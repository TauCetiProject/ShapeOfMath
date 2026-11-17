from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

import task_usage as u


def event(input=100,cached=80,output=10,reasoning=4,write=0):
    return {'type':'event_msg','timestamp':'2026-11-16T00:00:00Z','payload':{'type':'token_count','info':{
        'total_token_usage':{'input_tokens':input,'cached_input_tokens':cached,'output_tokens':output,
            'reasoning_output_tokens':reasoning,'cache_write_input_tokens':write}}}}


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name);self.db=u.connection(self.path/'usage.sqlite');self.addCleanup(self.db.close)
        u.register(self.db,task_id='paper',kind='source');u.register(self.db,task_id='other',kind='source')
        self.log=self.path/'session.jsonl'

    def append(self,*events):
        with self.log.open('a') as f:
            for e in events:f.write(json.dumps(e)+'\n')

    def request(self,ident='request-1',provider='anthropic'):
        return {'provider':provider,'request_id':ident,'model':'recorded-model',
            'usage':{'input_tokens':20,'cache_read_input_tokens':80,'cache_creation_input_tokens':30,'output_tokens':10}}

    def test_api_accounting_and_duplicates_across_owner_tasks(self):
        response=self.request();self.assertTrue(u.record_api(self.db,'paper',response))
        self.assertFalse(u.record_api(self.db,'paper',response))
        self.assertFalse(u.record_api(self.db,'paper',self.request(provider='claude')))
        with self.assertRaisesRegex(ValueError,'different content or owner'):u.record_api(self.db,'other',response)
        report=u.report(self.db,['paper']);tokens=report['unique_total']['tokens']
        self.assertEqual(tokens['fresh_input_tokens'],20);self.assertEqual(tokens['cache_read_input_tokens'],80)
        self.assertEqual(tokens['cache_write_input_tokens'],30);self.assertEqual(tokens['output_tokens'],10)
        self.assertIsNone(tokens['reasoning_output_tokens'])

    def test_openai_cached_subset_reasoning_subset_and_unknowns(self):
        n=u.normalized('openai',{'input_tokens':100,'input_tokens_details':{'cached_tokens':75},'output_tokens':20,'output_tokens_details':{'reasoning_tokens':12}})
        self.assertEqual(n['fresh_input_tokens'],25);self.assertEqual(n['reasoning_output_tokens'],12)
        self.assertIsNone(n['cache_write_input_tokens'])
        self.assertIsNone(u.normalized('openai',{'input_tokens':100,'output_tokens':20})['fresh_input_tokens'])
        for usage in ({'input_tokens':2,'cached_input_tokens':3},{'output_tokens':2,'reasoning_output_tokens':3},{'output_tokens':True}):
            with self.assertRaises(ValueError):u.normalized('openai',usage)

    def test_session_counter_deltas_deduplicate_and_do_not_include_prior_work(self):
        self.append(event());window=u.start_window(self.db,'paper',self.log,'codex-model')['window_id']
        self.append(event(130,100,15,6),event(130,100,15,6),event(180,140,21,9))
        result=u.finish_window(self.db,window)
        self.assertEqual(result['counter_events'],2)
        self.assertEqual(result['usage']['fresh_input_tokens'],20)
        self.assertEqual(result['usage']['cache_read_input_tokens'],60)
        self.assertEqual(result['usage']['output_tokens'],11)
        self.assertFalse(u.finish_window(self.db,window)['changed'])
        self.assertEqual(u.report(self.db,['paper'])['unique_total']['samples'],1)

    def test_one_session_owner_no_overlap_and_switch_tasks(self):
        self.append(event());one=u.start_window(self.db,'paper',self.log,'m')['window_id']
        with self.assertRaisesRegex(ValueError,'open task interval'):u.start_window(self.db,'other',self.log,'m')
        self.append(event(120,90,15,6));u.finish_window(self.db,one)
        two=u.start_window(self.db,'other',self.log,'m')['window_id'];self.append(event(130,95,19,8));u.finish_window(self.db,two)
        self.assertEqual(u.report(self.db,['paper','other'])['unique_total']['tokens']['output_tokens'],9)

    def test_unknown_empty_interval_and_partial_line_are_not_zero(self):
        window=u.start_window(self.db,'paper',self.log,'m')['window_id']
        self.log.write_text(json.dumps(event())[:20])
        result=u.finish_window(self.db,window)
        self.assertTrue(all(v is None for v in result['usage'].values()))
        report=u.report(self.db,['paper']);self.assertIsNone(report['unique_total']['tokens']['output_tokens'])
        self.assertFalse(report['measurement_complete'])

    def test_new_session_measured_from_zero_baseline_and_existing_unknown_baseline_rejected(self):
        window=u.start_window(self.db,'paper',self.log,'m')['window_id'];self.append(event())
        self.assertEqual(u.finish_window(self.db,window)['usage']['fresh_input_tokens'],20)
        other=self.path/'other.jsonl';other.write_text(json.dumps({'type':'session_meta'})+'\n')
        window=u.start_window(self.db,'other',other,'m')['window_id']
        with other.open('a') as f:f.write(json.dumps(event())+'\n')
        with self.assertRaisesRegex(ValueError,'No initial counter baseline'):u.finish_window(self.db,window)

    def test_counter_reset_and_prefix_change_do_not_record_partial_usage(self):
        self.append(event());window=u.start_window(self.db,'paper',self.log,'m')['window_id']
        self.append(event(130,100,15,6),event(10,0,1,0))
        with self.assertRaisesRegex(ValueError,'reset'):u.finish_window(self.db,window)
        self.assertEqual(self.db.execute('SELECT count(*) FROM sample').fetchone()[0],0)
        self.log.write_text(json.dumps(event(200,100,30,9))+'\n')
        with self.assertRaisesRegex(ValueError,'prefix changed'):u.finish_window(self.db,window)

    def test_shared_task_unique_total_and_missing_measurements(self):
        u.register(self.db,task_id='shared-cone',kind='shared')
        u.record_api(self.db,'paper',self.request('paper'))
        u.record_api(self.db,'other',self.request('other'))
        u.link_shared(self.db,'paper','shared-cone');u.link_shared(self.db,'other','shared-cone')
        report=u.report(self.db,['paper','other'])
        self.assertFalse(report['measurement_complete']);self.assertIsNone(report['unique_total']['tokens']['output_tokens'])
        self.assertEqual(report['unique_total']['known_subtotals']['output_tokens'],20)
        u.record_api(self.db,'shared-cone',self.request('shared'))
        report=u.report(self.db,['paper','other'])
        self.assertTrue(report['measurement_complete']);self.assertEqual(report['unique_total']['samples'],3)
        self.assertEqual(report['unique_total']['tokens']['output_tokens'],30)
        self.assertEqual(report['tasks']['paper']['own_usage']['tokens']['output_tokens'],10)
        with self.assertRaisesRegex(ValueError,'cycle'):u.link_shared(self.db,'shared-cone','paper')

    def test_model_change_is_not_misattributed(self):
        self.append(event());window=u.start_window(self.db,'paper',self.log,'one')['window_id']
        self.append({'type':'turn_context','payload':{'model':'two'}},event(120,100,12,5))
        with self.assertRaisesRegex(ValueError,'model changed'):u.finish_window(self.db,window)
        self.assertEqual(self.db.execute('SELECT count(*) FROM sample').fetchone()[0],0)

    def test_unusable_window_can_close_as_unknown_with_reason(self):
        self.append(event());window=u.start_window(self.db,'paper',self.log,'m')['window_id']
        self.append(event(10,0,1,0))
        with self.assertRaisesRegex(ValueError,'reset'):u.finish_window(self.db,window)
        self.assertTrue(u.abandon_window(self.db,window,'Session counters reset; attribution unavailable.')['usage_unknown'])
        report=u.report(self.db,['paper']);self.assertFalse(report['measurement_complete']);self.assertEqual(report['open_windows'],0)
        self.assertIsNone(report['unique_total']['tokens']['output_tokens'])
        self.assertFalse(u.abandon_window(self.db,window,'Repeat')['changed'])
        u.start_window(self.db,'other',self.log,'m')


if __name__=='__main__':unittest.main()
