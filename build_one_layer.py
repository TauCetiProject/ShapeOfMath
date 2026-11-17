"""Freeze the non-cyclotomic seed list, review its parents once, and stop."""
import hashlib
import json
from pathlib import Path
import build_example as original

ROOT=Path(__file__).resolve().parent
NEW=[]
RESOURCES=[]


def definitions(text):
    for line in text.strip().splitlines():
        slug,kind,title,description,field,source,locator=line.split('|')
        NEW.append(dict(slug=slug,kind=kind,title=title,description=description,field=field,
                        boundary=True,aliases=[],learning_source=source,learning_locator=locator))


definitions('''
category|definition|Category|Objects and morphisms with associative composition and identity morphisms.|Category theory|stacks-project|Categories, §2, Definition 2.1
functor|definition|Functor|A map of categories preserving objects, morphisms, identities and composition.|Category theory|stacks-project|Categories, §2
natural-transformation|definition|Natural transformation|A family of maps between the values of two functors, commuting with every morphism in their source category.|Category theory|stacks-project|Categories, §2
category-equivalence|definition|Equivalence of categories|A functor with an inverse up to natural isomorphism.|Category theory|stacks-project|Categories, §2
monoidal-functor|definition|Strong monoidal functor|A functor equipped with coherent isomorphisms preserving tensor products and the tensor unit.|Category theory|egno-tensor-categories-2015|§2.4
monoidal-equivalence|definition|Tensor equivalence|A strong monoidal functor whose underlying functor is an equivalence of categories.|Category theory|egno-tensor-categories-2015|§2.4
monoidal-natural-transformation|definition|Monoidal natural transformation|A natural transformation between monoidal functors compatible with their tensor-product and unit maps.|Category theory|egno-tensor-categories-2015|§2.4
dual-object|definition|Dual object in a monoidal category|An object paired with another by evaluation and coevaluation maps satisfying the two zigzag identities; left and right duals reverse the order of the factors.|Category theory|egno-tensor-categories-2015|§2.10
double-dual-functor|definition|Double-dual functor|The covariant monoidal endofunctor X↦X** obtained by taking a chosen dual twice in a rigid monoidal category.|Category theory|egno-tensor-categories-2015|§§2.10 and 4.7
endomorphism-algebra|definition|Endomorphism algebra of an object in a linear category|The vector space End(X), with multiplication given by composition and unit the identity of X.|Category theory|egno-tensor-categories-2015|§§1.2–1.3
idempotent-endomorphism|definition|Idempotent endomorphism|An endomorphism e:X→X satisfying e∘e=e.|Category theory|stacks-project|Homological Algebra, §12.4, tag 09SF
idempotent-splitting|definition|Splitting of an idempotent endomorphism|Maps r:X→Y and i:Y→X with ir=e and ri=id_Y exhibit Y as the image of the idempotent e.|Category theory|stacks-project|Homological Algebra, §12.4, tag 09SF
additive-category|definition|Additive category|A category with abelian-group morphism sets, bilinear composition, a zero object and finite biproducts.|Category theory|egno-tensor-categories-2015|§1.2, Definition 1.2.1
abelian-category|definition|Abelian category|An additive category with kernels and cokernels in which every monomorphism is a kernel and every epimorphism is a cokernel.|Category theory|egno-tensor-categories-2015|§1.3, Definition 1.3.1
subobject|definition|Subobject in a category|An equivalence class of monomorphisms into a fixed object, where two are equivalent if an isomorphism of their domains commutes with the maps.|Category theory|egno-tensor-categories-2015|§1.3, Definition 1.3.5
zero-object|definition|Zero object in a category|An object that is both initial and terminal.|Category theory|stacks-project|Categories, §12
biproduct|definition|Finite biproduct|An object with injections and projections making it simultaneously the finite product and coproduct of the given objects.|Category theory|egno-tensor-categories-2015|§1.2
adjoint-functors|definition|Adjoint functors|Functors F:C→D and G:D→C with natural bijections Hom_D(FX,Y)≅Hom_C(X,GY); F is left adjoint to G.|Category theory|stacks-project|Categories, §24
representable-functor|definition|Representable functor|A functor naturally isomorphic to Hom(A,−), or to Hom(−,A) in the contravariant case.|Category theory|stacks-project|Categories, §3
tensor-category|definition|Tensor category over a field|A locally finite k-linear abelian rigid monoidal category with a k-bilinear tensor product and End(1)=k. Semisimplicity is not required.|Tensor categories|egno-tensor-categories-2015|§§4.1 and 4.16
twist|definition|Twist in a braided monoidal category|A natural automorphism θ of the identity with θ₁=id and θ_{X⊗Y}=c_{Y,X}c_{X,Y}(θ_X⊗θ_Y).|Tensor categories|egno-tensor-categories-2015|§8.10
tensor-ideal|definition|Tensor ideal of morphisms|A family of linear subspaces of morphism spaces closed under composition on either side and tensoring with arbitrary morphisms.|Tensor categories|egno-tensor-categories-2015|§§2.10 and 4.11; compare negligible morphisms in the paper
quotient-linear-category|definition|Quotient of a linear category by an ideal|Keep the objects and replace each morphism space by its quotient by the corresponding ideal subspace.|Category theory|morrison-snyder-2012|Definition 3.2, with the general quotient construction
vector-space|definition|Vector space|An abelian group with scalar multiplication by a field, satisfying the distributive and associativity laws.|Linear algebra|representation-theory-notes-2011|§1.2, linear-algebra background
bilinear-map|definition|Bilinear map|A map of two vector-space variables that is linear in each variable separately.|Linear algebra|conrad-tensor-products|§3
tensor-product-vectors|definition|Tensor product of vector spaces|The vector space V⊗W with its universal bilinear map from V×W.|Linear algebra|conrad-tensor-products|§§1 and 3
field|definition|Field|A commutative ring in which 1≠0 and every nonzero element is invertible.|Algebra|milne-galois-notes|Chapter 1, Fields
associative-algebra|definition|Associative algebra over a field|A vector space with an associative bilinear multiplication and a multiplicative identity.|Algebra|representation-theory-notes-2011|§1.2
algebra-module|definition|Module over an associative algebra|A vector space on which the algebra acts linearly, compatibly with multiplication and the identity.|Algebra|representation-theory-notes-2011|§1.3
idempotent-element|definition|Idempotent element of an algebra|An element e satisfying e²=e.|Algebra|morrison-jones-wenzl-2015|§2
orthogonal-idempotents|definition|Orthogonal idempotents in an algebra|Idempotents e and f satisfying ef=fe=0.|Algebra|representation-theory-notes-2011|§2.3
algebra-unit|definition|Invertible element of an algebra|An element with a two-sided multiplicative inverse.|Algebra|milne-galois-notes|Chapter 1, Rings
split-semisimple-algebra|definition|Split semisimple algebra|A finite-dimensional algebra isomorphic to a finite product of full matrix algebras over its base field.|Algebra|representation-theory-notes-2011|§§2.3 and 2.5
temperley-lieb-algebra|definition|Temperley–Lieb algebra|TL_n(δ) is spanned by planar noncrossing pairings of n top and n bottom points. Multiply by stacking and replace every closed loop by δ; equivalently its generators satisfy eᵢ²=δeᵢ, eᵢeᵢ₊₁eᵢ=eᵢ and eᵢeⱼ=eⱼeᵢ for abs(i−j)>1.|Diagrammatic algebra|morrison-jones-wenzl-2015|§1; δ=−[2] in that note
colored-operad|definition|Colored operad|A collection of operations with specified input and output types, with associative substitution into inputs and identity operations.|Operads|morrison-snyder-2012|§2.3, gluing shaded tangles
planar-isotopy|definition|Planar isotopy of tangle diagrams|A continuous deformation of embedded diagrams preserving their incidences, boundary components and marked data.|Topology|morrison-snyder-2012|Definition 2.2
fusion-matrix|definition|Fusion matrix|For an object X in a fusion category, the matrix with entries N_{X,Y}^Z recording the multiplicity of Z in X⊗Y, indexed by simple objects.|Tensor categories|egno-tensor-categories-2015|§4.5
grothendieck-ring|definition|Grothendieck ring of a fusion category|The free abelian group on simple isomorphism classes, with addition induced by direct sum and multiplication by tensor product.|Tensor categories|egno-tensor-categories-2015|§4.5
spectral-radius|definition|Spectral radius of a finite matrix|The maximum absolute value of the complex eigenvalues of the matrix.|Linear algebra|egno-tensor-categories-2015|§3.2
perron-frobenius|theorem|Perron–Frobenius theorem for nonnegative matrices|A nonnegative real matrix has a nonnegative eigenvalue equal to its spectral radius. If it is irreducible, that eigenvalue is simple and has a strictly positive eigenvector, unique up to scalar.|Linear algebra|egno-tensor-categories-2015|§3.2, Theorem 3.2.1
squared-norm|definition|Squared norm of a simple object in a rigid tensor category|The choice-independent product of the two quantum traces obtained from an isomorphism X→X** and its inverse dual; in a pivotal category it equals dim(X)dim(X*).|Tensor categories|egno-tensor-categories-2015|§7.21, Definition 7.21.2
ii1-factor|definition|Type II₁ factor|An infinite-dimensional von Neumann algebra with center ℂ1 admitting a faithful normal tracial state.|Operator algebras|jones-von-neumann-notes|§6.1, Definition 6.1.10
hilbert-bimodule|definition|Hilbert bimodule over von Neumann algebras|A Hilbert space with commuting normal unital *-representations of M and Nᵒᵖ, giving left M and right N actions.|Operator algebras|thom-connes-fusion-2006|§2.1
tracial-l2-space|definition|Tracial L²-space of a finite von Neumann algebra|The Hilbert completion of M for the inner product ⟨x,y⟩=τ(y*x), with the natural left and right multiplication actions.|Operator algebras|jones-von-neumann-notes|Chapter 7 and Chapter 10
connes-fusion|construction|Connes fusion of Hilbert bimodules|The relative tensor product of an M–N and an N–P Hilbert bimodule, formed using bounded vectors and completion in the canonical relative inner product, producing an M–P Hilbert bimodule.|Operator algebras|thom-connes-fusion-2006|§5; the note treats the same-algebra case and explains the generalization
module-dimension|definition|Von Neumann dimension of a Hilbert module|A Hilbert module over a finite factor is represented by a projection on a sum of copies of L²(M); its dimension is the extended matrix trace of that projection.|Operator algebras|jones-von-neumann-notes|§10.1
hyperfinite-von-neumann|definition|Hyperfinite von Neumann algebra|A von Neumann algebra that is the weak closure of an increasing union of finite-dimensional *-subalgebras.|Operator algebras|jones-von-neumann-notes|§15.1
field-extension|definition|Field extension|An inclusion of one field into another.|Field theory|milne-galois-notes|Chapter 1, Extension fields
number-field|definition|Number field|A finite extension of ℚ.|Number theory|milne-number-theory-notes|Introduction and Chapter 2
algebraic-integer|definition|Algebraic integer|A complex number satisfying a monic polynomial with integer coefficients.|Number theory|milne-number-theory-notes|Chapter 2
root-of-unity|definition|Root of unity|An element ζ satisfying ζⁿ=1 for some positive integer n; its order is the least such n.|Field theory|milne-galois-notes|Chapter 5, Cyclotomic extensions
field-embedding|definition|Field embedding|An injective homomorphism of fields preserving the multiplicative identity.|Field theory|milne-galois-notes|Chapters 1–2
splitting-field-algebra|definition|Splitting field for a semisimple algebra|A field extension K/k for which K⊗_k A is a product of full matrix algebras over K.|Algebra|representation-theory-notes-2011|§§2.3–2.5; compare Brauer's theorem in Morrison–Snyder §2.1
galois-group|definition|Galois group of a finite Galois extension|The group of field automorphisms of the extension that fix the base field pointwise.|Field theory|milne-galois-notes|Chapter 3
normal-closure|definition|Normal closure of a number field|The smallest normal extension of ℚ inside a fixed algebraic closure that contains the given number field.|Field theory|milne-galois-notes|Chapter 2, Normal closures
galois-correspondence|theorem|Fundamental theorem of finite Galois theory|For a finite Galois extension L/k, intermediate fields correspond bijectively, with inclusions reversed, to subgroups of Gal(L/k), by taking fixed fields.|Field theory|milne-galois-notes|Chapter 3
''')

# Only old seed concepts are targets in this pass. New records receive no incoming
# prerequisite edges until a later pass, even when both ingredients are now present.
ADDITIONS={
 'linear-category':'category vector-space bilinear-map field',
 'pivotal-category':'double-dual-functor monoidal-natural-transformation',
 'braided-category':'natural-transformation',
 'categorical-trace':'dual-object',
 'group-algebra':'associative-algebra vector-space field',
 'integer':'',
 'monoidal-category':'category functor natural-transformation',
 'rigid-category':'dual-object',
 'ribbon-category':'twist dual-object',
 'simple-object':'abelian-category subobject zero-object',
 'semisimple-category':'additive-category biproduct',
 'split-simple':'endomorphism-algebra field',
 'split-semisimple':'additive-category',
 'fusion-category':'tensor-category simple-object abelian-category',
 'split-fusion-category':'endomorphism-algebra',
 'scalar-extension-category':'field-extension tensor-product-vectors',
 'rational-form':'monoidal-equivalence monoidal-functor',
 'complete-rational-form':'idempotent-endomorphism idempotent-splitting',
 'karoubi-envelope':'category idempotent-endomorphism idempotent-splitting',
 'minimal-idempotent':'associative-algebra idempotent-element orthogonal-idempotents',
 'schur-lemma':'abelian-category',
 'cyclotomic-field':'number-field root-of-unity',
 'cyclotomic-integer':'algebraic-integer',
 'frobenius-perron-dimension':'fusion-matrix grothendieck-ring spectral-radius perron-frobenius',
 'global-dimension':'squared-norm',
 'brauer-splitting':'splitting-field-algebra split-semisimple-algebra algebra-module',
 'fpdim-cyclotomic':'root-of-unity algebraic-integer',
 'global-dimension-cyclotomic':'root-of-unity algebraic-integer',
 'ii1-subfactor':'ii1-factor',
 'jones-index':'module-dimension tracial-l2-space',
 'principal-even-part':'hilbert-bimodule tracial-l2-space connes-fusion',
 'dual-even-part':'hilbert-bimodule tracial-l2-space connes-fusion',
 'principal-graph':'fusion-matrix',
 'finite-depth':'simple-object',
 'haagerup-subfactor':'hyperfinite-von-neumann',
 'extended-haagerup-subfactor':'hyperfinite-von-neumann',
 'principal-haagerup-category':'', 'dual-haagerup-category':'',
 'principal-extended-haagerup-category':'', 'dual-extended-haagerup-category':'',
 'haagerup-center':'', 'haagerup-planar-algebra':'', 'extended-haagerup-planar-algebra':'',
 'shaded-planar-tangle':'planar-isotopy',
 'shaded-planar-algebra':'colored-operad vector-space',
 'uncappable':'', 'rotational-eigenvector':'root-of-unity',
 'lopsided-planar-algebra':'', 'quantum-integer':'field',
 'jones-wenzl-idempotent':'temperley-lieb-algebra idempotent-element algebra-unit',
 'negligible-morphism':'tensor-ideal',
 'semisimplification':'tensor-ideal quotient-linear-category',
 'half-braiding':'natural-transformation',
 'drinfeld-center':'functor',
 'center-induction':'adjoint-functors',
 'module-category':'functor natural-transformation',
 'dual-fusion-category':'functor natural-transformation',
 'internal-hom':'representable-functor',
 's-matrix':'dual-object', 't-matrix':'twist', 'modular-category':'spectral-radius',
 'center-base-change':'category-equivalence',
 'module-dual-base-change':'monoidal-equivalence',
 'noncyclotomic-haagerup':'field-embedding',
 'haagerup-fields':'field-extension monoidal-equivalence',
 'galois-conjugate-category':'field-embedding monoidal-equivalence',
 'haagerup-galois-conjugates':'normal-closure galois-group galois-correspondence',
}
# Knowing spectral radius is not necessary to understand invertibility of an S matrix.
# The existing linear-algebra convention in that definition suffices this pass.
ADDITIONS['modular-category']=''


def resource(slug,title,authors,url,year=None,local=None,version='Accessed 2026-11-12'):
    path=ROOT/'references'/(local or (slug+'.pdf'))
    artifact=dict(url=url,version=version,accessed_at='2026-11-12',note='Selected definition excerpts inspected as learning resources; not an ingestion of the whole book.')
    if path.exists(): artifact.update(local_path=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    RESOURCES.append(dict(slug=slug,title=title,authors=authors,year=year,field='Standard background',status='catalogued',
                          identifiers=[['url',url]],coverage='Only the located definition excerpts are selected; full-source ingestion has not been performed.',
                          summary=title,dependency_review='Learning resource. No strict dependency from the research paper is implied.',artifacts=[artifact]))


resource('egno-tensor-categories-2015','Tensor Categories',['Pavel Etingof','Shlomo Gelaki','Dmitri Nikshych','Victor Ostrik'],
         'https://math.mit.edu/~etingof/egnobookfinal.pdf',2015)
resource('stacks-project','The Stacks Project',['The Stacks Project Authors'],'https://stacks.math.columbia.edu/',
         local='stacks-categories.pdf',version='Categories chapter snapshot; Karoubian section tag 09SF also inspected')
RESOURCES[-1]['artifacts'][0]['url']='https://stacks.math.columbia.edu/download/categories.pdf'
resource('morrison-jones-wenzl-2015','A Formula for the Jones-Wenzl Projections',['Scott Morrison'],
         'https://tqft.net/math/JonesWenzlProjections.pdf',2015)
RESOURCES[-1]['identifiers'].append(['arxiv','1503.00384'])
resource('jones-von-neumann-notes','Von Neumann Algebras',['Vaughan F. R. Jones'],
         'https://math.berkeley.edu/~vfr/VonNeumann2009.pdf',2009)
resource('milne-galois-notes','Fields and Galois Theory',['J. S. Milne'],
         'https://www.jmilne.org/math/CourseNotes/FT.pdf',2022,version='5.10, September 2022')
resource('milne-number-theory-notes','Algebraic Number Theory',['J. S. Milne'],
         'https://www.jmilne.org/math/CourseNotes/ANT.pdf',2020,version='3.08, July 2020')
resource('thom-connes-fusion-2006','A remark about the Connes fusion tensor product',['Andreas Thom'],
         'https://arxiv.org/pdf/math/0601045',2006,version='arXiv:math/0601045v1')
RESOURCES[-1]['identifiers'].append(['arxiv','math/0601045'])
resource('representation-theory-notes-2011','Introduction to representation theory',
         ['Pavel Etingof','Oleg Golberg','Sebastian Hensel','Tiankai Liu','Alex Schwendner','Dmitry Vaintrob','Elena Yudovina'],
         'https://math.mit.edu/~etingof/replect.pdf',2011,version='January 10, 2011')
resource('conrad-tensor-products','Tensor Products',['Keith Conrad'],
         'https://kconrad.math.uconn.edu/blurbs/linmultialg/tensorprod.pdf')


def main():
    authors=json.loads((ROOT/'data/author-papers.json').read_text())
    known={c['slug']:c for c in original.CONCEPTS+authors['concepts']}
    base_edges=original.EDGES+authors['dependencies']
    direct_seed={l['concept'] for l in authors['source_concepts'] if l['source']=='morrison-snyder-2012'}
    seed=set(direct_seed)
    # Include the background already in the previous paper catalogue. This freeze
    # follows only the pre-existing graph, before this pass proposes any new nodes.
    while True:
        expanded=seed|{e['prerequisite'] for e in base_edges if e['dependent'] in seed}
        if expanded==seed: break
        seed=expanded
    assert set(ADDITIONS)==seed,(sorted(seed-set(ADDITIONS)),sorted(set(ADDITIONS)-seed))
    new={c['slug']:c for c in NEW}
    assert len(new)==len(NEW) and not set(new)&set(known)
    all_concepts={**known,**new}
    parents={s:{e['prerequisite'] for e in base_edges if e['dependent']==s} for s in seed}
    batch_edges=[]
    for target,extra in ADDITIONS.items():
        for parent in extra.split():
            assert parent in all_concepts,parent
            if parent in parents[target]: continue
            parents[target].add(parent)
            item=all_concepts[parent]
            row=dict(prerequisite=parent,dependent=target,basis='pedagogical' if all_concepts[target]['kind']=='theorem' else 'both',
                     rationale=f"To understand {all_concepts[target]['title']}, learn {item['title']}; this is inferred background, not an original-paper citation.")
            if parent in new:
                row.update(source=item['learning_source'],locator=item['learning_locator'])
            batch_edges.append(row)
    selected=set().union(*parents.values())
    assert set(new)<=selected,sorted(set(new)-selected)
    assert all(e['dependent'] in seed for e in batch_edges)
    links=[]
    for c in NEW:
        links.append(dict(source=c['learning_source'],concept=c['slug'],role='explains',locator=c['learning_locator'],
                          note='Selected learning reference; not a priority claim or a strict paper dependency. This new concept is not expanded in this pass.'))
        if c['slug']=='vector-space':
            links[-1]['role']='relies_on'
            links[-1]['note']='This exposition assumes vector-space theory. A dedicated introductory linear-algebra reference remains to be selected; the new concept is unexpanded.'
    # Two especially useful learning links for existing concepts.
    links += [dict(source='morrison-jones-wenzl-2015',concept='jones-wenzl-idempotent',role='explains',locator='§§1–2',
                   note='The note uses loop value −[2]. Our TL_n(δ) records the loop parameter explicitly, so signs must be translated.'),
              dict(source='stacks-project',concept='karoubi-envelope',role='discusses',locator='Homological Algebra, §12.4, tag 09SF',
                   note='Explains splitting of idempotents and the Karoubian property. No dependency of Morrison–Snyder on this exposition is asserted.'),
              dict(source='egno-tensor-categories-2015',concept='fusion-category',role='explains',locator='§§4.1 and 4.16',
                   note='Use §4.16 for non-algebraically closed fields; do not silently impose splitness. The source uses an additive convention for linear categories.')]
    batch=dict(note='One frozen expansion layer for Non-cyclotomic fusion categories. New concept prerequisites are intentionally unexpanded.',
               sources=RESOURCES,concepts=[{k:v for k,v in c.items() if not k.startswith('learning_')} for c in NEW],
               dependencies=batch_edges,source_concepts=links,source_relations=[])
    report=dict(paper='morrison-snyder-2012',seed_concepts=sorted(seed),direct_seed_concepts=sorted(direct_seed),
                new_to_database=sorted(new),new_to_paper_existing=sorted((selected-seed)&set(known)),
                reused_prerequisite_concepts=sorted(selected&set(known)),
                new_to_paper=sorted(selected-seed),
                reviews=[dict(concept=s,parents=sorted(parents[s]),added_parents=ADDITIONS[s].split(),
                              note='Existing parents reviewed; no additional prerequisites selected in this pass.' if not ADDITIONS[s] else 'Selected direct background; expand new parents in a later pass.') for s in sorted(seed)])
    (ROOT/'data/one-layer-batch.json').write_text(json.dumps(batch,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'data/one-layer-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['NON-CYCLOTOMIC FUSION CATEGORIES — ONE EXPANSION LAYER','',
           f"Frozen seed: {len(seed)} concepts; new database records: {len(new)}; existing collection concepts newly included for this paper: {len(report['new_to_paper_existing'])}.",
           'All added prerequisite edges target the frozen seed. Newly created concepts have not had their own prerequisites expanded.','', 'PREREQUISITE REVIEW','']
    for review in report['reviews']:
        s=review['concept']; lines += [all_concepts[s]['title'], '  Immediate prerequisites: '+('; '.join(all_concepts[p]['title'] for p in review['parents']) or '(none selected)'),
                                      '  '+review['note'],'']
    lines+=['NEW CONCEPTS','']
    for c in NEW:
        lines += [c['title'], '  '+c['description'],f"  Learn from: {c['learning_source']}, {c['learning_locator']}",'']
    (ROOT/'data/noncyclotomic-one-layer.txt').write_text('\n'.join(lines))
    print(json.dumps({'seed':len(seed),'new_database_records':len(new),'existing_added_to_paper':len(report['new_to_paper_existing']),
                      'layer_size':len(selected-seed),'added_edges':len(batch_edges),'learning_sources':len(RESOURCES)}))


if __name__=='__main__': main()
