"""Offline regression tests for full model streaming and strict JSON proposals."""
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from erp_bar.runtime.model_json import parse_model_object
from erp_bar.runtime.model_stream import GenerationStream
from erp_bar.runtime.events import event_sink, observed_model, agent_scope
from erp_bar.agent_view.server import Session, run_demo

REPLY = '{"action":"SEARCH_PRODUCT","arguments":{},"reason":"Product identity is not yet verified."}'


class JsonBoundaryTests(unittest.TestCase):
    def test_plain_and_fenced_response(self):
        for response in [REPLY, '\n'+REPLY+'\n', '```json\n'+REPLY+'\n```']:
            self.assertEqual(parse_model_object(response)['action'], 'SEARCH_PRODUCT')

    def test_thinking_is_separate_from_json_even_when_it_contains_json(self):
        for response in ['<think>{"action":"WRONG"}</think>'+REPLY,
                         REPLY+'\n<think>model reflection</think>',
                         '<think>before</think>```json\n'+REPLY+'\n```\n<think>after</think>']:
            self.assertEqual(parse_model_object(response)['action'],'SEARCH_PRODUCT')

    def test_extra_data_is_rejected_not_silently_executed(self):
        for tail in ['\nHere is my explanation.', '\n'+REPLY, '\n{"action":"CREATE_PRODUCT"}']:
            with self.assertRaisesRegex(ValueError,'exactly one JSON object'):
                parse_model_object(REPLY+tail)

    def test_duplicate_keys_and_incomplete_objects_are_rejected(self):
        for text in ['{"action":"READ","action":"WRITE"}', '<think>unfinished', REPLY[:-1], '[]', '"text"']:
            with self.assertRaises(ValueError):parse_model_object(text)

    def test_braces_and_think_tags_inside_strings_stay_intact(self):
        reason='Literal } { and <think> in a JSON string.'
        self.assertEqual(parse_model_object(json.dumps({'reason':reason}))['reason'],reason)

    def test_observer_does_not_announce_proposal_for_invalid_json(self):
        @observed_model
        def call():return REPLY+'\nExtra text'
        captured=[]
        with event_sink(captured.append):call()
        self.assertNotIn('proposal',[e['kind'] for e in captured])


class StreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Tests can run offline without the Ollama package installed.
        try:
            import langchain_ollama
        except ImportError:
            fake=ModuleType('langchain_ollama');fake.ChatOllama=Mock()
            sys.modules['langchain_ollama']=fake
        from erp_bar import llm
        cls.llm=llm

    def test_native_json_and_separate_thinking_are_enabled(self):
        with patch.dict(os.environ,{'OLLAMA_REASONING':'true'}), patch.object(self.llm,'ChatOllama') as constructor:
            self.llm.get_llm()
        self.assertEqual(constructor.call_args.kwargs['format'],'json')
        self.assertIs(constructor.call_args.kwargs['reasoning'],True)

    def test_non_thinking_model_configuration(self):
        with patch.dict(os.environ,{'OLLAMA_REASONING':'auto'}), patch.object(self.llm,'ChatOllama') as constructor:
            self.llm.get_llm()
        self.assertIsNone(constructor.call_args.kwargs['reasoning'])

    def test_both_channels_stream_before_return_and_prompts_unchanged(self):
        captured=[]
        def stream(messages):
            self.assertEqual(messages,[('system','original schema'),('human','demand')])
            yield SimpleNamespace(content='',additional_kwargs={'reasoning_content':'First I need to verify the product.'})
            self.assertTrue(any(e['kind']=='model_stream' and e['phase']=='thinking' for e in captured))
            self.assertFalse(any(e['kind']=='proposal' for e in captured))
            for char in REPLY:
                yield SimpleNamespace(content=char,additional_kwargs={})
        with patch.object(self.llm,'get_llm',return_value=SimpleNamespace(stream=stream)) as get, event_sink(captured.append), agent_scope('inventory_agent'):
            response=self.llm.invoke_llm('original schema','demand')
        get.assert_called_once()
        self.assertEqual(response,REPLY)
        final=next(e for e in captured if e['kind']=='model_stream_end')
        self.assertEqual(final['thinking'],'First I need to verify the product.')
        self.assertEqual(final['output'],REPLY)
        self.assertEqual(captured[-1]['kind'],'proposal')
        self.assertEqual(len({e['stream_id'] for e in captured}),1)
        self.assertTrue(all(e['agent']=='inventory_agent' for e in captured))

    def test_full_long_generation_is_not_a_600_character_summary(self):
        captured=[]
        display=GenerationStream(lambda kind,**data:captured.append(dict(kind=kind,**data)))
        thinking='Review the warehouse evidence. '*300
        for start in range(0,len(thinking),7):display.feed('thinking',thinking[start:start+7])
        display.feed('output',REPLY);display.finish()
        self.assertEqual(captured[-1]['thinking'],thinking)
        self.assertEqual(''.join(e['delta'] for e in captured if e['kind']=='model_stream' and e['phase']=='thinking'),thinking)

    def test_split_secret_is_redacted_in_both_channels(self):
        captured=[]
        with patch.dict(os.environ,{'ODOO_PASSWORD':'very-secret-value'}):
            display=GenerationStream(lambda kind,**data:captured.append(dict(kind=kind,**data)))
            for phase in ['thinking','output']:
                for char in 'Uses very-secret-value.':display.feed(phase,char)
            display.finish()
        for phase in ['thinking','output']:
            self.assertEqual(captured[-1][phase],'Uses [redacted].')
            self.assertNotIn('very-secret', ''.join(e.get('delta','') for e in captured if e.get('phase')==phase))

    def test_interrupted_request_preserves_partial_text_without_retry(self):
        def stream(messages):
            yield SimpleNamespace(content='',additional_kwargs={'reasoning_content':'Partial thinking.'})
            raise RuntimeError('connection detail')
        captured=[]
        with patch.object(self.llm,'get_llm',return_value=SimpleNamespace(stream=stream)) as get, event_sink(captured.append):
            with self.assertRaises(RuntimeError):self.llm.invoke_llm('schema','demand')
        get.assert_called_once()
        self.assertTrue(next(e for e in captured if e['kind']=='model_stream_end')['interrupted'])
        self.assertEqual(captured[-1]['kind'],'model_error')
        self.assertNotIn('proposal',[e['kind'] for e in captured])

    def test_demand_response_without_reason_is_streamed(self):
        reply='{"product_query":"Lemonade","requested_qty":1,"is_ambiguous":false}'
        captured=[]
        chunks=[SimpleNamespace(content=[{'type':'text','text':reply}],additional_kwargs={})]
        with patch.object(self.llm,'get_llm',return_value=SimpleNamespace(stream=lambda _:iter(chunks))), event_sink(captured.append):
            self.assertEqual(self.llm.invoke_llm('demand schema','1 Lemonade'),reply)
        self.assertEqual(next(e for e in captured if e['kind']=='model_stream_end')['output'],reply)

    def test_bad_observer_does_not_fail_or_repeat_generation(self):
        chunks=[SimpleNamespace(content=REPLY,additional_kwargs={})]
        def broken(_):raise RuntimeError('UI disconnected')
        with patch.object(self.llm,'get_llm',return_value=SimpleNamespace(stream=lambda _:iter(chunks))) as get, event_sink(broken):
            self.assertEqual(self.llm.invoke_llm('schema','demand'),REPLY)
        get.assert_called_once()


class ReplayTests(unittest.TestCase):
    def test_completed_stream_compacts_tokens_and_preserves_full_snapshot(self):
        session=Session(live=True)
        session.publish(dict(kind='thinking',agent='inventory_agent',stream_id='A'))
        for _ in range(150):session.publish(dict(kind='model_stream',agent='inventory_agent',stream_id='A',phase='thinking',delta='word '))
        session.publish(dict(kind='model_stream_end',agent='inventory_agent',stream_id='A',thinking='word '*150,output=REPLY))
        events=session.snapshot()['events']
        self.assertEqual(len(events),2)
        self.assertEqual(events[-1]['thinking'],'word '*150)
        self.assertEqual(events[-1]['id'],session.sequence)

    def test_demo_uses_streaming_for_all_four_agents(self):
        session=Session()
        with patch.object(session,'demo_wait'),event_sink(session.publish):run_demo(session)
        events=session.snapshot()['events']
        generations=[e for e in events if e['kind']=='model_stream_end']
        self.assertEqual({e['agent'] for e in generations},{'supervisor','sales_agent','inventory_agent','purchase_agent'})
        self.assertTrue(all(e['demo'] and e['thinking'] and json.loads(e['output']) for e in generations))
        self.assertEqual(events[-1]['status'],'DELIVERED')

if __name__=='__main__':unittest.main()
