"""Apply and report a reviewable, reproducible recursive prerequisite experiment."""
import argparse
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path

import mathdb as m

PLAN=m.ROOT/'data/recursive-expansion.json'


def merge_into_seed(payload,plan):
    """Project the reviewed definitions/edges into a fresh ingestion seed.

    Review certifications remain explicit curation events, applied separately.
    """
    batch=plan['batch']
    for table in ('sources','concepts'):
        existing={r['slug'] for r in payload[table]}
        payload[table].extend(copy.deepcopy(r) for r in batch[table] if r['slug'] not in existing)
    known={r['slug']:r for r in payload['concepts']}
    for revision in plan['revisions']:
        record=known[revision['concept']]
        if 'title' in revision['changes'] and revision['changes']['title']!=record['title']:
            record.setdefault('aliases',[]).append(record['title'])
        record.update(revision['changes'])
    edges={(e['prerequisite'],e['dependent']):e for e in payload['dependencies']}
    for e in batch['dependencies']:
        edges.setdefault((e['prerequisite'],e['dependent']),copy.deepcopy(e))
    for e in plan['remove_dependencies']:
        edges.pop((e['prerequisite'],e['dependent']),None)
    payload['dependencies']=list(edges.values())
    linked={(e['source'],e['concept'],m.canonical_role(e['role']),e['locator']) for e in payload['source_concepts']}
    for link in batch['source_concepts']:
        key=(link['source'],link['concept'],link['role'],link['locator'])
        if key not in linked:
            payload['source_concepts'].append(copy.deepcopy(link));linked.add(key)
    from curate_dependency_purposes import annotate_edges
    annotate_edges(payload['dependencies'])
    # Compute the same reduction as live curation without depending on the live DB.
    with closing(m.connect(':memory:')) as db:
        m.initialize(db);m.ingest(db,payload)
        removed=set()
        ids={r['id']:r['slug'] for r in db.execute('SELECT id,slug FROM concept')}
        for root in plan['roots']:
            for item in m.reduce_dependencies(db,'Reduce reproducible recursive seed',root)['removed']:
                e=item['edge'];removed.add((ids[e['prerequisite_id']],ids[e['dependent_id']]))
    payload['dependencies']=[e for e in payload['dependencies'] if (e['prerequisite'],e['dependent']) not in removed]
    payload['note']+=' Includes recursive prerequisite reviews to an explicit elementary baseline; certifications are separate curation judgments.'


def apply(db,plan):
    fingerprint=hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    for row in db.execute("SELECT after_json FROM curation_event WHERE operation='recursive_experiments'"):
        if json.loads(row[0]).get('plan_sha256')==fingerprint:
            return dict(already_applied=True,cones={root:m.prerequisite_cone(db,root,'proof') for root in plan['roots']})
    batch=copy.deepcopy(plan['batch'])
    from curate_dependency_purposes import annotate_edges
    annotate_edges(batch['dependencies'])
    for table in ('sources','concepts'):
        singular='source' if table=='sources' else 'concept'
        existing={r['slug']:dict(r) for r in db.execute(f'SELECT * FROM {singular}')}
        if table=='concepts':
            for c in batch[table]:
                if c['slug'] in existing and any(c[k]!=existing[c['slug']][k] for k in ('title','kind','description')):
                    raise ValueError(f"Review existing identity before reusing {c['slug']}")
        batch[table]=[r for r in batch[table] if r['slug'] not in existing]
    ids={r['id']:r['slug'] for r in db.execute('SELECT id,slug FROM concept')}
    existing={(ids[r['prerequisite_id']],ids[r['dependent_id']]) for r in db.execute('SELECT * FROM concept_dependency')}
    batch['dependencies']=[e for e in batch['dependencies'] if (e['prerequisite'],e['dependent']) not in existing]
    m.ingest(db,batch)
    for revision in plan['revisions']:
        current=m.lookup(db,'concept',revision['concept'])
        changes={k:v for k,v in revision['changes'].items() if current[k]!=v}
        if changes:m.revise(db,revision['concept'],changes,revision['reason'])
    with db:
        for removed in plan['remove_dependencies']:
            p=m.lookup(db,'concept',removed['prerequisite'])['id'];d=m.lookup(db,'concept',removed['dependent'])['id']
            before=[dict(r) for r in db.execute('SELECT * FROM concept_dependency WHERE prerequisite_id=? AND dependent_id=?',(p,d))]
            if before:
                db.execute('DELETE FROM concept_dependency WHERE prerequisite_id=? AND dependent_id=?',(p,d))
                m.event(db,'correct_prerequisite',removed['reason'],before,{})
    reviewed={r['concept'] for r in plan['reviews']}
    reductions={}
    for root in plan['roots']:
        cone=m.prerequisite_cone(db,root,'proof')
        missing={n['slug'] for n in cone['nodes']}-reviewed
        if missing:raise ValueError(f'Unreviewed prerequisite frontier: {sorted(missing)}')
        reductions[root]=m.reduce_dependencies(db,'Retain immediate prerequisite covers; preserve the original edges and alternative paths in history.',root)
    for review in plan['reviews']:
        current=m.lookup(db,'concept',review['concept'])
        if current['boundary']:
            m.revise(db,review['concept'],{'boundary':0},'This concept has an explicit immediate-prerequisite review under the recursive experiment baseline.')
    # Only certify after all edits and reductions; no incidental traversal certifies a node.
    for review in plan['reviews']:
        m.set_completeness(db,'concept',review['concept'],{'prerequisites_complete':True},
            f"Recursive prerequisite review: {review['source']}, {review['locator']}. {review['note']} Baseline: {plan['baseline']}")
    cones={root:m.prerequisite_cone(db,root,'proof') for root in plan['roots']}
    if any(not c['all_reviewed'] for c in cones.values()):
        raise ValueError('An immediate-prerequisite review was invalidated during the experiment')
    with db:
        m.event(db,'recursive_experiments','Complete two recursive reviews under an explicit elementary baseline.',{},
            dict(plan_sha256=fingerprint,roots=plan['roots'],baseline=plan['baseline'],
                 counts={r:dict(concepts=len(c['nodes']),edges=len(c['edges']),depth=c['max_depth']) for r,c in cones.items()}))
    return dict(already_applied=False,cones=cones,reductions=reductions)


def write_reports(db,plan,result):
    report=dict(baseline=plan['baseline'],primitives=plan['primitives'],cones=result['cones'])
    (m.ROOT/'data/recursive-cones.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['RECURSIVE PREREQUISITE EXPERIMENTS','',plan['baseline'],'',
           'Each listed concept has an explicit immediate-prerequisite review. The complete flag is not inferred from reachability.',
           'Edges are transitively reduced. Original redundant edges, rationales, evidence and retained alternative paths are in the curation history.','']
    reviews={r['concept']:r for r in plan['reviews']}
    for root,cone in result['cones'].items():
        nodes={c['id']:c for c in cone['nodes']}
        lines += [m.lookup(db,'concept',root)['title'].upper(),
                  f"{len(nodes)} concepts including the root; {len(cone['edges'])} edges; {cone['max_depth']} levels below the root.",
                  'Recorded cone fully reviewed: '+str(cone['all_reviewed']),
                  'Baseline leaves: '+', '.join(cone['leaves']),'']
        for node in cone['nodes']:
            parents=[nodes[e['prerequisite_id']]['title'] for e in cone['edges'] if e['dependent_id']==node['id']]
            r=reviews[node['slug']]
            lines += [node['title'],node['description'],'Immediate prerequisites: '+('; '.join(parents) or 'None at the stated primitive baseline.'),
                      f"Reference: {r['source']}, {r['locator']}."]
            if r['note']:lines.append('Review: '+r['note'])
            lines.append('')
    lines += ['A FEW REDUCTION EXAMPLES','']
    for row in db.execute("SELECT after_json FROM curation_event WHERE operation='transitive_reduction'"):
        reduction=json.loads(row[0])
        if reduction.get('root') in plan['roots']:
            for removed in reduction['removed']:
                lines.append(' → '.join(removed['path']))
    (m.ROOT/'data/recursive-experiments.txt').write_text('\n'.join(lines)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=m.DEFAULT_DB)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    plan=json.loads(PLAN.read_text())
    with closing(m.connect(args.db)) as original:
        m.initialize(original)
        if args.dry_run:
            with closing(m.connect(':memory:')) as preview:
                original.backup(preview);result=apply(preview,plan)
        else:
            result=apply(original,plan)
            if args.db.resolve()==m.DEFAULT_DB.resolve():write_reports(original,plan,result)
    print(json.dumps(dict(already_applied=result['already_applied'],dry_run=args.dry_run,
        cones={r:dict(concepts=len(c['nodes']),edges=len(c['edges']),depth=c['max_depth'],leaves=c['leaves'],all_reviewed=c['all_reviewed']) for r,c in result['cones'].items()}),indent=2))


if __name__=='__main__':main()
