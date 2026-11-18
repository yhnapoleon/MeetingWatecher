import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from http.server import HTTPServer,BaseHTTPRequestHandler
import threading

from meeting_eval.model_client import ModelClient
try:
    from meeting_eval.stage_runner import run_stage
except ImportError:
    run_stage=None


class ResponseClassificationTests(unittest.TestCase):
    def test_slow_http_error_body_obeys_absolute_request_deadline(self):
        import time
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(429);self.send_header('Content-Length','30');self.end_headers()
                try:
                    for _ in range(30):self.wfile.write(b'x');self.wfile.flush();time.sleep(.05)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash',f'http://127.0.0.1:{server.server_port}')):
                start=time.monotonic()
                with self.assertRaises(ValueError) as failure:ModelClient(None,tmp).call('JSON',{},'probe',deadline_seconds=.2)
                self.assertEqual(failure.exception.kind,'transport_failed')
                self.assertLess(time.monotonic()-start,.8)
        finally:server.shutdown();server.server_close();thread.join()

    def test_truncated_content_length_response_is_transport_failure(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Length','200');self.end_headers()
                self.wfile.write(b'{"choices": [');self.wfile.flush();self.close_connection=True
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash',f'http://127.0.0.1:{server.server_port}')):
                with self.assertRaises(ValueError) as failure:ModelClient(None,tmp).call('JSON',{},'probe',deadline_seconds=2)
                self.assertEqual(getattr(failure.exception,'kind',None),'transport_failed')
                self.assertTrue(json.loads(next(Path(tmp).rglob('meta.json')).read_text())['usage_unknown'])
        finally:server.shutdown();server.server_close();thread.join()

    def test_wire_contract_is_single_and_provider_error_is_redacted(self):
        import urllib.error
        schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}
        for strict in (False,True):
            with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret-key','deepseek-flash','https://api.deepseek.com/chat/completions')):
                client=ModelClient(None,tmp)
                error=urllib.error.HTTPError(client.endpoint,400,'Bad request',{},io.BytesIO(b'{"error":"secret-key invalid schema"}'))
                with patch('urllib.request.urlopen',side_effect=error) as network:
                    with self.assertRaises(ValueError) as failure:client.call('按输出契约返回结果',dict(output_schema=schema,output_contract='Output JSON'), 'check_work',strict_schema=schema if strict else None)
                self.assertEqual(failure.exception.kind,'terminal_error')
                body=json.loads(network.call_args[0][0].data);payload=json.loads(body['messages'][1]['content'])
                self.assertNotIn('output_contract',payload)
                self.assertEqual('output_schema' in payload,not strict)
                if not strict:self.assertIn('json',json.dumps(body['messages']).lower())
                meta=json.loads(next(Path(tmp).rglob('meta.json')).read_text())
                self.assertNotIn('secret-key',json.dumps(meta));self.assertIn('[REDACTED]',meta['provider_error'])

    def test_strict_fixed_empty_objects_are_program_owned(self):
        from meeting_eval.model_client import strict_tool_schema,restore_fixed_objects
        empty={'type':'object','properties':{},'required':[],'additionalProperties':False}
        source={'type':'object','properties':{'case_id':{'type':'string'},'checks':empty,
            'nested':{'type':'object','properties':{'issues':empty},'required':['issues'],'additionalProperties':False}},'required':['case_id','checks','nested'],'additionalProperties':False}
        wire=strict_tool_schema(source)
        self.assertEqual(list(wire['properties']),['case_id'])
        self.assertEqual(restore_fixed_objects({'case_id':'M'},source),{'case_id':'M','checks':{},'nested':{'issues':{}}})
        self.assertEqual(restore_fixed_objects({'checks':{'unexpected':1}},source)['checks'],{'unexpected':1})
    def test_strict_tool_recovery_uses_beta_and_validates_tool_identity(self):
        response=dict(choices=[dict(finish_reason='tool_calls',message=dict(content=None,tool_calls=[dict(type='function',function=dict(name='submit_result',arguments='{"ok":true}'))]))],usage={'total_tokens':4})
        schema={'type':'object','properties':{'ok':{'type':'boolean','example':True},'checks':{'type':'object','properties':{},'required':[],'additionalProperties':False}},'required':['ok','checks']}
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://api.deepseek.com/chat/completions')):
            client=ModelClient(None,tmp)
            with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as network:
                self.assertEqual(client.call('JSON',{},'check_work',strict_schema=schema),{'ok':True,'checks':{}})
            request=network.call_args[0][0]
            self.assertEqual(request.full_url,'https://api.deepseek.com/beta/chat/completions')
            body=json.loads(request.data)
            self.assertTrue(body['tools'][0]['function']['strict'])
            self.assertNotIn('response_format',body)
            self.assertNotIn('example',body['tools'][0]['function']['parameters']['properties']['ok'])
            response['choices'][0]['message']['tool_calls'][0]['function']['name']='wrong'
            with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
                with self.assertRaisesRegex(ValueError,'tool identity'):client.call('JSON',{'different':True},'check_work',strict_schema=schema)
    def test_cached_response_recovers_usage_without_meta(self):
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')):
            folder=Path(tmp)/'attempt';folder.mkdir()
            (folder/'response.json').write_text(json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content='{}'))],usage={'total_tokens':123})))
            ModelClient(None,tmp).call('JSON',{},'probe',attempt_dir=folder)
            self.assertEqual(json.loads((folder/'meta.json').read_text())['usage']['total_tokens'],123)

    def test_interrupted_chunked_response_is_transport_failure(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Transfer-Encoding','chunked');self.end_headers()
                self.wfile.write(b'10\r\nshort');self.wfile.flush();self.close_connection=True
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash',f'http://127.0.0.1:{server.server_port}')):
                try:ModelClient(None,tmp).call('JSON',{},'probe',deadline_seconds=2)
                except ValueError as exc:self.assertEqual(getattr(exc,'kind',None),'transport_failed')
                else:self.fail('Truncated transport accepted')
                self.assertTrue(json.loads(next(Path(tmp).rglob('meta.json')).read_text())['usage_unknown'])
        finally:server.shutdown();server.server_close();thread.join()
    def test_deadline_reader_accepts_complete_http_response(self):
        body=json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content='{"ok":true}'))],usage={'total_tokens':4})).encode()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash',f'http://127.0.0.1:{server.server_port}')):
                try:out=ModelClient(None,tmp).call('JSON',{},'probe',deadline_seconds=2)
                except Exception as exc:self.fail('A complete HTTP response must be accepted: '+repr(exc))
                self.assertEqual(out,{'ok':True})
        finally:server.shutdown();server.server_close();thread.join()
    def test_length_is_distinct_from_invalid_json_and_preserves_usage(self):
        for finish,content,kind in [('length','', 'budget_exhausted'),('stop','{"x":', 'syntax_invalid')]:
            response=dict(choices=[dict(finish_reason=finish,message=dict(content=content))],usage=dict(total_tokens=123))
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')):
                client=ModelClient(None,tmp)
                with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
                    try:client.call('JSON',{},'track_context')
                    except ValueError as exc:self.assertEqual(getattr(exc,'kind',None),kind)
                    else:self.fail('Invalid response was accepted')
                meta=json.loads(next(Path(tmp).rglob('meta.json')).read_text())
                self.assertEqual(meta['usage']['total_tokens'],123)
                self.assertEqual(meta['outcome'],kind)


class StageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(run_stage,'Bounded persistent stage runner is missing')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)

    def invoke(self,client):
        return run_stage(client,'Output JSON',dict(meeting={'case_id':'M'}),'track_context',
            lambda raw:raw['value'],self.folder,{'thinking':'enabled','reasoning_effort':'high','max_tokens':16384})

    def test_budget_recovery_preserves_payload_and_accepted_cache(self):
        from meeting_eval.model_client import ModelResponseError
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def __init__(self):self.calls=[]
            def call(self,prompt,payload,stage,**kwargs):
                self.calls.append((payload,kwargs))
                if len(self.calls)==1:raise ModelResponseError('length','budget_exhausted')
                return {'case_id':'M','value':{'complete':True}}
        client=Client();self.assertEqual(self.invoke(client),{'complete':True})
        self.assertEqual(self.invoke(client),{'complete':True})
        self.assertEqual(len(client.calls),2)
        self.assertEqual(client.calls[1][1]['inference']['max_tokens'],32768)
        self.assertEqual(client.calls[0][0],client.calls[1][0])
        state=json.loads(next(self.folder.rglob('state.json')).read_text())
        self.assertEqual([a['status'] for a in state['attempts']],['budget_exhausted','accepted'])

    def test_structure_recovery_uses_feedback_not_more_budget(self):
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def __init__(self):self.calls=[]
            def call(self,prompt,payload,stage,**kwargs):
                self.calls.append((payload,kwargs))
                if len(self.calls)==1:return {'case_id':'WRONG','value':0}
                return {'case_id':'M','value':2}
        client=Client();self.assertEqual(self.invoke(client),2)
        self.assertIn('validation_feedback',client.calls[1][0])
        self.assertEqual(client.calls[1][1]['inference']['max_tokens'],16384)

    def test_syntax_recovery_does_not_repeat_malformed_output(self):
        from meeting_eval.model_client import ModelResponseError
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def __init__(self):self.calls=[]
            def call(self,prompt,payload,stage,**kwargs):
                self.calls.append(payload)
                if len(self.calls)==1:raise ModelResponseError('bad JSON','syntax_invalid',{'raw_text':'{"rows":[{"x":"quoted } ["}}'})
                return {'case_id':'M','value':2}
        client=Client();self.assertEqual(self.invoke(client),2)
        feedback=client.calls[1]['validation_feedback']
        self.assertNotIn('previous_output',feedback)
        self.assertIn('close that container with ]',feedback['error'])

    def test_structural_recovery_uses_strict_schema_once(self):
        from meeting_eval.model_client import ModelResponseError
        class Client:
            model='deepseek-flash';endpoint='https://api.deepseek.com/chat/completions'
            def __init__(self):self.calls=[]
            def call(self,*args,**kwargs):
                self.calls.append(kwargs)
                if len(self.calls)==1:raise ModelResponseError('bad','syntax_invalid')
                return {'ok':True}
        client=Client();schema={'type':'object','properties':{'ok':{'type':'boolean'}}}
        self.assertEqual(run_stage(client,'JSON',{'output_schema':schema},'probe',lambda x:x,self.folder,{'thinking':'enabled','reasoning_effort':'high','max_tokens':16384}),{'ok':True})
        self.assertNotIn('strict_schema',client.calls[0])
        self.assertEqual(client.calls[1]['strict_schema'],schema)
        self.assertEqual(client.calls[1]['inference'],{'thinking':'disabled','temperature':0,'max_tokens':16384})

    def test_proxy_endpoint_keeps_json_recovery(self):
        from meeting_eval.model_client import ModelResponseError
        class Client:
            model='deepseek-flash';endpoint='https://proxy.invalid/my-prefix/chat/completions'
            def __init__(self):self.calls=[]
            def call(self,*args,**kwargs):
                self.calls.append(kwargs)
                if len(self.calls)==1:raise ModelResponseError('bad','syntax_invalid')
                return {'ok':True}
        client=Client()
        run_stage(client,'JSON',{'output_schema':{'type':'object'}},'probe',lambda x:x,self.folder,{})
        self.assertNotIn('strict_schema',client.calls[1])

    def test_rate_limit_cooldown_defers_without_spending_second_attempt(self):
        import time
        from meeting_eval.model_client import ModelResponseError
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def __init__(self):self.calls=0
            def call(self,*args,**kwargs):
                self.calls+=1
                if self.calls==1:
                    exc=ModelResponseError('429','transport_failed');exc.retry_at=time.time()+120;raise exc
                return {'case_id':'M','value':3}
        client=Client()
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'cooldown'):self.invoke(client)
        self.assertEqual(client.calls,1)
        p=next(self.folder.rglob('state.json'));state=json.loads(p.read_text());state['attempts'][0]['retry_at']=0;p.write_text(json.dumps(state))
        self.assertEqual(self.invoke(client),3);self.assertEqual(client.calls,2)

    def test_crash_after_failure_meta_preserves_terminal_and_cooldown(self):
        import time
        for outcome in ('terminal_error','transport_failed'):
            with self.subTest(outcome=outcome):
                class Client:
                    model='deepseek-flash';endpoint='https://example.invalid/'+outcome
                    def __init__(self):self.calls=0
                    def call(self,*args,**kwargs):
                        self.calls+=1;folder=kwargs['attempt_dir'];folder.mkdir(exist_ok=True)
                        (folder/'meta.json').write_text(json.dumps(dict(outcome=outcome,retry_at=time.time()+120,usage_unknown=True,http_status=402 if outcome=='terminal_error' else 429)))
                        raise KeyboardInterrupt('Simulated crash after metadata commit')
                client=Client()
                with self.assertRaises(KeyboardInterrupt):self.invoke(client)
                with self.assertRaises(ValueError):self.invoke(client)
                self.assertEqual(client.calls,1)

    def test_exhaustion_persists_across_reentry(self):
        from meeting_eval.model_client import ModelResponseError
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def __init__(self):self.calls=0
            def call(self,*args,**kwargs):
                self.calls+=1;raise ModelResponseError('length','budget_exhausted')
        client=Client()
        for _ in range(3):
            with self.assertRaisesRegex(ValueError,'exhausted'):self.invoke(client)
        self.assertEqual(client.calls,2)

    def test_damaged_accepted_is_rebuilt_without_new_request(self):
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def __init__(self):self.calls=0
            def call(self,*args,**kwargs):self.calls+=1;return {'case_id':'M','value':{'complete':True}}
        client=Client();self.invoke(client)
        next(self.folder.rglob('accepted.json')).write_text('{')
        self.assertEqual(self.invoke(client),{'complete':True})
        self.assertEqual(client.calls,1)

    def test_budget_change_does_not_reset_attempts_or_accepted_ancestors(self):
        from meeting_eval.model_client import ModelResponseError
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def __init__(self):self.calls=0
            def call(self,*args,**kwargs):self.calls+=1;raise ModelResponseError('bad','syntax_invalid')
        client=Client()
        for budget in (16384,32768):
            with self.assertRaisesRegex(ValueError,'exhausted'):
                run_stage(client,'JSON',{},'probe',lambda x:x,self.folder,{'max_tokens':budget})
        self.assertEqual(client.calls,2)

    def test_service_accepts_only_budget_change_for_v5(self):
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        from meeting_eval.stage_runner import semantic_config
        with patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')):
            a=Extractor(None,self.folder/'model','context-v5',inference_config={'track_context':{'max_tokens':16384}})
            b=Extractor(None,self.folder/'model','context-v5',inference_config={'track_context':{'max_tokens':32768}})
            self.assertEqual(semantic_config(a.config),semantic_config(b.config))
            default=Extractor(None,self.folder/'model','context-v5')
            self.assertEqual(semantic_config(default.config),semantic_config(b.config))
            store=Store(self.folder/'state.sqlite')
            try:
                Service(store,default);Service(store,a);Service(store,b)
                b.config['model']='changed-model'
                with self.assertRaisesRegex(ValueError,'configuration changed'):Service(store,b)
            finally:store.db.close()


if __name__=='__main__':unittest.main()
