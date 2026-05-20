#!/usr/bin/env python3
"""Combine per-adapter result JSONs into index.html.

Usage:
  python render.py                              # reads results/*.json
  python render.py results/a.json results/b.json   # explicit files
"""
import json, sys, time
from pathlib import Path

from benchmark import RESULTS_DIR

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DOOMbench: Can your database run DOOM?</title>
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#f9f8f7;
  --surface:#fff;
  --surface-h:#f3f2f0;
  --border:#e8e7e4;
  --border-strong:#c6c4c0;
  --text:#1a1917;
  --text2:#5f5e5a;
  --dim:#9e9d99;
  --red:#c0392b;
  --red-tint:#fdf1f0;
  --green:#16a34a;
  --orange:#d97706;
  --sans:'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  --mono:'JetBrains Mono','Courier New',monospace;
  --radius:3px;
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:var(--sans);line-height:1.5;-webkit-font-smoothing:antialiased;overflow-x:hidden}

/* ── Nav ─────────────────────────────────────────────────────── */
.nav{position:sticky;top:0;z-index:100;background:rgba(249,248,247,.9);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border-bottom:1px solid var(--border)}
.nav-inner{padding:0 clamp(24px,4vw,64px);height:52px;display:flex;align-items:center;justify-content:space-between}
.nav-brand{font-family:var(--mono);font-size:.85rem;font-weight:700;color:var(--text);letter-spacing:-.3px;text-decoration:none}
.nav-brand em{color:var(--red);font-style:normal}
.nav-link{font-size:.8rem;color:var(--dim);text-decoration:none;transition:color .15s}
.nav-link:hover{color:var(--text)}

/* ── Page ────────────────────────────────────────────────────── */
.page{padding:0 clamp(24px,4vw,64px)}

/* ── Hero ────────────────────────────────────────────────────── */
.hero{padding:clamp(64px,11vw,128px) 0 clamp(48px,7vw,80px);border-bottom:1px solid var(--border)}
.hero h1{font-size:clamp(3.6rem,9.5vw,8rem);font-weight:700;letter-spacing:-4px;line-height:.98;color:var(--text)}
.hero h1 em{color:var(--red);font-style:normal}
.hero-sub{margin-top:24px;font-size:1.1rem;font-weight:500;color:var(--text2);max-width:560px;line-height:1.65}
.hero-meta{display:none}
.bench-footnote{
  margin-top:32px;padding-top:20px;border-top:1px solid var(--border);
  font-size:.82rem;font-style:italic;color:var(--text2);
  max-width:640px;line-height:1.65;
}
.bench-footnote sup{font-size:.65em;vertical-align:super;font-style:normal}

/* ── Bench table ─────────────────────────────────────────────── */
.bench-section{padding:clamp(36px,5vw,60px) clamp(24px,4vw,64px) clamp(28px,4vw,48px)}
.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;min-width:560px}

thead th{
  padding:10px 18px;
  font-size:.68rem;font-weight:600;letter-spacing:.6px;text-transform:uppercase;
  color:var(--dim);border-bottom:2px solid var(--border);
  text-align:right;white-space:nowrap;vertical-align:bottom;
}
thead th:first-child{text-align:left}
thead th.sortable{cursor:pointer;user-select:none;transition:color .12s}
thead th.sortable:hover{color:var(--text2)}
thead th.sorted{color:var(--text);border-bottom:2px solid var(--red)}
.sort-arrow{display:inline-block;margin-left:4px;font-size:.75em;opacity:.4;width:1em;text-align:center}
thead th.sorted .sort-arrow{opacity:1}

tbody td{
  padding:15px 18px;
  border-bottom:1px solid var(--border);
  vertical-align:middle;
  text-align:right;
}
tbody td:first-child{text-align:left}
tbody tr:last-child td{border-bottom:none}
tbody tr.clickable{cursor:pointer}
tbody tr.clickable:hover td{background:var(--surface-h)}
tbody tr.clickable:hover .db-name{color:var(--red)}
tbody tr.clickable:hover .watch-tag{background:var(--red-tint);color:var(--red);border-color:transparent}

/* DB name cell */
.db-cell{display:flex;align-items:center;gap:10px;flex-wrap:nowrap}
.db-name{font-family:var(--mono);font-weight:700;font-size:1rem;color:var(--text);white-space:nowrap;transition:color .12s}
.watch-tag{
  font-size:.58rem;font-weight:700;letter-spacing:.4px;text-transform:uppercase;
  padding:3px 8px;border-radius:var(--radius);
  border:1px solid var(--border);background:transparent;
  color:var(--dim);white-space:nowrap;
  transition:opacity .15s,background .12s,color .12s,border-color .12s;flex-shrink:0;
  font-family:var(--sans);
  opacity:0;
}
tbody tr:hover .watch-tag{opacity:1}

/* Metric cell */
.num{font-family:var(--mono);font-weight:700;font-size:.88rem;white-space:nowrap}
.num.null{color:var(--dim);font-weight:400}
.unit{font-size:.72rem;font-weight:500;margin-left:1px;opacity:.6}

/* Bar cell */
.bar-cell{position:relative;display:inline-flex;align-items:center;justify-content:flex-end;min-width:120px;width:100%}
.bar-bg{position:absolute;left:0;top:50%;transform:translateY(-50%);height:20px;border-radius:2px;opacity:.18;transition:width .3s cubic-bezier(.4,0,.2,1)}
.bar-num{position:relative;z-index:1;font-family:var(--mono);font-weight:700;font-size:.88rem;white-space:nowrap}

/* Reference rows */
.ref-row td{border-bottom:1px dashed var(--border)}
.ref-row:last-child td{border-bottom:none}
.ref-row .db-name{color:var(--dim);font-weight:500;font-style:italic}
.ref-row .num,.ref-row .bar-num{color:var(--dim);opacity:.55}
.ref-divider td{
  padding:6px 18px;
  font-size:.62rem;letter-spacing:.5px;text-transform:uppercase;
  color:var(--dim);border-bottom:1px solid var(--border);
  text-align:left !important;
}

.table-note{font-size:.73rem;color:var(--dim);margin-top:14px;line-height:1.55}

/* ── Delight ──────────────────────────────────────────────────── */
@keyframes row-in{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
@keyframes footnote-hl{0%,100%{background:transparent}25%{background:var(--red-tint)}}
@keyframes redact-flicker{0%,100%{opacity:.7}40%{opacity:.2}60%{opacity:.5}}
@keyframes doom-flash{0%{opacity:0}10%{opacity:.95}80%{opacity:.95}100%{opacity:0}}
.dewitt-row:hover .dewitt-val{animation:redact-flicker 1.4s ease-in-out infinite}
.bench-footnote.flash{animation:footnote-hl .9s ease}
.fn-star{color:var(--dim);text-decoration:none;cursor:pointer;font-size:.35em;vertical-align:super}
.fn-star:hover{color:var(--red)}

/* ── DeWitt-redacted rows ─────────────────────────────────────── */
.dewitt-row .db-name{color:var(--text2)}
.dewitt-tag{background:var(--surface-h)!important;color:var(--dim)!important;border-color:var(--border)!important;cursor:help;font-style:normal}
.dewitt-val{color:var(--border-strong);letter-spacing:3px;font-size:.72rem;opacity:.7}

/* ── Column tooltip ───────────────────────────────────────────── */
.th-info{font-size:.7em;color:var(--dim);margin-left:4px;opacity:.45;font-style:normal;transition:opacity .12s}
thead th:hover .th-info{opacity:1}
.col-tip{
  position:fixed;z-index:300;display:none;
  background:var(--surface);border:1px solid var(--border);
  box-shadow:0 4px 20px rgba(0,0,0,.1),0 1px 4px rgba(0,0,0,.06);
  border-radius:var(--radius);padding:11px 15px;
  max-width:280px;font-size:.8rem;line-height:1.6;
  color:var(--text2);font-family:var(--sans);font-weight:400;
  pointer-events:none;
  opacity:0;transform:translateY(-4px);
  transition:opacity .15s ease,transform .15s ease;
}
.col-tip.vis{opacity:1;transform:none}

/* ── Column sub-labels ───────────────────────────────────────── */
.th-label-row{display:flex;align-items:center;justify-content:flex-end;gap:2px}
.th-sub{font-size:.58rem;font-weight:600;letter-spacing:.5px;text-transform:uppercase;color:var(--dim);margin-top:3px;opacity:.65;text-align:right}

/* ── Metric legend ───────────────────────────────────────────── */
.metric-legend{display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin-bottom:clamp(24px,3vw,40px);padding-bottom:clamp(20px,3vw,32px);border-bottom:1px solid var(--border)}
.legend-item{padding-right:clamp(12px,2vw,28px)}
.legend-item:last-child{padding-right:0}
.legend-header{display:flex;align-items:center;gap:7px;margin-bottom:5px}
.legend-name{font-family:var(--mono);font-weight:700;font-size:.82rem;color:var(--text)}
.legend-tag{font-size:.56rem;font-weight:700;letter-spacing:.5px;text-transform:uppercase;padding:2px 6px;border-radius:var(--radius);font-family:var(--sans);white-space:nowrap}
.tag-oltp{background:color-mix(in oklch,var(--green) 12%,transparent);color:var(--green)}
.tag-olap{background:color-mix(in oklch,var(--orange) 12%,transparent);color:var(--orange)}
.tag-htap{background:color-mix(in oklch,var(--red) 12%,transparent);color:var(--red)}
.tag-e2e{background:var(--surface-h);color:var(--text2)}
.legend-desc{font-size:.75rem;color:var(--text2);line-height:1.55}
@media(max-width:680px){.metric-legend{grid-template-columns:1fr 1fr;gap:clamp(12px,2vw,20px) 0}.legend-item{padding-right:clamp(8px,2vw,16px)}}
@media(max-width:380px){.metric-legend{grid-template-columns:1fr}}

/* ── Footnote links ──────────────────────────────────────────── */
.bench-footnote a{color:var(--red);text-decoration:none}
.bench-footnote a:hover{text-decoration:underline}
.bench-footnote+.bench-footnote{margin-top:10px;padding-top:0;border-top:none}

/* ── Badge column ─────────────────────────────────────────────── */
thead th.th-badge{text-align:left}
td.td-badge{text-align:left;width:1%;white-space:nowrap}
.badge-btn{
  background:none;border:none;cursor:pointer;padding:4px 6px;
  border-radius:var(--radius);display:inline-flex;align-items:center;
  position:relative;opacity:.75;transition:opacity .12s;
}
.badge-btn:hover{opacity:1}
.badge-img{height:18px;display:block}
.copied-tip{
  position:absolute;bottom:calc(100% + 5px);left:50%;transform:translateX(-50%) translateY(3px);
  font-size:.62rem;font-family:var(--sans);font-weight:600;letter-spacing:.2px;
  padding:3px 9px;border-radius:var(--radius);white-space:nowrap;pointer-events:none;
  background:var(--text);color:var(--surface);
  opacity:0;transition:opacity .15s,transform .15s;
}
.badge-btn.copied .copied-tip{opacity:1;transform:translateX(-50%) translateY(0)}

/* ── Footer ───────────────────────────────────────────────────── */
footer.footer{border-top:1px solid var(--border);padding:24px 0 40px}
footer.footer .page{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
.footer-text{font-size:.75rem;color:var(--dim)}
.footer-text a{color:var(--red);text-decoration:none}
.footer-text a:hover{text-decoration:underline}

/* ── Modal ────────────────────────────────────────────────────── */
.modal-overlay{
  display:none;position:fixed;inset:0;z-index:500;
  background:#0c0b0a;flex-direction:column;
}
.modal-overlay.open{display:flex}
.modal-card{
  flex:1;display:flex;flex-direction:column;overflow:hidden;
  animation:modal-in .22s cubic-bezier(.16,1,.3,1) both;
}
@keyframes modal-in{from{opacity:0}to{opacity:1}}
.modal-header{
  display:flex;align-items:center;justify-content:space-between;
  padding:13px 24px;flex-shrink:0;
  border-bottom:1px solid rgba(255,255,255,.07);
}
.modal-db{font-family:var(--mono);font-weight:700;font-size:.9rem;color:rgba(255,255,255,.75);letter-spacing:.2px}
.modal-version{font-family:var(--mono);font-size:.65rem;color:rgba(255,255,255,.3);margin-left:10px}
.modal-close{
  background:none;border:none;cursor:pointer;
  font-size:1.1rem;line-height:1;color:rgba(255,255,255,.3);
  padding:5px 9px;border-radius:3px;
  transition:background .12s,color .12s;
}
.modal-close:hover{background:rgba(255,255,255,.08);color:rgba(255,255,255,.75)}
#modal-body{flex:1;overflow:hidden;display:flex;align-items:center;justify-content:center}
.modal-video{width:100%;height:100%;display:block;object-fit:contain;background:#0c0b0a}
.modal-stats{
  padding:10px 24px;flex-shrink:0;
  border-top:1px solid rgba(255,255,255,.07);
  display:flex;gap:20px;flex-wrap:wrap;align-items:center;
  font-size:.7rem;color:rgba(255,255,255,.28);font-family:var(--mono);
}
.modal-stats b{color:rgba(255,255,255,.58);font-weight:700}

.no-preview{
  display:flex;align-items:center;justify-content:center;height:100%;
  color:rgba(255,255,255,.15);font-family:var(--mono);font-size:.8rem;
}
</style>
</head>
<body>

<nav class="nav">
  <div class="nav-inner">
    <a class="nav-brand" href="#"><em>DOOM</em>bench</a>
    <a class="nav-link" href="https://cedardb.com">cedardb.com →</a>
  </div>
</nav>

<main>
<div class="page">
  <header class="hero">
    <h1>Can your database<br>run <em>DOOM</em>?<a href="#bench-footnote" class="fn-star" onclick="flashFootnote(event)">*</a></h1>
    <p class="hero-sub">Every vendor picks a workload that flatters them. We picked DOOM.</p>
  </header>

</div><!-- end .page -->
  <section class="bench-section">
    <div id="metric-legend" class="metric-legend"></div>
    <div class="table-wrap"><table id="bench-table"></table></div>
    <p class="table-note" id="table-note"></p>
    <p class="bench-footnote" id="bench-footnote"><sup>*</sup> Strictly speaking, this is Wolfenstein 3D. It's using raycasting, not a BSP tree. I'm working on a BSP implementation in SQL. Watch this space.</p>
    <p class="bench-footnote">Measured on a c8id.4xlarge (16&thinsp;vCPU, 32&thinsp;GB&thinsp;RAM), instance-local storage in RAID 0. Every system runs the same <a href="https://github.com/cedardb/DOOMQL">DOOMQL</a> codebase; adapters with SQL syntax deviations use per-adapter overrides. DOOMbench is <a href="https://github.com/cedardb/DOOMbench">open source</a>. Currently Postgres-compatible only, PRs to add new systems are welcome.</p>
  </section>
</main>

<footer class="footer">
  <div class="page">
    <span class="footer-text">DOOMbench &middot; <span id="hero-meta"></span></span>
    <span class="footer-text"><a href="https://github.com/cedardb/DOOMbench">github.com/cedardb/DOOMbench</a></span>
  </div>
</footer>

<!-- Modal -->
<div id="modal" class="modal-overlay" onclick="handleOverlayClick(event)">
  <div class="modal-card" role="dialog" aria-modal="true">
    <div class="modal-header">
      <span id="modal-db" class="modal-db"></span><span id="modal-version" class="modal-version"></span>
      <button class="modal-close" onclick="_doClose()" aria-label="Close">&#x2715;</button>
    </div>
    <div id="modal-body"></div>
    <div id="modal-stats" class="modal-stats"></div>
  </div>
</div>

<script>
const DATA=__DATA__;
const VIDEO_DATA=__VIDEO_DATA__;

// ── Config ──────────────────────────────────────────────────────
const METRICS=[
  {key:'doom_score',lower:false,label:'DOOMscore\u2122',sublabel:'HTAP',
   desc:'The HTAP benchmark. Four clients play the actual game with the server ticking at 35\u2009Hz, the original DOOM tick rate. Combined frames per second, penalised proportionally if the server can\u2019t sustain 35 ticks/s: half the tick rate, half the DOOMscore\u2122.'},
  {key:'fps_static',lower:false,label:'Static FPS',sublabel:'OLAP',
   desc:'Pure read throughput. Four players query their rendered view as fast as possible with zero writes or movement. FPS is summed across all four clients.'},
  {key:'ticks_per_sec',lower:false,label:'Tick\u2009/\u2009s',sublabel:'OLTP',
   desc:'Pure write throughput. Four players move around and shoot while the server processes game ticks as fast as possible without any frames being rendered. Each tick is one atomic SQL transaction: move every player, advance every bullet, resolve every kill across multiple tables.'},
  {key:'latency_p50_ms',lower:true,label:'Lag p50',sublabel:'E2E',
   desc:'The metric every eSports gamer cares about. Median time from a player input being committed to that change appearing in a rendered frame. Measured end-to-end across three independent transactions: write the input, run the tick, read back the new state. Captures OLTP speed, OLAP speed, and any replication lag in a single number.'},
];

const GAME_REFS=[];

// Systems whose benchmark results cannot be published (DeWitt clause)
const DEWITT_REDACTED=['AlloyDB'];

let sortKey='doom_score', sortAsc=false;

// ── Helpers ─────────────────────────────────────────────────────
function esc(s){
  return s==null?'':String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function ratioColor(r){
  return r>=.8?'var(--green)':r>=.5?'var(--orange)':'var(--red)';
}
function fmtNum(v){
  if(v==null) return null;
  return Number.isInteger(v)?v.toLocaleString():v.toFixed(1);
}
function shortVersion(v){
  if(!v) return '';
  const colon=v.lastIndexOf(':');
  return colon>=0?v.slice(colon+1):v;
}

// ── Table build ─────────────────────────────────────────────────
function build(){
  const results=DATA.results||[];

  // Hero meta
  const m=document.getElementById('hero-meta');
  if(m&&DATA.generated_at) m.textContent='Generated '+DATA.generated_at;

  if(!results.length){
    document.getElementById('bench-table').innerHTML='<tr><td style="padding:48px;color:var(--dim)">No results yet.</td></tr>';
    return;
  }

  // Best values for each metric — exclude DeWitt-redacted systems so a hidden
  // result doesn't silently set the baseline and wash out everyone else's colors
  const visibleResults=results.filter(r=>!DEWITT_REDACTED.some(d=>d.toLowerCase()===r.db.toLowerCase()));
  const bests={};
  for(const mt of METRICS){
    const vals=visibleResults.map(r=>r[mt.key]).filter(v=>v!=null);
    bests[mt.key]=vals.length?(mt.lower?Math.min(...vals):Math.max(...vals)):1;
  }
  // Reference max for fps_htap (includes game refs, excludes DeWitt)
  const allHtap=[...visibleResults.map(r=>r.fps_htap||0),...GAME_REFS.map(r=>r.fps_htap)];
  const maxHtap=Math.max(...allHtap,1);

  // Sort DB results (exclude DeWitt-redacted systems — they appear separately below)
  const sorted=[...results]
    .filter(r=>!DEWITT_REDACTED.some(d=>d.toLowerCase()===r.db.toLowerCase()))
    .sort((a,b)=>{
    const av=a[sortKey],bv=b[sortKey];
    if(av==null&&bv==null) return 0;
    if(av==null) return 1; if(bv==null) return -1;
    return sortAsc?av-bv:bv-av;
  });

  // When sorted by HTAP FPS, intersperse game refs into ranking
  // Otherwise, show them as a separate block at the bottom
  const sortByHtap=sortKey==='fps_htap';
  let rows='';

  function dbRow(r){
    const hasVideo=!!VIDEO_DATA[r.db];
    const cells=METRICS.map(mt=>{
      const val=r[mt.key];
      const isActive=sortKey===mt.key;
      if(val==null) return `<td><div class="bar-cell"><span class="bar-num" style="color:var(--dim);font-weight:400">&#x2013;</span></div></td>`;
      const ratio=mt.lower?(bests[mt.key]/val):(val/bests[mt.key]);
      const color=ratioColor(ratio);
      const disp=fmtNum(val);
      const u=mt.lower?`<span class="unit">ms</span>`:'';
      const w=isActive?Math.min(100,Math.max(2,ratio*100)).toFixed(1):'0';
      return `<td><div class="bar-cell"><div class="bar-bg" style="width:${w}%;background:${color}"></div><span class="bar-num" style="color:${color}">${esc(disp)}${u}</span></div></td>`;
    }).join('');
    const watchTag=hasVideo?`<span class="watch-tag">&#x25B6; watch</span>`:'';
    const clickAttr=hasVideo?`class="clickable" onclick="openModal('${esc(r.db)}')"`:'' ;
    const badgeUrl=shieldUrl(r.fps_htap,r.latency_p50_ms);
    const badgeCell=`<td class="td-badge"><button class="badge-btn" onclick="copyBadge('${esc(r.db)}',this,event)" title="Copy README badge"><img class="badge-img" src="${esc(badgeUrl)}" alt="badge" loading="lazy"><span class="copied-tip">Copied!</span></button></td>`;
    return `<tr ${clickAttr}>
      <td><div class="db-cell"><span class="db-name">${esc(r.db)}</span>${watchTag}</div></td>
      ${cells}${badgeCell}
    </tr>`;
  }

  function refRow(r){
    const isActive=sortKey==='fps_htap';
    const ratio=r.fps_htap/maxHtap;
    const w=Math.min(100,Math.max(2,ratio*100)).toFixed(1);
    const disp=fmtNum(r.fps_htap%1?r.fps_htap:Math.round(r.fps_htap));
    const emptyCells=METRICS.slice(1).map(()=>'<td></td>').join('');
    const valCell=isActive
      ?`<td><div class="bar-cell"><div class="bar-bg" style="width:${w}%;background:var(--dim)"></div><span class="bar-num">${esc(disp)}</span></div></td>`
      :`<td><span class="num">${esc(disp)}</span></td>`;
    return `<tr class="ref-row">
      <td><div class="db-cell"><span class="db-name">${esc(r.db)}</span></div></td>
      ${valCell}${emptyCells}
    </tr>`;
  }

  function dewittRow(name){
    const videoKey=Object.keys(VIDEO_DATA).find(k=>k.toLowerCase()===name.toLowerCase());
    const hasVideo=!!videoKey;
    const cells=METRICS.map(()=>
      `<td><div class="bar-cell"><span class="bar-num dewitt-val">&#x2588;&#x2588;&#x2588;</span></div></td>`
    ).join('');
    const watchTag=hasVideo?`<span class="watch-tag">&#x25B6; watch</span>`:'';
    const clickAttr=hasVideo?` class="dewitt-row clickable" onclick="openModal('${esc(videoKey)}')"`:' class="dewitt-row"';
    return `<tr${clickAttr}>
      <td><div class="db-cell"><span class="db-name">${esc(name)}</span>${watchTag}<span class="watch-tag dewitt-tag" title="This vendor\u2019s license prohibits publishing benchmark results without approval (DeWitt clause). We respect the law; the law is what it is.">&sect;&thinsp;DeWitt</span></div></td>
      ${cells}<td class="td-badge"></td>
    </tr>`;
  }

  if(sortByHtap){
    // Merge and sort DB + game refs by fps_htap
    const combined=[
      ...sorted.map(r=>({type:'db',data:r,val:r.fps_htap??-Infinity})),
      ...GAME_REFS.map(r=>({type:'ref',data:r,val:r.fps_htap})),
    ].sort((a,b)=>sortAsc?a.val-b.val:b.val-a.val);
    rows=combined.map(item=>item.type==='db'?dbRow(item.data):refRow(item.data)).join('');
  } else {
    rows=sorted.map(dbRow).join('');
    if(GAME_REFS.length){
      rows+=`<tr class="ref-divider"><td colspan="${2+METRICS.length}">Game server reference fps</td></tr>`;
      rows+=[...GAME_REFS].sort((a,b)=>b.fps_htap-a.fps_htap).map(refRow).join('');
    }
  }

  if(DEWITT_REDACTED.length){
    rows+=`<tr class="ref-divider"><td colspan="${2+METRICS.length+1}">Results classified per vendor license</td></tr>`;
    rows+=DEWITT_REDACTED.map(dewittRow).join('');
  }

  // Header
  const thCells=METRICS.map(mt=>{
    const active=sortKey===mt.key;
    const arrow=active?(sortAsc?'&#x2191;':'&#x2193;'):'&#x21C5;';
    const dsc=esc(mt.desc).replace(/'/g,'&#39;');
    const sub=mt.sublabel?`<div class="th-sub">${esc(mt.sublabel)}</div>`:'';
    return `<th class="sortable${active?' sorted':''}" onclick="setSort('${mt.key}',${mt.lower})" onmouseenter="showTip(this,'${dsc}')" onmouseleave="hideTip()">
      <div class="th-label-row">${esc(mt.label)}<span class="th-info">&#x24D8;</span><span class="sort-arrow">${arrow}</span></div>${sub}
    </th>`;
  }).join('');
  const thead=`<thead><tr><th>Database</th>${thCells}<th class="th-badge">README</th></tr></thead>`;

  document.getElementById('bench-table').innerHTML=`${thead}<tbody>${rows}</tbody>`;
  document.querySelectorAll('#bench-table tbody tr').forEach((tr,i)=>{
    tr.style.animation=`row-in .22s cubic-bezier(.16,1,.3,1) ${i*22}ms both`;
  });

  const note=document.getElementById('table-note');
  if(note) note.textContent='Click a row to watch its recorded replay \u00b7 click a badge to copy the README markdown.';
}

function setSort(key,lower){
  if(sortKey===key){sortAsc=!sortAsc;}
  else{sortKey=key;sortAsc=lower;}
  build();
}

// ── Badge helpers ─────────────────────────────────────────────────
function shieldUrl(fps,lag){
  const enc=s=>encodeURIComponent(s).replace(/-/g,'--');
  let verdict,color;
  if(!fps){verdict='no data';color='lightgrey';}
  else if(fps>=35){verdict=`yes \u00b7 ${fps} FPS`;color='brightgreen';}
  else if(fps>=10){verdict=`barely \u00b7 ${fps} FPS`;color='yellow';}
  else{verdict=`no \u00b7 ${fps} FPS`;color='red';}
  if(lag!=null) verdict+=` \u00b7 ${lag}ms lag`;
  return `https://img.shields.io/badge/${enc('can it run DOOM?')}-${enc(verdict)}-${color}`;
}

function copyBadge(db,btn,e){
  e.stopPropagation();
  const r=(DATA.results||[]).find(x=>x.db===db);
  if(!r) return;
  const url=shieldUrl(r.fps_htap,r.latency_p50_ms);
  const md='[![can it run DOOM?]('+url+')](https://github.com/cedardb/DOOMQL)';
  navigator.clipboard.writeText(md).then(()=>{
    btn.classList.add('copied');
    setTimeout(()=>btn.classList.remove('copied'),1800);
  });
}

// ── Modal ─────────────────────────────────────────────────────────
function openModal(db){
  const r=(DATA.results||[]).find(x=>x.db===db);
  document.getElementById('modal-db').textContent=db;
  const _verEl=document.getElementById('modal-version');
  if(_verEl) _verEl.textContent=r?.db_version?shortVersion(r.db_version):'';

  // Stats bar
  const stats=document.getElementById('modal-stats');
  const dot='<span style="color:var(--border-strong)"> &middot; </span>';
  if(DEWITT_REDACTED.some(d=>d.toLowerCase()===db.toLowerCase())){
    const redact=`<b style="color:var(--border-strong);letter-spacing:2px">&#x2588;&#x2588;&#x2588;</b>`;
    stats.innerHTML=METRICS.map(mt=>`${esc(mt.label)} ${redact}`).join(dot)
      +dot+'<span style="font-style:italic;opacity:.5">\u00a7 DeWitt clause</span>';
  } else if(r){
    const parts=[];
    if(r.doom_score!=null)    parts.push(`DOOMscore\u2122 <b>${r.doom_score}</b>`);
    if(r.fps_static!=null)    parts.push(`Static FPS <b>${r.fps_static}</b>`);
    if(r.ticks_per_sec!=null) parts.push(`Tick/s <b>${r.ticks_per_sec}</b>`);
    if(r.latency_p50_ms!=null) parts.push(`Lag p50 <b>${r.latency_p50_ms} ms</b>`);
    stats.innerHTML=parts.join(dot);
  } else {
    stats.innerHTML='';
  }

  // Body — video or ASCII fallback
  const body=document.getElementById('modal-body');
  body.innerHTML='';
  if(VIDEO_DATA[db]){
    const vid=document.createElement('video');
    vid.src=VIDEO_DATA[db]; vid.className='modal-video';
    vid.autoplay=true; vid.loop=true; vid.muted=true; vid.playsInline=true;
    body.appendChild(vid);
  } else {
    body.innerHTML='<div class="no-preview">no preview captured</div>';
  }

  document.getElementById('modal').classList.add('open');
  document.addEventListener('keydown',_escHandler);
}

function handleOverlayClick(e){
  if(e.target===document.getElementById('modal')) _doClose();
}

function _doClose(){
  const modal=document.getElementById('modal');
  if(!modal.classList.contains('open')) return;
  modal.classList.remove('open');
  const vid=modal.querySelector('video');
  if(vid){vid.pause();vid.src='';}
  document.getElementById('modal-body').innerHTML='';
  document.removeEventListener('keydown',_escHandler);
}

function _escHandler(e){if(e.key==='Escape') _doClose();}

// ── Column tooltip ────────────────────────────────────────────────
let _tip=null,_tipTimer=null;
function showTip(el,text){
  if(!_tip){
    _tip=document.createElement('div');
    _tip.className='col-tip';
    document.body.appendChild(_tip);
  }
  clearTimeout(_tipTimer);
  _tip.textContent=text;
  _tip.style.display='block';
  const r=el.getBoundingClientRect();
  let left=r.left,top=r.bottom+6;
  const tw=_tip.offsetWidth||280;
  if(left+tw>window.innerWidth-12) left=window.innerWidth-tw-12;
  if(left<8) left=8;
  _tip.style.left=left+'px';
  _tip.style.top=top+'px';
  requestAnimationFrame(()=>_tip&&_tip.classList.add('vis'));
}
function hideTip(){
  if(!_tip) return;
  _tip.classList.remove('vis');
  _tipTimer=setTimeout(()=>{if(_tip){_tip.style.display='none';}},160);
}

// ── Delight ───────────────────────────────────────────────────────
// Footnote anchor flash
function flashFootnote(e){
  const fn=document.getElementById('bench-footnote');
  if(!fn) return;
  fn.classList.remove('flash');
  void fn.offsetWidth;
  fn.classList.add('flash');
}

// Konami code → IDDQD
(function(){
  const SEQ=['ArrowUp','ArrowUp','ArrowDown','ArrowDown','ArrowLeft','ArrowRight','ArrowLeft','ArrowRight','b','a'];
  let idx=0;
  document.addEventListener('keydown',e=>{
    idx = e.key===SEQ[idx] ? idx+1 : (e.key===SEQ[0] ? 1 : 0);
    if(idx<SEQ.length) return;
    idx=0;
    const el=document.createElement('div');
    el.style.cssText='position:fixed;inset:0;z-index:9999;background:#c0392b;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:12px;pointer-events:none;animation:doom-flash 2s cubic-bezier(.16,1,.3,1) forwards';
    el.innerHTML='<div style="font-family:var(--mono);font-size:clamp(1.4rem,4vw,2.8rem);font-weight:700;color:#f9f8f7;letter-spacing:4px">IDDQD</div><div style="font-family:var(--sans);font-size:.9rem;color:rgba(249,248,247,.6);letter-spacing:1px">GOD MODE ENABLED</div>';
    document.body.appendChild(el);
    setTimeout(()=>el.remove(),2100);
  });
})();

// ── Metric legend ─────────────────────────────────────────────────
function buildLegend(){
  const el=document.getElementById('metric-legend');
  if(!el) return;
  const tagClass={OLTP:'tag-oltp',OLAP:'tag-olap',HTAP:'tag-htap','E2E':'tag-e2e'};
  const shortDesc={
    doom_score:'4 clients play at 35 Hz. Combined FPS, penalised proportionally if the server falls behind the tick rate.',
    fps_static:'4 viewers, zero writes. Raw analytical read throughput — the theoretical ceiling. FPS summed across all clients.',
    ticks_per_sec:'Game loop only, no rendering. 4 players move and shoot; server processes ticks as fast as possible.',
    latency_p50_ms:'Button press to visible frame. Captures OLTP speed, OLAP speed, and replication lag in a single number.',
  };
  el.innerHTML=METRICS.map(mt=>{
    const tc=tagClass[mt.sublabel||'']||'tag-e2e';
    return `<div class="legend-item">
      <div class="legend-header"><span class="legend-name">${esc(mt.label)}</span><span class="legend-tag ${tc}">${esc(mt.sublabel||'')}</span></div>
      <p class="legend-desc">${esc(shortDesc[mt.key]||'')}</p>
    </div>`;
  }).join('');
}

// ── Init ──────────────────────────────────────────────────────────
build();
buildLegend();
</script>
</body>
</html>"""


def write_results(data, video_data=None, path="index.html"):
    def safe(obj):
        return json.dumps(obj, ensure_ascii=False).replace("</script>", r"<\/script>")
    html = (HTML_TEMPLATE
            .replace("__DATA__",       safe(data))
            .replace("__VIDEO_DATA__", safe(video_data or {})))
    Path(path).write_text(html, encoding="utf8")
    print(f"\nResults written → {path}")


def main(files=None):
    if files is None:
        files = sorted(RESULTS_DIR.glob("*.json"))

    if not files:
        print(f"No result files found in {RESULTS_DIR}/", file=sys.stderr)
        sys.exit(1)

    results    = []
    video_data = {}
    for f in files:
        r = json.loads(Path(f).read_text(encoding="utf8"))
        results.append(r)
        print(f"  loaded {f}")
        mp4_path = RESULTS_DIR / f"{Path(f).stem}_replay.mp4"
        if mp4_path.exists():
            video_data[r["db"]] = mp4_path.as_posix()
            print(f"  found  {mp4_path}  ({mp4_path.stat().st_size // 1024} KB)")

    cols   = ["DB", "FPS", "Ticks/s", "Lag p50ms", "FPS HTAP"]
    widths = [20, 8, 9, 10, 9]
    sep    = "  "
    hdr    = sep.join(f"{c:>{w}}" for c, w in zip(cols, widths))
    print("\n## Results")
    print(hdr)
    print("─" * len(hdr))
    for r in results:
        vals = [
            r["db"],
            r.get("fps_static", "–"),
            r.get("ticks_per_sec", "–"),
            r.get("latency_p50_ms", "–"),
            r.get("fps_htap", "–"),
        ]
        print(sep.join(f"{str(v):>{w}}" for v, w in zip(vals, widths)))

    write_results(
        {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": results},
        video_data=video_data,
    )


if __name__ == "__main__":
    files = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else None
    main(files=files)
