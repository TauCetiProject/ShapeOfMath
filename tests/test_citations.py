from pathlib import Path
import sqlite3
import unittest

import mathdb as m
from test_mathdb import concept, source


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.db=m.connect(':memory:')
        m.initialize(self.db)
        m.ingest(self.db,dict(sources=[source(),source('target')],concepts=[concept('a')]))

    def tearDown(self):
        self.db.close()

    def review(self):
        m.set_completeness(self.db,'source','paper',dict(citations_complete=True,
            requirements_complete=True,introductions_complete=True),'Reviewed each immediate list')

    def test_unresolved_text_and_nullable_assessment(self):
        with self.db:
            ident=m.add_citation(self.db,dict(source='paper',text='An unpublished note, personal communication.'))
        row=m.citation_record(self.db,ident)
        self.assertEqual(row['text'],'An unpublished note, personal communication.')
        self.assertIsNone(row['cited_source_id'])
        self.assertIsNone(row['pedagogically_necessary'])
        self.assertIsNone(row['needed_material'])
        self.assertEqual(row['identifiers'],[])
        self.review()  # Unresolved references do not prevent capture completeness.
        self.assertEqual(m.lookup(self.db,'source','paper')['citations_complete'],1)
        self.assertEqual(m.verify(self.db)['citations'],1)

    def test_extraction_normalization_and_multiple_identifiers(self):
        identifiers=m.extract_identifiers('Author. doi:10.1234/ABC. arXiv:1002.0168v2; '
            'https://arxiv.org/pdf/math.QA/9602217v1.pdf. ISBN 3-540-06585-7; Zbl 0869.17005.')
        self.assertIn(('doi','10.1234/abc'),identifiers)
        self.assertIn(('arxiv','1002.0168'),identifiers)
        self.assertIn(('arxiv','math.QA/9602217'),identifiers)
        self.assertIn(('isbn','9783540065852'),identifiers)
        self.assertIn(('zbl','0869.17005'),identifiers)
        self.assertIn(('doi','10.1234/foo(bar)'),m.extract_identifiers('(https://doi.org/10.1234/foo(bar)).'))
        self.assertNotIn(('isbn','9783540065853'),m.extract_identifiers('ISBN 9783540065853'))
        with self.db:
            ident=m.add_citation(self.db,dict(source='paper',text='A reference. doi:10.1234/TARGET.',
                identifiers=[['arxiv','1002.0168v3'],['doi','https://doi.org/10.1234/target']]))
        row=m.citation_record(self.db,ident)
        self.assertEqual(row['cited_source_id'],m.lookup(self.db,'source','target')['id'])
        self.assertEqual(len(row['identifiers']),2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_relation').fetchone()[0],0)

    def test_same_identifier_can_occur_in_multiple_bibliographies(self):
        with self.db:
            for owner in ('paper','target'):
                m.add_citation(self.db,dict(source=owner,text='A reference, doi:10.1234/other.',label='1'))
        self.assertEqual(m.verify(self.db)['citations'],2)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                m.add_citation(self.db,dict(source='paper',text='A duplicate label.',label='1'))

    def test_capture_review_is_independent_of_assessment_and_resolution(self):
        with self.db:
            ident=m.add_citation(self.db,dict(source='paper',text='A reference.'))
        self.review()
        for value in (True,False,None):
            m.revise_citation(self.db,ident,dict(pedagogically_necessary=value,
                needed_material='Theorem 2.3; only the existence assertion.'),'Assess reading requirements')
            self.assertIs(m.citation_record(self.db,ident)['pedagogically_necessary'],value)
            self.assertEqual(m.lookup(self.db,'source','paper')['citations_complete'],1)
        m.revise_citation(self.db,ident,dict(identifiers=[['doi','10.1234/target']]),'Identify the reference')
        self.assertEqual(m.lookup(self.db,'source','paper')['citations_complete'],1)
        self.assertEqual(m.citation_record(self.db,ident)['cited_source_id'],m.lookup(self.db,'source','target')['id'])
        for flag in ('requirements_complete','introductions_complete'):
            self.assertEqual(m.lookup(self.db,'source','paper')[flag],1)
        with self.assertRaises(ValueError):
            m.revise_citation(self.db,ident,dict(pedagogically_necessary='false'),'Reject string boolean')

    def test_insert_edit_and_delete_reset_capture_review_only(self):
        self.review()
        with self.db:
            ident=m.add_citation(self.db,dict(source='paper',text='A reference.'))
        self.assertEqual(m.lookup(self.db,'source','paper')['citations_complete'],0)
        self.review()
        m.revise_citation(self.db,ident,dict(text='A corrected reference, doi:10.1234/target.'),'Correct the transcription')
        self.assertEqual(m.lookup(self.db,'source','paper')['citations_complete'],0)
        self.review()
        with self.db:
            self.db.execute('DELETE FROM citation WHERE id=?',(ident,))
        self.assertEqual(m.lookup(self.db,'source','paper')['citations_complete'],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM citation_identifier').fetchone()[0],0)
        self.assertEqual(m.lookup(self.db,'source','paper')['requirements_complete'],1)

    def test_conflicting_identifiers_roll_back_batch(self):
        with self.assertRaisesRegex(ValueError,'conflicting sources'):
            m.ingest(self.db,dict(citations=[dict(source='paper',text='A conflicting reference.',
                identifiers=[['doi','10.1234/paper'],['doi','10.1234/target']])]))
        self.assertEqual(self.db.execute('SELECT count(*) FROM citation').fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'conflicting sources'):
            m.ingest(self.db,dict(citations=[dict(source='paper',text='doi:10.1234/target',cited_source='paper')]))
        self.assertEqual(self.db.execute('SELECT count(*) FROM citation').fetchone()[0],0)

    def test_resolve_after_referenced_source_enters_catalogue(self):
        m.ingest(self.db,dict(citations=[dict(source='paper',text='Reference. arXiv:1002.0168v1.')]))
        self.review()
        other=source('later');other['identifiers']=[['arxiv','1002.0168']]
        m.ingest(self.db,dict(sources=[other]))
        rows=m.resolve_citations(self.db,'paper','Match new catalogue records')
        self.assertEqual(rows[0]['cited_source_id'],m.lookup(self.db,'source','later')['id'])
        self.assertEqual(m.lookup(self.db,'source','paper')['citations_complete'],1)
        self.assertEqual(m.snapshot(self.db)['citation_identifier'][0]['scheme'],'arxiv')

    def test_legacy_roles_consolidate_and_preserve_notes(self):
        with self.db:
            for role,note in [('defines','A definition.'),('proves','A proof.'),('presents','An exposition.')]:
                m.add_link(self.db,dict(source='paper',concept='a',role=role,locator='§1',note=note))
        rows=self.db.execute('SELECT * FROM source_concept').fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['role'],'explains')
        for note in ('A definition.','A proof.','An exposition.'):
            self.assertIn(note,rows[0]['note'])
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                self.db.execute("UPDATE source_concept SET role='proves'")

    def test_v4_migration_consolidates_roles_and_resets_broadened_review(self):
        db=m.connect(':memory:')
        try:
            db.executescript((Path(__file__).parent/'fixtures/schema_v4.sql').read_text())
            cid=m.stable_id('concept','a');sid=m.stable_id('source','paper')
            with db:
                db.execute("INSERT INTO concept(id,slug,title,kind,description,field) VALUES (?,'a','A','definition','Definition.','Test')",(cid,))
                db.execute("INSERT INTO source(id,slug,title,authors,field,status,coverage,summary,dependency_review) VALUES (?,'paper','Paper','[]','Test','reviewed','Full','Test','Test')",(sid,))
                db.execute("INSERT INTO source_identifier VALUES ('doi','10.1234/paper',?)",(sid,))
                for ident,role,note in [(41,'proves','Proof.'),(42,'introduces','New result.'),(43,'defines','Definition.')]:
                    db.execute('INSERT INTO source_concept VALUES (?,?,?,?,?,?)',(ident,sid,cid,role,'§1',note))
                db.execute('UPDATE source SET requirements_complete=1,introductions_complete=1')
            m.initialize(db)
            row=db.execute('SELECT * FROM source_concept').fetchone()
            self.assertEqual((row['id'],row['role']),(41,'explains'))
            self.assertEqual(row['note'],'Proof.\nNew result.\nDefinition.')
            self.assertEqual(db.execute('SELECT count(*) FROM source_concept').fetchone()[0],1)
            row=m.lookup(db,'source','paper')
            self.assertEqual((row['requirements_complete'],row['introductions_complete'],row['citations_complete']),(1,0,0))
            m.set_completeness(db,'source','paper',{'citations_complete':True},'Empty bibliography checked')
            m.initialize(db)
            self.assertEqual(m.lookup(db,'source','paper')['citations_complete'],1)
            self.assertEqual(m.verify(db)['integrity'],'ok')
        finally:
            db.close()
