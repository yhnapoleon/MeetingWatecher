"""Persistent, bounded technical recovery; semantic verdicts are not retries."""
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import json
import os
from pathlib import Path
import time

from .inputs import digest
from .model_client import ModelResponseError,supports_strict_recovery


def semantic_config(value):
    """Budget is attempt metadata; every other configuration change invalidates reuse."""
    if isinstance(value,dict):
        result={k:semantic_config(v) for k,v in value.items() if k!='max_tokens'}
        if isinstance(result.get('inference'),dict):
            result['inference']={k:v for k,v in result['inference'].items() if v!={}}
            if not result['inference']:result.pop('inference')
        return result
    if isinstance(value,list):return [semantic_config(v) for v in value]
    return value


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    os.replace(temp,path)


def delimiter_hint(text):
    """Diagnose delimiters outside strings, without modifying candidate content."""
    stack=[];quoted=False;escaped=False
    for i,c in enumerate(text):
        if quoted:
            if escaped:escaped=False
            elif c=='\\':escaped=True
            elif c=='"':quoted=False
            continue
        if c=='"':quoted=True
        elif c in '{[':stack.append((c,i))
        elif c in '}]':
            if not stack:return f'Unexpected closing {c} at position {i}.'
            if stack[-1][0]!={'}':'{',']':'['}[c]:
                return f'At position {i}, closing {c} conflicts with opener {stack[-1][0]} at {stack[-1][1]}; close that container with '+{'{':'}','[':']'}[stack[-1][0]]+' first.'
            stack.pop()
    if stack:return 'Unclosed containers at end: '+repr(stack)+'. Close each object/array separately in reverse nesting order.'
    return 'Check commas, keys and string escaping against the full output schema.'


RECOVERY_GRANT=ContextVar('stage_recovery_grant',default=None)


@contextmanager
def recovery_scope(grant):
    token=RECOVERY_GRANT.set(grant)
    try:yield
    finally:RECOVERY_GRANT.reset(token)


@contextmanager
def node_lock(path,node_id,stage):
    """Nonblocking OS lock; process death releases it without stale-lock recovery."""
    with (path/'node.lock').open('a+b') as handle:
        handle.seek(0,2)
        if not handle.tell():handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            error=ModelResponseError('Stage already running','stage_busy')
            error.recovery=dict(node_id=node_id,stage=stage,status='waiting_retry',reason='stage_busy')
            raise error from exc
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def run_stage(client,prompt,payload,stage,validate,folder,inference,*,require_case_id=True,recovery_grant=None,reference_repair=None):
    identity=dict(payload=payload,prompt=prompt,inference=semantic_config(inference),model=client.model,
                  endpoint=client.endpoint,runner=2,require_case_id=require_case_id)
    if reference_repair is not None:identity['reference_repair']=reference_repair.protocol
    node_id=digest(identity)
    path=Path(folder)/stage/node_id;path.mkdir(parents=True,exist_ok=True)
    with node_lock(path,node_id,stage):
        return _run_stage(client,prompt,payload,stage,validate,path,inference,require_case_id,
                          recovery_grant if recovery_grant is not None else RECOVERY_GRANT.get(),reference_repair)


def _run_stage(client,prompt,payload,stage,validate,path,settings,require_case_id,grant,reference_repair=None):
    from .check_transport import normalize_check_output
    accepted=path/'accepted.json';state_path=path/'state.json'
    state=json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else dict(attempts=[])

    def save():
        attempts=state['attempts']
        state.update(node_id=path.name,stage=stage,request_count=len(attempts),
            content_attempts=max((a['generation'] for a in attempts),default=0),
            transport_retries=sum(a.get('transport_retry',False) for a in attempts),
            charged_request_seconds=round(sum(a.get('charged_seconds',0) for a in attempts),3))
        atomic_json(state_path,state)

    def stop(status,message,kind=None):
        state['status']=status;save()
        last=state['attempts'][-1] if state['attempts'] else {}
        error=ModelResponseError(message,kind or last.get('status','terminal_error'))
        error.retry_at=last.get('retry_at')
        error.recovery={k:state[k] for k in ('node_id','stage','status','request_count','content_attempts','transport_retries','charged_request_seconds')}
        error.recovery.update(reason=error.kind,retry_at=error.retry_at,manual_grant_used=bool(state.get('manual_grant')))
        raise error

    def accept(raw,attempt,candidate='raw.json'):
        if attempt.get('reference_patch') and candidate!='merged.json':
            request=json.loads((path/attempt['directory']/'stage-request.json').read_text(encoding='utf8'))
            raw=reference_repair.merge(raw,request)
            candidate='merged.json';atomic_json(path/attempt['directory']/candidate,raw)
        expected=payload.get('meeting',{}).get('case_id')
        if require_case_id and expected is not None and (not isinstance(raw,dict) or raw.get('case_id')!=expected):raise ValueError('Wrong case_id')
        value=validate(raw)
        # Commit the validated candidate pointer first; a crash can rebuild accepted.
        attempt.update(status='accepted',candidate_file=candidate);state['status']='accepted';save()
        atomic_json(accepted,dict(value=value,hash=digest(value)))
        return value

    def normalize(attempt):
        if stage not in ('check_work','check_repair'):return None
        previous=attempt.get('previous_output') or {}
        if previous.get('finish_reason') not in ('stop','tool_calls'):return None
        normalized=normalize_check_output(previous.get('raw_text') or '',payload.get('output_schema',{}))
        if normalized is None:return None
        ap=path/attempt['directory']
        atomic_json(ap/'normalized.json',normalized['value'])
        atomic_json(ap/'normalization.json',normalized['normalization'])
        try:return (True,accept(normalized['value'],attempt,'normalized.json'))
        except (ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:
            attempt['normalization_rejected']=str(exc)[:2000];save()
            return None

    def record_failure(exc,attempt,raw):
        attempt.update(status=getattr(exc,'kind','schema_invalid'),error=type(exc).__name__+': '+str(exc)[:2000],
                       previous_output=getattr(exc,'previous_output',None) if raw is None else raw,retry_at=getattr(exc,'retry_at',None))
        from .context_wire import ReferenceValidationError
        if isinstance(exc,ReferenceValidationError):
            atomic_json(path/attempt['directory']/'reference-issues.json',exc.issues)
            attempt['validation_feedback']=exc.feedback(payload['meeting'])
        # Schema failure still needs the original text and finish marker, including duplicate-key detection.
        response_file=path/attempt['directory']/'response.json'
        if raw is not None and response_file.exists():
            response=json.loads(response_file.read_text(encoding='utf8'));choice=response['choices'][0]
            message=choice['message'];text=message.get('content')
            if attempt['output_mode']=='strict_tool':text=message['tool_calls'][0]['function']['arguments']
            attempt['previous_output']=dict(raw_text=text,finish_reason=choice['finish_reason'])
        save()

    def consume(attempt,cached=False):
        ap=path/attempt['directory'];raw=None
        request=json.loads((ap/'stage-request.json').read_text(encoding='utf8'))
        mode={'strict_schema':request['output_schema']} if attempt['output_mode']=='strict_tool' else {}
        start=time.monotonic()
        try:
            try:
                actual_prompt=reference_repair.prompt if attempt.get('reference_patch') else prompt
                raw=client.call(actual_prompt,request,stage,inference=attempt['inference'],attempt_dir=ap,
                                deadline_seconds=attempt['reserved_seconds'],**mode)
            except ModelResponseError as exc:record_failure(exc,attempt,None)
            except Exception as exc:
                # Unexpected client/programming errors are visible, never format retries.
                record_failure(ModelResponseError(type(exc).__name__+': '+str(exc),'terminal_error'),attempt,None)
            else:
                atomic_json(ap/'raw.json',raw)
                try:
                    # Settle before committing acceptance, so cached success retains actual time.
                    if not cached:attempt['charged_seconds']=time.monotonic()-start
                    return (True,accept(raw,attempt))
                except (ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:record_failure(exc,attempt,raw)
        except BaseException:
            # Interrupts leave the pre-request reservation intact unless a response was received.
            raise
        if not cached:attempt['charged_seconds']=time.monotonic()-start
        save()
        return normalize(attempt)

    if accepted.exists():
        try:
            saved=json.loads(accepted.read_text(encoding='utf8'))
            if saved['hash']==digest(saved['value']):return saved['value']
        except (ValueError,KeyError,TypeError):pass
        accepted.replace(path/'accepted-damaged.json')
    if state['attempts']:
        last=state['attempts'][-1];ap=path/last['directory']
        candidate=last.get('candidate_file','raw.json');raw_path=ap/candidate
        if last['status']=='accepted' and raw_path.exists():return accept(json.loads(raw_path.read_text(encoding='utf8')),last,candidate)
        if last['status']=='started':
            meta_path=ap/'meta.json'
            meta=json.loads(meta_path.read_text(encoding='utf8')) if meta_path.exists() else {}
            if isinstance(meta.get('duration_seconds'),(int,float)):
                last['charged_seconds']=max(0,meta['duration_seconds'])
            if (ap/'response.json').exists():
                result=consume(last,cached=True)
                if result:return result[1]
            elif raw_path.exists():
                try:return accept(json.loads(raw_path.read_text(encoding='utf8')),last,candidate)
                except (ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:record_failure(exc,last,None)
            else:
                last.update(status=meta.get('outcome','transport_failed'),error='Interrupted request; recorded HTTP status '+str(meta.get('http_status')),
                            usage_unknown=meta.get('usage') is None,retry_at=meta.get('retry_at'))
            save()
        if last['status'] in ('syntax_invalid','schema_invalid'):
            result=normalize(last)
            if result:return result[1]

    # A persisted per-node authorization adds one generation and one transport retry.
    if state.get('status')=='recovery_required' and grant and path.name in grant and not state.get('manual_grant'):
        state['manual_grant']=dict(retry_id=grant[path.name],base_requests=len(state['attempts']),
            content_limit=state['content_attempts']+1,transport_limit=state['transport_retries']+1)
        save()
    manual=state.get('manual_grant')
    request_limit=min(6,manual['base_requests']+2) if manual else 4
    content_limit=manual['content_limit'] if manual else 2
    transport_limit=manual['transport_limit'] if manual else 2
    retryable={'budget_exhausted','syntax_invalid','schema_invalid','transport_failed'}
    while True:
        save();last=state['attempts'][-1] if state['attempts'] else None
        if last and last['status'] not in retryable:
            stop('terminal_error','Stage terminal error: '+last.get('error','Missing accepted candidate'))
        transport=bool(last and last['status']=='transport_failed')
        patch_request=None
        if (reference_repair is not None and last and last['status']=='schema_invalid'
                and not any(a.get('reference_patch') for a in state['attempts'])):
            raw_file=path/last['directory']/'raw.json'
            if raw_file.exists():patch_request=reference_repair.prepare(json.loads(raw_file.read_text(encoding='utf8')),payload)
        generation=(last['generation']+(not transport)) if last else 1
        # At most one extra generation, only for a grounded reference patch.
        patch_transport=transport and last.get('reference_patch',False)
        active_limit=max(content_limit,3) if patch_request is not None or patch_transport else content_limit
        exhausted=(len(state['attempts'])>=request_limit or generation>active_limit or
            transport and state['transport_retries']>=transport_limit or state['charged_request_seconds']>=600)
        if last and last.get('reference_patch') and not transport:exhausted=True
        if last and last['status']=='budget_exhausted' and last['inference'].get('max_tokens',6000)>=32768:
            exhausted=exhausted or not (manual and len(state['attempts'])==manual['base_requests'])
        if exhausted:stop('recovery_required','Stage recovery exhausted: '+last['error'])
        if transport:
            remaining=max(0,(last.get('retry_at') if last.get('retry_at') is not None else time.time()+1)-time.time())
            if remaining>60:stop('waiting_retry','Provider cooldown; retry after '+str(last['retry_at']))
            time.sleep(remaining)
        request=copy.deepcopy(payload);actual=copy.deepcopy(settings);mode={}
        if transport:
            # A transport retry repeats the same generation, feedback and output mode.
            request=json.loads((path/last['directory']/'stage-request.json').read_text(encoding='utf8'))
            actual=copy.deepcopy(last['inference'])
            if last['output_mode']=='strict_tool':mode['strict_schema']=request['output_schema']
        elif patch_request is not None:
            request=patch_request;actual=dict(thinking='disabled',temperature=0,max_tokens=8192)
            if supports_strict_recovery(client.model,client.endpoint):mode['strict_schema']=request['output_schema']
        elif last:
            actual=copy.deepcopy(last['inference'])
            if last['status']=='budget_exhausted':actual['max_tokens']=32768
            elif last['status']=='syntax_invalid':
                previous=last.get('previous_output') or {}
                request['validation_feedback']=dict(error=last['error']+' '+delimiter_hint(previous.get('raw_text') or ''),
                    instruction='重新生成完整 JSON。逐层关闭每一个 object 和 array。保持原文含义，完整满足输出契约。')
            elif last['status']=='schema_invalid':
                request['validation_feedback']=last.get('validation_feedback') or dict(error=last['error'],
                    instruction='修复所列结构/证据错误，保持原文含义和给定身份，完整满足输出契约。')
            if last['status'] in ('syntax_invalid','schema_invalid') and 'output_schema' in request and supports_strict_recovery(client.model,client.endpoint):
                mode['strict_schema']=request['output_schema'];actual.update(thinking='disabled',temperature=0);actual.pop('reasoning_effort',None)
        allowance=min(300,600-state['charged_request_seconds'])
        attempt=dict(directory='attempt-'+str(len(state['attempts'])+1),status='started',inference=actual,
            output_mode='strict_tool' if mode else 'json_content',generation=generation,transport_retry=transport,
            reserved_seconds=allowance,charged_seconds=allowance)
        if patch_request is not None or patch_transport:attempt['reference_patch']=True
        # Write logical request before reservation; no HTTP is possible before state commit.
        atomic_json(path/attempt['directory']/'stage-request.json',request)
        state['attempts'].append(attempt);state['status']='running';save()
        result=consume(attempt)
        if result:return result[1]


