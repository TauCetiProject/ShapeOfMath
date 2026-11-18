"""Concept overlap within a cohort of sources.

A cohort is a named, reproducible selection of catalogued sources, written as a
JSON file (see docs/COHORTS.md and cohorts/). This module resolves the selection
against the database and measures how the sources' prerequisite cones overlap.
It only reads the database.
"""
from collections import Counter, defaultdict
from contextlib import closing
from itertools import combinations
from pathlib import Path
from statistics import mean, median
import argparse
import json
import random
import sqlite3
import sys

import mathdb as m

ROLES = ('relies_on', 'introduces', 'explains', 'discusses')
PICK_KEYS = {'sources', 'identifiers', 'arxiv', 'doi'}
FILTER_KEYS = {'doi_prefixes', 'fields', 'years'}
COMBINE_KEYS = {'any', 'exclude', 'sample'}


def connect(path):
    """Open the catalogue for reading: a PostgreSQL URL or an existing SQLite file."""
    if not m.is_postgres_url(path) and not Path(path).is_file():
        raise ValueError('Database does not exist: ' + str(Path(path).resolve()))
    db = m.connect(path)
    if m.is_postgres(db):
        db.execute('SET default_transaction_read_only = on')
    return db


class Catalogue:
    """The parts of the database a cohort selection and analysis need."""

    def __init__(self, db):
        self.sources = {r['id']: dict(r) for r in db.execute(
            'SELECT id,slug,title,year,field,requirements_complete,introductions_complete FROM source')}
        self.by_slug = {r['slug']: ident for ident, r in self.sources.items()}
        self.identifiers = defaultdict(list)
        self.by_identifier = {}
        for r in db.execute('SELECT scheme,value,source_id FROM source_identifier ORDER BY scheme,value'):
            self.identifiers[r['source_id']].append((r['scheme'], r['value']))
            self.by_identifier[(r['scheme'], r['value'])] = r['source_id']
        self.concepts = {r['id']: dict(r) for r in db.execute(
            "SELECT id,slug,title,kind,statement_prerequisites_complete FROM concept WHERE status='active'")}
        self.parents = defaultdict(set)
        for r in db.execute("SELECT prerequisite_id,dependent_id FROM concept_dependency WHERE purpose IN ('statement','both')"):
            self.parents[r['dependent_id']].add(r['prerequisite_id'])
        self.links = defaultdict(list)
        for r in db.execute('SELECT source_id,concept_id,role FROM active_source_concept'):
            self.links[r['source_id']].append((r['concept_id'], r['role']))
        self.event = db.execute('SELECT coalesce(max(id),0) FROM curation_event').fetchone()[0]

    def cone(self, roots):
        """Statement prerequisite cone (statement and both edges), roots included."""
        found = set(roots)
        pending = list(roots)
        while pending:
            for parent in self.parents[pending.pop()] - found:
                found.add(parent)
                pending.append(parent)
        return found


def select(catalogue, selector, missing):
    """Resolve a selector to a set of source ids; unknown explicit entries go to missing."""
    if not isinstance(selector, dict):
        raise ValueError('A selector must be a JSON object')
    unknown = set(selector) - PICK_KEYS - FILTER_KEYS - COMBINE_KEYS
    if unknown:
        raise ValueError('Unknown selector keys: ' + ', '.join(sorted(unknown)))
    sets = []

    def explicit(entries):
        found = set()
        for scheme, value in entries:
            if scheme == 'slug':
                ident = catalogue.by_slug.get(value)
            else:
                try:
                    ident = catalogue.by_identifier.get(m.normalize_identifier(scheme, value))
                except ValueError:
                    ident = None
            if ident is None:
                missing.append(scheme + ':' + value)
            else:
                found.add(ident)
        return found

    if 'sources' in selector:
        sets.append(explicit(('slug', s) for s in selector['sources']))
    if 'identifiers' in selector:
        sets.append(explicit(tuple(s.split(':', 1)) for s in selector['identifiers']))
    if 'arxiv' in selector:
        sets.append(explicit(('arxiv', s) for s in selector['arxiv']))
    if 'doi' in selector:
        sets.append(explicit(('doi', s) for s in selector['doi']))
    if 'doi_prefixes' in selector:
        prefixes = tuple(p.lower() for p in selector['doi_prefixes'])
        sets.append({ident for ident, ids in catalogue.identifiers.items()
                     if any(s == 'doi' and v.startswith(prefixes) for s, v in ids)})
    if 'fields' in selector:
        fields = set(selector['fields'])
        sets.append({ident for ident, s in catalogue.sources.items() if s['field'] in fields})
    if 'years' in selector:
        low, high = selector['years']
        sets.append({ident for ident, s in catalogue.sources.items()
                     if s['year'] is not None and low <= s['year'] <= high})
    if 'any' in selector:
        sets.append(set().union(*(select(catalogue, child, missing) for child in selector['any'])))
    if not sets:
        raise ValueError('A selector needs at least one of: ' + ', '.join(sorted(PICK_KEYS | FILTER_KEYS | {'any'})))
    chosen = set.intersection(*sets)
    if 'exclude' in selector:
        chosen -= select(catalogue, selector['exclude'], [])
    if 'sample' in selector:
        sample = selector['sample']
        ordered = sorted(catalogue.sources[i]['slug'] for i in chosen)
        count = min(sample['count'], len(ordered))
        picked = random.Random(str(sample['seed'])).sample(ordered, count)
        chosen = {catalogue.by_slug[s] for s in picked}
    return chosen


def resolve(catalogue, cohort):
    """Return (all source ids, {group: ids}, missing explicit entries)."""
    missing = []
    groups = {name: select(catalogue, sel, missing) for name, sel in cohort.get('groups', {}).items()}
    if 'select' in cohort:
        chosen = select(catalogue, cohort['select'], missing)
        groups = {name: ids & chosen for name, ids in groups.items()}
    elif groups:
        chosen = set().union(*groups.values())
    else:
        raise ValueError('A cohort needs "select" or "groups"')
    return chosen, groups, sorted(set(missing))


def expected_growth(cones):
    """Exact mean union size after n sources, averaged over all orderings.

    With M sources and f_c the number of cones containing concept c,
    E[U_n] = sum_c (1 - C(M - f_c, n) / C(M, n)).
    """
    size = len(cones)
    histogram = Counter(Counter(c for cone in cones for c in cone).values())
    if not histogram:
        return [0.0] * (size + 1)
    top = max(histogram)
    curve = [0.0]
    for n in range(1, size + 1):
        # ratio(f) = C(M-f, n) / C(M, n), built up one factor at a time.
        ratio, total = 1.0, 0.0
        for f in range(1, top + 1):
            ratio *= max(size - n - f + 1, 0) / (size - f + 1)
            total += histogram.get(f, 0) * (1 - ratio)
        curve.append(total)
    return curve


def jaccard(a, b):
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def analyse(catalogue, cohort, roles=('relies_on',), top=20):
    if not roles or set(roles) - set(ROLES):
        raise ValueError('Roles must be among: ' + ', '.join(ROLES))
    chosen, groups, missing = resolve(catalogue, cohort)
    concepts = catalogue.concepts
    cones = {}
    sources = []
    for ident in sorted(chosen, key=lambda i: catalogue.sources[i]['slug']):
        source = catalogue.sources[ident]
        roots = {c for c, role in catalogue.links[ident] if role in roles and c in concepts}
        cone = catalogue.cone(roots)
        cones[ident] = cone
        sources.append({
            'slug': source['slug'], 'title': source['title'], 'year': source['year'],
            'identifiers': [s + ':' + v for s, v in catalogue.identifiers[ident]],
            'requirements_complete': bool(source['requirements_complete']),
            'introductions_complete': bool(source['introductions_complete']),
            'roots': len(roots), 'cone': len(cone),
            'unreviewed_in_cone': sum(not concepts[c]['statement_prerequisites_complete'] for c in cone)})
    frequency = Counter(c for cone in cones.values() for c in cone)
    union = set(frequency)
    slug = {i: catalogue.sources[i]['slug'] for i in chosen}
    pairs = [(jaccard(cones[a], cones[b]), slug[a], slug[b]) for a, b in combinations(sorted(cones), 2)]
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    values = [p[0] for p in pairs]
    group_unions = {name: set().union(*(cones[i] for i in ids)) if ids else set() for name, ids in groups.items()}
    return {
        'cohort': cohort.get('name', ''),
        'description': cohort.get('description', ''),
        'curation_event': catalogue.event,
        'root_roles': list(roles),
        'cone_rule': 'Roots plus all ancestors along statement and both edges; proof-only edges are not followed.',
        'missing_from_database': missing,
        'source_count': len(sources),
        'sources_without_roots': [s['slug'] for s in sources if not s['roots']],
        'sources_with_incomplete_requirements': [s['slug'] for s in sources if not s['requirements_complete']],
        'union_size': len(union),
        'unreviewed_in_union': sorted(concepts[c]['slug'] for c in union if not concepts[c]['statement_prerequisites_complete']),
        'shared_by': {str(k): v for k, v in sorted(Counter(frequency.values()).items())},
        'most_shared': [{'slug': concepts[c]['slug'], 'title': concepts[c]['title'], 'sources': k}
                        for c, k in sorted(frequency.items(), key=lambda x: (-x[1], concepts[x[0]]['slug']))[:top]],
        'pairwise_jaccard': {
            'pairs': len(pairs),
            'mean': mean(values) if values else None,
            'median': median(values) if values else None,
            'highest': [{'a': a, 'b': b, 'jaccard': round(j, 4)} for j, a, b in pairs[:top]]},
        'expected_union_growth': [round(x, 3) for x in expected_growth(list(cones.values()))],
        'groups': {name: {'sources': len(ids), 'union_size': len(group_unions[name]),
                          'unreviewed_in_union': sum(not concepts[c]['statement_prerequisites_complete'] for c in group_unions[name])}
                   for name, ids in groups.items()},
        'group_jaccard': [{'a': a, 'b': b, 'jaccard': round(jaccard(group_unions[a], group_unions[b]), 4)}
                          for a, b in combinations(sorted(groups), 2)],
        'sources': sources}


def summary(result):
    lines = [f"Cohort {result['cohort']}: {result['source_count']} sources (database event {result['curation_event']})",
             f"Roots: {', '.join(result['root_roles'])}; {result['cone_rule']}"]
    if result['missing_from_database']:
        lines.append(f"Not in database ({len(result['missing_from_database'])}): " + ', '.join(result['missing_from_database'][:10])
                     + (' ...' if len(result['missing_from_database']) > 10 else ''))
    lines += [f"Sources without recorded roots: {len(result['sources_without_roots'])}",
              f"Sources whose requirements are not certified complete: {len(result['sources_with_incomplete_requirements'])}",
              f"Union of cones: {result['union_size']} concepts, {len(result['unreviewed_in_union'])} with unreviewed statement prerequisites",
              'Concepts shared by exactly k sources: ' + ', '.join(f'k={k}: {v}' for k, v in result['shared_by'].items())]
    pairwise = result['pairwise_jaccard']
    if pairwise['pairs']:
        lines.append(f"Pairwise Jaccard over {pairwise['pairs']} pairs: mean {pairwise['mean']:.3f}, median {pairwise['median']:.3f}")
    growth = result['expected_union_growth']
    if len(growth) > 1:
        points = sorted({1, len(growth) // 4, len(growth) // 2, len(growth) - 1} - {0})
        lines.append('Expected union after n sources (all orderings): ' + ', '.join(f'n={n}: {growth[n]:.1f}' for n in points))
    if result['groups']:
        lines.append('Groups:')
        for name, g in result['groups'].items():
            lines.append(f"  {name}: {g['sources']} sources, union {g['union_size']}, unreviewed {g['unreviewed_in_union']}")
        for pair in result['group_jaccard']:
            lines.append(f"  {pair['a']} / {pair['b']}: Jaccard {pair['jaccard']:.3f}")
    lines.append('Most shared concepts:')
    lines += [f"  {c['sources']:4d}  {c['title']} ({c['slug']})" for c in result['most_shared']]
    lines.append('Sources (roots, cone, unreviewed in cone, requirements certified):')
    lines += [f"  {s['slug']}: {s['roots']}, {s['cone']}, {s['unreviewed_in_cone']}, {'yes' if s['requirements_complete'] else 'no'}"
              for s in result['sources']]
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('cohort', type=Path, help='Cohort JSON file')
    parser.add_argument('--db', type=m.database_arg, default=m.DEFAULT_DB)
    parser.add_argument('--roles', default='relies_on',
                        help='Comma-separated source roles that seed the cones (default relies_on)')
    parser.add_argument('--top', type=int, default=20, help='Number of most-shared concepts and closest pairs to list')
    parser.add_argument('--json', type=Path, help='Also write the full result to this JSON file')
    parser.add_argument('--list', action='store_true', help='Only list the selected sources')
    args = parser.parse_args(argv)
    try:
        cohort = json.loads(args.cohort.read_text())
        with closing(connect(args.db)) as db:
            catalogue = Catalogue(db)
        if args.list:
            chosen, _, missing = resolve(catalogue, cohort)
            for slug in sorted(catalogue.sources[i]['slug'] for i in chosen):
                print(slug)
            for entry in missing:
                print('missing', entry, file=sys.stderr)
            return 0
        result = analyse(catalogue, cohort, tuple(r.strip() for r in args.roles.split(',') if r.strip()), args.top)
    except (ValueError, OSError, KeyError, json.JSONDecodeError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(summary(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
