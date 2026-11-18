"""General reviewed-plan imports for prepared source and cone tasks.

Historical2015 importers are retained unchanged. Shared edit helpers below start
from their reviewed implementation; this module has no sample allowlist.
"""
from contextlib import closing, contextmanager
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import sysconfig
import tempfile

import mathdb as m


def read(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default


def digest(path):
    with Path(path).open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()


def engine_hashes():
    schema=m.ROOT/'schema.sql'
    if not schema.exists():schema=Path(sysconfig.get_path('data'))/'share/the-shape-of-math/schema.sql'
    return {'curation_plans':digest(__file__),'mathdb':digest(m.__file__),'schema':digest(schema)}


def save(path, value):
    path=Path(path);temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(path)


def prepare(db,payload,resolutions):
    batch=copy.deepcopy(payload);decisions=[];concept_map={};source_map={}
    existing={r['slug']:r for r in db.execute('select * from concept')}
    for c in batch.get('concepts',[]):
        decision=resolutions.get('concepts',{}).get(c['slug'])
        if decision:
            if not decision.get('reason','').strip():raise ValueError('Identity resolution needs reason')
            target=m.lookup(db,'concept',decision['target'])
            concept_map[c['slug']]=target['slug'];decisions.append({'candidate':c,**decision})
        elif c['slug'] in existing:
            old=existing[c['slug']]
            if any(c[k]!=old[k] for k in ['title','kind','description']):
                raise ValueError('Definition conflict requiring resolutions.json: '+c['slug'])
            concept_map[c['slug']]=c['slug']
            decisions.append({'candidate':c['slug'],'target':c['slug'],'reason':'Exact same name, kind and mathematical paragraph.'})
    for slug,decision in resolutions.get('concepts',{}).items():
        if slug in concept_map:continue
        if not decision.get('reason','').strip():raise ValueError('Reference resolution needs reason')
        concept_map[slug]=m.lookup(db,'concept',decision['target'])['slug']
        decisions.append({'candidate_reference':slug,**decision})
    batch['concepts']=[c for c in batch.get('concepts',[]) if c['slug'] not in concept_map]
    for s in batch.get('sources',[]):
        matches=set()
        for scheme,value in s['identifiers']:
            key=m.normalize_identifier(scheme,value)
            found=db.execute('select s.slug from source_identifier i join source s on s.id=i.source_id where i.scheme=? and i.value=?',key).fetchone()
            if found:matches.add(found[0])
        same_slug=db.execute('select slug from source where slug=?',(s['slug'],)).fetchone()
        if same_slug:matches.add(same_slug[0])
        if len(matches)>1:raise ValueError('Conflicting source identities: '+s['slug'])
        if matches:
            target=next(iter(matches));source_map[s['slug']]=target
            decisions.append({'source':s['slug'],'target':target,'reason':'Catalogue identity matched by external identifier or same stable source slug.','proposed_metadata':s})
    batch['sources']=[s for s in batch.get('sources',[]) if s['slug'] not in source_map]
    def concept(slug):return concept_map.get(slug,slug)
    def source(slug):return source_map.get(slug,slug)
    for e in batch.get('dependencies',[]):
        e['prerequisite']=concept(e['prerequisite']);e['dependent']=concept(e['dependent'])
        if e.get('source'):e['source']=source(e['source'])
        definitions={c['slug']:c for c in batch.get('concepts',[])}
        target=definitions.get(e['dependent']) or existing.get(e['dependent'])
        if target and target['kind'] in ('theorem','conjecture') and e.get('purpose') not in ('statement','proof','both'):
            raise ValueError('Classify theorem dependency purpose before new-paper ingestion: '+e['prerequisite']+' -> '+e['dependent'])
    old_edges={(r['prerequisite'],r['dependent']):dict(r) for r in db.execute('select e.*,p.slug as prerequisite,d.slug as dependent from concept_dependency e join concept p on p.id=e.prerequisite_id join concept d on d.id=e.dependent_id')}
    kept=[];pending={};purpose_updates={}
    for e in batch.get('dependencies',[]):
        pair=e['prerequisite'],e['dependent']
        if pair[0]==pair[1]:raise ValueError('Identity resolution creates self dependency')
        if pair in old_edges or pair in pending:
            old=old_edges.get(pair) or pending[pair]
            old_purpose=purpose_updates.get(old.get('id'),{}).get('purpose',old.get('purpose','statement'))
            new_purpose=e.get('purpose','statement')
            if 'unclassified' in (old_purpose,new_purpose):raise ValueError('Review unclassified duplicate dependency: '+str(pair))
            merged=old_purpose if old_purpose==new_purpose else 'both'
            if pair in old_edges and merged!=old_purpose:
                purpose_updates[old['id']]={'before':old,'purpose':merged,'evidence':e}
            elif pair in pending:pending[pair]['purpose']=merged
            decisions.append({'existing_edge':list(pair),'additional_evidence':e})
        else:kept.append(e);pending[pair]=e
    batch['dependencies']=kept
    for l in batch.get('source_concepts',[]):
        l['concept']=concept(l['concept']);l['source']=source(l['source'])
    for e in batch.get('related_concepts',[]):
        for key in ['concept_a','concept_b']:e[key]=concept(e[key])
        if e.get('source'):e['source']=source(e['source'])
    for e in batch.get('source_relations',[]):
        for key in ['prerequisite','dependent']:e[key]=source(e[key])
    for c in batch.get('citations',[]):
        c['source']=source(c['source'])
        if c.get('cited_source'):c['cited_source']=source(c['cited_source'])
    for item in batch.get('formalizations',[]):item['concept']=concept(item['concept'])
    return batch,decisions,concept_map,source_map,list(purpose_updates.values())


def correct_source_roles(db,corrections):
    """Apply curator-reviewed origin demotions against exact occurrence snapshots."""
    checked=[];seen=set()
    for correction in corrections:
        if (correction.get('from_role')!='introduces' or correction.get('to_role')!='explains'
                or not correction.get('reason','').strip() or not correction.get('locator','').strip()):
            raise ValueError('Source role correction requires an introduction demotion, location and reason')
        source=m.lookup(db,'source',correction['source'])
        concept=m.lookup(db,'concept',correction['concept'])
        before=correction.get('before',{})
        row=db.execute('SELECT * FROM source_concept WHERE id=?',(before.get('id'),)).fetchone()
        if (row is None or dict(row)!=before or row['source_id']!=source['id']
                or row['concept_id']!=concept['id'] or row['role']!=correction['from_role']
                or row['id'] in seen):
            raise ValueError('Source role correction needs a current exact occurrence snapshot')
        seen.add(row['id']);checked.append((correction,dict(row)))
    for correction,before in checked:
        db.execute('UPDATE source_concept SET role=?,locator=?,note=?,introduction_evidence=? WHERE id=?',
                   (correction['to_role'],correction['locator'],correction.get('note',before['note']),
                    '',before['id']))
        after=dict(db.execute('SELECT * FROM source_concept WHERE id=?',(before['id'],)).fetchone())
        m.event(db,'correct_source_occurrence_role',correction['reason'],before,
                {'occurrence':after,'review':correction})


def correct_source_metadata(db,updates):
    """Apply curator-written descriptive source corrections against exact old text."""
    allowed={'summary','coverage','dependency_review'}
    for update in updates:
        changes=update.get('changes',{});expected=update.get('before',{})
        if (not changes or not set(changes)<=allowed or set(expected)!=set(changes)
                or not all(isinstance(v,str) for v in changes.values())
                or not update.get('reason','').strip()):
            raise ValueError('Source metadata correction needs supported text fields, exact before values and a reason')
        source=dict(m.lookup(db,'source',update['source']))
        if any(source[key]!=value for key,value in expected.items()):
            raise ValueError('Source metadata correction is stale: '+source['slug'])
        db.execute('UPDATE source SET '+','.join(key+'=?' for key in changes)+' WHERE id=?',
                   (*changes.values(),source['id']))
        after=dict(m.lookup(db,'source',source['id']))
        m.event(db,'correct_source_metadata',update['reason'],source,{'source':after,'review':update})


def correct_locators(db,corrections):
    """Correct evidence pointers without changing identities or mathematical edges."""
    tables={'dependency':'concept_dependency','source_occurrence':'source_concept'}
    checked=[];seen=set()
    for correction in corrections:
        kind=correction.get('kind');before=correction.get('before',{})
        if (kind not in tables or not isinstance(correction.get('locator'),str)
                or not correction['locator'].strip() or not correction.get('reason','').strip()):
            raise ValueError('Locator correction requires a supported kind, pointer and reason')
        key=(kind,before.get('id'))
        row=db.execute('SELECT * FROM '+tables[kind]+' WHERE id=?',(before.get('id'),)).fetchone()
        if row is None or dict(row)!=before or key in seen:
            raise ValueError('Locator correction requires an exact current row snapshot, once per row')
        seen.add(key);checked.append((correction,tables[kind],dict(row)))
    for correction,table,before in checked:
        db.execute('UPDATE '+table+' SET locator=? WHERE id=?',(correction['locator'],before['id']))
        after=dict(db.execute('SELECT * FROM '+table+' WHERE id=?',(before['id'],)).fetchone())
        m.event(db,'correct_evidence_locator',correction['reason'],before,
                {'kind':correction['kind'],'row':after,'review':correction})


def correct_source_identifiers(db,corrections):
    """Replace or remove checked erroneous identifiers, preserving source identity."""
    with m.atomic(db):
        checked=[];seen=set()
        for correction in corrections:
            before=correction.get('before',{});replacement=correction.get('replacement')
            if (set(before)!={'scheme','value','source_id'} or not correction.get('reason','').strip()
                    or 'replacement' not in correction):
                raise ValueError('Identifier correction requires an exact row, explicit replacement/null and reason')
            key=(before['scheme'],before['value'])
            row=db.execute('SELECT * FROM source_identifier WHERE scheme=? AND value=?',key).fetchone()
            if row is None or dict(row)!=before or key in seen:
                raise ValueError('Identifier correction requires an exact current row snapshot, once per identifier')
            if replacement is not None:
                if not isinstance(replacement,(list,tuple)) or len(replacement)!=2:
                    raise ValueError('Replacement identifier must be a scheme/value pair or null')
                replacement=m.normalize_identifier(*replacement)
                if replacement==key:raise ValueError('Replacement identifier is unchanged')
            seen.add(key);checked.append((correction,dict(row),replacement))
        for correction,before,replacement in checked:
            if replacement is not None:
                m.add_identifier(db,before['source_id'],*replacement)
            if replacement is None and db.execute('SELECT count(*) FROM source_identifier WHERE source_id=?',
                                                  (before['source_id'],)).fetchone()[0]<=1:
                raise ValueError('Cannot remove the last source identifier without a replacement')
            db.execute('DELETE FROM source_identifier WHERE scheme=? AND value=?',(before['scheme'],before['value']))
            after=({'scheme':replacement[0],'value':replacement[1],'source_id':before['source_id']}
                   if replacement is not None else None)
            m.event(db,'correct_source_identifier',correction['reason'],before,
                    {'replacement':after,'review':correction})


def correct_dependency_evidence(db,updates):
    """Revise checked explanations/pointers while preserving the dependency itself."""
    with m.atomic(db):
        checked=[];seen=set()
        for update in updates:
            before=update.get('before',{});changes=update.get('changes',{})
            if (not changes or not set(changes)<={'rationale','locator'}
                    or not update.get('reason','').strip()
                    or any(not isinstance(v,str) or not v.strip() for v in changes.values())):
                raise ValueError('Dependency evidence update needs rationale/locator text and a reason')
            row=db.execute('SELECT * FROM concept_dependency WHERE id=?',(before.get('id'),)).fetchone()
            if row is None or dict(row)!=before or row['id'] in seen:
                raise ValueError('Dependency evidence update needs an exact current row snapshot, once per edge')
            seen.add(row['id']);checked.append((update,dict(row)))
        for update,before in checked:
            changes=update['changes']
            db.execute('UPDATE concept_dependency SET '+','.join(k+'=?' for k in changes)+' WHERE id=?',
                       (*changes.values(),before['id']))
            after=dict(db.execute('SELECT * FROM concept_dependency WHERE id=?',(before['id'],)).fetchone())
            m.event(db,'correct_dependency_evidence',update['reason'],before,{'edge':after,'review':update})




def apply_operations(db, payload, review, resolutions, task_id, plan_id, fingerprint):
    # Full split/merge plans use the core's exact incident routing validation.
    # Do these before append operations and explicit post-change review judgments.
    for reorganization in review.get('proposed_reorganizations',[]):
        m.reorganize(db,reorganization)
    revisions=review.get('proposed_revisions',[])
    inventories=[]
    for revision in revisions:
        concept=m.lookup(db,'concept',revision['slug']);concept_id=concept['id']
        inventory={
            'incoming':[dict(r) for r in db.execute('SELECT * FROM concept_dependency WHERE dependent_id=?',(concept_id,))],
            'outgoing':[dict(r) for r in db.execute('SELECT * FROM concept_dependency WHERE prerequisite_id=?',(concept_id,))],
            'source_occurrences':[dict(r) for r in db.execute('SELECT * FROM source_concept WHERE concept_id=?',(concept_id,))],
            'aliases':[dict(r) for r in db.execute('SELECT * FROM concept_alias WHERE concept_id=?',(concept_id,))],
            'related':[dict(r) for r in db.execute('SELECT * FROM concept_related WHERE concept_a_id=? OR concept_b_id=?',(concept_id,concept_id))],
            'formalizations':m.formalizations(db,concept=revision['slug'])}
        def canonical(rows):return sorted(json.dumps(r,sort_keys=True) for r in rows)
        expected=revision['incident_inventory']
        if (set(expected)!=set(inventory) or any(canonical(inventory[k])!=canonical(expected[k]) for k in inventory)
                or not revision.get('disposition','').strip() or not revision.get('reason','').strip()):
            raise ValueError('Same-identity revision needs a current complete incident inventory and disposition: '+revision['slug'])
        inventories.append(inventory)
    for revision,inventory in zip(revisions,inventories):
        with db:m.event(db,'review_revision_incident_links',revision['reason'],inventory,{'slug':revision['slug'],'disposition':revision['disposition']})
        m.revise(db,revision['slug'],revision['changes'],revision['reason'])
    batch,decisions,concept_map,source_map,purpose_updates=prepare(db,payload,resolutions)
    before_links=[dict(r) for r in db.execute('select * from source_concept')]
    m.ingest(db,batch)
    # An existing source can acquire additional checked identifiers/artifacts;
    # identity reuse must not silently discard those supplied in the payload.
    for candidate in payload.get('sources',[]):
        if candidate['slug'] not in source_map:continue
        source=m.lookup(db,'source',source_map[candidate['slug']])
        for scheme,value in candidate['identifiers']:
            key=m.normalize_identifier(scheme,value)
            old=db.execute('SELECT * FROM source_identifier WHERE scheme=? AND value=?',key).fetchone()
            if old is None:
                m.add_identifier(db,source['id'],*key)
                m.event(db,'add_source_identifier','Reviewed identifier from reused source in task '+task_id,{},
                        {'source_id':source['id'],'scheme':key[0],'value':key[1]})
        for artifact in candidate.get('artifacts',[]):
            if not db.execute('SELECT 1 FROM source_artifact WHERE source_id=? AND url=? AND version=? AND sha256 IS ?',
                              (source['id'],artifact['url'],artifact.get('version',''),artifact.get('sha256'))).fetchone():
                db.execute('INSERT INTO source_artifact(source_id,url,version,accessed_at,sha256,local_path,note) VALUES (?,?,?,?,?,?,?)',
                    (source['id'],artifact['url'],artifact.get('version',''),artifact['accessed_at'],artifact.get('sha256'),artifact.get('local_path'),artifact.get('note','')))
                m.event(db,'add_source_artifact','Reviewed artifact from reused source in task '+task_id,{},
                        {'source_id':source['id'],**artifact})
    with db:
        for update in purpose_updates:
            db.execute('UPDATE concept_dependency SET purpose=? WHERE id=?',(update['purpose'],update['before']['id']))
        if purpose_updates:m.event(db,'merge_dependency_purposes','Keep both explicit uses when a shared input is needed for statement and proof.',{},purpose_updates)
        for removal in review.get('proposed_edge_removals',[]):
            if not removal.get('reason','').strip() or removal.get('purpose') not in ('statement','proof'):
                raise ValueError('An input-role correction requires an explicit purpose and mathematical reason')
            prereq=m.lookup(db,'concept',concept_map.get(removal['prerequisite'],removal['prerequisite']))
            dependent=m.lookup(db,'concept',concept_map.get(removal['dependent'],removal['dependent']))
            old=db.execute('SELECT * FROM concept_dependency WHERE prerequisite_id=? AND dependent_id=?',(prereq['id'],dependent['id'])).fetchone()
            if old is None:
                raise ValueError('Proposed edge removal is stale; review the current paths: '+str(removal))
            old=dict(old)
            if old['purpose']==removal['purpose']:
                db.execute('DELETE FROM concept_dependency WHERE id=?',(old['id'],))
                after=None
            elif old['purpose']=='both':
                remaining='proof' if removal['purpose']=='statement' else 'statement'
                db.execute('UPDATE concept_dependency SET purpose=? WHERE id=?',(remaining,old['id']))
                after={**old,'purpose':remaining}
            else:raise ValueError('Correction does not match the current dependency purpose')
            m.event(db,'correct_dependency_identity',removal['reason'],old,{'replacement_role':after,'review':removal})
        for route in review.get('proposed_source_occurrence_routings',[]):
            if route.get('role')!='relies_on' or not route.get('reason','').strip() or not route.get('locator','').strip():
                raise ValueError('A required-occurrence correction needs its checked location and reason')
            source=m.lookup(db,'source',route['source'])
            old_concept=m.lookup(db,'concept',route['from_concept'])
            new_concept=m.lookup(db,'concept',route['to_concept'])
            located=list(db.execute('SELECT * FROM source_concept WHERE source_id=? AND concept_id=? AND role=?',
                                    (source['id'],old_concept['id'],route['role'])))
            if len(located)!=1:raise ValueError('Occurrence routing needs one unambiguous existing link')
            old=dict(located[0])
            db.execute('UPDATE source_concept SET concept_id=?,locator=?,note=? WHERE id=?',
                       (new_concept['id'],route['locator'],old['note']+'\n'+route['reason'],old['id']))
            after=dict(db.execute('SELECT * FROM source_concept WHERE id=?',(old['id'],)).fetchone())
            m.event(db,'correct_source_requirement_identity',route['reason'],old,{'occurrence':after,'review':route})
        correct_source_roles(db,review.get('proposed_source_role_corrections',[]))
        correct_source_metadata(db,review.get('proposed_source_metadata_updates',[]))
        correct_locators(db,review.get('proposed_locator_corrections',[]))
        correct_source_identifiers(db,review.get('proposed_source_identifier_corrections',[]))
        correct_dependency_evidence(db,review.get('proposed_dependency_evidence_updates',[]))
    reduction=m.reduce_dependencies(db,'Transitive reduction after reviewed task '+task_id+' '+plan_id+'; preserve typed evidence and witnesses.')
    for r in review.get('reviews',[]):
        flags={k:r[k] for k in ('statement_prerequisites_complete','proof_prerequisites_complete') if k in r}
        if not flags or any(type(v) is not bool for v in flags.values()) or not r.get('reason','').strip():
            raise ValueError('Each cone node requires an explicit boolean judgment and mathematical reason')
        slug=concept_map.get(r['slug'],r['slug'])
        m.set_completeness(db,'concept',slug,flags,r['reason'])
    for r in review.get('source_reviews',[]):
        flags=r.get('flags',r.get('source_flags',{}))
        reasons=r.get('flag_reasons',{})
        if (not flags or not set(flags)<= {'requirements_complete','introductions_complete','citations_complete'}
                or any(type(v) is not bool for v in flags.values())
                or any(not reasons.get(k,r.get('reason','')).strip() for k in flags)):
            raise ValueError('Source review requires explicit independent boolean judgments and a reason')
        for key,value in flags.items():
            m.set_completeness(db,'source',source_map.get(r['source'],r['source']),{key:value},reasons.get(key,r.get('reason')))
    result={'changed':True,'task_id':task_id,'plan_id':plan_id,'sha256':fingerprint,'source':review.get('source'),
            'new_concepts':len(batch.get('concepts',[])),'new_sources':len(batch.get('sources',[])),
            'new_citations':len(batch.get('citations',[])),'resolutions':decisions,'purpose_updates':purpose_updates,'review':review,
            'reduction':reduction,'verification':m.verify(db)}
    # Capture changes to reused located occurrences as well as the append batch.
    after_links={r['id']:dict(r) for r in db.execute('select * from source_concept')}
    result['updated_occurrences']=[{'before':r,'after':after_links[r['id']]} for r in before_links if r!=after_links[r['id']]]
    return result


class ProtectedTransaction:
    """Keep legacy helper context managers inside one real outer transaction."""
    protected=False

    def __enter__(self):
        return self if self.protected else super().__enter__()

    def __exit__(self,*args):
        return False if self.protected else super().__exit__(*args)

    def commit(self):
        if self.protected:raise RuntimeError('Inner commit forbidden during reviewed-plan import')
        return super().commit()

    def rollback(self):
        if self.protected:raise RuntimeError('Inner rollback forbidden during reviewed-plan import')
        return super().rollback()

    def outer_commit(self):return super().commit()

    def outer_rollback(self):return super().rollback()


class PlanConnection(ProtectedTransaction,sqlite3.Connection):pass


def postgres_plan_connection(url):
    import pgcompat

    class PostgresPlanConnection(ProtectedTransaction,pgcompat.Connection):pass
    return PostgresPlanConnection(url)


@contextmanager
def transaction(db):
    if db.in_transaction:raise ValueError('Import requires a connection without an existing transaction')
    db.execute('BEGIN IMMEDIATE');db.protected=True
    try:
        yield
        if not db.in_transaction:raise RuntimeError('Plan operation escaped its transaction')
        db.outer_commit()
    except BaseException:
        db.outer_rollback();raise
    finally:db.protected=False


@contextmanager
def dry_run(db):
    """Apply a plan inside one transaction and always roll it back."""
    if db.in_transaction:raise ValueError('Check requires a connection without an existing transaction')
    db.execute('BEGIN IMMEDIATE');db.protected=True
    try:
        yield
        if not db.in_transaction:raise RuntimeError('Plan operation escaped its transaction')
    finally:
        db.protected=False;db.outer_rollback()


def connect(path,readonly=False):
    if m.is_postgres_url(path):
        db=postgres_plan_connection(str(path))
        if readonly:db.execute('SET default_transaction_read_only = on')
        return db
    path=Path(path).resolve()
    if not path.is_file():raise ValueError('Database does not exist: '+str(path))
    db=sqlite3.connect(path.as_uri()+('?mode=ro' if readonly else '?mode=rw'),uri=True,factory=PlanConnection)
    db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=10000')
    return db


def version(db):return db.execute('SELECT coalesce(max(id),0) FROM curation_event').fetchone()[0]


def schema_version(db):
    if m.is_postgres(db):return db.execute('SELECT version FROM schema_version').fetchone()[0]
    return db.execute('PRAGMA user_version').fetchone()[0]


def database_identity(db_path):
    """Name the database in receipts: a resolved file path, or a URL without credentials."""
    return m.database_label(db_path)


def load_task(directory):
    directory=Path(directory).resolve();assignment=read(directory/'assignment.json')
    manifest=read(directory/'policy-manifest.json')
    if not assignment or not manifest:raise ValueError('Use a task directory prepared by curation/prepare_task.py')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}',assignment.get('task_id','')):
        raise ValueError('task_id must be a stable identifier using letters, digits, dots, colons, underscores or hyphens')
    if assignment.get('kind') not in ('source','cone') or assignment.get('write_mode')!='stage_only':
        raise ValueError('Expected a prepared, stage-only source or cone task')
    for relative,sha in manifest['files_sha256'].items():
        path=(directory/relative).resolve();path.relative_to(directory)
        if digest(path)!=sha:raise ValueError('Pinned task input changed: '+relative)
    return assignment,digest(directory/'policy-manifest.json')


def load_plan(directory,path):
    directory=Path(directory).resolve();assignment,package_sha=load_task(directory)
    path=Path(path).resolve();path.relative_to(directory/'output')
    if not re.fullmatch(r'plan-\d{3,}\.json',path.name):raise ValueError('Use a numbered plan-NNN.json inside task/output')
    review_path=path.with_name(path.stem+'-review.json');resolutions_path=path.with_name(path.stem+'-resolutions.json')
    payload=read(path);review=read(review_path);resolutions=read(resolutions_path,{})
    if not isinstance(payload,dict) or not isinstance(review,dict):raise ValueError('Plan payload and review sidecar required')
    if review.get('reviewed_ready') is not True:raise ValueError('Curator has not released the plan: reviewed_ready must be true')
    if 'source_flags' in review or 'judgments' in review:
        raise ValueError('Use explicit source_reviews entries with flags/reasons, not legacy source_flags/judgments')
    allowed={'proposed_reorganizations','proposed_revisions','proposed_edge_removals',
        'proposed_source_occurrence_routings','proposed_source_role_corrections','proposed_source_metadata_updates',
        'proposed_locator_corrections','proposed_source_identifier_corrections','proposed_dependency_evidence_updates'}
    unsupported={key for key in review if key.startswith('proposed_')}-allowed
    if unsupported:raise ValueError('Unsupported reviewed operations: '+', '.join(sorted(unsupported)))
    sha=hashlib.sha256(path.read_bytes()+review_path.read_bytes()+json.dumps(resolutions,sort_keys=True).encode()).hexdigest()
    return {'directory':directory,'path':path,'assignment':assignment,'package_sha256':package_sha,
        'task_id':assignment['task_id'],'plan_id':path.name,'sha256':sha,'payload':payload,'review':review,'resolutions':resolutions}


def prior_import(db,plan):
    for row in db.execute("SELECT id,after_json FROM curation_event WHERE operation='curated_task_plan' ORDER BY id"):
        result=json.loads(row['after_json'])
        if result['task_id']==plan['task_id']:
            if result['package_sha256']!=plan['package_sha256']:
                raise ValueError('task_id already belongs to a different pinned package; use a new task_id')
            if result['plan_id']==plan['plan_id']:
                if result['sha256']!=plan['sha256']:raise ValueError('Released plan changed after import; submit a new numbered plan')
                return {**result,'changed':False,'import_event':row['id']}
    return None


def assert_review_inputs(db,plan):
    """Reject completeness reviews based on changed statements or direct inputs.

    A curator may instead give reviewed_against_event after checking the current
    database, which is then guarded by the same exact-event import receipt.
    """
    review=plan['review']
    explicit=review.get('reviewed_against_event')
    if explicit is not None:
        if type(explicit) is not int or explicit!=version(db):raise ValueError('reviewed_against_event is stale')
        if not review.get('current_state_review_reason','').strip():raise ValueError('Current-state review needs a reason')
        return
    path=plan['directory']/plan['assignment']['catalogue']
    with closing(connect(path,True)) as baseline:
        def same_concept(ident):
            old=baseline.execute('SELECT * FROM concept WHERE id=?',(ident,)).fetchone()
            current=db.execute('SELECT * FROM concept WHERE id=?',(ident,)).fetchone()
            keys=('id','slug','title','description','kind','field','revision','status')
            return old is not None and current is not None and all(old[k]==current[k] for k in keys)
        for row in review.get('reviews',[]):
            slug=plan['resolutions'].get('concepts',{}).get(row['slug'],{}).get('target',row['slug'])
            old=baseline.execute('SELECT * FROM concept WHERE slug=?',(slug,)).fetchone()
            current=db.execute('SELECT * FROM concept WHERE slug=?',(slug,)).fetchone()
            if old is None:
                if current is not None:raise ValueError('Reviewed concept was created after task snapshot; refresh task or review current event: '+slug)
                continue
            keys=('id','slug','title','description','kind','field','revision','status')
            if current is None or any(old[k]!=current[k] for k in keys):raise ValueError('Reviewed concept changed since task snapshot: '+slug)
            for table,where,args in [('concept_dependency','dependent_id=?',(old['id'],))]:
                a=[dict(r) for r in baseline.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY id',args)]
                b=[dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY id',args)]
                if a!=b:raise ValueError('Reviewed prerequisite list changed since task snapshot: '+slug)
                if any(not same_concept(edge['prerequisite_id']) for edge in a):
                    raise ValueError('A reviewed prerequisite changed meaning since task snapshot: '+slug)
        for row in review.get('source_reviews',[]):
            slug=row['source']
            for candidate in plan['payload'].get('sources',[]):
                if candidate['slug']!=slug:continue
                matches=set()
                for scheme,value in candidate['identifiers']:
                    key=m.normalize_identifier(scheme,value)
                    found=db.execute('SELECT s.slug FROM source s JOIN source_identifier i ON i.source_id=s.id WHERE i.scheme=? AND i.value=?',key).fetchone()
                    if found:matches.add(found[0])
                if len(matches)>1:raise ValueError('Conflicting source identities in source review')
                if matches:slug=next(iter(matches))
            source=m.lookup(db,'source',slug) if db.execute('SELECT 1 FROM source WHERE slug=?',(slug,)).fetchone() else None
            old=baseline.execute('SELECT * FROM source WHERE slug=?',(slug,)).fetchone()
            if old is None:
                if source is not None:raise ValueError('Reviewed source was created after task snapshot; refresh task or review current event')
                continue
            if source is None or dict(old)!=dict(source):raise ValueError('Reviewed source changed since task snapshot: '+row['source'])
            for table in ('source_concept','citation','source_artifact','source_identifier'):
                order='scheme,value' if table=='source_identifier' else 'id'
                a=[dict(r) for r in baseline.execute(f'SELECT * FROM {table} WHERE source_id=? ORDER BY {order}',(old['id'],))]
                b=[dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE source_id=? ORDER BY {order}',(old['id'],))]
                if a!=b:raise ValueError('Reviewed source inputs changed since task snapshot: '+row['source'])
                if table=='source_concept' and any(not same_concept(link['concept_id']) for link in a):
                    raise ValueError('A concept in the reviewed source changed since task snapshot: '+row['source'])


def execute(db,plan):
    prior=prior_import(db,plan)
    if prior:return prior
    assert_review_inputs(db,plan)
    result=apply_operations(db,plan['payload'],plan['review'],plan['resolutions'],plan['task_id'],plan['plan_id'],plan['sha256'])
    result.update(package_sha256=plan['package_sha256'],assignment=plan['assignment'],engine_sha256=engine_hashes())
    m.event(db,'curated_task_plan','Mechanical import of a released source/cone plan; mathematical completeness remains independently reviewed.',{},result)
    result['import_event']=version(db)
    return result


def check(directory,path,db_path):
    plan=load_plan(directory,path)
    if m.is_postgres_url(db_path):
        # No private copy: apply in the live database's transaction, then roll back.
        with closing(connect(db_path)) as db:
            current=version(db)
            if schema_version(db)!=10:raise ValueError('Migrate database schema explicitly before importing plans')
            with dry_run(db):result=execute(db,plan)
    else:
        with closing(connect(db_path,True)) as live,closing(sqlite3.connect(':memory:',factory=PlanConnection)) as private:
            private.row_factory=sqlite3.Row;private.execute('PRAGMA foreign_keys=ON');live.backup(private)
            current=version(private)
            if schema_version(private)!=10:raise ValueError('Migrate database schema explicitly before importing plans')
            with transaction(private):result=execute(private,plan)
    receipt={'task_id':plan['task_id'],'plan_id':plan['plan_id'],'sha256':plan['sha256'],
        'package_sha256':plan['package_sha256'],'engine_sha256':engine_hashes(),
        'expected_event':current,'database_path':database_identity(db_path),'preflight_ok':True,
        'result':result}
    save(plan['path'].with_name(plan['path'].stem+'-check.json'),receipt)
    return receipt


def import_plan(directory,path,db_path):
    plan=load_plan(directory,path);receipt_path=plan['path'].with_name(plan['path'].stem+'-check.json')
    with closing(connect(db_path)) as db:
        with transaction(db):
            if schema_version(db)!=10:raise ValueError('Migrate database schema explicitly before importing plans')
            previous=prior_import(db,plan)
            if previous:result=previous
            else:
                receipt=read(receipt_path)
                if not receipt or receipt.get('preflight_ok') is not True:raise ValueError('Run check for this plan and database first')
                for key in ('task_id','plan_id','sha256','package_sha256'):
                    if receipt.get(key)!=plan[key]:raise ValueError('Plan/package changed after check; check again')
                if receipt.get('engine_sha256')!=engine_hashes():raise ValueError('Importer, core or schema changed after check; check again')
                if receipt.get('database_path')!=database_identity(db_path) or receipt.get('expected_event')!=version(db):
                    raise ValueError('Database changed after check; check again against current state')
                result=execute(db,plan)
    # SQL commit is authoritative. A failed receipt write can be recovered by
    # repeating import; the exact same released plan will not execute twice.
    save(plan['path'].with_name(plan['path'].stem+'-result.json'),result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('check','import'));parser.add_argument('task',type=Path);parser.add_argument('plan',type=Path)
    parser.add_argument('--db',type=m.database_arg,default=m.DEFAULT_DB);args=parser.parse_args()
    try:
        result=(check if args.command=='check' else import_plan)(args.task,args.plan,args.db)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,sqlite3.Error) as error:
        print(str(error),file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
