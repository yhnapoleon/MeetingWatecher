import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meeting_eval.model_client import ModelClient


class InferenceTests(unittest.TestCase):
    def test_explicit_low_is_sent_and_does_not_reuse_high(self):
        response = {'choices':[{'finish_reason':'stop','message':{'content':'{"items":[]}'}}]}
        with tempfile.TemporaryDirectory() as tmp, patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')):
            client = ModelClient(None,tmp)
            with patch('urllib.request.urlopen',side_effect=lambda *a,**kw:io.BytesIO(json.dumps(response).encode())) as remote:
                for effort in ('high','low','low'):
                    client.call('JSON',{},'interpret_work',inference={'thinking':'enabled','reasoning_effort':effort,'max_tokens':32768})
            self.assertEqual(remote.call_count,2)
            requests=[json.loads(p.read_text()) for p in Path(tmp).rglob('request.json')]
            self.assertEqual({r['reasoning_effort'] for r in requests},{'high','low'})
            self.assertTrue(all(r['max_tokens']==32768 for r in requests))

    def test_low_requires_enabled_deepseek(self):
        from meeting_eval.model_client import inference_parameters
        for model,mode in [('deepseek-flash','disabled'),('other-model','enabled')]:
            with self.subTest(model=model,mode=mode),self.assertRaises(ValueError):
                inference_parameters(model,32768,{'thinking':mode,'reasoning_effort':'low'})

    def test_thinking_changes_request_and_cache_without_repeating_saved_call(self):
        response = {'choices':[{'finish_reason':'stop','message':{'content':'{"items":[]}'}}]}
        with tempfile.TemporaryDirectory() as tmp, patch('meeting_eval.model_client.credentials',return_value=('secret-key','deepseek-flash','https://example.invalid')):
            client = ModelClient(None,tmp)
            def send(*args,**kwargs):
                return io.BytesIO(json.dumps(response).encode())
            with patch('urllib.request.urlopen',side_effect=send) as remote:
                client.call('p',{},'actions')
                client.call('p',{},'actions',inference={'thinking':'enabled','reasoning_effort':'high','max_tokens':8192})
                client.call('p',{},'actions',inference={'thinking':'enabled','reasoning_effort':'high','max_tokens':8192})
            self.assertEqual(remote.call_count,2)
            requests = [json.loads(p.read_text()) for p in Path(tmp).rglob('request.json')]
            self.assertEqual(len(requests),2)
            active = next(r for r in requests if r['thinking']['type']=='enabled')
            self.assertEqual((active['temperature'],active['max_tokens'],active['reasoning_effort']),(1,8192,'high'))
            self.assertNotIn('secret-key',json.dumps(requests))

    def test_unsupported_or_inconsistent_settings_fail_before_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch('meeting_eval.model_client.credentials',return_value=('secret','other-model','https://example.invalid')):
            client = ModelClient(None,tmp)
            with self.assertRaisesRegex(ValueError,'DeepSeek'):
                client.call('p',{},'actions',inference={'thinking':'enabled'})
            client.model='deepseek-flash'
            for settings in ({'thinking':'enabled','temperature':0},{'max_tokens':-1},{'typo':'high'}):
                with self.subTest(settings=settings),self.assertRaises(ValueError):
                    client.call('p',{},'actions',inference=settings)

    def test_configuration_is_part_of_extractor_database_identity(self):
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        with tempfile.TemporaryDirectory() as tmp, patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')):
            first=Extractor(None,Path(tmp)/'model','actions')
            second=Extractor(None,Path(tmp)/'model','actions',inference_config={'actions':{'thinking':'enabled'}})
            store=Store(Path(tmp)/'state.sqlite')
            try:
                Service(store,first)
                with self.assertRaisesRegex(ValueError,'configuration changed'):
                    Service(store,second)
            finally:
                store.close()


if __name__=='__main__':
    unittest.main()
