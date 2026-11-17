"""Correct source attribution without confusing original contributions and exposition."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path

import mathdb as m

POLICY=m.ROOT/'data/source-attribution-review.json'


def project(payload, policy=None):
    """Apply reviewed origin claims to a reproducible ingestion batch."""
    policy=policy or json.loads(POLICY.read_text())
    existing={s['slug'] for s in payload['sources']}
    payload['sources'].extend(copy.deepcopy(s) for s in policy['sources'] if s['slug'] not in existing)
    sources={s['slug']:s for s in payload['sources']}
    for item in policy['source_artifacts']:
        artifacts=sources[item['source']].setdefault('artifacts',[])
        artifact=item['artifact']
        if not any((a['url'],a.get('version',''))==(artifact['url'],artifact.get('version','')) for a in artifacts):
            artifacts.append(copy.deepcopy(artifact))
    for link in payload['source_concepts']:
        link['role']=m.canonical_role(link['role'])
        if link['role']=='introduces' and not link.get('introduction_evidence','').strip():
            raise ValueError('Unreviewed introduction in builder: '+link['source']+' / '+link['concept'])
    for claim in policy['introductions']:
        matches=[r for r in payload['source_concepts'] if r['source']==claim['source'] and r['concept']==claim['concept'] and r['locator']==claim['locator']]
        if matches:
            previous_note=matches[0].get('note','')
            matches[0].update(copy.deepcopy(claim))
            extra=claim.get('note','')
            matches[0]['note']=previous_note+('\n' if previous_note and extra and extra!=previous_note else '')+(extra if extra!=previous_note else '')
        else:payload['source_concepts'].append(copy.deepcopy(claim))
    return payload


def apply(db,policy=None):
    policy=policy or json.loads(POLICY.read_text())
    fingerprint=hashlib.sha256(json.dumps(policy,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    for r in db.execute("SELECT after_json FROM curation_event WHERE operation='source_attribution_review'"):
        if json.loads(r[0]).get('policy_sha256')==fingerprint:return False
    existing={r['slug'] for r in db.execute('SELECT slug FROM source')}
    new=[r for r in policy['sources'] if r['slug'] not in existing]
    if new:m.ingest(db,{'sources':new,'note':'Catalogue the earlier Kuperberg source for origin attribution.'})
    with db:
        before=[dict(r) for r in db.execute('SELECT * FROM source_concept')]
        # Any remaining positive claims must already carry evidence (schema invariant).
        for claim in policy['introductions']:
            sid=m.lookup(db,'source',claim['source'])['id'];cid=m.lookup(db,'concept',claim['concept'])['id']
            old=db.execute("SELECT * FROM source_concept WHERE source_id=? AND concept_id=? AND locator=? AND role='explains'",(sid,cid,claim['locator'])).fetchone()
            if old:
                db.execute("UPDATE source_concept SET role='introduces',introduction_evidence=?,note=? WHERE id=?",
                           (claim['introduction_evidence'],old['note']+('\n' if old['note'] and claim.get('note') else '')+claim.get('note',''),old['id']))
            else:m.add_link(db,claim)
        for source in policy['source_artifacts']:
            sid=m.lookup(db,'source',source['source'])['id']
            a=source['artifact']
            db.execute('''INSERT OR IGNORE INTO source_artifact(source_id,url,version,accessed_at,sha256,local_path,note)
                          VALUES (?,?,?,?,?,?,?)''',(sid,a['url'],a['version'],a['accessed_at'],a['sha256'],a['local_path'],a['note']))
        after=[dict(r) for r in db.execute('SELECT * FROM source_concept')]
        m.event(db,'source_attribution_links','Require original-contribution evidence; distinguish explanations, proof inputs and historical origins.',
                {'occurrences':before},{'policy_sha256':fingerprint,'occurrences':after,'judgments':policy['judgments']})
    for judgment in policy['judgments']:
        m.set_completeness(db,'source',judgment['source'],judgment['changes'],judgment['reason'])
    m.resolve_citations(db,'morrison-g2-2011','Match the bibliography entry for Kuperberg 1994 to the newly catalogued original source.')
    with db:
        m.event(db,'source_attribution_review','Complete the explicit source-attribution audit and its independent review judgments.',{},
                {'policy_sha256':fingerprint,'judgments':policy['judgments'],'pending':policy['pending']})
    return True


if __name__=='__main__':
    with closing(m.connect()) as db:
        m.initialize(db);print(json.dumps({'changed':apply(db),**m.verify(db)},indent=2))
