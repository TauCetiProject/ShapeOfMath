import datetime
import json
import unittest

try:
    import openalex_pg as op
except ImportError:  # optional dependencies: pip install '.[openalex]'
    op = None


@unittest.skipIf(op is None, 'pyarrow/numpy not installed')
class WorkRowTests(unittest.TestCase):
    def test_key_columns(self):
        row = op.work_row({
            'id': 'https://openalex.org/W42', 'doi': 'https://doi.org/10.1007/ABC', 'title': 'T',
            'publication_year': 2015, 'publication_date': datetime.date(2015, 1, 2), 'type': 'article',
            'language': 'en', 'cited_by_count': 3, 'is_retracted': False, 'is_paratext': False,
            'primary_location': {'source': {'id': 'https://openalex.org/S7', 'display_name': 'Annals',
                                            'issn_l': '0003-486X', 'type': 'journal'}},
            'primary_topic': {'id': 'https://openalex.org/T11', 'display_name': 'Topic',
                              'subfield': {'id': 'https://openalex.org/subfields/2602', 'display_name': 'Algebra'}},
            'authorships': [{'author': {'id': 'https://openalex.org/A5', 'display_name': 'Kim',
                                        'orcid': 'https://orcid.org/0000-0001'}}],
            'referenced_works': ['https://openalex.org/W1', 'https://openalex.org/W2'],
            'open_access': {'is_oa': True, 'oa_status': 'green', 'oa_url': 'u'},
            'best_oa_location': {'pdf_url': 'p', 'landing_page_url': 'l', 'version': 'submittedVersion', 'license': 'cc-by'},
            'locations': [{'id': 'pmh:oai:arXiv.org:1501.00001', 'landing_page_url': 'https://arxiv.org/abs/1501.00001v2'},
                          {'pdf_url': 'https://arxiv.org/pdf/math/0501234v1'}],
            'updated_date': datetime.datetime(2026, 10, 14, 3, tzinfo=datetime.timezone.utc)})
        fields = dict(zip([f.strip() for f in op.WORK_FIELDS.split(',')], row))
        self.assertEqual(fields['id'], 42)
        self.assertEqual(fields['doi'], '10.1007/abc')
        self.assertEqual(fields['arxiv_ids'], ['1501.00001', 'math/0501234'])
        self.assertEqual((fields['source_id'], fields['primary_topic_id'], fields['subfield_id']), (7, 11, 2602))
        self.assertEqual(json.loads(fields['authors']), [{'id': 5, 'name': 'Kim', 'orcid': '0000-0001'}])
        self.assertEqual(fields['referenced_works'], [1, 2])
        self.assertEqual(fields['best_oa_pdf_url'], 'p')
        self.assertEqual(fields['updated_date'], datetime.date(2026, 10, 14))

    def test_missing_nested_values(self):
        row = op.work_row({'id': 'https://openalex.org/W1', 'updated_date': datetime.datetime(2026, 1, 1)})
        fields = dict(zip([f.strip() for f in op.WORK_FIELDS.split(',')], row))
        self.assertEqual((fields['arxiv_ids'], fields['referenced_works'], fields['authors']), ([], [], '[]'))
        self.assertIsNone(fields['source_id'])


if __name__ == '__main__':
    unittest.main()
