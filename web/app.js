'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const compare = (a,b) => a.title.localeCompare(b.title);
const state = {data:null,etag:null,kind:'concept',slug:'fusion-category',query:'',moreUp:false,moreDown:false,view:'neighbors',mode:'statement'};
let graphObserver,toastTimer;
const api = '/api/v1/';
// The public site (Cloudflare Worker) serves one slice of the collection per view
// and searches the sidebar on the server; it is read-only. Locally, ?public
// exercises the same mode against mathdb_server.py.
const PUBLIC_SITE = document.documentElement.classList.contains('public-site') || new URLSearchParams(location.search).has('public');
if(PUBLIC_SITE)document.documentElement.classList.add('public-site');
const viewCache = new Map();
let viewRequest = 0, searchTimer;
const shortKind = value => value[0].toUpperCase()+value.slice(1);
const flag = (done,label) => `<span class="pill dot ${done?'':'pending'}">${esc(label)}: ${done?'complete':'awaiting review'}</span>`;
const routeButton = (kind,slug,label,cls='',extra='') => `<button class="${cls}" data-action="navigate" data-kind="${kind}" data-slug="${esc(slug)}" ${extra}>${label}</button>`;
function toast(message){const el=$('#toast');el.textContent=message;el.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.hidden=true,4200);}
function authorNames(source){try{const names=Array.isArray(source.authors)?source.authors:JSON.parse(source.authors);return Array.isArray(names)?names:typeof names==='string'?[names]:[];}catch{return typeof source.authors==='string'?[source.authors]:[];}}
function entities(kind=state.kind){return (kind==='concept'?state.data.concept.filter(c=>c.status==='active'):state.data.source).slice().sort(compare);}
function current(){return entities().find(c=>c.slug===state.slug);}
function byId(kind,id){return (kind==='concept'?state.data.concept:state.data.source).find(c=>c.id===id);}
function occurrences(sourceId,conceptId){return state.data.source_concept.filter(l=>(!sourceId||l.source_id===sourceId)&&(!conceptId||l.concept_id===conceptId)&&byId('concept',l.concept_id)?.status==='active');}
function identifierURL(scheme,value){
  if(scheme==='doi')return 'https://doi.org/'+value;
  if(scheme==='arxiv')return 'https://arxiv.org/abs/'+value;
  if(scheme==='isbn')return 'https://search.worldcat.org/search?q=bn%3A'+encodeURIComponent(value);
  if(scheme==='zbl')return 'https://zbmath.org/?q=an%3A'+encodeURIComponent(value);
  if(scheme==='url'&&/^https?:\/\//i.test(value))return value;
  return null;
}
function identifierLink(i){const url=identifierURL(i.scheme,i.value);return url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(i.scheme)}: ${esc(i.value)} ↗</a>`:`<span>${esc(i.scheme)}: ${esc(i.value)}</span>`;}
async function getJSON(path){
  const response=await fetch(api+path);
  if(!response.ok){const error=new Error(response.status===404?'Record not found':'Could not load the collection.');error.status=response.status;throw error;}
  return response.json();
}
async function loadView(){
  const key=state.kind+'/'+state.slug,request=++viewRequest;
  let result=viewCache.get(key);
  if(!result){
    try{result=await getJSON('view/'+state.kind+'/'+encodeURIComponent(state.slug));}
    catch(error){if(error.status!==404)throw error;result={data:{concept:[],source:[]},formalizations:[]};}
    if(viewCache.size>50)viewCache.delete(viewCache.keys().next().value);
    viewCache.set(key,result);
  }
  if(request!==viewRequest)return false;
  state.data=result.data;state.formalizations=result.formalizations;return true;
}
async function loadList(){
  const result=await getJSON('search?'+new URLSearchParams({kind:state.kind,q:state.query,limit:'200'}));
  state.list=result.items;state.listTotal=result.total;state.listKind=state.kind;
}
async function refreshPublic(){
  const tasks=[loadView()];
  if(state.listKind!==state.kind)tasks.push(loadList());
  const [current]=await Promise.all(tasks);
  if(current)render();
}
async function load(){
  if(PUBLIC_SITE){
    const stats=await getJSON('stats');
    $('#stats').textContent=`${stats.active_concepts} concepts · ${stats.sources} sources`;
    $('#collection-label').textContent='Public collection';
    await refreshPublic();return;
  }
  const response=await fetch(api+'state');if(!response.ok)throw new Error('Could not open the database.');
  const result=await response.json();state.etag=response.headers.get('ETag');state.data=result.data;state.formalizations=result.formalizations;
  $('#stats').textContent=`${result.stats.active_concepts} concepts · ${result.stats.sources} sources`;
  render();
}
function navigate(kind,slug,view=state.view){
  const fromDrawer=mobileNavigation.matches&&$('.sidebar').classList.contains('open');
  const target=`#${kind}/${encodeURIComponent(slug)}${kind==='concept'?'?'+new URLSearchParams({view,mode:state.mode}):''}`;
  if(location.hash===target){state.kind=kind;state.slug=slug;state.view=view;render();}else location.hash=target;
  setNavigation(false,{restoreFocus:false});
  if(fromDrawer)$('#main').focus({preventScroll:true});
}
function parseRoute(){
  const [path,query='']=location.hash.split('?'),match=path.match(/^#(concept|source)\/([^?]+)$/),params=new URLSearchParams(query);
  if(match){try{state.kind=match[1];state.slug=decodeURIComponent(match[2]);state.view=params.get('view')==='cone'?'cone':'neighbors';state.mode=params.get('mode')==='proof'?'proof':'statement';}catch{state.slug='';}}
  state.moreUp=false;state.moreDown=false;
  if(PUBLIC_SITE){if(state.listKind&&state.listKind!==state.kind){state.query='';$('#search').value='';}if(state.listKind!==undefined)refreshPublic().catch(showError);return;}
  state.query='';$('#search').value='';
  if(state.data)render();
}
function renderNavigation(){
  for(const kind of ['concept','source'])$(`#${kind}-tab`).setAttribute('aria-selected',String(state.kind===kind));
  $('#search').placeholder=state.kind==='concept'?'Find a concept…':'Find a source…';$('#search').setAttribute('aria-label',`Search ${state.kind}s`);
  $('#add-record').textContent=`+ Add ${state.kind}`;
  const list=PUBLIC_SITE?(state.list||[]):entities().filter(c=>[c.title,c.description,c.field,...(state.kind==='source'?authorNames(c):state.data.concept_alias.filter(a=>a.concept_id===c.id).map(a=>a.alias))].join(' ').toLocaleLowerCase().includes(state.query.toLocaleLowerCase()));
  $('#list-count').textContent=PUBLIC_SITE&&state.listTotal>list.length?`${list.length} of ${state.listTotal} ${state.kind}s`:`${PUBLIC_SITE?state.listTotal??0:list.length} ${state.kind}s`;
  $('#record-list').innerHTML=list.map(c=>routeButton(state.kind,c.slug,`<strong>${esc(c.title)}</strong><small>${state.kind==='concept'?esc(c.field):esc([authorNames(c).join(', '),c.year].filter(Boolean).join(' · '))}</small>`,`record-item${c.slug===state.slug?' selected':''}`,c.slug===state.slug?'aria-current="true"':'')).join('')||'<p class="empty-search">No matching records.<br>Try another name or field.</p>';
  MathText.render($('#record-list'));
}
function render(){
  if(!state.data)return;
  graphObserver?.disconnect();ConeView.destroy();renderNavigation();
  $('#record-list [aria-current="true"]')?.scrollIntoView({block:'nearest'});
  const record=current();
  if(!record){$('#main').innerHTML='<div class="error-page"><h1>Record not found</h1><p>Choose a concept or source from the collection.</p></div>';return;}
  document.title=record.title+' · The Shape of Math';
  $('#main').innerHTML=state.kind==='concept'?renderConcept(record):renderSource(record);
  MathText.render($('#main'));
  if(state.kind==='concept'&&state.view==='cone'){ConeView.mount();}
  else if(state.kind==='concept'){requestAnimationFrame(drawConnections);graphObserver=new ResizeObserver(drawConnections);graphObserver.observe($('.graph'));}
}
function neighborNode(concept,edge,direction){
 return `<div class="graph-node" data-node="${esc(concept.id)}" data-direction="${direction}">${routeButton('concept',concept.slug,`<strong>${esc(concept.title)}</strong><small>${esc(concept.kind)} · <span>${esc(edge.purpose)}</span></small>`,'node-main',`title="${esc(edge.rationale)}"`)}<div class="node-actions"><button class="text-button" data-action="edit-edge" data-id="${edge.id}">Edit dependency</button><button class="remove-link" data-action="remove-edge" data-id="${edge.id}" aria-label="Remove dependency involving ${esc(concept.title)}" title="Remove dependency">×</button></div></div>`;
}
function renderConcept(c){
  const up=state.data.concept_dependency.filter(e=>e.prerequisite_id===c.id&&ConeView.includes(e,state.mode)).map(e=>({edge:e,c:byId('concept',e.dependent_id)})).sort((a,b)=>compare(a.c,b.c));
  const down=state.data.concept_dependency.filter(e=>e.dependent_id===c.id&&ConeView.includes(e,state.mode)).map(e=>({edge:e,c:byId('concept',e.prerequisite_id)})).sort((a,b)=>compare(a.c,b.c));
  function neighbors(items,direction){const more=direction==='up'?state.moreUp:state.moreDown;return items.length?`<div class="node-grid">${items.slice(0,more?items.length:6).map(x=>neighborNode(x.c,x.edge,direction)).join('')}</div>${items.length>6?`<button class="more-button" data-action="expand" data-direction="${direction}">${more?'Show fewer':`Show all ${items.length}`}</button>`:''}`:`<div class="graph-empty">${direction==='up'?'No dependents recorded yet.':ConeView.complete(c,state.mode)?'The empty prerequisite list has been reviewed.':'No prerequisites recorded yet. This list has not been certified complete.'}</div>`;}
  const links=occurrences(null,c.id);
  function sourceCards(role){const ids=[...new Set(links.filter(l=>l.role===role).map(l=>l.source_id))];return ids.map(id=>{const source=byId('source',id);const locations=[...new Set(links.filter(l=>l.source_id===id&&l.role===role).map(l=>l.locator))];return routeButton('source',source.slug,`<strong>${esc(source.title)}</strong><small>${esc(authorNames(source).join(', '))}${source.year?' · '+source.year:''}<br>${esc(locations.join('; '))}</small>`,'source-card');}).join('')||'<p class="context-empty">No source recorded.</p>';}
  const related=state.data.concept_related.filter(r=>r.concept_a_id===c.id||r.concept_b_id===c.id);
  return `<div class="page-topline"><div class="breadcrumbs">Collection <span>/</span> Concepts</div><span class="eyebrow">${esc(c.field)}</span></div>
  <div class="title-row"><div><h1>${esc(c.title)}</h1><p class="subtitle">${state.view==='cone'?'Explore every recorded prerequisite, with shared concepts shown once.':'Explore its immediate mathematical neighborhood.'}</p></div><div class="heading-actions"><div class="view-switch" role="group" aria-label="Prerequisite purpose"><button data-action="mode-statement" aria-pressed="${state.mode==='statement'}">Statement</button><button data-action="mode-proof" aria-pressed="${state.mode==='proof'}">Proof</button></div><div class="view-switch" role="group" aria-label="Concept graph view"><button data-action="view-neighbors" aria-pressed="${state.view!=='cone'}">Neighborhood</button><button data-action="view-cone" aria-pressed="${state.view==='cone'}">Entire cone</button></div><button class="quiet-button" data-action="edit-concept">Edit concept</button></div></div>
  ${state.view!=='cone'?`<section class="concept-summary" aria-label="Selected concept statement"><span class="eyebrow">${esc(c.kind)}</span><p>${esc(c.description)}</p><button class="text-button" data-action="review">${ConeView.complete(c,state.mode)?'Prerequisite coverage certified':'Review prerequisite coverage'}</button></section>`:''}
  <div class="concept-layout ${state.view==='cone'?'cone-layout':''}">${state.view==='cone'?ConeView.markup(state.data,c,state.mode):`<section class="graph-panel" aria-label="Concept dependency graph"><div class="panel-topbar"><strong>The local picture</strong><span>Click a concept to move through the map</span></div><div class="graph"><svg class="connections" aria-hidden="true"></svg>
  <section class="graph-section"><div class="section-label"><span>Things that rely on this <span class="counter">${up.length}</span></span><button class="text-button" data-action="add-edge" data-direction="up">+ Dependent</button></div>${neighbors(up,'up')}</section>
  <div class="focus-wrap"><article class="focus-node" id="focus-node"><div class="eyebrow">${esc(c.kind)} · Selected concept</div><h2>${esc(c.title)}</h2><div class="focus-foot"><span>${ConeView.complete(c,state.mode)?'Immediate prerequisite coverage certified':'Prerequisite coverage not certified'}</span><button data-action="review">Review</button></div></article></div>
  <section class="graph-section"><div class="section-label"><span>Prerequisites <span class="counter">${down.length}</span></span><button class="text-button" data-action="add-edge" data-direction="down">+ Prerequisite</button></div>${neighbors(down,'down')}</section></div>
  <div class="graph-footer"><span><span class="legend-arrow">↑</span> Prerequisite → dependent</span><span>One step in either direction</span></div></section>`}
  <aside class="context-sidebar">${renderFormalizations(c)}${purposeFrontiers(c)}<section class="context-block"><h2 class="context-title">Introduced in <button class="text-button" data-action="add-occurrence" data-role="introduces">+ Link</button></h2>${sourceCards('introduces')}</section>
  <section class="context-block"><h2 class="context-title">Explained in <button class="text-button" data-action="add-occurrence" data-role="explains">+ Link</button></h2>${sourceCards('explains')}</section>
  <section class="context-block"><h2 class="context-title">Needed by <button class="text-button" data-action="add-occurrence" data-role="relies_on">+ Link</button></h2>${sourceCards('relies_on')}</section>
  <section class="context-block"><h2 class="context-title">Related concepts <button class="text-button" data-action="add-related">+ Link</button></h2>${related.map(r=>{const neighbor=byId('concept',r.concept_a_id===c.id?r.concept_b_id:r.concept_a_id);return routeButton('concept',neighbor.slug,`${esc(neighbor.title)} <span>${esc(r.rationale)}</span>`,'context-link');}).join('')||'<p class="context-empty">No related concepts recorded. These links have no prerequisite direction.</p>'}</section></aside></div>`;
}
const locNumber = value => Number(value).toLocaleString(undefined,{maximumFractionDigits:1});
const formalizationStatus = status => ({formalized:'Formalized',partial:'Partially formalized',inherited:'Available through dependency',not_formalized:'Not formalized (reviewed)',unknown:'Unknown / awaiting review'}[status]);
function formalizationFileLabel(file){
 const parts=file.path.split('/'),name=parts.pop();
 const label=`<span class="file-name">${esc(name)}${file.url?' <span aria-hidden="true">↗</span>':''}</span>${parts.length?`<span class="file-directory">${parts.map(esc).join('/<wbr>')}/</span>`:''}`;
 return file.url?`<a class="formalization-file-link" href="${esc(file.url)}" title="${esc(file.path)}" aria-label="${esc(file.path)}" target="_blank" rel="noopener noreferrer">${label}</a>`:`<span class="formalization-file-link" title="${esc(file.path)}">${label}</span>`;
}
function renderFormalizations(c){
 const reviews=state.formalizations.filter(r=>r.concept_id===c.id);
 return `<section class="context-block formalizations"><h2 class="context-title">Formalization <button class="text-button" data-action="add-library">+ Library</button></h2>
 <p class="context-empty">Native files implementing definitions, theorems and their core API. Dependency code is counted in its owning library. Whole-file lines are shared evenly.</p>
 ${reviews.map(r=>`<article class="formalization-review"><div class="formalization-heading"><strong>${esc(r.library_name)}</strong><button class="text-button" data-action="edit-formalization" data-library="${esc(r.library)}">Review / edit</button></div>
 <p class="formalization-status">${esc(c.kind==='conjecture'&&r.status==='formalized'?'Formal statement recorded':formalizationStatus(r.status))}${r.review_needed?' · concept changed since review':''}</p>
 ${c.kind==='conjecture'?'<p class="context-empty">Coverage concerns the conjecture’s formal statement. This record does not claim a proof.</p>':''}
 ${['formalized','partial'].includes(r.status)?`<p class="loc-estimate">${r.estimated_loc!==null?`≈ ${locNumber(r.estimated_loc)} LOC`:`LOC estimate incomplete · ${r.measured_files}/${r.file_count} files counted`}${r.estimated_loc===null&&r.measured_files?`<small>${locNumber(r.known_loc)} LOC from counted files</small>`:''}${r.status==='partial'?'<small>Estimate covers the recorded partial implementation.</small>':''}</p>`:''}
 ${r.status==='inherited'?'<p class="loc-estimate">0 native LOC<small>Provided by a checked dependency; no native files assigned.</small></p>':''}
 ${r.evidence?`<details class="formalization-evidence"><summary>Review evidence</summary><p>${esc(r.evidence)}</p><small>Reviewed ${esc(r.reviewed_at)}</small></details>`:''}
 ${r.files.length?`<ul class="formalization-files">${r.files.map(f=>`<li>${formalizationFileLabel(f)}<small>${f.loc===null?'File LOC unknown':`${locNumber(f.loc)} lines${f.allocated_loc===null?'':` ÷ ${f.mapped_concepts} concept${f.mapped_concepts===1?'':'s'} ≈ ${locNumber(f.allocated_loc)} LOC`}`}</small><details class="formalization-file-evidence"><summary>Contribution and declarations</summary><p>${esc(f.note)}</p>${f.declarations?`<small>${esc(f.declarations)}</small>`:''}${f.revision?`<small title="${esc(f.revision)}">Revision: ${esc(f.revision.slice(0,12))} · ${esc(f.measured_at)}</small>`:''}</details><button class="text-button" data-action="measure-file" data-id="${f.id}">Record file count</button></li>`).join('')}</ul>`:''}</article>`).join('')}</section>`;
}
function formalizationForm(library){
 const c=current(),r=state.formalizations.find(r=>r.concept_id===c.id&&r.library===library);
 let next=0;
 function fileFields(f={}){const i=next++;return `<fieldset class="formalization-file-fields" data-index="${i}"><legend>Implementing file</legend>${field('file-path-'+i,'Repository file path',f.path||'',{required:false,help:'A .lean file that defines, proves or develops the concept’s API.'})}${field('file-declarations-'+i,'Declarations',f.declarations||'',{required:false,help:'Optional names of definitions or theorems.'})}${field('file-note-'+i,'What does this file implement?',f.note||'',{required:false,textarea:true,rows:2})}<button type="button" class="text-button" data-remove-formalization-file>Remove file</button></fieldset>`;}
 openForm('Formalization in '+r.library_name,
 field('status','Status',r.status,{choices:['unknown','formalized','partial','inherited','not_formalized'].map(v=>[v,formalizationStatus(v)])})+
 field('evidence','What was checked?',r.evidence||'',{textarea:true,help:'Compare the actual declaration and hypotheses with this concept. For a negative review, describe the search and revision inspected.'})+
 `<div id="formalization-file-editor"><div id="formalization-file-list">${(r.files.length?r.files:[{}]).map(fileFields).join('')}</div><button type="button" class="text-button" id="add-formalization-file">+ Add implementing file</button></div>`+reasonField(),v=>{
 const files=['formalized','partial'].includes(v.get('status'))?[...$('#editor').querySelectorAll('.formalization-file-fields')].map(el=>{const i=el.dataset.index;return {path:v.get('file-path-'+i),declarations:v.get('file-declarations-'+i),note:v.get('file-note-'+i)};}):[];
 return mutate('concepts/'+encodeURIComponent(c.slug)+'/formalizations/'+encodeURIComponent(library),'POST',{status:v.get('status'),evidence:v.get('evidence'),files,reason:v.get('reason')});
 });
 function update(){const enabled=['formalized','partial'].includes($('#field-status').value);$('#formalization-file-editor').hidden=!enabled;for(const el of $('#editor').querySelectorAll('.formalization-file-fields input,.formalization-file-fields textarea')){el.disabled=!enabled;el.required=enabled&&!el.name.startsWith('file-declarations-');}}
 $('#field-status').addEventListener('change',update);
 $('#add-formalization-file').addEventListener('click',()=>{$('#formalization-file-list').insertAdjacentHTML('beforeend',fileFields());update();});
 $('#formalization-file-list').addEventListener('click',e=>{if(e.target.closest('[data-remove-formalization-file]'))e.target.closest('fieldset').remove();});
 update();
}
function formalizationFileForm(id){
 const f=state.data.formalization_file.find(f=>f.id===Number(id));
 openForm('File line count',`<p class="form-note">${esc(f.path)}. This count is shared by every mapped concept in this library. Count physical lines, including comments and blank lines.</p>`+
 field('loc','Whole-file lines',f.loc??'',{type:'number',required:false,help:'Leave blank to clear an outdated count.'})+
 field('revision','Repository revision',f.revision||'',{required:false,help:'Use the inspected commit hash for a reproducible count.'})+reasonField(),v=>{
 const loc=v.get('loc')===''?null:Number(v.get('loc'));
 return mutate('formalization-files','POST',{library:f.library_slug,path:f.path,loc,revision:loc===null?null:v.get('revision'),reason:v.get('reason')});
 });
 const update=()=>{$('#field-revision').required=$('#field-loc').value!=='';};$('#field-loc').addEventListener('input',update);update();
}
function formalizationLibraryForm(){
 openForm('Add a formalization library',field('slug','Library identifier','',{help:'Lowercase letters, digits and hyphens; for example my-library.'})+field('name','Library name')+
 field('repository_url','Repository URL','',{required:false,help:'Optional GitHub-compatible repository URL, used for links to files at their measured revision.'})+reasonField(),v=>mutate('formalization-libraries','POST',{slug:v.get('slug'),name:v.get('name'),repository_url:v.get('repository_url')||null,reason:v.get('reason')}));
}

function purposeFrontiers(c){
 const graph=ConeView.collect(state.data,c.id,state.mode);
 function panel(edges,title){return edges.length?`<section class="context-block"><h2 class="context-title">${title}</h2>${edges.map(e=>{const p=byId('concept',e.prerequisite_id),d=byId('concept',e.dependent_id);return `<div class="context-empty">${routeButton('concept',p.slug,esc(p.title),'context-link')}<small>Needed by ${esc(d.title)}</small> <button class="text-button" data-action="edit-edge" data-id="${e.id}">Classify / edit</button></div>`;}).join('')}</section>`:'';}
 return panel(graph.unclassified,'Dependencies awaiting classification')+(state.mode==='statement'?panel(graph.proofFrontier,'Proof prerequisites · not expanded'):'');
}
function editEdge(id){const e=state.data.concept_dependency.find(e=>e.id===Number(id));openForm('Edit dependency',field('purpose','Needed for',e.purpose,{choices:[['statement','Understanding the statement / definition'],['proof','Understanding the proof'],['both','Both'],['unclassified','Not classified yet']]})+field('rationale','Mathematical reason',e.rationale,{textarea:true})+reasonField(),v=>mutate('dependencies/'+e.id,'PATCH',{purpose:v.get('purpose'),rationale:v.get('rationale'),reason:v.get('reason')}));}
function drawConnections(){
  const graph=$('.graph'),focus=$('#focus-node'),svg=$('.connections');if(!graph||!focus||!svg)return;
  const bounds=graph.getBoundingClientRect(),f=focus.getBoundingClientRect();svg.setAttribute('viewBox',`0 0 ${bounds.width} ${bounds.height}`);
  let paths='<defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" fill="#8fa588"/></marker></defs>';
  // Each column has a collector in a clear gutter. Branches enter the
  // sides of cards, so no connection can disappear behind another card.
  for(const node of graph.querySelectorAll('.graph-node')){
    const n=node.getBoundingClientRect(),up=node.dataset.direction==='up';
    const grid=node.closest('.node-grid').getBoundingClientRect(),right=n.left>grid.left+grid.width/2;
    const x=(right?n.right:n.left)-bounds.left,y=n.top+n.height/2-bounds.top,lane=x+(right?12:-12);
    const fx=f.left+f.width/2-bounds.left,fy=(up?f.top:f.bottom)-bounds.top,rail=fy+(up?-22:22);
    const d=up?`M ${fx} ${fy} V ${rail} H ${lane} V ${y} H ${x}`:`M ${x} ${y} H ${lane} V ${rail} H ${fx} V ${fy}`;
    paths+=`<path data-node="${esc(node.dataset.node)}" d="${d}" fill="none" stroke="#9caf94" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round" marker-end="url(#arrow)"/>`;
  }
  svg.innerHTML=paths;
}
function sourceRequirements(sourceId){
 const links=occurrences(sourceId,null).filter(l=>l.role==='relies_on'),candidates=new Set(links.map(l=>l.concept_id)),cones=new Map(),covered=new Set(),all=new Set();
 for(const id of candidates){const cone=ConeView.collect(state.data,id);cones.set(id,cone);for(const n of cone.nodes){all.add(n.id);if(n.id!==id)covered.add(n.id);}}
 const direct=new Set([...candidates].filter(id=>!covered.has(id)));
 const inherited=[...all].filter(id=>!direct.has(id)).map(id=>({concept:byId('concept',id),via:[...direct].filter(root=>cones.get(root).nodes.some(n=>n.id===id)).map(root=>byId('concept',root).title),links:links.filter(l=>l.concept_id===id)})).sort((a,b)=>compare(a.concept,b.concept));
 return {direct,inherited};
}
function renderSource(source){
 const needs=sourceRequirements(source.id),links=occurrences(source.id,null),citations=state.data.citation.filter(c=>c.source_id===source.id),identifiers=state.data.source_identifier.filter(i=>i.source_id===source.id);
 function conceptList(role,title){const list=links.filter(l=>l.role===role&&(role!=='relies_on'||needs.direct.has(l.concept_id))).sort((a,b)=>compare(byId('concept',a.concept_id),byId('concept',b.concept_id)));return `<section class="list-panel"><div class="list-panel-head"><h2>${title}<small>${new Set(list.map(l=>l.concept_id)).size}</small></h2><button class="text-button" data-action="add-occurrence" data-role="${role}">+ Add concept</button></div>${list.map(l=>{const c=byId('concept',l.concept_id);return `<div class="concept-row">${routeButton('concept',c.slug,`<strong>${esc(c.title)}</strong><p>${esc(c.description)}</p><small>${esc(l.locator)}</small>${l.role==='introduces'?`<p class="origin-evidence">${esc(l.introduction_evidence)}</p>`:''}`)}<div class="row-actions"><button data-action="edit-occurrence" data-id="${l.id}" aria-label="Edit link to ${esc(c.title)}">Edit</button></div></div>`;}).join('')||`<div class="list-empty">${role==='introduces'?(source.introductions_complete?'No concepts or results introduced; this list has been reviewed.':'No introductions recorded. Original-contribution review is incomplete.'):'No required concepts recorded yet.'}</div>`}</section>`;}
 return `<div class="page-topline"><div class="breadcrumbs">Collection <span>/</span> Sources</div><span class="pill neutral">${esc(source.status)}</span></div><div class="title-row"><div><h1>${esc(source.title)}</h1><p class="subtitle">${esc(authorNames(source).join(' · '))}${source.year?' · '+source.year:''}</p></div><div class="heading-actions"><button class="quiet-button" data-action="edit-source">Edit source</button></div></div>
 ${source.summary?`<p class="source-intro">${esc(source.summary)}</p>`:''}<div class="source-links">${identifiers.map(identifierLink).join('')}<button class="text-button" data-action="add-identifier">+ Identifier</button></div>
 <div class="review-strip">${flag(source.requirements_complete,'Reading concepts')}${flag(source.introductions_complete,'Introduced concepts')}${flag(source.citations_complete,'Citations')}<button class="text-button" data-action="review">Review lists</button></div>
 <p class="coverage-note">${esc(source.coverage)}</p><div class="concept-columns">${conceptList('relies_on','Concepts it needs')}${conceptList('introduces','Concepts it introduces')}</div>
 ${needs.inherited.length?`<details class="source-detail-block"><summary>Inherited prerequisites (${needs.inherited.length})</summary><p class="form-note">Brought in through the required concepts above; shared background is listed once.</p>${needs.inherited.map(item=>`<div class="concept-row">${routeButton('concept',item.concept.slug,`<strong>${esc(item.concept.title)}</strong><small>Via ${esc(item.via.join('; '))}</small>`)}${item.links.map(l=>`<div class="row-actions"><button data-action="edit-occurrence" data-id="${l.id}" title="${esc(l.locator)}">Edit recorded occurrence</button></div>`).join('')}</div>`).join('')}</details>`:''}
 ${links.some(l=>l.role==='explains')?`<details class="source-detail-block"><summary>Explanations and other proofs (${new Set(links.filter(l=>l.role==='explains').map(l=>l.concept_id)).size})</summary><p class="form-note">Useful locations for learning these concepts. These are separate from original-source attribution.</p>${conceptList('explains','Concepts explained here')}</details>`:''}
 ${links.some(l=>l.role==='discusses')?`<section class="context-block"><h2 class="context-title">Also discussed</h2>${links.filter(l=>l.role==='discusses').map(l=>{const c=byId('concept',l.concept_id);return routeButton('concept',c.slug,esc(c.title),'context-link');}).join('')}</section>`:''}
 <section class="citation-section"><div class="section-heading"><h2>Citations<span class="small-count">${citations.length}</span></h2><div class="actions">${citations.length?'<button class="text-button" data-action="resolve-citations">Match identifiers</button>':''}<button class="text-button" data-action="add-citation">+ Add citation</button></div></div>
 ${citations.length?citations.map((citation,i)=>{const ids=state.data.citation_identifier.filter(x=>x.citation_id===citation.id),target=citation.cited_source_id?byId('source',citation.cited_source_id):null;return `<article class="citation-row"><div class="citation-number">${String(i+1).padStart(2,'0')}</div><div>${citation.label?`<div class="citation-label">${esc(citation.label)}</div>`:''}<p class="citation-text">${esc(citation.text)}</p><div class="citation-meta"><span class="pill ${citation.pedagogically_necessary===null?'neutral':citation.pedagogically_necessary?'':'no'}">Pedagogically necessary: ${citation.pedagogically_necessary===null?'unknown':citation.pedagogically_necessary?'yes':'no'}</span>${ids.map(identifierLink).join('')}${target?routeButton('source',target.slug,'View source →','text-button'):''}</div>${citation.needed_material?`<p class="citation-needed"><strong>Needed material:</strong> ${esc(citation.needed_material)}</p>`:''}</div><button class="citation-edit" data-action="edit-citation" data-id="${citation.id}" aria-label="Edit citation ${esc(citation.label||i+1)}">Edit</button></article>`;}).join(''):`<p class="context-empty">${source.citations_complete?'The bibliography has been reviewed and has no recorded entries.':'No bibliography has been captured yet.'}</p>`}</section>
 ${source.dependency_review?`<section class="source-summary-footer"><h3>Source dependency review</h3><p>${esc(source.dependency_review)}</p></section>`:''}
 ${renderCitedBy(source)}`;
}
function renderCitedBy(source){const citations=state.data.citation.filter(c=>c.cited_source_id===source.id);if(!citations.length)return '';return `<section class="context-block"><h2 class="context-title">Cited by</h2>${citations.map(c=>{const s=byId('source',c.source_id);return routeButton('source',s.slug,esc(s.title),'context-link');}).join('')}</section>`;}
function field(name,label,value='',options={}){
 const attrs=`name="${name}" id="field-${name}" ${options.required===false?'':'required'} ${options.help?`aria-describedby="help-${name}"`:''}`;
 let control;
 if(options.choices)control=`<select ${attrs}>${options.choices.map(x=>{const [v,t]=Array.isArray(x)?x:[x,x];return `<option value="${esc(v)}" ${String(value)===String(v)?'selected':''}>${esc(t)}</option>`;}).join('')}</select>`;
 else if(options.textarea)control=`<textarea ${attrs} rows="${options.rows||3}" ${options.maxlength?`maxlength="${options.maxlength}"`:''}>${esc(value)}</textarea>`;
 else control=`<input ${attrs} type="${options.type||'text'}" value="${esc(value)}" ${options.maxlength?`maxlength="${options.maxlength}"`:''}>`;
 return `<div class="form-field"><label for="field-${name}">${esc(label)}</label>${control}${options.help?`<span class="help" id="help-${name}">${esc(options.help)}</span>`:''}</div>`;
}
const reasonField=()=>field('reason','Reason for this edit','',{textarea:true,rows:2,help:'Saved in the collection’s curation history.'});
const conceptOptions=(exclude)=>entities('concept').filter(c=>c.id!==exclude).map(c=>[c.slug,c.title]);
const sourceOptions=()=>entities('source').map(s=>[s.slug,s.title]);
function openForm(title,body,onSave,button='Save changes',extra=''){
 setNavigation(false,{restoreFocus:false});
 const dialog=$('#editor');dialog.innerHTML=`<div class="dialog-header"><h2 id="dialog-title">${esc(title)}</h2><button type="button" class="icon-button" data-action="close-dialog" aria-label="Close dialog">×</button></div><form class="editor-form"><div class="form-body">${body}<div class="form-error" role="alert" hidden></div></div><div class="form-footer">${extra}<button type="button" class="secondary-button" data-action="close-dialog">Cancel</button><button type="submit" class="primary-button">${esc(button)}</button></div></form>`;
 if(!dialog.open)dialog.showModal();
 const form=dialog.querySelector('form');
 form.addEventListener('submit',async event=>{event.preventDefault();const submit=form.querySelector('[type=submit]'),error=form.querySelector('.form-error');submit.disabled=true;error.hidden=true;
 try{await onSave(new FormData(form));dialog.close();await load();toast('Saved to the collection.');}catch(ex){error.textContent=ex.message;error.hidden=false;if(ex.status===412){const reload=document.createElement('button');reload.type='button';reload.className='text-button';reload.textContent='Close this draft and reload the latest collection';reload.addEventListener('click',()=>{dialog.close();load().catch(showError);});error.append(document.createElement('br'),reload);}}finally{submit.disabled=false;}});
}
async function mutate(path,method,payload){
 const response=await fetch(api+path,{method,headers:{'Content-Type':'application/json','If-Match':state.etag},body:JSON.stringify(payload)});
 const result=await response.json();if(!response.ok){const error=new Error(result.error||'Could not save this edit.');error.status=response.status;throw error;}return result.result;
}
function editConcept(create=false){const c=create?{}:current();openForm(create?'Add a concept':'Edit concept',
 field('title','Name',c.title||'',{maxlength:200})+(create?field('slug','Stable short identifier','',{help:'For example: fusion-category. This becomes its URL.'}):'')+
 `<div class="form-row">${field('kind','Kind',c.kind||'definition',{choices:['definition','theorem','construction','conjecture']})}${field('field','Field',c.field||'')}</div>`+
 field('description','Definition or theorem statement',c.description||'',{textarea:true,rows:5,maxlength:1500,help:'One short paragraph. Necessary qualifications belong here or in the name.'})+reasonField(),async values=>{
 const item={title:values.get('title'),kind:values.get('kind'),field:values.get('field'),description:values.get('description'),reason:values.get('reason')};if(create)item.slug=values.get('slug');
 await mutate('concepts'+(create?'':'/'+encodeURIComponent(c.slug)),create?'POST':'PATCH',item);if(create){state.slug=item.slug;location.hash='#concept/'+encodeURIComponent(item.slug);}},create?'Add concept':'Save changes');if(create)autoSlug();}
function autoSlug(){const title=$('#field-title'),slug=$('#field-slug');let edited=false;slug.addEventListener('input',()=>edited=true);title.addEventListener('input',()=>{if(!edited)slug.value=title.value.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');});}
function editSource(create=false){const s=create?{}:current();openForm(create?'Add a source':'Edit source',
 field('title','Title',s.title||'')+(create?field('slug','Stable short identifier',''):'')+field('authors','Authors (one per line)',s.authors?authorNames(s).join('\n'):'',{textarea:true,rows:2,required:false})+
 `<div class="form-row">${field('year','Year',s.year||'',{type:'number',required:false})}${field('field','Field',s.field||'')}</div>`+
 (create?`<div class="form-row">${field('scheme','Identifier type','doi',{choices:['doi','arxiv','isbn','zbl','url']})}${field('identifier','Identifier','')}</div>`:field('status','Ingestion status',s.status,{choices:['catalogued','draft','reviewed']}))+
 field('summary','Short summary',s.summary||'',{textarea:true,required:false})+field('coverage','Parts inspected',s.coverage||'',{textarea:true,required:false})+reasonField(),async values=>{
 const item={title:values.get('title'),authors:values.get('authors').split('\n').map(x=>x.trim()).filter(Boolean),year:values.get('year')?Number(values.get('year')):null,field:values.get('field'),summary:values.get('summary'),coverage:values.get('coverage'),status:create?'draft':values.get('status'),reason:values.get('reason')};
 if(create){item.slug=values.get('slug');item.identifiers=[[values.get('scheme'),values.get('identifier')]];item.dependency_review='Not yet reviewed.';}
 await mutate('sources'+(create?'':'/'+encodeURIComponent(s.slug)),create?'POST':'PATCH',item);if(create){state.slug=item.slug;location.hash='#source/'+encodeURIComponent(item.slug);}},create?'Add source':'Save changes');if(create)autoSlug();}
function review(){const r=current(),isConcept=state.kind==='concept';const flags=isConcept?[['statement_prerequisites_complete','All immediate statement prerequisites are recorded'],...(['theorem','conjecture'].includes(r.kind)?[['proof_prerequisites_complete','All direct prerequisites for the proof are recorded']]:[])]:[['requirements_complete','All concepts needed to read this source are recorded'],['introductions_complete','All concepts this source introduces are recorded'],['citations_complete','All bibliography entries have been captured as text']];
 openForm('Review completeness','<p class="form-note">These judgments are independent. They do not certify completion further down the prerequisite graph.</p>'+flags.map(([key,label])=>`<label class="form-check"><input type="checkbox" name="${key}" ${r[key]?'checked':''}>${esc(label)}</label>`).join('')+reasonField(),values=>mutate('reviews','POST',{kind:state.kind,slug:r.slug,changes:Object.fromEntries(flags.map(([key])=>[key,values.has(key)])),reason:values.get('reason')}),'Record review');}
function addEdge(direction){const c=current();openForm(direction==='down'?'Add a prerequisite':'Add a dependent',
 field('other',direction==='down'?'Prerequisite concept':'Dependent concept','',{choices:conceptOptions(c.id)})+
 field('purpose','Needed for','statement',{choices:[['statement','Understanding the statement / definition'],['proof','Understanding the proof'],['both','Both'],['unclassified','Not classified yet']]})+
 field('basis','Dependency basis','both',{choices:[['both','Logical and pedagogical'],['logical','Logical'],['pedagogical','Pedagogical']]})+
 field('rationale','Why is this a prerequisite?','',{textarea:true})+
 field('source','Evidence source','',{required:false,choices:[['','No specific source'],...sourceOptions()]})+field('locator','Location in source','',{required:false}),values=>mutate('dependencies','POST',{
 prerequisite:direction==='down'?values.get('other'):c.slug,dependent:direction==='down'?c.slug:values.get('other'),purpose:values.get('purpose'),basis:values.get('basis'),rationale:values.get('rationale'),source:values.get('source')||null,locator:values.get('locator')||null,reason:values.get('rationale')}),'Add dependency');}
function removeLink(type,id,title){openForm(title,'<p class="form-note">This removes the link. The mathematical concept and source records remain in the collection.</p>'+reasonField(),values=>mutate(type+'/'+id,'DELETE',{reason:values.get('reason')}),'Remove link');}
function addRelated(){const c=current();openForm('Link related concepts',field('other','Related concept','',{choices:conceptOptions(c.id)})+field('rationale','What connects these concepts?','',{textarea:true,help:'A connection without a prerequisite direction.'}),values=>mutate('related','POST',{concept_a:c.slug,concept_b:values.get('other'),rationale:values.get('rationale'),reason:values.get('rationale')}),'Add related link');}
function occurrenceForm(role,id=null){const old=id?state.data.source_concept.find(l=>l.id===Number(id)):null,isConcept=state.kind==='concept',selected=current();openForm(old?'Edit concept–source link':'Link a concept and source',
 (old?'':isConcept?field('source','Source','',{choices:sourceOptions()}):field('concept','Concept','',{choices:conceptOptions()}))+
 field('role','Relationship',old?.role||role,{choices:[['relies_on','Source relies on the concept'],['introduces','Source originally introduces the concept'],['explains','Source explains the concept or gives another proof'],['discusses','Source discusses the concept']]})+
 field('locator','Where in the source?',old?.locator||'')+field('introduction_evidence','Evidence of an original contribution',old?.introduction_evidence||'',{textarea:true,required:false,help:'Check predecessor attribution. A numbered definition or another proof of a known theorem is not evidence of originality.'})+field('note','Notes',old?.note||'',{textarea:true,required:false})+reasonField(),async values=>{
 const item={role:values.get('role'),locator:values.get('locator'),note:values.get('note'),introduction_evidence:values.get('role')==='introduces'?(values.get('introduction_evidence')||''):'',reason:values.get('reason')};
 if(!old){item.source=isConcept?values.get('source'):selected.slug;item.concept=isConcept?selected.slug:values.get('concept');}
 return mutate('source-concepts'+(old?'/'+old.id:''),old?'PATCH':'POST',item);
 },'Save link',old?`<button type="button" class="text-button" data-action="remove-occurrence" data-id="${old.id}">Remove link</button>`:'');
 const select=$('#field-role'),evidence=$('#field-introduction_evidence');
 const update=()=>{const needed=select.value==='introduces';evidence.required=needed;evidence.disabled=!needed;evidence.closest('.form-field').hidden=!needed;};
 select.addEventListener('change',update);update();} 
function citationForm(id=null){const old=id?state.data.citation.find(c=>c.id===Number(id)):null,source=current(),ids=old?state.data.citation_identifier.filter(i=>i.citation_id===old.id):[];openForm(old?'Edit citation':'Add a citation',
 field('label','Printed citation label',old?.label||'',{required:false})+field('text','Original reference text',old?.text||'',{textarea:true,rows:4})+
 field('necessary','Pedagogically necessary?',old?.pedagogically_necessary===null||!old?'unknown':old.pedagogically_necessary?'yes':'no',{choices:[['unknown','Unknown / not reviewed'],['yes','Yes'],['no','No']]})+
 field('needed_material','What do we need from this citation?',old?.needed_material||'',{textarea:true,required:false,help:'For example: Theorem 2.3, existence part only.'})+
 field('identifiers','Identifiers',ids.map(i=>i.scheme+' '+i.value).join('\n'),{textarea:true,rows:2,required:false,help:'One per line: doi 10.1234/example. Explicit identifiers in the reference text are also extracted.'})+
 field('cited_source','Link to an existing source',old?.cited_source_id?byId('source',old.cited_source_id).slug:'',{choices:[['','Unresolved / match identifiers'],...sourceOptions()],required:false})+reasonField(),values=>{
 const pairs=values.get('identifiers').split('\n').filter(x=>x.trim()).map(line=>{const match=line.trim().match(/^(doi|arxiv|isbn|zbl|url)\s+(.+)$/i);if(!match)throw new Error('Use “scheme value” for each identifier, for example “arxiv 1002.0168”.');return [match[1],match[2]];});
 const item={label:values.get('label')||null,text:values.get('text'),pedagogically_necessary:{yes:true,no:false,unknown:null}[values.get('necessary')],needed_material:values.get('needed_material')||null,identifiers:pairs,cited_source:values.get('cited_source')||null,reason:values.get('reason')};if(!old)item.source=source.slug;
 return mutate('citations'+(old?'/'+old.id:''),old?'PATCH':'POST',item);
 },'Save citation',old?`<button type="button" class="text-button" data-action="remove-citation" data-id="${old.id}">Remove citation</button>`:'');}
function addIdentifier(){const s=current();openForm('Add a source identifier',field('scheme','Identifier type','doi',{choices:['doi','arxiv','isbn','zbl','url']})+field('value','Identifier','')+reasonField(),values=>mutate('sources/'+encodeURIComponent(s.slug)+'/identifiers','POST',{scheme:values.get('scheme'),value:values.get('value'),reason:values.get('reason')}),'Add identifier');}
async function showHistory(before=null){const response=await fetch(api+'history?limit=20'+(before?'&before='+before:''));if(!response.ok)throw new Error('Could not load history.');const events=await response.json(),dialog=$('#editor');dialog.innerHTML=`<div class="dialog-header"><h2 id="dialog-title">Curation history</h2><button class="icon-button" data-action="close-dialog" aria-label="Close history">×</button></div><div class="dialog-body"><p class="form-note">Every edit records its reason and the data before and after the change.</p>${events.map(e=>`<article class="history-event"><strong>${esc(e.reason)}</strong><small>${esc(new Date(e.occurred_at).toLocaleString())} · ${esc(e.operation.replaceAll('_',' '))} · #${e.id}</small><a href="/api/v1/history/${e.id}" target="_blank" rel="noopener">Inspect change ↗</a></article>`).join('')||'<p class="form-note">No earlier events.</p>'}${events.length===20?`<button class="more-button" data-action="older-history" data-id="${events.at(-1).id}">Earlier events</button>`:''}</div>`;if(!dialog.open)dialog.showModal();}
async function reduceCone(){
 const response=await fetch(api+'concepts/'+encodeURIComponent(state.slug)+'/reduction');const plan=await response.json();
 if(!response.ok)throw new Error(plan.error||'Could not inspect the cone.');
 if(!plan.removed.length){toast('This prerequisite cone is already transitively reduced.');return;}
 const names=new Map(state.data.concept.map(c=>[c.slug,c.title]));
 const examples=plan.removed.slice(0,6).map(x=>`<li>${x.path.map(slug=>esc(names.get(slug)||slug)).join(' → ')}</li>`).join('');
 openForm('Reduce redundant links',`<p class="form-note">Remove ${plan.removed.length} direct links that also have indirect prerequisite paths. Every concept remains reachable. Original edges and their evidence stay in the curation history; existing reviews are preserved.</p><ul class="reduction-paths">${examples}</ul>`+reasonField(),values=>mutate('reductions','POST',{root:state.slug,reason:values.get('reason')}),'Reduce links');
}
function showError(error){toast(error.message||String(error));}
document.addEventListener('click',async event=>{const button=event.target.closest('[data-action]');if(!button)return;const {action,id,direction,role}=button.dataset;try{
 if(action==='navigate')navigate(button.dataset.kind,button.dataset.slug);
 else if(action==='view-cone')navigate('concept',state.slug,'cone');
 else if(action==='mode-statement'||action==='mode-proof'){state.mode=action==='mode-proof'?'proof':'statement';navigate('concept',state.slug,state.view);}
 else if(action==='edit-edge')editEdge(id);
 else if(action==='view-neighbors')navigate('concept',state.slug,'neighbors');
 else if(action==='cone-display')ConeView.setDisplay(button.dataset.display);else if(action==='cone-fit')ConeView.fit();else if(action==='cone-readable')ConeView.readable();
 else if(action==='cone-outline-expand')ConeView.outlineLevels(true);
 else if(action==='cone-outline-collapse')ConeView.outlineLevels(false);
 else if(action==='cone-outline-top')ConeView.jumpToLevel(0);
 else if(action==='cone-in')ConeView.zoom(1.3);else if(action==='cone-out')ConeView.zoom(1/1.3);
 else if(action==='cone-download')ConeView.download(state.slug);else if(action==='reduce-cone')await reduceCone();
 else if(action==='expand'){state[direction==='up'?'moreUp':'moreDown']=!state[direction==='up'?'moreUp':'moreDown'];render();}
 else if(action==='edit-concept')editConcept();else if(action==='edit-source')editSource();
 else if(action==='edit-formalization')formalizationForm(button.dataset.library);
 else if(action==='measure-file')formalizationFileForm(id);
 else if(action==='add-library')formalizationLibraryForm();
 else if(action==='review')review();else if(action==='add-edge')addEdge(direction);
 else if(action==='remove-edge')removeLink('dependencies',id,'Remove dependency');
 else if(action==='add-related')addRelated();else if(action==='add-occurrence')occurrenceForm(role);
 else if(action==='edit-occurrence')occurrenceForm(null,id);else if(action==='remove-occurrence')removeLink('source-concepts',id,'Remove concept–source link');
 else if(action==='add-citation')citationForm();else if(action==='edit-citation')citationForm(id);
 else if(action==='remove-citation')removeLink('citations',id,'Remove citation');
 else if(action==='add-identifier')addIdentifier();else if(action==='close-dialog')$('#editor').close();
 else if(action==='older-history')await showHistory(id);
 else if(action==='resolve-citations'){await mutate('citations/resolve','POST',{source:current().slug,reason:'Match explicit citation identifiers to the current source catalogue'});await load();toast('Citation identifiers matched against the collection.');}
 }catch(error){showError(error);}});
$('#search').addEventListener('input',event=>{state.query=event.target.value;
 if(!PUBLIC_SITE){renderNavigation();return;}
 clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadList().then(renderNavigation).catch(showError),200);});
for(const kind of ['concept','source'])$(`#${kind}-tab`).addEventListener('click',()=>{state.query='';$('#search').value='';const slug=kind===state.kind?state.slug:kind==='concept'?'fusion-category':'morrison-g2-2011';navigate(kind,PUBLIC_SITE||entities(kind).some(r=>r.slug===slug)?slug:entities(kind)[0]?.slug||'');});
$('#add-record').addEventListener('click',()=>state.kind==='concept'?editConcept(true):editSource(true));
$('#refresh-button').addEventListener('click',()=>load().then(()=>toast('Collection refreshed.')).catch(showError));
$('#history-button').addEventListener('click',()=>showHistory().catch(showError));
const mobileNavigation=matchMedia('(max-width: 720px)');
let navigationReturnFocus=null;
function setNavigation(open,{restoreFocus=true}={}){
 const sidebar=$('.sidebar'),wasOpen=sidebar.classList.contains('open'),modal=open&&mobileNavigation.matches;
 if(modal&&!wasOpen)navigationReturnFocus=document.activeElement;
 sidebar.classList.toggle('open',modal);
 $('#toggle-nav').setAttribute('aria-expanded',String(modal));
 $('#nav-backdrop').hidden=!modal;
 $('#main').inert=modal;$('.masthead-right').inert=modal;$('.brand').inert=modal;
 sidebar.inert=mobileNavigation.matches&&!modal;
 if(open)$('#search').focus({preventScroll:true});
 else if(wasOpen&&restoreFocus){
  const target=navigationReturnFocus?.isConnected&&navigationReturnFocus.matches('button,a[href],input,select,textarea,[tabindex]')&&navigationReturnFocus.getClientRects().length?navigationReturnFocus:$('#toggle-nav');
  target.focus({preventScroll:true});
 }
}
$('#toggle-nav').addEventListener('click',()=>setNavigation(!$('.sidebar').classList.contains('open')));
$('#nav-backdrop').addEventListener('click',()=>setNavigation(false));
document.addEventListener('pointerdown',event=>{
 if(mobileNavigation.matches&&$('.sidebar').classList.contains('open')&&!event.target.closest('.sidebar,#toggle-nav')){
  event.preventDefault();setNavigation(false);
 }
});
document.addEventListener('keydown',event=>{
 if($('#editor').open)return;
 const open=mobileNavigation.matches&&$('.sidebar').classList.contains('open');
 if(open&&event.key==='Escape'){event.preventDefault();setNavigation(false);return;}
 if(open&&event.key==='Tab'){
  const controls=[$('#toggle-nav'),...$('.sidebar').querySelectorAll('button:not([disabled]),input,a[href]')].filter(el=>el.getClientRects().length);
  const index=controls.indexOf(document.activeElement);
  if(index<0||(!event.shiftKey&&index===controls.length-1)||(event.shiftKey&&index===0)){
   event.preventDefault();(event.shiftKey?controls.at(-1):controls[0]).focus();
  }
 }
 if(event.key==='/'&&!/INPUT|TEXTAREA|SELECT/.test(event.target.tagName)){event.preventDefault();setNavigation(true);}
});
mobileNavigation.addEventListener('change',()=>{
 const wasInside=$('.sidebar').contains(document.activeElement);
 setNavigation(false,{restoreFocus:false});
 if(wasInside&&mobileNavigation.matches)$('#toggle-nav').focus({preventScroll:true});
});
window.addEventListener('hashchange',()=>{setNavigation(false,{restoreFocus:false});parseRoute();$('#main').scrollTop=0;});
setNavigation(false,{restoreFocus:false});
parseRoute();load().catch(error=>{$('#main').innerHTML=`<div class="error-page"><h1>Could not open the collection</h1><p>${esc(error.message)}</p><p>Check that the local database server is running.</p></div>`;});
