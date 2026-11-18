"""Prepare curation tasks and import their results.

A task directory holds `assignment.json` and a read-only `catalogue.sqlite`
snapshot. The worker writes `output/result.json`; after a merge review against the
live catalogue, `import` applies it in a single transaction. See
docs/CURATION_TASKS.md for the result format.
"""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

import mathdb as m


def read(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default


def digest(path):
    with Path(path).open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()


def save(path, value):
    path=Path(path);temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(path)


def resolve_identities(db,payload,resolutions):
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
                raise ValueError('Same slug, different text: map it in same_as or choose a new slug: '+c['slug'])
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




def apply_operations(db, result_file, task_id, fingerprint):
    payload=result_file.get('changes',{});ops=result_file.get('operations',{})
    resolutions={'concepts':result_file.get('same_as',{})}
    # Full split/merge plans use the core's exact incident routing validation.
    # Do these before append operations and explicit post-change review judgments.
    for reorganization in ops.get('reorganizations',[]):
        m.reorganize(db,reorganization)
    revisions=ops.get('revisions',[])
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
    batch,decisions,concept_map,source_map,purpose_updates=resolve_identities(db,payload,resolutions)
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
        for removal in ops.get('edge_removals',[]):
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
        for route in ops.get('occurrence_routings',[]):
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
        correct_source_roles(db,ops.get('source_role_corrections',[]))
        correct_source_metadata(db,ops.get('source_metadata_updates',[]))
        correct_locators(db,ops.get('locator_corrections',[]))
        correct_source_identifiers(db,ops.get('source_identifier_corrections',[]))
        correct_dependency_evidence(db,ops.get('dependency_evidence_updates',[]))
    reduction=m.reduce_dependencies(db,'Transitive reduction after task '+task_id+'; preserve typed evidence and witnesses.')
    for r in result_file.get('concept_reviews',[]):
        flags={k:r[k] for k in ('statement_prerequisites_complete','proof_prerequisites_complete') if k in r}
        if not flags or any(type(v) is not bool for v in flags.values()) or not r.get('reason','').strip():
            raise ValueError('Each cone node requires an explicit boolean judgment and mathematical reason')
        slug=concept_map.get(r['slug'],r['slug'])
        m.set_completeness(db,'concept',slug,flags,r['reason'])
    for r in result_file.get('source_reviews',[]):
        flags=r.get('flags',{})
        reasons=r.get('flag_reasons',{})
        if (not flags or not set(flags)<= {'requirements_complete','introductions_complete','citations_complete'}
                or any(type(v) is not bool for v in flags.values())
                or any(not reasons.get(k,r.get('reason','')).strip() for k in flags)):
            raise ValueError('Source review requires explicit independent boolean judgments and a reason')
        for key,value in flags.items():
            m.set_completeness(db,'source',source_map.get(r['source'],r['source']),{key:value},reasons.get(key,r.get('reason')))
    result={'changed':True,'task_id':task_id,'sha256':fingerprint,
            'new_concepts':len(batch.get('concepts',[])),'new_sources':len(batch.get('sources',[])),
            'new_citations':len(batch.get('citations',[])),'identities':decisions,'purpose_updates':purpose_updates,
            'concept_reviews':result_file.get('concept_reviews',[]),'source_reviews':result_file.get('source_reviews',[]),
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
def rolled_back(db):
    """Apply edits inside one transaction and always roll them back."""
    if db.in_transaction:raise ValueError('Dry run requires a connection without an existing transaction')
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


SECTIONS={'changes','same_as','operations','concept_reviews','source_reviews','notes'}
OPERATIONS={'reorganizations','revisions','edge_removals','occurrence_routings','source_role_corrections',
    'source_metadata_updates','locator_corrections','source_identifier_corrections','dependency_evidence_updates'}


def load_result(directory):
    """Read a task's assignment and result.json, rejecting unknown sections."""
    directory=Path(directory).resolve()
    assignment=read(directory/'assignment.json')
    if not assignment or not assignment.get('task_id'):raise ValueError('No assignment.json with a task_id in '+str(directory))
    path=directory/'output/result.json'
    result=read(path)
    if not isinstance(result,dict):raise ValueError('Missing or invalid '+str(path))
    unknown=set(result)-SECTIONS
    if unknown:raise ValueError('Unknown result sections: '+', '.join(sorted(unknown)))
    unknown=set(result.get('operations',{}))-OPERATIONS
    if unknown:raise ValueError('Unknown operations: '+', '.join(sorted(unknown)))
    for slug,entry in result.get('same_as',{}).items():
        if not isinstance(entry,dict) or not entry.get('target') or not entry.get('reason','').strip():
            raise ValueError('same_as entries need a target and a reason: '+slug)
    return {'directory':directory,'task_id':assignment['task_id'],'result':result,
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def previous_import(db,task):
    for row in db.execute("SELECT id,after_json FROM curation_event WHERE operation='curated_task_plan' ORDER BY id"):
        done=json.loads(row['after_json'])
        if done['task_id']==task['task_id']:
            if done['sha256']!=task['sha256']:
                raise ValueError('Task '+task['task_id']+' was already imported with a different result; prepare a new task for further changes')
            return {**done,'changed':False,'import_event':row['id']}
    return None


def apply(db,task):
    if schema_version(db)!=10:raise ValueError('Migrate database schema explicitly before importing')
    done=previous_import(db,task)
    if done:return done
    result=apply_operations(db,task['result'],task['task_id'],task['sha256'])
    m.event(db,'curated_task_plan','Import of a merged task result.',{},result)
    result['import_event']=version(db)
    return result


def import_result(directory,db_path,dry_run=False):
    """Apply output/result.json to the database in one transaction.

    With dry_run, apply it and roll back (PostgreSQL), or apply it to a private
    in-memory copy (SQLite), leaving everything unchanged.
    """
    task=load_result(directory)
    if dry_run:
        with closing(connect(db_path)) as db:
            if m.is_postgres(db):
                with rolled_back(db):return apply(db,task)
        with closing(connect(db_path,True)) as live,closing(sqlite3.connect(':memory:',factory=PlanConnection)) as db:
            db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');live.backup(db)
            with transaction(db):return apply(db,task)
    with closing(connect(db_path)) as db:
        with transaction(db):result=apply(db,task)
    save(task['directory']/'output/import.json',result)
    return result


DEFAULT_BASELINE='Sets and natural numbers, elementary logic and finite arithmetic'
PROMPTS={'source':'prompts/ingest-source.md','cone':'prompts/expand-prerequisites.md'}


def prepare_task(kind,assignment,output,db_path):
    """Create a task directory: assignment.json plus a read-only SQLite catalogue snapshot.

    db_path is an SQLite file or a PostgreSQL URL; either is copied to catalogue.sqlite.
    """
    output=Path(output).resolve()
    postgres=m.is_postgres_url(db_path)
    if not postgres:
        db_path=Path(db_path).resolve()
        if not db_path.is_file():raise ValueError('Catalogue does not exist')
    if output.exists():raise ValueError('Task directory exists; refusing to overwrite')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}',assignment.get('task_id','')):
        raise ValueError('task_id must use letters, digits, dots, colons, underscores or hyphens')
    if kind=='source' and not assignment.get('source_identifiers'):raise ValueError('Source identifiers required')
    if kind=='cone' and not assignment.get('roots'):raise ValueError('At least one concept root required')
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.curation-task-',dir=output.parent))
    try:
        if postgres:
            import pg_sync
            pg_sync.export(str(db_path),temp/'catalogue.sqlite')
        else:
            with closing(sqlite3.connect(db_path.as_uri()+'?mode=ro',uri=True)) as live:
                with closing(sqlite3.connect(temp/'catalogue.sqlite')) as private:live.backup(private)
        with closing(sqlite3.connect(temp/'catalogue.sqlite')) as db:
            db.row_factory=sqlite3.Row
            event=db.execute('SELECT max(id) FROM curation_event').fetchone()[0]
            roots=[]
            for root in assignment.get('roots',[]):
                if isinstance(root,str):root={'slug':root}
                rows=db.execute("SELECT id,slug,title FROM concept WHERE (id=? OR slug=?) AND status='active'",(root.get('id'),root.get('slug'))).fetchall()
                if len(rows)!=1:raise ValueError('Root identity missing or ambiguous: '+str(root))
                row=dict(rows[0])
                if any(root.get(k) and root[k]!=row[k] for k in ('id','slug')):raise ValueError('Root UUID and slug disagree')
                roots.append(row)
        try:commit=subprocess.run(['git','-C',str(m.ROOT),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
        except (OSError,subprocess.CalledProcessError):commit=None
        result=dict(assignment,kind=kind,prompt=PROMPTS[kind],repository=str(m.ROOT),repository_commit=commit,
            catalogue='catalogue.sqlite',catalogue_event=event,output_directory='output',
            prepared_at_utc=datetime.now(timezone.utc).isoformat(),
            baseline=assignment.get('baseline') or DEFAULT_BASELINE)
        if roots:result['roots']=roots
        artifact=result.get('artifact')
        if artifact and artifact.get('path'):
            source=Path(artifact['path']).resolve()
            if artifact.get('sha256') and artifact['sha256']!=digest(source):raise ValueError('Artifact hash mismatch')
            target=temp/('artifact'+source.suffix);shutil.copyfile(source,target)
            result['artifact']=dict(artifact,path=target.name,sha256=digest(target))
        (temp/'output').mkdir()
        save(temp/'assignment.json',result);temp.rename(output)
        return result
    except BaseException:
        shutil.rmtree(temp,ignore_errors=True);raise


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare',help='create a task directory')
    p.add_argument('--kind',choices=('source','cone'),required=True)
    p.add_argument('--assignment',type=Path,required=True,help='JSON file with task_id and source_identifiers or roots')
    p.add_argument('--out',type=Path,required=True,help='new task directory')
    p.add_argument('--db',type=m.database_arg,default=m.DEFAULT_DB)
    i=sub.add_parser('import',help='apply TASK/output/result.json')
    i.add_argument('task',type=Path);i.add_argument('--db',type=m.database_arg,default=m.DEFAULT_DB)
    i.add_argument('--dry-run',action='store_true',help='apply to a private copy only')
    args=parser.parse_args()
    try:
        if args.command=='prepare':
            done=prepare_task(args.kind,json.loads(args.assignment.read_text()),args.out,args.db)
            print(json.dumps({k:done[k] for k in ('task_id','catalogue_event')},indent=2))
        else:
            print(json.dumps(import_result(args.task,args.db,args.dry_run),ensure_ascii=False,indent=2))
        return 0
    except (ValueError,OSError,KeyError,sqlite3.Error) as error:
        print(str(error),file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
