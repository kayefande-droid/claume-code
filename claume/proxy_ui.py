"""Admin UI assets for the free-claume proxy.

The proxy serves this single-file dashboard at http://127.0.0.1:8000/admin
- FCC-style: paste your key, pick the model, click Apply / Verify.
"""

# NOTE: this module must stay import-free (no sibling imports) because
# claume.proxy imports ADMIN_HTML from it at module load time.""

# The luxurious proxy dashboard (GET /admin) — dark NVIDIA-green theme,
# key field, searchable model dropdown, fallback list, live verify.
ADMIN_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>free-claume admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root{
    --bg:#07090c; --panel:#0d1117; --panel2:#111823; --line:#1d2634;
    --green:#76b900; --mint:#7ef0c0; --text:#e6edf3; --dim:#8b949e;
    --gold:#e3b341; --red:#f85149;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    background:
      radial-gradient(1200px 600px at 20% -10%, rgba(118,185,0,.09), transparent 60%),
      radial-gradient(900px 500px at 90% 110%, rgba(126,240,192,.05), transparent 60%),
      var(--bg);
    color:var(--text); font-family:"Segoe UI",system-ui,sans-serif; min-height:100vh;
  }
  .wrap{max-width:920px;margin:0 auto;padding:44px 22px}
  .logo{font-size:38px;font-weight:800;letter-spacing:-1px}
  .logo .g{color:var(--green)} .logo .m{color:var(--mint)}
  .sub{color:var(--dim);margin-top:6px}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--green);
    box-shadow:0 0 10px var(--green);margin-right:8px;animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  .card{
    background:linear-gradient(180deg,var(--panel2),var(--panel));
    border:1px solid var(--line);border-radius:14px;padding:22px;margin-top:22px;
    box-shadow:0 10px 30px rgba(0,0,0,.35);
  }
  label{display:block;color:var(--dim);font-size:12px;text-transform:uppercase;
    letter-spacing:.12em;margin:16px 0 6px}
  label:first-child{margin-top:0}
  input[type=text],input[type=password]{width:100%;padding:12px 14px;border-radius:10px;
    border:1px solid var(--line);background:#0a0e14;color:var(--text);font-size:14px;
    outline:none;transition:border-color .15s}
  input:focus{border-color:var(--green)}
  select{width:100%;padding:12px 14px;border-radius:10px;border:1px solid var(--line);
    background:#0a0e14;color:var(--text);font-size:14px;outline:none}
  .hint{color:var(--dim);font-size:12px;margin-top:6px;line-height:1.5}
  .hint a{color:var(--mint);text-decoration:none}
  .row{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}
  button{
    flex:1;min-width:140px;padding:12px 18px;border-radius:10px;border:0;cursor:pointer;
    font-size:14px;font-weight:700;letter-spacing:.02em;transition:transform .1s,filter .15s;
  }
  button:hover{filter:brightness(1.12)} button:active{transform:scale(.98)}
  .primary{background:linear-gradient(90deg,var(--green),#8fd400);color:#04140a}
  .ghost{background:var(--panel2);color:var(--mint);border:1px solid var(--line)}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-top:22px}
  .stat{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:14px}
  .stat .k{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.1em}
  .stat .v{font-size:22px;font-weight:700;margin-top:6px}
  .v.green{color:var(--green)} .v.mint{color:var(--mint)} .v.gold{color:var(--gold)}
  #msg{margin-top:14px;font-size:13px;min-height:18px;white-space:pre-wrap}
  .ok{color:var(--mint)} .err{color:var(--red)} .warn{color:var(--gold)}
  code{background:var(--panel2);border:1px solid var(--line);padding:2px 8px;border-radius:6px;font-size:12px}
</style>
</head>
<body>
<div class="wrap">
  <div class="logo"><span class="g">free</span>-claume <span class="m">admin</span></div>
  <div class="sub"><span class="dot"></span>OpenAI-compatible gateway to NVIDIA NIM &middot; paste your key, pick a model, Apply.</div>

  <div class="card">
    <label>API key (NVIDIA NIM)</label>
    <input type="password" id="apikey" placeholder="nvapi-... (leave empty to keep the saved one)">
    <div class="hint">Get a free key at <a href="https://build.nvidia.com/settings/api-keys" target="_blank">build.nvidia.com/settings/api-keys</a> &middot; stored locally only. <span id="keymask"></span></div>

    <label>Model</label>
    <select id="model"></select>
    <div class="hint">Default: <code>nvidia/nemotron-3-super-120b-a12b</code> &middot; the dropdown loads live models from your key.</div>

    <label>Fallback models (one per line, tried in order)</label>
    <textarea id="fallbacks" rows="3" style="width:100%;padding:12px 14px;border-radius:10px;border:1px solid var(--line);background:#0a0e14;color:var(--text);font-size:13px;outline:none"></textarea>
    <div class="hint">If the main model is down or end-of-life, requests automatically try these next.</div>

    <div class="row">
      <button class="primary" onclick="apply()">Apply</button>
      <button class="ghost" onclick="verify()">&#9654; Verify</button>
      <button class="ghost" onclick="loadModels()">&#8635; Refresh models</button>
    </div>
    <div id="msg"></div>
  </div>

  <div class="stats">
    <div class="stat"><div class="k">Endpoint</div><div class="v mint" style="font-size:15px" id="baseurl">—</div></div>
    <div class="stat"><div class="k">Key</div><div class="v green" id="keystate">—</div></div>
    <div class="stat"><div class="k">Requests</div><div class="v" id="reqs">0</div></div>
    <div class="stat"><div class="k">Errors</div><div class="v gold" id="errs">0</div></div>
  </div>

  <div class="card" style="margin-top:22px">
    <div class="hint" style="font-size:13px">
      <b style="color:var(--text)">Use it anywhere:</b> point any OpenAI SDK at <code id="baseurl2">…</code> —
      or just run <code>claume</code> in another terminal; the agent talks to this proxy automatically.
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let MODELS = [];

function msg(text, cls){ const m=$('msg'); m.textContent=text; m.className=cls||''; }

async function loadData(){
  try{
    const r = await fetch('/admin/data'); const d = await r.json();
    $('keystate').textContent = d.has_key ? 'saved' : 'missing';
    $('keymask').textContent = d.key_masked ? ('saved: '+d.key_masked) : '';
    $('reqs').textContent = d.stats.requests;
    $('errs').textContent = d.stats.errors;
    $('baseurl').textContent = d.base_url; $('baseurl2').textContent = d.base_url;
    if(!MODELS.length){ MODELS = d.models||[]; fillModels(d.model); }
    if(d.fallbacks && !$('fallbacks').value) $('fallbacks').value = d.fallbacks.join('\n');
  }catch(e){ msg('cannot reach proxy: '+e, 'err'); }
}

function fillModels(current){
  const sel = $('model'); sel.innerHTML='';
  if(current && !MODELS.includes(current)){
    const o=document.createElement('option'); o.value=current; o.textContent=current+' (current)'; sel.appendChild(o);
  }
  for(const m of MODELS){
    const o=document.createElement('option'); o.value=m; o.textContent=m; sel.appendChild(o);
  }
  if(current) sel.value = current;
  else if(MODELS.includes('nvidia/nemotron-3-super-120b-a12b')) sel.value='nvidia/nemotron-3-super-120b-a12b';
}

async function loadModels(){
  msg('loading live model list…','warn');
  try{
    const r = await fetch('/v1/models'); const d = await r.json();
    if(d.data && d.data.length){ MODELS = d.data.map(m=>m.id); fillModels($('model').value); msg('loaded '+MODELS.length+' models','ok'); }
    else msg('model list unavailable (add a key first)','warn');
  }catch(e){ msg('failed: '+e,'err'); }
}

async function apply(){
  const body = {
    api_key: $('apikey').value.trim(),
    model: $('model').value,
    fallbacks: $('fallbacks').value.split('\n').map(s=>s.trim()).filter(Boolean),
  };
  try{
    const r = await fetch('/admin/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d = await r.json();
    if(!d.ok){ msg('apply failed: '+(d.error||r.status),'err'); return; }
    let m = 'saved: '+d.changed.join(', ');
    if(body.api_key) m += ' — key stored';
    msg(m,'ok'); $('apikey').value='';
    loadData();
  }catch(e){ msg('apply failed: '+e,'err'); }
}

async function verify(){
  msg('testing model with your key…','warn');
  try{
    const r = await fetch('/admin/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:$('model').value})});
    const d = await r.json();
    if(d.ok) msg('✓ '+d.model+' replied: "'+d.reply+'" — you are good to go','ok');
    else msg('✗ '+d.model+' — '+(d.error||('HTTP '+d.status)),'err');
  }catch(e){ msg('verify failed: '+e,'err'); }
}

loadData();
</script>
</body>
</html>"""

# Kept for backward compatibility with the old /proxy-ui dashboard route.
DASHBOARD_HTML = ADMIN_HTML

# The old /proxy-ui dashboard was merged into /admin (FCC-style).
