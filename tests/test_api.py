import json
from contextlib import closing
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import mathdb as m
import mathdb_server as server
from test_mathdb import concept,source,edge


class QuietHandler(server.Handler):
    def log_message(self,*args):
        pass


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'db.sqlite'
        with closing(m.connect(self.path)) as db:
            m.initialize(db)
            m.ingest(db,dict(sources=[source(),source('target')],concepts=[concept(x) for x in ('a','b','c')],
                dependencies=[edge('a','b')],source_concepts=[dict(source='paper',concept='a',role='relies_on',locator='§1'),
                dict(source='paper',concept='b',role='introduces',introduction_evidence='Synthetic fixture: the source establishes this new concept.',locator='Theorem 1')]))
        self.http=server.make_server(self.path,0)
        self.http.RequestHandlerClass=QuietHandler
        self.thread=threading.Thread(target=self.http.serve_forever,kwargs={'poll_interval':0.02},daemon=True)
        self.thread.start()
        self.base=f'http://127.0.0.1:{self.http.server_address[1]}'
        self.etag=None
        self.request('GET','state')

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
        self.temp.cleanup()

    def request(self,method,path,item=None,headers=None,raw=None,absolute=False):
        data=raw if raw is not None else (json.dumps(item).encode() if item is not None else None)
        h={'Content-Type':'application/json'} if data is not None else {}
        if method!='GET' and self.etag:
            h['If-Match']=self.etag
        if headers:
            h.update(headers)
        req=Request(self.base+(path if absolute else '/api/v1/'+path),data=data,headers=h,method=method)
        try:
            response=urlopen(req,timeout=5)
        except HTTPError as error:
            response=error
        with response:
            body=response.read()
            out=json.loads(body) if response.headers.get_content_type()=='application/json' else body.decode()
            if response.headers.get('ETag'):
                self.etag=response.headers['ETag']
            return response.status,out,response.headers

    def test_read_neighborhood_source_and_assets(self):
        status,result,_=self.request('GET','concepts/a')
        self.assertEqual(status,200)
        self.assertEqual([c['slug'] for c in result['dependents']],['b'])
        self.assertEqual(result['prerequisites'],[])
        _,result,_=self.request('GET','concepts/b')
        self.assertEqual([c['slug'] for c in result['prerequisites']],['a'])
        _,result,_=self.request('GET','sources/paper')
        self.assertEqual(result['authors'],['Test'])
        self.assertEqual({c['role'] for c in result['concepts']},{'relies_on','introduces'})
        self.assertEqual(result['citations'],[])
        status,body,headers=self.request('GET','/',absolute=True)
        self.assertEqual(status,200);self.assertIn('The Shape of Math',body)
        self.assertIn("default-src 'self'",headers['Content-Security-Policy'])
        self.assertIn('/math-text.js',body)
        status,body,headers=self.request('GET','/math-text.js',absolute=True)
        self.assertEqual(status,200);self.assertIn('window.MathText',body)
        self.assertEqual(headers.get_content_type(),'text/javascript')
        self.assertEqual(self.request('GET','/../schema.sql',absolute=True)[0],404)

    def test_conditional_write_and_stale_edit_rejection(self):
        initial=self.etag
        status,result,_=self.request('PATCH','concepts/a',dict(title='Better label',reason='Clarify name'))
        self.assertEqual(status,200);self.assertNotEqual(self.etag,initial)
        self.assertEqual(result['result']['title'],'Better label')
        status,_,_=self.request('PATCH','concepts/a',dict(title='Stale label',reason='Old edit'),headers={'If-Match':initial})
        self.assertEqual(status,412)
        self.assertEqual(self.request('GET','concepts/a')[1]['title'],'Better label')
        self.assertEqual(self.request('PATCH','concepts/a',dict(title='No version',reason='Test'),headers={'If-Match':''})[0],412)
        req=Request(self.base+'/api/v1/concepts/a',data=b'{"title":"No version","reason":"Test"}',headers={'Content-Type':'application/json'},method='PATCH')
        with self.assertRaises(HTTPError) as error:
            urlopen(req)
        self.assertEqual(error.exception.code,428)
        error.exception.close()
        self.assertEqual(len(self.request('GET','history')[1]),2)

    def test_cycle_failure_is_atomic_and_reviews_reset_locally(self):
        self.request('POST','reviews',dict(kind='concept',slug='b',changes={'prerequisites_complete':True},reason='Reviewed'))
        before=self.etag
        status,result,_=self.request('POST','dependencies',{**edge('b','a'),'reason':'Would cycle'})
        self.assertEqual(status,409);self.assertIn('cycle',result['error']);self.assertEqual(self.etag,before)
        self.assertEqual(self.request('GET','concepts/b')[1]['prerequisites_complete'],1)
        status,result,_=self.request('POST','dependencies',{**edge('c','b'),'reason':'Another prerequisite'})
        self.assertEqual(status,200)
        self.assertEqual(self.request('GET','concepts/b')[1]['prerequisites_complete'],0)
        self.assertEqual(self.request('DELETE','dependencies/'+str(result['result']['id']),{'reason':'Remove this route'})[0],200)

    def test_citation_lifecycle_keeps_capture_independent(self):
        status,result,_=self.request('POST','citations',dict(source='paper',label='[1]',text='A reference. doi:10.1234/target.',
            pedagogically_necessary=False,needed_material='Theorem 2.3',reason='Capture reference'))
        self.assertEqual(status,200);ident=result['result']['id']
        self.assertIs(result['result']['pedagogically_necessary'],False)
        self.assertEqual(result['result']['needed_material'],'Theorem 2.3')
        self.assertIsNotNone(result['result']['cited_source_id'])
        self.request('POST','reviews',dict(kind='source',slug='paper',changes={'citations_complete':True},reason='All entries captured'))
        self.request('PATCH','citations/'+str(ident),dict(pedagogically_necessary=None,needed_material='Lemma 3',reason='Assess reference'))
        self.assertEqual(self.request('GET','sources/paper')[1]['citations_complete'],1)
        self.request('PATCH','citations/'+str(ident),dict(text='Corrected citation.',reason='Correct transcription'))
        self.assertEqual(self.request('GET','sources/paper')[1]['citations_complete'],0)
        self.assertEqual(self.request('DELETE','citations/'+str(ident),{'reason':'Remove duplicate'})[0],200)
        self.assertEqual(self.request('GET','sources/paper')[1]['citations'],[])

    def test_create_records_edit_source_and_manage_links(self):
        status,_,_=self.request('POST','concepts',{**concept('new'),'reason':'Create concept'})
        self.assertEqual(status,200)
        status,_,_=self.request('POST','sources',{**source('new-paper'),'reason':'Create source'})
        self.assertEqual(status,200)
        self.request('PATCH','sources/new-paper',dict(authors=['One','Two'],coverage='Section 1 inspected',reason='Inspect source'))
        self.assertEqual(self.request('GET','sources/new-paper')[1]['authors'],['One','Two'])
        self.assertEqual(self.request('POST','sources/new-paper/identifiers',dict(scheme='arxiv',value='1002.0168v1',reason='Find identifier'))[0],200)
        status,result,_=self.request('POST','source-concepts',dict(source='new-paper',concept='new',role='introduces',introduction_evidence='Synthetic fixture: the source establishes this new concept.',locator='Definition 1',reason='Locate definition'))
        self.assertEqual(status,200);ident=result['result']['id']
        self.request('PATCH','source-concepts/'+str(ident),dict(note='A useful convention.',reason='Explain convention'))
        self.assertEqual(self.request('GET','sources/new-paper')[1]['concepts'][0]['note'],'A useful convention.')
        self.assertEqual(self.request('DELETE','source-concepts/'+str(ident),{'reason':'Remove occurrence'})[0],200)
        status,result,_=self.request('POST','related',dict(concept_a='new',concept_b='a',rationale='Parallel objects.',reason='Connect concepts'))
        self.assertEqual(status,200)
        self.assertEqual(self.request('GET','concepts/a')[1]['related'][0]['slug'],'new')
        self.assertEqual(self.request('DELETE','related/'+str(result['result']['id']),{'reason':'Reconsider connection'})[0],200)

    def test_bad_requests_and_cross_origin_edits_rejected(self):
        before=self.etag
        self.assertEqual(self.request('PATCH','concepts/a',{'title':'Oops','reason':''})[0],400)
        self.assertEqual(self.request('PATCH','concepts/a',{'scope':'Removed','reason':'Test'})[0],400)
        self.assertEqual(self.request('PATCH','concepts/a',raw=b'{bad json')[0],400)
        self.assertEqual(self.request('PATCH','concepts/a',{'title':'Oops','reason':'Test'},headers={'Origin':'https://example.com'})[0],403)
        self.assertEqual(self.request('PATCH','concepts/a',{'title':'Oops','reason':'Test'},headers={'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.request('GET','state',headers={'Host':'example.com'})[0],403)
        self.assertEqual(self.request('GET','state')[2]['ETag'],before)

    def test_ingest_rollback_and_unknown_paths(self):
        status,_,_=self.request('POST','ingest',dict(batch={'concepts':[concept('new')],
            'dependencies':[edge('b','a')]},reason='Invalid cyclic batch'))
        self.assertEqual(status,409)
        self.assertEqual(self.request('GET','concepts/new')[0],404)
        self.assertEqual(self.request('GET','history/99999')[0],404)
        self.assertEqual(self.request('POST','anything',{'reason':'Test'})[0],404)

    def test_formalization_reports_and_shared_file_edits(self):
        _, libraries, _ = self.request('GET', 'formalization-libraries')
        self.assertEqual({r['slug'] for r in libraries}, {'mathlib', 'tau-ceti'})
        item = dict(status='formalized', evidence='Compared exact statements at fixture commit.',
                    files=[dict(path='Mathlib/Shared.lean', note='Defines these objects and their API.')], reason='Inspect implementation')
        self.assertEqual(self.request('POST', 'concepts/a/formalizations/mathlib', item)[0], 200)
        self.assertEqual(self.request('POST', 'concepts/b/formalizations/mathlib', item)[0], 200)
        report = self.request('GET', 'formalizations?concept=a&library=mathlib')[1][0]
        self.assertIsNone(report['estimated_loc'])
        self.assertEqual(report['files'][0]['mapped_concepts'], 2)
        self.assertEqual(self.request('POST', 'formalization-files', dict(library='mathlib', path='Mathlib/Shared.lean',
                         loc=121, revision='fixture-commit', reason='Count committed bytes'))[0], 200)
        report = self.request('GET', 'concepts/a')[1]['formalizations']
        self.assertEqual(next(r for r in report if r['library']=='mathlib')['estimated_loc'], 60.5)
        self.assertEqual(self.request('GET', 'formalizations?library=mathlib&status=formalized')[1][0]['estimated_loc'], 60.5)
        self.assertEqual(len(self.request('GET', 'formalization-files?library=mathlib')[1]), 1)
        before = self.etag
        self.assertEqual(self.request('POST', 'concepts/a/formalizations/mathlib', {**item, 'files': []})[0], 400)
        self.assertEqual(self.etag, before)
        self.assertEqual(self.request('GET', 'formalizations?library=missing')[0], 404)
        self.assertEqual(self.request('GET', 'formalizations?status=bad')[0], 400)
        self.request('POST', 'formalization-libraries', dict(slug='third', name='Third Library', reason='Extend registry'))
        _, state, _ = self.request('GET', 'state')
        self.assertIn('formalizations', state)
        self.assertEqual(len(state['data']['concept_formalization_file']), 2)
        self.assertEqual(next(r for r in state['formalizations'] if r['library']=='third')['status'], 'unknown')
        self.request('PATCH', 'concepts/a', dict(description='A changed mathematical meaning.', reason='Correct statement'))
        report = self.request('GET', 'formalizations?concept=a&library=mathlib')[1][0]
        self.assertEqual(report['status'], 'unknown')
        self.assertTrue(report['review_needed'])
        self.assertEqual(self.request('GET', 'formalizations?concept=b&library=mathlib')[1][0]['estimated_loc'], 121)

    def test_inherited_formalization_is_distinct_from_unknown_and_native_cost(self):
        status, _, _ = self.request('POST', 'concepts/a/formalizations/tau-ceti', dict(status='inherited',
            evidence='Exact declaration checked in Mathlib at dependency-commit; no native contribution.', files=[], reason='Review dependency'))
        self.assertEqual(status, 200)
        report = self.request('GET', 'formalizations?concept=a&library=tau-ceti&status=inherited')[1][0]
        self.assertEqual(report['estimated_loc'], 0)
        self.assertEqual(report['files'], [])
        unknown = self.request('GET', 'formalizations?concept=b&library=tau-ceti')[1][0]
        self.assertEqual(unknown['status'], 'unknown')
        self.assertIsNone(unknown['estimated_loc'])

    def test_formalization_only_ingest_rolls_back_all_records_and_audit(self):
        before = self.request('GET', 'state')[1]
        batch = dict(formalization_libraries=[dict(slug='new-library', name='New Library')],
            formalizations=[dict(concept='a', library='new-library', status='formalized', evidence='Checked fixture.',
                                 files=[dict(path='New.lean', note='Definition and API.')]),
                            dict(concept='missing', library='new-library', status='unknown', evidence='Check failed.', files=[])])
        self.assertEqual(self.request('POST', 'ingest', dict(batch=batch, reason='Must roll back'))[0], 404)
        self.assertEqual(self.request('GET', 'state')[1], before)

    def test_migration_from_v5_preserves_combined_reviews_and_citation_data(self):
        db=m.connect(':memory:')
        try:
            db.executescript((Path(__file__).parent/'fixtures/schema_v5.sql').read_text())
            with db:
                db.execute("INSERT INTO source(id,slug,title,authors,field,status,coverage,summary,dependency_review) VALUES ('s','paper','Paper','[]','Test','reviewed','Full','','')")
                db.execute("INSERT INTO source_identifier VALUES ('doi','10.1234/paper','s')")
                db.execute("INSERT INTO concept(id,slug,title,kind,description,field) VALUES ('c','a','A','definition','Definition.','Test')")
                db.execute("INSERT INTO source_concept VALUES (42,'s','c','presents','Definition 1','Original note')")
                db.execute("INSERT INTO citation(id,source_id,text,pedagogically_necessary,needed_material) VALUES (17,'s','A reference.',0,'Lemma 1')")
                db.execute('UPDATE source SET requirements_complete=1,presentations_complete=1,citations_complete=1')
            m.initialize(db)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],10)
            self.assertEqual(db.execute('SELECT id,role,note FROM source_concept').fetchone()[:],(42,'explains','Original note'))
            row=m.lookup(db,'source','paper')
            self.assertEqual((row['requirements_complete'],row['introductions_complete'],row['citations_complete']),(1,0,1))
            self.assertIs(m.citation_record(db,17)['pedagogically_necessary'],False)
            m.initialize(db)
            self.assertEqual(m.verify(db)['citations'],1)
        finally:
            db.close()
