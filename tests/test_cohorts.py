from contextlib import closing, redirect_stdout
from itertools import permutations
from pathlib import Path
import io
import json
import tempfile
import unittest

import cohorts
import mathdb as m
from test_mathdb import concept, edge, source


def paper(slug, year, ident):
    return {**source(slug), 'year': year, 'identifiers': [ident]}


def link(src, slug, role='relies_on'):
    item = dict(source=src, concept=slug, role=role, locator='Section 1')
    if role == 'introduces':
        item['introduction_evidence'] = 'Abstract states the new definition.'
    return item


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite'
        with closing(m.connect(self.path)) as db:
            m.initialize(db)
            theorem = {**concept('t'), 'kind': 'theorem'}
            m.ingest(db, dict(
                sources=[paper('p1', 2010, ['arxiv', '1001.00001']), paper('p2', 2012, ['doi', '10.4007/annals.2012.1']),
                         paper('p3', 2015, ['doi', '10.1007/s00222-015-1']), paper('p4', 2001, ['doi', '10.4007/annals.2001.2'])],
                concepts=[concept(x) for x in 'abcdx'] + [theorem],
                dependencies=[edge('a', 'b'), edge('a', 'c'), edge('b', 'd'),
                              {**edge('x', 't'), 'purpose': 'proof'}, {**edge('a', 't'), 'purpose': 'statement'}],
                source_concepts=[link('p1', 'd'), link('p2', 'c'), link('p2', 'b'), link('p3', 't'),
                                 link('p3', 'x', 'introduces')]))
            m.set_completeness(db, 'concept', 'a', {'statement_prerequisites_complete': True}, 'Primitive in this fixture')
        with closing(cohorts.connect(self.path)) as db:
            self.catalogue = cohorts.Catalogue(db)

    def tearDown(self):
        self.temp.cleanup()

    def slugs(self, selector):
        missing = []
        chosen = cohorts.select(self.catalogue, selector, missing)
        return {self.catalogue.sources[i]['slug'] for i in chosen}, missing

    def test_selectors_combine_by_intersection_union_and_exclusion(self):
        self.assertEqual(self.slugs({'arxiv': ['arXiv:1001.00001', '9999.99999']}), ({'p1'}, ['arxiv:9999.99999']))
        self.assertEqual(self.slugs({'doi_prefixes': ['10.4007/ANNALS.']})[0], {'p2', 'p4'})
        self.assertEqual(self.slugs({'doi_prefixes': ['10.4007/annals.'], 'years': [2006, 2025]})[0], {'p2'})
        self.assertEqual(self.slugs({'any': [{'sources': ['p1']}, {'identifiers': ['doi:10.1007/s00222-015-1']}]})[0], {'p1', 'p3'})
        self.assertEqual(self.slugs({'years': [2000, 2030], 'exclude': {'sources': ['p4']}})[0], {'p1', 'p2', 'p3'})
        with self.assertRaises(ValueError):
            self.slugs({'categories': ['math.NT']})

    def test_sample_is_reproducible_from_its_seed(self):
        selector = {'years': [2000, 2030], 'sample': {'count': 2, 'seed': 'fixture:1'}}
        first, second = self.slugs(selector)[0], self.slugs(selector)[0]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)

    def test_statement_cones_overlap_and_coverage(self):
        cohort = {'name': 'fixture', 'groups': {'arxiv': {'arxiv': ['1001.00001']},
                                                'journals': {'doi_prefixes': ['10.4007/', '10.1007/s00222-'], 'years': [2006, 2025]}}}
        result = cohorts.analyse(self.catalogue, cohort)
        cones = {s['slug']: s['cone'] for s in result['sources']}
        # p1: d,b,a; p2: c,b,a; p3: t,a (the proof-only input x is not followed).
        self.assertEqual(cones, {'p1': 3, 'p2': 3, 'p3': 2})
        self.assertEqual(result['union_size'], 5)
        self.assertEqual(result['shared_by'], {'1': 3, '2': 1, '3': 1})
        self.assertEqual(result['most_shared'][0]['slug'], 'a')
        self.assertEqual(result['unreviewed_in_union'], ['b', 'c', 'd', 't'])
        self.assertEqual(result['groups']['journals']['sources'], 2)
        self.assertEqual(result['pairwise_jaccard']['highest'][0], {'a': 'p1', 'b': 'p2', 'jaccard': 0.5})
        with_introductions = cohorts.analyse(self.catalogue, cohort, roles=('relies_on', 'introduces'))
        self.assertEqual(with_introductions['union_size'], 6)

    def test_expected_growth_matches_all_orderings(self):
        cones = [{1, 2, 3}, {2, 3}, {3, 4}, set(), {5}]
        exact = cohorts.expected_growth(cones)
        orders = list(permutations(cones))
        for n in range(len(cones) + 1):
            brute = sum(len(set().union(*order[:n])) for order in orders) / len(orders)
            self.assertAlmostEqual(exact[n], brute)

    def test_cli_writes_json_and_summary(self):
        cohort_path = Path(self.temp.name) / 'cohort.json'
        cohort_path.write_text(json.dumps({'name': 'fixture', 'select': {'years': [2006, 2025]}}))
        out = Path(self.temp.name) / 'out.json'
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(cohorts.main([str(cohort_path), '--db', str(self.path), '--json', str(out)]), 0)
        self.assertIn('Cohort fixture: 3 sources', buffer.getvalue())
        self.assertEqual(json.loads(out.read_text())['union_size'], 5)


if __name__ == '__main__':
    unittest.main()
