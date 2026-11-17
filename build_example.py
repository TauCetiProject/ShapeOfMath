"""Manual concept catalogue: short definitions, precise theorems, and one construction."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONCEPTS, EDGES, LINKS = [], [], []


def records(field, text):
    for line in text.strip().splitlines():
        slug, kind, title, description, prereqs = line.split('|')
        CONCEPTS.append(dict(slug=slug, kind=kind, title=title, description=description,
                             field=field, aliases=[], boundary=not prereqs))
        for prerequisite in prereqs.split():
            EDGES.append(dict(prerequisite=prerequisite, dependent=slug, basis='both',
                              rationale='The definition or chosen proof of this concept uses the prerequisite as specified.'))


records('Foundations / analysis', '''
finite-set|definition|Finite set|A set X is finite if it is bijective with {1,…,n} for some integer n≥0; its cardinality is n.|
integer|definition|Integer|An integer is an element of the ordered ring ℤ, obtained by adjoining additive inverses to the natural numbers.|
real-number|definition|Real number|A real number is an element of a complete ordered field ℝ; completeness means every nonempty subset bounded above has a least upper bound.|
real-sequence|definition|Real sequence|A real sequence is a function a:ℕ₊→ℝ, written (aₙ)ₙ≥1.|integer real-number
sequence-limit|definition|Limit of a real sequence|A sequence (aₙ) converges to L∈ℝ if for every ε>0 there is N such that n≥N implies abs(aₙ−L)<ε.|real-sequence
real-series|definition|Convergent real series|The series ∑ₙ≥1aₙ converges to S if its sequence of partial sums converges to S.|sequence-limit
nonnegative-series|definition|Sum of a nonnegative series|For aₙ≥0, define ∑ₙ≥1aₙ as the supremum of its finite partial sums; the value may be infinite.|real-number integer
factorial|definition|Factorial|For n≥1, n!=1·2···n, and 0!=1.|integer
factorial-growth|theorem|Factorial domination of fixed exponentials|For every fixed real C>0, the sequence Cⁿ/n! tends to zero.|factorial sequence-limit
real-polynomial|definition|Real polynomial|A real polynomial is a finite sum ∑ⱼ₌₀ᵐaⱼxʲ with real coefficients and nonnegative integer m.|real-number integer
integer-polynomial|definition|Integer polynomial|An integer polynomial is a real polynomial all of whose coefficients lie in ℤ.|real-polynomial integer
derivative|definition|Derivative of a real function|The derivative f′(x) is the finite limit of (f(x+h)−f(x))/h as h→0, when it exists. Higher derivatives are defined by iteration.|real-number
riemann-integral|definition|Riemann integral|A bounded f:[a,b]→ℝ has Riemann integral I if all tagged Riemann sums approach I as the maximum length of the partition intervals tends to zero.|real-number
fundamental-calculus|theorem|Fundamental theorem of calculus for continuous integrands|If f is continuous on [a,b], then F(x)=∫ₐˣf(t)dt has derivative f on (a,b); any antiderivative G of f satisfies ∫ₐᵇf=G(b)−G(a).|riemann-integral derivative
integration-by-parts|theorem|Integration by parts for C¹ real functions|For u,v∈C¹([a,b]), ∫ₐᵇuv′=u(b)v(b)−u(a)v(a)−∫ₐᵇu′v.|fundamental-calculus
rational-number|definition|Rational number|A real x is rational if x=a/b for integers a,b with b≠0; otherwise it is irrational.|integer real-number
sine|definition|Real sine function|The sine function is defined by the everywhere convergent power series sin(x)=∑ₖ≥0(−1)ᵏx²ᵏ⁺¹/(2k+1)!.|real-series factorial
pi|definition|π|π is the least positive zero of the real sine function and equals the circumference-to-diameter ratio of a Euclidean circle.|sine
pi-irrational|theorem|Irrationality of π|There are no integers a,b with b≠0 such that π=a/b.|pi rational-number integer-polynomial factorial-growth integration-by-parts
cesaro-lemma|theorem|Cesàro convergence theorem|If aₙ→L, then (a₁+···+aₙ)/n→L.|sequence-limit
''')

records('Number theory', '''
prime|definition|Prime number|An integer p>1 is prime if its only positive divisors are 1 and p.|integer
congruence|definition|Congruence modulo an integer|The relation a≡b (mod m) means that m divides a−b.|integer
finite-involution|definition|Involution of a finite set|An involution of a finite set X is a map f:X→X with f(f(x))=x for all x∈X.|finite-set
fixed-point|definition|Fixed point of a self-map|A fixed point of f:X→X is an x∈X satisfying f(x)=x. The fixed-point set is Fix(f)={x∈X:f(x)=x}.|
involution-parity|theorem|Fixed-point parity lemma for finite involutions|If f is an involution of a finite set X, then X and Fix(f) have the same cardinality modulo two.|finite-involution fixed-point integer
zagier-involution|construction|Zagier's involution|On Sₚ={(x,y,z)∈ℤ₊³:x²+4yz=p}, map (x,y,z) to (x+2z,z,y−x−z) when x<y−z; to (2y−x,y,x−y+z) when y−z<x<2y; and to (x−2y,x−y+z,y) when x>2y. These cases define a self-inverse map of Sₚ.|prime congruence finite-involution
fermat-two-squares|theorem|Fermat's two-square theorem|A prime p is a²+b² for integers a,b if and only if p=2 or p≡1 (mod 4).|prime congruence involution-parity zagier-involution
''')

records('Combinatorics / discrete geometry', '''
euclidean-space|definition|Euclidean space ℝᵈ|For d≥1, ℝᵈ consists of d-tuples of real numbers with distance dist(x,y)=(∑ᵢ(xᵢ−yᵢ)²)¹ᐟ².|real-number integer
convex-set|definition|Convex subset of ℝᵈ|C⊆ℝᵈ is convex if (1−t)x+ty∈C whenever x,y∈C and 0≤t≤1.|euclidean-space
convex-hull|definition|Convex hull|The smallest convex set containing a given set of points.|convex-set
convex-position|definition|Convex position|A finite P⊂ℝ² is in convex position if no point of P is in the convex hull of the other points.|convex-hull finite-set
planar-general-position|definition|General position for planar point sets|A finite P⊂ℝ² is in general position here if no three distinct points of P lie on one line.|euclidean-space finite-set
subset-coloring|definition|Coloring of r-element subsets|An r-subset coloring is a map from the r-element subsets of X to C.|finite-set integer
homogeneous-set|definition|Homogeneous set for a subset coloring|H⊆X is homogeneous for c if c is constant on the r-element subsets of H.|subset-coloring
finite-ramsey|theorem|Finite Ramsey theorem for uniform subset colorings|For integers r≥1 and s,t≥r, there is N such that every red–blue coloring of r-subsets of an N-element set has a red-homogeneous s-set or a blue-homogeneous t-set.|homogeneous-set
ramsey-number|definition|Two-color uniform Ramsey number Rᵣ(s,t)|Rᵣ(s,t) is the least N such that every red–blue r-subset coloring on N elements has a red-homogeneous s-set or a blue-homogeneous t-set; set it to ∞ if there is no such N.|homogeneous-set integer
finite-simple-graph|definition|Finite simple undirected graph|A finite simple graph is (V,E), where V is finite and E is a set of two-element subsets of V.|finite-set
clique|definition|Clique|A set of vertices of a graph, every two of which are adjacent.|finite-simple-graph
independent-set|definition|Independent set in a graph|A set of vertices in a graph containing no edge.|finite-simple-graph
monotone-subsequence|definition|Monotone subsequence|A strictly increasing subsequence has indices i₁<···<iₖ and values aᵢ₁<···<aᵢₖ; a decreasing subsequence reverses the value comparisons and retains increasing indices.|real-number finite-set
erdos-szekeres-monotone|theorem|Erdős–Szekeres monotone subsequence theorem|For integers r,s≥2, every sequence of (r−1)(s−1)+1 distinct real numbers has an increasing subsequence of length r or a decreasing subsequence of length s, both strict. The threshold is sharp.|monotone-subsequence integer
cup-cap|definition|Cups and caps of planar point sets|Order p₁,…,pₖ by increasing x-coordinate. They form a k-cup if the k−1 successive slopes strictly increase, and a k-cap if those slopes strictly decrease.|euclidean-space
binomial-coefficient|definition|Binomial coefficient|The binomial coefficient binom(n,k) counts the k-subsets of an n-element set and equals n!/(k!(n−k)!).|finite-set factorial
erdos-szekeres-cups-caps|theorem|Erdős–Szekeres cups–caps theorem|For r,s≥3, any binom(r+s−4,r−2)+1 planar points with no three collinear and with distinct x-coordinates contain an r-cup or an s-cap. This threshold is sharp for the cups–caps problem.|cup-cap planar-general-position binomial-coefficient
erdos-szekeres-convex|theorem|Erdős–Szekeres convex polygon theorem|For each n≥3 there is N such that every planar set of at least N points in general position contains n points in convex position. The 1935 proof gives N≤binom(2n−4,n−2)+1.|convex-position planar-general-position finite-ramsey klein-five-points erdos-szekeres-cups-caps
klein-five-points|theorem|Esther Klein's five-point theorem|Every set of five planar points in general position contains four points in convex position.|convex-position planar-general-position
monotone-gap-theorem|theorem|Monotone-gap selection theorem for points on a line|For r,s≥2, any binom(r+s−4,r−2)+1 distinct points on a line contain r points with nondecreasing consecutive gaps or s points with nonincreasing consecutive gaps.|euclidean-space binomial-coefficient
rooted-tree|definition|Rooted finitely branching tree|A rooted tree is a connected acyclic graph with a distinguished root. It is finitely branching if every vertex has finitely many children, meaning adjacent vertices one edge farther from the root.|
konig-infinity|theorem|König's infinity lemma|Every infinite rooted finitely branching tree has an infinite simple path starting at its root.|rooted-tree
''')

records('Topology / fair division', '''
simplex|definition|Geometric n-simplex|An n-simplex is conv(v₀,…,vₙ), where v₁−v₀,…,vₙ−v₀ are linearly independent. Its faces are the hulls of subsets of its vertices.|convex-hull
simplex-triangulation|definition|Triangulation of a geometric simplex|A triangulation of S is a finite collection of simplices covering S, closed under faces, such that any two members intersect in a common face or not at all.|simplex
barycentric-subdivision|definition|Barycentric subdivision|Vertices are the barycenters b(F) of nonempty faces F; a simplex corresponds to a chain F₀⊊···⊊Fₖ and has vertices b(F₀),…,b(Fₖ).|simplex-triangulation
sperner-labeling|definition|Sperner labeling of a triangulated simplex|For S=conv(v₀,…,vₙ), label each triangulation vertex by an element of {0,…,n}; a vertex on conv(vᵢ:i∈I) must have a label in I.|simplex-triangulation subset-coloring
sperner-lemma|theorem|Sperner's lemma|Every Sperner-labeled triangulation of an n-simplex has an odd number of elementary n-simplices carrying all n+1 labels. In particular there is at least one.|sperner-labeling involution-parity
dual-sperner-labeling|definition|Dual Sperner labeling on a barycentrically subdivided simplex|Label vertices of a barycentric subdivision of the standard simplex Δⁿ by {0,…,n}. On the boundary, the label of x must be an i with xᵢ=0; interior labels are unrestricted.|barycentric-subdivision
dual-sperner-lemma|theorem|Dual Sperner lemma for barycentric subdivisions|For m≥1, the m-fold barycentric subdivision of a simplex satisfying the dual zero-coordinate boundary labeling rule contains an elementary n-simplex with all n+1 labels.|dual-sperner-labeling sperner-lemma
bolzano-weierstrass|theorem|Bolzano–Weierstrass theorem in ℝᵈ|Every bounded sequence in ℝᵈ has a convergent subsequence. If all its terms lie in a closed set, the subsequential limit lies in that set.|euclidean-space sequence-limit
closed-preference-correspondence|definition|Closed preference correspondence with finite alternatives|For metric X and finite alternatives A, P:X→nonempty subsets of A is a closed preference correspondence if {x:a∈P(x)} is closed in X for every a∈A. Ties are allowed.|
envy-free-allocation|definition|Envy-free allocation of finitely many shares|An allocation is envy-free if each participant weakly prefers their own assigned share to every other share, evaluated at that same allocation.|finite-set
cake-division-theorem|theorem|Envy-free interval cake division theorem|For n participants and consecutive pieces of [0,1] parametrized by Δⁿ⁻¹, suppose preferred-piece sets are nonempty and closed and exclude empty pieces whenever a positive-length piece exists. Then some partition admits a bijection assigning every participant a preferred piece.|envy-free-allocation closed-preference-correspondence sperner-lemma barycentric-subdivision bolzano-weierstrass
rental-harmony|theorem|Su's rental harmony theorem|For n participants and rooms, let pᵢ≥0 and ∑pᵢ=R>0. Suppose preferred-room sets are nonempty and closed, and contain only free rooms whenever some room is free. Then some price vector admits a bijection assigning every participant a preferred room.|envy-free-allocation closed-preference-correspondence dual-sperner-lemma bolzano-weierstrass
chore-division-theorem|theorem|Envy-free division of an interval of chores|For n participants and consecutive chore pieces parametrized by Δⁿ⁻¹, suppose preferred-piece sets are nonempty and closed and contain only empty pieces whenever an empty piece is available. Then there is a partition and bijection assigning each participant a preferred piece.|rental-harmony
brouwer-fixed-point|theorem|Brouwer fixed-point theorem|Every continuous f:Δⁿ→Δⁿ has a fixed point. The equivalent closed-ball formulation belongs to this same theorem concept.|simplex fixed-point sperner-lemma
''')

records('Probability / integration', '''
sigma-algebra|definition|σ-algebra|A σ-algebra on Ω contains Ω and is closed under complements in Ω and countable unions.|
measure|definition|Measure|A measure μ maps a σ-algebra to [0,∞], sends ∅ to 0, and satisfies μ(⋃ₙAₙ)=∑ₙμ(Aₙ) for every pairwise disjoint sequence of measurable sets.|sigma-algebra nonnegative-series
lebesgue-integral|definition|Lebesgue integral|For measurable f≥0, ∫f dμ is the supremum of integrals of nonnegative simple functions below f. For signed f with ∫abs(f)dμ<∞, define ∫f=∫f⁺−∫f⁻.|measure
probability-space|definition|Probability space|A probability space is (Ω,𝔽,P), where 𝔽 is a σ-algebra on Ω and P is a measure on 𝔽 with P(Ω)=1.|measure
real-random-variable|definition|Real-valued random variable|A real-valued random variable is a measurable map from a probability space to ℝ with its Borel σ-algebra.|probability-space real-number
distribution|definition|Distribution of a real random variable|The distribution μₓ of X is defined by μₓ(B)=P(X∈B) for Borel B⊆ℝ.|real-random-variable
expectation|definition|Expectation of an integrable real random variable|If E abs(X)=∫abs(X)dP<∞, the expectation of X is EX=∫X dP.|real-random-variable lebesgue-integral
variance|definition|Variance of a real random variable|If EX²<∞, then Var(X)=E[(X−EX)²].|expectation
pairwise-independence|definition|Pairwise independent random variables|A family (Xᵢ) is pairwise independent if P(Xᵢ∈A,Xⱼ∈B)=P(Xᵢ∈A)P(Xⱼ∈B) for all i≠j and Borel A,B⊆ℝ.|real-random-variable
independent-family|definition|Independent family of random variables|For distinct i₁,…,iₖ and Borel A₁,…,Aₖ, independence requires P(⋂ⱼ{Xᵢⱼ∈Aⱼ})=∏ⱼP(Xᵢⱼ∈Aⱼ).|real-random-variable
identically-distributed|definition|Identically distributed random variables|A family is identically distributed when all its random variables have the same distribution.|distribution
almost-sure-convergence|definition|Almost-sure convergence of real random variables|Xₙ→X almost surely means P({ω:limₙXₙ(ω)=X(ω)})=1.|real-random-variable sequence-limit
chebyshev-inequality|theorem|Chebyshev's inequality|If EX²<∞ and t>0, then P(abs(X−EX)≥t)≤Var(X)/t².|variance
borel-cantelli-first|theorem|First Borel–Cantelli lemma|If ∑ₙP(Aₙ)<∞, then P(⋂ₘ⋃ₙ≥ₘAₙ)=0: almost surely only finitely many Aₙ occur.|probability-space real-series
monotone-convergence|theorem|Monotone convergence theorem for Lebesgue integrals|If 0≤fₙ≤fₙ₊₁ and fₙ→f pointwise, then ∫fₙdμ increases to ∫f dμ, allowing infinity.|lebesgue-integral sequence-limit
etemadi-strong-law|theorem|Etemadi's strong law of large numbers|If (Xₙ) is pairwise independent and identically distributed with E abs(X₁)<∞, then (X₁+···+Xₙ)/n→EX₁ almost surely.|pairwise-independence identically-distributed expectation almost-sure-convergence chebyshev-inequality borel-cantelli-first monotone-convergence cesaro-lemma
kolmogorov-strong-law|theorem|Kolmogorov's strong law for iid real random variables|If (Xₙ) is jointly independent and identically distributed with E abs(X₁)<∞, then (X₁+···+Xₙ)/n→EX₁ almost surely.|independent-family etemadi-strong-law
kolmogorov-maximal|theorem|Kolmogorov's maximal inequality|If X₁,…,Xₙ are independent with EXᵢ=0 and EXᵢ²<∞, then for λ>0, P(max₁≤ₖ≤ₙ abs(∑ᵢ≤ₖXᵢ)≥λ)≤(∑ᵢ≤ₙVar(Xᵢ))/λ².|independent-family variance
rectangular-average|definition|Rectangular average of a real random array|For positive integer indices, the rectangular average at (n₁,…,nᵣ) is (∏ⱼnⱼ)⁻¹∑₁≤ᵢⱼ≤ₙⱼXᵢ₁,…,ᵢᵣ. Its joint limit means that every nⱼ tends to infinity.|real-random-variable integer
log-moment|definition|L(log L)ᵏ moment condition|X∈L(log L)ᵏ means E[abs(X)(log⁺abs(X))ᵏ]<∞, where log⁺t=max(0,log t) for t>0 and log⁺0=0.|expectation integer
divisor-function|definition|Divisor function d(n)|d(n) is the number of positive divisors of n, equivalently the number of ordered positive integer pairs (a,b) satisfying ab=n.|integer
divisor-summatory-bound|theorem|Divisor summatory bound ∑ₙ≤ₓd(n)=O(x log x)|There is an absolute constant C such that ∑₁≤ₙ≤ₓd(n)≤Cx log x for x≥2; the sum counts positive integer pairs (a,b) with ab≤x.|divisor-function real-number
abel-summation|theorem|Abel's summation formula|If Aₖ=∑ⱼ₌₁ᵏaⱼ, then ∑ₖ₌₁ᴺaₖbₖ=A_N b_N+∑ₖ₌₁ᴺ⁻¹Aₖ(bₖ−bₖ₊₁).|real-sequence
etemadi-array-law|theorem|Etemadi's strong law for random arrays|For an r-indexed pairwise independent identically distributed real array with E[abs(X)(log⁺abs(X))ʳ⁻¹]<∞, its rectangular averages converge almost surely to EX as every side length tends to infinity.|etemadi-strong-law rectangular-average log-moment divisor-summatory-bound abel-summation
''')


def link(source, role, locator, slugs, note=''):
    for slug in slugs.split():
        LINKS.append(dict(source=source, concept=slug, role=role, locator=locator, note=note))


link('zagier-1990','relies_on','p. 144','prime congruence finite-involution fixed-point involution-parity')
link('zagier-1990','explains','p. 144, displayed map','zagier-involution')
link('zagier-1990','explains','p. 144','fermat-two-squares','Proves the nontrivial p≡1 mod 4 direction of the full named theorem.')
link('niven-1947','relies_on','p. 509','integer-polynomial factorial factorial-growth derivative riemann-integral fundamental-calculus integration-by-parts rational-number pi sine')
link('niven-1947','explains','p. 509','pi-irrational')
link('erdos-szekeres-1935','relies_on','Introduction and first proof, pp. 463–464','convex-hull convex-position planar-general-position subset-coloring homogeneous-set')
link('erdos-szekeres-1935','explains','First proof, pp. 464–467','ramsey-number finite-simple-graph clique independent-set')
link('erdos-szekeres-1935','explains','First proof, pp. 464–467','finite-ramsey')
link('erdos-szekeres-1935','explains','Introduction, p. 463','klein-five-points')
link('erdos-szekeres-1935','relies_on','Second proof, pp. 467–470','monotone-subsequence cup-cap binomial-coefficient')
link('erdos-szekeres-1935','explains','Second proof, pp. 467–468','erdos-szekeres-monotone','The stored statement uses distinct entries and strict monotonicity; the paper also permits equal ordinates with weak comparisons.')
link('erdos-szekeres-1935','explains','Second proof, pp. 468–469','monotone-gap-theorem','A descriptive title for a precisely stated intermediate result, not a standard eponym.')
link('erdos-szekeres-1935','explains','Second proof, pp. 469–470','erdos-szekeres-cups-caps')
link('erdos-szekeres-1935','explains','Both proofs, pp. 463–470','erdos-szekeres-convex')
link('erdos-szekeres-1935','relies_on','Final paragraph, p. 470','konig-infinity','The alternative existence argument is mentioned rather than proved in detail.')
link('su-1999','explains','§§1–2','simplex simplex-triangulation sperner-labeling')
link('su-1999','explains','§2','sperner-lemma')
link('su-1999','relies_on','§§3–4','barycentric-subdivision closed-preference-correspondence envy-free-allocation bolzano-weierstrass')
link('su-1999','explains','§§3–4','cake-division-theorem')
link('su-1999','explains','§7','dual-sperner-labeling')
link('su-1999','explains','§7','dual-sperner-lemma rental-harmony')
link('su-1999','explains','§8','chore-division-theorem')
link('su-1999','discusses','§1','brouwer-fixed-point','A named application is mentioned; its proof is not given in this paper.')
link('etemadi-1981','relies_on','Theorem 1, pp. 119–120','real-random-variable expectation variance pairwise-independence identically-distributed almost-sure-convergence chebyshev-inequality borel-cantelli-first monotone-convergence cesaro-lemma')
link('etemadi-1981','explains','Theorem 1, pp. 119–120','etemadi-strong-law')
link('etemadi-1981','discusses','Opening paragraph','kolmogorov-strong-law kolmogorov-maximal','Contrasted with Etemadi; neither is an input to his proof.')
link('etemadi-1981','relies_on','Theorem 2 and Remark 1, pp. 120–121','rectangular-average log-moment divisor-function divisor-summatory-bound abel-summation')
link('etemadi-1981','explains','Theorem 2 and Remark 1, pp. 120–121','etemadi-array-law')

PROOF_ROUTES = {
 'fermat-two-squares':('zagier-1990','p. 144','Zagier compares two involutions on the same finite solution set; prime factorisation isolates one fixed point.'),
 'pi-irrational':('niven-1947','p. 509','Niven uses a factorial-scaled polynomial integral with integral endpoint derivatives and a vanishing positive upper bound.'),
 'erdos-szekeres-convex':('erdos-szekeres-1935','Both proofs, pp. 463–470','The graph records inputs to both the Ramsey proof and the cups–caps proof; a chosen route need not use all alternatives.'),
 'erdos-szekeres-cups-caps':('erdos-szekeres-1935','pp. 469–470','The ordered-slope definitions and binomial threshold specify the cup-or-cap conclusion.'),
 'erdos-szekeres-monotone':('erdos-szekeres-1935','pp. 467–468','The conclusion specifies increasing or decreasing subsequences of explicit lengths.'),
 'monotone-gap-theorem':('erdos-szekeres-1935','pp. 468–469','The intermediate distance statement uses a line, weak comparisons, and a binomial threshold.'),
 'klein-five-points':('erdos-szekeres-1935','p. 463','The hull of the five points yields a four-point subset in convex position.'),
 'finite-ramsey':('erdos-szekeres-1935','pp. 464–467','The finite theorem is stated and proved for homogeneous subsets of uniform colorings.'),
 'sperner-lemma':('su-1999','§2','Su pairs trap-door paths; boundary endpoints and fully labeled cells are compared modulo two.'),
 'dual-sperner-lemma':('su-1999','§7','The stated barycentric case is translated to ordinary Sperner labels by simplex duality.'),
 'cake-division-theorem':('su-1999','§§3–4','Fully labeled cells encode distinct choices at nearby partitions; pass to a convergent subsequence with a fixed finite assignment.'),
 'rental-harmony':('su-1999','§§6–7','Use the dual boundary convention for nonnegative prices, then take a limit of compatible assignments.'),
 'chore-division-theorem':('su-1999','§8','Suppress room attributes and interpret the rent coordinates as divisible chore amounts.'),
 'etemadi-strong-law':('etemadi-1981','Theorem 1, pp. 119–120','Truncate the variables, control centered sums on geometric subsequences, and interpolate nonnegative partial sums.'),
 'etemadi-array-law':('etemadi-1981','Theorem 2 and Remark 1, pp. 120–121','Use geometric rectangles and divisor multiplicity estimates to repeat the scalar proof.'),
 'kolmogorov-strong-law':('etemadi-1981','Opening comparison','This comparison route derives the iid theorem from Etemadi because joint independence implies pairwise independence; it is not an input to Etemadi.'),
}


def main():
    bibliography=json.loads((ROOT/'data/sources.json').read_text())
    slugs={c['slug'] for c in CONCEPTS}
    assert len(slugs)==len(CONCEPTS)
    assert all(e['prerequisite'] in slugs for e in EDGES)
    assert all(l['concept'] in slugs for l in LINKS)
    titles={c['slug']:c['title'] for c in CONCEPTS}
    for e in EDGES:
        e['rationale']=f"{titles[e['dependent']]} uses {titles[e['prerequisite']]} in its definition or the chosen account."
        if e['dependent'] in PROOF_ROUTES:
            source, locator, reason=PROOF_ROUTES[e['dependent']]
            e.update(source=source,locator=locator,rationale=reason)
    aliases={'fermat-two-squares':["Fermat's sum-of-two-squares theorem"],
             'erdos-szekeres-convex':['Happy ending theorem'],
             'brouwer-fixed-point':['Brouwer fixed-point theorem for a closed ball']}
    for c in CONCEPTS: c['aliases']=aliases.get(c['slug'],[])
    payload=dict(note='Concepts v7: short definitions and significant theorem statements. Proof maneuvers are source notes, not concept records.',
                 concepts=CONCEPTS, dependencies=EDGES, source_concepts=LINKS, **bibliography)
    author_batch=ROOT/'data/author-papers.json'
    if author_batch.exists():
        extra=json.loads(author_batch.read_text())
        for key in ['concepts','dependencies','source_concepts','sources','source_relations']:
            payload[key].extend(extra[key])
        payload['note']+=' Includes draft extractions from the G₂ and non-cyclotomic fusion category papers.'
    layer_batch=ROOT/'data/one-layer-batch.json'
    if layer_batch.exists():
        extra=json.loads(layer_batch.read_text())
        for key in ['concepts','dependencies','source_concepts','sources','source_relations']:
            payload[key].extend(extra[key])
        payload['note']+=' Includes one frozen layer of prerequisites for the non-cyclotomic paper.'
    coverage_batch = ROOT/'data/coverage-example.json'
    if coverage_batch.exists():
        extra=json.loads(coverage_batch.read_text())
        payload['source_concepts'].extend(extra['source_concepts'])
        payload['related_concepts']=extra['related_concepts']
    citation_batch = ROOT/'data/citations-example.json'
    if citation_batch.exists():
        payload['citations']=json.loads(citation_batch.read_text())['citations']
    recursive_plan = ROOT/'data/recursive-expansion.json'
    if recursive_plan.exists():
        from curate_recursive import merge_into_seed
        merge_into_seed(payload,json.loads(recursive_plan.read_text()))
    attribution = ROOT/'data/source-attribution-review.json'
    if attribution.exists():
        from curate_attribution import project
        project(payload,json.loads(attribution.read_text()))
    collection_review = ROOT/'data/full-review-plan.json'
    if collection_review.exists():
        from curate_full_review import project as project_review
        project_review(payload,json.loads(collection_review.read_text()))
    from curate_dependency_purposes import project as project_purposes
    project_purposes(payload)
    from contextlib import closing
    import mathdb as m
    with closing(m.connect(':memory:')) as db:
        m.initialize(db);m.ingest(db,payload)
        removed={x['edge']['id'] for x in m.reduction_plan(db)['removed']}
        names={r['id']:r['slug'] for r in db.execute('SELECT id,slug FROM concept')}
        retained={(names[e['prerequisite_id']],names[e['dependent_id']]) for e in db.execute('SELECT * FROM concept_dependency') if e['id'] not in removed}
        payload['dependencies']=[e for e in payload['dependencies'] if (e['prerequisite'],e['dependent']) in retained]
    # A boundary is a node whose own prerequisites are not expanded in this graph.
    expanded={e['dependent'] for e in payload['dependencies']}
    for concept in payload['concepts']:
        concept['boundary']=concept['slug'] not in expanded
    (ROOT/'data/seed.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'concepts':len(payload['concepts']),'dependencies':len(payload['dependencies']),'occurrences':len(payload['source_concepts']),
                      'types':{k:sum(c['kind']==k for c in payload['concepts']) for k in ['definition','theorem','construction']}}))


if __name__=='__main__': main()
