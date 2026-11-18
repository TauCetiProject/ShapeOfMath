"""Check that the Cloudflare Worker and mathdb_server.py return the same public API.

    python tests/compare_worker.py http://127.0.0.1:8123 http://127.0.0.1:8787 --database URL

Both servers must read the same collection. The script compares stats, a sample
of concept and source slices, and sidebar searches, as parsed JSON (so 2 and 2.0
are equal). It exits 1 and lists the paths that differ.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mathdb as m  # noqa: E402


def get(base, path):
    # Cloudflare's bot protection rejects Python's default User-Agent.
    request = Request(base.rstrip('/') + path, headers={'User-Agent': 'shapeofmath-compare/1.0'})
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def paths(database, sample, seed=0):
    db = m.connect(database)
    rng = random.Random(seed)
    concepts = [r[0] for r in db.execute("SELECT slug FROM concept WHERE status='active' ORDER BY slug")]
    sources = [r[0] for r in db.execute('SELECT slug FROM source ORDER BY slug')]
    out = ['/api/v1/stats']
    out += ['/api/v1/view/concept/' + quote(s, safe='') for s in rng.sample(concepts, min(sample, len(concepts)))]
    out += ['/api/v1/view/source/' + quote(s, safe='') for s in rng.sample(sources, min(sample // 2, len(sources)))]
    for kind, q in [('concept', ''), ('concept', 'drinfeld'), ('concept', 'Hilbert space'), ('concept', '50%'),
                    ('source', ''), ('source', 'morrison'), ('source', '2015')]:
        out.append('/api/v1/search?' + urlencode({'kind': kind, 'q': q, 'limit': 200}))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('reference', help='mathdb_server.py base URL')
    parser.add_argument('worker', help='Worker base URL')
    parser.add_argument('--database', default=m.DEFAULT_DB, help='collection both servers read')
    parser.add_argument('--sample', type=int, default=100)
    args = parser.parse_args(argv)
    checked, differ = 0, []
    for path in paths(args.database, args.sample):
        checked += 1
        if get(args.reference, path) != get(args.worker, path):
            differ.append(path)
    print(json.dumps({'checked': checked, 'differ': differ}, indent=1))
    return 1 if differ else 0


if __name__ == '__main__':
    sys.exit(main())
