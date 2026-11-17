"""Report mechanical coverage/completion and allocation checks for the frozen run."""
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import mathdb as m

RUN=Path(__file__).resolve().parent


def save(name,data):
    path=RUN/name
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    temp.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--final',action='store_true',help='Require every scoped pair to have a current reviewed disposition')
    args=parser.parse_args()
    baseline=json.loads((RUN/'baseline.json').read_text())
    plan=json.loads((RUN/'plan.json').read_text())
    roster={c['id']:c for c in baseline['concepts']}
    expected={(c['id'],lib) for c in baseline['concepts'] for lib in plan['libraries']}
    receipts=[json.loads(p.read_text()) for p in sorted((RUN/'imported').glob('batch-???.json'))]
    digest_errors=[]
    for receipt in receipts:
        path=RUN/'proposals'/(receipt['batch_id']+'.json')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=receipt['proposal_sha256']:
            digest_errors.append(receipt['batch_id'])
    with closing(m.connect()) as live,closing(m.connect(':memory:')) as db:
        live.backup(db)
        stats=m.verify(db)
        report=m.formalizations(db)
        all_records={(r['concept_id'],r['library']):r for r in report}
        scoped=[r for r in report if (r['concept_id'],r['library']) in expected]
        missing=[]
        retired=[]
        stale=[]
        completed=[]
        for ident,lib in sorted(expected):
            r=all_records.get((ident,lib))
            old=roster[ident]
            if r is None:
                retired.append(dict(concept_id=ident,concept=old['slug'],library=lib,reason='Baseline identity is no longer active; requires explicit handling.'))
            elif r['review_id'] is None:
                missing.append(dict(concept_id=ident,concept=old['slug'],library=lib))
            elif r['review_needed']:
                stale.append(dict(concept_id=ident,concept=old['slug'],library=lib,review_id=r['review_id']))
            else:
                completed.append(r)
        unresolved=[r for r in completed if r['status'] in ('unknown','partial')]
        positive_missing_counts=[dict(concept=r['concept'],library=r['library']) for r in completed
                                 if r['status'] in ('formalized','partial') and r['estimated_loc'] is None]
        # All active mappings, including outside-scope ones, share each file.
        allocation=[]
        for lib in plan['libraries']:
            raw=db.execute('SELECT coalesce(sum(loc),0) FROM formalization_file_allocation WHERE library_slug=?',(lib,)).fetchone()[0]
            shares=sum(r['known_loc'] or 0 for r in report if r['library']==lib)
            ok=math.isclose(raw,shares,rel_tol=1e-11,abs_tol=1e-7)
            allocation.append(dict(library=lib,mapped_measured_file_loc=raw,sum_allocated_known_loc=shares,conserved=ok))
        additions=[dict(r) for r in db.execute("SELECT id,slug,title,revision FROM concept WHERE status='active' ORDER BY slug") if r['id'] not in roster]
        counts={lib:dict(Counter(r['status'] for r in completed if r['library']==lib)) for lib in plan['libraries']}
        statements=[dict(concept=r['concept'],library=r['library'],status=r['status']) for r in completed
                    if r['statement_only'] and r['status'] in ('formalized','inherited','partial')]
        pilot_changes=[]
        for old in baseline['existing_formalizations']:
            new=all_records.get((old['concept_id'],old['library']))
            if new:
                pilot_changes.append(dict(concept=old['concept'],library=old['library'],previous_loc=old['estimated_loc'],current_loc=new['estimated_loc'],
                    status_changed=old['status']!=new['status'],files_changed={f['path'] for f in old['files']}!={f['path'] for f in new['files']}))
        complete=(len(receipts)==len(plan['jobs']) and not missing and not retired and not stale and not digest_errors
                  and not positive_missing_counts and all(a['conserved'] for a in allocation))
        summary=dict(updated_at=datetime.now(timezone.utc).isoformat(),run_complete=complete,
                     baseline_concepts=len(roster),baseline_pairs=len(expected),processed_current_pairs=len(completed),
                     imported_expansion_jobs=len(receipts),total_expansion_jobs=len(plan['jobs']),
                     status_counts=counts,conjecture_statement_only_pairs=statements,unreviewed_pairs=len(missing),stale_pairs=len(stale),retired_pairs=len(retired),
                     unresolved_reviewed_pairs=len(unresolved),concurrent_new_concepts_outside_scope=len(additions),
                     positive_pairs_missing_measurements=positive_missing_counts,proposal_digest_errors=digest_errors,
                     allocation_checks=allocation,existing_pilot_loc_changes=pilot_changes,
                     pinned_revisions=plan['revisions'],tau_mathlib_dependency=plan['tau_mathlib_dependency'],database_stats=stats,
                     method='Source-based author judgments and independent mathematical review in subagents; coordinator mechanical validation/import. No fresh Lean rebuild or transitive axiom audit.')
        save('summary.json',summary)
        save('unresolved-reviewed.json',unresolved)
        save('unreviewed-pairs.json',missing)
        save('stale-reviews.json',stale)
        save('retired-pairs.json',retired)
        save('concurrent-additions.json',additions)
        if complete:
            file_ids={f['id'] for r in completed for f in r['files']}
            files=[dict(r) for r in db.execute('SELECT * FROM formalization_file ORDER BY library_slug,path') if r['id'] in file_ids]
            batch=dict(note='Completed independently reviewed full frozen-catalogue formalization update. Re-review before replay over later meanings.',
                       formalization_libraries=[dict(slug=r['slug'],name=r['name'],repository_url=r['repository_url'])
                                               for r in db.execute('SELECT * FROM formalization_library') if r['slug'] in plan['libraries']],
                       formalization_files=[dict(library=f['library_slug'],**{k:f[k] for k in ('path','loc','revision','sha256','measured_at')}) for f in files],
                       formalizations=[dict(concept=r['concept'],library=r['library'],status=r['status'],evidence=r['evidence'],
                           files=[{k:f[k] for k in ('path','declarations','note')} for f in r['files']]) for r in completed])
            save('reviewed-batch.json',batch)
    lines=['FORMALIZATION COVERAGE UPDATE — '+('COMPLETE PASS' if complete else 'IN PROGRESS'),'',
           f"Frozen baseline: {len(roster)} active concepts / {len(expected)} Mathlib+Tau Ceti pairs.",
           f"Current reviewed dispositions: {len(completed)}; imported expansion jobs: {len(receipts)}/{len(plan['jobs'])}.",
           f"Unreviewed: {len(missing)}; stale: {len(stale)}; retired requiring handling: {len(retired)}.",
           f"Explicitly unresolved after review (unknown or partial): {len(unresolved)}.",
           f"Concepts added concurrently outside the frozen scope: {len(additions)}.",'',
           'STATUS COUNTS BY LIBRARY (only current reviewed baseline pairs)']
    for lib,c in counts.items():lines.append(lib+': '+json.dumps(c,sort_keys=True))
    lines+=['',f'Positive conjecture-statement records: {len(statements)}. These are statement coverage only; no conjecture proof or truth is claimed.','','ALLOCATION CHECKS']
    for a in allocation:lines.append(a['library']+': '+str(a['mapped_measured_file_loc'])+' mapped measured lines; '+str(a['sum_allocated_known_loc'])+' allocated known LOC; conserved='+str(a['conserved']))
    lines+=['','Unknown is not absence; partial is not the full endpoint. Inherited-only availability has zero native LOC; unknown has no estimate.',
            'Estimates divide whole-file physical LOC among all current mapped active concepts, including mappings outside this run.',
            'Original pilot numbers can change through newly shared file allocations even if their source bytes and file selections are unchanged.',
            '',summary['method'],'',
            'See summary.json, unresolved-reviewed.json, unreviewed-pairs.json, proposals/, reviews/ and imported/ for the reproducible audit trail.','']
    (RUN/'summary.txt').write_text('\n'.join(lines))
    print(json.dumps({k:summary[k] for k in ('run_complete','processed_current_pairs','baseline_pairs','imported_expansion_jobs','unreviewed_pairs','stale_pairs','retired_pairs','unresolved_reviewed_pairs','allocation_checks')},indent=2))
    if args.final and not complete:
        raise SystemExit('Run is not complete; continue the queued work/rechecks rather than certifying this snapshot.')


if __name__=='__main__':
    main()
