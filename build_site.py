"""Build a read-only static copy of the browser for publication.

The published site is the same single-page app as `mathdb_server.py`, reading a
snapshot written to `state.json` instead of the API. Editing controls are hidden;
edits continue to go through the local server or the audited API.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil

import mathdb as m
import mathdb_server as server

WEB = Path(__file__).resolve().parent / 'web'
ASSETS = ('app.js', 'cone.js', 'math-text.js', 'app.css')


def build(db_path: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        shutil.copyfile(WEB / name, out / name)
    index = (WEB / 'index.html').read_text()
    marker = '<html lang="en">'
    if marker not in index:
        raise ValueError('web/index.html no longer has the expected <html> tag')
    (out / 'index.html').write_text(index.replace(marker, '<html lang="en" class="static-site">', 1))
    with closing(m.connect(db_path)) as db:
        db.execute('BEGIN')
        state = server.read_api(db, ['state'], {})
    (out / 'state.json').write_text(json.dumps(state, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
    # GitHub Pages: serve files as-is, without Jekyll processing.
    (out / '.nojekyll').write_text('')
    return state['stats']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=m.DEFAULT_DB)
    parser.add_argument('--out', type=Path, default=Path('_site'))
    args = parser.parse_args(argv)
    stats = build(args.db, args.out)
    print(f"Wrote {args.out}: {stats['active_concepts']} concepts, {stats['sources']} sources")


if __name__ == '__main__':
    main()
