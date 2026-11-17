"""Apply the editorial corrections without losing the previous curation history."""
import json
import mathdb as m


def main():
    author=json.loads((m.ROOT/'data/author-papers.json').read_text())
    updates={c['slug']:c for c in author['concepts']}
    corrections=['intertwiner','karoubi-envelope','euler-measure','simple-object','minimal-idempotent','fusion-category','jones-wenzl-idempotent']
    demoted=['normalized-third-twisted-moment','normalized-moment-invariance']
    new_note=next(l['note'] for l in author['source_concepts'] if l['concept']=='haagerup-fields')
    with m.connect() as db,db:
        before={'concepts':[],'edges':[]}
        after={'revised':[],'demoted':[],'source_note':new_note}
        for slug in corrections:
            row=dict(m.lookup(db,'concept',slug)); update=updates[slug]
            if row['title']==update['title'] and row['description']==update['description']: continue
            before['concepts'].append(row)
            if row['title']!=update['title']:
                db.execute('INSERT OR IGNORE INTO concept_alias VALUES (?,?)',(row['id'],row['title']))
            db.execute('UPDATE concept SET title=?,description=? WHERE id=?',(update['title'],update['description'],row['id']))
            after['revised'].append(slug)
        for slug in demoted:
            row=dict(m.lookup(db,'concept',slug))
            if row['status']!='active': continue
            before['concepts'].append(row)
            edges=[dict(r) for r in db.execute('SELECT * FROM concept_dependency WHERE prerequisite_id=? OR dependent_id=?',(row['id'],row['id']))]
            before['edges'].extend(edges)
            db.execute('DELETE FROM concept_dependency WHERE prerequisite_id=? OR dependent_id=?',(row['id'],row['id']))
            db.execute("UPDATE concept SET status='superseded' WHERE id=?",(row['id'],))
            db.execute('DELETE FROM concept_embedding WHERE concept_id=?',(row['id'],))
            after['demoted'].append(slug)
        # Replace the obsolete broad parents of these definitions. The one-layer
        # batch supplies their newly reviewed immediate parents.
        layer_path=m.ROOT/'data/one-layer-batch.json'
        layer=json.loads(layer_path.read_text()) if layer_path.exists() else {'dependencies':[]}
        for slug in ['karoubi-envelope','minimal-idempotent','jones-wenzl-idempotent','simple-object']:
            ident=m.lookup(db,'concept',slug)['id']
            parent_slugs={e['prerequisite'] for e in author['dependencies']+layer['dependencies'] if e['dependent']==slug}
            allowed={r['id'] for parent in parent_slugs for r in db.execute('SELECT id FROM concept WHERE slug=?',(parent,))}
            for edge in list(db.execute('SELECT * FROM concept_dependency WHERE dependent_id=?',(ident,))):
                if edge['prerequisite_id'] not in allowed:
                    before['edges'].append(dict(edge))
                    db.execute('DELETE FROM concept_dependency WHERE id=?',(edge['id'],))
        sid=m.lookup(db,'source','morrison-snyder-2012')['id']
        cid=m.lookup(db,'concept','haagerup-fields')['id']
        db.execute('UPDATE source_concept SET note=? WHERE source_id=? AND concept_id=?',(new_note,sid,cid))
        db.execute("UPDATE source SET status='draft' WHERE id=?",(sid,))
        if before['concepts'] or before['edges']:
            m.event(db,'refine_concept_boundaries','User correction: disambiguate terminology and keep paper-local expressions in proof notes.',before,after)
        print(json.dumps(after,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
