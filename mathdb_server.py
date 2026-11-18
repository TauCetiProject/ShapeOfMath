"""Local browser and versioned JSON API for the mathematical concept database."""
from __future__ import annotations

import argparse
from contextlib import closing
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import signal
import sqlite3
import subprocess
import sys
import sysconfig
import tempfile
import time
from urllib.parse import parse_qs, unquote, urlsplit

import mathdb as m

MAX_BODY = 2 * 1024 * 1024
WEB = m.ROOT / 'web'
if not WEB.is_dir():
    WEB = Path(sysconfig.get_path('data')) / 'share/the-shape-of-math/web'
DOCS = m.ROOT / 'API.md'
if not DOCS.exists():
    DOCS = WEB.parent / 'API.md'

EXPERIMENT_REPORTS = m.ROOT / 'experiments/curation-2015'
if not EXPERIMENT_REPORTS.is_dir():
    EXPERIMENT_REPORTS = WEB.parent / 'experiments/curation-2015'
PUBLIC_REPORTS = ('sample.tsv', 'report.txt', 'fa-analysis.txt', 'nt-analysis.txt',
                  'fa-cone.txt', 'nt-cone.txt', 'numerical-range.svg',
                  'product-vector-subspaces-field.svg', 'unresolved.json')
OVERLAP_REPORTS = ('index.html', 'explorer.js', 'explorer.css', 'snapshot.json',
                   'results.json', 'curves.csv', 'papers.csv', 'report.md',
                   'model-report.md', 'model-results.json', 'prospective-predictions.json',
                   'model-pilot.png', 'model-pilot.svg', 'model-pilot.pdf') + tuple(
    name + '.' + extension
    for name in ('reading-marginal', 'reading-cumulative', 'reading_introduced-marginal',
                 'reading_introduced-cumulative', 'all_linked-marginal', 'all_linked-cumulative',
                 'reading-diagnostics', 'reading-pairwise')
    for extension in ('svg', 'png', 'pdf'))
EXPANDED_OVERLAP_REPORTS = ('index.html', 'explorer.js', 'snapshot.json', 'results.json',
    'curves.csv', 'report.md', 'model-results.json', 'verification.json',
    'models.png', 'models.svg', 'models.pdf') + tuple(
        dataset+'-'+metric+'.'+extension
        for dataset in ('all60', 'reviewed58', 'first30', 'next30')
        for metric in ('known', 'marginal', 'cumulative')
        for extension in ('svg', 'png', 'pdf'))


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def version(db):
    return str(db.execute('SELECT coalesce(max(id),0) FROM curation_event').fetchone()[0])


def fields(item, allowed, required=()):
    if not isinstance(item, dict):
        raise ValueError('Expected a JSON object')
    unknown = set(item) - set(allowed)
    missing = set(required) - set(item)
    if unknown or missing:
        raise ValueError(f'Unexpected fields: {sorted(unknown)}; missing fields: {sorted(missing)}')


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


def concept_detail(db, slug):
    out = dict(m.lookup(db, 'concept', slug))
    for name, own, other in [('prerequisites','dependent_id','prerequisite_id'),
                              ('dependents','prerequisite_id','dependent_id')]:
        out[name] = rows(db, f'''SELECT c.*,d.id AS edge_id,d.basis,d.rationale,d.evidence_source_id,d.locator,d.purpose
            FROM concept_dependency d JOIN concept c ON c.id=d.{other} WHERE d.{own}=? ORDER BY c.title''', (out['id'],))
    out['related'] = m.related(db, slug)
    out['formalizations'] = m.formalizations(db, concept=slug)
    out['sources'] = rows(db, '''SELECT s.id,s.slug,s.title,s.year,sc.id AS link_id,sc.role,sc.locator,sc.note,sc.introduction_evidence
        FROM active_source_concept sc JOIN source s ON s.id=sc.source_id WHERE sc.concept_id=? ORDER BY s.title''', (out['id'],))
    return out


def source_detail(db, slug):
    out = dict(m.lookup(db, 'source', slug))
    out['authors'] = json.loads(out['authors'])
    out['identifiers'] = rows(db, 'SELECT scheme,value FROM source_identifier WHERE source_id=?', (out['id'],))
    out['concepts'] = rows(db, '''SELECT c.*,sc.id AS link_id,sc.role,sc.locator,sc.note FROM active_source_concept sc
        JOIN concept c ON c.id=sc.concept_id WHERE sc.source_id=? ORDER BY c.title''', (out['id'],))
    out['citations'] = [m.citation_record(db, r[0]) for r in db.execute('SELECT id FROM citation WHERE source_id=? ORDER BY id', (out['id'],))]
    out['cited_by'] = rows(db, '''SELECT s.slug,s.title,c.id AS citation_id,c.label FROM citation c
        JOIN source s ON s.id=c.source_id WHERE c.cited_source_id=? ORDER BY s.title''', (out['id'],))
    out['relations'] = rows(db, 'SELECT * FROM source_relation WHERE dependent_id=? OR prerequisite_id=?', (out['id'],out['id']))
    out['requirements'] = m.source_requirements(db,slug)
    return out


def read_api(db, parts, query):
    if parts == ['state']:
        return {'version': version(db), 'stats': m.verify(db), 'data': m.snapshot(db), 'formalizations': m.formalizations(db)}
    if parts == ['formalizations']:
        return m.formalizations(db, **{key: query[key][0] for key in ('concept', 'library', 'status') if key in query})
    if parts == ['formalization-libraries']:
        return rows(db, 'SELECT * FROM formalization_library ORDER BY name')
    if parts == ['formalization-files']:
        library = query.get('library', [None])[0]
        if library:
            m.library_record(db, library)
        return rows(db, 'SELECT * FROM formalization_file WHERE (CAST(? AS TEXT) IS NULL OR library_slug=?) ORDER BY library_slug,path', (library,library))
    if parts == ['history']:
        limit = int(query.get('limit', ['20'])[0])
        if not 1 <= limit <= 100:
            raise ValueError('History limit must be between 1 and 100')
        before = int(query.get('before', [str(2**63-1)])[0])
        return rows(db, 'SELECT id,occurred_at,operation,reason FROM curation_event WHERE id<? ORDER BY id DESC LIMIT ?', (before,limit))
    if len(parts) == 2 and parts[0] == 'history':
        row = db.execute('SELECT * FROM curation_event WHERE id=?', (int(parts[1]),)).fetchone()
        if row is None:
            raise APIError(404, 'Unknown history event')
        out = dict(row)
        for key in ('before_json','after_json'):
            out[key] = json.loads(out[key])
        return out
    if parts in (['concepts'], ['sources']):
        table = 'concept' if parts[0] == 'concepts' else 'source'
        result = rows(db, f'SELECT * FROM {table} ORDER BY title')
        q = query.get('q', [''])[0].casefold()
        return [r for r in result if (table != 'concept' or r['status']=='active') and
                q in ' '.join(str(r.get(k,'')) for k in ('title','slug','description','field','authors')).casefold()]
    if len(parts) == 2 and parts[0] == 'concepts':
        return concept_detail(db, parts[1])
    if len(parts) == 3 and parts[0] == 'concepts' and parts[2] == 'cone':
        return m.prerequisite_cone(db, parts[1],query.get('mode',['statement'])[0])
    if len(parts) == 3 and parts[0] == 'concepts' and parts[2] == 'reduction':
        return m.reduction_plan(db, parts[1])
    if len(parts) == 2 and parts[0] == 'sources':
        return source_detail(db, parts[1])
    if len(parts) == 2 and parts[0] == 'citations':
        return m.citation_record(db, int(parts[1]))
    raise APIError(404, 'Unknown API endpoint')


def row_by_id(db, table, ident):
    # All callers choose the table from fixed code, never a request field.
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (int(ident),)).fetchone()
    if row is None:
        raise APIError(404, f'Unknown {table} record')
    return dict(row)


def write_api(db, method, parts, payload):
    if not isinstance(payload, dict):
        raise ValueError('Expected a JSON object')
    item = dict(payload)
    reason = item.pop('reason', '')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Every edit requires a nonempty reason')
    if method == 'POST' and parts == ['concepts']:
        fields(item, ('slug','title','kind','description','field','boundary','aliases'), ('slug','title','kind','description','field'))
        ident = m.add_concept(db, item)
        out = dict(m.lookup(db,'concept',ident))
        m.event(db,'create_concept',reason,{},out)
        return out
    if method == 'POST' and parts == ['formalization-libraries']:
        return m.save_library(db, item, reason)
    if method == 'POST' and parts == ['formalization-files']:
        return m.save_formalization_file(db, item, reason)
    if method == 'POST' and len(parts)==4 and parts[0]=='concepts' and parts[2]=='formalizations':
        return m.save_formalization(db, parts[1], parts[3], item, reason)
    if method == 'PATCH' and len(parts)==2 and parts[0]=='concepts':
        m.revise(db,parts[1],item,reason)
        return dict(m.lookup(db,'concept',parts[1]))
    if method == 'POST' and parts == ['sources']:
        fields(item, ('slug','title','authors','year','field','status','coverage','summary','dependency_review','identifiers','artifacts'),
               ('slug','title','authors','field','status','coverage','summary','dependency_review','identifiers'))
        if not isinstance(item['authors'],list) or not all(isinstance(x,str) for x in item['authors']):
            raise ValueError('authors must be an array of names')
        m.ingest(db, {'sources':[item], 'note':reason})
        return dict(m.lookup(db,'source',item['slug']))
    if method == 'PATCH' and len(parts)==2 and parts[0]=='sources':
        allowed=('title','authors','year','field','status','coverage','summary','dependency_review')
        fields(item,allowed)
        if not item:
            raise ValueError('No source changes supplied')
        before=dict(m.lookup(db,'source',parts[1]))
        if 'authors' in item:
            if not isinstance(item['authors'],list) or not all(isinstance(x,str) for x in item['authors']):
                raise ValueError('authors must be an array of names')
            item['authors']=json.dumps(item['authors'],ensure_ascii=False)
        db.execute(f"UPDATE source SET {','.join(k+'=?' for k in item)} WHERE id=?", (*item.values(),before['id']))
        out=dict(m.lookup(db,'source',parts[1]))
        m.event(db,'revise_source',reason,before,out)
        return out
    if method=='POST' and len(parts)==3 and parts[0]=='sources' and parts[2]=='identifiers':
        fields(item,('scheme','value'),('scheme','value'))
        sid=m.lookup(db,'source',parts[1])['id']
        before=rows(db,'SELECT scheme,value FROM source_identifier WHERE source_id=?',(sid,))
        m.add_identifier(db,sid,item['scheme'],item['value'])
        out=rows(db,'SELECT scheme,value FROM source_identifier WHERE source_id=?',(sid,))
        m.event(db,'add_source_identifier',reason,before,out)
        return out
    if method=='POST' and parts==['dependencies']:
        fields(item,('prerequisite','dependent','basis','rationale','source','locator','purpose'),('prerequisite','dependent','basis','rationale'))
        m.add_edge(db,item)
        ids=[m.lookup(db,'concept',item[k])['id'] for k in ('prerequisite','dependent')]
        out=row_by_id(db,'concept_dependency',db.execute('SELECT id FROM concept_dependency WHERE prerequisite_id=? AND dependent_id=?',ids).fetchone()[0])
        m.event(db,'add_dependency',reason,{},out)
        return out
    if method=='PATCH' and len(parts)==2 and parts[0]=='dependencies':
        fields(item,('prerequisite','dependent','basis','rationale','source','locator','purpose'))
        before=row_by_id(db,'concept_dependency',parts[1])
        values={k:v for k,v in item.items() if k in ('basis','rationale','locator','purpose')}
        for key,column,table in [('prerequisite','prerequisite_id','concept'),('dependent','dependent_id','concept'),('source','evidence_source_id','source')]:
            if key in item:
                values[column]=m.lookup(db,table,item[key])['id'] if item[key] else None
        if not values:
            raise ValueError('No dependency changes supplied')
        db.execute(f"UPDATE concept_dependency SET {','.join(k+'=?' for k in values)} WHERE id=?",(*values.values(),before['id']))
        out=row_by_id(db,'concept_dependency',parts[1])
        m.event(db,'revise_dependency',reason,before,out)
        return out
    if method=='POST' and parts==['related']:
        fields(item,('concept_a','concept_b','rationale','source','locator'),('concept_a','concept_b','rationale'))
        m.add_related(db,item)
        a,b=sorted(m.lookup(db,'concept',item[k])['id'] for k in ('concept_a','concept_b'))
        out=row_by_id(db,'concept_related',db.execute('SELECT id FROM concept_related WHERE concept_a_id=? AND concept_b_id=?',(a,b)).fetchone()[0])
        m.event(db,'relate',reason,{},out)
        return out
    if method=='POST' and parts==['source-concepts']:
        fields(item,('source','concept','role','locator','note','introduction_evidence'),('source','concept','role','locator'))
        m.add_link(db,item)
        out=rows(db,'''SELECT * FROM source_concept WHERE source_id=? AND concept_id=? AND role=? AND locator=?''',
                 (m.lookup(db,'source',item['source'])['id'],m.lookup(db,'concept',item['concept'])['id'],m.canonical_role(item['role']),item['locator']))[0]
        m.event(db,'link',reason,{},out)
        return out
    if method=='PATCH' and len(parts)==2 and parts[0]=='source-concepts':
        fields(item,('role','locator','note','introduction_evidence'))
        before=row_by_id(db,'source_concept',parts[1])
        if m.lookup(db,'concept',before['concept_id'])['status']!='active':
            raise ValueError('Cannot edit a historical occurrence')
        if not item:
            raise ValueError('No occurrence changes supplied')
        if 'role' in item:
            item['role']=m.canonical_role(item['role'])
        effective={**before,**item}
        if effective['role']=='introduces' and (not isinstance(effective['introduction_evidence'],str) or not effective['introduction_evidence'].strip()):
            raise ValueError('introduces requires introduction_evidence for an original contribution')
        db.execute(f"UPDATE source_concept SET {','.join(k+'=?' for k in item)} WHERE id=?",(*item.values(),before['id']))
        out=row_by_id(db,'source_concept',parts[1])
        m.event(db,'revise_source_concept',reason,before,out)
        return out
    if method=='POST' and parts==['citations']:
        fields(item,('source','label','text','cited_source','pedagogically_necessary','needed_material','identifiers'),('source','text'))
        out=m.citation_record(db,m.add_citation(db,item))
        m.event(db,'add_citation',reason,{},out)
        return out
    if method=='POST' and parts==['citations','resolve']:
        fields(item,('source',),('source',))
        return m.resolve_citations(db,item['source'],reason)
    if method=='PATCH' and len(parts)==2 and parts[0]=='citations':
        m.revise_citation(db,int(parts[1]),item,reason)
        return m.citation_record(db,int(parts[1]))
    if method=='POST' and parts==['reviews']:
        fields(item,('kind','slug','changes'),('kind','slug','changes'))
        m.set_completeness(db,item['kind'],item['slug'],item['changes'],reason)
        return dict(m.lookup(db,item['kind'],item['slug']))
    if method=='POST' and parts==['reductions']:
        fields(item,('root',))
        return m.reduce_dependencies(db,reason,item.get('root'))
    if method=='POST' and parts==['reorganize']:
        m.reorganize(db,{**item,'reason':reason})
        return m.verify(db)
    if method=='POST' and parts==['ingest']:
        fields(item,('batch',),('batch',))
        m.ingest(db,{**item['batch'],'note':reason})
        return m.verify(db)
    deletable={'dependencies':'concept_dependency','related':'concept_related','source-concepts':'source_concept','citations':'citation'}
    if method=='DELETE' and len(parts)==2 and parts[0] in deletable:
        fields(item,())
        table=deletable[parts[0]]
        before=row_by_id(db,table,parts[1])
        if table=='source_concept' and m.lookup(db,'concept',before['concept_id'])['status']!='active':
            raise ValueError('Cannot delete a historical occurrence')
        db.execute(f'DELETE FROM {table} WHERE id=?',(before['id'],))
        m.event(db,'delete_'+table,reason,before,{})
        return {'deleted':before['id']}
    raise APIError(404,'Unknown edit endpoint')


class Handler(BaseHTTPRequestHandler):
    server_version='ShapeOfMath/1.0'

    def log_message(self, fmt, *args):
        # Request paths are useful locally; request bodies are never logged.
        super().log_message(fmt,*args)

    def respond(self, status, body, content_type='application/json; charset=utf-8', etag=None):
        if not isinstance(body,bytes):
            body=json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if etag is not None:
            self.send_header('ETag','"'+etag+'"')
        self.end_headers()
        self.wfile.write(body)

    def handle_request(self):
        try:
            host=self.headers.get('Host','')
            port=self.server.server_address[1]
            if host not in (f'127.0.0.1:{port}',f'localhost:{port}'):
                raise APIError(403,'Use the local server address')
            parsed=urlsplit(self.path)
            parts=[unquote(p) for p in parsed.path.split('/') if p]
            if parts[:2]!=['api','v1']:
                assets={'/':(WEB/'index.html','text/html; charset=utf-8'),
                        '/app.js':(WEB/'app.js','text/javascript; charset=utf-8'),
                        '/cone.js':(WEB/'cone.js','text/javascript; charset=utf-8'),
                        '/math-text.js':(WEB/'math-text.js','text/javascript; charset=utf-8'),
                        '/app.css':(WEB/'app.css','text/css; charset=utf-8'),
                        '/api/docs':(DOCS,'text/plain; charset=utf-8')}
                assets['/experiments/2015']=(WEB/'experiments-2015.html','text/html; charset=utf-8')
                assets['/experiments/2015/more']=(WEB/'experiments-2015-more.html','text/html; charset=utf-8')
                for name in ('sample.json','progress.json'):
                    assets['/experiments/curation-2015-round2/'+name]=(
                        EXPERIMENT_REPORTS.parent/'curation-2015-round2'/name,'application/json; charset=utf-8')
                if len(parts)==5 and parts[:3]==['curation','source-tasks','papers']:
                    sample_path=EXPERIMENT_REPORTS.parent/'curation-2015-round2/sample.json'
                    assigned={p['id'] for group in json.loads(sample_path.read_text())['papers'].values() for p in group} if sample_path.is_file() else set()
                    if parts[3] in assigned and parts[4] in ('report.txt','unresolved.json'):
                        kind='application/json; charset=utf-8' if parts[4].endswith('.json') else 'text/plain; charset=utf-8'
                        assets[parsed.path]=(WEB.parent/'curation/source-tasks/papers'/parts[3]/parts[4],kind)
                overlap=EXPERIMENT_REPORTS/'overlap'
                assets['/experiments/2015/overlap']=(overlap/'index.html','text/html; charset=utf-8')
                overlap_types={'.html':'text/html; charset=utf-8', '.js':'text/javascript; charset=utf-8',
                               '.css':'text/css; charset=utf-8', '.json':'application/json; charset=utf-8',
                               '.csv':'text/csv; charset=utf-8', '.svg':'image/svg+xml', '.png':'image/png',
                               '.pdf':'application/pdf', '.md':'text/plain; charset=utf-8'}
                for name in OVERLAP_REPORTS:
                    assets['/experiments/curation-2015/overlap/'+name]=(overlap/name,overlap_types[Path(name).suffix])
                expanded=EXPERIMENT_REPORTS.parent/'curation-2015-round2/overlap'
                assets['/experiments/2015/overlap/expanded']=(expanded/'index.html','text/html; charset=utf-8')
                for name in EXPANDED_OVERLAP_REPORTS:
                    assets['/experiments/curation-2015-round2/overlap/'+name]=(expanded/name,overlap_types[Path(name).suffix])
                for name in PUBLIC_REPORTS:
                    kind=('image/svg+xml' if name.endswith('.svg') else
                          'application/json; charset=utf-8' if name.endswith('.json') else
                          'text/plain; charset=utf-8')
                    assets['/experiments/curation-2015/'+name]=(EXPERIMENT_REPORTS/name,kind)
                if len(parts)==5 and parts[:3]==['experiments','curation-2015','papers']:
                    sample=EXPERIMENT_REPORTS/'sample.json'
                    allowed={r['id'] for group in json.loads(sample.read_text())['papers'].values() for r in group} if sample.is_file() else set()
                    if parts[3] in allowed and parts[4] in ('report.txt','analysis.json','analysis-review.json','cone-review.json'):
                        assets[parsed.path]=(EXPERIMENT_REPORTS/'papers'/parts[3]/parts[4],
                                             'text/plain; charset=utf-8' if parts[4].endswith('.txt') else 'application/json; charset=utf-8')
                if self.command!='GET' or parsed.path not in assets:
                    raise APIError(404,'Not found')
                path,kind=assets[parsed.path]
                if not path.is_file():
                    raise APIError(404,'Not found')
                self.respond(200,path.read_bytes(),kind)
                return
            with closing(m.connect(self.server.db_path)) as db:
                if self.command=='GET':
                    db.execute('BEGIN')
                    out=read_api(db,parts[2:],parse_qs(parsed.query))
                    self.respond(200,out,etag=version(db))
                    return
                if self.command not in ('POST','PATCH','DELETE'):
                    raise APIError(405,'Unsupported method')
                origin=self.headers.get('Origin')
                if origin is not None and origin != 'http://'+host:
                    raise APIError(403,'Cross-origin edits are not allowed')
                if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
                    raise APIError(415,'Edits require Content-Type: application/json')
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=MAX_BODY:
                    raise APIError(413,'Expected a JSON body of at most 2 MiB')
                try:
                    payload=json.loads(self.rfile.read(size),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))
                except (json.JSONDecodeError,UnicodeDecodeError):
                    raise APIError(400,'Malformed JSON')
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    expected=self.headers.get('If-Match')
                    current=version(db)
                    if expected is None:
                        raise APIError(428,'Send the latest ETag in If-Match before editing')
                    if expected!='"'+current+'"':
                        raise APIError(412,'The database changed. Reload and review your edit before saving again.')
                    out=write_api(db,self.command,parts[2:],payload)
                    # Every operation ends in an audit event. Writers hold the write
                    # lock until commit, so the newest event is this edit's version.
                    own_version=version(db)
                self.respond(200,{'version':own_version,'result':out},etag=own_version)
        except APIError as ex:
            self.respond(ex.status,{'error':ex.message})
        except sqlite3.IntegrityError as ex:
            self.respond(409,{'error':str(ex)})
        except (ValueError,KeyError,TypeError,OverflowError) as ex:
            status=404 if isinstance(ex,ValueError) and str(ex).startswith('Unknown ') else 400
            self.respond(status,{'error':str(ex)})
        except Exception:
            import traceback
            traceback.print_exc()
            self.respond(500,{'error':'An internal error occurred; no partial edit was saved.'})

    do_GET=handle_request
    do_POST=handle_request
    do_PATCH=handle_request
    do_DELETE=handle_request
    do_OPTIONS=handle_request


def make_server(db_path=m.DEFAULT_DB, port=8000):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    server.db_path=m.resolve_database(db_path)
    return server


def server_processes(port):
    """Find this checkout's server processes on Linux, including older servers."""
    proc = Path('/proc')
    if not proc.is_dir():
        raise ValueError('Server management requires Linux; use Ctrl+C to stop the server.')
    script = Path(__file__).resolve()
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdecimal() or int(entry.name) == os.getpid():
            continue
        try:
            argv = (entry / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
            cwd = (entry / 'cwd').resolve(strict=True)
            # Match an actual Python script/module invocation, not text in a
            # shell command, editor, or a server belonging to another checkout.
            if not Path(argv[0]).name.startswith('python'):
                continue
            if len(argv) > 2 and argv[1:3] == ['-m', 'mathdb_server']:
                if cwd != script.parent:
                    continue
                options = argv[3:]
            elif len(argv) > 1 and (cwd / argv[1]).resolve() == script:
                options = argv[2:]
            else:
                continue
            parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
            parser.add_argument('--port', type=int, default=8000)
            # Ignore unrelated/partially started commands rather than killing
            # them. Only run/restart invocations can own a server.
            parser.add_argument('--db')
            parser.add_argument('--reload', action='store_true')
            parser.add_argument('command', nargs='?', default='run', choices=('run', 'restart'))
            options, unknown = parser.parse_known_args(options)
            if not unknown and options.port == port:
                found.append((int(entry.name), (entry / 'stat').read_text().rsplit(')', 1)[1].split()[19]))
        except (OSError, ValueError, IndexError, UnicodeError, argparse.ArgumentError):
            continue
    return found


def stop_servers(port):
    processes = server_processes(port)
    for pid, started in processes:
        try:
            # Recheck the process start time to avoid signalling a reused PID.
            if Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19] == started:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except FileNotFoundError:
            pass
    deadline = time.monotonic() + 10
    while processes:
        alive = []
        for pid, started in processes:
            try:
                state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
                if state[0] != 'Z' and state[19] == started:
                    alive.append((pid, started))
            except FileNotFoundError:
                pass
        processes = alive
        if processes and time.monotonic() >= deadline:
            raise ValueError('Server did not stop within 10 seconds; no replacement was started.')
        if processes:
            time.sleep(0.05)


def run_reloading(args):
    """Keep a worker running from fresh source, including after syntax errors."""
    watched = [Path(__file__).resolve(), Path(m.__file__).resolve(), m.ROOT / 'schema.sql']

    def snapshot():
        return tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in watched)

    # Fail immediately on a port conflict instead of leaving an idle watcher.
    with make_server(args.db, args.port):
        pass
    # Workers read source even after a same-size edit within one second. Python's
    # normal .pyc timestamp validation can otherwise reuse the previous code.
    cache = tempfile.TemporaryDirectory(prefix='mathdb-reload-')
    env = {**os.environ, 'PYTHONPYCACHEPREFIX': cache.name, 'PYTHONDONTWRITEBYTECODE': '1'}
    worker = None

    def stop_worker():
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()

    try:
        while True:
            before = snapshot()
            # A database URL carries a password: pass it in the environment, not argv.
            database = m.resolve_database(args.db)
            target = (['--db', str(database)] if not m.is_postgres_url(database) else [])
            worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *target, '--port', str(args.port)],
                                      env={**env, 'MATHDB_DATABASE': str(database)} if not target else env)
            reported = False
            while snapshot() == before:
                code = worker.poll()
                if code is not None and not reported:
                    print(f'Server exited ({code}); waiting for a code change.', flush=True)
                    reported = True
                time.sleep(0.25)
            print('Code changed; restarting server…', flush=True)
            stop_worker()
    except KeyboardInterrupt:
        pass
    finally:
        stop_worker()
        cache.cleanup()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',nargs='?',default='run',choices=('run','restart','stop','status'))
    parser.add_argument('--db',type=m.database_arg,default=m.DEFAULT_DB)
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--reload',action='store_true',help='Restart automatically when Python code or schema.sql changes')
    args=parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    if args.port == 0 and (args.reload or args.command != 'run'):
        parser.error('Server management and --reload require a fixed port')
    # SIGTERM follows the same cleanup path as Ctrl+C, including for the reload
    # supervisor so stopping it cannot leave an orphan worker behind.
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    try:
        if args.command == 'status':
            running=bool(server_processes(args.port))
            print(f'Server {"running" if running else "stopped"} on port {args.port}.')
            return
        if args.command in ('stop','restart'):
            stop_servers(args.port)
            if args.command == 'stop':
                print(f'Server stopped on port {args.port}.')
                return
        if args.reload:
            run_reloading(args)
            return
        run_server(args)
    except (OSError,ValueError) as ex:
        if isinstance(ex,OSError) and ex.errno == errno.EADDRINUSE:
            command=shlex.join(['python','mathdb_server.py','restart','--port',str(args.port),'--db',m.database_label(args.db)]
                               + (['--reload'] if args.reload else []))
            parser.exit(1,f'Port {args.port} is already in use. To replace this project\'s server, run:\n'
                        f'  {command}\n')
        parser.exit(1,f'{ex}\n')
    except KeyboardInterrupt:
        pass


def run_server(args):
    with closing(m.connect(args.db)) as db:
        m.initialize(db)
        m.verify(db)
    with make_server(args.db,args.port) as server:
        print(f'The Shape of Math: http://127.0.0.1:{server.server_address[1]}',flush=True)
        print('JSON API documentation: /api/docs',flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__=='__main__':
    main()
