"""Apply a digest-bound independent correction without altering old run artifacts.

Stop the queued importer first; this uses its same structural/revision/blob checks.
The mathematical replacement is supplied solely by author+independent reviewer.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

RUN=Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proposal',type=Path)
    parser.add_argument('review',type=Path)
    args=parser.parse_args()
    if (RUN/'watcher.pid').exists():
        raise SystemExit('Stop the queued importer cleanly before applying a follow-up.')
    author=json.loads(args.proposal.read_text())
    review=json.loads(args.review.read_text())
    ident=author.get('batch_id',author.get('followup_id'))
    if not ident or review.get('batch_id',review.get('followup_id'))!=ident:
        raise ValueError('Follow-up IDs do not match')
    if review['proposal_sha256']!=digest(args.proposal):
        raise ValueError('Independent review does not match exact correction proposal')
    if (RUN/'imported'/(ident+'.json')).exists():
        raise ValueError('This correction was already imported; do not silently replay it')
    if 'original_batch_id' in author:
        original=author['original_batch_id']
        if author['original_proposal_sha256']!=digest(RUN/'proposals'/(original+'.json')) or author['original_review_sha256']!=digest(RUN/'reviews'/(original+'.json')):
            raise ValueError('Referenced original proposal/review changed')
    for original in author.get('original_artifacts',[]):
        for stem in ('proposal','review'):
            if original[stem+'_sha256']!=digest(Path(original[stem+'_path'])):
                raise ValueError('Referenced original artifact changed')
    spec=importlib.util.spec_from_file_location('reviewed_import',RUN/'import_reviewed.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    slugs=sorted({r['concept'] for r in author['reviews']})
    libraries=sorted({r['library'] for r in author['reviews']})
    job=dict(id=ident,author=author['author'],reviewer=review['reviewer'],
             concepts=[module.ROSTER[slug] for slug in slugs],libraries=libraries)
    module.write_json(RUN/'jobs'/(ident+'.json'),job)
    shutil.copyfile(args.proposal,RUN/'proposals'/(ident+'.json'))
    shutil.copyfile(args.review,RUN/'reviews'/(ident+'.json'))
    print(json.dumps(module.import_one(job),indent=2))


if __name__=='__main__':
    main()
