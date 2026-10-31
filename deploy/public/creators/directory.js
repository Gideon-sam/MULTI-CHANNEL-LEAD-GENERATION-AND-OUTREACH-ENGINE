'use strict';
const $ = id => document.getElementById(id);
const labels = {identity:'Creator identity',country:'Creator country',language:'English content',commercial:'Commercial activity',need:'Content workflow need',contact:'Primary business contact',contact_activity:'Recent contact activity',backup:'Separate backup contact'};
const state = {rows:[],filtered:[],page:0,pageSize:50,version:'',details:new Map(),selected:null,request:0};
function node(tag, text, cls) {const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n;}
function display(value) {return value===null||value===undefined||value===''?'Not recorded':String(value);}
function safeURL(value) {try {const u=new URL(value);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password?u.href:null;}catch{return null;}}
function link(text,value) {const url=safeURL(value);if(!url)return node('span','Link not recorded','sub');const a=node('a',text,'button');a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
function verdict(value) {return value==='Approve'?'User approved':value==='Reject'?'User rejected':'Awaiting review';}
function badge(value) {return node('span',verdict(value),`badge ${value==='Approve'?'approved':value==='Reject'?'rejected':''}`);}
function showError(message) {$('error').hidden=false;$('error-text').textContent=message;}
async function getJSON(path) {const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);try {const r=await fetch(path,{signal:controller.signal,cache:path.includes('manifest')?'no-store':'default'});if(!r.ok)throw new Error(`HTTP ${r.status}`);return await r.json();}finally{clearTimeout(timer);}}
async function load() {
  $('error').hidden=true;
  try {
    const manifest=await getJSON('data/manifest.json');
    if(!/^[a-f0-9]{16}$/.test(manifest.version))throw new Error('Invalid data version');
    const data=await getJSON(`data/${manifest.version}/index.json`);
    if(!Array.isArray(data.rows))throw new Error('Invalid directory data');
    state.rows=data.rows;state.version=manifest.version;state.details.clear();
    for(const [id,value] of [['total',data.stats.total],['approved',data.stats.user_approved],['proof-complete',data.stats.proof_complete],['activity-total',data.stats.activity_pass]])$(id).textContent=Number(value).toLocaleString();
    $('source-summary').textContent=Object.entries(data.stats.platforms).map(([k,v])=>`${v.toLocaleString()} ${k} candidates`).join(' · ');
    $('updated').textContent=`Workbook snapshot published ${new Date(manifest.generated_at).toLocaleString()}`;
    $('country').replaceChildren(new Option('All countries',''),new Option('Not recorded','unset'));
    [...new Set(state.rows.map(r=>r.country).filter(Boolean))].sort().forEach(c=>$('country').append(new Option(c,c)));
    $('export').disabled=false;render();route();
  }catch(error){showError(`The dataset could not load (${error.name==='AbortError'?'request timed out':error.message}). Please retry.`);$('count').textContent='Dataset unavailable';$('rows').replaceChildren();const tr=node('tr');const td=node('td','Could not load creators. Use Try again above.','empty');td.colSpan=6;tr.append(td);$('rows').append(tr);}
}
function render() {
  const query=$('search').value.trim().toLowerCase(),platform=$('platform').value,v=$('verdict').value,c=$('country').value,p=$('proof').value,m=$('missing').value;
  state.filtered=state.rows.filter(r=>(!platform||r.platform===platform)&&(!v||r.verdict===v)&&(!c||(c==='unset'?!r.country:r.country===c))&&(!p||(p==='complete'?r.proof_count===8:r.proof_count<8))&&(!m||r.missing.includes(m))&&(!query||[r.name,r.show,r.id,r.contact].join(' ').toLowerCase().includes(query)));
  const sort=$('sort').value;
  state.filtered.sort((a,b)=>sort==='name'?a.name.localeCompare(b.name):sort==='proof'?b.proof_count-a.proof_count||a.rank-b.rank:sort==='recent'?b.latest.localeCompare(a.latest):sort==='activity'?(b.items30??-1)-(a.items30??-1):a.rank-b.rank);
  const pages=Math.max(1,Math.ceil(state.filtered.length/state.pageSize));state.page=Math.min(state.page,pages-1);
  $('rows').replaceChildren();
  for(const row of state.filtered.slice(state.page*state.pageSize,(state.page+1)*state.pageSize)){
    const tr=node('tr'),person=node('td'),wrap=node('div',undefined,'person'),text=node('div');
    wrap.append(node('span',row.name.split(/\s+/).slice(0,2).map(n=>n[0]||'').join('').toUpperCase(),'avatar'));
    text.append(node('span',row.name,'person-title'));if(row.show&&row.show!==row.name)text.append(node('span',row.show,'sub'));text.append(node('span',`${row.platform} · #${row.rank}`,'platform'));wrap.append(text);person.append(wrap);
    const decision=node('td');decision.append(badge(row.verdict),node('span','Final check outstanding','sub'));
    const proof=node('td');proof.append(node('strong',`${row.proof_count} / 8 pairs`));const bar=node('div',undefined,'proof-bar');bar.setAttribute('aria-hidden','true');for(let i=0;i<8;i++)bar.append(node('i',undefined,i<row.proof_count?'filled':''));proof.append(bar,node('span',row.proof_count===8?'Live recheck needed':`${8-row.proof_count} missing`,'sub'));
    const activity=node('td');activity.append(node('strong',`${display(row.items30)} / 30 days`),node('span',`${display(row.long60)} long-form / 60 days`,'sub'));
    const contact=node('td');contact.append(node('strong',row.country?`${row.country} · hint`:'Country not recorded'),node('span',row.channel||'Contact type not recorded','sub'),node('span',row.contact||'Contact not recorded','sub contact'));
    const action=node('td'),button=node('button','View details ↗','button');button.type='button';button.setAttribute('aria-label',`View details for ${row.name}`);button.addEventListener('click',()=>{location.hash=row.key;});action.append(button);tr.append(person,decision,proof,activity,contact,action);$('rows').append(tr);
  }
  if(!state.filtered.length){const tr=node('tr'),td=node('td','No creators match these filters. Reset filters to see the complete directory.','empty');td.colSpan=6;tr.append(td);$('rows').append(tr);}
  $('count').textContent=`${state.filtered.length.toLocaleString()} of ${state.rows.length.toLocaleString()} creators`;
  $('page-label').textContent=`Page ${state.page+1} of ${pages}`;$('previous').disabled=state.page===0;$('next').disabled=state.page+1>=pages;
}
function section(title){const s=node('section',undefined,'detail-section');s.append(node('h3',title));$('detail-body').append(s);return s;}
function fact(label,value){const item=node('div',undefined,'fact');item.append(node('span',label),node('strong',display(value)));return item;}
async function copy(value,button){try{await navigator.clipboard.writeText(value);button.textContent='Copied';}catch{button.textContent='Copy from text below';}setTimeout(()=>{button.textContent='Copy creator ID';},1800);}
async function openDetail(row){
  const request=++state.request;state.selected=row;
  $('detail-title').textContent=row.name;$('detail-subtitle').textContent=`${row.platform} · ${row.id}`;$('detail-body').replaceChildren(node('p','Loading evidence…','status-note'));
  if(!$('detail').open)$('detail').showModal();
  try {
    const chunkKey=`${state.version}/${row.chunk}`;
    if(!state.details.has(chunkKey))state.details.set(chunkKey,await getJSON(`data/${state.version}/details-${row.chunk}.json`));
    if(request!==state.request)return;
    const detail=state.details.get(chunkKey)[row.key];if(!detail)throw new Error('Record not found');
    const f=detail.facts;$('detail-body').replaceChildren();
    const toolbar=node('div',undefined,'detail-toolbar'),copyButton=node('button','Copy creator ID','button');copyButton.addEventListener('click',()=>copy(row.id,copyButton));toolbar.append(badge(row.verdict),node('span',`${row.proof_count}/8 stored evidence pairs`,'tag'),copyButton);$('detail-body').append(toolbar);
    const overview=section('Creator at a glance'),grid=node('div',undefined,'facts-grid');
    grid.append(fact('Country (research hint)',row.country),fact('Platform',row.platform),fact('Latest content date',row.latest),fact('Published items / 30 days',row.items30),fact('Long-form items / 60 days',row.long60),fact('Historical engine state',row.engine_status));overview.append(grid);
    const sources=section('Open the original sources'),links=node('div',undefined,'link-list');
    for(const [name,url] of [['Official website',f.official_site],['Creator profile',row.profile],['Canonical creator identity',f.canonical_identity],['Recent content',f.recent_content],['Publisher feed',f.feed]])if(safeURL(url))links.append(link(`${name} ↗`,url));
    sources.append(links.childNodes.length?links:node('p','Source links were not recorded for this creator.'));
    sources.append(node('p','Links open the recorded public pages. Their current availability has not been rechecked by this website.','status-note'));
    const fit=section('Why this creator may fit IncuBrix');fit.append(node('div',f.fit_reason||'A specific content-workflow fit reason has not been recorded.','fit'));fit.append(node('p','This is the stored research rationale. An inferred repurposing opportunity does not establish a creator’s stated need.','status-note'));fit.append(node('h4','Commercial activity'),node('p',f.commercial||'Commercial evidence is not recorded.'));
    const status=section('Why this record needs attention'),reasons=node('ul',undefined,'reason-list');
    const reasonsText=[];
    if(row.missing.length)reasonsText.push(`Missing stored URL/excerpt pairs: ${row.missing.map(k=>labels[k]).join(', ')}.`);else reasonsText.push('All eight proof pairs are present. Their meaning, freshness and source availability still need final validation.');
    if(!row.activity_pass)reasonsText.push('The stored counts do not establish the required activity threshold: 8 items in 30 days or 2 long-form items in 60 days.');
    if(!f.backup_contact)reasonsText.push('A separate backup contact address or URL is not recorded.');
    if(!f.contact_active_date)reasonsText.push('A date proving recent business-contact activity is not recorded.');
    if(f.possible_duplicate)reasonsText.push(`Possible duplicate identity: ${f.possible_duplicate}.`);
    if(row.reason)reasonsText.push(`Recorded engine reason: ${row.reason.replaceAll('_',' ')}.`);
    reasonsText.push(`Workbook evidence-import decision: ${f.import_decision}. User approval is tracked separately.`);
    for(const reason of reasonsText)reasons.append(node('li',reason));status.append(reasons);
    const contacts=section('Business contact routes'),contactGrid=node('div',undefined,'contacts');
    for(const [title,type,value,url] of [['Primary contact',row.channel,f.primary_contact,f.primary_contact_url],['Backup contact',f.backup_channel,f.backup_contact,f.backup_contact_url]]){const card=node('div',undefined,'contact-card');card.append(node('h4',title),node('span',display(type),'tag'),node('p',display(value)));if(safeURL(url))card.append(link('Open contact route ↗',url));contactGrid.append(card);}
    contacts.append(contactGrid,node('p',`Recorded primary-contact activity date: ${display(f.contact_active_date)}. Confirm ownership and business purpose using the evidence below. The site does not send messages.`,'status-note'));
    const evidence=section('Evidence trail — eight required checks');
    for(const proof of detail.proofs){const card=node('details',undefined,'proof-card'),head=node('summary');head.append(node('span',labels[proof.kind]),node('span',proof.present?'Pair recorded':'Missing evidence',`badge ${proof.present?'approved':''}`));card.append(head);const body=node('div',undefined,'proof-body');if(proof.url){const a=link(proof.url,proof.url);a.className='';body.append(a);}else body.append(node('p','Evidence URL not recorded.'));body.append(node('blockquote',proof.quote||'Exact source excerpt not recorded.'));body.append(node('p','Stored excerpt supplied with the research workbook. Retrieval date for this individual proof is not recorded in this export.'));card.append(body);evidence.append(card);}
    const timing=section('Research provenance'),dates=node('div',undefined,'facts-grid');dates.append(fact('Historical source group',row.source_group),fact('Record checked date',f.checked_date),fact('Feed retrieval time',f.feed_fetched_at));timing.append(dates,node('p','Activity windows are relative to the original collection date. A fresh qualification run is required before outreach.','status-note'));
    const messages=section('Outreach drafts');messages.append(node('p','Drafts from the workbook; use only after qualification and an authorized launch. Nothing has been sent.','status-note'));
    f.messages.forEach((message,i)=>{messages.append(node('h4',i?`Follow-up ${i}`:'First message'),node('p',message||'No draft recorded.','message'));});
  }catch(error){if(request===state.request)$('detail-body').replaceChildren(node('p',`Could not load evidence: ${error.message}. Close and reopen this creator to retry.`,'alert error'));}
}
function route(){const key=location.hash.slice(1);if(!key){if($('detail').open)$('detail').close();return;}const row=state.rows.find(r=>r.key===key);if(row)openDetail(row);}
for(const [kind,label] of Object.entries(labels))$('missing').append(new Option(label,kind));
$('filters').addEventListener('submit',e=>e.preventDefault());
for(const id of ['search','platform','verdict','country','proof','missing','sort'])$(id).addEventListener('input',()=>{state.page=0;render();});
$('clear').addEventListener('click',()=>{$('filters').reset();state.page=0;render();});
$('page-size').addEventListener('change',()=>{state.pageSize=Number($('page-size').value);state.page=0;render();});
$('previous').addEventListener('click',()=>{state.page--;render();});$('next').addEventListener('click',()=>{state.page++;render();});
$('close').addEventListener('click',()=>$('detail').close());
$('detail').addEventListener('close',()=>{state.request++;history.replaceState(null,'',location.pathname+location.search);});
window.addEventListener('hashchange',route);$('retry').addEventListener('click',load);
$('export').addEventListener('click',()=>{
  const fields=['id','name','show','platform','country','verdict','engine_status','proof_count','missing','items30','long60','latest','channel','contact','profile','reason'];
  function cell(value){let text=Array.isArray(value)?value.join('; '):String(value??'');if(/^[\s]*[=+\-@]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';}
  const lines=[fields.map(cell).join(','),...state.filtered.map(r=>fields.map(f=>cell(r[f])).join(','))];
  const url=URL.createObjectURL(new Blob(['\ufeff',lines.join('\r\n')],{type:'text/csv;charset=utf-8'}));const a=node('a');a.href=url;a.download='incubrix-creator-research.csv';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
try {const saved=localStorage.getItem('incubrix-directory-theme');if(['light','dark'].includes(saved))document.documentElement.dataset.theme=saved;}catch{}
$('theme').addEventListener('click',()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;try{localStorage.setItem('incubrix-directory-theme',theme);}catch{}});
load();
