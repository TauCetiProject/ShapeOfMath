"""Reviewed statement vocabulary for the existing theorem catalogue.

Other incoming edges describe the already selected proof routes. Missing proof
inputs remain open under the old immediate-completeness judgments; this pass does
not claim to have newly completed those proofs.
"""
from contextlib import closing
import json
import hashlib
import mathdb as m

STATEMENTS={
 'factorial-growth':'factorial sequence-limit',
 'fundamental-calculus':'riemann-integral derivative',
 'integration-by-parts':'riemann-integral derivative',
 'pi-irrational':'pi rational-number',
 'cesaro-lemma':'sequence-limit',
 'involution-parity':'finite-involution fixed-point congruence',
 'fermat-two-squares':'prime congruence',
 'finite-ramsey':'homogeneous-set finite-set',
 'erdos-szekeres-monotone':'monotone-subsequence natural-number',
 'erdos-szekeres-cups-caps':'cup-cap planar-general-position binomial-coefficient',
 'erdos-szekeres-convex':'convex-position planar-general-position binomial-coefficient',
 'klein-five-points':'convex-position planar-general-position',
 'monotone-gap-theorem':'euclidean-space binomial-coefficient',
 'konig-infinity':'rooted-tree',
 'sperner-lemma':'sperner-labeling',
 'dual-sperner-lemma':'dual-sperner-labeling',
 'bolzano-weierstrass':'euclidean-space sequence-limit',
 'cake-division-theorem':'envy-free-allocation closed-preference-correspondence simplex bijection',
 'rental-harmony':'envy-free-allocation closed-preference-correspondence simplex bijection',
 'chore-division-theorem':'envy-free-allocation closed-preference-correspondence simplex bijection',
 'brouwer-fixed-point':'simplex fixed-point continuous-map',
 'chebyshev-inequality':'variance',
 'borel-cantelli-first':'probability-space real-series',
 'monotone-convergence':'lebesgue-integral sequence-limit',
 'etemadi-strong-law':'pairwise-independence identically-distributed expectation almost-sure-convergence',
 'kolmogorov-strong-law':'independent-family identically-distributed expectation almost-sure-convergence',
 'kolmogorov-maximal':'independent-family variance',
 'divisor-summatory-bound':'divisor-function real-number',
 'abel-summation':'real-sequence',
 'etemadi-array-law':'pairwise-independence identically-distributed rectangular-average log-moment almost-sure-convergence',
 'schur-lemma':'simple-object isomorphism-in-category',
 'g2-web-basis':'nonelliptic-g2-web',
 'g2-spider-equivalence':'g2-spider seven-dimensional-g2 intertwiner braided-category monoidal-equivalence',
 'g2-braid-surjectivity':'seven-dimensional-g2 tensor-power-representation centralizer-algebra group-algebra braid-action-tensor-power',
 'lehrer-zhang-generation':'strong-multiplicity-free braid-action-tensor-power centralizer-algebra',
 'brauer-splitting':'cyclotomic-field group-algebra splitting-field-algebra algebra-module',
 'fpdim-cyclotomic':'frobenius-perron-dimension cyclotomic-integer',
 'global-dimension-cyclotomic':'global-dimension cyclotomic-integer',
 'noncyclotomic-haagerup':'principal-haagerup-category principal-extended-haagerup-category complete-rational-form cyclotomic-field',
 'haagerup-fields':'haagerup-subfactor extended-haagerup-subfactor principal-even-part dual-even-part complete-rational-form drinfeld-center ribbon-category quantum-integer',
 'haagerup-galois-conjugates':'galois-conjugate-category principal-haagerup-category principal-extended-haagerup-category normal-closure galois-group',
 'center-base-change':'rational-form drinfeld-center',
 'module-dual-base-change':'dual-fusion-category rational-form',
 'perron-frobenius':'spectral-radius',
 'galois-correspondence':'galois-group',
 'integral-monotonicity':'lebesgue-integral',
 'linearity-lebesgue-integral':'lebesgue-integral',
 'markov-inequality':'expectation',
 'partial-fractions':'complex-number rational-function',
 'holomorphic-spectral-mapping':'holomorphic-functional-calculus operator-spectrum',
 'caratheodory-blaschke-approximation':'finite-blaschke-product sequence holomorphic-function',
 'numerical-radius-norm-comparison':'numerical-radius operator-norm self-adjoint-operator',
 'toeplitz-hausdorff':'numerical-range convex-set',
 'numerical-radius-power-inequality':'numerical-radius natural-number',
 'berger-stampfli':'numerical-radius disk-algebra holomorphic-functional-calculus',
 'local-numerical-radius-norm-estimate':'numerical-radius complex-hilbert-space',
 'drury-teardrop':'numerical-range disk-algebra holomorphic-functional-calculus convex-hull',
 'crouzeix-functional-calculus':'holomorphic-functional-calculus numerical-range operator-norm',
 'snake-lemma':'exact-sequence-vector-spaces cokernel-linear-map',
 'vector-space-dimension-formula':'vector-space-dimension sum-vector-subspaces intersection-of-sets finite-dimensional-vector-space',
 'linear-kneser-theorem':'product-vector-subspaces-field stabilizer-field-vector-subspace vector-space-dimension separable-field-extension',
 'uniform-subfield-stabilizer-theorem':'product-vector-subspaces-field stabilizer-field-vector-subspace vector-space-dimension',
 'kneser-addition-theorem':'sumset stabilizer-subgroup-sumset finite-set',
 'balandraud-uniform-stabilizer-theorem':'sumset stabilizer-subgroup-sumset finite-set',
 'cauchy-schwarz-inner-product':'complex-inner-product-space complex-modulus',
}


def annotate_edges(edges):
    for e in edges:
        if e['dependent'] in STATEMENTS:
            e['purpose']='statement' if e['prerequisite'] in STATEMENTS[e['dependent']].split() else 'proof'


def project(payload):
    known={c['slug']:c for c in payload['concepts']}
    annotate_edges(payload['dependencies'])
    pairs={(e['prerequisite'],e['dependent']) for e in payload['dependencies']}
    for child,parents in STATEMENTS.items():
        if child not in known:continue
        for parent in parents.split():
            if parent not in known or (parent,child) in pairs:continue
            payload['dependencies'].append(dict(prerequisite=parent,dependent=child,purpose='statement',basis='both',
                rationale=f'The statement of {known[child]["title"]} uses {known[parent]["title"]}. Restored independently of proof-route shortcuts.'))
    return payload


def apply(db):
    fingerprint=hashlib.sha256(json.dumps(STATEMENTS,sort_keys=True).encode()).hexdigest()
    for r in db.execute("SELECT after_json FROM curation_event WHERE operation='dependency_purpose_review'"):
        if json.loads(r[0]).get('sha256')==fingerprint:return {'changes':0,'unrecorded_statement_vocabulary':[]}
    before=[dict(r) for r in db.execute('SELECT * FROM concept_dependency')]
    old_reviews={r['slug']:dict(r) for r in db.execute('SELECT * FROM concept')}
    changes=[];missing=[]
    with db:
        for e in before:
            child=m.lookup(db,'concept',e['dependent_id']);parent=m.lookup(db,'concept',e['prerequisite_id'])
            if child['slug'] not in STATEMENTS:continue
            purpose='statement' if parent['slug'] in STATEMENTS[child['slug']].split() else 'proof'
            if e['purpose']!=purpose:
                db.execute('UPDATE concept_dependency SET purpose=? WHERE id=?',(purpose,e['id']))
                changes.append({'before':e,'purpose':purpose})
        for child,parents in STATEMENTS.items():
            if child not in old_reviews:continue
            for parent in parents.split():
                if parent not in old_reviews:
                    missing.append({'dependent':child,'missing_statement_concept':parent});continue
                p=old_reviews[parent]['id'];d=old_reviews[child]['id']
                if not db.execute('SELECT 1 FROM concept_dependency WHERE prerequisite_id=? AND dependent_id=?',(p,d)).fetchone():
                    edge=dict(prerequisite=parent,dependent=child,purpose='statement',basis='both',
                              rationale=f'The theorem statement uses {old_reviews[parent]["title"]}; a proof-only route cannot replace this statement dependency.')
                    m.add_edge(db,edge);changes.append({'restored':edge})
        m.event(db,'classify_dependency_purposes','Review existing theorem statement vocabulary separately from selected-proof inputs, restoring shortcuts removed by untyped reduction.',{}, {'changes':changes,'unrecorded_statement_vocabulary':missing})
    reduction=m.reduce_dependencies(db,'Preserve both statement and proof reachability; never remove a statement edge via a proof-only path.')
    for slug,c in old_reviews.items():
        if slug not in STATEMENTS:continue
        complete=bool(c['prerequisites_complete']) and not any(r['dependent']==slug for r in missing)
        m.set_completeness(db,'concept',slug,{'statement_prerequisites_complete':complete,'proof_prerequisites_complete':bool(c['prerequisites_complete'])},
            'Typed review of the existing immediate lists: statement vocabulary is separated from the selected proof; preserve previously explicit union reviews and leave previously unfinished lists uncertified. Proof parents are recorded but not recursively followed by the statement expansion.')
    with db:m.event(db,'dependency_purpose_review','Finish explicit classification of the existing theorem catalogue; future expansion follows statement edges and records proof frontiers.',{}, {'sha256':fingerprint,'missing_statement_vocabulary':missing})
    return {'changes':len(changes),'unrecorded_statement_vocabulary':missing,'reduction':reduction}


if __name__=='__main__':
    with closing(m.connect()) as db:
        m.initialize(db);out=apply(db);print(json.dumps({'changes':out['changes'],'missing':out['unrecorded_statement_vocabulary'],**m.verify(db)},indent=2))
