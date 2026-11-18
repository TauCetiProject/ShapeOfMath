"""Benchmark cone queries and cycle checks on a synthetic collection at scale.

    python bench_scale.py stats --copies 100 --cross 0.2      # cone sizes, offline
    python bench_scale.py load URL --copies 100 --cross 0.2   # into an empty database
    python bench_scale.py run URL                             # timings

The synthetic collection replicates the real one (`--sqlite`): concepts with at
least ten direct dependents form a shared core, every other concept is copied
once per field, and a fraction `--cross` of the copied edges point into another
field. Numbering follows the real topological order, so the result is acyclic.
It is a load test, not a model of how mathematics grows.
"""
from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path
import json
import random
import statistics
import sys
import time

import mathdb as m


def real_graph(path):
    """Edges of an existing SQLite collection, renumbered in a topological order."""
    import sqlite3
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    ids = [r[0] for r in db.execute("SELECT id FROM concept WHERE status='active' ORDER BY id")]
    edges = db.execute('SELECT prerequisite_id,dependent_id,purpose FROM concept_dependency').fetchall()
    index = {c: i for i, c in enumerate(ids)}
    children = [[] for _ in ids]
    indegree = [0] * len(ids)
    for p, d, _ in edges:
        children[index[p]].append(index[d])
        indegree[index[d]] += 1
    order, ready = [], deque(i for i, k in enumerate(indegree) if k == 0)
    while ready:
        i = ready.popleft()
        order.append(i)
        for c in children[i]:
            indegree[c] -= 1
            if indegree[c] == 0:
                ready.append(c)
    rank = {old: new for new, old in enumerate(order)}
    return len(ids), [(rank[index[p]], rank[index[d]], purpose) for p, d, purpose in edges]


def generate(path, copies, cross, seed=0, core_dependents=10):
    """Replicate a real graph `copies` times around its shared core.

    Concepts with at least `core_dependents` direct dependents form one shared
    core. Every other concept is copied once per field. A fraction `cross` of the
    edges between copied concepts point into another field's copy instead.
    Concept i of field f is numbered so that numbers respect the original
    topological order; every edge goes from a smaller to a larger number.
    """
    n, edges = real_graph(path)
    dependents = [0] * n
    for p, d, _ in edges:
        dependents[p] += 1
    core = [i for i in range(n) if dependents[i] >= core_dependents]
    is_core = set(core)
    rest = [i for i in range(n) if i not in is_core]
    # Number by (original rank, field) so cross-field edges stay acyclic.
    number, k = {}, 0
    for i in range(n):
        if i in is_core:
            number[(i, 0)] = k; k += 1
        else:
            for f in range(copies):
                number[(i, f)] = k; k += 1
    rng = random.Random(seed)
    out = []
    for f in range(copies):
        for p, d, purpose in edges:
            if d in is_core:
                if f == 0:
                    out.append((number[(p, 0)], number[(d, 0)], purpose))
                continue
            pf = 0 if p in is_core else (rng.randrange(copies) if rng.random() < cross else f)
            out.append((number[(p, pf)], number[(d, f)], purpose))
    out = list({(p, d): (p, d, purpose) for p, d, purpose in out}.values())
    parents = [[] for _ in range(k)]
    for p, d, purpose in out:
        parents[d].append((p, purpose))
    return parents


def cone_size(parents, i):
    seen = {i}
    queue = deque([i])
    while queue:
        for p, purpose in parents[queue.popleft()]:
            if purpose not in ('statement', 'both'):
                continue
            if p not in seen:
                seen.add(p)
                queue.append(p)
    return len(seen)


def stats(parents, seed=1, sample=300):
    n = len(parents)
    rng = random.Random(seed)
    sizes = sorted(cone_size(parents, rng.randrange(n)) for _ in range(sample))
    q = lambda f: sizes[min(len(sizes) - 1, int(f * len(sizes)))]
    return {'concepts': n, 'edges': sum(map(len, parents)), 'statement_cone_median': q(.5), 'p90': q(.9),
            'p99': q(.99), 'max_sampled': sizes[-1], 'last_concept': cone_size(parents, n - 1)}


def concept_id(i):
    return f'00000000-0000-0000-0000-{i:012d}'


def load(url, parents):
    n = len(parents)
    kinds = ['definition'] * n
    for i, ps in enumerate(parents):
        if any(purpose in ('proof', 'both') for _, purpose in ps):
            kinds[i] = 'theorem'
    db = m.connect(url)
    m.initialize(db)
    raw = db._conn
    started = time.time()
    with raw.transaction():
        for table in ('concept', 'concept_dependency'):
            raw.execute(f'ALTER TABLE {table} DISABLE TRIGGER USER')
        with raw.cursor() as cur, cur.copy('COPY concept (id,slug,title,kind,description,field,statement_prerequisites_complete) FROM STDIN') as copy:
            for i in range(n):
                copy.write_row((concept_id(i), f'c{i}', f'Concept {i}', kinds[i], f'Synthetic concept {i}.', 'Synthetic', 1))
        edge = 0
        with raw.cursor() as cur, cur.copy('COPY concept_dependency (id,prerequisite_id,dependent_id,basis,rationale,purpose) FROM STDIN') as copy:
            for i, ps in enumerate(parents):
                for p, purpose in ps:
                    edge += 1
                    copy.write_row((edge, concept_id(p), concept_id(i), 'logical', 'Synthetic.', purpose))
        raw.execute("SELECT setval(pg_get_serial_sequence('concept_dependency','id'), %s)", (edge + 1,))
        for table in ('concept', 'concept_dependency'):
            raw.execute(f'ALTER TABLE {table} ENABLE TRIGGER USER')
    raw.execute('ANALYZE concept')
    raw.execute('ANALYZE concept_dependency')
    db.close()
    return {'concepts': n, 'edges': edge, 'seconds': round(time.time() - started, 1)}


def run(url, samples=40, seed=2):
    db = m.connect(url)
    n = db.execute('SELECT count(*) FROM concept').fetchone()[0]
    rng = random.Random(seed)
    out = {'concepts': n, 'cone': [], 'cycle_check': []}
    # Random concepts, plus those with the most direct prerequisites (large cones).
    busiest = [int(r[0][1:]) for r in db.execute("""SELECT c.slug FROM concept_dependency d JOIN concept c ON c.id=d.dependent_id
        GROUP BY c.slug ORDER BY count(*) DESC LIMIT 10""")]
    for i in sorted(rng.randrange(n) for _ in range(samples)) + busiest:
        for mode in ('statement', 'all'):
            t = time.time()
            cone = m.prerequisite_cone(db, f'c{i}', mode)
            out['cone'].append({'concept': i, 'mode': mode, 'nodes': len(cone['nodes']), 'edges': len(cone['edges']),
                                'seconds': round(time.time() - t, 3)})
    # Cycle checks: a new edge between existing concepts, rolled back.
    # The trigger walks the new prerequisite's cone: tiny for a foundational
    # prerequisite, largest for a deep one. The last case closes a real cycle:
    # the root of the largest cone above one of its own leaves.
    root = max(busiest, key=lambda i: len(m.prerequisite_cone(db, f'c{i}', 'all')['nodes']))
    leaf = int(m.prerequisite_cone(db, f'c{root}', 'all')['leaves'][0][1:])
    for p, d in [(0, n - 1), (n // 2, n - 1), (leaf, root), (root, leaf)]:
        t = time.time()
        outcome = 'accepted'
        try:
            with db:
                db.execute("""INSERT INTO concept_dependency(prerequisite_id,dependent_id,basis,rationale,purpose)
                    VALUES (?,?, 'logical','Benchmark.','statement') ON CONFLICT DO NOTHING""", (concept_id(p), concept_id(d)))
                raise KeyboardInterrupt  # roll back
        except KeyboardInterrupt:
            pass
        except Exception as ex:  # the expected cycle rejection
            outcome = str(ex)
        out['cycle_check'].append({'prerequisite': p, 'dependent': d, 'outcome': outcome, 'seconds': round(time.time() - t, 3)})
    db.close()
    largest = max(out['cone'], key=lambda c: c['nodes'])
    times = [c['seconds'] for c in out['cone']]
    out['summary'] = {'cones': len(times), 'cone_nodes_median': statistics.median(c['nodes'] for c in out['cone']),
                      'cone_seconds_median': statistics.median(times), 'cone_seconds_max': max(times),
                      'largest_cone': largest}
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('stats', 'load', 'run'))
    parser.add_argument('url', nargs='?')
    parser.add_argument('--sqlite', default=str(m.ROOT / 'data' / 'math.sqlite'), help='real collection to replicate')
    parser.add_argument('--copies', type=int, default=100)
    parser.add_argument('--cross', type=float, default=0.0, help='fraction of edges pointing into another field')
    args = parser.parse_args(argv)
    if args.command == 'run':
        result = run(args.url)
    else:
        parents = generate(args.sqlite, args.copies, args.cross)
        result = stats(parents) if args.command == 'stats' else load(args.url, parents)
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    sys.exit(main())
