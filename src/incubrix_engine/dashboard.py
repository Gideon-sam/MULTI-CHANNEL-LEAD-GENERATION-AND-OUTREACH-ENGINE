from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .files import write_text
from .models import Lead


def write_dashboard(
    leads: list[Lead], pending: list[Lead], rejected: list[Lead], summary: dict, path: Path
) -> None:
    rejected_rows = [
        {
            "creator_name": row.creator_name,
            "country_iso2": row.country_iso2,
            "stable_creator_id": row.stable_creator_id,
            "profile_url": row.profile_url,
            "source_feed_url": row.source_feed_url,
            "candidate_status": row.candidate_status,
            "rejection_reason": row.rejection_reason,
            "checked_date": row.checked_date,
            "longform_count_60d": row.longform_count_60d,
            "metadata": {"collection_name": row.metadata.get("collection_name", "")},
        }
        for row in rejected
    ]
    payload = json.dumps(
        {"summary": summary, "rows": [asdict(row) for row in leads + pending] + rejected_rows},
        ensure_ascii=False,
    )
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    document = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>IncuBrix / Evidence desk</title>
<style>
:root{--ink:#122d33;--muted:#526a70;--line:#d7e2e3;--green:#007969;--paper:#f4f7f5}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,sans-serif}header{background:#102f35;color:white;padding:32px max(24px,calc((100vw - 1320px)/2))}header small{color:#8ed7c2;letter-spacing:.15em;text-transform:uppercase}h1{font-size:36px;line-height:1.15;letter-spacing:-.04em;margin:14px 0}header p{max-width:760px;color:#c4d7d8}main{max-width:1368px;margin:auto;padding:24px}.notice{border-left:4px solid #bb7419;background:#fff7e9;padding:16px 20px;margin-bottom:24px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.card{padding:20px;border:1px solid var(--line);border-radius:12px;background:white}.card span{display:block;color:var(--muted);font-size:13px}.card b{font-size:32px;font-weight:600}.tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:24px 0 16px}input,select,button{font:inherit;padding:10px 14px;border:1px solid #b6c9ca;border-radius:8px;background:white;color:var(--ink)}input{flex:1;min-width:220px}button{cursor:pointer}button:hover{border-color:var(--green)}button:disabled{opacity:.4;cursor:default}a{color:var(--green);text-decoration:underline;text-underline-offset:3px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:12px;background:white}table{width:100%;border-collapse:collapse}th,td{padding:14px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:#eaf0ed;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}.status{display:inline-block;padding:3px 8px;border-radius:5px;background:#fff1d8;font-size:12px;white-space:nowrap}.approved{background:#d8f2e8}.rejected{background:#edf0f1;color:#67777b}.sub{display:block;color:var(--muted);font-size:12px;max-width:360px}.pager{display:flex;align-items:center;justify-content:space-between;margin:18px 0}dialog{width:min(920px,95vw);max-height:90vh;border:1px solid var(--line);border-radius:16px;padding:28px;color:var(--ink)}dialog::backdrop{background:#102f35aa}dialog h2{margin-top:0}dialog pre{white-space:pre-wrap;word-break:break-word;background:#f2f5f3;padding:16px;max-height:40vh;overflow:auto;font-size:12px}.detail-links{display:flex;gap:16px;flex-wrap:wrap}.close{float:right}footer{color:var(--muted);font-size:12px;margin-top:28px}@media(max-width:700px){.cards{grid-template-columns:1fr 1fr}h1{font-size:28px}main{padding:16px}header{padding:24px}th,td{padding:10px}}
</style></head><body><header><small>IncuBrix · Growth operations</small><h1>Every lead starts with evidence.</h1><p>Inspect source-backed candidates, review qualification gaps, and trace approved outreach to the creator’s published information.</p></header>
<main><div class="notice" id="notice"></div><section class="cards" aria-label="Run counts" id="cards"></section>
<div class="tools"><input id="search" type="search" aria-label="Search creators, titles or IDs" placeholder="Search creator, show, stable ID…"><select id="status" aria-label="Qualification status"><option value="">All statuses</option><option>Needs review</option><option>Qualified</option><option>Rejected</option></select><select id="country" aria-label="Country hint or approved country"><option value="">All countries</option></select><a href="leads.csv" download>Approved CSV</a><a href="review_queue.csv" download>Review queue</a><a href="Human_Review.xlsx" download>Human review workbook</a></div>
<div class="table-wrap"><table><thead><tr><th>Creator / show</th><th>Country</th><th>Status</th><th>Activity</th><th>Evidence</th></tr></thead><tbody id="rows"></tbody></table></div>
<div class="pager"><span id="count" aria-live="polite"></span><div><button id="prev" type="button">Previous</button> <button id="next" type="button">Next</button></div></div>
<footer>Country and contact values in the review queue are discovery hints. Only approved rows are included in leads.csv. No creator outreach has been sent. Source availability and timestamps are recorded separately from the engine run date.</footer></main>
<dialog id="detail"><button class="close" type="button">Close</button><h2 id="detail-title"></h2><p id="detail-status"></p><div class="detail-links" id="detail-links"></div><h3>Evidence and decision record</h3><pre id="detail-json"></pre><h3>Draft first message</h3><p id="detail-message"></p></dialog>
<script type="application/json" id="data">__PAYLOAD__</script><script>
'use strict';
const data=JSON.parse(document.querySelector('#data').textContent), $=s=>document.querySelector(s);let page=0;const size=50;
const target=data.summary.run_metrics.target_leads||2000;
const notice=$('#notice');notice.textContent=data.summary.qualified>=target?'Lead count target reached. Check validation_report.json and remaining submission gates before launch.':'Review needed: '+data.summary.qualified+' approved creators toward your '+target.toLocaleString()+' target. Open Human_Review.xlsx to complete evidence decisions. Country balance, Priority A sequences and three seed tests must also pass.';
for(const [label,value] of [['Checked profiles',data.rows.length],['Approved leads',data.summary.qualified],['Awaiting review',data.summary.pending_review],['Rejected',data.summary.rejected]]){const c=document.createElement('div');c.className='card';const l=document.createElement('span');l.textContent=label;const v=document.createElement('b');v.textContent=value.toLocaleString();c.append(l,v);$('#cards').append(c)}
for(const country of [...new Set(data.rows.map(r=>r.country_iso2).filter(Boolean))].sort()){const option=document.createElement('option');option.value=option.textContent=country;$('#country').append(option)}
function link(label,url,parent){try{const parsed=new URL(url);if(!['http:','https:'].includes(parsed.protocol))return;const a=document.createElement('a');a.href=parsed.href;a.textContent=label;a.target='_blank';a.rel='noopener noreferrer';parent.append(a)}catch{}}
function openDetail(r){$('#detail-title').textContent=r.creator_name||r.stable_creator_id;$('#detail-status').textContent=r.candidate_status+' · '+(r.rejection_reason||'Creator-specific evidence reviewed');const l=$('#detail-links');l.replaceChildren();link('Official profile',r.profile_url,l);link('Recent content',r.recent_content_url,l);link('Contact source',r.channel_evidence_url,l);link('Source feed',r.source_feed_url,l);$('#detail-json').textContent=JSON.stringify({stable_creator_id:r.stable_creator_id,country:r.country_iso2,best_channel:r.best_channel,contact:r.channel_handle_or_url,backup:r.backup_channel,checked_date:r.checked_date,notes:r.evidence_notes,metadata:r.metadata},null,2);$('#detail-message').textContent=r.first_message||'No draft: qualification requirements not met.';$('#detail').showModal()}
function render(){const q=$('#search').value.trim().toLowerCase(),status=$('#status').value,country=$('#country').value;const filtered=data.rows.filter(r=>(!status||r.candidate_status===status)&&(!country||r.country_iso2===country)&&(!q||[r.creator_name,r.stable_creator_id,r.metadata.collection_name||''].join(' ').toLowerCase().includes(q)));page=Math.min(page,Math.max(0,Math.ceil(filtered.length/size)-1));const rows=$('#rows');rows.replaceChildren();for(const r of filtered.slice(page*size,(page+1)*size)){const tr=document.createElement('tr');const name=document.createElement('td');name.textContent=r.creator_name||'Unresolved creator';const sub=document.createElement('span');sub.className='sub';sub.textContent=r.metadata.collection_name||r.stable_creator_id;name.append(sub);const c=document.createElement('td');c.textContent=r.country_iso2||'Unverified';const s=document.createElement('td'),badge=document.createElement('span');badge.className='status '+(r.candidate_status==='Qualified'?'approved':r.candidate_status==='Rejected'?'rejected':'');badge.textContent=r.candidate_status;s.append(badge);const a=document.createElement('td');a.textContent=r.candidate_status==='Rejected'?'—':r.longform_count_60d+' long-form / 60d';const e=document.createElement('td'),b=document.createElement('button');b.type='button';b.textContent='Inspect';b.addEventListener('click',()=>openDetail(r));e.append(b);tr.append(name,c,s,a,e);rows.append(tr)}if(!filtered.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=5;td.textContent='No matching records.';tr.append(td);rows.append(tr)}$('#count').textContent=filtered.length+' records · page '+(page+1)+' of '+Math.max(1,Math.ceil(filtered.length/size));$('#prev').disabled=page===0;$('#next').disabled=(page+1)*size>=filtered.length}
for(const selector of ['#search','#status','#country'])$(selector).addEventListener('input',()=>{page=0;render()});$('#prev').addEventListener('click',()=>{page--;render()});$('#next').addEventListener('click',()=>{page++;render()});$('.close').addEventListener('click',()=>$('#detail').close());render();
</script></body></html>"""
    write_text(path, document.replace("__PAYLOAD__", payload))
