/* Full prerequisite DAGs: one node per concept, with shared ancestors preserved. */
window.ConeView=(()=>{
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let active=null;
 function includes(edge,mode){return mode==='all'||(mode==='statement'?['statement','both']:['statement','proof','both']).includes(edge.purpose);}
 function complete(node,mode){return mode==='statement'?!!node.statement_prerequisites_complete:!!node.statement_prerequisites_complete&&(!['theorem','conjecture'].includes(node.kind)||!!node.proof_prerequisites_complete);}
 function collect(data,rootId,mode='statement'){
  const all=new Map(data.concept.filter(c=>c.status==='active').map(c=>[c.id,c])),parents=new Map();
  const selected=data.concept_dependency.filter(e=>includes(e,mode));
  for(const edge of selected){if(!parents.has(edge.dependent_id))parents.set(edge.dependent_id,[]);parents.get(edge.dependent_id).push(edge);}
  const seen=new Set([rootId]),queue=[rootId];
  for(let i=0;i<queue.length;i++)for(const e of parents.get(queue[i])||[])if(!seen.has(e.prerequisite_id)){seen.add(e.prerequisite_id);queue.push(e.prerequisite_id);}
  const nodes=queue.map(id=>({...all.get(id),depth:0,coverage_complete:complete(all.get(id),mode)})),byId=new Map(nodes.map(n=>[n.id,n]));
  const edges=selected.filter(e=>seen.has(e.dependent_id)&&seen.has(e.prerequisite_id));
  const remaining=new Map(nodes.map(n=>[n.id,0]));for(const e of edges)remaining.set(e.prerequisite_id,remaining.get(e.prerequisite_id)+1);
  const ready=[rootId];for(let i=0;i<ready.length;i++){const child=byId.get(ready[i]);for(const e of parents.get(child.id)||[]){const p=byId.get(e.prerequisite_id);p.depth=Math.max(p.depth,child.depth+1);remaining.set(p.id,remaining.get(p.id)-1);if(!remaining.get(p.id))ready.push(p.id);}}
  if(ready.length!==nodes.length)throw new Error('The prerequisite graph contains a cycle.');
  return {nodes,edges,rootId,mode,unreviewed:nodes.filter(n=>!n.coverage_complete),unclassified:data.concept_dependency.filter(e=>seen.has(e.dependent_id)&&e.purpose==='unclassified'),proofFrontier:data.concept_dependency.filter(e=>seen.has(e.dependent_id)&&['proof','both'].includes(e.purpose)&&!seen.has(e.prerequisite_id))};
 }
 function layout(graph){
  const levels=[];for(const node of graph.nodes)(levels[node.depth]??=[]).push(node);
  const nodeWidth=244,nodeHeight=94,gap=28,step=140;
  const routes=new Map(),previous=new Map();
  // Reserve an empty slot at each skipped level. Long edges travel through
  // these slots instead of being drawn behind unrelated concept cards.
  for(const edge of graph.edges){
   const d=graph.nodes.find(n=>n.id===edge.dependent_id),p=graph.nodes.find(n=>n.id===edge.prerequisite_id);
   const route=[d];
   for(let depth=d.depth+1;depth<p.depth;depth++){
    const slot={id:`route-${edge.id}-${depth}`,depth,dummy:true};
    levels[depth].push(slot);route.push(slot);
   }
   route.push(p);routes.set(edge.id,route);
   for(let i=1;i<route.length;i++){
    if(!previous.has(route[i].id))previous.set(route[i].id,[]);
    previous.get(route[i].id).push(route[i-1]);
   }
  }
  const size=node=>node.dummy?12:nodeWidth;
  const rowWidth=level=>level.reduce((sum,node)=>sum+size(node),0)+Math.max(0,level.length-1)*gap;
  const width=Math.max(...levels.map(rowWidth))+48;
  for(let depth=0;depth<levels.length;depth++){
   const score=node=>{const children=previous.get(node.id)||[];return children.length?children.reduce((sum,n)=>sum+n.x+size(n)/2,0)/children.length:width/2;};
   levels[depth].sort((a,b)=>score(a)-score(b)||(a.title||a.id).localeCompare(b.title||b.id));
   let x=(width-rowWidth(levels[depth]))/2;
   for(const node of levels[depth]){node.x=x;node.y=24+depth*step;x+=size(node)+gap;}
  }
  return {...graph,width,height:48+(levels.length-1)*step+nodeHeight,nodeWidth,nodeHeight,routes};
 }
 function edgePath(graph,edge){
  const route=graph.routes.get(edge.id).slice().reverse(),center=n=>n.x+(n.dummy?6:graph.nodeWidth/2);
  let x=center(route[0]),y=route[0].y,path=`M ${x} ${y}`;
  for(const node of route.slice(1)){
   const nx=center(node),bottom=node.y+graph.nodeHeight,mid=(y+bottom)/2;
   path+=` C ${x} ${mid}, ${nx} ${mid}, ${nx} ${bottom}`;
   if(node.dummy)path+=` L ${nx} ${node.y}`;
   x=nx;y=node.y;
  }
  return path;
 }
 function outline(graph){
  const nodes=new Map(graph.nodes.map(n=>[n.id,n])),levels=[];
  for(const node of graph.nodes)(levels[node.depth]??=[]).push(node);
  const controls=`<nav class="cone-outline-nav" aria-label="Outline navigation"><label>Jump to level<select class="cone-outline-select" aria-label="Jump to outline level">${levels.map((level,depth)=>`<option value="${depth}">${depth===0?'Selected concept':`Level ${depth} · ${level.length} concept${level.length===1?'':'s'}`}</option>`).join('')}</select></label><div class="cone-outline-actions"><button class="text-button" data-action="cone-outline-expand">Expand all</button><button class="text-button" data-action="cone-outline-collapse">Collapse levels</button><button class="text-button" data-action="cone-outline-top">Back to start ↑</button></div></nav>`;
  return `<div class="cone-list" aria-label="Prerequisite outline">${controls}${levels.map((level,depth)=>`<details class="cone-list-level" data-depth="${depth}" ${depth<2?'open':''}><summary><span>${depth===0?'Selected concept':`Level ${depth}`}</span><small>${level.length} concept${level.length===1?'':'s'}</small></summary><div class="cone-level-content">${level.sort((a,b)=>a.title.localeCompare(b.title)).map(node=>{
   const inputs=graph.edges.filter(e=>e.dependent_id===node.id);
   const href=n=>`#concept/${encodeURIComponent(n.slug)}?view=cone&mode=${escape(graph.mode)}`;
   return `<article class="cone-list-node" data-concept-id="${escape(node.id)}"><a class="cone-list-title" href="${href(node)}">${escape(node.title)}</a><p>${escape(node.description)}</p><span class="pill ${node.coverage_complete?'':'pending'}">${node.coverage_complete?'Prerequisite coverage certified':'Prerequisite coverage not certified'}</span>${inputs.length?`<details><summary>${inputs.length} direct prerequisite${inputs.length===1?'':'s'}</summary><ul>${inputs.map(edge=>`<li><a href="${href(nodes.get(edge.prerequisite_id))}">${escape(nodes.get(edge.prerequisite_id).title)}</a> <small>${escape(edge.purpose)}</small></li>`).join('')}</ul></details>`:''}</article>`;
  }).join('')}</div></details>`).join('')}</div>`;
 }
 function lines(title){const result=[];let current='';for(const word of title.split(/\s+/)){if(current&&current.length+word.length>28){result.push(current);current=word;}else current+=(current?' ':'')+word;}if(current)result.push(current);if(result.length>3)return [...result.slice(0,2),result[2].slice(0,25)+'…'];return result;}
 function markup(data,root,mode='statement'){
  const graph=layout(collect(data,root.id,mode)),nodes=new Map(graph.nodes.map(n=>[n.id,n]));
  const paths=graph.edges.map(e=>{const p=nodes.get(e.prerequisite_id),d=nodes.get(e.dependent_id);return `<path class="cone-edge" data-edge-id="${e.id}" d="${edgePath(graph,e)}" fill="none" stroke="${e.purpose==='proof'?'#ac8859':'#a8b9a0'}" stroke-dasharray="${e.purpose==='proof'?'5 3':'none'}" stroke-width="1.4" marker-end="url(#cone-arrow)"><title>${escape(p.title)} → ${escape(d.title)} [${escape(e.purpose)}]: ${escape(e.rationale)}</title></path>`;}).join('');
  const boxes=graph.nodes.map(n=>{const selected=n.id===root.id;const label=lines(n.title);return `<a class="cone-node${selected?' cone-root':''}" data-concept-id="${escape(n.id)}" href="#concept/${encodeURIComponent(n.slug)}?view=cone&mode=${escape(mode)}" aria-label="${escape(n.title)}"><title>${escape(n.title)}\n${escape(n.description)}\n${n.coverage_complete?'Immediate prerequisite coverage certified':'Prerequisite coverage not certified'}</title><rect x="${n.x}" y="${n.y}" width="${graph.nodeWidth}" height="${graph.nodeHeight}" rx="7" fill="${selected?'#184b40':'#fffefb'}" stroke="${selected?'#184b40':n.coverage_complete?'#c3d2bc':'#c6aa79'}" stroke-width="1.3"/><circle cx="${n.x+graph.nodeWidth-12}" cy="${n.y+12}" r="3" fill="${selected?'#d1e2cf':n.coverage_complete?'#73936b':'#b38d4b'}"/>${label.map((line,i)=>`<text x="${n.x+12}" y="${n.y+22+i*16}" fill="${selected?'#fffefb':'#263c35'}" font-family="system-ui, sans-serif" font-size="13">${escape(line)}</text>`).join('')}<text x="${n.x+12}" y="${n.y+80}" fill="${selected?'#bad0c0':'#7b8476'}" font-family="system-ui, sans-serif" font-size="10">${escape(n.kind)} · ${n.coverage_complete?'coverage certified':'coverage not certified'}</text></a>`;}).join('');
  return `<section class="graph-panel cone-panel" data-display="${matchMedia('(max-width: 720px)').matches?'list':'diagram'}" aria-label="Entire prerequisite cone"><div class="panel-topbar"><div><strong>${mode==='statement'?'Statement prerequisites':'Statement and proof prerequisites'}</strong><span class="cone-stats">${graph.nodes.length} concepts · ${graph.edges.length} links · ${Math.max(...graph.nodes.map(n=>n.depth))} levels</span></div><div class="cone-controls"><div class="view-switch cone-display-switch" role="group" aria-label="Cone presentation"><button data-action="cone-display" data-display="diagram">Diagram</button><button data-action="cone-display" data-display="list">Outline</button></div><div class="cone-diagram-controls"><button class="quiet-button" data-action="cone-fit" title="See the whole graph">Fit all</button><button class="quiet-button" data-action="cone-readable" aria-label="View graph at 100 percent">100%</button><button class="quiet-button" data-action="cone-out" aria-label="Zoom out">−</button><span id="cone-zoom">100%</span><button class="quiet-button" data-action="cone-in" aria-label="Zoom in">+</button><button class="quiet-button" data-action="cone-download">Save SVG</button></div></div></div><p class="cone-description">${escape(root.description)}</p><p class="cone-hint">Drag to explore · Use Fit all for an overview</p><div class="cone-viewport" tabindex="0" role="region" aria-label="Prerequisite diagram. Drag to pan, scroll to zoom, or use the zoom controls."><svg class="cone-svg" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="All ${graph.nodes.length} concepts in the prerequisite cone" data-world-width="${graph.width}" data-world-height="${graph.height}" data-node-width="${graph.nodeWidth}" data-root-x="${nodes.get(root.id).x}" data-root-y="${nodes.get(root.id).y}"><defs><marker id="cone-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" fill="#91a88a"/></marker></defs><g class="cone-world">${paths}${boxes}</g></svg></div>${outline(graph)}<div class="cone-review-summary">${graph.unclassified.length?`<span class="pill pending">${graph.unclassified.length} dependencies need classification</span>`:''}${graph.unreviewed.length||graph.unclassified.length?`<span class="pill pending">${graph.unreviewed.length} concepts lack certified prerequisite coverage</span>`:'<span class="pill dot">Every immediate '+(mode==='statement'?'statement':'statement and proof')+' prerequisite list in this cone is certified complete</span>'}<button class="text-button" data-action="reduce-cone">Reduce redundant links</button></div><div class="graph-footer"><span><span class="legend-arrow">↑</span> Prerequisite → dependent · Shared concepts appear once</span><span>Drag to pan · Scroll to zoom · Click to recenter</span></div></section>`;
 }
 function paint(){if(!active)return;const {world,scale,x,y}=active;world.setAttribute('transform',`translate(${x} ${y}) scale(${scale})`);document.querySelector('#cone-zoom').textContent=Math.round(scale*100)+'%';}
 function fit(){if(!active)return;const a=active,w=a.viewport.clientWidth,h=a.viewport.clientHeight;a.view='fit';a.scale=Math.min(1,(w-36)/a.width,(h-36)/a.height);a.x=(w-a.width*a.scale)/2;a.y=(h-a.height*a.scale)/2;paint();}
 function zoom(factor,anchor){if(!active)return;const a=active,point=anchor||{x:a.viewport.clientWidth/2,y:a.viewport.clientHeight/2},scale=Math.max(.04,Math.min(3,a.scale*factor)),ratio=scale/a.scale;a.view='custom';a.x=point.x-(point.x-a.x)*ratio;a.y=point.y-(point.y-a.y)*ratio;a.scale=scale;paint();}
 function readable(){if(!active)return;const a=active;a.view='readable';a.scale=1;a.x=a.viewport.clientWidth/2-Number(a.svg.dataset.rootX)-Number(a.svg.dataset.nodeWidth)/2;a.y=28-Number(a.svg.dataset.rootY);paint();}
 function resize(){
  if(!active)return;const a=active,w=a.viewport.clientWidth,h=a.viewport.clientHeight,oldWidth=a.viewportWidth,oldHeight=a.viewportHeight;
  if(!w||!h)return;
  a.svg.setAttribute('viewBox',`0 0 ${w} ${h}`);a.viewportWidth=w;a.viewportHeight=h;
  if(!oldWidth||a.view==='readable')readable();else if(a.view==='fit')fit();
  else {a.x+=(w-oldWidth)/2;a.y+=(h-oldHeight)/2;paint();}
 }
 function mount(){destroy();const viewport=document.querySelector('.cone-viewport');if(!viewport)return;const svg=viewport.querySelector('svg');active={viewport,svg,world:svg.querySelector('.cone-world'),scale:1,x:0,y:0,view:'readable',width:Number(svg.dataset.worldWidth),height:Number(svg.dataset.worldHeight),userDisplay:false,media:matchMedia('(max-width: 720px)')};
  active.onMedia=event=>{if(!active.userDisplay)setDisplay(event.matches?'list':'diagram',false);};active.media.addEventListener('change',active.onMedia);
  active.observer=new ResizeObserver(resize);active.observer.observe(viewport);setDisplay(viewport.closest('.cone-panel').dataset.display,false);resize();let drag=null;
  const panel=viewport.closest('.cone-panel'),nav=panel.querySelector('.cone-outline-nav');
  active.outlineObserver=new ResizeObserver(outlineInsets);active.outlineObserver.observe(nav);
  panel.querySelector('.cone-outline-select').addEventListener('change',event=>jumpToLevel(event.target.value));
  viewport.addEventListener('wheel',event=>{event.preventDefault();const rect=viewport.getBoundingClientRect();zoom(Math.exp(-event.deltaY*.002),{x:event.clientX-rect.left,y:event.clientY-rect.top});},{passive:false});
  viewport.addEventListener('pointerdown',event=>{if(event.target.closest('a')||event.button!==0)return;drag={id:event.pointerId,x:event.clientX,y:event.clientY};viewport.setPointerCapture(event.pointerId);viewport.classList.add('dragging');});
  viewport.addEventListener('pointermove',event=>{if(!drag||drag.id!==event.pointerId||!active)return;active.view='custom';active.x+=event.clientX-drag.x;active.y+=event.clientY-drag.y;drag.x=event.clientX;drag.y=event.clientY;paint();});
  const stop=()=>{drag=null;viewport.classList.remove('dragging');};viewport.addEventListener('pointerup',stop);viewport.addEventListener('pointercancel',stop);
  viewport.addEventListener('keydown',event=>{if(event.target!==viewport||!active)return;const delta={ArrowLeft:[40,0],ArrowRight:[-40,0],ArrowUp:[0,40],ArrowDown:[0,-40]}[event.key];if(delta){event.preventDefault();active.view='custom';active.x+=delta[0];active.y+=delta[1];paint();}else if(event.key==='+'||event.key==='=')zoom(1.3);else if(event.key==='-')zoom(1/1.3);else if(event.key.toLowerCase()==='f')fit();});
 }
 function download(slug){if(!active)return;const svg=active.svg.cloneNode(true);svg.setAttribute('width',active.width);svg.setAttribute('height',active.height);svg.setAttribute('viewBox',`0 0 ${active.width} ${active.height}`);svg.querySelector('.cone-world').removeAttribute('transform');svg.querySelectorAll('a').forEach(a=>{a.setAttribute('href',location.origin+'/'+a.getAttribute('href'));});const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml'})),link=document.createElement('a');link.href=url;link.download=slug+'-'+(new URLSearchParams(location.hash.split('?')[1]||'').get('mode')||'statement')+'-prerequisites.svg';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 function setDisplay(display,user=true){
  if(!active)return;active.userDisplay=user;const panel=active.viewport.closest('.cone-panel');panel.dataset.display=display;
  for(const button of panel.querySelectorAll('[data-action="cone-display"]'))button.setAttribute('aria-pressed',String(button.dataset.display===display));
  if(display==='diagram')resize();
 }
 function jumpToLevel(depth){
  if(!active||!/^\d+$/.test(String(depth)))return;
  const panel=active.viewport.closest('.cone-panel'),level=panel.querySelector(`.cone-list-level[data-depth="${depth}"]`);
  if(!level)return;
  outlineInsets();
  level.open=true;panel.querySelector('.cone-outline-select').value=String(depth);
  level.scrollIntoView({block:'start'});level.querySelector('summary').focus({preventScroll:true});
 }
 function outlineInsets(){
  if(!active)return;const panel=active.viewport.closest('.cone-panel'),nav=panel.querySelector('.cone-outline-nav');
  if(nav.offsetHeight){
   panel.style.setProperty('--outline-nav-height',`${nav.offsetHeight}px`);
   panel.style.setProperty('--outline-main-padding',getComputedStyle(panel.closest('main')).paddingTop);
  }
 }
 function outlineLevels(open){
  if(!active)return;const panel=active.viewport.closest('.cone-panel');
  for(const level of panel.querySelectorAll('.cone-list-level'))level.open=open||level.dataset.depth==='0';
  if(!open)jumpToLevel(0);
 }
 function destroy(){active?.observer.disconnect();active?.outlineObserver?.disconnect();active?.media.removeEventListener('change',active.onMedia);active=null;}
 return {includes,complete,collect,markup,mount,destroy,fit,readable,zoom,download,setDisplay,jumpToLevel,outlineLevels};
})();
