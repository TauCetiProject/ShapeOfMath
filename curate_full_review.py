"""Apply the collection review, with per-record evidence and an exact link ledger."""
from contextlib import closing
import argparse
import copy
import hashlib
import json
from pathlib import Path

import mathdb as m

ROOT=Path(__file__).resolve().parent
PLAN=ROOT/'data/full-review-plan.json'

ORIGINS = {
 ('erdos-szekeres-1935','erdos-szekeres-monotone'):
  'The second proof, pp. 467–468, establishes the sharp monotone-subsequence threshold and explicitly credits Richard Rado with independent consideration. Preserve that shared credit; the earlier Ramsey theorem is separately credited to Ramsey.',
 ('erdos-szekeres-1935','erdos-szekeres-cups-caps'):
  'The second proof, pp. 469–470, derives the sharp ordered-slope threshold and gives matching configurations; this is a contribution of the paper, unlike the Ramsey and Klein inputs explicitly credited earlier.',
 ('erdos-szekeres-1935','erdos-szekeres-convex'):
  'The introduction poses the general convex-polygon question, credits Esther Klein for the five-point case, and claims two proofs of the new general existence theorem; pp. 464–470 supply them.',
 ('erdos-szekeres-1935','klein-five-points'):
  'The introduction, p. 463, explicitly attributes this proposition and its proof to Esther Klein and publishes that proof. This occurrence records its introduction to the literature here, with mathematical credit to Klein, not a claim that Erdős and Szekeres discovered it.',
 ('erdos-szekeres-1935','monotone-gap-theorem'):
  'The second proof, pp. 468–469, states and proves the sharp monotone-gap selection result before the planar slope argument. No predecessor is credited for this intermediate standalone selection theorem. Its descriptive title is ours.',
 ('etemadi-1981','etemadi-strong-law'):
  'The summary distinguishes the pairwise-independent strong law from the classical iid proof and cites Chung only for the weak law. Theorem 1 proves the stronger pairwise-independent assertion; the contribution is the changed hypothesis, not merely a new proof of the iid theorem.',
 ('etemadi-1981','etemadi-array-law'):
  'Theorem 2 proves the pairwise-independent two-parameter array law and Remark 1 states the r-parameter extension. The predecessor Smythe [4] is explicitly described as an iid martingale approach. The origin claim concerns this pairwise-independent version.',
}

# Correct source locations checked in the downloaded artifacts, not inferred from
# bibliography metadata. Entries removed here were unsupported exposition claims.
LOCATORS = {
 ('su-1999','brouwer-fixed-point'):'§1',
 ('su-1999','rental-harmony'):'§§6–7',
 ('representation-theory-notes-2011','orthogonal-idempotents'):'§7.3, Definition 7.4',
 ('representation-theory-notes-2011','split-semisimple-algebra'):'§2.3, representations of sums of matrix algebras',
 ('conrad-tensor-products','bilinear-map'):'§2, bilinear maps (specialized from modules to vector spaces)',
 ('stacks-project','zero-object'):'Categories, §4.12, initial and final objects; a zero object is both',
 ('egno-tensor-categories-2015','tensor-ideal'):'Exercise 8.18.1(ii), tensor-ideal property of negligible morphisms',
 ('morrison-snyder-2012','center-base-change'):'Lemma 5.1',
 ('morrison-snyder-2012','module-dual-base-change'):'Lemma 5.2',
}
DROP_LINKS = {
 ('representation-theory-notes-2011','splitting-field-algebra'):
  'The inspected notes assume an algebraically closed field in §1.2; §§2.3–2.5 do not explain a general splitting field. Remove the unsupported learning-reference claim.',
 ('niven-1947','integration-by-parts'):
  'Niven differentiates the explicitly constructed antiderivative and applies the fundamental theorem of calculus; repeated integration by parts is an alternative reconstruction, not an assumed named tool in this paper.',
}

SOURCE_GAPS = {
 'zagier-1990': ['Origin of the exact displayed involution has not been compared with the Heath–Brown artifact; do not certify the introduction list.'],
 'niven-1947': ['Add the sine/cosine derivative and sign facts used in the proof before certifying reading requirements.'],
 'erdos-szekeres-1935': ['The stated convex-polygon conjecture and quantitative Ramsey recurrence have not yet received separate contribution/identity decisions.'],
 'su-1999': ['The weaker boundary assumption in §8 is not in the current rental theorem statement; compare Alkan–Demange–Gale before settling the origin of the full result.', 'The dual Sperner lemma is credited to Scarf [12]; no original attribution to Su.'],
 'etemadi-1981': ['Banach-space and converse extensions in Remarks 2–3 are outside current concept capture.', 'Variance additivity and r-dimensional divisor estimates remain missing prerequisites.'],
 'morrison-g2-2011': ['The eigenvalue/Vandermonde argument in Lemma 2.3 requires explicit linear-algebra concepts before reading completeness can be certified.'],
 'morrison-snyder-2012': ['Origin of the rational-form terminology and lopsided normalization remains unresolved.', 'Unitary fusion categories, algebra objects, bimodule objects and dominant functors remain missing background for §§3–6.'],
}

def cleaned_link(link):
    link=copy.deepcopy(link)
    key=(link['source'],link['concept'])
    if key in DROP_LINKS:return None
    if key in LOCATORS:link['locator']=LOCATORS[key]
    note=link.get('note','')
    for text in [' This new concept is not expanded in this pass.',
                 'This new concept is not expanded in this pass.',
                 'The new concept is unexpanded.']:
        note=note.replace(text,'')
    if key==('representation-theory-notes-2011','vector-space'):
        note='The exposition assumes vector-space theory; this is a background requirement, not an explanation of vector spaces.'
    if key==('su-1999','dual-sperner-lemma'):
        note='Su §7 explicitly credits this dual lemma to Scarf [12]. This is an explanation, not an origin claim.'
    if key==('erdos-szekeres-1935','erdos-szekeres-monotone'):
        credit='The paper also credits Richard Rado for independent consideration of the monotone-subsequence problem.'
        if credit not in note:note+=' '+credit
    link['note']=note.strip()
    if key in ORIGINS:
        link['role']='introduces';link['introduction_evidence']=ORIGINS[key]
    return link

def project(payload,plan=None):
    """Apply reviewed content to a freshly built seed; do not grant review flags."""
    plan=plan or json.loads(PLAN.read_text())
    for c in payload['concepts']:
        changes=plan['revisions'].get(c['slug'],{})
        if 'title' in changes and changes['title']!=c['title']:
            c.setdefault('aliases',[]).append(c['title'])
        c.update(changes)
    # Preserve located original edge evidence when the same parent is retained.
    old={(e['prerequisite'],e['dependent']):e for e in payload['dependencies']}
    payload['dependencies']=[e for e in payload['dependencies'] if e['dependent'] not in plan['parents']]
    for child,parents in plan['parents'].items():
        for parent in parents:
            payload['dependencies'].append(copy.deepcopy(old.get((parent,child),dict(
                prerequisite=parent,dependent=child,basis='both',
                rationale=f'Collection review: the definition of {child} uses {parent}; see the per-concept review and explicit unfinished frontier.'))))
    # Correct the chosen Niven route without changing the named theorem identity.
    payload['dependencies']=[e for e in payload['dependencies'] if (e['prerequisite'],e['dependent'])!=('integration-by-parts','pi-irrational')]
    payload['dependencies'].append(dict(prerequisite='fundamental-calculus',dependent='pi-irrational',basis='both',source='niven-1947',locator='p. 509',rationale='Niven differentiates F′sin−Fcos and evaluates its integral at the endpoints; this uses the fundamental theorem of calculus.'))
    payload['source_concepts']=[x for l in payload['source_concepts'] if (x:=cleaned_link(l)) is not None]
    for s in payload['sources']:
        if s['slug'] in ('kuperberg-1996','lehrer-zhang-2006'):
            s['coverage']='Located original-contribution passages reviewed; complete source ingestion has not been performed.'
    # Use the same reduction algorithm as live curation, retaining the original
    # detailed deletion evidence there. The seed contains the reduced final DAG.
    with closing(m.connect(':memory:')) as db:
        m.initialize(db)
        m.ingest(db,dict(concepts=payload['concepts'],sources=payload['sources'],dependencies=payload['dependencies']))
        redundant={r['edge']['id'] for r in m.reduction_plan(db)['removed']}
        pairs={(r['prerequisite_id'],r['dependent_id']) for r in db.execute('select * from concept_dependency') if r['id'] not in redundant}
        ids={r['slug']:r['id'] for r in db.execute('select * from concept')}
        payload['dependencies']=[e for e in payload['dependencies'] if (ids[e['prerequisite']],ids[e['dependent']]) in pairs]
    return payload

def apply(db,plan=None,write_files=True):
    plan=plan or json.loads(PLAN.read_text())
    fingerprint=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    for r in db.execute("select after_json from curation_event where operation='collection_review'"):
        if json.loads(r[0]).get('plan_sha256')==fingerprint:return False
    before=m.snapshot(db)
    for slug,changes in plan['revisions'].items():
        current=m.lookup(db,'concept',slug)
        delta={k:v for k,v in changes.items() if current[k]!=v}
        if delta:m.revise(db,slug,delta,'Collection-wide mathematical review: '+next(r['review_note'] for r in plan['concepts'] if r['slug']==slug))
    ids={r['slug']:r['id'] for r in db.execute('select * from concept')}
    slugs={v:k for k,v in ids.items()}
    source_slugs={r['id']:r['slug'] for r in db.execute('select * from source')}
    wanted={}
    for e in before['concept_dependency']:
        if slugs[e['dependent_id']] in plan['parents']:continue
        if (slugs[e['prerequisite_id']],slugs[e['dependent_id']])==('integration-by-parts','pi-irrational'):continue
        item=dict(prerequisite=slugs[e['prerequisite_id']],dependent=slugs[e['dependent_id']],basis=e['basis'],rationale=e['rationale'],locator=e['locator'])
        if e['evidence_source_id']:item['source']=source_slugs[e['evidence_source_id']]
        wanted[(e['prerequisite_id'],e['dependent_id'])]=item
    # First perform semantic edits to unreduced candidate parents. Reduction gets
    # its own full retained-path evidence below.
    for child,parents in plan['parents'].items():
        for parent in parents:
            if (ids[parent],ids[child]) not in wanted:
                wanted[(ids[parent],ids[child])]=dict(prerequisite=parent,dependent=child,basis='both',rationale=f'Reviewed definition of {child} uses {parent}.')
    wanted[(ids['fundamental-calculus'],ids['pi-irrational'])]=dict(prerequisite='fundamental-calculus',dependent='pi-irrational',basis='both',source='niven-1947',locator='p. 509',rationale='Niven differentiates F′sin−Fcos and evaluates its integral at the endpoints, using the fundamental theorem of calculus.')
    with db:
        changes=[]
        for e in list(db.execute('select * from concept_dependency')):
            if (e['prerequisite_id'],e['dependent_id']) not in wanted:
                changes.append({'action':'remove','edge':dict(e)})
                db.execute('delete from concept_dependency where id=?',(e['id'],))
        existing={(e['prerequisite_id'],e['dependent_id']) for e in db.execute('select * from concept_dependency')}
        for pair,e in wanted.items():
            if pair not in existing:
                m.add_edge(db,e);changes.append({'action':'add','edge':e})
        m.event(db,'collection_review_edges','Review all prerequisite meanings; remove unsupported special-case, invertibility and finite-depth assumptions. Reduction is recorded separately.',{}, {'changes':changes})
        link_changes=[]
        for row in list(db.execute('select l.*,s.slug as source,c.slug as concept from active_source_concept l join source s on s.id=l.source_id join concept c on c.id=l.concept_id')):
            old=dict(row);new=cleaned_link(old)
            if new is None:
                db.execute('delete from source_concept where id=?',(row['id'],))
                link_changes.append({'before':old,'after':None,'reason':DROP_LINKS[(row['source'],row['concept'])]})
            else:
                keys=['role','locator','note','introduction_evidence']
                if any(old[k]!=new.get(k,'') for k in keys):
                    db.execute('update source_concept set role=?,locator=?,note=?,introduction_evidence=? where id=?',(*[new.get(k,'') for k in keys],row['id']))
                    link_changes.append({'before':old,'after':new})
        m.event(db,'collection_review_occurrences','Check actual roles, predecessor credit and learning-reference locations for every active source occurrence.',{}, {'changes':link_changes})
        for slug in ('kuperberg-1996','lehrer-zhang-2006'):
            db.execute('update source set coverage=? where slug=?',('Located original-contribution passages reviewed; complete source ingestion has not been performed.',slug))
    m.reduce_dependencies(db,'Transitive reduction after collection review; retain original shortcut evidence and paths through retained edges.')
    with db:
        old_markers=[dict(r) for r in db.execute("select id,slug,boundary from concept where status='active' and boundary <> (not exists(select 1 from concept_dependency d where d.dependent_id=concept.id))")]
        db.execute("update concept set boundary=(not exists(select 1 from concept_dependency d where d.dependent_id=concept.id)) where status='active' and boundary <> (not exists(select 1 from concept_dependency d where d.dependent_id=concept.id))")
        if old_markers:m.event(db,'review_boundary_markers','Align frontier markers with the reviewed graph; markers do not certify prerequisites.',old_markers,{'aligned_ids':[r['id'] for r in old_markers]})
    # Reviews happen last, after all semantic edits and invalidations.
    for r in plan['concepts']:
        reason=r['review_note']+' Baseline: '+plan['baseline']
        if r['missing_prerequisites']:reason+=' Unfinished immediate background: '+'; '.join(r['missing_prerequisites'])
        m.set_completeness(db,'concept',r['slug'],{'prerequisites_complete':r['prerequisites_complete']},reason)
    m.set_completeness(db,'source','niven-1947',{'introductions_complete':True},'Read the complete one-page paper: an alternative proof of the known irrationality theorem. Its auxiliary polynomials and integral are proof data, not reusable new concepts; the introduced-concept list is reviewed empty.')
    m.set_completeness(db,'source','morrison-g2-2011',{'introductions_complete':True},'Rechecked the abstract, predecessor credits, §§1–3 and appendix: recalls Kuperberg and reproves Lehrer–Zhang; local formulas remain proof data. Reviewed empty introduction list.')
    after=m.snapshot(db)
    by_id={c['id']:c['slug'] for c in before['concept']}
    final_edges={e['id']:e for e in after['concept_dependency']}
    final_links={l['id']:l for l in after['source_concept']}
    ledger=copy.deepcopy(plan)
    for r in ledger['concepts']:
        cid=ids[r['slug']]
        r['incident_edges_before']=[e['id'] for e in before['concept_dependency'] if cid in (e['prerequisite_id'],e['dependent_id'])]
        r['source_occurrences_before']=[l['id'] for l in before['source_concept'] if l['concept_id']==cid]
        r['related_links_before']=[l['id'] for l in before['concept_related'] if cid in (l['concept_a_id'],l['concept_b_id'])]
        r['aliases_reviewed']=[a for a in before['concept_alias'] if a['concept_id']==cid]
    ledger['edges']=[{'id':e['id'],'prerequisite':by_id[e['prerequisite_id']],'dependent':by_id[e['dependent_id']],
                      'disposition':'retain' if e['id'] in final_edges else 'remove; see semantic edit or retained-path reduction event',
                      'review':'Checked against the endpoint definitions and annotated proof/learning route.'} for e in before['concept_dependency']]
    ledger['occurrences']=[{'id':l['id'],'source':next(s['slug'] for s in before['source'] if s['id']==l['source_id']),
                          'concept':by_id[l['concept_id']], 'before_role':l['role'],
                          'after':final_links.get(l['id']), 'review':'Checked the role and location against the source passage; explanations do not assert original contribution.'}
                         for l in before['source_concept'] if by_id[l['concept_id']] in {r['slug'] for r in plan['concepts']}]
    ledger['source_gaps']=SOURCE_GAPS
    ledger['source_review']=[{'slug':s['slug'],'review':'Complete text read for the seven draft papers; only the attached passages/bibliographic evidence reviewed for catalogue and learning sources.',
                           'remaining':SOURCE_GAPS.get(s['slug'],['Full-source concept and citation ingestion has not been performed.'])} for s in before['source']]
    ledger['related_review']=[{'id':r['id'],'decision':'retain','reason':'Principal and dual even parts are related; neither is assumed prior to the other.'} for r in before['concept_related']]
    ledger['source_relation_review']=[{'id':r['id'],'decision':'retain','reason':'Located citation or historical relation; unique availability is not established, so no strict dependency is inferred.'} for r in before['source_relation']]
    ledger['citation_review']=[{'id':r['id'],'decision':'retain','reason':'Matched against Morrison’s printed reference list on p. 198; preserve raw text, identifiers and nullable pedagogical judgment independently.'} for r in before['citation']]
    ledger['historical_review']=[{'slug':c['slug'],'decision':'retain superseded, no active links or vector','reason':'Paper-local twisted-moment expression or choice-independence calculation, preserved in the field-of-definition theorem notes.'} for c in before['concept'] if c['status']=='superseded']
    ledger['plan_sha256']=fingerprint
    ledger['verification']=m.verify(db)
    with db:m.event(db,'collection_review','Record-by-record mathematical review of the existing collection, with identified omissions left uncertified.',{'inventory':plan['inventory']},ledger)
    if write_files:(ROOT/'data/full-review.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
    return True

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=m.database_arg,default=m.DEFAULT_DB);args=parser.parse_args()
    with closing(m.connect(args.db)) as db:
        m.initialize(db);print(json.dumps({'changed':apply(db),**m.verify(db)},indent=2))
