"""Admin UI assets for the free-claume proxy.

The proxy serves this single-file dashboard at http://127.0.0.1:<port>/admin

v2.3 — rebuilt as a *design-studio* dashboard: editorial typography,
an explode-view hero, live per-key health rows, a searchable model
picker, per-key verification, an update checker, and a self-design
brief generator (claume can rebuild its own website from this design
language). Google Fonts are pulled from the CDN; everything else is
inline — the file stays import-free because claume.proxy imports
ADMIN_HTML at module load time.
"""

ADMIN_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>claume studio — free-claume admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<!-- Editorial + technical font pairing pulled from Google Fonts:
     Fraunces (display serif) · Space Grotesk (UI) · JetBrains Mono (code) -->
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,600;9..144,700&family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#060807; --ink:#e9f2e4; --dim:#7d8a76; --faint:#46503f;
  --green:#76b900; --lime:#b7f04a; --mint:#7ef0c0;
  --panel:#0b0f0a; --panel2:#10160e; --line:#1c2418; --line2:#2a3522;
  --gold:#e3b341; --red:#f85149; --serif:'Fraunces',Georgia,serif;
  --sans:'Space Grotesk','Segoe UI',sans-serif; --mono:'JetBrains Mono',Consolas,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{
  background:
    radial-gradient(1100px 500px at 15% -10%, rgba(118,185,0,.10), transparent 60%),
    radial-gradient(800px 420px at 95% 15%, rgba(126,240,192,.05), transparent 65%),
    var(--bg);
  color:var(--ink); font-family:var(--sans); min-height:100vh;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1080px;margin:0 auto;padding:52px 26px 90px}
/* ---------- top bar ---------- */
.topbar{display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap}
.kicker{font-family:var(--mono);font-size:11px;letter-spacing:.32em;text-transform:uppercase;color:var(--dim)}
.kicker b{color:var(--green);font-weight:500}
h1.logo{
  font-family:var(--serif);font-weight:600;font-size:46px;letter-spacing:-.02em;line-height:1.05;margin-top:10px;
}
h1.logo em{font-style:italic;font-weight:300;color:var(--lime)}
.sub{color:var(--dim);margin-top:12px;font-size:14.5px;line-height:1.65;max-width:640px}
.sub a{color:var(--mint);text-decoration:none;border-bottom:1px solid rgba(126,240,192,.25)}
.pillrow{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}
.pill{
  font-family:var(--mono);font-size:11px;letter-spacing:.06em;padding:6px 12px;border-radius:999px;
  border:1px solid var(--line2);color:var(--dim);background:rgba(16,22,14,.6);
}
.pill .dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--green);
  box-shadow:0 0 8px var(--green);margin-right:7px;animation:pulse 2.4s infinite;vertical-align:1px}
.pill.err .dot{background:var(--red);box-shadow:0 0 8px var(--red)}
.pill.warn .dot{background:var(--gold);box-shadow:0 0 8px var(--gold)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
/* ---------- explode-view hero ---------- */
.explode{position:relative;height:300px;margin:34px 0 8px;perspective:1100px}
.layer{
  position:absolute;left:50%;top:50%;width:min(560px,80%);height:150px;margin-left:min(-280px,-40%);
  border:1px solid var(--line2);border-radius:14px;
  background:linear-gradient(165deg,rgba(22,30,17,.9),rgba(10,14,8,.92));
  box-shadow:0 24px 50px rgba(0,0,0,.45);
  transform-style:preserve-3d;
  transform:translateY(0) translateZ(0) rotateX(14deg) rotateZ(-2deg);
  animation:explodeIn 1.1s cubic-bezier(.19,1,.22,1) both;
  transition:transform .5s cubic-bezier(.19,1,.22,1);
}
.explode:hover .layer.l1{transform:translateY(-96px) translateZ(70px) rotateX(14deg) rotateZ(-2deg)}
.explode:hover .layer.l2{transform:translateY(-14px) translateZ(24px) rotateX(14deg) rotateZ(-2deg)}
.explode:hover .layer.l3{transform:translateY(66px) translateZ(-24px) rotateX(14deg) rotateZ(-2deg)}
.layer .tag{position:absolute;top:12px;left:16px;font-family:var(--mono);font-size:10px;letter-spacing:.22em;
  text-transform:uppercase;color:var(--dim)}
.layer .big{position:absolute;bottom:14px;left:16px;font-family:var(--serif);font-size:21px;font-weight:400}
.layer .big i{font-style:italic;color:var(--lime);font-weight:300}
.layer.l1{animation-delay:.05s}.layer.l1 .big{color:var(--ink)}
.layer.l2{animation-delay:.2s}.layer.l2 .big{color:var(--mint)}
.layer.l3{animation-delay:.35s}.layer.l3 .big{color:var(--gold)}
@keyframes explodeIn{from{opacity:0;transform:translateY(46px) translateZ(-160px) rotateX(14deg) rotateZ(-2deg)}
  to{opacity:1;transform:translateY(0) translateZ(0) rotateX(14deg) rotateZ(-2deg)}}
.hintline{font-family:var(--mono);font-size:10.5px;color:var(--faint);letter-spacing:.18em;text-transform:uppercase;
  text-align:center;margin-top:2px}
/* ---------- section scaffolding ---------- */
section{margin-top:58px}
.shead{display:flex;align-items:baseline;gap:14px;margin-bottom:6px}
.snum{font-family:var(--mono);font-size:11px;color:var(--green);letter-spacing:.2em}
h2{font-family:var(--serif);font-weight:600;font-size:27px;letter-spacing:-.01em}
.sdesc{color:var(--dim);font-size:13.5px;margin:6px 0 20px;max-width:640px;line-height:1.6}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:22px}
@media (max-width:820px){.grid2{grid-template-columns:1fr}}
.card{
  background:linear-gradient(180deg,var(--panel2),var(--panel));
  border:1px solid var(--line);border-radius:16px;padding:24px;
  box-shadow:0 18px 40px rgba(0,0,0,.4);
}
label{display:block;font-family:var(--mono);font-size:10.5px;text-transform:uppercase;letter-spacing:.2em;
  color:var(--dim);margin:18px 0 8px}
label:first-child{margin-top:0}
input[type=text],input[type=password],select,textarea{
  width:100%;padding:13px 15px;border-radius:11px;border:1px solid var(--line);
  background:#080b07;color:var(--ink);font-size:14px;font-family:var(--sans);outline:none;
  transition:border-color .15s, box-shadow .15s;
}
input:focus,select:focus,textarea:focus{border-color:var(--green);box-shadow:0 0 0 3px rgba(118,185,0,.12)}
textarea{font-family:var(--mono);font-size:12.5px;line-height:1.6;resize:vertical}
.hint{color:var(--dim);font-size:12px;margin-top:7px;line-height:1.55}
.hint a{color:var(--mint);text-decoration:none}
.hint code, .inlinecode{font-family:var(--mono);font-size:11.5px;background:var(--panel2);
  border:1px solid var(--line);padding:2px 7px;border-radius:6px;color:var(--lime)}
.row{display:flex;gap:10px;margin-top:20px;flex-wrap:wrap}
button{
  flex:1;min-width:150px;padding:13px 18px;border-radius:11px;border:0;cursor:pointer;
  font-family:var(--sans);font-size:13.5px;font-weight:600;letter-spacing:.02em;
  transition:transform .12s, filter .15s, box-shadow .15s;
}
button:hover{filter:brightness(1.14)} button:active{transform:scale(.98)}
.primary{background:linear-gradient(92deg,var(--green),#9ade1f);color:#07130a;box-shadow:0 8px 24px rgba(118,185,0,.22)}
.ghost{background:rgba(22,30,17,.7);color:var(--mint);border:1px solid var(--line2)}
.danger{background:rgba(60,18,16,.7);color:#ff9d97;border:1px solid #3a1d1a}
.gold{background:rgba(58,45,14,.7);color:var(--gold);border:1px solid #4a3a17}
/* ---------- key health table ---------- */
table{width:100%;border-collapse:collapse;font-size:13px}
th{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.18em;color:var(--faint);
  text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:11px 10px;border-bottom:1px solid rgba(28,36,24,.55);font-family:var(--mono);font-size:12px}
tr:last-child td{border-bottom:0}
.ok{color:var(--mint)} .bad{color:var(--red)} .warn{color:var(--gold)} .mut{color:var(--dim)}
/* ---------- stats ---------- */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-top:18px}
.stat{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:16px 18px;position:relative;overflow:hidden}
.stat::after{content:'';position:absolute;inset:auto -30% -60% auto;width:120px;height:120px;border-radius:50%;
  background:radial-gradient(circle,rgba(118,185,0,.09),transparent 70%)}
.stat .k{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.18em;color:var(--faint)}
.stat .v{font-family:var(--serif);font-size:27px;font-weight:600;margin-top:7px}
.v.green{color:var(--green)}.v.mint{color:var(--mint)}.v.gold{color:var(--gold)}.v.red{color:var(--red)}
/* ---------- model picker ---------- */
.msearch{position:relative}
.mlist{max-height:210px;overflow:auto;border:1px solid var(--line);border-radius:11px;margin-top:8px;background:#080b07}
.mlist div{padding:9px 14px;font-family:var(--mono);font-size:12px;color:var(--dim);cursor:pointer;
  display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid rgba(28,36,24,.5)}
.mlist div:hover,.mlist div.sel{background:rgba(118,185,0,.10);color:var(--ink)}
.mlist .cur{color:var(--green);font-size:10px;letter-spacing:.14em;text-transform:uppercase}
/* ---------- msg / toast ---------- */
#msg{margin-top:16px;font-size:13px;min-height:20px;white-space:pre-wrap;font-family:var(--mono)}
.ok{color:var(--mint)}.err{color:var(--red)}.warn{color:var(--gold)}
/* ---------- pipeline / self-design ---------- */
.pipe{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:8px}
@media (max-width:820px){.pipe{grid-template-columns:repeat(2,1fr)}}
.stage{border:1px solid var(--line);border-radius:13px;padding:16px;background:rgba(13,18,11,.7);position:relative}
.stage .n{font-family:var(--mono);font-size:10px;color:var(--green);letter-spacing:.24em}
.stage .t{font-family:var(--serif);font-size:16.5px;margin-top:8px}
.stage .d{font-size:12px;color:var(--dim);margin-top:6px;line-height:1.55}
.brief{font-family:var(--mono);font-size:12px;line-height:1.7;color:var(--mint);white-space:pre-wrap;
  background:#070a06;border:1px dashed var(--line2);border-radius:12px;padding:16px;margin-top:14px;display:none}
footer{margin-top:80px;border-top:1px solid var(--line);padding-top:22px;display:flex;justify-content:space-between;
  gap:14px;flex-wrap:wrap;color:var(--faint);font-family:var(--mono);font-size:11px;letter-spacing:.1em}
footer a{color:var(--dim);text-decoration:none}
</style>
</head>
<body>
<div class="wrap">

  <div class="topbar">
    <div>
      <div class="kicker">free-claume proxy <b>·</b> nvidia nim gateway <b>·</b> <span id="verline">v—</span></div>
      <h1 class="logo">claume <em>studio</em></h1>
      <p class="sub">The control room for your free coding agent — vault NVIDIA keys, verify the live
        model chain, and steer the design system claume builds with. Point any OpenAI SDK at
        <span class="inlinecode" id="baseurl2">…</span>.</p>
      <div class="pillrow">
        <span class="pill" id="pill-proxy"><span class="dot"></span>proxy live</span>
        <span class="pill" id="pill-keys"><span class="dot"></span>keys —</span>
        <span class="pill" id="pill-model"><span class="dot"></span>model —</span>
        <span class="pill" id="pill-update"><span class="dot"></span>version —</span>
      </div>
    </div>
  </div>

  <div class="explode" title="explode view — hover to separate the stack">
    <div class="layer l1"><span class="tag">layer 01 — gateway</span><div class="big">openai-compatible <i>streaming</i> endpoint</div></div>
    <div class="layer l2"><span class="tag">layer 02 — resilience</span><div class="big">key rotation <i>·</i> model fallback chain</div></div>
    <div class="layer l3"><span class="tag">layer 03 — upstream</span><div class="big">nvidia nim <i>integrate.api.nvidia.com</i></div></div>
  </div>
  <div class="hintline">hover to explode the stack</div>

  <!-- ══════════════ 01 · identity & keys ══════════════ -->
  <section>
    <div class="shead"><span class="snum">01</span><h2>Identity &amp; keys</h2></div>
    <p class="sdesc">Every key below is live-verified against NVIDIA — the table is the truth about your
      rotation pool, not just a masked string. Get free keys at
      <a href="https://build.nvidia.com/settings/api-keys" target="_blank">build.nvidia.com/settings/api-keys</a>.</p>
    <div class="grid2">
      <div class="card">
        <label>Add / replace primary key</label>
        <input type="password" id="apikey" placeholder="nvapi-… (leave empty to keep the saved one)">
        <label>Add rotation key</label>
        <input type="password" id="apikey2" placeholder="nvapi-… stored as NVIDIA_API_KEY_2, _3 …">
        <div class="row">
          <button class="primary" onclick="applyAll()">Apply</button>
          <button class="ghost" onclick="verifyAll()">&#9654; Verify all keys</button>
        </div>
        <div class="hint">Keys are stored locally in the obfuscated vault only. Rotation is automatic on
          401/403/429 — add several for heavy builds.</div>
      </div>
      <div class="card">
        <label>Key pool health <span style="float:right;text-transform:none;letter-spacing:0">
          <a href="javascript:refreshHealth()" style="color:var(--mint)">&#8635; re-probe</a></span></label>
        <table>
          <thead><tr><th>key</th><th>status</th><th>models</th><th></th></tr></thead>
          <tbody id="keyrows"><tr><td colspan="4" class="mut">probing…</td></tr></tbody>
        </table>
        <div class="hint" id="checkedline">—</div>
      </div>
    </div>
  </section>

  <!-- ══════════════ 02 · model chain ══════════════ -->
  <section>
    <div class="shead"><span class="snum">02</span><h2>Model chain</h2></div>
    <p class="sdesc">The primary model plus an ordered fallback chain — if a model is retired (410) or
      rate-limited mid-build, the proxy transparently walks the chain and your turn survives.
      The list is filtered to models that actually answer chat completions.</p>
    <div class="grid2">
      <div class="card">
        <label>Primary model</label>
        <div class="msearch">
          <input type="text" id="modelsearch" placeholder="search live models…" autocomplete="off">
          <div class="mlist" id="mlist"></div>
        </div>
        <label>Fallback models (one per line, tried in order)</label>
        <textarea id="fallbacks" rows="4" spellcheck="false"></textarea>
        <div class="row">
          <button class="primary" onclick="applyChain()">Save chain</button>
          <button class="ghost" onclick="loadModels(true)">&#8635; Refresh live models</button>
          <button class="ghost" onclick="verifyModel()">&#9654; Verify primary</button>
        </div>
      </div>
      <div class="card">
        <label>Live status</label>
        <div class="stats">
          <div class="stat"><div class="k">primary</div><div class="v mint" style="font-size:14px;font-family:var(--mono)" id="curmodel">—</div></div>
          <div class="stat"><div class="k">model probe</div><div class="v" id="modelprobe">—</div></div>
          <div class="stat"><div class="k">requests</div><div class="v green" id="reqs">0</div></div>
          <div class="stat"><div class="k">errors</div><div class="v gold" id="errs">0</div></div>
          <div class="stat" style="grid-column:1/-1"><div class="k">last proxy error</div>
            <div class="v mut" style="font-size:12.5px;font-family:var(--mono)" id="lasterr">none</div></div>
        </div>
      </div>
    </div>
  </section>

  <!-- ══════════════ 03 · design system ══════════════ -->
  <section>
    <div class="shead"><span class="snum">03</span><h2>Design system</h2></div>
    <p class="sdesc">claume's own visual language — the one that rendered this dashboard. Use it for
      claume's website or any app UI you ask it to design: the Link System pipeline walks these four
      stages, pulling fonts, components, motion and canvas assets as it builds.</p>
    <div class="pipe">
      <div class="stage"><div class="n">STAGE 1</div><div class="t">Layout blueprint</div>
        <div class="d">atomic-shadcnspace — grids, tokens, spatial rhythm. Typography: Fraunces display over Space Grotesk UI, JetBrains Mono for code.</div></div>
      <div class="stage"><div class="n">STAGE 2</div><div class="t">Human components</div>
        <div class="d">uidiscovery-21st — hand-designed blocks replace placeholder divs. NVIDIA-green (#76b900) on near-black, editorial serif italics.</div></div>
      <div class="stage"><div class="n">STAGE 3</div><div class="t">Motion timelines</div>
        <div class="d">animation-motion — Framer Motion springs, staggered entries, hover explode-layers with cubic-bezier(.19,1,.22,1).</div></div>
      <div class="stage"><div class="n">STAGE 4</div><div class="t">Canvas texture</div>
        <div class="d">microinteractions-reactbits — aurora shader fields, braille ripples, glass panel depth shadows.</div></div>
    </div>
    <div class="card" style="margin-top:22px">
      <label>Self-design brief — rebuild claume's website in this language</label>
      <div class="row" style="margin-top:6px">
        <button class="gold" onclick="genBrief()">✦ Generate design brief</button>
        <button class="ghost" onclick="copyBrief()">⧉ Copy brief</button>
      </div>
      <div class="brief" id="brief"></div>
      <div class="hint">Paste the brief into claume (<span class="inlinecode">claume</span> → paste → enter) and it
        rebuilds its own site — or any app UI you point it at — using the same fonts, palette, motion and
        explode-view mechanics rendered here.</div>
    </div>
  </section>

  <div id="msg"></div>

  <footer>
    <span>free-claume studio · <span id="verfoot">v—</span> · MIT © TRacKay</span>
    <span><a href="https://github.com/kayefande-droid/claume-code" target="_blank">github.com/kayefande-droid/claume-code</a>
      · <a href="https://build.nvidia.com" target="_blank">build.nvidia.com</a></span>
  </footer>
</div>

<script>
const $ = id => document.getElementById(id);
let MODELS = [], CURRENT = '', DATA = null, BRIEF = '';

function msg(text, cls){ const m=$('msg'); m.textContent=text; m.className=cls||''; }
function setPill(id, text, cls){ const p=$(id); p.innerHTML='<span class="dot"></span>'+text; p.className='pill '+(cls||''); }

/* ---------- data load ---------- */
async function loadData(){
  try{
    const r = await fetch('/admin/data'); DATA = await r.json();
    const d = DATA;
    $('verline').textContent = 'v' + (d.version||'?');
    $('verfoot').textContent = 'v' + (d.version||'?');
    $('baseurl2').textContent = d.base_url;
    $('reqs').textContent = d.stats.requests;
    $('errs').textContent = d.stats.errors;
    $('lasterr').textContent = d.stats.last_error || 'none';
    $('curmodel').textContent = d.model;
    CURRENT = d.model;
    if(!$('fallbacks').value && d.fallbacks) $('fallbacks').value = d.fallbacks.join('\n');
    if(!MODELS.length){ MODELS = d.models||[]; renderModels(); }
    setPill('pill-proxy', 'proxy live', '');
    setPill('pill-keys', 'keys ' + (d.has_key ? 'saved' : 'missing'), d.has_key ? '' : 'err');
    setPill('pill-model', d.model.split('/').pop().slice(0,26), '');
    checkUpdate();
    renderHealth(d.health);
  }catch(e){ setPill('pill-proxy','proxy unreachable','err'); msg('cannot reach proxy: '+e,'err'); }
}

/* ---------- key health ---------- */
function renderHealth(h){
  const tb = $('keyrows');
  if(!h || !h.keys || !h.keys.length){ tb.innerHTML = '<tr><td colspan="4" class="mut">no keys yet — add one on the left</td></tr>'; $('checkedline').textContent=''; return; }
  tb.innerHTML = h.keys.map(k =>
    '<tr><td>'+k.masked+'</td>' +
    '<td class="'+(k.ok?'ok':'bad')+'">'+(k.ok?(k.status===429?'valid · busy':'live'):'✗ HTTP '+k.status)+'</td>' +
    '<td class="mut">'+(k.ok?k.models:'—')+'</td>' +
    '<td><a href="javascript:delKey()" data-name="'+k.masked+'" style="color:var(--faint);text-decoration:none">✕</a></td></tr>'
  ).join('');
  const mp = h.model || {};
  $('modelprobe').innerHTML = mp.ok ? '<span class="ok">live</span>' : '<span class="bad">down</span>';
  $('modelprobe').title = (mp.id||'') + ' — ' + (mp.detail||'');
  $('checkedline').textContent = 'model ' + (mp.id||'—') + ': ' + (mp.detail||'—') + ' · checked ' + (h.checked_at||'');
}
async function refreshHealth(){
  msg('re-probing key pool…','warn');
  try{ const r = await fetch('/admin/refresh'); const d = await r.json(); renderHealth(d.health); msg('health refreshed','ok'); }
  catch(e){ msg('refresh failed: '+e,'err'); }
}
async function delKey(){
  const name = prompt('key NAME to remove (e.g. NVIDIA_API_KEY_2):');
  if(!name) return;
  const r = await fetch('/admin/key-del',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
  const d = await r.json();
  msg(d.ok ? 'removed '+d.removed+' — '+d.keys+' key(s) left' : ('✗ '+d.error||'not found'), d.ok?'ok':'err');
  refreshHealth(); loadData();
}

/* ---------- apply / verify ---------- */
async function applyAll(){
  const body = { api_key: $('apikey').value.trim(), model: CURRENT,
    fallbacks: $('fallbacks').value.split('\n').map(s=>s.trim()).filter(Boolean) };
  try{
    const r = await fetch('/admin/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d = await r.json();
    if(!d.ok){ msg('apply failed: '+(d.error||r.status),'err'); return; }
    let m = 'saved: '+d.changed.join(', ');
    $('apikey').value='';
    const k2 = $('apikey2').value.trim();
    if(k2){
      const r2 = await fetch('/admin/key-add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:k2})});
      const d2 = await r2.json();
      if(d2.ok){ m += ' · rotation key stored as '+d2.stored_as; $('apikey2').value=''; }
      else m += ' · ✗ rotation key rejected: '+d2.error;
    }
    msg(m,'ok'); refreshHealth(); loadData();
  }catch(e){ msg('apply failed: '+e,'err'); }
}
async function verifyAll(){
  msg('verifying every key against '+CURRENT+'…','warn');
  try{
    const r = await fetch('/admin/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:CURRENT})});
    const d = await r.json();
    if(d.ok) msg('✓ all '+d.keys.length+' key(s) verified on '+d.model+' — reply: "'+d.reply+'"','ok');
    else msg('✗ '+(d.error||('some keys failed: '+JSON.stringify(d.keys))),'err');
  }catch(e){ msg('verify failed: '+e,'err'); }
}
async function verifyModel(){
  msg('probing primary model…','warn');
  try{
    const r = await fetch('/admin/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:CURRENT})});
    const d = await r.json();
    if(d.ok) msg('✓ '+d.model+' replied: "'+d.reply+'" — chain is healthy','ok');
    else msg('✗ '+d.model+' — '+(d.error||'see key rows'),'err');
  }catch(e){ msg('verify failed: '+e,'err'); }
}
async function applyChain(){
  try{
    const r = await fetch('/admin/apply',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({model:CURRENT, fallbacks:$('fallbacks').value.split('\n').map(s=>s.trim()).filter(Boolean)})});
    const d = await r.json();
    msg(d.ok ? 'model chain saved — '+d.model : 'save failed','ok');
    loadData();
  }catch(e){ msg('save failed: '+e,'err'); }
}

/* ---------- models ---------- */
function renderModels(){
  const q = ($('modelsearch').value||'').toLowerCase();
  const list = MODELS.filter(m=>m.toLowerCase().includes(q)).slice(0,40);
  const el = $('mlist');
  el.innerHTML = list.map(m =>
    '<div onclick="pickModel(\''+m.replace(/'/g,"\\'")+'\')"><span>'+m+'</span>'+(m===CURRENT?'<span class="cur">primary</span>':'')+'</div>'
  ).join('') || '<div class="mut">no matches — refresh live models</div>';
}
function pickModel(m){ CURRENT = m; $('curmodel').textContent = m; setPill('pill-model', m.split('/').pop().slice(0,26),''); renderModels(); msg('primary set to '+m+' — press Save chain','warn'); }
async function loadModels(force){
  msg('loading live model list…','warn');
  try{
    const r = await fetch('/v1/models'); const d = await r.json();
    if(d.data && d.data.length){ MODELS = d.data.map(m=>m.id); renderModels(); msg('loaded '+MODELS.length+' chat-capable models','ok'); }
    else msg('model list unavailable (add a key first)','warn');
  }catch(e){ msg('failed: '+e,'err'); }
}
$('modelsearch').addEventListener('input', renderModels);

/* ---------- update check ---------- */
async function checkUpdate(){
  try{
    const r = await fetch('/admin/check-update'); const d = await r.json();
    if(d.update_available){
      setPill('pill-update','update '+d.latest+' available','warn');
      $('verline').textContent += ' → '+d.latest+' available';
    } else setPill('pill-update','v'+d.current+' is current','');
  }catch(e){ setPill('pill-update','version —','warn'); }
}

/* ---------- self-design brief ---------- */
function genBrief(){
  const d = DATA || {};
  BRIEF =
`DESIGN BRIEF — claume studio language (v${d.version||'2.3'})
Target: ${location.origin} — the claume website

TYPOGRAPHY (pull from Google Fonts):
  Display  : Fraunces (opsz 9..144, 300-700) — editorial serif, italics for emphasis
  UI       : Space Grotesk 300-700 — interface, labels, buttons
  Code     : JetBrains Mono 400/500/700 — code, kickers, data tables

PALETTE:
  bg #060807 · panel #0b0f0a→#10160e gradient · line #1c2418 / #2a3522
  text #e9f2e4 · dim #7d8a76 · nvidia-green #76b900 · lime #b7f04a
  mint #7ef0c0 · gold #e3b341 · red #f85149

MECHANICS (copy the /admin dashboard):
  · explode-view hero: 3 stacked layer-cards, perspective 1100px,
    hover separates on Z (translateZ ±70) with cubic-bezier(.19,1,.22,1)
  · kicker labels: JetBrains Mono 11px, .32em tracking, uppercase
  · numbered sections (01/02/03…) with serif H2s
  · glass-depth cards: 165deg panel gradient + 24px/50px black shadows
  · live status pills with pulsing 7px glow-dots
  · status table with per-row health, mono 12px

MOTION: staggered explodeIn on load (0.05/0.2/0.35s), spring hovers,
  scale(.98) on :active, smooth-scroll anchors.

ASSETS: pull iconography from Phosphor/Lucide, hero texture from an
  aurora canvas shader (reactbits), favicon from the claume pixel-bot.

Build it with the Link System pipeline (no placeholder divs).`;
  const b = $('brief'); b.textContent = BRIEF; b.style.display='block';
  msg('brief generated — copy it and paste into claume','ok');
}
function copyBrief(){
  if(!BRIEF) genBrief();
  (navigator.clipboard ? navigator.clipboard.writeText(BRIEF) : Promise.reject())
    .then(()=>msg('brief copied — paste into claume','ok'))
    .catch(()=>msg('select the brief text manually to copy','warn'));
}

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""

# Kept for backward compatibility with the old /proxy-ui dashboard route.
DASHBOARD_HTML = ADMIN_HTML
