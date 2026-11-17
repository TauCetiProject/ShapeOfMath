from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import discovery as d

FIXTURES=Path(__file__).resolve().parent/'fixtures'/'discovery'


def work(ident,count=5,arxiv='1501.00001',doi='10.4007/annals.2015.181.1.1'):
    return {'id':ident,'title':'A sample article','doi':'https://doi.org/'+doi,
            'cited_by_count':count,'is_retracted':False,'authorships':[],
            'locations':[{'landing_page_url':'https://arxiv.org/abs/'+arxiv}]}


class DiscoveryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.scope=self.root/'input.json';self.run=self.root/'run'

    def init(self,scope):
        d.save(self.scope,scope);d.initialize(self.scope,self.run)

    def seed(self,url,data,params=None):
        url=url+('?' + d.urllib.parse.urlencode(params) if params else '')
        directory=self.root/'seed';directory.mkdir(exist_ok=True)
        d.save(directory/(str(len(list(directory.iterdir())))+'.json'),{'url':url,'retrieved_at_utc':'2026-11-16T00:00:00Z','data':data})
        return directory

    def test_id_year_ignores_record_creation_old_and_modern_ids(self):
        for ident,year in [('1501.00001',2015),('math/0501234',2005),('hep-th/9901001',1999),('0704.0001v2',2007)]:
            self.assertEqual(d.submission_year(ident),year)
        self.assertIsNone(d.submission_year('1513.00001'))
        inventory=self.root/'inventory.jsonl';inventory.write_text('\n'.join(json.dumps(r) for r in [
            {'id':'1501.00001','cats':['math.FA'],'created':'2017-01-01'},
            {'id':'1401.00001','categories':'math.FA','created':'2015-01-01'}]))
        rows=d.inventory_cohort({'inventory':str(inventory),'start_year':2015,'end_year':2015,'categories':['math.FA']})
        self.assertEqual([r['id'] for r in rows],['1501.00001'])

    def test_dynamic_journal_indexes_across_years(self):
        annals=d.issue_list(d.REGISTRY['annals'],2021,2022,'https://annals.math.princeton.edu/2021/193-1 https://annals.math.princeton.edu/2022/195-2')
        self.assertEqual([i['volume'] for i in annals],['193','195'])
        springer=d.issue_list(d.REGISTRY['inventiones'],2020,2020,'<h3>Volume 219 January - March 2020</h3><a href="/volumes-and-issues/219-2">issue</a><h3>Volume 220 April - June 2020</h3><a href="/volumes-and-issues/220-1">issue</a>')
        self.assertEqual([i['volume'] for i in springer],['219','220'])
        ams=d.issue_list(d.REGISTRY['jams'],2016,2016,'<a href="/JAMS/2015-28-01">x</a> "IssueDirectory":"2016-29-03" <a href="/JAMS/2016-29-03">')
        self.assertEqual(len(ams),1);self.assertEqual(ams[0]['issue'],'3')

    def test_jams_index_ignores_other_ams_journals_and_dates(self):
        body=(FIXTURES/'jams-index-excerpts.html').read_text()
        found={(i['year'],i['volume'],i['issue']) for i in d.issue_list(d.REGISTRY['jams'],2006,2025,body)}
        self.assertIn((2016,'29','3'),found);self.assertIn((2006,'19','1'),found)
        self.assertFalse({v for _,v,_ in found}&{'358','360','46','12'})

    def test_annals_pre_2011_entries_use_crossref_first_page_dois(self):
        body=(FIXTURES/'annals-2006-163-1.html').read_text()
        issue={'year':2006,'volume':'163','issue':'1'}
        known={'10.4007/annals.2006.163.1','10.4007/annals.2006.163.37'}
        parsed=d.parse_toc(d.REGISTRY['annals'],issue,body,{},known)
        self.assertEqual(parsed['publisher_count'],9)
        self.assertIn('10.4007/annals.2006.163.1',parsed['dois']);self.assertIn('10.4007/annals.2006.163.37',parsed['dois'])
        # Without a Crossref page-form record the publisher sequence form stays and is reviewed.
        self.assertIn('10.4007/annals.2006.163.1.3',parsed['dois'])
        self.assertNotIn('10.4007/annals.2006.163.1.1',parsed['dois'])

    def test_jams_modern_pii_uses_crossref_serial_doi_only_when_registered(self):
        body="<a href='/jams/2024-37-04/S0894-0347-2024-01041-6/'>x</a><a href='/jams/2024-37-04/S0894-0347-2024-01042-8/'>y</a>"
        parsed=d.parse_toc(d.REGISTRY['jams'],{'year':2024,'volume':'37','issue':'4'},body,{},{'10.1090/jams/1041'})
        self.assertEqual(parsed['dois'],['10.1090/jams/1041','10.1090/s0894-0347-2024-01042-8'])

    def test_crossref_only_issue_years_are_explicit_and_unverified(self):
        records={'10.4310/a1':{'volume':'218','issue':'1','title':['T'],'author':[{'family':'X'}],'journal-issue':{'published-print':{'date-parts':[[2017]]}}},
                 '10.4310/fm':{'volume':'218','issue':'1','title':['Front Matter']},
                 '10.4310/a2':{'volume':'232','issue':'1','title':['U'],'author':[{'family':'Y'}],'journal-issue':{'published-print':{'date-parts':[[2024]]}}},
                 '10.4310/x':{'volume':'240','title':['Online first'],'author':[{'family':'Z'}]}}
        audits=d.crossref_issues('Acta',[2017,2018],records)
        self.assertEqual([(a['year'],a['status'],a['crossref_dois']) for a in audits],
            [(2017,'crossref_only',['10.4310/a1']),(2018,'crossref_only_empty',[])])
        with self.assertRaisesRegex(ValueError,'crossref_issue_years'):
            d.validate_scope({'version':1,'journals':{'start_year':2017,'end_year':2017,'journals':[dict(d.REGISTRY['acta'],crossref_issue_years='2017')]}},self.root)

    def test_reconcile_excludes_furniture_and_moves_misfiled_crossref_records(self):
        records={'a':{'volume':'1','issue':'3','title':['Real'],'author':[{'family':'X'}]}}
        first={'url':'u1','publisher_dois':['a'],'publisher_count':1,'unidentified_entries':[],'crossref_not_publisher':[],'publisher_not_crossref':[]}
        third={'url':'u3','publisher_dois':['b'],'publisher_count':1,'unidentified_entries':[],'crossref_not_publisher':['a'],'publisher_not_crossref':[]}
        d.reconcile_issues([first,third],d.REGISTRY['annals'],records)
        self.assertEqual(third['status'],'verified');self.assertEqual(third['crossref_issue_metadata_conflicts'][0]['listed_on'],'u1')
        self.assertTrue(d.nonarticle({'title':['Front Matter']}));self.assertFalse(d.nonarticle({'title':['Index'],'author':[{'family':'X'}]}))
        lost={'url':'u4','publisher_dois':['c'],'publisher_count':1,'unidentified_entries':[],'crossref_not_publisher':['z'],'publisher_not_crossref':[]}
        d.reconcile_issues([lost],d.REGISTRY['annals'],{'z':{}});self.assertEqual(lost['status'],'needs_review')

    def test_top_percentage_ties_unknowns_retraction_and_pooling(self):
        spec={'cohort':{'categories':['math.FA','math.NT']},'top_percent':25,'group_by':'category','ties':'include','exclude_retracted':True}
        rows=[{'id':str(i),'categories':['math.FA','math.NT'],'openalex_matches':[d.compact(work('W'+str(i),count=count))]} for i,count in enumerate((9,9,2))]
        rows.append({'id':'missing','categories':['math.FA'],'openalex_matches':[]})
        r=d.rank(rows,spec)
        self.assertEqual(r['math.FA']['target'],1);self.assertEqual(r['math.FA']['selected_count'],2)
        self.assertFalse(r['math.FA']['complete']);self.assertTrue(r['math.NT']['complete'])
        spec.update(group_by='pool',top_count=1,ties='exact');spec.pop('top_percent')
        r=d.rank(rows,spec)['combined'];self.assertEqual(r['cohort_size'],4);self.assertEqual(r['selected_count'],1)
        rows[0]['openalex_matches'][0]['is_retracted']=True
        self.assertEqual(len(d.rank(rows,spec)['combined']['excluded']),1)

    def test_unknown_scope_fields_and_changed_scope_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unknown scope'):
            d.validate_scope({'version':1,'citations':{'cohort':{'kind':'openalex','filter':'publication_year:2015'},'top_percnt':10}},self.root)
        self.init({'version':1,'citations':{'cohort':{'kind':'openalex','filter':'publication_year:2015'}}})
        d.save(self.run/'scope.json',{'version':9})
        with self.assertRaisesRegex(ValueError,'scope changed'):d.validate_run(self.run)
        with self.assertRaisesRegex(ValueError,'exists'):d.initialize(self.scope,self.run)

    def test_cache_projection_replay_without_network_and_secret_not_saved(self):
        self.run.mkdir();seed=self.seed('https://api.openalex.org/works',{'meta':{'count':1},'results':[work('W1')]},
            {'filter':'doi:test','per_page':100,'select':d.SELECT+',primary_location'})
        client=d.Client(self.run,offline=True,seeds=[seed])
        with patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            result=client.get('https://api.openalex.org/works',{'filter':'doi:test','per_page':100,'select':d.SELECT,'page':1})
        self.assertEqual(result['results'][0]['id'],'W1')
        self.assertEqual(client.calls,0)
        self.assertTrue(list((self.run/'cache').glob('*.json')))

    def test_seed_work_index_is_copied_for_later_offline_resume(self):
        self.run.mkdir();seed=self.seed('https://api.openalex.org/works',{'meta':{'count':1},'results':[work('W1')]},{'search':'sample'})
        self.assertEqual(d.Client(self.run,offline=True,seeds=[seed]).work_index()[0]['id'],'W1')
        self.assertEqual(d.Client(self.run,offline=True).work_index()[0]['id'],'W1')

    def test_full_offline_journal_pipeline_and_deduplicated_citation_overlap(self):
        journal=dict(d.REGISTRY['annals'],issues=[{'year':2015,'volume':'181','issue':'1','url':'https://annals.math.princeton.edu/2015/181-1'}])
        self.init({'version':1,'journals':{'start_year':2015,'end_year':2015,'journals':[journal]},
                   'citations':{'cohort':{'kind':'openalex','filter':'publication_year:2015'},'top_percent':100},'title_search':False})
        seed=self.seed(journal['issues'][0]['url'],{'status':200,'html':'<h2 class="entry-title"><a href="https://annals.math.princeton.edu/2015/181-1/p01">Sample</a></h2>'})
        self.seed('https://api.crossref.org/journals/0003-486X/works',{'status':'ok','message':{'total-results':1,'items':[
            {'DOI':'10.4007/annals.2015.181.1.1','title':['A sample article'],'author':[],'volume':'181','issue':'1'}]}},
            {'filter':'from-pub-date:2013-01-01,until-pub-date:2017-12-31,type:journal-article','rows':1000})
        self.seed('https://api.openalex.org/works',{'meta':{'count':1},'results':[work('https://openalex.org/W1')]},
            {'filter':'publication_year:2015','per_page':100,'select':d.SELECT})
        with redirect_stdout(io.StringIO()):status=d.Discovery(self.run,d.Client(self.run,offline=True,seeds=[seed])).run_all()
        self.assertTrue(status['complete']);self.assertEqual(status['candidate_count'],1)
        candidate=d.read(self.run/'candidates.json')[0]
        self.assertEqual(len(candidate['selections']),2);self.assertEqual(candidate['cited_by_count'],5)
        self.assertEqual(d.read(self.run/'issues.json')[0]['status'],'verified')
        self.assertTrue(d.verify(self.run)['verified'])
        with redirect_stdout(io.StringIO()):again=d.Discovery(self.run,d.Client(self.run,offline=True)).run_all()
        self.assertTrue(again['complete'])

    def test_budget_checkpoint_does_not_rank_partial_openalex_population(self):
        self.init({'version':1,'citations':{'cohort':{'kind':'openalex','filter':'publication_year:2015'}}})
        status=d.Discovery(self.run,d.Client(self.run,budget=0)).run_all()
        self.assertFalse(status['complete']);self.assertEqual(d.read(self.run/'rankings.json'),{})
        self.assertIn('budget',status['stages']['citations']['reason'])

    def test_crossref_cursor_pagination_and_openalex_limit(self):
        class Fake:
            offline=False
            def __init__(self):self.calls=[]
            def get(self,url,args):
                self.calls.append(args)
                if 'cursor' not in args:return {'message':{'total-results':3,'items':[{'DOI':'a'}]}}
                return {'message':{'items':[{'DOI':'a'},{'DOI':'b'},{'DOI':'c'}],'next-cursor':'next'}}
        fake=Fake();self.assertEqual({w['DOI'] for w in d.crossref_pages(fake,'1234-1234','test')},{'a','b','c'})
        class Large:
            offline=False
            def get(self,url,args):return {'meta':{'count':10001},'results':[work('W1')]}
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaisesRegex(d.Blocked,'OPENALEX_API_KEY'):list(d.oa_pages(Large(),{}))


if __name__=='__main__':unittest.main()
