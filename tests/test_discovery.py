import importlib.util
from pathlib import Path
import unittest

PATH=Path(__file__).resolve().parents[1]/'experiments/discovery-2015/discover.py'
spec=importlib.util.spec_from_file_location('discovery',PATH)
discovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(discovery)


def paper(ident,citations=None,work=None,retracted=False):
    matches=[] if citations is None else [{'openalex_id':work or ident,'cited_by_count':citations,
        'is_retracted':retracted,'arxiv_matches':{ident:[]},'title':ident}]
    return {'id':ident,'cats':['math.FA'],'openalex_matches':matches}


class DiscoveryTests(unittest.TestCase):
    def test_arxiv_ids_normalize_versions_and_preserve_evidence(self):
        work={'locations':[{'landing_page_url':'https://arxiv.org/abs/1501.00001v3'},
            {'id':'pmh:oai:arXiv.org:math/0501234'},
            {'pdf_url':'https://arxiv.org/pdf/1501.00001.pdf'},
            {'doi':'https://doi.org/10.48550/arXiv.1501.00001'}]}
        result=discovery.arxiv_ids(work)
        self.assertEqual(set(result),{'1501.00001','math/0501234'})
        self.assertEqual(len(result['1501.00001']),3)

    def test_rank_includes_cutoff_ties_and_never_sets_unknown_to_zero(self):
        rows=[paper(str(i),100 if i<3 else i) for i in range(20)]+[paper('missing')]
        r=discovery.rank(rows)['math.FA']
        self.assertEqual(r['target_count'],3)
        self.assertEqual(r['selected_count_with_ties'],3)
        self.assertEqual(r['cutoff_citations'],100)
        self.assertEqual(r['unresolved'],[{'arxiv':'missing','status':'unmatched'}])
        self.assertIn('provisional',r['coverage_status'])

    def test_duplicate_work_ids_and_ambiguous_records(self):
        a=paper('a',10,work='shared');b=paper('b',10,work='shared')
        conflict=paper('c',20,work='one');conflict['openalex_matches']+=paper('c',40,work='two')['openalex_matches']
        r=discovery.rank([a,b,conflict,paper('d',100,retracted=True)])['math.FA']
        self.assertEqual(r['distinct_matched_works'],1)
        self.assertEqual(r['selected'][0]['arxiv_ids'],['a','b'])
        self.assertEqual({x['status'] for x in r['unresolved']},{'multiple_openalex_works','retracted'})


if __name__=='__main__':unittest.main()
