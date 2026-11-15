/* =====================================================================
   Nothingburger · landing + studio
   ===================================================================== */
import { TASKS } from './backend.js';
import { space, initSpace, setSpace, enterSpace, leaveSpace, onSpaceChange, simUnavailable, preloadSpace, tourReady, peekSpace } from './space.js';
import { createCampus } from './campus.js';
import { initFlow, planJob, hideFlow, flowOpen } from './flow.js';
import { initBuildingSearch } from './building-search.js';

const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const P2=Math.PI*2;
const root=document.documentElement;
const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp=(x,a=0,b=1)=>Math.min(b,Math.max(a,x));
const sstep=(a,b,x)=>{const t=clamp((x-a)/(b-a));return t*t*(3-2*t);};
const lerp=(a,b,t)=>a+(b-a)*t;
const bell=(a,b,c,d,x)=>sstep(a,b,x)*(1-sstep(c,d,x));

/* ---------- task catalogue: areas, tasks, actions ---------- */
const AREAS=[
  {id:'sink',name:'Kitchen sink',cat:'Plumbing',meas:[['Counter height','0.91 m','tape'],['Faucet set back','0.46 m','scan'],['Basin depth','0.20 m','tape']],
    tasks:[['Fix the dripping faucet','faucet'],['Unclog the drain','drain'],['Check the pipes for leaks','pipes']]},
  {id:'trash',name:'Trash & recycling',cat:'Garbage',meas:[['Bin height','0.66 m','tape'],['Bag weight, full','up to 6 kg','tape']],
    tasks:[['Take out the trash','trash'],['Replace the bin liner','liner'],['Sort the recycling','recycle']]},
  {id:'table',name:'Dining table',cat:'Tables',meas:[['Table height','0.76 m','tape'],['Top','1.50 × 0.90 m','scan']],
    tasks:[['Wipe down the table','wipe'],['Push in the chairs','chairs']]},
  {id:'light',name:'Pendant light',cat:'Lighting',meas:[['Bulb height','1.60 m','scan'],['Bulb in from table edge','0.45 m','tape']],
    tasks:[['Change the light bulb','bulb']]},
  {id:'bath',name:'Bathroom',cat:'Plumbing',meas:[['Door, clear','0.76 m','scan'],['Toilet tank top','0.76 m','tape'],['Vanity height','0.86 m','tape']],
    tasks:[['Fix the running toilet','toilet'],['Unclog the bathroom sink','vanity'],['Wipe the mirror','mirror']]},
  {id:'living',name:'Living room',cat:'Floors',meas:[['Rug','2.60 × 1.80 m','scan'],['Coffee table','0.40 m high','tape']],
    tasks:[['Vacuum the rug','vacuum'],['Tidy the coffee table','tidy']]},
  {id:'window',name:'Living room window',cat:'Windows',meas:[['Sill height','0.90 m','tape'],['Glass','1.00 × 1.20 m','scan']],
    tasks:[['Clean the window','window']]}
];
const AREA=Object.fromEntries(AREAS.map(a=>[a.id,a]));
const DONE={faucet:'Faucet fixed',drain:'Drain cleared',pipes:'Pipes checked, no leaks',trash:'Trash taken out',liner:'New liner in',recycle:'Recycling sorted',wipe:'Table wiped',chairs:'Chairs pushed in',bulb:'Bulb changed',toilet:'Toilet fixed',vanity:'Sink cleared',mirror:'Mirror wiped',vacuum:'Rug vacuumed',tidy:'Coffee table tidied',window:'Window cleaned'};
const ACT_AREA={faucet:'sink',drain:'sink',pipes:'sink',trash:'trash',liner:'trash',recycle:'trash',wipe:'table',chairs:'table',bulb:'light',toilet:'bath',vanity:'bath',mirror:'bath',vacuum:'living',tidy:'living',window:'window'};
const TASK_NAME={};AREAS.forEach(a=>a.tasks.forEach(([t,k])=>TASK_NAME[k]=t));

function matchTask(text){
  const s=' '+text.toLowerCase()+' ', has=(...w)=>w.some(x=>s.includes(x));
  if(has('pilot','heater','radiator','furnace','disposal','latch','hex key')) return null;   // caretaker jobs: no stand-in here
  const bath=has('bathroom','toilet','vanity','mirror','shower');
  if(has('bulb','light','lamp')) return 'bulb';
  if(has('toilet','flush')) return 'toilet';
  if(has('mirror')) return 'mirror';
  if(bath&&has('sink','drain','clog')) return 'vanity';
  if(has('faucet','tap ','drip')) return 'faucet';
  if(has('pipe','leak')) return 'pipes';
  if(has('drain','clog','sink')) return 'drain';
  if(has('recycl')) return 'recycle';
  if(has('liner')) return 'liner';
  if(has('trash','garbage','rubbish','bin ')) return 'trash';
  if(has('chair')) return 'chairs';
  if(has('table','wipe','crumb','spill')) return has('coffee')?'tidy':'wipe';
  if(has('window','glass')) return 'window';
  if(has('vacuum','rug','carpet','floor','dust')) return 'vacuum';
  if(has('tidy','coffee')) return 'tidy';
  return null;
}

/* ---------- page shell: nav, studio enter/exit, prompt UI ---------- */
const nav=$('#nav');
if(nav) addEventListener('scroll',()=>nav.classList.toggle('scrolled',scrollY>40),{passive:true});
let inStudio=false, enterHooks=[], exitHooks=[], cooldown=0;
function enterStudio(instant){
  if(inStudio) return; inStudio=true; root.classList.add('studio');
  if(location.hash!=='#studio') location.hash='studio';
  enterHooks.forEach(f=>f(instant));
  enterSpace(instant||tourReady()?0:1250);   // a tour the walk-in already faded in stays up
  showPrompt();
}
function exitStudio(){
  if(!inStudio) return; inStudio=false; root.classList.remove('studio');
  cooldown=performance.now()+900;
  if(location.hash==='#studio') location.hash='';
  const how=$('#how'); window.scrollTo({top:how.getBoundingClientRect().top+scrollY+how.offsetHeight/2-innerHeight/2,behavior:'instant'});
  hidePrompt(); leaveSpace(); exitHooks.forEach(f=>f());
}
$$('[data-open-studio]').forEach(b=>b.addEventListener('click',()=>enterStudio(false)));
$$('[data-close-studio]').forEach(b=>b.addEventListener('click',e=>{e.preventDefault();exitStudio();}));
addEventListener('hashchange',()=>{ if(location.hash==='#studio') enterStudio(false); else if(inStudio) exitStudio(); });
const typing=()=>{const t=document.activeElement;return !!t&&['INPUT','TEXTAREA','SELECT'].includes(t.tagName);};
addEventListener('keydown',e=>{ if(e.key==='Escape'&&inStudio&&!typing()) exitStudio(); });
/* auto-enter at the end of the landing scroll */
const openBar=$('#openBar');
function onScrollOpen(){
  if(inStudio) return;
  const sec=$('#open'), top=sec.getBoundingClientRect().top+scrollY, max=document.documentElement.scrollHeight-innerHeight;
  const p=clamp((scrollY-(top-innerHeight*0.6))/Math.max(1,max-(top-innerHeight*0.6)));
  openBar.style.width=(p*100).toFixed(1)+'%';
  if(landingProgress()>0.45) preloadSpace();   // start the hall's tour loading before the walk-in reaches the door
  if(p>0.985&&performance.now()>cooldown) enterStudio(false);
}
addEventListener('scroll',onScrollOpen,{passive:true});
function landingProgress(){ const max=document.documentElement.scrollHeight-innerHeight; return clamp(scrollY/Math.max(1,max)); }
const veil=$('#veil');

/* prompt */
const promptEl=$('#prompt'), input=$('#taskInput'), pmsg=$('#pmsg');
function showPrompt(){promptEl.classList.add('show');}
function hidePrompt(){promptEl.classList.remove('show');}
$('#askBtn').addEventListener('click',()=>{showPrompt();input.focus();});
/* suggested jobs under the prompt: the apartment's chores, or the building jobs from the backend's list */
const chips=$('#chips');
const SIM_CHIPS=['Fix the dripping faucet','Change the light bulb','Wipe down the table','Take out the trash'];
function setChips(kind,jobs){
  chips.replaceChildren(); chips.classList.remove('all');
  const add=(t,cls)=>{const b=document.createElement('button');b.type='button';b.textContent=t;if(cls)b.className=cls;b.addEventListener('click',()=>{input.value=t;input.focus();});chips.appendChild(b);return b;};
  if(jobs&&jobs.length){ jobs.forEach(t=>add(t)); input.placeholder=`Describe a job, like “${jobs[0].toLowerCase()}”`; return; }   // a space that lists its own jobs (an outdoor lot)
  if(kind==='sim'){ SIM_CHIPS.forEach(t=>add(t)); input.placeholder='Describe a task, like “fix the dripping kitchen faucet”'; return; }
  TASKS[0][1].forEach(t=>add(t));
  for(const [group,items] of TASKS.slice(1)){ const g=document.createElement('span');g.className='chip-group k';g.textContent=group;chips.appendChild(g); items.forEach(t=>add(t,'more-chip')); }
  const more=document.createElement('button');more.type='button';more.className='chip-toggle';more.setAttribute('aria-expanded','false');more.textContent='More jobs';
  more.addEventListener('click',()=>{const on=chips.classList.toggle('all');more.setAttribute('aria-expanded',String(on));more.textContent=on?'Fewer':'More jobs';});
  chips.appendChild(more);
  input.placeholder='Describe a job, like “change a hallway bulb”';
}
setChips('scan');
let clipName='';
$('#clip').addEventListener('change',e=>{const f=e.target.files[0];clipName=f?f.name:'';$('#attachLbl').childNodes[1].textContent=f?' '+(f.name.length>16?f.name.slice(0,14)+'…':f.name):'＋ Demo clip';});

/* area list + cards (the 3D layer hooks into these) */
const API={select:()=>{},run:()=>{},hover:()=>{}};
const list=$('#areaList');
AREAS.forEach(a=>{
  const li=document.createElement('li');
  li.innerHTML=`<button type="button" class="area-btn" data-area="${a.id}" aria-pressed="false"><span class="d"></span><span><b>${a.name}</b><small>${a.cat}</small></span><span class="c">${a.tasks.length}</span></button>`;
  const b=li.firstChild; b.addEventListener('click',()=>API.select(a.id,true));
  b.addEventListener('mouseenter',()=>API.hover(a.id)); b.addEventListener('mouseleave',()=>API.hover(null));
  list.appendChild(li);
});
const card=$('#card');
function closeCard(){card.classList.remove('show');API.select(null,false);}
function showAreaCard(id){
  const a=AREA[id]; if(!a){card.classList.remove('show');return;}
  card.innerHTML=`<div class="card-head"><div><span class="tag" style="--c:var(--gold-ink)">${a.cat}</span><h2>${a.name}</h2></div><button class="x" type="button" aria-label="Close">×</button></div>
  <table class="meas"><tbody>${a.meas.map(m=>`<tr><td>${m[0]}</td><td class="v">${m[1]}</td><td class="s"><span class="tag" style="--c:var(--${m[2]})">${m[2]}</span></td></tr>`).join('')}</tbody></table>
  <p class="k" style="margin-top:18px">Tasks the robot can do here</p>
  <ul class="tasks">${a.tasks.map(([t,k])=>`<li><button type="button" class="task" data-act="${k}">${t}<span class="go">Plan →</span></button></li>`).join('')}</ul>
  <p class="note">Measurements come from the scan and a tape check. The dimension lines in the view show the ones the robot design depends on.</p>`;
  card.querySelector('.x').addEventListener('click',closeCard);
  card.querySelectorAll('.task').forEach(b=>b.addEventListener('click',()=>{const t=TASK_NAME[b.dataset.act];input.value=t;showPrompt();planJob(t);}));
  hideFlow(); card.classList.add('show');
}
function setAreaButtons(id){$$('.area-btn').forEach(b=>b.setAttribute('aria-pressed',b.dataset.area===id?'true':'false'));}

promptEl.addEventListener('submit',e=>{
  e.preventDefault(); const text=input.value.trim();
  if(!text){pmsg.className='pmsg err';pmsg.textContent='Type a task first, or pick one from the chips above.';return;}
  pmsg.className='pmsg';pmsg.textContent='';
  planJob(text);
});

/* spaces and the plan panel */
onSpaceChange(s=>{ setChips(s.kind,s.jobs); if(s.kind==='scan'){card.classList.remove('show');API.select(null,false);} });
initFlow({
  canSim:plan=>root.classList.contains('no-webgl')?null:matchTask(plan.job),
  runSim:(act,text,ui)=>API.run(act,text,ui),
  toSim:()=>setSpace('sample-apartment'),
  onOpen:()=>{card.classList.remove('show');API.select(null,false);}
});
initSpace({simOK:()=>!root.classList.contains('no-webgl')});
initBuildingSearch();
function noGL(){root.classList.add('no-webgl');simUnavailable();}

/* =====================================================================
   3D
   ===================================================================== */
let THREE,RoundedBoxGeometry,RoomEnvironment,mergeGeometries;
try{
  THREE=await import('three');
  [{RoundedBoxGeometry},{RoomEnvironment},{mergeGeometries}]=await Promise.all([
    import('three/addons/geometries/RoundedBoxGeometry.js'),import('three/addons/environments/RoomEnvironment.js'),import('three/addons/utils/BufferGeometryUtils.js')]);
}catch(e){noGL();}
if(THREE) start(); else boot();
function boot(){ if(location.hash==='#studio') enterStudio(true); }

function start(){
const canvas=$('#scene');
let renderer;
try{renderer=new THREE.WebGLRenderer({canvas,antialias:true,powerPreference:'high-performance'});}
catch(e){noGL();boot();return;}
const DPR_MAX=Math.min(devicePixelRatio||1,2); let dpr=Math.min(DPR_MAX,1.5); renderer.setPixelRatio(dpr);
const MAX_ANISO=renderer.capabilities.getMaxAnisotropy();
renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap; renderer.shadowMap.autoUpdate=false; renderer.shadowMap.needsUpdate=true;
renderer.outputColorSpace=THREE.SRGBColorSpace;
renderer.toneMapping=THREE.ACESFilmicToneMapping; renderer.toneMappingExposure=0.95;
const scene=new THREE.Scene(); scene.background=new THREE.Color('#F4EFE7');
const pmrem=new THREE.PMREMGenerator(renderer);
scene.environment=pmrem.fromScene(new RoomEnvironment(renderer),0.04).texture;
const camera=new THREE.PerspectiveCamera(30,1,0.05,140);
/* the landing's site model of JRR Hall; the apartment below is the studio's sample space */
let campus=null;
fetch('assets/jrr-site.json').then(r=>r.json()).then(site=>{campus=createCampus(THREE,renderer,site,{reduce});campus.resize(W,H,mob);}).catch(()=>{});
onSpaceChange(s=>{ if(s.kind==='sim') renderer.shadowMap.needsUpdate=true; });

/* lights */
scene.add(new THREE.HemisphereLight(0xfff6ea,0xcdb9a0,0.75));
const sun=new THREE.DirectionalLight(0xfff0da,2.2);
sun.position.set(-7,12,8); sun.castShadow=true; sun.shadow.mapSize.set(4096,4096);
Object.assign(sun.shadow.camera,{left:-8,right:8,top:8,bottom:-8,near:1,far:40});
sun.shadow.bias=-0.0004; sun.shadow.normalBias=0.025; scene.add(sun);

/* helpers */
const M=(c,r=0.85,m=0,extra={})=>new THREE.MeshStandardMaterial(Object.assign({color:c,roughness:r,metalness:m,envMapIntensity:0.55},extra));
function rbox(w,h,d,r,mat,x=0,y=0,z=0,parent=scene){
  const rr=Math.min(r,w/2-1e-3,h/2-1e-3,d/2-1e-3);
  const g=rr>0.002?new RoundedBoxGeometry(w,h,d,3,rr):new THREE.BoxGeometry(w,h,d);
  const m=new THREE.Mesh(g,mat); m.position.set(x,y,z); m.castShadow=true; m.receiveShadow=true; parent.add(m); return m;
}
function cyl(rt,rb,h,mat,x=0,y=0,z=0,parent=scene,seg=28,open=false){const m=new THREE.Mesh(new THREE.CylinderGeometry(rt,rb,h,seg,1,open),mat);m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;}
function sph(r,mat,x,y,z,parent=scene){const m=new THREE.Mesh(new THREE.SphereGeometry(r,24,16),mat);m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;}
function tex(w,h,draw,repeat){const c=document.createElement('canvas');c.width=w;c.height=h;draw(c.getContext('2d'),w,h);const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=8;if(repeat){t.wrapS=t.wrapT=THREE.RepeatWrapping;t.repeat.set(repeat[0],repeat[1]);}return t;}
function rng(seed){return function(){seed|=0;seed=seed+0x6D2B79F5|0;let t=Math.imul(seed^seed>>>15,1|seed);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;}}
const V=(x,y,z)=>new THREE.Vector3(x,y,z);

/* palette */
const C={wall:'#EEE7DC',cut:'#C9B9A4',white:'#F8F5EF',counter:'#DCD6CC',wood:'#A97D55',woodDark:'#5B4434',oak:'#D7BC95',sage:'#A3AE94',sageDeep:'#88957A',blue:'#8DA1B3',ink:'#1E1B17',leaf:'#7C986A',leaf2:'#6A8758',cream:'#F5F0E6',steel:'#C7CBCD'};
const brass=M('#C99A2E',0.3,0.9,{envMapIntensity:1});
const chrome=M('#D9DDE0',0.15,1,{envMapIntensity:1.1});
const steel=M(C.steel,0.32,0.85,{envMapIntensity:0.9});

/* blob contact shadows */
const blobTex=tex(128,128,(g,w)=>{const r=g.createRadialGradient(w/2,w/2,0,w/2,w/2,w/2);r.addColorStop(0,'rgba(40,28,14,.42)');r.addColorStop(.55,'rgba(40,28,14,.16)');r.addColorStop(1,'rgba(40,28,14,0)');g.fillStyle=r;g.fillRect(0,0,w,w);});
const blobMat=new THREE.MeshBasicMaterial({map:blobTex,transparent:true,depthWrite:false,toneMapped:false});
function blob(x,z,w,d,y=0.003){const m=new THREE.Mesh(new THREE.PlaneGeometry(w,d),blobMat);m.rotation.x=-Math.PI/2;m.position.set(x,y,z);m.renderOrder=1;scene.add(m);return m;}

/* area groups (for highlighting) */
const AG={}; AREAS.forEach(a=>{AG[a.id]=new THREE.Group();scene.add(AG[a.id]);});

const leafG=new THREE.SphereGeometry(1,14,10), leafM=[M('#7C986A',0.65,0,{envMapIntensity:0.5}),M('#6A8758',0.65,0,{envMapIntensity:0.5}),M('#8FAA78',0.65,0,{envMapIntensity:0.5})];
function plant(x,y,z,s=1,potC='#E9E1D3'){const g=new THREE.Group();g.position.set(x,y,z);g.scale.setScalar(s);scene.add(g);
  cyl(0.13,0.1,0.26,M(potC,0.6),0,0.13,0,g,32); const rim=new THREE.Mesh(new THREE.TorusGeometry(0.128,0.012,8,32),M(potC,0.55));rim.rotation.x=Math.PI/2;rim.position.y=0.26;g.add(rim);
  cyl(0.118,0.118,0.01,M('#4A3B2C',1),0,0.245,0,g,24);
  const r=rng(Math.round((x+9)*97+(z+9)*13));
  for(let i=0;i<18;i++){const pv=new THREE.Group();pv.position.set((r()-.5)*0.08,0.25,(r()-.5)*0.08);pv.rotation.y=r()*P2;g.add(pv);
    const tg=new THREE.Group();tg.rotation.z=0.12+r()*0.55;pv.add(tg);const len=0.2+r()*0.22;
    const lf=new THREE.Mesh(leafG,leafM[i%3]);lf.scale.set(0.035+r()*0.02,len/2,0.007);lf.position.y=len/2;lf.rotation.y=(r()-.5)*0.8;lf.castShadow=true;lf.receiveShadow=true;tg.add(lf);}
  return g;}
/* ---------- blueprint grid + plan dimensions ---------- */
const gridMat=new THREE.ShaderMaterial({transparent:true,depthWrite:false,toneMapped:false,uniforms:{uColor:{value:new THREE.Color('#2A231B')}},
  vertexShader:`varying vec3 vW;void main(){vec4 w=modelMatrix*vec4(position,1.);vW=w.xyz;gl_Position=projectionMatrix*viewMatrix*w;}`,
  fragmentShader:`uniform vec3 uColor;varying vec3 vW;float line(vec2 p,float s,float w){vec2 q=p/s;vec2 g=abs(fract(q-.5)-.5)/(fwidth(q)*w);return 1.-min(min(g.x,g.y),1.);}
  void main(){float mi=line(vW.xz,.25,1.);float ma=line(vW.xz,1.,1.3);float d=length(vW.xz-vec2(.5,0.));float fade=1.-smoothstep(7.,21.,d);gl_FragColor=vec4(uColor,(mi*.07+ma*.16)*fade);}`});
const grid=new THREE.Mesh(new THREE.PlaneGeometry(90,90),gridMat); grid.rotation.x=-Math.PI/2; grid.position.y=-0.215; grid.renderOrder=-1; scene.add(grid);
const dimMat=new THREE.LineBasicMaterial({color:'#3A322A',transparent:true,opacity:.45});
function planDim(a,b,t){const g=new THREE.BufferGeometry().setFromPoints([a,b,a.clone().add(t),a.clone().sub(t),b.clone().add(t),b.clone().sub(t)]);scene.add(new THREE.LineSegments(g,dimMat));}
planDim(V(-5,-0.21,4.3),V(5,-0.21,4.3),V(0,0,0.14)); planDim(V(6.9,-0.21,-3.7),V(6.9,-0.21,3.7),V(0.14,0,0));

/* ---------- shell: floor, walls, windows ---------- */
const floorTex=(()=>{const FW=2048,FH=1520,fc=document.createElement('canvas'),bc=document.createElement('canvas');fc.width=bc.width=FW;fc.height=bc.height=FH;
  const g=fc.getContext('2d'),b=bc.getContext('2d');g.fillStyle='#D9C29E';g.fillRect(0,0,FW,FH);b.fillStyle='#202020';b.fillRect(0,0,FW,FH);
  const r=rng(7),rows=37,rh=FH/rows;
  for(let i=0;i<rows;i++){let x=-r()*380;while(x<FW){const len=290+r()*440,v=(r()-.5)*20;g.fillStyle=`rgb(${218+v},${194+v},${158+v})`;g.fillRect(x,i*rh,len-3,rh-2.4);
    const bv=200+Math.floor(r()*30);b.fillStyle=`rgb(${bv},${bv},${bv})`;b.fillRect(x+1,i*rh+1,len-5,rh-4.4);
    for(let k=0;k<9;k++){const yy=i*rh+r()*rh,xx=x+r()*len,l2=60+r()*180;g.globalAlpha=.07;g.fillStyle=r()>.5?'#6b4a2b':'#fff';g.fillRect(xx,yy,l2,1.2);b.globalAlpha=.25;b.fillStyle='#000';b.fillRect(xx,yy,l2,1);g.globalAlpha=b.globalAlpha=1;}
    x+=len;}}
  const t=new THREE.CanvasTexture(fc);t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=MAX_ANISO;
  const bt=new THREE.CanvasTexture(bc);bt.anisotropy=MAX_ANISO;return {t,bt};})();
const floorMat=M('#ffffff',0.58,0,{map:floorTex.t,bumpMap:floorTex.bt,bumpScale:0.9,envMapIntensity:0.4});
const cutMat=M(C.cut,0.9);
const slab=rbox(10,0.2,7.4,0,[cutMat,cutMat,floorMat,cutMat,cutMat,cutMat],0,-0.1,0);
const tileTex=(c1,c2,n,m,gap)=>tex(1024,1024,(g,w,h)=>{g.fillStyle=c2;g.fillRect(0,0,w,h);const tw=w/n,th=h/m;for(let i=0;i<n;i++)for(let j=0;j<m;j++){const off=(m>n&&j%2)?tw/2:0;g.fillStyle=c1;g.fillRect(i*tw+gap+off,j*th+gap,tw-gap*2,th-gap*2);if(off)g.fillRect(i*tw+gap+off-w,j*th+gap,tw-gap*2,th-gap*2);}});
const bfT=tileTex('#E9E7E2','#B9B3A9',8,8,3);const bathFloor=new THREE.Mesh(new THREE.PlaneGeometry(2.45,2.35),M('#fff',0.35,0,{map:bfT,bumpMap:bfT,bumpScale:0.6,envMapIntensity:0.7}));
bathFloor.rotation.x=-Math.PI/2; bathFloor.position.set(-3.675,0.002,-2.425); bathFloor.receiveShadow=true; scene.add(bathFloor);

const wallMat=M(C.wall,0.95,0,{envMapIntensity:0.3}), capMat=M(C.cut,0.9);
const WH=2.6, CUT=1.05;
/* wall along x or z with optional openings [[a0,a1,y0,y1],...] */
function wallX(x0,x1,z0,z1,h,open=[]){ // runs along x
  let segs=[[x0,x1]]; const cuts=[];
  for(const o of open){segs=segs.flatMap(([a,b])=>o[0]>=b||o[1]<=a?[[a,b]]:[[a,o[0]],[o[1],b]].filter(s=>s[1]-s[0]>1e-3));cuts.push(o);}
  for(const [a,b] of segs) box(a,b,0,h,z0,z1);
  for(const o of cuts){ if(o[2]>0) box(o[0],o[1],0,o[2],z0,z1); if(o[3]<h) box(o[0],o[1],o[3],h,z0,z1); }
  function box(a,b,y0,y1,c0,c1){rbox(b-a,y1-y0,c1-c0,0,wallMat,(a+b)/2,(y0+y1)/2,(c0+c1)/2); if(y1===h) rbox(b-a+0.002,0.012,c1-c0+0.002,0,capMat,(a+b)/2,y1+0.006,(c0+c1)/2);}
}
function wallZ(x0,x1,z0,z1,h,open=[]){ // runs along z
  let segs=[[z0,z1]];
  for(const o of open) segs=segs.flatMap(([a,b])=>o[0]>=b||o[1]<=a?[[a,b]]:[[a,o[0]],[o[1],b]].filter(s=>s[1]-s[0]>1e-3));
  for(const [a,b] of segs) box(a,b,0,h);
  for(const o of open){ if(o[2]>0) box(o[0],o[1],0,o[2]); if(o[3]<h) box(o[0],o[1],o[3],h); }
  function box(a,b,y0,y1){rbox(x1-x0,y1-y0,b-a,0,wallMat,(x0+x1)/2,(y0+y1)/2,(a+b)/2); if(y1===h) rbox(x1-x0+0.002,0.012,b-a+0.002,0,capMat,(x0+x1)/2,y1+0.006,(a+b)/2);}
}
const KWIN=[-0.45,0.85,1.1,2.1], LWIN=[2.45,3.45,0.9,2.1];
wallX(-5,5,-3.7,-3.6,WH,[KWIN]);
wallZ(-5,-4.9,-3.6,3.7,WH,[LWIN]);
wallZ(4.9,5,-3.6,3.7,0.3,[[0.45,1.26,0,1]]);
wallX(-5,5,3.6,3.7,0.3);
wallZ(-2.45,-2.35,-3.6,-1.15,CUT);
wallX(-4.9,-2.45,-1.25,-1.15,CUT,[[-3.86,-3.05,0,9]]);
/* in the studio the cut-away walls rise to full height and a ceiling closes the room */
const risers=[];
function riser(x0,x1,z0,z1,y0,y1){const g=new THREE.Group();g.userData.dyn=true;g.position.set((x0+x1)/2,y0,(z0+z1)/2);scene.add(g);
  const m=new THREE.Mesh(new THREE.BoxGeometry(x1-x0,y1-y0,z1-z0),wallMat);m.position.y=(y1-y0)/2;m.receiveShadow=true;g.add(m);
  const c=new THREE.Mesh(new THREE.BoxGeometry(x1-x0+0.002,0.012,z1-z0+0.002),capMat);c.position.y=(y1-y0)+0.006;g.add(c);g.scale.y=0.001;g.visible=false;risers.push(g);}
riser(-5,5,3.6,3.7,0.3,WH); riser(4.9,5,-3.6,0.45,0.3,WH); riser(4.9,5,1.26,3.6,0.3,WH); riser(4.9,5,0.45,1.26,2.12,WH);
riser(-2.45,-2.35,-3.6,-1.15,CUT,WH); riser(-4.9,-3.86,-1.25,-1.15,CUT,WH); riser(-3.05,-2.45,-1.25,-1.15,CUT,WH); riser(-3.86,-3.05,-1.25,-1.15,2.08,WH);
const ceil=new THREE.Group();ceil.userData.dyn=true;ceil.visible=false;scene.add(ceil);
{const p=new THREE.Mesh(new THREE.PlaneGeometry(10,7.4),M('#F3EEE6',0.95,0,{envMapIntensity:0.3}));p.rotation.x=Math.PI/2;p.position.y=WH;ceil.add(p);
 const glow=new THREE.MeshStandardMaterial({color:'#FFF6E6',emissive:new THREE.Color('#FFF1DA'),emissiveIntensity:1.4,roughness:0.4});
 for(const [x,z] of [[-2.7,1.0],[1.1,-2.4],[-3.6,-2.4],[2.6,1.6]]){const d=new THREE.Mesh(new THREE.CylinderGeometry(0.2,0.22,0.05,40),glow);d.position.set(x,WH-0.025,z);ceil.add(d);const r=new THREE.Mesh(new THREE.TorusGeometry(0.215,0.012,8,40),M('#E8E1D6',0.5));r.rotation.x=Math.PI/2;r.position.set(x,WH-0.05,z);ceil.add(r);}}
/* open front door leaf, only with the full walls */
{const g=new THREE.Group();g.userData.dyn=true;g.position.set(4.86,0,1.28);g.rotation.y=-0.12;g.scale.y=0.001;g.visible=false;scene.add(g);risers.push(g);
 const leaf=new THREE.Mesh(new THREE.BoxGeometry(0.8,2.03,0.045),M('#E7DFD2',0.6));leaf.position.set(-0.4,1.015,0.03);g.add(leaf);
 for(const y of [0.55,1.45]){const pn=new THREE.Mesh(new THREE.BoxGeometry(0.62,0.7,0.006),M('#DDD3C4',0.6));pn.position.set(-0.4,y,0.055);g.add(pn);}
 const kn=new THREE.Mesh(new THREE.SphereGeometry(0.03,16,12),brass);kn.position.set(-0.72,1.0,0.08);g.add(kn);}
/* baseboards on the low front and right walls */
rbox(9.8,0.08,0.015,0,M('#E3DACD',0.7),0,0.04,3.592); rbox(0.015,0.08,4.05,0,M('#E3DACD',0.7),4.892,0.04,-1.575); rbox(0.015,0.08,2.34,0,M('#E3DACD',0.7),4.892,0.04,2.43);
/* tiles on bathroom back wall and kitchen backsplash */
const wtT=tileTex('#F1EEE8','#C8C1B6',10,5,3);const wallTile=new THREE.Mesh(new THREE.PlaneGeometry(2.45,1.2),M('#fff',0.25,0,{map:wtT,bumpMap:wtT,bumpScale:0.5,envMapIntensity:0.8}));wallTile.position.set(-3.675,0.6,-3.598);scene.add(wallTile);
const spT=tileTex('#F6F3EE','#CEC7BB',8,12,3);const splash=M('#fff',0.22,0,{map:spT,bumpMap:spT,bumpScale:0.5,envMapIntensity:0.8});
for(const [a,b] of [[-1.9,-0.45],[0.85,1.9]]){const p=new THREE.Mesh(new THREE.PlaneGeometry(b-a,0.46),splash);p.position.set((a+b)/2,1.14,-3.598);scene.add(p);}
{const p=new THREE.Mesh(new THREE.PlaneGeometry(1.3,0.19),splash);p.position.set(0.2,1.005,-3.598);scene.add(p);}
/* baseboards */
const bbM=M('#E3DACD',0.7);
rbox(9.8,0.08,0.015,0,bbM,0,0.04,-3.592); rbox(0.015,0.08,7.2,0,bbM,-4.892,0.04,0);
/* windows: frames, glass, sky outside */
const skyTex=tex(64,256,(g,w,h)=>{const r=g.createLinearGradient(0,0,0,h);r.addColorStop(0,'#BFD7EA');r.addColorStop(.7,'#E8EEF0');r.addColorStop(1,'#F2EEE6');g.fillStyle=r;g.fillRect(0,0,w,h);});
const skyMat=new THREE.MeshBasicMaterial({map:skyTex,toneMapped:false});
const frameM=M(C.white,0.45);
const glassM=new THREE.MeshPhysicalMaterial({color:'#dfeaf0',roughness:0.05,metalness:0,transparent:true,opacity:0.22,envMapIntensity:1.2});
function windowX(x0,x1,y0,y1,z,parent=scene){const cx=(x0+x1)/2,cy=(y0+y1)/2,w=x1-x0,h=y1-y0;
  rbox(w,0.05,0.12,0.01,frameM,cx,y0,z,parent);rbox(w,0.05,0.12,0.01,frameM,cx,y1,z,parent);rbox(0.05,h,0.12,0.01,frameM,x0,cy,z,parent);rbox(0.05,h,0.12,0.01,frameM,x1,cy,z,parent);rbox(0.03,h,0.06,0,frameM,cx,cy,z,parent);
  rbox(w+0.08,0.03,0.2,0.008,frameM,cx,y0-0.03,z+0.06,parent);
  const gl=new THREE.Mesh(new THREE.PlaneGeometry(w,h),glassM);gl.position.set(cx,cy,z);parent.add(gl);const s=new THREE.Mesh(new THREE.PlaneGeometry(w+0.4,h+0.4),skyMat);s.position.set(cx,cy,z-0.2);parent.add(s);return gl;}
function windowZ(z0,z1,y0,y1,x,parent=scene){const g=new THREE.Group();g.position.set(x,0,(z0+z1)/2);g.rotation.y=Math.PI/2;parent.add(g);return windowX(-(z1-z0)/2,(z1-z0)/2,y0,y1,0,g);}
windowX(KWIN[0],KWIN[1],KWIN[2],KWIN[3],-3.65);
const lwinGlass=windowZ(LWIN[0],LWIN[1],LWIN[2],LWIN[3],-4.95,AG.window);
/* door frames */
const casing=M(C.white,0.5);
rbox(0.14,2.08,0.06,0.01,casing,4.95,1.04,0.42); rbox(0.14,2.08,0.06,0.01,casing,4.95,1.04,1.29); rbox(0.14,0.06,0.93,0.01,casing,4.95,2.08,0.855);
const landing=rbox(1.3,0.12,1.3,0.02,M('#C8B8A1',0.9),5.65,-0.18,0.855);
rbox(0.12,0.012,0.81,0,M('#B5A288'),4.95,0.006,0.855);
rbox(0.62,0.012,0.42,0.006,M('#3F3A33',0.95),5.6,-0.114,0.855);

/* ---------- kitchen ---------- */
const cab=M(C.white,0.55,0,{envMapIntensity:0.5});
rbox(3.8,0.86,0.6,0.015,cab,0,0.43,-3.3);
rbox(3.84,0.04,0.63,0.008,M(C.counter,0.35,0,{envMapIntensity:0.8}),0,0.89,-3.295);
for(let i=0;i<6;i++){const x=-1.9+0.633*i;if(i)rbox(0.008,0.76,0.004,0,M('#D7CFC2'),x,0.46,-2.998);rbox(0.18,0.016,0.02,0.007,brass,x+0.316,0.8,-2.99);}
rbox(0.6,0.62,0.006,0.004,M('#2A2826',0.25,0.2),1.2,0.44,-2.997); // oven door
rbox(0.5,0.02,0.02,0.008,steel,1.2,0.79,-2.985);
/* sink area (tagged) */
const basin=rbox(0.62,0.012,0.44,0.004,M('#9FA6AB',0.3,0.8),0.2,0.913,-3.28,AG.sink);
rbox(0.56,0.2,0.38,0.02,M('#8E959A',0.35,0.8),0.2,0.81,-3.28,AG.sink);
const faucet=new THREE.Group();faucet.position.set(0.2,0.91,-3.5);AG.sink.add(faucet);
cyl(0.022,0.026,0.06,chrome,0,0.03,0,faucet);cyl(0.014,0.014,0.3,chrome,0,0.18,0,faucet);
const spout=new THREE.Mesh(new THREE.TorusGeometry(0.1,0.013,10,24,Math.PI),chrome);spout.position.set(0,0.33,0.1);spout.rotation.y=Math.PI/2;faucet.add(spout);spout.castShadow=true;
const handle=rbox(0.012,0.012,0.09,0.005,chrome,0.06,0.12,0.02,faucet);
const spoutTip=V(0.2,1.22,-3.3);
rbox(0.632,0.74,0.004,0,M('#EDE8DF',0.6),0.2,0.45,-2.995,AG.sink);
/* cooktop */
rbox(0.6,0.01,0.5,0.004,M('#1A1917',0.15,0.3,{envMapIntensity:1}),1.2,0.915,-3.28);
for(const [dx,dz] of [[-.15,-.12],[.15,-.12],[-.15,.12],[.15,.12]]){const t=new THREE.Mesh(new THREE.TorusGeometry(0.075,0.005,6,28),M('#55504a',0.4));t.rotation.x=-Math.PI/2;t.position.set(1.2+dx,0.922,-3.28+dz);scene.add(t);}
/* uppers, fridge */
rbox(1.3,0.76,0.33,0.012,cab,-1.25,1.75,-3.435); rbox(0.9,0.76,0.33,0.012,cab,1.45,1.75,-3.435);
for(const x of [-1.25,1.45]) rbox(0.006,0.7,0.004,0,M('#D7CFC2'),x,1.75,-3.268);
rbox(0.76,1.78,0.72,0.03,steel,2.38,0.89,-3.24); rbox(0.76,0.008,0.725,0,M('#9EA3A6',0.4,0.8),2.38,1.2,-3.24);
rbox(0.022,0.5,0.03,0.008,chrome,2.06,1.5,-2.86); rbox(0.022,0.36,0.03,0.008,chrome,2.06,0.92,-2.86);
blob(2.38,-3.2,1.1,1.0); blob(0,-3.25,4.4,1.0);
plant(-1.5,0.91,-3.42,0.55);
cyl(0.075,0.07,0.17,steel,1.7,0.995,-3.4); cyl(0.05,0.05,0.025,M('#2a2826'),1.7,1.09,-3.4);
/* drip */
const drip=sph(0.009,M('#bcd8ea',0.05,0,{transparent:true,opacity:0.85,envMapIntensity:1.5}),spoutTip.x,spoutTip.y,spoutTip.z); drip.castShadow=false;

/* ---------- trash + recycling ---------- */
function bin(x,z,col,lidCol){const g=new THREE.Group();g.position.set(x,0,z);AG.trash.add(g);
  cyl(0.17,0.15,0.62,M(col,0.4,0.6),0,0.31,0,g,32); const lid=new THREE.Group();lid.userData.dyn=true;lid.position.set(0,0.63,-0.17);g.add(lid);
  const l=cyl(0.175,0.175,0.03,M(lidCol,0.35,0.6),0,0,0.17,lid,32);rbox(0.08,0.02,0.03,0.008,M('#2a2826'),0,0.02,0.33,lid);blob(x,z,0.6,0.6);return {g,lid};}
const trashBin=bin(-2.15,-2.6,'#BFC3C5','#AEB2B4'), recBin=bin(-2.15,-2.15,'#6F8FA8','#5E7D96');
const bag=sph(0.13,M('#2E3330',0.6),-2.15,0.48,-2.6); bag.scale.set(1,1.1,1); bag.visible=false; bag.userData.dyn=true; bag.castShadow=false;
const bagKnot=sph(0.035,M('#2E3330',0.6),0,0.14,0,bag);

/* ---------- dining ---------- */
const TX=0.5,TZ=-0.85;
rbox(1.5,0.045,0.9,0.012,M(C.wood,0.5,0,{envMapIntensity:0.6}),TX,0.7375,TZ,AG.table);
for(const [dx,dz] of [[-.66,-.36],[.66,-.36],[-.66,.36],[.66,.36]]) cyl(0.026,0.022,0.715,M(C.woodDark,0.6),TX+dx,0.3575,TZ+dz,AG.table);
const chairs=[];
function chair(x,z,ry){const g=new THREE.Group();g.userData.dyn=true;g.position.set(x,0,z);g.rotation.y=ry;AG.table.add(g);const s=M(C.sage,0.85),l=M(C.woodDark,0.6);
  rbox(0.44,0.045,0.44,0.02,s,0,0.455,0,g);rbox(0.44,0.4,0.045,0.02,s,0,0.68,-0.2,g);for(const [dx,dz] of [[-.19,-.19],[.19,-.19],[-.19,.19],[.19,.19]])cyl(0.015,0.015,0.44,l,dx,0.22,dz,g);chairs.push(g);return g;}
chair(TX-0.36,TZ+0.66,Math.PI); chair(TX+0.36,TZ+0.66,Math.PI); chair(TX+0.98,TZ,-Math.PI/2);
const chairOut=[chairs[0].position.z,chairs[1].position.z];
blob(TX,TZ,2.2,1.5);
rbox(0.3,0.012,0.3,0.004,M('#E8DED0',0.8),TX+0.4,0.766,TZ-0.15,AG.table);
cyl(0.045,0.035,0.15,M('#E9E1D3',0.4),TX+0.4,0.84,TZ-0.15,AG.table); sph(0.035,M('#D98C4A',0.6),TX+0.4,0.94,TZ-0.15,AG.table);
const spill=new THREE.Mesh(new THREE.CircleGeometry(0.13,32),new THREE.MeshStandardMaterial({color:'#7a5534',roughness:0.15,transparent:true,opacity:0.55,envMapIntensity:1}));
spill.rotation.x=-Math.PI/2; spill.scale.set(1.3,1,1); spill.position.set(TX-0.25,0.762,TZ+0.05); scene.add(spill);
/* pendant */
const BULB=V(TX,1.6,TZ);
cyl(0.005,0.005,0.9,M(C.ink),TX,2.21,TZ,AG.light);
const shadeM=brass.clone(); shadeM.side=THREE.DoubleSide;
cyl(0.06,0.24,0.2,shadeM,TX,1.74,TZ,AG.light,40,true);
cyl(0.028,0.028,0.06,M(C.ink,0.4),TX,1.665,TZ,AG.light);
const bulbMat=M('#E8E4DC',0.2,0,{emissive:new THREE.Color('#FFC864'),emissiveIntensity:0});
const bulbG=new THREE.Group(); bulbG.userData.dyn=true; bulbG.position.copy(BULB); AG.light.add(bulbG);
const bulb=new THREE.Mesh(new THREE.SphereGeometry(0.055,28,18),bulbMat); bulb.scale.set(1,1.15,1); bulb.userData.noHi=true; bulbG.add(bulb);
const bulbLight=new THREE.PointLight(0xffcf7a,0,6,2); bulbLight.position.set(TX,1.52,TZ); scene.add(bulbLight);
const haloTex=tex(128,128,(g,w)=>{const r=g.createRadialGradient(w/2,w/2,0,w/2,w/2,w/2);r.addColorStop(0,'rgba(255,214,130,1)');r.addColorStop(.35,'rgba(255,200,110,.35)');r.addColorStop(1,'rgba(255,200,110,0)');g.fillStyle=r;g.fillRect(0,0,w,w);});
const halo=new THREE.Sprite(new THREE.SpriteMaterial({map:haloTex,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,opacity:0})); halo.scale.set(1,1,1); halo.position.copy(BULB); scene.add(halo);

/* ---------- bathroom ---------- */
const porc=M('#FBFAF7',0.18,0,{envMapIntensity:0.9});
/* shower */
rbox(0.9,0.05,0.9,0.01,porc,-4.45,0.025,-3.15,AG.bath);
const sg=new THREE.Mesh(new THREE.PlaneGeometry(0.62,1.9),glassM);sg.position.set(-4.59,0.98,-2.7);AG.bath.add(sg);
rbox(0.02,1.9,0.02,0,chrome,-4.28,0.98,-2.7,AG.bath);
cyl(0.01,0.01,0.5,chrome,-4.45,1.75,-3.58,AG.bath); cyl(0.08,0.08,0.015,chrome,-4.45,2.0,-3.5,AG.bath).rotation.x=Math.PI/2;
/* toilet */
const toiletG=new THREE.Group(); toiletG.position.set(-3.55,0,-3.6); AG.bath.add(toiletG);
rbox(0.46,0.36,0.18,0.04,porc,0,0.58,0.1,toiletG);
const tankLid=rbox(0.48,0.035,0.2,0.012,porc,0,0.775,0.1,toiletG);
rbox(0.36,0.38,0.5,0.12,porc,0,0.19,0.42,toiletG);
rbox(0.38,0.03,0.46,0.12,M('#F2F0EB',0.25),0,0.395,0.43,toiletG);
const flush=rbox(0.06,0.015,0.02,0.006,chrome,-0.19,0.7,0.2,toiletG);
blob(-3.55,-3.25,0.8,1.0);
/* vanity + mirror */
rbox(0.75,0.82,0.5,0.015,M('#B99C7A',0.55),-2.825,0.41,-3.35,AG.bath);
rbox(0.78,0.04,0.52,0.01,porc,-2.825,0.84,-3.34,AG.bath);
rbox(0.42,0.012,0.32,0.08,M('#E9E8E4',0.12),-2.825,0.862,-3.32,AG.bath);
cyl(0.012,0.012,0.16,chrome,-2.825,0.94,-3.53,AG.bath); rbox(0.016,0.016,0.12,0.006,chrome,-2.825,1.02,-3.48,AG.bath);
const mirror=rbox(0.62,0.8,0.02,0.01,M('#E8EEF1',0.02,1,{envMapIntensity:1.4}),-2.825,1.55,-3.59,AG.bath);
rbox(0.66,0.84,0.015,0.01,brass,-2.825,1.55,-3.597,AG.bath);
blob(-2.825,-3.3,1.0,0.8);
rbox(0.6,0.012,0.4,0.01,M('#C9D4CF',0.95),-3.5,0.006,-2.3,AG.bath);
const smudgeTex=tex(256,256,(g,w)=>{const r=rng(3);for(let i=0;i<40;i++){g.fillStyle=`rgba(120,110,95,${0.06+r()*0.1})`;g.beginPath();g.ellipse(r()*w,r()*w,10+r()*40,6+r()*20,r()*3,0,7);g.fill();}});
const mirrorSmudge=new THREE.Mesh(new THREE.PlaneGeometry(0.56,0.74),new THREE.MeshBasicMaterial({map:smudgeTex,transparent:true,opacity:1,depthWrite:false}));mirrorSmudge.position.set(-2.825,1.55,-3.578);scene.add(mirrorSmudge);

/* ---------- living ---------- */
const rugTex=tex(520,360,(g,w,h)=>{g.fillStyle='#DCCDB6';g.fillRect(0,0,w,h);g.strokeStyle='#B98B6C';g.lineWidth=6;g.strokeRect(18,18,w-36,h-36);g.lineWidth=2;g.strokeRect(34,34,w-68,h-68);g.strokeStyle='rgba(120,90,60,.16)';g.lineWidth=1;for(let i=50;i<w-50;i+=8){g.beginPath();g.moveTo(i,50);g.lineTo(i,h-50);g.stroke();}});
const rug=rbox(2.6,0.012,1.8,0,M('#fff',0.98,0,{map:rugTex,envMapIntensity:0.2}),-2.7,0.006,1.05,AG.living);
const sofaM=M(C.sageDeep,0.95,0,{envMapIntensity:0.3}), cushM=M(C.sage,0.98,0,{envMapIntensity:0.3});
rbox(0.9,0.3,2.1,0.05,sofaM,-4.43,0.2,1.05); rbox(0.22,0.5,2.1,0.08,sofaM,-4.77,0.6,1.05);
rbox(0.9,0.26,0.2,0.08,sofaM,-4.43,0.5,0.1); rbox(0.9,0.26,0.2,0.08,sofaM,-4.43,0.5,2.0);
rbox(0.68,0.12,0.86,0.05,cushM,-4.32,0.41,0.62); rbox(0.68,0.12,0.86,0.05,cushM,-4.32,0.41,1.48);
const pil=rbox(0.12,0.34,0.34,0.06,M('#D2A64A',0.95),-4.6,0.62,0.45); pil.rotation.x=0.2;
rbox(0.5,0.02,0.7,0.01,M('#E6DCCB',0.98),-4.3,0.48,1.7);
blob(-4.43,1.05,1.4,2.6);
cyl(0.45,0.45,0.035,M(C.wood,0.5),-2.8,0.38,1.05,AG.living,40); cyl(0.11,0.15,0.36,M(C.woodDark,0.6),-2.8,0.18,1.05,AG.living);
const books=new THREE.Group();books.userData.dyn=true;books.position.set(-2.55,0.4,1.0);AG.living.add(books);
const book1=rbox(0.24,0.035,0.17,0.006,M('#3D5A73'),0,0.018,0,books), book2=rbox(0.21,0.03,0.15,0.006,M('#E5DED2'),0.01,0.05,0.01,books);
books.rotation.y=0.6;
const armG=new THREE.Group(); armG.position.set(-1.6,0,2.7); armG.rotation.y=-2.5; scene.add(armG);
rbox(0.78,0.32,0.78,0.08,M(C.blue,0.95),0,0.22,0,armG); rbox(0.78,0.44,0.18,0.08,M(C.blue,0.95),0,0.55,-0.3,armG);
rbox(0.15,0.24,0.7,0.07,M(C.blue,0.95),-0.33,0.48,0.02,armG); rbox(0.15,0.24,0.7,0.07,M(C.blue,0.95),0.33,0.48,0.02,armG);
blob(-1.6,2.7,1.1,1.1);
/* credenza + lamp */
rbox(0.85,0.62,0.4,0.015,M(C.oak,0.6),-4.42,0.31,-0.95);
for(let i=0;i<5;i++) rbox(0.05,0.2+((i*7)%4)*0.03,0.18,0.005,M(['#3D5A73','#B98B6C','#8A977C','#D2A64A','#E5DED2'][i],0.8),-4.7+i*0.06,0.72+((i*7)%4)*0.015,-0.95);
rbox(0.12,0.12,0.12,0.01,M('#E9E1D3',0.8),-4.2,0.68,-0.95); const spare=sph(0.045,M('#F2EFEA',0.2),-4.2,0.785,-0.95); spare.scale.set(1,1.15,1);
cyl(0.012,0.012,1.45,M(C.ink),-4.62,0.73,-0.4); cyl(0.13,0.17,0.24,M('#F4EEE2',0.7,0,{emissive:new THREE.Color('#ffe9c4'),emissiveIntensity:.2}),-4.62,1.5,-0.4,scene,32); cyl(0.14,0.14,0.02,M(C.ink),-4.62,0.01,-0.4);
plant(-0.9,0,3.3,1.5,'#C9BBA6');
const winSmudge=new THREE.Mesh(new THREE.PlaneGeometry(0.9,1.1),new THREE.MeshBasicMaterial({map:smudgeTex,transparent:true,opacity:1,depthWrite:false}));winSmudge.rotation.y=Math.PI/2;winSmudge.position.set(-4.93,1.5,2.95);scene.add(winSmudge);
const dustTex=tex(256,256,(g,w)=>{const r=rng(9);for(let i=0;i<260;i++){g.fillStyle=`rgba(90,75,55,${0.15+r()*0.25})`;g.fillRect(r()*w,r()*w,1+r()*3,1+r()*3);}});
const rugDust=new THREE.Mesh(new THREE.PlaneGeometry(1.6,1.2),new THREE.MeshBasicMaterial({map:dustTex,transparent:true,opacity:1,depthWrite:false}));rugDust.rotation.x=-Math.PI/2;rugDust.position.set(-2.2,0.014,1.25);scene.add(rugDust);

/* ---------- desk corner + entry ---------- */
rbox(1.2,0.035,0.6,0.01,M(C.oak,0.55),4.2,0.74,3.1);
for(const [dx,dz] of [[-.55,-.26],[.55,-.26],[-.55,.26],[.55,.26]]) cyl(0.014,0.014,0.72,M(C.ink),4.2+dx,0.36,3.1+dz);
rbox(0.32,0.01,0.22,0.004,steel,4.15,0.763,3.12); const scr=rbox(0.32,0.21,0.01,0.004,M('#2B2A28',0.3),4.15,0.87,3.24); scr.rotation.x=-0.2;
const dch=new THREE.Group(); dch.position.set(4.2,0,2.5); dch.rotation.y=0.2; scene.add(dch); rbox(0.46,0.07,0.44,0.03,M('#2E2B27',0.7),0,0.46,0,dch); rbox(0.44,0.48,0.06,0.03,M('#2E2B27',0.7),0,0.74,-0.21,dch); cyl(0.025,0.025,0.42,steel,0,0.22,0,dch);
blob(4.2,3.0,1.6,1.0);
rbox(0.36,0.45,1.0,0.02,M(C.oak,0.6),4.7,0.225,-0.3); plant(4.6,0,-3.3,1.4);
/* curtains on the living-room window */
{const cm=M('#EEE6D7',0.95,0,{side:THREE.DoubleSide,envMapIntensity:0.3});
 for(const [z0,z1] of [[LWIN[0]-0.3,LWIN[0]+0.08],[LWIN[1]-0.08,LWIN[1]+0.13]]){const g=new THREE.PlaneGeometry(z1-z0,2.0,40,1);const p=g.attributes.position;
   for(let i=0;i<p.count;i++){const u=p.getX(i);p.setZ(i,Math.sin((u+z0)*44)*0.022);} g.computeVertexNormals();
   const m=new THREE.Mesh(g,cm);m.rotation.y=Math.PI/2;m.position.set(-4.82,1.27,(z0+z1)/2);m.castShadow=true;m.receiveShadow=true;scene.add(m);}
 cyl(0.012,0.012,1.44,brass,-4.8,2.3,(LWIN[0]-0.32+LWIN[1]+0.12)/2).rotation.x=Math.PI/2;}
/* framed print over the sofa */
{const art=tex(600,420,(g,w,h)=>{g.fillStyle='#EFE7DA';g.fillRect(0,0,w,h);g.fillStyle='#C99A2E';g.beginPath();g.arc(w*0.36,h*0.48,h*0.27,0,7);g.fill();
   g.fillStyle='#8A977C';g.fillRect(w*0.52,h*0.2,w*0.26,h*0.58);g.fillStyle='#3D5A73';g.beginPath();g.moveTo(w*0.18,h*0.86);g.lineTo(w*0.5,h*0.62);g.lineTo(w*0.82,h*0.86);g.fill();});
 rbox(0.03,0.72,1.02,0.01,M('#2A2622',0.5),-4.885,1.55,1.05);const pl=new THREE.Mesh(new THREE.PlaneGeometry(0.94,0.64),M('#fff',0.9,0,{map:art}));pl.rotation.y=Math.PI/2;pl.position.set(-4.868,1.55,1.05);scene.add(pl);}

/* tag area meshes with their own materials so each can be highlighted alone */
const areaMeshes={};
for(const id in AG){areaMeshes[id]=[];const cache=new Map();AG[id].traverse(o=>{if(o.isMesh&&!o.userData.noHi&&o.material&&!Array.isArray(o.material)&&o.material.emissive){let mm=cache.get(o.material);if(!mm){mm=o.material.clone();cache.set(o.material,mm);}o.material=mm;o.userData.area=id;areaMeshes[id].push(o);}});}

/* floor highlights for each area (studio only) */
const decalTex=tex(256,256,(g,w)=>{g.fillStyle='rgba(201,154,46,.10)';g.strokeStyle='rgba(201,154,46,.95)';g.lineWidth=5;g.setLineDash([18,12]);const r=36;g.beginPath();g.roundRect(6,6,w-12,w-12,r);g.fill();g.stroke();});
const DECALS={sink:[0.2,-2.95,1.5,1.4],trash:[-2.0,-2.38,0.9,1.3],table:[TX+0.1,TZ+0.15,2.4,2.0],light:[TX,TZ,0.9,0.9],bath:[-3.67,-2.42,2.3,2.2],living:[-2.7,1.05,2.9,2.1],window:[-4.55,2.95,0.8,1.2]};
const decals={};
for(const id in DECALS){const [x,z,w,d]=DECALS[id];const m=new THREE.Mesh(new THREE.PlaneGeometry(w,d),new THREE.MeshBasicMaterial({map:decalTex,transparent:true,opacity:0,depthWrite:false,toneMapped:false}));m.rotation.x=-Math.PI/2;m.position.set(x,id==='light'?0.775:0.018,z);m.renderOrder=3;scene.add(m);decals[id]=m;}

/* ---------- merge static furniture into a few draw calls ---------- */
const callsBefore=(()=>{let n=0;scene.traverse(o=>{if(o.isMesh)n++;});return n;})();
(function mergeStatic(){
  scene.updateMatrixWorld(true); const groups=new Map();
  scene.traverse(o=>{
    if(!o.isMesh||o.isInstancedMesh||Array.isArray(o.material)||o.material.isShaderMaterial||o.material.transparent) return;
    for(let p=o;p;p=p.parent) if(p.userData.dyn) return;
    if(o===slab||o===bathFloor) return;
    const m=o.material, sig=[m.type,m.color&&m.color.getHexString(),m.roughness,m.metalness,m.map&&m.map.uuid,m.bumpMap&&m.bumpMap.uuid,m.emissive&&m.emissive.getHexString(),m.emissiveIntensity,m.envMapIntensity,m.side,m.vertexColors].join('|');
    const key=sig+'|'+(o.userData.area||'')+'|'+o.castShadow+'|'+o.receiveShadow; if(!groups.has(key)) groups.set(key,[]); groups.get(key).push(o);
  });
  for(const list of groups.values()){
    if(list.length<2) continue;
    const geos=list.map(m=>{let g=m.geometry.index?m.geometry.toNonIndexed():m.geometry.clone();g.applyMatrix4(m.matrixWorld);
      for(const n of Object.keys(g.attributes)) if(!['position','normal','uv'].includes(n)) g.deleteAttribute(n); if(!g.attributes.uv) g.setAttribute('uv',new THREE.BufferAttribute(new Float32Array(g.attributes.position.count*2),2)); g.clearGroups(); return g;});
    let merged; try{merged=mergeGeometries(geos,false);}catch(e){merged=null;} if(!merged) continue;
    const mm=new THREE.Mesh(merged,list[0].material); mm.castShadow=list[0].castShadow; mm.receiveShadow=list[0].receiveShadow;
    if(list[0].userData.area) mm.userData.area=list[0].userData.area; scene.add(mm);
    for(const m of list){ m.parent.remove(m); }
  }
  for(const id in areaMeshes) areaMeshes[id]=[];
  scene.traverse(o=>{ if(o.isMesh&&o.userData.area&&areaMeshes[o.userData.area]&&!areaMeshes[o.userData.area].includes(o)) areaMeshes[o.userData.area].push(o); });
})();

/* ---------- humanoid on tracks ---------- */
const robot=new THREE.Group(); scene.add(robot);
const body=new THREE.Group(); robot.add(body);
const RC=M(C.cream,0.38,0.05,{envMapIntensity:0.8}), RG=M('#2C2925',0.5,0.1), RD=M('#16140F',0.15,0.2,{envMapIntensity:1});
const LED=new THREE.MeshStandardMaterial({color:'#FFD27A',emissive:new THREE.Color('#FFC24A'),emissiveIntensity:2.2,roughness:0.3});
const trackG=new THREE.Group(); body.add(trackG);
for(const sx of [-0.17,0.17]){rbox(0.09,0.15,0.48,0.07,RG,sx,0.085,0,trackG);for(const sz of [0.2,-0.2]){const w=cyl(0.048,0.048,0.094,brass,sx,0.085,sz,trackG,20);w.rotation.z=Math.PI/2;}}
const CLE=16, cleats=new THREE.InstancedMesh(new THREE.BoxGeometry(0.1,0.016,0.03),M('#1A1815',0.7),CLE*2); cleats.castShadow=true; trackG.add(cleats);
rbox(0.3,0.12,0.48,0.045,RC,0,0.22,0,body); rbox(0.312,0.02,0.492,0.008,brass,0,0.17,0,body);
rbox(0.18,0.036,0.012,0.006,RD,0,0.23,0.245,body); rbox(0.11,0.007,0.004,0,LED,0,0.23,0.252,body);
cyl(0.06,0.07,0.32,RG,0,0.44,0,body,28);
const inner=cyl(0.046,0.046,0.34,M('#D8D2C8',0.25,0.7),0,0.55,0,body,24);
const torso=new THREE.Group(); torso.position.set(0,0.62,0); body.add(torso);
rbox(0.25,0.1,0.17,0.04,RG,0,0.05,0,torso);
rbox(0.34,0.42,0.21,0.08,RC,0,0.33,0,torso);
rbox(0.2,0.02,0.012,0.006,brass,0,0.42,0.106,torso);
const chestLED=rbox(0.045,0.045,0.01,0.012,LED,0,0.31,0.107,torso);
cyl(0.034,0.04,0.07,RG,0,0.575,0,torso,20);
const head=new THREE.Group(); head.position.set(0,0.6,0); torso.add(head);
rbox(0.2,0.19,0.18,0.075,RC,0,0.095,0,head);
rbox(0.16,0.07,0.012,0.03,RD,0,0.1,0.09,head);
sph(0.011,LED,-0.034,0.1,0.097,head); sph(0.011,LED,0.034,0.1,0.097,head);
sph(0.034,RC,-0.068,0.195,-0.01,head); sph(0.034,RC,0.068,0.195,-0.01,head);
sph(0.017,brass,-0.068,0.2,0.014,head); sph(0.017,brass,0.068,0.2,0.014,head);
const L1=0.30,L2=0.30,HAND=0.09;
function makeArm(side){
  const sh=new THREE.Group(); sh.position.set(0.215*side,0.5,0); sh.rotation.order='YXZ'; torso.add(sh);
  sph(0.052,RG,0,0,0,sh);
  const up=new THREE.Mesh(new THREE.CapsuleGeometry(0.041,L1-0.09,6,14),RC); up.position.y=-L1/2; up.castShadow=true; sh.add(up);
  const el=new THREE.Group(); el.position.y=-L1; sh.add(el); sph(0.04,RG,0,0,0,el);
  const fo=new THREE.Mesh(new THREE.CapsuleGeometry(0.036,L2-0.08,6,14),RC); fo.position.y=-L2/2; fo.castShadow=true; el.add(fo);
  rbox(0.078,0.02,0.078,0.008,brass,0,-L2+0.04,0,el);
  const wr=new THREE.Group(); wr.position.y=-L2; el.add(wr);
  rbox(0.14,0.042,0.05,0.016,RG,0,-0.024,0,wr);
  const fingers=[]; for(const s of [-1,1]) fingers.push(rbox(0.016,0.085,0.03,0.006,RD,0.05*s,-0.088,0,wr));
  const pad=rbox(0.13,0.03,0.09,0.012,M('#E8C95A',0.95),0,-0.075,0,wr); pad.visible=false;
  return {sh,el,wr,fingers,pad,side};
}
const armR=makeArm(-1), armL=makeArm(1), ARMS=[armR,armL];
/* backpack battery and shoulder plates */
rbox(0.24,0.26,0.07,0.03,RG,0,0.34,-0.13,torso); rbox(0.16,0.02,0.072,0.008,brass,0,0.42,-0.13,torso);
for(const sx of [-1,1]){const pl=rbox(0.11,0.05,0.13,0.025,RC,0.2*sx,0.545,0,torso);pl.rotation.z=-0.25*sx;}
for(const sx of [-0.152,0.152]) for(const sz of [-0.18,0,0.18]) sph(0.01,brass,sx,0.24,sz,body);
robot.traverse(o=>{if(o.isMesh)o.castShadow=false;});
const rShadow=blob(0,0,0.9,1.0,0.006); rShadow.material=rShadow.material.clone();
robot.visible=false; rShadow.visible=false;

/* ---------- occupancy grid + A* ---------- */
const OB=[
  [4.05,4.88,1.26,1.36],
  [-5,5,-3.7,-3.6],[-5,-4.9,-3.7,3.7],[4.9,5,-3.7,0.45],[4.9,5,1.26,3.7],[-5,5,3.6,3.7],[-2.45,-2.35,-3.6,-1.15],[-4.9,-3.86,-1.25,-1.15],[-3.05,-2.35,-1.25,-1.15],
  [-4.9,-4.0,-3.6,-2.7],[-3.8,-3.3,-3.6,-2.95],[-3.2,-2.45,-3.6,-3.1],[-2.32,-1.98,-2.77,-1.98],[-1.9,1.9,-3.6,-2.99],[2.0,2.76,-3.6,-2.86],
  [TX-0.75,TX+0.75,TZ-0.45,TZ+0.88],[TX+0.76,TX+1.2,TZ-0.22,TZ+0.22],[-4.88,-3.98,0.0,2.1],[-3.25,-2.35,0.6,1.5],[-2.05,-1.15,2.25,3.15],
  [-4.85,-4.0,-1.15,-0.75],[-4.75,-4.45,-0.55,-0.25],[3.6,4.8,2.8,3.4],[3.95,4.45,2.25,2.75],[4.52,4.88,-0.8,0.2],[4.45,4.8,-3.5,-3.1],[-1.1,-0.7,3.1,3.5]];
const GX0=-5,GZ0=-3.7,RES=0.05,NX=Math.round(11.4/RES),NZ=Math.round(7.4/RES),INFL=0.3;
const occ=new Uint8Array(NX*NZ);
function inRegion(x,z){return (x>-4.9&&x<4.9&&z>-3.6&&z<3.6)||(x>=4.85&&x<6.0&&z>0.62&&z<1.09);}
function distRect(x,z,o){const dx=Math.max(o[0]-x,0,x-o[1]),dz=Math.max(o[2]-z,0,z-o[3]);return Math.hypot(dx,dz);}
function blocked(x,z,r=INFL){ if(!inRegion(x,z)) return true; for(const o of OB) if(distRect(x,z,o)<r) return true; return false; }
for(let j=0;j<NZ;j++)for(let i=0;i<NX;i++) occ[j*NX+i]=blocked(GX0+(i+0.5)*RES,GZ0+(j+0.5)*RES)?1:0;
const cellOf=(x,z)=>[clamp(Math.floor((x-GX0)/RES),0,NX-1),clamp(Math.floor((z-GZ0)/RES),0,NZ-1)];
const posOf=(i,j)=>[GX0+(i+0.5)*RES,GZ0+(j+0.5)*RES];
function nearestFree(i,j){ if(!occ[j*NX+i]) return [i,j]; for(let r=1;r<40;r++) for(let dj=-r;dj<=r;dj++) for(let di=-r;di<=r;di++){ if(Math.max(Math.abs(di),Math.abs(dj))!==r) continue; const a=i+di,b=j+dj; if(a>=0&&b>=0&&a<NX&&b<NZ&&!occ[b*NX+a]) return [a,b]; } return [i,j]; }
function astar(sx,sz,gx,gz){
  let [si,sj]=nearestFree(...cellOf(sx,sz)), [gi,gj]=nearestFree(...cellOf(gx,gz));
  const N=NX*NZ,g=new Float32Array(N).fill(Infinity),came=new Int32Array(N).fill(-1),closed=new Uint8Array(N);
  const heap=[],push=(n,f)=>{heap.push([f,n]);let k=heap.length-1;while(k>0){const p=(k-1)>>1;if(heap[p][0]<=heap[k][0])break;[heap[p],heap[k]]=[heap[k],heap[p]];k=p;}};
  const pop=()=>{const top=heap[0],last=heap.pop();if(heap.length){heap[0]=last;let k=0;for(;;){const l=2*k+1,r=l+1;let m=k;if(l<heap.length&&heap[l][0]<heap[m][0])m=l;if(r<heap.length&&heap[r][0]<heap[m][0])m=r;if(m===k)break;[heap[m],heap[k]]=[heap[k],heap[m]];k=m;}}return top;};
  const h=(i,j)=>{const dx=Math.abs(i-gi),dz=Math.abs(j-gj);return (dx+dz)+(Math.SQRT2-2)*Math.min(dx,dz);};
  const s=sj*NX+si,goal=gj*NX+gi; g[s]=0; push(s,h(si,sj));
  const D=[[1,0,1],[-1,0,1],[0,1,1],[0,-1,1],[1,1,Math.SQRT2],[1,-1,Math.SQRT2],[-1,1,Math.SQRT2],[-1,-1,Math.SQRT2]];
  while(heap.length){const [,n]=pop(); if(closed[n]) continue; closed[n]=1; if(n===goal) break; const i=n%NX,j=(n-i)/NX;
    for(const [di,dj,c] of D){const a=i+di,b=j+dj;if(a<0||b<0||a>=NX||b>=NZ)continue;const m=b*NX+a;if(occ[m]||closed[m])continue;if(di&&dj&&(occ[j*NX+a]||occ[b*NX+i]))continue;const ng=g[n]+c;if(ng<g[m]){g[m]=ng;came[m]=n;push(m,ng+h(a,b));}}}
  if(came[goal]<0&&goal!==s) return null;
  const cells=[];for(let n=goal;n!==-1;n=came[n]){cells.push(n);if(n===s)break;} cells.reverse();
  return cells.map(n=>{const i=n%NX;return posOf(i,(n-i)/NX);});
}
function los(a,b,r){const d=Math.hypot(b[0]-a[0],b[1]-a[1]),n=Math.ceil(d/0.03);for(let k=0;k<=n;k++){const t=k/n,x=lerp(a[0],b[0],t),z=lerp(a[1],b[1],t);if(blocked(x,z,r))return false;}return true;}
function planPath(from,to){
  const raw=astar(from.x,from.z,to.x,to.z);
  let pts=[[from.x,from.z]];
  if(raw&&raw.length>1){ let k=0; const simp=[raw[0]]; while(k<raw.length-1){ let j=raw.length-1; while(j>k+1&&!los(raw[k],raw[j],INFL-0.02)) j--; simp.push(raw[j]); k=j; } pts.push(...simp); }
  pts.push([to.x,to.z]);
  pts=pts.filter((p,i)=>i===0||Math.hypot(p[0]-pts[i-1][0],p[1]-pts[i-1][1])>0.06);
  if(pts.length<2) pts.push([to.x+0.001,to.z]);
  const v3=pts.map(p=>V(p[0],0,p[1]));
  let curve=v3.length>2?new THREE.CatmullRomCurve3(v3,false,'centripetal'):new THREE.LineCurve3(v3[0],v3[1]);
  if(v3.length>2){ let ok=true; for(let s=1;s<120;s++){const p=curve.getPointAt(s/120); if(p.distanceTo(v3[v3.length-1])<0.45||p.distanceTo(v3[0])<0.45) continue; if(blocked(p.x,p.z,0.2)){ok=false;break;}}
    if(!ok){ const cp=new THREE.CurvePath(); for(let i=0;i<v3.length-1;i++) cp.add(new THREE.LineCurve3(v3[i],v3[i+1])); curve=cp; } }
  return curve;
}
let stepH=0.12;
const floorY=x=>x>5.08?-stepH:x<4.86?0:-stepH*sstep(4.86,5.08,x);

/* ---------- ribbon trails ---------- */
const NS=260;
function makeRibbon(NS=260){
  const mat=new THREE.ShaderMaterial({transparent:true,depthWrite:false,side:THREE.DoubleSide,toneMapped:false,
    uniforms:{uHead:{value:0},uStart:{value:0},uTime:{value:0},uLen:{value:5},uFade:{value:1},uFlutter:{value:reduce?0:1}},
    vertexShader:`attribute float aS;attribute float aSide;uniform float uHead,uTime,uLen,uFlutter;varying float vS,vSide;
      void main(){vS=aS;vSide=aSide;vec3 p=position;float b=(uHead-aS)*uLen;float lift=exp(-max(b,0.)/0.7)*step(0.,b);
      p.y+=lift*(0.04+0.06*uFlutter*(0.5+0.5*sin(uTime*3.4-b*6.)));gl_Position=projectionMatrix*modelViewMatrix*vec4(p,1.);}`,
    fragmentShader:`uniform float uHead,uStart,uTime,uLen,uFade;varying float vS,vSide;
      void main(){if(vS>uHead||vS<uStart)discard;float b=(uHead-vS)*uLen;vec3 g1=vec3(.79,.60,.18),g2=vec3(.98,.84,.47);
      float f=fract(vS*uLen/1.6-uTime*.35);float sheen=smoothstep(0.,.2,f)*(1.-smoothstep(.2,.45,f));
      vec3 col=mix(g1,g2,sheen*.7+(1.-abs(vSide))*.15);float edge=1.-pow(abs(vSide),8.);gl_FragColor=vec4(col,mix(.35,.95,exp(-b/3.))*edge*uFade);}`});
  const geo=new THREE.BufferGeometry();
  geo.setAttribute('position',new THREE.BufferAttribute(new Float32Array(NS*6),3));
  const aS=new Float32Array(NS*2),aSide=new Float32Array(NS*2),idx=[];
  for(let i=0;i<NS;i++){aS[i*2]=aS[i*2+1]=i/(NS-1);aSide[i*2]=-1;aSide[i*2+1]=1;if(i<NS-1){const a=i*2;idx.push(a,a+1,a+2,a+1,a+3,a+2);}}
  geo.setAttribute('aS',new THREE.BufferAttribute(aS,1));geo.setAttribute('aSide',new THREE.BufferAttribute(aSide,1));geo.setIndex(idx);
  const mesh=new THREE.Mesh(geo,mat);mesh.frustumCulled=false;mesh.renderOrder=2;mesh.visible=false;mesh.userData.n=NS;scene.add(mesh);return mesh;
}
const ribbons=[makeRibbon(),makeRibbon()]; let rib=0;
function setRibbon(mesh,curve,len){
  const pos=mesh.geometry.attributes.position.array,W=0.07,p=V(0,0,0),t=V(0,0,0),NS=mesh.userData.n;
  for(let i=0;i<NS;i++){const u=i/(NS-1);curve.getPointAt(u,p);curve.getTangentAt(Math.min(u,0.999),t);const nx=-t.z,nz=t.x,l=Math.hypot(nx,nz)||1;const y=floorY(p.x)+0.022;
    pos.set([p.x-nx/l*W,y,p.z-nz/l*W,p.x+nx/l*W,y,p.z+nz/l*W],i*6);}
  mesh.geometry.attributes.position.needsUpdate=true; mesh.material.uniforms.uLen.value=len; mesh.material.uniforms.uHead.value=0; mesh.material.uniforms.uFade.value=1; mesh.visible=true;
}

/* ---------- sparkles + labels ---------- */
const sparkTex=tex(64,64,(g,w)=>{const r=g.createRadialGradient(w/2,w/2,0,w/2,w/2,w/2);r.addColorStop(0,'rgba(255,230,160,1)');r.addColorStop(.4,'rgba(240,190,80,.6)');r.addColorStop(1,'rgba(240,190,80,0)');g.fillStyle=r;g.fillRect(0,0,w,w);});
const sparks=[];for(let i=0;i<18;i++){const s=new THREE.Sprite(new THREE.SpriteMaterial({map:sparkTex,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,opacity:0}));s.scale.setScalar(0.07);scene.add(s);sparks.push({s,v:V(0,0,0),life:0});}
function burst(at){sparks.forEach((p,i)=>{p.s.position.copy(at);const a=i/sparks.length*Math.PI*2;p.v.set(Math.cos(a)*0.6,0.5+Math.random()*0.5,Math.sin(a)*0.6);p.life=1;});}
const labelLayer=$('#labels');
const toast=document.createElement('div');toast.className='toast3d';labelLayer.appendChild(toast);let toastT=0;const toastPos=V(0,0,0);
function showToast(){}

/* dimension lines per area, shown only for the selected area */
const DIMS={
  sink:[[V(-0.25,0,-2.97),V(-0.25,0.91,-2.97),'Counter 0.91 m'],[V(0.62,0.95,-2.99),V(0.62,0.95,-3.45),'Faucet 0.46 m back']],
  trash:[[V(-1.93,0,-2.6),V(-1.93,0.66,-2.6),'Bin 0.66 m']],
  table:[[V(TX+0.78,0,TZ+0.46),V(TX+0.78,0.76,TZ+0.46),'Table 0.76 m'],[V(TX-0.75,0.8,TZ+0.52),V(TX+0.75,0.8,TZ+0.52),'1.50 m']],
  light:[[V(TX+0.32,0,TZ),V(TX+0.32,1.6,TZ),'Bulb 1.60 m'],[V(TX,0.8,TZ-0.45),V(TX,0.8,TZ),'0.45 m in']],
  bath:[[V(-3.86,1.12,-1.2),V(-3.05,1.12,-1.2),'Door 0.81 m (0.76 clear)'],[V(-3.25,0,-3.0),V(-3.25,0.76,-3.0),'Tank 0.76 m']],
  living:[[V(-4.0,0.03,2.05),V(-1.4,0.03,2.05),'Rug 2.60 m']],
  window:[[V(-4.86,0,2.3),V(-4.86,0.9,2.3),'Sill 0.90 m'],[V(-4.86,0.9,2.3),V(-4.86,2.1,2.3),'1.20 m']]
};
const dimLineMat=new THREE.LineBasicMaterial({color:'#8E6A16',depthTest:false,transparent:true,opacity:0.95});
const dimObjs={};
for(const id in DIMS){const g=new THREE.Group();g.visible=false;scene.add(g);g.renderOrder=5;const labels=[];
  for(const [a,b,text] of DIMS[id]){const dir=b.clone().sub(a).normalize();const n=Math.abs(dir.y)>0.9?V(0.07,0,0):V(0,0.06,0);
    const geo=new THREE.BufferGeometry().setFromPoints([a,b,a.clone().add(n),a.clone().sub(n),b.clone().add(n),b.clone().sub(n)]);const l=new THREE.LineSegments(geo,dimLineMat);l.renderOrder=5;g.add(l);
    const el=document.createElement('div');el.className='dim3d';el.textContent=text;labelLayer.appendChild(el);labels.push({el,pos:a.clone().add(b).multiplyScalar(0.5)});}
  dimObjs[id]={g,labels};}

/* ---------- world state for chores ---------- */
const W0={bulbOn:false,drip:true,spill:1,winSmudge:1,mirrorSmudge:1,dust:1,bagIn:true,chairsOut:true};
const world={...W0};
function resetWorld(){Object.assign(world,W0);}

/* ---------- stations and action timelines ---------- */
const P=Math.PI;
const ST={faucet:[0.2,-2.66,P],drain:[0.2,-2.66,P],pipes:[0.2,-2.66,P],trash:[-1.4,-2.6,-P/2],liner:[-1.4,-2.6,-P/2],recycle:[-1.4,-2.15,-P/2],
  wipe:[TX-1.1,TZ-0.05,P/2],chairs:[TX,0.55,P],bulb:[TX,-1.62,0],toilet:[-3.6,-2.66,P],vanity:[-2.86,-2.85,P],mirror:[-2.86,-2.85,P],
  vacuum:[-1.72,1.25,-P/2],tidy:[-1.95,1.0,-P/2],window:[-4.32,2.95,-P/2]};
const tmp=V(0,0,0);
/* each returns pose for progress p in [0,1] */
function pose(act,p){
  const reach=sstep(0,0.22,p)*(1-sstep(0.84,1,p));
  const o={lift:0,lean:0.3*reach,head:0,target:null,reach,roll:0,close:0,open:0,fwd:0,pad:false};
  const mid=(a,b)=>bell(a,a+0.06,b-0.06,b,p);
  switch(act){
    case 'wipe':{o.lean=0.5*reach;o.pad=true;const q=clamp((p-0.2)/0.62);o.target=V(TX-0.5+0.17*Math.sin(q*P*4)*mid(0.2,0.84),0.8,TZ+0.02+0.17*Math.sin(q*P*2));o.head=0.25*reach;break;}
    case 'bulb':{o.lift=0.3*sstep(0,0.3,p)*(1-sstep(0.88,1,p));o.lean=0.45*reach;o.head=-0.42*reach;o.open=sstep(0.15,0.3,p);o.close=sstep(0.42,0.5,p)*(1-sstep(0.8,0.86,p));o.roll=(P/2)*sstep(0.5,0.72,p);
      o.target=BULB.clone();o.target.y-=0.07*(1-sstep(0.3,0.42,p));break;}
    case 'faucet':{o.lean=0.45*reach;o.target=V(0.27,1.03,-3.48);o.close=sstep(0.3,0.38,p)*(1-sstep(0.78,0.84,p));o.roll=0.7*Math.sin((p-0.35)*P*8)*mid(0.35,0.78);o.head=0.2*reach;break;}
    case 'drain':{o.lean=0.45*reach;o.target=V(0.2,0.97+0.05*Math.sin(p*P*10)*mid(0.3,0.8),-3.28);o.head=0.35*reach;break;}
    case 'vanity':{o.lean=0.45*reach;o.target=V(-2.825,0.92+0.04*Math.sin(p*P*10)*mid(0.3,0.8),-3.32);o.head=0.35*reach;break;}
    case 'pipes':{o.lean=0.6*reach;o.target=V(0.2,0.5,-2.97);o.head=0.5*reach;break;}
    case 'trash':case 'liner':case 'recycle':{const bz=act==='recycle'?-2.15:-2.6;o.lean=0.45*reach;o.head=0.35*reach;o.close=sstep(0.4,0.48,p)*(1-sstep(0.86,0.92,p));
      o.target=V(-2.15,lerp(0.82,0.5,bell(0.25,0.35,0.42,0.55,p))+0.35*sstep(0.55,0.75,p)*(act==='recycle'?0:1),bz);break;}
    case 'chairs':{o.lean=0.35*reach;o.target=V(TX-0.36,0.82,chairs[0].position.z+0.2);break;}
    case 'toilet':{o.lean=0.5*reach;o.target=V(-3.74,0.71,-3.4);o.close=sstep(0.32,0.4,p)*(1-sstep(0.8,0.86,p));o.roll=0.5*Math.sin((p-0.4)*P*6)*mid(0.4,0.8);o.head=0.3*reach;break;}
    case 'mirror':{o.lift=0.18*reach;o.lean=0.45*reach;o.pad=true;const q=clamp((p-0.2)/0.62);o.target=V(-2.825+0.17*Math.cos(q*P*6),1.55+0.17*Math.sin(q*P*6)*mid(0.2,0.84),-3.53);break;}
    case 'window':{o.lift=0.18*reach;o.lean=0.3*reach;o.pad=true;const q=clamp((p-0.2)/0.62);o.target=V(-4.88,1.5+0.22*Math.sin(q*P*6)*mid(0.2,0.84),2.95+0.25*Math.cos(q*P*6));break;}
    case 'vacuum':{o.lean=0.25*reach;o.head=0.4*reach;o.fwd=0.28*Math.sin(p*P*4)*mid(0.1,0.9);o.target='floor';o.pad=true;break;}
    case 'tidy':{o.lean=0.6*reach;o.head=0.4*reach;o.target=V(-2.55,0.47+0.08*bell(0.4,0.5,0.6,0.7,p),1.0);o.close=sstep(0.38,0.45,p)*(1-sstep(0.72,0.8,p));break;}
  }
  return o;
}
function applyEffects(act,p){
  if(act==='wipe') world.spill=Math.min(world.spill,1-sstep(0.25,0.8,p));
  if(act==='bulb'){ if(p>0.74) world.bulbOn=true; }
  if(act==='faucet'&&p>0.7) world.drip=false;
  if(act==='mirror') world.mirrorSmudge=Math.min(world.mirrorSmudge,1-sstep(0.25,0.8,p));
  if(act==='window') world.winSmudge=Math.min(world.winSmudge,1-sstep(0.25,0.8,p));
  if(act==='vacuum') world.dust=Math.min(world.dust,1-sstep(0.15,0.85,p));
  if(act==='chairs'){renderer.shadowMap.needsUpdate=true;const k=sstep(0.35,0.7,p);chairs[0].position.z=lerp(chairOut[0],chairOut[0]-0.18,k);chairs[1].position.z=lerp(chairOut[1],chairOut[1]-0.18,k);if(p>0.7)world.chairsOut=false;}
  if(act==='tidy'){books.rotation.y=lerp(0.6,0,sstep(0.45,0.7,p));}
}

/* ---------- robot controller ---------- */
const R={mode:'hidden',curve:null,len:0,d:0,v:0,yaw:-P/2,act:null,actT:0,dur:3.4,pose:pose('none',0),arm:null,onDone:null,tread:0,appear:0,appearV:0,shown:false,fwd:0};
const sm={lift:0,lean:0,head:0,roll:0,close:0,open:0,fwd:0};
const START=V(5.75,0,0.855), DOCK=V(4.05,0,0.855);
function goTo(act,onDone,dur){
  const [sx,sz,yaw]=ST[act]; const from=V(robot.position.x,0,robot.position.z), to=V(sx,0,sz);
  R.act=act; R.stationYaw=yaw; R.onDone=onDone; R.dur=dur;
  if(from.distanceTo(to)<0.08){R.mode='turn';return;}
  R.curve=planPath(from,to); R.len=R.curve.getLength(); R.d=0; R.mode='drive';
  const old=ribbons[rib]; rib^=1; old.userData.fading=true; setRibbon(ribbons[rib],R.curve,R.len); ribbons[rib].userData.fading=false;
}
function goHome(){ const from=V(robot.position.x,0,robot.position.z); if(from.distanceTo(DOCK)<0.1){R.mode='idle';return;} R.act=null;R.stationYaw=-P/2;R.onDone=()=>{R.mode='idle';};R.dur=0;
  R.curve=planPath(from,DOCK);R.len=R.curve.getLength();R.d=0;R.mode='drive';const old=ribbons[rib];rib^=1;old.userData.fading=true;setRibbon(ribbons[rib],R.curve,R.len);ribbons[rib].userData.fading=false;}
/* landing: a scroll-driven tour. Scroll position maps straight onto the robot's progress around the home. */
const TOUR_ACTS=['wipe','bulb','faucet','trash','toilet','window','vacuum'];
const TOUR=[]; let tourLen=0, tourDrive=0; const tourPath=new THREE.CurvePath();
{ let from=START.clone();
  for(const act of TOUR_ACTS){
    const [sx,sz,yaw]=ST[act], to=V(sx,0,sz), curve=planPath(from,to), len=curve.getLength(), tEnd=curve.getTangentAt(0.999);
    TOUR.push({type:'drive',curve,len,w:len,d0:tourDrive}); tourDrive+=len; tourPath.add(curve);
    TOUR.push({type:'turn',act,yaw,yawIn:Math.atan2(tEnd.x,tEnd.z),pos:to,w:0.35,dEnd:tourDrive});
    TOUR.push({type:'act',act,yaw,pos:to,w:1.5,dEnd:tourDrive});
    from=to; }
  let c=0; for(const sg of TOUR){sg.t0=c;c+=sg.w;sg.t1=c;} tourLen=c; }
const tourRibbon=makeRibbon(Math.ceil(tourDrive/0.04)); setRibbon(tourRibbon,tourPath,tourDrive); tourRibbon.visible=false;
{let u0=0;for(let i=0;i<=400;i++){const p=tourPath.getPointAt(i/400);if(p.x<4.35){u0=i/400;break;}} tourRibbon.material.uniforms.uStart.value=u0;}
let Td=0, tourJump=true, curSeg=null, prevTd=0, prevDist=0;
function tourStep(dt){
  const max=document.documentElement.scrollHeight-H, y0=6, y1=Math.max(y0+300,max-0.06*H);
  const Tt=clamp((scrollY-y0)/(y1-y0))*tourLen;
  if(tourJump||reduce){Td=Tt;tourJump=false;}
  else {const cap=7.5*dt; Td+=clamp((Tt-Td)*(1-Math.exp(-6*dt)),-cap,cap);}
  const T=Td; let seg=TOUR[TOUR.length-1]; for(const sg of TOUR){ if(T<sg.t1){seg=sg;break;} }
  const q=clamp((T-seg.t0)/seg.w); if(seg!==curSeg){curSeg=seg;R.arm=null;}
  let dist;
  if(seg.type==='drive'){
    dist=seg.d0+q*seg.len; seg.curve.getPointAt(q,v1); seg.curve.getTangentAt(clamp(q,0.001,0.999),v2);
    robot.position.set(v1.x,floorY(v1.x),v1.z);
    if(Math.hypot(v2.x,v2.z)>1e-4){let dy=Math.atan2(v2.x,v2.z)-R.yaw;dy=Math.atan2(Math.sin(dy),Math.cos(dy));R.yaw+=dy*Math.min(1,dt*12);}
    R.mode='tour'; R.act=null;
  } else {
    dist=seg.dEnd; robot.position.set(seg.pos.x,floorY(seg.pos.x),seg.pos.z);
    if(seg.type==='turn'){let dy=seg.yaw-seg.yawIn;dy=Math.atan2(Math.sin(dy),Math.cos(dy));R.yaw=seg.yawIn+dy*sstep(0,1,q);R.mode='tour';R.act=null;}
    else {R.yaw=seg.yaw;R.mode='act';R.act=seg.act;R.actT=q;R.pose=pose(seg.act,q);}
  }
  const dd=dist-prevDist; prevDist=dist; R.tread+=dd;
  // the home reflects how far the tour has got, so scrolling back undoes the chores
  for(const sg of TOUR){ if(sg.type!=='act') continue; const qq=clamp((T-sg.t0)/sg.w);
    if(sg.act==='wipe') world.spill=1-sstep(0.25,0.8,qq);
    if(sg.act==='bulb') world.bulbOn=qq>0.74;
    if(sg.act==='faucet') world.drip=qq<0.7;
    if(sg.act==='window') world.winSmudge=1-sstep(0.25,0.8,qq);
    if(sg.act==='vacuum') world.dust=1-sstep(0.15,0.85,qq);
  }
  prevTd=T;
  tourRibbon.material.uniforms.uHead.value=dist/tourDrive; tourRibbon.visible=R.appear>0.02&&dist>0.02;
  return Math.abs(dd)/Math.max(dt,1e-3);
}
function toastAnchor(act){const [x,z]=ST[act];return V(x,1.75,z);}
function placeAtDock(){robot.position.set(DOCK.x,0,DOCK.z);R.yaw=-P/2;}

/* ---------- studio: select, hover, run ---------- */
let selected=null, hovered=null, currentRun=null;
API.hover=id=>{hovered=id;};
API.select=(id,fly)=>{
  selected=id; setAreaButtons(id);
  for(const k in dimObjs) dimObjs[k].g.visible=(k===id);
  if(id){showAreaCard(id); if(fly) driveToView(id); showPrompt();}
};
API.run=(act,text,ui)=>{
  const area=ACT_AREA[act]; selected=area; setAreaButtons(area); for(const k in dimObjs) dimObjs[k].g.visible=(k===area);
  if(R.appear<0.5) placeAtDock();
  cancelDrive(); CAM.aim=VIEWS[area]?VIEWS[area][2].clone():null;
  // reset the chore so it can be shown again
  if(act==='bulb') world.bulbOn=false; if(act==='faucet') world.drip=true; if(act==='wipe') world.spill=1; if(act==='mirror') world.mirrorSmudge=1; if(act==='window') world.winSmudge=1; if(act==='vacuum') world.dust=1;
  if(act==='chairs'){chairs[0].position.z=chairOut[0];chairs[1].position.z=chairOut[1];renderer.shadowMap.needsUpdate=true;}
  if(act==='tidy') books.rotation.y=0.6;
  currentRun=ui||null;
  if(ui) ui.status(`Driving to the ${AREA[area].name.toLowerCase()}`);
  goTo(act,()=>{if(ui) ui.finish(DONE[act]);if(currentRun===ui) currentRun=null;R.mode='idle';},4.4);
};

/* ---------- studio: you are the robot ---------- */
const DOOR_LOOK=V(0.2,1.0,-0.9), ROBOT_R=0.26;
const CAM={yaw:0,pitch:-0.08,ry:0,rp:-0.08,aim:null,bob:0,userT:-1e9,eye:V(0,0,0),eyeInit:false};
const angD=(a,b)=>Math.atan2(Math.sin(b-a),Math.cos(b-a));
function aimAt(x,y,z,t){const dx=t.x-x,dy=t.y-y,dz=t.z-z;return [Math.atan2(-dx,-dz),Math.atan2(dy,Math.hypot(dx,dz))];}
const inside=(x,z,r)=>!blocked(x,z,r)&&x<4.62;          // the front door is closed to you
const eyeTmp=V(0,0,0);
function eyePos(){robot.updateMatrixWorld(true);return head.localToWorld(eyeTmp.set(0,0.11,0.07));}
function becomeRobot(){
  robot.position.set(DOCK.x,0,DOCK.z); R.yaw=-P/2; robot.rotation.y=R.yaw; R.mode='idle'; R.act=null; R.arm=null; R.onDone=null; R.pose=pose('none',0);
  const e=eyePos(); [CAM.yaw,CAM.pitch]=aimAt(e.x,e.y,e.z,DOOR_LOOK); CAM.ry=CAM.yaw; CAM.rp=CAM.pitch; CAM.aim=null; CAM.eye.copy(e); CAM.eyeInit=true; tv=0;
}
const walkRing=new THREE.Mesh(new THREE.RingGeometry(0.16,0.2,40),new THREE.MeshBasicMaterial({color:'#C99A2E',transparent:true,opacity:0.9,toneMapped:false,depthWrite:false}));walkRing.rotation.x=-Math.PI/2;walkRing.visible=false;scene.add(walkRing);
function cancelDrive(){ if(R.mode==='drive'||R.mode==='turn'||R.mode==='act'){R.mode='idle';R.act=null;R.onDone=null;R.arm=null;R.v=0;} walkRing.visible=false; ribbons.forEach(r=>{if(r.visible)r.userData.fading=true;}); }
function driveTo(p,look){
  let goal=V(p.x,0,Math.min(p.z,3.3)); goal.x=Math.min(goal.x,4.5);
  if(!inside(goal.x,goal.z,ROBOT_R)){const [i,j]=nearestFree(...cellOf(Math.min(goal.x,4.4),goal.z));const [x,z]=posOf(i,j);goal=V(Math.min(x,4.4),0,z);}
  const from=V(robot.position.x,0,robot.position.z);
  const t0=performance.now(); R.act=null; R.onDone=()=>{R.mode='idle';walkRing.visible=false;if(look&&CAM.userT<t0)CAM.aim=look.clone();};
  R.stationYaw=look?Math.atan2(look.x-goal.x,look.z-goal.z):R.yaw;
  if(from.distanceTo(goal)<0.12){R.mode='turn';return;}
  R.curve=planPath(from,goal); R.len=R.curve.getLength(); R.d=0; R.v=0; R.mode='drive';
  if(!look){const t=R.curve.getTangentAt(0.999);R.stationYaw=Math.atan2(t.x,t.z);}
  const old=ribbons[rib]; rib^=1; old.userData.fading=true; setRibbon(ribbons[rib],R.curve,R.len); ribbons[rib].userData.fading=false;
  walkRing.position.set(goal.x,0.02,goal.z); walkRing.visible=true;
}
const VIEWS={sink:[0.7,-2.15,V(0.2,0.95,-3.35)],trash:[-1.05,-1.95,V(-2.15,0.55,-2.4)],table:[1.85,0.55,V(TX,0.76,TZ)],light:[1.6,0.45,V(TX,1.5,TZ)],
  bath:[-3.45,-0.55,V(-3.55,0.8,-3.0)],living:[-1.0,0.25,V(-3.0,0.35,1.3)],window:[-3.1,2.95,V(-4.95,1.5,2.95)]};
function driveToView(id){const v=VIEWS[id];if(v) driveTo(V(v[0],0,v[1]),v[2]);}
const keys=new Set(), pad={f:0,b:0,l:0,r:0};
addEventListener('keydown',e=>{ if(!inStudio||space.current?.kind==='scan'||typing()) return;
  if(['KeyW','KeyA','KeyS','KeyD','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','ShiftLeft','ShiftRight'].includes(e.code)){keys.add(e.code); if(e.code.startsWith('Arrow')) e.preventDefault();} });
addEventListener('keyup',e=>keys.delete(e.code)); addEventListener('blur',()=>keys.clear());
onSpaceChange(()=>{keys.clear();mv=0;tv=0;});
$$('[data-pad]').forEach(b=>{const k=b.dataset.pad;const on=e=>{e.preventDefault();pad[k]=1;b.classList.add('on');},off=()=>{pad[k]=0;b.classList.remove('on');};
  b.addEventListener('pointerdown',on);b.addEventListener('pointerup',off);b.addEventListener('pointerleave',off);b.addEventListener('pointercancel',off);});
let mv=0, tv=0;
/* W/S drive, A/D turn on the spot, like a tracked robot */
function driveManual(dt){
  const kd=c=>keys.has(c);
  const fwd=(kd('KeyW')||kd('ArrowUp')||pad.f?1:0)-(kd('KeyS')||kd('ArrowDown')||pad.b?1:0);
  const turn=(kd('KeyA')||kd('ArrowLeft')||pad.l?1:0)-(kd('KeyD')||kd('ArrowRight')||pad.r?1:0);
  if(fwd||turn){ if(R.mode!=='idle'&&R.mode!=='between'){ cancelDrive(); if(currentRun){currentRun.status('Stopped: you took the controls');currentRun=null;} } R.mode='idle'; CAM.aim=null; }
  tv+=(turn*1.8-tv)*(1-Math.exp(-dt*(turn?7:10))); if(Math.abs(tv)>1e-4){const w=tv*dt;R.yaw+=w;CAM.yaw+=w;R.tread+=Math.abs(w)*0.17;}
  let target=0;
  if(fwd){ // ease the body toward where you're looking while rolling
    const want=CAM.yaw+P, d=angD(R.yaw,want), st=d*(1-Math.exp(-dt*4)); R.yaw+=st; R.tread+=Math.abs(st)*0.17;
    target=fwd*((kd('ShiftLeft')||kd('ShiftRight'))?2.3:1.35)*Math.pow(Math.max(0,Math.cos(d)),2);
  }
  mv+=(target-mv)*(1-Math.exp(-dt*(target?4.5:7)));
  if(Math.abs(mv)>1e-3||Math.abs(tv)>1e-3){
    const dx=Math.sin(R.yaw)*mv*dt, dz=Math.cos(R.yaw)*mv*dt, x=robot.position.x, z=robot.position.z;
    if(inside(x+dx,z,ROBOT_R)) robot.position.x+=dx; if(inside(robot.position.x,z+dz,ROBOT_R)) robot.position.z+=dz;
    const moved=Math.hypot(robot.position.x-x,robot.position.z-z); if(moved<Math.abs(mv*dt)*0.3) mv*=0.5; R.tread+=Math.sign(mv)*moved;
    return moved/Math.max(dt,1e-3)+Math.abs(tv)*0.2;
  }
  return 0;
}
/* where the robot's eyes point */
function camFollow(dt,pz){
  const e=eyePos(), since=performance.now()-CAM.userT, free=since<3000, k=(1-Math.exp(-dt*4))*clamp((since-3000)/1500,0.15,1);
  if(R.mode==='act'&&pz.target&&!free){ const t=pz.target==='floor'?robot.localToWorld(V(0,0.1,0.7)):pz.target; const [y,p]=aimAt(e.x,e.y,e.z,t); CAM.yaw+=angD(CAM.yaw,y)*k; CAM.pitch+=(p-CAM.pitch)*k; }
  else if((R.mode==='drive'||R.mode==='turn')&&!free){ CAM.yaw+=angD(CAM.yaw,R.yaw+P)*k; CAM.pitch+=(-0.12-CAM.pitch)*k; }
  else if(CAM.aim&&!free){ const [y,p]=aimAt(e.x,e.y,e.z,CAM.aim); CAM.yaw+=angD(CAM.yaw,y)*k; CAM.pitch+=(p-CAM.pitch)*k; if(Math.abs(angD(CAM.yaw,y))<0.004&&Math.abs(p-CAM.pitch)<0.004) CAM.aim=null; }
  CAM.pitch=clamp(CAM.pitch,-1.25,1.2);
  // rendered view eases toward the target, so mouse look and turns glide instead of snapping
  const kv=1-Math.exp(-dt*(reduce?60:16)); CAM.ry+=(CAM.yaw-CAM.ry)*kv; CAM.rp+=(CAM.pitch-CAM.rp)*kv;
  if(!CAM.eyeInit){CAM.eye.copy(e);CAM.eyeInit=true;} else CAM.eye.lerp(e,1-Math.exp(-dt*22));
  return CAM.eye;
}
$('#resetView').addEventListener('click',()=>{driveTo(DOCK,DOOR_LOOK);});
/* in the studio, scrolling up leaves; scrolling down shows how to walk */
let wheelAcc=0,wheelT=0,tipT=null; const zoomTip=$('#zoomTip');
addEventListener('wheel',e=>{
  if(!inStudio||e.target!==canvas) return;
  e.preventDefault(); e.stopPropagation();
  const dy=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?innerHeight:1), now=performance.now();
  wheelAcc=Math.min(0,wheelAcc)*Math.exp(-(now-wheelT)/1200); wheelT=now;
  if(dy<0){ wheelAcc+=dy; if(wheelAcc<-90){wheelAcc=0;exitStudio();} }

},{capture:true,passive:false});
/* drag to look, click the floor to walk, click a glowing object for its tasks */
const ray=new THREE.Raycaster(), ndc=new THREE.Vector2(); let downAt=null, lastPt=null, dragging=false;
const allAreaMeshes=Object.values(areaMeshes).flat(), floorMeshes=[slab,bathFloor];
canvas.addEventListener('pointerdown',e=>{ if(!inStudio) return; downAt=[e.clientX,e.clientY]; lastPt=[e.clientX,e.clientY]; dragging=false; try{canvas.setPointerCapture(e.pointerId);}catch(_){} });
canvas.addEventListener('pointermove',e=>{ if(!inStudio) return;
  if(downAt&&e.pointerType==='mouse'&&e.buttons===0){downAt=null;dragging=false;}
  if(downAt){ const dx=clamp(e.clientX-lastPt[0],-60,60), dy=clamp(e.clientY-lastPt[1],-60,60); lastPt=[e.clientX,e.clientY];
    if(Math.hypot(e.clientX-downAt[0],e.clientY-downAt[1])>4) dragging=true;
    if(dragging){ CAM.yaw+=dx*0.0038; CAM.pitch=clamp(CAM.pitch+dy*0.0032,-1.25,1.2); CAM.aim=null; CAM.userT=performance.now(); canvas.style.cursor='grabbing'; } return; }
  ndc.set(e.clientX/W*2-1,-(e.clientY/H)*2+1); ray.setFromCamera(ndc,camera); const hit=ray.intersectObjects(allAreaMeshes,false)[0]; hovered=hit?hit.object.userData.area:null; canvas.style.cursor=hit?'pointer':'grab'; });
canvas.addEventListener('pointerup',e=>{ if(!inStudio||!downAt) return; const wasDrag=dragging; downAt=null; dragging=false; canvas.style.cursor='grab'; if(wasDrag) return;
  ndc.set(e.clientX/W*2-1,-(e.clientY/H)*2+1); ray.setFromCamera(ndc,camera);
  const h=ray.intersectObjects([...allAreaMeshes,...floorMeshes],false)[0]; if(h&&h.object.userData.area) API.select(h.object.userData.area,true); });
canvas.addEventListener('dblclick',e=>{ if(!inStudio||keys.size) return; ndc.set(e.clientX/W*2-1,-(e.clientY/H)*2+1); ray.setFromCamera(ndc,camera);
  const h=ray.intersectObjects([...allAreaMeshes,...floorMeshes],false)[0]; if(h&&!h.object.userData.area) driveTo(h.point,null); });
canvas.addEventListener('pointercancel',()=>{downAt=null;dragging=false;});
canvas.addEventListener('lostpointercapture',()=>{downAt=null;dragging=false;canvas.style.cursor='grab';});
addEventListener('blur',()=>{downAt=null;dragging=false;});

/* camera hand-off between the landing view and first person */
let blend=null, rise=0;
const qTmp=new THREE.Quaternion(), eTmp=new THREE.Euler(0,0,0,'YXZ');
function startBlend(dur){blend={p:camera.position.clone(),q:camera.quaternion.clone(),fov:camera.fov,off:curOff,k:0,dur:reduce?0.01:dur,up:inStudio};}
enterHooks.push(instant=>{
  R.appear=1; R.appearV=0; becomeRobot(); mv=0;
  tourRibbon.userData.fading=true; keys.clear();
  if(instant||campus){blend=null;rise=1;renderer.shadowMap.needsUpdate=true;} else startBlend(1.4);   // from the campus there is no shared camera to blend from
});
exitHooks.push(()=>{
  API.select(null,false); card.classList.remove('show'); cancelDrive(); walkRing.visible=false; keys.clear(); currentRun=null;
  startBlend(1.3);
  // pop back in at the tour position that matches the scroll
  R.appear=0; R.appearV=0; tourJump=true; curSeg=null; prevTd=1e9; prevDist=0;
  ribbons.forEach(r=>{r.visible=false;r.userData.fading=false;}); tourRibbon.userData.fading=false; tourRibbon.material.uniforms.uFade.value=1;
});

/* ---------- layout ---------- */
let W=1,H=1,mob=false;
function measure(){W=innerWidth;H=innerHeight;mob=W<900;renderer.setSize(W,H,false);camera.aspect=W/H;camera.updateProjectionMatrix();if(campus)campus.resize(W,H,mob);}
addEventListener('resize',measure); measure();
addEventListener('pointermove',e=>{mx=e.clientX/W-0.5;my=e.clientY/H-0.5;},{passive:true});
let mx=0,my=0;

/* ---------- main loop ---------- */
const TS=1; const clock=new THREE.Clock(); const camTarget=V(0.2,0.4,0), camPos=V(0,0,0), dummy=new THREE.Object3D(), v1=V(0,0,0), v2=V(0,0,0);
let sideS=1, studioK=0, curOff=0;
function solveArm(a,target,k){
  torso.updateWorldMatrix(true,false);
  const T=torso.worldToLocal(target.clone()),d=T.sub(a.sh.position);
  const psi=Math.atan2(d.x,d.z),h=Math.hypot(d.x,d.z),vv=d.y,Le=L2+HAND,D=Math.min(d.length(),L1+Le-1e-3);
  const at=Math.atan2(h,-vv),g=Math.acos(clamp((L1*L1+D*D-Le*Le)/(2*L1*D),-1,1)),beta=P-Math.acos(clamp((L1*L1+Le*Le-D*D)/(2*L1*Le),-1,1));
  a.sh.rotation.set(lerp(a.sh.rotation.x,-(at-g),k),lerp(a.sh.rotation.y,psi,k),lerp(a.sh.rotation.z,0,k));
  a.el.rotation.x=lerp(a.el.rotation.x,-beta,k);
}
function pickArm(target){ robot.updateMatrixWorld(true); const a=armR.sh.getWorldPosition(V(0,0,0)).distanceTo(target), b=armL.sh.getWorldPosition(V(0,0,0)).distanceTo(target); return a<=b?armR:armL; }
let first=true, ftAcc=0, ftN=0, lastUp=0;
function tick(){
  const raw=clock.getDelta(), dt=Math.min(raw,0.05)*TS, time=clock.elapsedTime*TS;
  if(inStudio&&space.cover&&!blend){requestAnimationFrame(tick);return;}   // a scan covers the page: rest the 3D
  ftAcc+=raw; ftN++; if(ftN>=40){const avg=ftAcc/ftN; ftAcc=0; ftN=0;
    if(avg>1/50&&dpr>1){dpr=Math.max(1,dpr-0.25);renderer.setPixelRatio(dpr);renderer.setSize(W,H,false);}
    else if(avg<1/58&&dpr<DPR_MAX&&clock.elapsedTime-lastUp>3){lastUp=clock.elapsedTime;dpr=Math.min(DPR_MAX,dpr+0.25);renderer.setPixelRatio(dpr);renderer.setSize(W,H,false);}}
  const rdt=dt;
  /* the landing (and the moment the hall's tour fades in) shows the campus model */
  if(campus&&(!inStudio||space.current?.kind==='scan')){
    const {fade}=campus.update(dt,inStudio?1:landingProgress(),reduce?0:mx,reduce?0:my);
    // the walk-in cross-fades straight into the hall's live tour when it has loaded; else to paper
    const peek=!inStudio&&fade>0.001&&tourReady();
    root.classList.toggle('tour-peek',peek); root.style.setProperty('--tour-in',peek?fade.toFixed(3):'0'); peekSpace(peek);
    veil.style.opacity=inStudio?1:(peek?0:fade.toFixed(3));
    renderer.render(campus.scene,campus.camera);
    requestAnimationFrame(tick); return;
  }
  veil.style.opacity=0; root.classList.remove('tour-peek');
  /* appear: the robot pops in on the first scroll and out again at the very top */
  const appearT=inStudio?1:(scrollY>6?1:0);
  R.appearV+=(appearT-R.appear)*(reduce?400:120)*dt; R.appearV*=Math.exp(-13*dt); R.appear+=R.appearV*dt; if(reduce) R.appear=appearT;
  robot.visible=R.appear>0.01; rShadow.visible=robot.visible;
  /* robot state */
  let speed=0; bag.visible=false;
  if(!inStudio){ speed=tourStep(dt); }
  else if((!blend||blend.k>0.7)&&(R.mode==='idle'||R.mode==='between'||keys.size||pad.f||pad.b||pad.l||pad.r)&&(speed=driveManual(dt),R.mode==='idle'||R.mode==='between')){ }
  else if(R.mode==='drive'){
    const vmax=1.5, acc=2.4, rem=R.len-R.d;
    R.v=Math.min(vmax,R.v+acc*rdt,Math.sqrt(2*acc*Math.max(rem,0))+0.05); R.d=Math.min(R.len,R.d+R.v*rdt); speed=R.v;
    const u=R.d/R.len; R.curve.getPointAt(u,v1); R.curve.getTangentAt(Math.min(u,0.999),v2);
    robot.position.set(v1.x,floorY(v1.x),v1.z); R.tread+=R.v*rdt;
    if(Math.hypot(v2.x,v2.z)>1e-4){let dy=Math.atan2(v2.x,v2.z)-R.yaw;dy=Math.atan2(Math.sin(dy),Math.cos(dy));R.yaw+=dy*(1-Math.exp(-dt*6));}
    ribbons[rib].material.uniforms.uHead.value=u;
    if(R.d>=R.len-1e-4){R.v=0;R.mode='turn';}
  } else if(inStudio&&R.mode==='turn'){
    let dy=R.stationYaw-R.yaw;dy=Math.atan2(Math.sin(dy),Math.cos(dy)); const step=Math.sign(dy)*Math.min(Math.abs(dy),Math.max(rdt*0.6,Math.abs(dy)*(1-Math.exp(-rdt*5)))); R.yaw+=step; R.tread+=Math.abs(step)*0.17;
    if(Math.abs(dy)<0.01){ R.yaw=R.stationYaw; if(R.act){R.mode='act';R.actT=0;R.arm=null;} else {R.mode='idle'; R.onDone&&R.onDone();} }
  } else if(inStudio&&R.mode==='act'){
    R.actT+=rdt/R.dur; const p=Math.min(1,R.actT); R.pose=pose(R.act,p); applyEffects(R.act,p);
    if(currentRun&&inStudio&&R.act) currentRun.status(p<0.85?'Working · '+Math.round(p*100)+'%':'Checking the result');
    if(p>=1){ const a=R.act; R.mode='between'; R.pose=pose('none',0); const tip=(R.arm?R.arm.wr.getWorldPosition(V(0,0,0)):robot.position.clone().add(V(0,1.2,0))); burst(tip); const cb=R.onDone; R.onDone=null; R.act=null; cb&&cb(a); }
  }
  if(R.mode!=='act') R.pose=pose('none',0);
  robot.rotation.y=R.yaw;
  tourRibbon.material.uniforms.uTime.value=time; if(tourRibbon.userData.fading){const f=tourRibbon.material.uniforms.uFade;f.value=Math.max(0,f.value-dt*0.8);if(f.value<=0)tourRibbon.visible=false;}
  ribbons.forEach(r=>{r.material.uniforms.uTime.value=time; if(r.userData.fading){r.material.uniforms.uFade.value=Math.max(0,r.material.uniforms.uFade.value-dt*0.8); if(r.material.uniforms.uFade.value<=0) r.visible=false;}});
  robot.scale.setScalar(Math.max(1e-4,R.appear)); rShadow.position.set(robot.position.x,robot.position.y+0.006,robot.position.z); rShadow.rotation.z=R.yaw; rShadow.material.opacity=clamp(R.appear);
  /* smooth pose */
  const k=1-Math.exp(-dt*7), pz=R.pose;
  for(const key of ['lift','lean','head','roll','close','open','fwd']) sm[key]+=(pz[key]-sm[key])*k;
  /* tracks */
  const Ls=0.4,Rr=0.072,Pp=2*Ls+2*P*Rr;
  for(let s2=0;s2<2;s2++){const sx=s2?0.17:-0.17;for(let i=0;i<CLE;i++){let u=((i/CLE)*Pp+R.tread)%Pp;if(u<0)u+=Pp;let z,yy,ang;
    if(u<Ls){z=Ls/2-u;yy=0.085-Rr;ang=0;}else if(u<Ls+P*Rr){const a=(u-Ls)/Rr;z=-Ls/2-Math.sin(a)*Rr;yy=0.085-Math.cos(a)*Rr;ang=-a;}
    else if(u<2*Ls+P*Rr){z=-Ls/2+(u-Ls-P*Rr);yy=0.085+Rr;ang=P;}else{const a=(u-2*Ls-P*Rr)/Rr;z=Ls/2+Math.sin(a)*Rr;yy=0.085+Math.cos(a)*Rr;ang=P-a;}
    dummy.position.set(sx,yy,z);dummy.rotation.set(ang,0,0);dummy.updateMatrix();cleats.setMatrixAt(s2*CLE+i,dummy.matrix);}}
  cleats.instanceMatrix.needsUpdate=true;
  /* body */
  body.position.y=(reduce||inStudio)?0:Math.sin(time*9)*0.004*Math.min(1,speed);
  body.position.z=sm.fwd;
  torso.position.y=0.62+sm.lift; inner.position.y=0.55+sm.lift*0.55;
  torso.rotation.x=sm.lean+((reduce||inStudio)?0:Math.min(0.08,speed*0.035));
  head.rotation.x=inStudio?0:sm.head; head.rotation.y=(inStudio||reduce||R.mode==='act')?0:Math.sin(time*0.8)*0.18;
  chestLED.material.emissiveIntensity=1.6+Math.sin(time*2.4)*0.6;
  head.visible=!(inStudio&&(!blend||blend.k>0.8));
  const sw=reduce?0:Math.sin(R.tread*5)*0.18*Math.min(1,speed);
  for(const [a,dir] of [[armL,1],[armR,-1]]){a.sh.rotation.set(-0.12+sw*dir,0,0.08*-dir);a.el.rotation.x=-0.35;a.wr.rotation.set(0,0,0);a.pad.visible=false;
    a.fingers.forEach((f,i)=>f.position.x=(i?1:-1)*0.05);}
  if(R.mode==='act'&&pz.target){
    robot.updateMatrixWorld(true);
    let tgt=pz.target==='floor'?robot.localToWorld(V(0.0,0.14,0.6)):pz.target;
    if(!R.arm) R.arm=pickArm(tgt);
    const a=R.arm; solveArm(a,tgt,pz.reach); a.wr.rotation.y=sm.roll; a.pad.visible=pz.pad&&pz.reach>0.3;
    a.fingers.forEach((f,i)=>f.position.x=(i?1:-1)*(0.05+0.035*sm.open-0.022*sm.close));
    if((R.act==='trash'||R.act==='liner')&&R.actT>0.5){bag.visible=true;a.wr.getWorldPosition(bag.position);bag.position.y-=0.2;bag.scale.setScalar(R.actT>0.88?Math.max(0.01,1-(R.actT-0.88)*8):1);}
  }
  /* trash lids */
  const lidOpen=(R.mode==='act'&&(R.act==='trash'||R.act==='liner'||R.act==='recycle'))?bell(0.15,0.3,0.78,0.92,R.actT):0;
  const lidBin=(R.act==='recycle')?recBin:trashBin; trashBin.lid.rotation.x+=((lidBin===trashBin?-1.4*lidOpen:0)-trashBin.lid.rotation.x)*k; recBin.lid.rotation.x+=((lidBin===recBin?-1.4*lidOpen:0)-recBin.lid.rotation.x)*k;
  /* world visuals */
  const on=world.bulbOn?1:0; bulbMat.emissiveIntensity+=(on*3-bulbMat.emissiveIntensity)*k; bulbLight.intensity+=(on*5-bulbLight.intensity)*k; halo.material.opacity+=(on*0.85-halo.material.opacity)*k; halo.visible=halo.material.opacity>0.01;
  bulbG.rotation.y=(R.mode==='act'&&R.act==='bulb')?sm.roll:bulbG.rotation.y;
  spill.material.opacity=0.55*world.spill; spill.visible=world.spill>0.01;
  winSmudge.material.opacity=0.55*world.winSmudge; mirrorSmudge.material.opacity=0.5*world.mirrorSmudge; rugDust.material.opacity=world.dust;
  if(world.drip){const c=(time*1.4)%1;drip.visible=true;drip.position.set(spoutTip.x,lerp(spoutTip.y,0.925,c*c),spoutTip.z);drip.scale.setScalar(c<0.08?c/0.08:1);} else drip.visible=false;
  sparks.forEach(sp=>{if(sp.life>0){sp.life-=dt*1.2;sp.v.y-=dt*1.4;sp.s.position.addScaledVector(sp.v,dt);sp.s.material.opacity=Math.max(0,sp.life);sp.s.visible=true;}else{sp.s.material.opacity=0;sp.s.visible=false;}});
  /* studio highlights */
  studioK+=((inStudio?1:0)-studioK)*(1-Math.exp(-dt*4));
  for(const id in decals){const act=(id===selected)?1:(id===hovered?0.8:0.4);decals[id].material.opacity=studioK*(act+(reduce?0:0.12*Math.sin(time*3+id.length)));decals[id].visible=studioK>0.01;}
  for(const id in areaMeshes){const kk=studioK*(id===selected?0.32:id===hovered?0.22:0);for(const m of areaMeshes[id]){m.material.emissive.setRGB(0.79*kk,0.6*kk,0.18*kk);}}
  /* camera */
  let fov=30, off=0;
  if(!inStudio){
    const hero=1-clamp(R.appear);
    const t=V(0.35*(1-hero)+0.4*hero,0.4,0.15*hero).lerp(V(robot.position.x,0.5,robot.position.z),0.42*clamp(R.appear));
    camTarget.lerp(t,first?1:1-Math.exp(-dt*2.2));
    const dist=(mob?24:18.5)+hero*1.0, az=0.74+(reduce?0:mx*0.06), el=0.6+(reduce?0:-my*0.03);
    camPos.set(Math.sin(az)*Math.cos(el),Math.sin(el),Math.cos(az)*Math.cos(el)).multiplyScalar(dist).add(camTarget);
    camera.position.copy(camPos); camera.lookAt(camTarget);
    off=-(mob?0:0.17*W*(1-hero));
  } else {
    const e=camFollow(dt,pz);
    camera.position.copy(e);
    eTmp.set(CAM.rp,CAM.ry,0,'YXZ'); camera.quaternion.setFromEuler(eTmp);
    fov=mob?78:70;
    const Rw=mob?0:flowOpen()?392:card.classList.contains('show')?352:0; off=Rw/2;
  }
  if(blend){
    blend.k=Math.min(1,blend.k+dt/blend.dur); const e=blend.k<.5?4*blend.k**3:1-Math.pow(-2*blend.k+2,3)/2;
    qTmp.copy(camera.quaternion); const p1=camera.position.clone();
    // arc over the top so the camera drops into the room from above (and rises out the same way)
    const c=V(blend.up?p1.x:blend.p.x,Math.max(blend.p.y,p1.y,7),blend.up?p1.z:blend.p.z);
    camera.position.set(0,0,0).addScaledVector(blend.p,(1-e)*(1-e)).addScaledVector(c,2*(1-e)*e).addScaledVector(p1,e*e);
    camera.quaternion.slerpQuaternions(blend.q,qTmp,e); fov=lerp(blend.fov,fov,e); off=lerp(blend.off,off,e);
    if(blend.k>=1) blend=null;
  }
  if(Math.abs(camera.fov-fov)>1e-3){camera.fov=fov;camera.updateProjectionMatrix();}
  curOff=off; camera.setViewOffset(W,H,off,0,W,H);
  /* walls rise inside the studio */
  rise+=((inStudio?1:0)-rise)*(1-Math.exp(-dt*(inStudio?2.2:3)));
  for(const g of risers){g.visible=rise>0.01;g.scale.y=Math.max(0.001,rise);}
  ceil.visible=inStudio&&rise>0.9;
  walkRing.material.opacity=0.6+0.3*Math.sin(time*5);
  first=false;
  /* overlays */
  const proj=(p)=>{v2.copy(p).project(camera);return [(v2.x*0.5+0.5)*W,(-v2.y*0.5+0.5)*H,v2.z<1];};
  for(const id in dimObjs){const show=dimObjs[id].g.visible&&inStudio;for(const l of dimObjs[id].labels){const [x,y,vis]=proj(l.pos);l.el.style.transform=`translate(${(x+8).toFixed(1)}px,${(y-11).toFixed(1)}px)`;l.el.style.opacity=show&&vis?1:0;}}
  if(toastT>0){toastT-=dt;const [x,y,vis]=proj(toastPos);toast.style.transform=`translate(${(x-50).toFixed(1)}px,${(y-16).toFixed(1)}px)`;toast.style.opacity=vis?Math.min(1,toastT*3,(2.2-toastT)*5).toFixed(2):0;} else toast.style.opacity=0;
  renderer.render(scene,camera);
  requestAnimationFrame(tick);
}
boot();
requestAnimationFrame(tick);
}
