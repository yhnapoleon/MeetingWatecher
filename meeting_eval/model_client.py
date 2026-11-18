"""A recorded JSON call; credentials never enter saved artifacts."""
import json
import io
import http.client
from email.utils import parsedate_to_datetime
from pathlib import Path
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit,urlunsplit

from scripts.run_action_baseline import credentials, write_json
from .inputs import digest, dumps
from .check_transport import unique_json


class ModelResponseError(ValueError):
    def __init__(self,message,kind,previous_output=None):
        super().__init__(message)
        self.kind=kind
        self.previous_output=previous_output
        self.retry_at=None


def read_response(stream,deadline):
    """Bound socket reads by the remaining wall-clock allowance."""
    chunks=[]
    while True:
        if stream.isclosed():break
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Model request deadline exceeded')
        # urllib HTTP(S) exposes the underlying socket through its buffered reader.
        stream.fp.raw._sock.settimeout(remaining)
        chunk=stream.read1(65536)
        if not chunk:break
        chunks.append(chunk)
    if time.monotonic()>deadline:raise TimeoutError('Model request deadline exceeded')
    # read1() permits premature EOF for a Content-Length body (unlike read()).
    if getattr(stream,'length',None):raise http.client.IncompleteRead(b''.join(chunks),stream.length)
    return json.loads(b''.join(chunks))


def read_error_body(error,deadline):
    """Diagnostics use the same absolute deadline, never an unbounded read()."""
    stream=error.fp
    if isinstance(stream,io.BytesIO):return stream.read(8192)
    if not isinstance(stream,http.client.HTTPResponse):return b''
    chunks=[];size=0
    while size<8192 and not stream.isclosed():
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        stream.fp.raw._sock.settimeout(remaining)
        chunk=stream.read1(8192-size)
        if not chunk:break
        chunks.append(chunk);size+=len(chunk)
    return b''.join(chunks)


def inference_parameters(model, max_tokens, inference=None):
    params = dict(model=model,temperature=0,max_tokens=max_tokens,
                  response_format={'type':'json_object'},stream=False)
    if model.startswith('deepseek'):
        params['thinking'] = {'type':'disabled'}
    if inference is None:
        return params
    if not isinstance(inference,dict) or set(inference)-{'thinking','reasoning_effort','temperature','max_tokens'}:
        raise ValueError('Unsupported inference configuration')
    if 'thinking' in inference or 'reasoning_effort' in inference:
        if not model.startswith('deepseek'):
            raise ValueError('Explicit thinking configuration currently supports DeepSeek only')
    mode = inference.get('thinking','disabled')
    if mode not in ('enabled','disabled'):
        raise ValueError('Invalid thinking mode')
    temperature = inference.get('temperature',1 if mode=='enabled' else 0)
    if type(temperature) not in (int,float) or not 0 <= temperature <= 2 or mode=='enabled' and temperature!=1:
        raise ValueError('Invalid temperature for thinking mode')
    budget = inference.get('max_tokens',max_tokens)
    if type(budget) is not int or budget <= 0:
        raise ValueError('Invalid max_tokens')
    params.update(temperature=temperature,max_tokens=budget)
    if model.startswith('deepseek'):
        params['thinking'] = {'type':mode}
    if 'reasoning_effort' in inference:
        if mode!='enabled' or inference['reasoning_effort'] not in ('low','high','max'):
            raise ValueError('Invalid reasoning_effort')
        params['reasoning_effort'] = inference['reasoning_effort']
    return params


def fixed_object(node):
    if node.get('type')!='object' or node.get('additionalProperties') is not False:return False,None
    value={}
    for key,child in node.get('properties',{}).items():
        fixed,item=fixed_object(child)
        if not fixed:return False,None
        value[key]=item
    return True,value


def restore_fixed_objects(value,node):
    """Restore only schema-determined empty objects, never a semantic prediction."""
    if isinstance(value,dict) and node.get('type')=='object':
        value=dict(value)
        for key,child in node.get('properties',{}).items():
            fixed,item=fixed_object(child)
            if key not in value and fixed:value[key]=item
            elif key in value:value[key]=restore_fixed_objects(value[key],child)
    elif isinstance(value,list) and node.get('type')=='array':
        value=[restore_fixed_objects(item,node['items']) for item in value]
    return value


def strict_tool_schema(node):
    """Provider-supported subset; original local validation remains authoritative."""
    keep={'type','properties','required','additionalProperties','items','enum','anyOf','description'}
    out={k:v for k,v in node.items() if k in keep}
    if 'properties' in out:
        out['properties']={k:strict_tool_schema(v) for k,v in out['properties'].items() if not fixed_object(v)[0]}
        out['required']=list(out['properties']);out['additionalProperties']=False
    if 'items' in out:out['items']=strict_tool_schema(out['items'])
    if 'anyOf' in out:out['anyOf']=[strict_tool_schema(v) for v in out['anyOf']]
    return out


def supports_strict_recovery(model,endpoint):
    parts=urlsplit(endpoint)
    return model.startswith('deepseek') and parts.scheme=='https' and parts.hostname=='api.deepseek.com' and parts.path in ('/chat/completions','/v1/chat/completions','/beta/chat/completions')


class ModelClient:
    def __init__(self, env_file, out):
        self.key,self.model,self.endpoint = credentials(env_file)
        self.out = Path(out)
        self.out.mkdir(parents=True,exist_ok=True)

    def call(self,prompt,payload,stage,max_tokens=6000,fresh=False,*,inference=None,attempt_dir=None,deadline_seconds=None,strict_schema=None):
        params = inference_parameters(self.model,max_tokens,inference)
        endpoint=self.endpoint
        if strict_schema is not None:
            if not supports_strict_recovery(self.model,endpoint):raise ValueError('Strict recovery requires the supported official DeepSeek endpoint')
            parts=urlsplit(endpoint);endpoint=urlunsplit((parts.scheme,parts.netloc,'/beta/chat/completions','',''))
            params.pop('response_format',None);params.pop('reasoning_effort',None)
            params.update(thinking={'type':'disabled'},temperature=0,
                tools=[dict(type='function',function=dict(name='submit_result',description='Submit the complete validated stage result.',strict=True,parameters=strict_tool_schema(strict_schema)))],
                tool_choice=dict(type='function',function={'name':'submit_result'}))
            prompt+='\n本次通过 submit_result 工具提交结果，不在普通 content 返回 JSON。严格按工具参数结构输出。工具schema省略的固定空object字段由程序恢复，不要自行添加这些字段；其他内容须完整保留。'
        wire_payload=dict(payload)
        if 'output_schema' in wire_payload:wire_payload.pop('output_contract',None)
        if strict_schema is not None:wire_payload.pop('output_schema',None)
        elif 'json' not in (prompt+dumps(wire_payload)).lower():
            prompt+='\n请仅返回一个完整 JSON object，遵守给定输出契约。'
        request = {**params,'messages':[{'role':'system','content':prompt},
                                       {'role':'user','content':dumps(wire_payload)}]}
        key = digest({'endpoint':endpoint,'request':request})
        folder = Path(attempt_dir) if attempt_dir is not None else self.out/key
        folder.mkdir(exist_ok=True)
        retries = sorted(folder.glob('retry-*'))
        latest = retries[-1] if retries else folder
        if attempt_dir is None and (fresh or ((latest/'meta.json').exists() and not (latest/'response.json').exists())):
            folder = folder/f'retry-{len(retries)+1:04d}'
            folder.mkdir()
        elif attempt_dir is None:
            folder = latest
        write_json(folder/'request.json',request)
        response_file = folder/'response.json'
        if response_file.exists():
            response = json.loads(response_file.read_text(encoding='utf-8'))
            meta=json.loads((folder/'meta.json').read_text(encoding='utf8')) if (folder/'meta.json').exists() else dict(stage=stage,status='received')
        else:
            meta = dict(stage=stage,model=self.model,endpoint=endpoint,status='failed',output_mode='strict_tool' if strict_schema is not None else 'json_content')
            start = time.perf_counter()
            try:
                req = urllib.request.Request(endpoint,data=dumps(request).encode('utf-8'),
                    headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'})
                deadline=time.monotonic()+deadline_seconds if deadline_seconds else None
                with urllib.request.urlopen(req,timeout=min(90,deadline_seconds) if deadline_seconds else 90) as stream:
                    response = read_response(stream,deadline) if deadline else json.load(stream)
                write_json(response_file,response)
                meta.update(status='received',usage=response.get('usage'),
                            model_returned=response.get('model'),fingerprint=response.get('system_fingerprint'))
            except (urllib.error.URLError,TimeoutError,ConnectionError,http.client.HTTPException,json.JSONDecodeError) as exc:
                meta['error_type'] = type(exc).__name__
                code=getattr(exc,'code',None)
                kind='transport_failed' if code is None or code in (408,429,500,502,503,504) else 'terminal_error'
                meta.update(outcome=kind,usage_unknown=True,http_status=code)
                if isinstance(exc,urllib.error.HTTPError):
                    try:
                        body=read_error_body(exc,deadline or time.monotonic()+5).decode('utf8',errors='replace')
                        meta['provider_error']=body.replace(self.key,'[REDACTED]')[:4000]
                    except (OSError,http.client.HTTPException):pass
                    finally:exc.close()
                error=ModelResponseError(str(exc),kind)
                if code in (429,503):
                    header=exc.headers.get('Retry-After') if exc.headers else None
                    try:retry_at=time.time()+max(0,float(header))
                    except (TypeError,ValueError):
                        try:retry_at=parsedate_to_datetime(header).timestamp()
                        except (TypeError,ValueError,AttributeError):retry_at=time.time()+(30 if code==429 else 1)
                    error.retry_at=retry_at;meta['retry_at']=retry_at
                raise error from exc
            finally:
                meta['duration_seconds'] = round(time.perf_counter()-start,3)
                write_json(folder/'meta.json',meta)
        meta.update(usage=response.get('usage'),usage_unknown=response.get('usage') is None,
                    model_returned=response.get('model'),fingerprint=response.get('system_fingerprint'))
        try:
            choice=response['choices'][0];finish=choice['finish_reason']
            previous=dict(raw_text=choice['message'].get('content'),finish_reason=finish)
            meta['finish_reason']=finish
            expected_finish='tool_calls' if strict_schema is not None else 'stop'
            if finish!=expected_finish:
                raise ModelResponseError('Incomplete model response: '+finish,
                    'budget_exhausted' if finish=='length' else 'terminal_error',previous)
            content=choice['message'].get('content') or ''
            if strict_schema is not None:
                calls=choice['message'].get('tool_calls',[])
                if len(calls)!=1 or calls[0].get('type')!='function' or calls[0].get('function',{}).get('name')!='submit_result':
                    raise ModelResponseError('Invalid strict tool identity','schema_invalid',previous)
                content=calls[0]['function']['arguments'];previous['raw_text']=content
            try:value=unique_json(content)
            except ValueError as exc:raise ModelResponseError('Invalid JSON: '+str(exc),'syntax_invalid',previous) from exc
            if not isinstance(value,dict):raise ModelResponseError('Model response must be an object','schema_invalid',previous)
            if strict_schema is not None:value=restore_fixed_objects(value,strict_schema)
            meta['outcome']='parsed'
            return value
        except ModelResponseError as exc:
            meta['outcome']=exc.kind
            raise
        finally:
            write_json(folder/'meta.json',meta)
