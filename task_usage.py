"""Measured task token accounting from API usage or Codex session counters.

Each provider request or log interval has exactly one owner task. Shared
prerequisite tasks are referenced, not duplicated into every paper's own usage.
This program never makes model API calls and never estimates missing counters.
"""
from contextlib import closing
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid


FIELDS=('fresh_input_tokens','cache_read_input_tokens','cache_write_input_tokens','output_tokens','reasoning_output_tokens')


def now():return datetime.now(timezone.utc).isoformat()
def read(path):return json.loads(Path(path).read_text())
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.replace(path)


def connection(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=10000')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS task(id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS shared_task(task_id TEXT REFERENCES task(id), shared_id TEXT REFERENCES task(id),
            PRIMARY KEY(task_id,shared_id),CHECK(task_id<>shared_id));
        CREATE TABLE IF NOT EXISTS sample(id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES task(id),
            source TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
            usage_json TEXT NOT NULL, evidence_json TEXT NOT NULL, recorded_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS session_window(id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES task(id),
            session_path TEXT NOT NULL, start_offset INTEGER NOT NULL, end_offset INTEGER,
            start_counters TEXT, model TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS one_open_session_owner ON session_window(session_path) WHERE end_offset IS NULL;
    ''')
    return db


def nonnegative(value,name):
    if value is not None and (type(value) is not int or value<0):raise ValueError(name+' must be a nonnegative integer or null')
    return value


def normalized(provider,usage):
    if not isinstance(usage,dict):raise ValueError('usage must be an object')
    result={f:None for f in FIELDS}
    if provider in ('anthropic','claude'):
        # Anthropic input excludes separate cache-read/cache-creation tokens.
        for dest,src in [('fresh_input_tokens','input_tokens'),('cache_read_input_tokens','cache_read_input_tokens'),
                         ('cache_write_input_tokens','cache_creation_input_tokens'),('output_tokens','output_tokens')]:
            result[dest]=usage.get(src)
        result['reasoning_output_tokens']=usage.get('reasoning_output_tokens')
    elif provider in ('openai','codex'):
        total=nonnegative(usage.get('input_tokens'),'input_tokens')
        cached=usage.get('cached_input_tokens',usage.get('input_tokens_details',{}).get('cached_tokens'))
        cached=nonnegative(cached,'cached_input_tokens')
        if total is not None and cached is not None and cached>total:raise ValueError('Cache reads exceed total input')
        result.update(fresh_input_tokens=total-cached if total is not None and cached is not None else None,
            cache_read_input_tokens=cached,cache_write_input_tokens=usage.get('cache_write_input_tokens'),
            output_tokens=usage.get('output_tokens'),
            reasoning_output_tokens=usage.get('reasoning_output_tokens',usage.get('output_tokens_details',{}).get('reasoning_tokens')))
    elif provider=='normalized':
        if set(usage)-set(FIELDS):raise ValueError('Unknown normalized usage fields')
        result.update(usage)
    else:raise ValueError('Supported usage formats: anthropic, openai, codex, normalized')
    for field,value in result.items():nonnegative(value,field)
    if result['reasoning_output_tokens'] is not None and result['output_tokens'] is not None and result['reasoning_output_tokens']>result['output_tokens']:
        raise ValueError('Reasoning tokens are a subset of generated output')
    return result


def register(db,task_path=None,task_id=None,kind=None):
    if task_path:
        path=Path(task_path).resolve();assignment=read(path/'assignment.json')
        task_id=assignment['task_id'];manifest=path/'policy-manifest.json'
        if not manifest.is_file():raise ValueError('Prepared task manifest missing')
        expected=read(manifest)['files_sha256'].get('assignment.json')
        if hashlib.sha256((path/'assignment.json').read_bytes()).hexdigest()!=expected:raise ValueError('Task assignment changed')
        metadata={'kind':assignment['kind'],'assignment_sha256':expected,
                  'task_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
    else:
        if not task_id or not kind:raise ValueError('Supply a prepared --task directory or --task-id and --kind')
        metadata={'kind':kind}
    if metadata['kind'] not in ('source','cone','shared','coordination','other'):raise ValueError('Unknown task kind')
    old=db.execute('SELECT metadata FROM task WHERE id=?',(task_id,)).fetchone()
    if old and json.loads(old['metadata'])!=metadata:raise ValueError('Task ID already registered with different inputs/kind')
    with db:db.execute('INSERT OR IGNORE INTO task VALUES (?,?)',(task_id,json.dumps(metadata,sort_keys=True)))
    return task_id


def insert_sample(db,ident,task_id,source,provider,model,usage,evidence):
    if not isinstance(model,str) or not model.strip():raise ValueError('Record the actual model name')
    row={'id':ident,'task_id':task_id,'source':source,'provider':provider,'model':model,
         'usage_json':json.dumps(usage,sort_keys=True),'evidence_json':json.dumps(evidence,sort_keys=True)}
    old=db.execute('SELECT * FROM sample WHERE id=?',(ident,)).fetchone()
    if old:
        if any(old[k]!=value for k,value in row.items()):raise ValueError('Usage evidence already recorded with different content or owner task')
        return False
    db.execute('INSERT INTO sample VALUES (?,?,?,?,?,?,?,?)',(*row.values(),now()))
    return True


def record_api(db,task_id,response):
    provider={'claude':'anthropic'}.get(response['provider'],response['provider']);request_id=response.get('request_id')
    if not isinstance(request_id,str) or not request_id.strip():raise ValueError('Provider request_id required for duplicate detection')
    usage=normalized(provider,response['usage'])
    evidence={'request_id':request_id,'raw_usage':response['usage'],
              'started_at':response.get('started_at'),'finished_at':response.get('finished_at'),
              'settings':response.get('settings',{})}
    ident=provider+':request:'+request_id
    with db:return insert_sample(db,ident,task_id,'api_response',provider,response['model'],usage,evidence)


def log_events(path,start=0,end=None):
    """Only complete JSONL records count. Never parse arbitrary conversation text."""
    path=Path(path)
    if not path.exists():
        if start:raise ValueError('Session log disappeared')
        return [],0
    events=[]
    with path.open('rb') as file:
        if file.seek(0,2)<start:raise ValueError('Session log was truncated')
        file.seek(start);offset=start
        while True:
            line=file.readline()
            if not line or (end is not None and file.tell()>end) or not line.endswith(b'\n'):break
            try:event=json.loads(line)
            except (ValueError,UnicodeDecodeError):raise ValueError('Invalid complete JSONL record in session log') from None
            # Retain only accounting records, not prompts, tool output or papers.
            if event.get('type')=='turn_context':
                events.append((offset,file.tell(),{'type':'turn_context','payload':{'model':event.get('payload',{}).get('model')}}))
            elif event.get('type')=='event_msg' and event.get('payload',{}).get('type')=='token_count':
                events.append((offset,file.tell(),event))
            offset=file.tell()
    return events,offset


def counters(event):
    payload=event.get('payload',{})
    if event.get('type')!='event_msg' or payload.get('type')!='token_count':return None
    info=payload.get('info') or {};value=info.get('total_token_usage')
    if value is None:return None
    for key,count in value.items():
        if key.endswith('tokens'):nonnegative(count,key)
    return value


def prefix_hash(path,end):
    digest=hashlib.sha256()
    if end:
        with Path(path).open('rb') as file:
            remaining=end
            while remaining:
                chunk=file.read(min(1024*1024,remaining))
                if not chunk:raise ValueError('Session log was truncated')
                digest.update(chunk);remaining-=len(chunk)
    return digest.hexdigest()


def start_window(db,task_id,session,model):
    if not model.strip():raise ValueError('Record the actual model name')
    path=str(Path(session).resolve());events,offset=log_events(path)
    before=None
    for _,_,event in events:
        value=counters(event)
        if value is not None:before=value
    ident=str(uuid.uuid4());baseline={'counters':before,'prefix_sha256':prefix_hash(path,offset)}
    with db:
        # One active owner per session. Resumption uses another nonoverlapping window.
        if db.execute('SELECT 1 FROM session_window WHERE session_path=? AND end_offset IS NULL',(path,)).fetchone():
            raise ValueError('Session already has an open task interval; finish it before switching tasks')
        db.execute('INSERT INTO session_window VALUES (?,?,?,?,NULL,?,?,?,NULL)',
                   (ident,task_id,path,offset,json.dumps(baseline,sort_keys=True),model,now()))
    return {'window_id':ident,'task_id':task_id,'start_offset':offset,'session_path':path}


def finish_window(db,ident):
    row=db.execute('SELECT * FROM session_window WHERE id=?',(ident,)).fetchone()
    if row is None:raise ValueError('Unknown window_id')
    if row['end_offset'] is not None:
        return {'window_id':ident,'changed':False,'end_offset':row['end_offset']}
    before=json.loads(row['start_counters']);path=row['session_path']
    if prefix_hash(path,row['start_offset'])!=before['prefix_sha256']:raise ValueError('Session prefix changed after task start')
    events,end=log_events(path,row['start_offset']);previous=before['counters'];records=[];observations=0
    totals={key:0 for key in ('input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens','reasoning_output_tokens')}
    known={key:True for key in totals}
    for start,stop,event in events:
        if event.get('type')=='turn_context' and event.get('payload',{}).get('model') not in (None,row['model']):
            raise ValueError('Session model changed or differs from recorded model; split intervals by model')
        current=counters(event)
        if current is None:continue
        if previous==current:continue # Duplicate notifications carry no extra usage.
        if previous is None:
            # A genuinely new log has a zero baseline; an existing session without
            # a reported baseline cannot be attributed to this interval reliably.
            if row['start_offset']!=0:raise ValueError('No initial counter baseline; cannot attribute cumulative usage to task')
            previous={key:0 for key in current}
        delta={}
        for key in totals:
            if current.get(key) is None or previous.get(key) is None:
                known[key]=False;continue
            change=current[key]-previous[key]
            if change<0:raise ValueError('Session token counters reset; no guessed attribution recorded')
            delta[key]=change;totals[key]+=change
        records.append({'start_offset':start,'end_offset':stop,'timestamp':event.get('timestamp'),
                        'before':previous,'after':current,'delta':delta})
        previous=current;observations+=1
    usage=normalized('codex',{key:totals[key] if known[key] and observations else None for key in totals})
    evidence={'session_path':path,'start_offset':row['start_offset'],'end_offset':end,
        'prefix_sha256':prefix_hash(path,end),'counter_changes':records,'started_at':row['started_at'],'finished_at':now(),
        'limits':'Recorded cumulative counters in this exact log interval, not a provider invoice. Complete work and wait for its usage event before finishing. No descendants or other sessions included. No-counter interval stays unknown.'}
    with db:
        if db.execute('SELECT 1 FROM session_window WHERE session_path=? AND id<>? AND end_offset IS NOT NULL AND start_offset<? AND end_offset>?',
                      (path,ident,end,row['start_offset'])).fetchone():raise ValueError('Overlapping previously recorded session interval')
        changed=insert_sample(db,'codex:window:'+ident,row['task_id'],'session_counter_delta','codex',row['model'],usage,evidence)
        db.execute('UPDATE session_window SET end_offset=?,finished_at=? WHERE id=?',(end,evidence['finished_at'],ident))
    return {'window_id':ident,'changed':changed,'usage':usage,'counter_events':observations,'end_offset':end}


def abandon_window(db,ident,reason):
    """Close unusable telemetry explicitly as unknown, preserving the explanation."""
    if not reason.strip():raise ValueError('Explain why usage cannot be measured')
    row=db.execute('SELECT * FROM session_window WHERE id=?',(ident,)).fetchone()
    if row is None:raise ValueError('Unknown window_id')
    if row['end_offset'] is not None:return {'window_id':ident,'changed':False}
    path=Path(row['session_path']);end=max(row['start_offset'],path.stat().st_size if path.exists() else 0)
    evidence={'session_path':str(path),'start_offset':row['start_offset'],'end_offset':end,
        'started_at':row['started_at'],'finished_at':now(),'abandoned_measurement':True,'reason':reason}
    with db:
        changed=insert_sample(db,'codex:window:'+ident,row['task_id'],'unavailable_session_measurement','codex',row['model'],
            {field:None for field in FIELDS},evidence)
        db.execute('UPDATE session_window SET end_offset=?,finished_at=? WHERE id=?',(end,evidence['finished_at'],ident))
    return {'window_id':ident,'changed':changed,'usage_unknown':True}


def link_shared(db,task_id,shared_id):
    if task_id==shared_id:raise ValueError('Task cannot share itself')
    # Enforce a DAG; totals walk each shared task only once.
    pending=[shared_id];seen=set()
    while pending:
        current=pending.pop()
        if current==task_id:raise ValueError('Shared-task reference would create a cycle')
        if current in seen:continue
        seen.add(current);pending.extend(r[0] for r in db.execute('SELECT shared_id FROM shared_task WHERE task_id=?',(current,)))
    with db:db.execute('INSERT OR IGNORE INTO shared_task VALUES (?,?)',(task_id,shared_id))


def summarize(samples):
    values=[json.loads(r['usage_json']) for r in samples]
    totals={key:(sum(v[key] for v in values) if values and all(v[key] is not None for v in values) else None) for key in FIELDS}
    return {'samples':len(values),'tokens':totals,
        'known_subtotals':{key:sum(v[key] for v in values if v[key] is not None) for key in FIELDS},
        'unknown_samples':{key:sum(v[key] is None for v in values) for key in FIELDS},
        'note':'Cache reads/writes are separate inputs. Reasoning is already included in output; do not add it again. No samples means unknown, not zero.'}


def report(db,task_ids):
    if not task_ids:task_ids=[r[0] for r in db.execute('SELECT id FROM task ORDER BY id')]
    included=set(task_ids);queue=list(task_ids)
    while queue:
        ident=queue.pop()
        if not db.execute('SELECT 1 FROM task WHERE id=?',(ident,)).fetchone():raise ValueError('Unknown task '+ident)
        for row in db.execute('SELECT shared_id FROM shared_task WHERE task_id=?',(ident,)):
            if row[0] not in included:included.add(row[0]);queue.append(row[0])
    tasks={};all_samples=[]
    for ident in sorted(included):
        samples=[dict(r) for r in db.execute('SELECT * FROM sample WHERE task_id=? ORDER BY id',(ident,))]
        all_samples+=samples
        tasks[ident]={'metadata':json.loads(db.execute('SELECT metadata FROM task WHERE id=?',(ident,)).fetchone()[0]),
            'own_usage':summarize(samples),'shared_tasks':[r[0] for r in db.execute('SELECT shared_id FROM shared_task WHERE task_id=? ORDER BY shared_id',(ident,))],
            'open_windows':[r[0] for r in db.execute('SELECT id FROM session_window WHERE task_id=? AND end_offset IS NULL',(ident,))],
            'evidence':[dict(id=r['id'],source=r['source'],provider=r['provider'],model=r['model'],
                usage=json.loads(r['usage_json']),evidence=json.loads(r['evidence_json'])) for r in samples]}
        tasks[ident]['measurement_complete']=bool(samples) and not tasks[ident]['open_windows'] and all(
            any(v is not None for v in json.loads(sample['usage_json']).values()) for sample in samples)
        if not tasks[ident]['measurement_complete']:tasks[ident]['own_usage']['tokens']={field:None for field in FIELDS}
    total=summarize(all_samples)
    unknown_tasks=[ident for ident,t in tasks.items() if not t['measurement_complete']]
    if unknown_tasks:total['tokens']={field:None for field in FIELDS}
    return {'requested_tasks':task_ids,'included_tasks':sorted(included),'tasks':tasks,
        'unique_total':total,'measurement_complete':not unknown_tasks,'tasks_without_complete_measurement':unknown_tasks,
        'shared_cost_policy':'Own usage stays on its task. Shared tasks included once in unique_total, with no invented per-paper allocation.',
        'open_windows':sum(len(t['open_windows']) for t in tasks.values())}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger',type=Path,required=True);cmd=parser.add_subparsers(dest='command',required=True)
    def task_args(p):
        group=p.add_mutually_exclusive_group(required=True);group.add_argument('--task',type=Path);group.add_argument('--task-id')
        p.add_argument('--kind',choices=('source','cone','shared','coordination','other'))
    reg=cmd.add_parser('register');task_args(reg)
    record=cmd.add_parser('record');task_args(record);record.add_argument('--response',type=Path,required=True)
    start=cmd.add_parser('start');task_args(start);start.add_argument('--session',type=Path,required=True);start.add_argument('--model',required=True)
    finish=cmd.add_parser('finish');finish.add_argument('window_id')
    abandon=cmd.add_parser('abandon');abandon.add_argument('window_id');abandon.add_argument('--reason',required=True)
    shared=cmd.add_parser('share');shared.add_argument('--task-id',required=True);shared.add_argument('--shared-task-id',required=True)
    show=cmd.add_parser('report');show.add_argument('--task-id',action='append',default=[]);show.add_argument('--out',type=Path)
    args=parser.parse_args()
    try:
        with closing(connection(args.ledger)) as db:
            if args.command in ('register','record','start'):
                ident=register(db,args.task,args.task_id,args.kind)
            if args.command=='register':result={'registered':ident}
            elif args.command=='record':result={'task_id':ident,'changed':record_api(db,ident,read(args.response))}
            elif args.command=='start':result=start_window(db,ident,args.session,args.model)
            elif args.command=='finish':result=finish_window(db,args.window_id)
            elif args.command=='abandon':result=abandon_window(db,args.window_id,args.reason)
            elif args.command=='share':link_shared(db,args.task_id,args.shared_task_id);result={'linked':True}
            else:
                result=report(db,args.task_id)
                if args.out:save(args.out,result)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,sqlite3.Error) as error:
        print(str(error),file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
