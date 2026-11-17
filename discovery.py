"""Collect bibliographic candidates; never ingest mathematical data.

python discovery.py init --scope discovery_examples/journals-2015.json --out RUN
python discovery.py run RUN
python discovery.py status RUN
python discovery.py verify RUN
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import csv
import gzip
import hashlib
import html
import json
from math import ceil
import os
from pathlib import Path
import re
import sqlite3
import sys
import sysconfig
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
RESOURCES = ROOT if (ROOT/'prompts').is_dir() else Path(sysconfig.get_path('data'))/'share/the-shape-of-math'
REGISTRY = {
    'annals': {'name':'Annals of Mathematics', 'issn':'0003-486X', 'style':'annals',
               'index_url':'https://annals.math.princeton.edu'},
    'inventiones': {'name':'Inventiones mathematicae', 'issn':'0020-9910', 'style':'springer',
                   'index_url':'https://link.springer.com/journal/222/volumes-and-issues', 'journal_id':'222'},
    'acta': {'name':'Acta Mathematica', 'issn':'0001-5962', 'style':'springer',
             'index_url':'https://link.springer.com/journal/11511/volumes-and-issues', 'journal_id':'11511'},
    'jams': {'name':'Journal of the American Mathematical Society', 'issn':'0894-0347', 'style':'ams',
             'index_url':'https://pubs.ams.org/view?ProductCode=jams',
             'index_fallback_urls':['https://www.ams.org/journals/jams/']},
}
ARXIV = re.compile(r'(?:arxiv(?:\.org/(?:abs|pdf)/|:)|10\.48550/arxiv\.|oai:arxiv\.org:)'
                   r'(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?', re.I)
SELECT = 'id,doi,title,authorships,cited_by_count,publication_year,publication_date,locations,type,is_retracted'
PROMPTS = ('prompts/discover-journals.md', 'prompts/discover-citations.md', 'docs/DISCOVERY.md')


def now(): return datetime.now(timezone.utc).isoformat()
def digest(path):
    with Path(path).open('rb') as file: return hashlib.file_digest(file, 'sha256').hexdigest()


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n'); temp.replace(path)


def read(path): return json.loads(Path(path).read_text())
def canonical(url):
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                                   urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(parsed.query))), ''))


def same_query(url):
    """Identify compatible field projections and the default first page."""
    parsed=urllib.parse.urlsplit(url)
    params=dict(urllib.parse.parse_qsl(parsed.query));params.pop('select',None)
    if params.get('page')=='1':params.pop('page')
    return (parsed.scheme,parsed.netloc,parsed.path,tuple(sorted(params.items())))


class Blocked(RuntimeError): pass


class Client:
    """Cache successful responses; replay offline; keep credentials out of disk."""
    def __init__(self, run, *, offline=False, budget=500, seeds=()):
        self.run = Path(run); self.cache = self.run/'cache'; self.cache.mkdir(exist_ok=True)
        self.offline = offline; self.budget = budget; self.calls = 0
        self.responses = {}; self.errors = []
        for directory in [*seeds, self.cache]:
            for path in sorted(Path(directory).glob('*.json')):
                envelope = read(path)
                if envelope.get('url') and 'data' in envelope:
                    if 'api_key' in dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(envelope['url']).query)):
                        raise ValueError('Seed response contains a credential in its URL')
                    self.responses[canonical(envelope['url'])] = envelope

    def get(self, url, params=None, *, text=False):
        query = url+('?' + urllib.parse.urlencode(params) if params else '')
        key = canonical(query)
        cached = self.responses.get(key)
        if cached is None:
            wanted=dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(query).query)).get('select','')
            for candidate in self.responses.values():
                selected=dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(candidate['url']).query)).get('select','')
                if same_query(candidate['url'])==same_query(query) and (not selected or (wanted and set(wanted.split(','))<=set(selected.split(',')))):
                    cached=candidate;break
        if cached is not None:
            data = cached['data']
            if isinstance(data, dict) and isinstance(data.get('status'),int) and data['status'] != 200:
                cached = None  # Old failures are not permanent negative evidence.
            else:
                self._persist(key, cached)
                return data.get('html', '') if text else data
        if self.offline: raise Blocked('Not cached in offline mode: '+query)
        for attempt in range(4):
            if self.calls >= self.budget: raise Blocked('Network-request budget reached; resume this run with a larger --request-budget')
            headers = {'User-Agent':'TheShapeOfMath-discovery/1.0', 'Accept':'text/html' if text else 'application/json'}
            if urllib.parse.urlsplit(url).netloc == 'api.openalex.org' and os.environ.get('OPENALEX_API_KEY'):
                headers['Authorization'] = 'Bearer '+os.environ['OPENALEX_API_KEY']
            self.calls += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(query, headers=headers), timeout=45) as response:
                    body = response.read()
                    data = {'status':200, 'html':body.decode('utf-8', errors='replace')} if text else json.loads(body)
                envelope = {'url':key, 'retrieved_at_utc':now(), 'data':data}
                self.responses[key] = envelope; self._persist(key, envelope)
                time.sleep(.15)
                return data['html'] if text else data
            except urllib.error.HTTPError as error:
                if error.code in (401, 403):
                    raise Blocked(f'HTTP {error.code} at {url}; OpenAlex may need OPENALEX_API_KEY, or the publisher may require another accessible route') from None
                if error.code not in (429, 500, 502, 503, 504): raise Blocked(f'HTTP {error.code} at {query}') from None
                retry = error.headers.get('Retry-After', '')
                try: delay = float(retry)
                except ValueError:
                    try: delay = max(0, (parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError): delay = 2**(attempt+1)
                if delay > 30 or attempt == 3:
                    raise Blocked(f'HTTP {error.code} at {url}; retry after {retry or "backoff"}, keeping this run/cache') from None
                time.sleep(max(delay, 2**attempt))
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt == 3: raise Blocked(f'Network unavailable at {url}: {type(error).__name__}') from None
                time.sleep(2**attempt)

    def _persist(self, key, envelope):
        path = self.cache/(hashlib.sha256(key.encode()).hexdigest()+'.json')
        if not path.exists(): save(path, envelope)

    def work_index(self):
        """Use identifier evidence from the saved metadata, not fuzzy matches."""
        works = {}
        for envelope in sorted(self.responses.values(), key=lambda r:(r.get('retrieved_at_utc',''),r['url'])):
            if urllib.parse.urlsplit(envelope['url']).netloc != 'api.openalex.org': continue
            self._persist(canonical(envelope['url']),envelope)
            data = envelope['data']
            for work in data.get('results', []) if isinstance(data, dict) else []:
                works[work['id']] = work
        return list(works.values())


def crossref_pages(client, issn, filters):
    url = f'https://api.crossref.org/journals/{issn}/works'
    params = {'filter':filters, 'rows':1000}
    first = client.get(url, params)['message']; yield from first['items']
    if first['total-results'] <= len(first['items']): return
    # Cursor pages may overlap the initial count probe; callers deduplicate DOI.
    cursor = '*'; seen = set(); count = 0
    while cursor:
        if cursor in seen: raise Blocked('Crossref repeated cursor; collection incomplete')
        seen.add(cursor); page = client.get(url, dict(params, cursor=cursor))['message']
        items = page['items']; yield from items; count += len(items)
        if not items or count >= first['total-results']: break
        cursor = page.get('next-cursor')
        if not cursor: raise Blocked('Crossref ended before the advertised record count')


def oa_pages(client, params):
    url = 'https://api.openalex.org/works'
    args = dict(params, per_page=100, select=SELECT)
    first = client.get(url, dict(args, page=1)); yield from first['results']
    count = first['meta']['count']
    if count <= 100: return
    if count <= 10000:
        for page in range(2, ceil(count/100)+1):
            data = client.get(url, dict(args, page=page))
            if not data['results']: raise Blocked('OpenAlex ended before advertised count')
            yield from data['results']
        return
    if not os.environ.get('OPENALEX_API_KEY') and not client.offline:
        raise Blocked('OpenAlex cohort exceeds 10,000 records; set OPENALEX_API_KEY for cursor paging and resume')
    cursor = '*'; seen = set(); obtained = 0
    while cursor:
        if cursor in seen: raise Blocked('OpenAlex repeated cursor')
        seen.add(cursor); data = client.get(url, dict(args, cursor=cursor))
        rows = data['results']; yield from rows; obtained += len(rows)
        if not rows or obtained >= count: break
        cursor = data['meta'].get('next_cursor')
        if not cursor: raise Blocked('OpenAlex cursor ended before advertised count')


def oa_lookup(client, values, field='doi'):
    if not values: return []
    if len(values)>100: raise ValueError('At most100 OR values per query')
    params = {'filter':field+':'+ '|'.join(values), 'per_page':100, 'select':SELECT}
    data = client.get('https://api.openalex.org/works', params)
    if data['meta']['count']>100:
        if len(values)==1: return list(oa_pages(client, {'filter':params['filter']}))
        middle = len(values)//2
        return oa_lookup(client, values[:middle], field)+oa_lookup(client, values[middle:], field)
    return data['results']


def arxiv_ids(work):
    found = defaultdict(list)
    places = [('work.doi', work.get('doi') or '')]
    for location in work.get('locations', []):
        places.extend((key, location.get(key) or '') for key in ('id','doi','landing_page_url','pdf_url'))
    for field,value in places:
        for match in ARXIV.finditer(value):
            ident = match.group(1)
            if '/' in ident: ident = ident.lower()
            entry = {'field':field, 'value':value}
            if entry not in found[ident]: found[ident].append(entry)
    return dict(found)


def doi_ids(work):
    values = [work.get('doi')]+[r.get('doi') for r in work.get('locations', [])]
    return {str(value).lower().removeprefix('https://doi.org/').removeprefix('http://doi.org/') for value in values if value}


def compact(work):
    return {'openalex_id':work['id'], 'doi':work.get('doi'), 'title':work.get('title'),
            'authors':[a.get('author',{}).get('display_name') for a in work.get('authorships',[])],
            'cited_by_count':work.get('cited_by_count'), 'is_retracted':bool(work.get('is_retracted')),
            'arxiv_matches':arxiv_ids(work)}


def submission_year(ident):
    match = re.fullmatch(r'(\d{2})(\d{2})\.\d{4,5}(?:v\d+)?',ident)
    if not match: match = re.fullmatch(r'[a-z-]+(?:\.[A-Za-z]{2})?/(\d{2})(\d{2})\d{3}(?:v\d+)?',ident)
    if not match or not 1 <= int(match.group(2)) <= 12: return None
    yy = int(match.group(1)); return 1900+yy if yy>=91 else 2000+yy


def inventory_cohort(spec):
    path = Path(spec['inventory']); opener = gzip.open if path.suffix=='.gz' else open
    records = {}
    with opener(path, 'rt') as file:
        for line in file:
            row = json.loads(line); ident = row['id']
            categories = row.get('cats', row.get('categories', []))
            if isinstance(categories, str): categories = categories.split()
            year = submission_year(ident)
            if year is None or not spec['start_year'] <= year <= spec['end_year']: continue
            selected = set(categories)&set(spec['categories'])
            if selected:
                records[ident] = {'id':ident, 'categories':sorted(set(categories)), 'year':year,
                                  'title':row.get('title'), 'openalex_matches':[]}
    return [records[key] for key in sorted(records)]


def normalize(text): return ''.join(c for c in __import__('unicodedata').normalize('NFKD', text or '').casefold() if c.isalnum())


def issue_list(journal, start, end, body):
    """Extract actual issue links; never guess issue counts or volume/year formulas."""
    style = journal.get('style','generic'); issues = {}
    if style=='annals':
        for url,year,volume,issue in re.findall(r'(https?://annals\.math\.princeton\.edu/(?:articles/category/)?(\d{4})/(?:\d+/)?(\d+)-(\d+))',body):
            if start<=int(year)<=end:
                issues[(year,volume,issue)]={'year':int(year),'volume':volume,'issue':issue,
                    'url':url}
    elif style=='ams':
        # Only JAMS issue links/directories; the index also cites Transactions, Bulletin and dates.
        for year,volume,issue in re.findall(r'(?:"IssueDirectory"\s*:\s*"|/jams/)(\d{4})-(\d+)-(\d{2})\b',body,re.I):
            if start<=int(year)<=end:
                issues[(year,volume,str(int(issue)))]={'year':int(year),'volume':volume,'issue':str(int(issue)),
                    'url':f'https://www.ams.org/journals/jams/{year}-{volume}-{issue}/'}
    elif style=='springer':
        # The archive headings identify a volume's year. Article online dates do not.
        pattern = re.compile(r'Volume\s+(\d+)[\s\S]{0,300}?\b(19\d{2}|20\d{2})\b',re.I)
        years = {v:int(y) for v,y in pattern.findall(html.unescape(re.sub('<[^>]*>',' ',body)))}
        for volume,issue in re.findall(r'/volumes-and-issues/(\d+)-(\d+)',body):
            year = years.get(volume)
            if year is not None and start<=year<=end:
                issues[(str(year),volume,issue)]={'year':year,'volume':volume,'issue':issue,
                    'url':f'https://link.springer.com/journal/{journal["journal_id"]}/volumes-and-issues/{volume}-{issue}'}
    return sorted(issues.values(),key=lambda i:(i['year'],int(i['volume']),int(i['issue'])))


def parse_toc(journal, issue, body, pii_dois, known_dois=()):
    """Read one publisher issue page. `known_dois` are Crossref DOIs used only to choose
    between identifier schemes the publisher itself supplies (sequence vs first page)."""
    style = journal.get('style','generic'); urls = []; unknown = []; known = set(known_dois)
    if style=='annals':
        dois = set()
        for chunk in body.split('<h2 class="entry-title">')[1:]:
            entry = re.match(r'\s*<a href="([^"]+)"[^>]*>(.*?)</a>',chunk,re.S)
            if not entry: continue
            url,title = entry.groups()
            match = re.search(r'/(\d{4})/(\d+)-(\d+)/p(\d+)$',url)
            pages = re.search(r'Pages\s+(\d+)',chunk.split('<div id="post-')[0])
            if match and int(match.group(1))>=2003:
                y,v,i,n=match.groups(); sequence=f'10.4007/annals.{y}.{v}.{i}.{int(n)}'
                # Before 2011 Crossref registered Annals DOIs by first page, not by sequence.
                by_page = f'10.4007/annals.{y}.{v}.{int(pages.group(1))}' if pages else None
                dois.add(by_page if by_page and sequence not in known and by_page in known else sequence); urls.append(url)
            else: unknown.append({'url':url,'title':html.unescape(re.sub('<[^>]+>','',title))})
    elif style=='ams':
        pattern = r"href=['\"]/[Jj][Aa][Mm][Ss]/"+str(issue['year'])+'-'+re.escape(issue['volume'])+'-'+str(issue['issue']).zfill(2)+r"/([^/'\"]+)/"
        piis = set(re.findall(pattern,body)); dois = set()
        for p in piis:
            p = p.lower(); number = re.fullmatch(r's0894-0347-\d{4}-0*(\d+)-.',p)
            modern = f'10.1090/jams/{number.group(1)}' if number else None
            # Recent AMS DOIs use the PII serial; accept that form only when Crossref has it.
            dois.add(pii_dois.get(p) or (modern if modern in known and '10.1090/'+p not in known else '10.1090/'+p))
    else:
        if style=='springer': dois = set(re.findall(r'/article/(10\.[0-9]+/[^"?#\s<>]+)',body))
        else: dois = set(re.findall(r'https?://(?:dx\.)?doi\.org/(10\.[0-9]+/[^"?#\s<>]+)',body))
    count = re.search(r'(\d+) articles in this issue',body)
    return {'dois':sorted(d.lower() for d in dois),'article_urls':urls,'unidentified_entries':unknown,
            'publisher_count':int(count.group(1)) if count else len(dois)+len(unknown)}


NONARTICLE_TITLES = {'front matter','back matter','index','masthead','table of contents'}


def nonarticle(work):
    """Crossref issue furniture, identified only by an exact title and no authors."""
    return not work.get('author') and ' '.join(work.get('title',[])).strip().casefold() in NONARTICLE_TITLES


def reconcile_issues(audits, journal, records):
    """Publisher contents decide the issue. A Crossref record whose volume/issue disagrees
    is a metadata conflict only when another fetched issue page of this journal lists it."""
    listed = {doi:a for a in audits for doi in a.get('publisher_dois',[])}
    for audit in audits:
        if audit.get('status')=='blocked': continue
        moved = [d for d in audit['crossref_not_publisher'] if d in listed and listed[d] is not audit]
        audit['crossref_issue_metadata_conflicts'] = [{'doi':d,'crossref_volume':records[d].get('volume'),
            'crossref_issue':records[d].get('issue'),'listed_on':listed[d]['url']} for d in moved]
        audit['crossref_not_publisher'] = [d for d in audit['crossref_not_publisher'] if d not in moved]
        audit['status'] = 'verified' if (journal.get('style')!='generic' and audit['publisher_dois']
            and not audit['unidentified_entries'] and not audit['crossref_not_publisher']
            and not audit['publisher_not_crossref'] and audit['publisher_count']==len(audit['publisher_dois'])) else 'needs_review'


def issue_year(work):
    """Year of the issue as Crossref records it; never the online-first date."""
    for part in (work.get('journal-issue',{}).get('published-print'),work.get('journal-issue',{}).get('published-online'),work.get('published-print')):
        if part and part.get('date-parts') and part['date-parts'][0] and part['date-parts'][0][0]: return int(part['date-parts'][0][0])
    return None


def crossref_issues(name, years, records):
    """Explicitly requested Crossref-only contents for years without a reachable publisher index.
    These issues are not publisher-verified; omissions in Crossref cannot be detected."""
    groups=defaultdict(set);undated=[]
    for doi,w in records.items():
        if not w.get('volume') or not w.get('issue') or nonarticle(w): continue
        year=issue_year(w)
        if year is None: undated.append(doi)
        elif year in years: groups[(year,str(w['volume']),str(w['issue']))].add(doi)
    audits=[]
    for (year,volume,issue),dois in sorted(groups.items(),key=lambda g:(g[0][0],int(g[0][1]) if g[0][1].isdigit() else 0,g[0][2])):
        audits.append({'year':year,'volume':volume,'issue':issue,'url':None,'journal':name,'status':'crossref_only',
            'crossref_dois':sorted(dois),'publisher_dois':[],'publisher_count':None,'unidentified_entries':[],
            'crossref_not_publisher':[],'publisher_not_crossref':[],
            'note':'Enumerated from Crossref volume/issue metadata at the user\'s request; publisher index not inspected.'})
    for year in years:
        if not any(a['year']==year for a in audits):
            audits.append({'year':year,'volume':None,'issue':None,'url':None,'journal':name,'status':'crossref_only_empty',
                'crossref_dois':[],'note':'No Crossref records with issue coordinates for this year.'})
    return audits


def validate_scope(value, base):
    scope = json.loads(json.dumps(value))
    def keys(part,allowed):
        unknown=set(part)-set(allowed)
        if unknown:raise ValueError('Unknown scope keys: '+', '.join(sorted(unknown)))
    keys(scope,('version','journals','citations','title_search','catalogue'))
    if scope.get('version') != 1: raise ValueError('scope.version must be1')
    if not scope.get('journals') and not scope.get('citations'): raise ValueError('Supply journals, citations, or both')
    def years(part):
        if not isinstance(part.get('start_year'),int) or not isinstance(part.get('end_year'),int) or not 1880<=part['start_year']<=part['end_year']<=datetime.now().year:
            raise ValueError('Supply inclusive start_year/end_year within1880..current year')
    if scope.get('journals'):
        part = scope['journals']; years(part); journals = []
        keys(part,('start_year','end_year','journals','include_errata','date_padding_years'))
        if not isinstance(part.get('date_padding_years',2),int) or part.get('date_padding_years',2)<0:raise ValueError('date_padding_years must be a nonnegative integer')
        if not part.get('journals'): raise ValueError('journals.journals cannot be empty')
        for entry in part['journals']:
            journal = dict(REGISTRY[entry]) if isinstance(entry,str) and entry in REGISTRY else dict(entry) if isinstance(entry,dict) else None
            if not journal or not journal.get('name') or not re.fullmatch(r'\d{4}-\d{3}[\dXx]',journal.get('issn','')): raise ValueError('Unknown journal; supply name/ISSN and publisher index/style or explicit issues')
            journal.setdefault('style','generic')
            if journal['style'] not in ('annals','springer','ams','generic'): raise ValueError('Unknown publisher style')
            if 'issues' not in journal and not journal.get('index_url'): raise ValueError('Journal needs index_url or explicit issues')
            fallback = journal.get('crossref_issue_years',[])
            if not isinstance(fallback,list) or not all(isinstance(y,int) and not isinstance(y,bool) for y in fallback): raise ValueError('crossref_issue_years must be a list of years')
            journal['crossref_issue_years']=sorted(set(fallback))
            for issue in journal.get('issues',[]):
                if not all(k in issue for k in ('year','volume','issue','url')): raise ValueError('Issue requires year/volume/issue/url')
                issue['volume']=str(issue['volume']); issue['issue']=str(issue['issue'])
            journals.append(journal)
        part['journals']=journals;part.setdefault('date_padding_years',2);part.setdefault('include_errata',True)
        if not isinstance(part['include_errata'],bool):raise ValueError('include_errata must be boolean')
    if scope.get('citations'):
        part = scope['citations'];cohort=part['cohort'];kind=cohort.get('kind')
        keys(part,('cohort','group_by','top_percent','top_count','ties','exclude_retracted'))
        keys(cohort,('kind','inventory','start_year','end_year','categories') if kind=='arxiv' else ('kind','filter'))
        if kind=='arxiv':
            years(cohort)
            if not isinstance(cohort.get('categories'),list) or not cohort['categories'] or not all(isinstance(c,str) and c for c in cohort['categories']): raise ValueError('arXiv cohort requires explicit category strings')
            cohort['categories']=list(dict.fromkeys(cohort['categories']))
            path=Path(cohort['inventory']);cohort['inventory']=str((base/path).resolve()) if not path.is_absolute() else str(path.resolve())
            if not Path(cohort['inventory']).is_file(): raise ValueError('arXiv inventory not found')
            part.setdefault('group_by','category')
        elif kind=='openalex':
            if not cohort.get('filter'): raise ValueError('OpenAlex cohort requires an explicit API filter')
            part.setdefault('group_by','pool')
            if part['group_by']!='pool': raise ValueError('OpenAlex-filter cohorts use group_by=pool; separate scopes for separate filters')
        else: raise ValueError('Citation cohort kind must be arxiv or openalex')
        if part.get('group_by') not in ('category','pool'): raise ValueError('group_by must be category or pool')
        if 'top_count' in part:
            if 'top_percent' in part or isinstance(part['top_count'],bool) or not isinstance(part['top_count'],int) or part['top_count']<1:raise ValueError('Supply positive top_count or top_percent, not both')
        else:
            percent=part.setdefault('top_percent',10)
            if isinstance(percent,bool) or not isinstance(percent,(int,float)) or not 0<percent<=100: raise ValueError('top_percent must be >0 and <=100')
        part.setdefault('ties','include');part.setdefault('exclude_retracted',True)
        if not isinstance(part['exclude_retracted'],bool):raise ValueError('exclude_retracted must be boolean')
        if part['ties'] not in ('include','exact'): raise ValueError('ties must be include or exact')
    scope.setdefault('title_search',True)
    if not isinstance(scope['title_search'],bool):raise ValueError('title_search must be boolean')
    if scope.get('catalogue'):
        path=Path(scope['catalogue']);scope['catalogue']=str((base/path).resolve()) if not path.is_absolute() else str(path.resolve())
        if not Path(scope['catalogue']).is_file(): raise ValueError('catalogue not found')
    return scope


def initialize(scope_path, output):
    output=Path(output).resolve()
    if output.exists(): raise ValueError('Run directory exists; use run to resume or a new directory for a new scope')
    source=Path(scope_path).resolve();scope=validate_scope(read(source),source.parent)
    output.mkdir(parents=True);(output/'cache').mkdir()
    inputs={}
    if scope.get('citations',{}).get('cohort',{}).get('kind')=='arxiv':
        path=scope['citations']['cohort']['inventory'];inputs[path]=digest(path)
    save(output/'scope.json',scope)
    for name in PROMPTS:
        target=output/'instructions'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((RESOURCES/name).read_bytes())
    save(output/'manifest.json',{'created_at_utc':now(),'scope_sha256':digest(output/'scope.json'),
        'input_sha256':inputs,'code_sha256':{'discovery.py':digest(Path(__file__))},
        'instruction_sha256':{name:digest(output/'instructions'/name) for name in PROMPTS},
        'note':'Discovery only. No mathematical curation and no shared database writes.'})
    save(output/'status.json',{'state':'initialized','complete':False,'stages':{}})


def validate_run(run):
    run=Path(run);manifest=read(run/'manifest.json')
    if digest(run/'scope.json')!=manifest['scope_sha256']: raise ValueError('Frozen scope changed; initialize a new run')
    for path,sha in manifest['input_sha256'].items():
        if digest(path)!=sha: raise ValueError('Input changed: '+path)
    if digest(Path(__file__))!=manifest['code_sha256']['discovery.py']: raise ValueError('Discovery code changed since initialization; use pinned code or a new run')
    return read(run/'scope.json')


def rank(rows, spec):
    categories=spec['cohort'].get('categories',[]) if spec['group_by']=='category' else ['combined']
    groups={}
    for category in categories:
        pool=[p for p in rows if category=='combined' or category in p['categories']]
        works={};unresolved=[];excluded=[]
        for paper in pool:
            matches={w['openalex_id']:w for w in paper['openalex_matches']}
            if len(matches)!=1:
                unresolved.append({'id':paper['id'],'reason':'unmatched' if not matches else 'multiple_openalex_works'});continue
            w=next(iter(matches.values()))
            if w.get('is_retracted') and spec['exclude_retracted']:
                excluded.append({'id':paper['id'],'reason':'retracted'});continue
            count=w.get('cited_by_count')
            if not isinstance(count,int) or isinstance(count,bool) or count<0:
                unresolved.append({'id':paper['id'],'reason':'unknown_citation_count'});continue
            record=works.setdefault(w['openalex_id'],dict(w,cohort_ids=[],categories=set()))
            record['cohort_ids'].append(paper['id']);record['categories'].update(paper['categories'])
        ordered=sorted(works.values(),key=lambda w:(-w['cited_by_count'],w['openalex_id']))
        target=spec['top_count'] if 'top_count' in spec else ceil(len(pool)*spec['top_percent']/100)
        cutoff=ordered[min(target,len(ordered))-1]['cited_by_count'] if ordered and target else None
        chosen=([w for w in ordered if w['cited_by_count']>=cutoff] if spec['ties']=='include' else ordered[:target]) if cutoff is not None else []
        for w in ordered:w['categories']=sorted(w['categories'])
        groups[category]={'cohort_size':len(pool),'distinct_matched_eligible_works':len(works),'target':target,
            'cutoff_citations':cutoff,'selected_count':len(chosen),'selected':chosen,'ranking':ordered,
            'unresolved':unresolved,'excluded':excluded,'complete':not unresolved,
            'denominator':'Full cohort IDs before canonical-work deduplication and retraction exclusion; unknown counts are not zero.'}
    return groups


class Discovery:
    def __init__(self,run,client):
        self.run=Path(run);self.client=client;self.scope=validate_run(run)
        self.status={'state':'running','complete':False,'started_at_utc':now(),'stages':{}}
        self.journals=[];self.cohort=[];self.rankings={};self.issues=[];self.pending=[]

    def progress(self):
        self.status['updated_at_utc']=now();self.status['network_requests_this_invocation']=self.client.calls
        save(self.run/'status.json',self.status)

    def journals_stage(self):
        spec=self.scope['journals']
        for journal in spec['journals']:
            name=journal['name'];stage='journal:'+name
            try:
                issues=[i for i in journal.get('issues',[]) if spec['start_year']<=i['year']<=spec['end_year']]
                if 'issues' not in journal:
                    failures=[]
                    for url in [journal['index_url'],*journal.get('index_fallback_urls',[])]:
                        try:
                            body=self.client.get(url,text=True)
                            issues=issue_list(journal,spec['start_year'],spec['end_year'],body)
                            if issues:break
                            failures.append('No requested issue links parsed at '+url)
                        except Blocked as error:failures.append(str(error))
                    if not issues and not journal['crossref_issue_years']:raise Blocked('; '.join(failures))
                years=set(i['year'] for i in issues)
                missing=sorted(set(range(spec['start_year'],spec['end_year']+1))-years)
                records={};piis={}
                pad=spec['date_padding_years']
                filters=f'from-pub-date:{spec["start_year"]-pad}-01-01,until-pub-date:{spec["end_year"]+pad}-12-31,type:journal-article'
                for work in crossref_pages(self.client,journal['issn'],filters):
                    records[work['DOI'].lower()]=work
                    for pii in work.get('alternative-id',[]):piis[pii.lower()]=work['DOI'].lower()
                for issue in issues:
                    audit=dict(issue,journal=name,status='pending')
                    try:
                        try:body=self.client.get(issue['url'],text=True)
                        except Blocked:
                            if journal.get('style')!='ams':raise
                            fallback='https://pubs.ams.org/view?'+urllib.parse.urlencode({'ProductCode':'jams','directory':f'{issue["year"]}-{issue["volume"]}-{str(issue["issue"]).zfill(2)}'})
                            body=self.client.get(fallback,text=True);audit['fetched_url']=fallback
                        parsed=parse_toc(journal,issue,body,piis,records)
                        expected={doi for doi,w in records.items() if str(w.get('volume'))==issue['volume'] and str(w.get('issue'))==issue['issue']}
                        # Crossref registers issue furniture as journal-article; keep it visible, not expected.
                        furniture=sorted(doi for doi in expected if doi not in parsed['dois'] and nonarticle(records[doi]))
                        expected-=set(furniture)
                        # Annals DOI supplies absent issue coordinates; only checked DOI records count.
                        for doi in parsed['dois']:
                            if doi not in records:
                                try:records[doi]=self.client.get('https://api.crossref.org/works/'+urllib.parse.quote(doi,safe=''))['message']
                                except Blocked as error:self.pending.append({'kind':'journal_doi_metadata','doi':doi,'reason':str(error)})
                        expected.update(doi for doi in parsed['dois'] if doi in records)
                        audit.update(publisher_dois=parsed['dois'],publisher_count=parsed['publisher_count'],
                            unidentified_entries=parsed['unidentified_entries'],crossref_not_publisher=sorted(expected-set(parsed['dois'])),
                            publisher_not_crossref=sorted(set(parsed['dois'])-set(records)),crossref_nonarticles_excluded=furniture)
                        for doi in parsed['dois']:
                            w=records.get(doi)
                            if not w:continue
                            title=' '.join(w.get('title',[]));erratum=bool(re.match(r'(?:erratum|corrigendum|correction)\b',title,re.I))
                            self.journals.append({'key':'doi:'+doi,'doi':doi,'title':title,
                                'authors':[' '.join(filter(None,(a.get('given'),a.get('family')))) for a in w.get('author',[])],
                                'journal':name,'year':issue['year'],'volume':issue['volume'],'issue':issue['issue'],
                                'issue_url':issue['url'],'included':spec['include_errata'] or not erratum,'erratum':erratum,
                                'openalex_matches':[],'title_search_candidates':[]})
                    except Blocked as error:audit.update(status='blocked',reason=str(error))
                    self.issues.append(audit)
                reconcile_issues([a for a in self.issues if a['journal']==name],journal,records)
                fallback_years=sorted(set(journal['crossref_issue_years'])&set(missing))
                for audit in crossref_issues(name,fallback_years,records):
                    self.issues.append(audit)
                    for doi in audit['crossref_dois']:
                        w=records[doi];title=' '.join(w.get('title',[]));erratum=bool(re.match(r'(?:erratum|corrigendum|correction)\b',title,re.I))
                        self.journals.append({'key':'doi:'+doi,'doi':doi,'title':title,
                            'authors':[' '.join(filter(None,(a.get('given'),a.get('family')))) for a in w.get('author',[])],
                            'journal':name,'year':audit['year'],'volume':audit['volume'],'issue':audit['issue'],
                            'issue_url':None,'issue_source':'crossref_only','included':spec['include_errata'] or not erratum,'erratum':erratum,
                            'openalex_matches':[],'title_search_candidates':[]})
                self.status['stages'][stage]={'state':('collected' if not missing else 'collected_with_crossref_only_years' if set(missing)<=set(fallback_years) and all(a['status']=='crossref_only' for a in self.issues if a['journal']==name and a['year'] in missing) else 'incomplete')
                        if all(i['status']=='verified' for i in self.issues if i['journal']==name and i['year'] not in fallback_years) else 'incomplete',
                    'issues_found':len(issues),'years_without_verified_issue_listing':missing,
                    'crossref_only_years':fallback_years,'crossref_only_issues':sum(1 for a in self.issues if a['journal']==name and a['status']=='crossref_only'),
                    'issue_enumeration':'explicit_user_list' if 'issues' in journal else 'publisher_index',
                    'enumeration_limit':'Explicit lists verify only supplied issues; an omitted issue cannot be detected.' if 'issues' in journal else None}
            except Blocked as error:self.status['stages'][stage]={'state':'blocked','reason':str(error)}
            self.progress()
        self.match_journals()

    def match_journals(self):
        lookup=defaultdict(dict)
        def index(works):
            for work in works:
                for doi in doi_ids(work):lookup[doi][work['id']]=work
        index(self.client.work_index())
        needed=sorted({r['doi'] for r in self.journals if r['doi'] not in lookup})
        for offset in range(0,len(needed),50):
            try:index(oa_lookup(self.client,['https://doi.org/'+d for d in needed[offset:offset+50]]))
            except Blocked as error:self.pending.append({'kind':'journal_openalex_lookup','reason':str(error)});break
        for row in self.journals:
            row['openalex_matches']=[compact(w) for w in lookup[row['doi']].values()]
            if not self.scope['title_search'] or any(w['arxiv_matches'] for w in row['openalex_matches']) or row['erratum']:continue
            try:
                data=self.client.get('https://api.openalex.org/works',{'search':row['title'],'per_page':5,'select':SELECT})
                row['title_search_candidates']=[dict(compact(w),exact_normalized_title=normalize(w.get('title'))==normalize(row['title'])) for w in data['results'] if arxiv_ids(w)]
            except Blocked as error:self.pending.append({'kind':'title_search','doi':row['doi'],'reason':str(error)})
        save(self.run/'journals.json',self.journals);save(self.run/'issues.json',self.issues)

    def citations_stage(self):
        spec=self.scope['citations'];part=spec['cohort']
        try:
            if part['kind']=='openalex':
                works={w['id']:w for w in oa_pages(self.client,{'filter':part['filter']})}
                self.cohort=[{'id':ident,'categories':[],'openalex_matches':[compact(w)]} for ident,w in sorted(works.items())]
            else:
                self.cohort=inventory_cohort(part);by_id={p['id']:p for p in self.cohort}
                if not self.cohort:raise Blocked('No inventory IDs match the requested years/categories; check inventory coverage before claiming an empty population')
                matches=defaultdict(dict)
                def index(works):
                    for work in works:
                        for ident in set(arxiv_ids(work))&set(by_id):matches[ident][work['id']]=work
                index(self.client.work_index())
                needed=[p['id'] for p in self.cohort if p['id'] not in matches]
                for offset in range(0,len(needed),75):
                    index(oa_lookup(self.client,['https://doi.org/10.48550/arxiv.'+i for i in needed[offset:offset+75]]))
                    print('arXiv identifier lookup',min(offset+75,len(needed)),'/',len(needed),flush=True)
                missing=[i for i in needed if i not in matches]
                for offset in range(0,len(missing),40):
                    index(oa_lookup(self.client,[s+'://arxiv.org/abs/'+i for i in missing[offset:offset+40] for s in ('http','https')],'locations.landing_page_url'))
                for ident,p in by_id.items():p['openalex_matches']=[compact(w) for w in matches[ident].values()]
            self.rankings=rank(self.cohort,spec)
            self.status['stages']['citations']={'state':'collected','cohort_records':len(self.cohort),
                'ranking_complete':all(g['complete'] for g in self.rankings.values())}
        except Blocked as error:
            # No partial list is ranked as the full cohort. Cached pages permit resume.
            self.status['stages']['citations']={'state':'blocked','reason':str(error)}
        save(self.run/'cohort.json',self.cohort);save(self.run/'rankings.json',self.rankings);self.progress()

    def export(self):
        candidates={};unresolved=list(self.pending)
        def add(key,row,selection):
            item=candidates.setdefault(key,dict(row,selections=[]))
            if row.get('cited_by_count') is not None:item['cited_by_count']=row['cited_by_count']
            item['arxiv_ids']=sorted(set(item['arxiv_ids'])|set(row['arxiv_ids']))
            item['source_dois']=sorted(set(item.get('source_dois',[]))|{v for v in (row.get('doi'),item.get('doi')) if v})
            item['identity_conflict']=item.get('identity_conflict',False) or row.get('identity_conflict',False)
            item['match_status']='multiple_openalex_works' if item['identity_conflict'] else 'identifier_linked' if len(item['arxiv_ids'])==1 else 'multiple_arxiv_ids' if item['arxiv_ids'] else 'arxiv_not_found'
            if selection not in item['selections']:item['selections'].append(selection)
            return item
        for row in self.journals:
            if not row['included']:continue
            ids=sorted(set().union(*(set(w['arxiv_matches']) for w in row['openalex_matches'])))
            ws={w['openalex_id'] for w in row['openalex_matches']}
            key=next(iter(ws)) if len(ws)==1 else row['key']
            item=add(key,{'title':row['title'],'doi':row['doi'],'arxiv_ids':ids,
                'openalex_id':next(iter(ws)) if len(ws)==1 else None,'identity_conflict':len(ws)>1,
                'match_status':'identifier_linked' if len(ids)==1 else 'multiple_arxiv_ids' if ids else 'arxiv_not_found'},
                {'kind':'journal_issue','journal':row['journal'],'year':row['year'],'issue_url':row['issue_url'],
                 'issue_source':row.get('issue_source','publisher_page')})
            if len(ids)!=1 or len(ws)>1:unresolved.append({'key':row['key'],'kind':'journal_arxiv_match','reason':item['match_status'],'title_search_candidates':row['title_search_candidates']})
        for group,r in self.rankings.items():
            for w in r['selected']:
                ids=sorted(w['arxiv_matches'])
                add(w['openalex_id'],{'title':w['title'],'doi':w.get('doi'),'openalex_id':w['openalex_id'],
                    'arxiv_ids':ids,'cited_by_count':w['cited_by_count'],
                    'match_status':'identifier_linked' if len(ids)==1 else 'multiple_arxiv_ids' if ids else 'arxiv_not_found'},
                    {'kind':'citation_ranking','group':group,'percent':self.scope['citations'].get('top_percent'),
                     'count':self.scope['citations'].get('top_count'),'provisional':not r['complete']})
            unresolved.extend(dict(u,kind='citation_metadata',group=group) for u in r['unresolved'])
        known=set()
        if self.scope.get('catalogue'):
            with closing(sqlite3.connect(Path(self.scope['catalogue']).as_uri()+'?mode=ro',uri=True)) as db:
                known={r[0] for r in db.execute("SELECT value FROM source_identifier WHERE scheme='arxiv'")}
        rows=[]
        for key,row in sorted(candidates.items()):
            rows.append(dict(row,key=key,already_catalogued=bool(set(row['arxiv_ids'])&known),
                             ready_for_artifact_check=row['match_status']=='identifier_linked'))
        save(self.run/'candidates.json',rows);save(self.run/'unresolved.json',unresolved)
        with (self.run/'candidates.csv').open('w',newline='') as file:
            writer=csv.writer(file);writer.writerow(['key','title','doi','openalex_id','arxiv_ids','citations','match_status','already_catalogued','selections'])
            for row in rows:writer.writerow([row['key'],row['title'],row.get('doi'),row.get('openalex_id'),';'.join(row['arxiv_ids']),row.get('cited_by_count'),row['match_status'],row['already_catalogued'],json.dumps(row['selections'],ensure_ascii=False)])
        self.status['complete']=bool(self.status['stages']) and all(r['state']=='collected' for r in self.status['stages'].values())
        self.status.update(state='finished' if self.status['complete'] else 'needs_attention',candidate_count=len(rows),
            unresolved_count=len(unresolved),complete_meaning='Collection stages completed. Does not certify all matches, citation rankings, or mathematical inventories.')
        self.progress()
        manifest=read(self.run/'manifest.json')
        manifest['output_sha256']={p.name:digest(p) for p in self.run.glob('*.json') if p.name not in ('manifest.json','scope.json')}
        manifest['output_sha256']['candidates.csv']=digest(self.run/'candidates.csv')
        manifest['cache_sha256']={p.name:digest(p) for p in self.client.cache.glob('*.json')}
        save(self.run/'manifest.json',manifest)

    def run_all(self):
        self.progress()
        if self.scope.get('journals'):self.journals_stage()
        if self.scope.get('citations'):self.citations_stage()
        self.export();return self.status


def verify(run):
    run=Path(run);scope=validate_run(run);manifest=read(run/'manifest.json')
    for name,sha in manifest.get('output_sha256',{}).items():
        if digest(run/name)!=sha:raise ValueError('Output changed: '+name)
    for name,sha in manifest.get('cache_sha256',{}).items():
        if digest(run/'cache'/name)!=sha:raise ValueError('Cached response changed: '+name)
    for name,sha in manifest['instruction_sha256'].items():
        if digest(run/'instructions'/name)!=sha:raise ValueError('Pinned instructions changed: '+name)
    if scope.get('citations') and read(run/'status.json')['stages'].get('citations',{}).get('state')=='collected':
        if rank(read(run/'cohort.json'),scope['citations'])!=read(run/'rankings.json'):raise ValueError('Rankings do not reproduce')
    return {'verified':True,'scope_sha256':manifest['scope_sha256'],'status':read(run/'status.json')}


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    init=commands.add_parser('init');init.add_argument('--scope',type=Path,required=True);init.add_argument('--out',type=Path,required=True)
    run=commands.add_parser('run');run.add_argument('directory',type=Path);run.add_argument('--offline',action='store_true')
    run.add_argument('--request-budget',type=int,default=500);run.add_argument('--seed-cache',type=Path,action='append',default=[])
    for name in ('status','verify'):
        commands.add_parser(name).add_argument('directory',type=Path)
    commands.add_parser('journals')
    args=parser.parse_args()
    try:
        if args.command=='init':initialize(args.scope,args.out);result={'initialized':str(args.out)}
        elif args.command=='run':
            if args.request_budget<0:raise ValueError('request-budget must be nonnegative')
            result=Discovery(args.directory,Client(args.directory,offline=args.offline,budget=args.request_budget,seeds=args.seed_cache)).run_all()
        elif args.command=='status':result=read(args.directory/'status.json')
        elif args.command=='verify':result=verify(args.directory)
        else:result=REGISTRY
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if args.command=='run' and not result['complete']:return 2
    except (ValueError,KeyError,OSError,Blocked) as error:
        print(f'Discovery error: {error}',file=sys.stderr);return 1
    return 0


if __name__=='__main__':sys.exit(main())
