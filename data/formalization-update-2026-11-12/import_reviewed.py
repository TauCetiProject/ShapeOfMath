"""Mechanical validator/importer for independently reviewed coverage batches.

Mathematical judgments come exclusively from the author and independent reviewer.
This script checks their identities/digests, roster, revisions, paths and exact
committed byte measurements, then applies accepted results through mathdb's API.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import mathdb as m

RUN = Path(__file__).resolve().parent
PLAN = json.loads((RUN / 'plan.json').read_text())
BASELINE = json.loads((RUN / 'baseline.json').read_text())
ROSTER = {r['slug']: r for r in BASELINE['concepts']}
REPOSITORIES = {'mathlib': Path('/home/kim/mathlib4'), 'tau-ceti': Path('/home/kim/TauCeti')}
REVISION = PLAN['revisions']
STATUSES = {'formalized', 'partial', 'inherited', 'not_formalized', 'unknown'}
ALLOWED_TABLES = {'formalization_library', 'formalization_file', 'concept_formalization', 'concept_formalization_file', 'curation_event'}


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def pair(row):
    return row['concept'], row['library']


def fingerprints(db):
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") if r[0] not in ALLOWED_TABLES]
    return {t: hashlib.sha256(repr([tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY rowid')]).encode()).hexdigest() for t in tables}


def measurements(reviews):
    result = []
    for library, path in sorted({(r['library'], f['path']) for r in reviews for f in r['files']}):
        m.formalization_path(path)
        sha = REVISION[library]
        repo = REPOSITORIES[library]
        mode = subprocess.run(['git', '-C', str(repo), 'ls-tree', sha, '--', path], check=True, capture_output=True).stdout.split()
        if not mode or mode[0] not in (b'100644', b'100755'):
            raise ValueError(f'Not a regular committed native file: {library}/{path}')
        content = subprocess.run(['git', '-C', str(repo), 'show', sha + ':' + path], check=True, capture_output=True).stdout
        result.append(dict(library=library, path=path, revision=sha,
                           loc=content.count(b'\n') + int(bool(content) and not content.endswith(b'\n')),
                           sha256=hashlib.sha256(content).hexdigest(), measured_at=now()))
    return result


def context_records(job):
    contexts = {c['slug']: c for c in job['concepts']}
    for slug, c in contexts.items():
        if c != ROSTER[slug]:
            raise ValueError('Original job roster differs from the frozen baseline')
    recheck_path = RUN / 'rechecks' / (job['id'] + '-input.json')
    if recheck_path.exists():
        recheck = json.loads(recheck_path.read_text())
        original = (RUN / 'jobs' / (job['id'] + '.json')).read_bytes()
        if recheck['parent_job_sha256'] != hashlib.sha256(original).hexdigest():
            raise ValueError('Recheck input does not match original job bytes')
        for entry in recheck['changes']:
            old, current = entry['baseline'], entry['current']
            if old != contexts[old['slug']] or current['id'] != old['id'] or current['slug'] != old['slug']:
                raise ValueError('Recheck changed a frozen concept identity')
            contexts[current['slug']] = current
    return contexts


def validate_record(row, expected, contexts=None):
    if pair(row) not in expected:
        raise ValueError(f'Unexpected concept/library pair: {pair(row)}')
    c = (contexts or ROSTER)[row['concept']]
    if row.get('concept_id') != c['id'] or row.get('concept_revision') != c['revision']:
        raise ValueError(f'Proposal baseline identity/revision mismatch: {pair(row)}')
    if row['status'] not in STATUSES or not isinstance(row['evidence'], str) or not row['evidence'].strip():
        raise ValueError(f'Invalid status/evidence: {pair(row)}')
    if not isinstance(row['files'], list) or bool(row['files']) != (row['status'] in ('formalized', 'partial')):
        raise ValueError(f'Invalid native file set for status: {pair(row)}')
    paths = []
    for f in row['files']:
        m.require_fields(f, ('path', 'declarations', 'note'), ('path', 'declarations', 'note'))
        m.formalization_path(f['path'])
        if not isinstance(f['declarations'], str) or not f['declarations'].strip() or not isinstance(f['note'], str) or not f['note'].strip():
            raise ValueError(f'Missing declaration anchor/contribution note: {pair(row)}')
        paths.append(f['path'])
    if len(set(paths)) != len(paths):
        raise ValueError(f'Duplicate file paths: {pair(row)}')


def prepare(job):
    proposal_path = RUN / 'proposals' / (job['id'] + '.json')
    review_path = RUN / 'reviews' / (job['id'] + '.json')
    raw = proposal_path.read_bytes()
    proposal = json.loads(raw)
    review = json.loads(review_path.read_text())
    for obj in (proposal, review):
        if obj.get('batch_id', obj.get('followup_id')) != job['id']:
            raise ValueError('Batch ID mismatch')
    if proposal.get('author') != job['author'] or review.get('reviewer') != job['reviewer'] or job['author'] == job['reviewer']:
        raise ValueError('Author/reviewer independence mismatch')
    digest = hashlib.sha256(raw).hexdigest()
    if review.get('proposal_sha256') != digest:
        raise ValueError('Independent review does not match proposal bytes')
    contexts = context_records(job)
    expected = {(c['slug'], library) for c in job['concepts'] for library in job['libraries']}
    proposed = proposal['reviews']
    decisions = review['decisions']
    if len(proposed) != len(expected) or {pair(r) for r in proposed} != expected:
        raise ValueError('Proposal does not cover the exact assigned roster')
    if len(decisions) != len(expected) or {pair(r) for r in decisions} != expected:
        raise ValueError('Review does not cover the exact proposal roster')
    by_pair = {pair(r): r for r in proposed}
    accepted = []
    for decision in decisions:
        if decision.get('decision') not in ('accept', 'change', 'reject') or not decision.get('reason', '').strip():
            raise ValueError('Missing independent mathematical decision/reason')
        if decision['decision'] == 'reject':
            raise ValueError(f"Mathematical review rejected {pair(decision)}: {decision['reason']}")
        row = decision['replacement'] if decision['decision'] == 'change' else by_pair[pair(decision)]
        if pair(row) != pair(decision):
            raise ValueError('Replacement changed the reviewed pair')
        validate_record(row, expected, contexts)
        accepted.append(row)
    return accepted, digest, contexts


def import_one(job):
    accepted, digest, contexts = prepare(job)
    counts = measurements(accepted)
    # Add run/source context mechanically; it does not change the mathematical
    # review decision. Preserve each source-search account in the saved evidence.
    rows = []
    for r in accepted:
        evidence = r['evidence']
        if r.get('search_notes'):
            evidence += '\nSearch and boundary notes: ' + r['search_notes']
        evidence += f"\nCoverage update source snapshot: {r['library']} {REVISION[r['library']]}."
        if r['library'] == 'tau-ceti':
            evidence += ' Its pinned Mathlib dependency is ' + PLAN['tau_mathlib_dependency'] + '.'
        evidence += '\nAuthor/reviewer decisions: data/formalization-update-2026-11-12/reviews/' + job['id'] + '.json.'
        rows.append({k:r[k] for k in ('concept','library','status','files')} | {'evidence':evidence})
    batch = dict(note=f"Whole-catalogue formalization update {job['id']}: independent source review by {job['reviewer']} of {job['author']} proposals.",
                 formalizations=rows, formalization_files=counts)
    with closing(m.connect()) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            for r in accepted:
                current = m.lookup(db, 'concept', r['concept'])
                c = contexts[r['concept']]
                if current['id'] != c['id'] or current['revision'] != c['revision'] or current['status'] != 'active':
                    raise ValueError(f"Live concept changed since baseline; mathematical re-review required: {r['concept']}")
            before = fingerprints(db)
            # Shared measurements already pinned to the same content do not need
            # redundant audit events or fabricated measurement timestamps.
            needed = []
            for f in counts:
                old = db.execute('SELECT * FROM formalization_file WHERE library_slug=? AND path=?', (f['library'],f['path'])).fetchone()
                if old is None or any(old[k] != f[k] for k in ('revision','loc','sha256')):
                    needed.append(f)
            batch['formalization_files'] = needed
            m.ingest(db, batch)
            if fingerprints(db) != before:
                raise ValueError('Unrelated mathematical tables changed during coverage import')
            stats = m.verify(db)
            history = db.execute('SELECT max(id) FROM curation_event').fetchone()[0]
    receipt = dict(batch_id=job['id'], imported_at=now(), proposal_sha256=digest,
                   author=job['author'],reviewer=job['reviewer'],pairs=len(accepted),
                   status_counts={s:sum(r['status']==s for r in accepted) for s in sorted(STATUSES)},
                   selected_files=len(counts),measurements_updated=len(batch['formalization_files']),
                   history_version=history,unrelated_tables_preserved=True,
                   context_rechecks={slug:dict(baseline_revision=ROSTER[slug]['revision'],reviewed_revision=c['revision'])
                                     for slug,c in contexts.items() if c['revision'] != ROSTER[slug]['revision']})
    write_json(RUN/'imported'/(job['id']+'.json'),receipt)
    write_json(RUN/'imported'/(job['id']+'-batch.json'),batch)
    return receipt


def main():
    imported, errors = [], []
    for summary in PLAN['jobs']:
        ident=summary['id']
        if (RUN/'imported'/(ident+'.json')).exists():
            continue
        if not (RUN/'proposals'/(ident+'.json')).exists() or not (RUN/'reviews'/(ident+'.json')).exists():
            continue
        job=json.loads((RUN/'jobs'/(ident+'.json')).read_text())
        try:
            receipt=import_one(job)
            imported.append(receipt)
        except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, subprocess.CalledProcessError) as ex:
            errors.append(dict(batch_id=ident,error=str(ex)))
    write_json(RUN/'import-errors.json',errors)
    receipts=[json.loads(p.read_text()) for p in sorted((RUN/'imported').glob('batch-???.json'))]
    progress=dict(updated_at=now(),baseline_concepts=PLAN['baseline_concepts'],baseline_pairs=PLAN['baseline_pairs'],
                  expansion_jobs=len(PLAN['jobs']),proposals=len(list((RUN/'proposals').glob('batch-???.json'))),
                  independent_reviews=len(list((RUN/'reviews').glob('batch-???.json'))),
                  imported_jobs=len(receipts),imported_expansion_pairs=sum(r['pairs'] for r in receipts),
                  status_counts={s:sum(r['status_counts'].get(s,0) for r in receipts) for s in sorted(STATUSES)},
                  errors=errors)
    write_json(RUN/'progress.json',progress)
    print(json.dumps(dict(imported_now=[r['batch_id'] for r in imported],**progress),indent=2))


if __name__=='__main__':
    main()
