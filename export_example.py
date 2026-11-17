"""Export the active concept model as JSON, TSV and readable catalogues."""
import csv
from contextlib import closing
import json
import mathdb as m


def citation_lines(db, source_id):
    lines=[]
    for row in db.execute('SELECT id FROM citation WHERE source_id=? ORDER BY id',(source_id,)):
        citation=m.citation_record(db,row['id'])
        judgment={True:'yes',False:'no',None:'unknown'}[citation['pedagogically_necessary']]
        lines += [f"  [{citation['label'] or citation['id']}] {citation['text']}",
                  f"    Pedagogically necessary: {judgment}"]
        for identifier in citation['identifiers']:
            lines.append(f"    {identifier['scheme']}: {identifier['value']}")
        if citation['cited_source_id']:
            lines.append(f"    Catalogue source: {m.lookup(db,'source',citation['cited_source_id'])['slug']}")
        if citation['needed_material']:
            lines.append(f"    Needed material: {citation['needed_material']}")
        lines.append('')
    return lines


def main():
    # Export one consistent snapshot without holding the working database's read
    # lock while generating catalogues and prerequisite closures.
    with closing(m.connect()) as source, closing(m.connect(':memory:')) as db:
        source.backup(db)
        state=m.snapshot(db)
        concepts={r['id']:r for r in state['concept'] if r['status']=='active'}
        sources={r['id']:r for r in state['source']}
        formalizations=m.formalizations(db)
        by_concept={}
        for review in formalizations:
            by_concept.setdefault(review['concept_id'],[]).append(review)
        (m.ROOT/'data/snapshot.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
        (m.ROOT/'data/formalizations.json').write_text(json.dumps(formalizations,ensure_ascii=False,indent=2)+'\n')
        with (m.ROOT/'data/formalizations.tsv').open('w',newline='') as fh:
            cols=['concept','title','concept_kind','statement_only','library','status','review_needed','file_count','measured_files','estimated_loc','known_loc']
            writer=csv.writer(fh,delimiter='\t')
            writer.writerow(cols+['files'])
            writer.writerows([[r[col] for col in cols]+['; '.join(f['path'] for f in r['files'])] for r in formalizations])
        lines=['THE SHAPE OF MATH — CONCEPTS v10','',json.dumps(m.verify(db),indent=2),'',
               'Each record is a short definition, theorem, construction or conjecture.',
               'Proof steps are recorded in dependency rationales and source notes.','', 'SOURCES','']
        for s in sources.values():
            lines += [f"{s['slug']} — {s['title']} [{s['status']}]",f"  Coverage: {s['coverage']}",
                      f"  Required concepts complete: {bool(s['requirements_complete'])}; introduced concepts complete: {bool(s['introductions_complete'])}; citations captured: {bool(s['citations_complete'])}",
                      f"  Source dependency review: {s['dependency_review']}"]
            for ident in state['source_identifier']:
                if ident['source_id']==s['id']: lines.append(f"  {ident['scheme']}: {ident['value']}")
            lines += citation_lines(db,s['id'])
            lines.append('')
        lines += ['CONCEPTS','']
        for c in sorted(concepts.values(),key=lambda r:r['title']):
            lines += [f"{c['slug']} — {c['title']} [{c['kind']}]",f"  {c['description']}"]
            lines.append(f"  Immediate statement prerequisites complete: {bool(c['statement_prerequisites_complete'])}")
            if c['kind'] in ('theorem','conjecture'):
                lines.append(f"  Immediate prerequisites for the proof complete: {bool(c['proof_prerequisites_complete'])}")
            if c['boundary']: lines.append('  Prerequisite frontier: elementary ingredients not expanded here.')
            for review in by_concept[c['id']]:
                estimate=review['estimated_loc']
                lines.append(f"  {review['library_name']} formalization: {review['status']}"+
                             (f"; estimated LOC: {estimate:.1f}" if estimate is not None else '; LOC unknown/incomplete'))
                if review['statement_only']:
                    lines.append('    Conjecture statement coverage only; this record does not claim a proof.')
                if review['review_needed']: lines.append('    Concept changed since formalization review; re-review required.')
                if review['evidence']: lines.append(f"    Evidence: {review['evidence']}")
                for f in review['files']:
                    lines.append(f"    {f['path']}: {f['note']}" + (f" [{f['declarations']}]" if f['declarations'] else ''))
                    lines.append(f"      File LOC: {f['loc']}; revision: {f['revision']}; allocated LOC: {f['allocated_loc']}")
            for e in state['concept_dependency']:
                if e['dependent_id']==c['id']:
                    lines.append(f"  <- {concepts[e['prerequisite_id']]['title']} [{e['purpose']}]: {e['rationale']}")
            for link in state['source_concept']:
                if link['concept_id']==c['id']:
                    lines.append(f"  {link['role']} in {sources[link['source_id']]['slug']}, {link['locator']}"+(f" — {link['note']}" if link['note'] else ''))
                    if link['role']=='introduces': lines.append(f"    Origin evidence: {link['introduction_evidence']}")
            for neighbor in m.related(db,c['slug']):
                lines.append(f"  Related: {neighbor['title']} — {neighbor['rationale']}")
            lines.append('')
        (m.ROOT/'data/catalogue.txt').write_text('\n'.join(lines))
        with (m.ROOT/'data/concepts.tsv').open('w',newline='') as fh:
            cols=['slug','title','kind','description','field','boundary','prerequisites_complete','statement_prerequisites_complete','proof_prerequisites_complete']
            writer=csv.writer(fh,delimiter='\t')
            writer.writerow(cols)
            writer.writerows([[c[col] for col in cols] for c in concepts.values()])
        for source in sources.values():
            if source['status']=='catalogued': continue
            occurrences=[link for link in state['source_concept'] if link['source_id']==source['id'] and link['concept_id'] in concepts]
            direct={link['concept_id'] for link in occurrences}
            background={r['id'] for r in m.closure(db,source['slug'])}-direct
            requirements=m.source_requirements(db,source['slug'])
            paper=[source['title'],'',f"Coverage: {source['coverage']}",
                   f"Required concepts complete: {bool(source['requirements_complete'])}",
                   f"Introduced concepts complete: {bool(source['introductions_complete'])}",
                   f"All citations captured: {bool(source['citations_complete'])}",
                   'Completion refers to immediate concepts only; false means not certified.',
                   '',f"REQUIRED CONCEPT FRONTIER ({len(requirements['direct'])})",'']
            for concept in requirements['direct']:
                paper += [f"- {concept['title']}: {concept['description']}"]
            paper += ['',f"INHERITED PREREQUISITES ({len(requirements['inherited'])})",'']
            for concept in requirements['inherited']:
                paper += [f"- {concept['title']} — via {', '.join(concept['via'])}"]
            intro={l['concept_id'] for l in occurrences if l['role']=='introduces'}
            paper += ['',f'INTRODUCED CONCEPTS ({len(intro)})','']
            paper += ['- '+concepts[cid]['title'] for cid in sorted(intro,key=lambda cid:concepts[cid]['title'])]
            if not intro: paper.append('Empty introduction list reviewed.' if source['introductions_complete'] else 'No origin claims recorded; introduction review remains incomplete.')
            paper += ['',f'LOCATED CONCEPTS ({len(direct)})','']
            for number,link in enumerate(occurrences,1):
                c=concepts[link['concept_id']]
                paper += [f"{number}. {c['title']}",
                          f"   {c['description']}",f"   Source: {link['role']}, {link['locator']}"]
                if link['note']: paper.append(f"   Note: {link['note']}")
                if link['role']=='introduces': paper.append(f"   Origin evidence: {link['introduction_evidence']}")
                paper.append('')
            paper += [f'ADDITIONAL PREREQUISITES ({len(background)})','']
            for cid in sorted(background,key=lambda cid:concepts[cid]['title']):
                c=concepts[cid]
                paper += [f"- {c['title']} [{c['kind']}]: {c['description']}"]
            paper += ['', 'CITATIONS', ''] + citation_lines(db,source['id'])
            (m.ROOT/'data'/f"{source['slug']}.txt").write_text('\n'.join(paper)+'\n')
            print(source['slug'],len(direct),'direct concepts;',len(background),'additional prerequisites')
        print(json.dumps(m.verify(db),indent=2))


if __name__=='__main__': main()
