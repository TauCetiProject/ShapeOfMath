import importlib.util
from itertools import permutations
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]/'experiments/curation-2015-round2/overlap'
spec=importlib.util.spec_from_file_location('expanded_overlap',HERE/'analyse.py')
expanded=importlib.util.module_from_spec(spec);spec.loader.exec_module(expanded)


class KnownFractionTests(unittest.TestCase):
    def check_brute_force(self,cones,known=frozenset()):
        exact=expanded.exact_curves(cones,known)
        fractions=[[] for _ in cones];increments=[[] for _ in cones];totals=[[] for _ in cones]
        for order in permutations(range(len(cones))):
            seen=set(known)
            for n,i in enumerate(order):
                new=len(cones[i]-seen)
                fractions[n].append(1-new/len(cones[i]));increments[n].append(new)
                seen.update(cones[i]);totals[n].append(len(seen-known))
        for key,columns in [('mean_known',fractions),('mean_marginal',increments),('mean_cumulative',totals)]:
            values=exact[key][1:] if key=='mean_cumulative' else exact[key]
            for expected,col in zip(values,columns):self.assertAlmostEqual(expected,sum(col)/len(col))
        return exact

    def test_unequal_sizes_average_fractions_not_counts(self):
        cones=[{'a'},{'a','b','c','d'}]
        exact=self.check_brute_force(cones)
        self.assertAlmostEqual(exact['mean_known'][1],.625)
        self.assertNotAlmostEqual(exact['mean_known'][1],1-exact['mean_marginal'][1]/2.5)

    def test_initial_known_and_intermediate_positions(self):
        self.check_brute_force([{'a','b'},{'b','c','d'},{'e'},{'a','d'}],{'a','b','z'})

    def test_empty_cone_undefined_and_total_coverage(self):
        with self.assertRaises(ValueError):expanded.exact_curves([set(),{'a'}])
        self.assertEqual(expanded.exact_curves([{'a'},{'b'}],{'a','b'})['mean_known'],[1,1])
        self.assertEqual(expanded.exact_curves([{'a'}])['mean_known'],[0])

    def test_order_ranges_reproducible_with_exact_endpoints(self):
        cones=[{'a'},{'a','b','c','d'}]
        a=expanded.distributions(cones,set(),50,'test')
        self.assertEqual(a,expanded.distributions(cones,set(),50,'test'))
        self.assertEqual(a['known'][0]['p05'],0)
        self.assertEqual(a['known'][-1]['median'],.625)

    def test_balanced_next_papers_keep_discrete_five_percent_tail(self):
        cones=[{'unique'}]+[{'shared'} for _ in range(19)]
        bands=expanded.distributions(cones,set(),61,'balanced-tail')
        self.assertEqual(bands['samples'],80)
        # Exactly 5% of next papers have zero coverage at every later position.
        # Sampling their identities unevenly would make this quantile jump to 1.
        for d in bands['known'][2:]:
            self.assertEqual(d['p05'],0)
            self.assertEqual(d['median'],1)

    def test_small_pool_bands_exact_against_permutations(self):
        cones=[{'a','b'},{'b','c','d'},{'e'},{'a','d'}];known={'a'}
        bands=expanded.distributions(cones,known,1,'exact')
        columns=[[] for _ in cones]
        for order in permutations(range(len(cones))):
            seen=set(known)
            for n,i in enumerate(order):
                columns[n].append(len(cones[i]&seen)/len(cones[i]));seen.update(cones[i])
        for expected,col in zip(bands['known'],columns):
            self.assertAlmostEqual(expected['p05'],expanded.original.quantile(col,.05))
            self.assertAlmostEqual(expected['p95'],expanded.original.quantile(col,.95))


if __name__=='__main__':unittest.main()
