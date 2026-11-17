from collections import Counter
import importlib.util
from itertools import permutations
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / 'experiments/curation-2015/overlap/analyse.py'
spec = importlib.util.spec_from_file_location('cone_overlap', path)
overlap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlap)


class ConeOverlapTests(unittest.TestCase):
    def test_exact_means_and_distributions_match_every_permutation(self):
        cones = [{'shared','ab','a'}, {'shared','ab','b'}, {'shared','c'}, set()]
        cumulative, marginal, _ = overlap.exact_means(cones)
        totals=[[] for _ in cones]; additions=[[] for _ in cones]
        for order in permutations(range(len(cones))):
            known=set()
            for n, i in enumerate(order):
                additions[n].append(len(cones[i] - known))
                known |= cones[i]; totals[n].append(len(known))
        bands=overlap.bands(cones, 10, 'test')
        for n in range(len(cones)):
            self.assertAlmostEqual(cumulative[n+1],sum(totals[n])/len(totals[n]))
            self.assertAlmostEqual(marginal[n],sum(additions[n])/len(additions[n]))
            self.assertAlmostEqual(bands['cumulative'][n]['distribution_mean'],cumulative[n+1])
            self.assertAlmostEqual(bands['marginal'][n]['distribution_mean'],marginal[n])
            # Marginal distributions have repeated observations in the full
            # permutation enumeration; compare their exact probability masses.
            size=len(cones); frequencies=Counter(c for cone in cones for c in cone)
            if n==size-1:
                self.assertAlmostEqual(marginal[n],sum(f==1 for f in frequencies.values())/size)

    def test_sum_of_marginals_is_union_and_means_decrease(self):
        cones=[{'common',str(i),str(i//2)} for i in range(10)]
        cumulative,marginal,_=overlap.exact_means(cones)
        self.assertAlmostEqual(sum(marginal),len(set().union(*cones)))
        self.assertEqual(cumulative[0],0)
        self.assertTrue(all(a>=b for a,b in zip(marginal,marginal[1:])))

    def test_combined_sampled_bands_have_exact_endpoints_and_are_reproducible(self):
        cones=[{'common',str(i)} for i in range(11)]
        a=overlap.bands(cones, 20, 'seed');b=overlap.bands(cones, 20, 'seed')
        self.assertEqual(a,b)
        self.assertEqual(a['marginal'][0]['distribution_mean'],2)
        self.assertEqual(a['marginal'][-1]['distribution_mean'],1)
        self.assertEqual(a['cumulative'][-1]['p05'],12)
        self.assertEqual(a['cumulative'][-1]['p95'],12)

    def test_balanced_means_match_every_cycle_order(self):
        cones=[{'a','x'},{'a','y'},{'b','x'},{'b','z'}]
        categories=['A','A','B','B']
        totals=[[] for _ in cones]
        # Exactly one member of each field in each two-paper cycle.
        for order in permutations(range(4)):
            if any({categories[i] for i in order[start:start+2]}!={'A','B'} for start in (0,2)):
                continue
            known=set()
            for n,i in enumerate(order):
                known|=cones[i];totals[n].append(len(known))
        means=overlap.balanced_mean(cones,categories)
        for n,col in enumerate(totals):self.assertAlmostEqual(means[n+1],sum(col)/len(col))

    def test_order_averaged_paper_additions_sum_to_union(self):
        cones=[{'a','b'},{'b','c'},{'b','c','d'}]
        frequency=Counter(c for cone in cones for c in cone)
        contributions=[sum(1/frequency[c] for c in cone) for cone in cones]
        self.assertAlmostEqual(sum(contributions),len(frequency))

    def test_quantile_range_contains_at_least_ninety_percent_of_discrete_mass(self):
        for values in (list(range(10)), [1]*7+[2]*3, list(range(30))):
            low=overlap.quantile(values,.05);high=overlap.quantile(values,.95)
            self.assertGreaterEqual(sum(low<=v<=high for v in values)/len(values),.9)
