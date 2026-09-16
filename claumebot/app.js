/* claume bot — renderer app (v3.2)
 * Bridge client + voice pipeline + master onboarding.
 * The 3D point-cloud avatar lives in avatar.js; this file drives its states.
 */
'use strict';

const $ = (id) => document.getElementById(id);

const state = {
  port: 8765,
  master: '',
  mode: 'BOOTING',           // BOOTING | IDLE | LISTENING | THINKING | SPEAKING
  camOn: false,
  camStream: null,
  ttsVoices: [],
  ttsVoiceIdx: -1,
  speaking: false,
  wake: null,                // webkitSpeechRecognition handle
  wakeOn: false,
  recording: false,
};

/* ---------------- bridge helpers ---------------- */
function apiBase() { return `http://127.0.0.1:${state.port}`; }

async function apiGet(path) {
  const r = await fetch(`${apiBase()}${path}`);
  if (!r.ok) throw new Error(`GET ${path} -> ${r.status}`);
  return r.json();
}
async function apiPost(path, body, raw = false) {
  const r = await fetch(`${apiBase()}${path}`, {
    method: 'POST',
    headers: raw ? { 'Content-Type': 'application/octet-stream' } : { 'Content-Type': 'application/json' },
    body: raw ? body : JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `${path} -> ${r.status}`);
  return j;
}

/* ---------------- UI state ---------------- */
function setMode(mode) {
  state.mode = mode;
  const chip = $('stateChip');
  chip.textContent = mode;
  chip.className = '';
  if (mode === 'LISTENING') chip.classList.add('listening');
  if (mode === 'SPEAKING') chip.classList.add('speaking');
  if (window.Avatar) Avatar.setMode(mode);
}
function out(text, isErr = false) {
  const el = $('terminalOutput');
  el.textContent = text;
  el.classList.toggle('err', isErr);
}
const THINK_LINES = [
  'Parsing instruction… mapping token routes… validating runtime channels…',
  'Consulting claume reasoning chain… weighing options…',
  'Scanning context… aligning response vectors…',
  'Cross-checking memory of you, master… composing…',
];
let thinkTimer = null;
function thinking(on) {
  const box = $('thinkingConsole');
  if (on) {
    $('thinkingLog').textContent = THINK_LINES[Math.floor(Math.random() * THINK_LINES.length)];
    box.classList.add('on');
    let i = 1;
    thinkTimer = setInterval(() => {
      $('thinkingLog').textContent = THINK_LINES[(i++) % THINK_LINES.length];
    }, 1600);
  } else {
    box.classList.remove('on');
    if (thinkTimer) { clearInterval(thinkTimer); thinkTimer = null; }
  }
  setMode(on ? 'THINKING' : 'IDLE');
}

/* ---------------- TTS ---------------- */
function loadVoices() {
  const synth = window.speechSynthesis;
  if (!synth) return;
  const fill = () => {
    state.ttsVoices = synth.getVoices().filter((v) => v.lang && v.lang.startsWith('en'));
    const sel = $('voiceSelect');
    sel.innerHTML = '';
    state.ttsVoices.forEach((v, i) => {
      const o = document.createElement('option');
      o.value = String(i);
      o.textContent = `${v.name} (${v.lang})`;
      sel.appendChild(o);
    });
    // prefer human-sounding Windows voices for the "human speech/accent" ask
    const prefer = ['zira', 'aria', 'jenny', 'guy', 'david', 'google uk english female', 'google us english'];
    let idx = state.ttsVoices.findIndex((v) => prefer.some((p) => v.name.toLowerCase().includes(p)));
    if (idx < 0 && state.ttsVoices.length) idx = 0;
    state.ttsVoiceIdx = idx;
    if (idx >= 0) sel.value = String(idx);
  };
  fill();
  synth.onvoiceschanged = fill;
}

async function speak(text) {
  if (!text) return;
  state.speaking = true;
  setMode('SPEAKING');
  try {
    // 1) backend pyttsx3 (SAPI5 human neural voices, offline)
    const r = await fetch(`${apiBase()}/api/tts?text=${encodeURIComponent(text.slice(0, 900))}`);
    if (r.ok) {
      const blob = await r.blob();
      await playBlob(blob);
      state.speaking = false;
      setMode('IDLE');
      return;
    }
  } catch (_) { /* fall through to web speech */ }
  // 2) Web Speech fallback with accent selection
  return new Promise((resolve) => {
    const synth = window.speechSynthesis;
    if (!synth) { state.speaking = false; setMode('IDLE'); resolve(); return; }
    const u = new SpeechSynthesisUtterance(text);
    if (state.ttsVoiceIdx >= 0 && state.ttsVoices[state.ttsVoiceIdx]) {
      u.voice = state.ttsVoices[state.ttsVoiceIdx];
      u.lang = u.voice.lang;
    }
    u.rate = 1.0; u.pitch = 1.0;
    u.onend = u.onerror = () => { state.speaking = false; setMode('IDLE'); resolve(); };
    synth.speak(u);
  });
}
function playBlob(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const a = new Audio(url);
    a.onended = () => { URL.revokeObjectURL(url); resolve(); };
    a.onerror = (e) => { URL.revokeObjectURL(url); reject(e); };
    a.play().catch(reject);
  });
}

/* ---------------- camera ---------------- */
async function initCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 360 }, audio: false });
    state.camStream = stream;
    $('cam').srcObject = stream;
    $('camOff').style.display = 'none';
    state.camOn = true;
    $('nodeCam').textContent = 'LIVE';
    $('nodeCam').className = 'ready';
  } catch (_) {
    $('nodeCam').textContent = 'DENIED';
    $('nodeCam').className = 'off';
  }
}
function camFrame() {
  if (!state.camOn) return '';
  const v = $('cam');
  if (!v.videoWidth) return '';
  const c = document.createElement('canvas');
  c.width = 640; c.height = 360;
  const ctx = c.getContext('2d');
  ctx.translate(c.width, 0); ctx.scale(-1, 1);      // un-mirror
  ctx.drawImage(v, 0, 0, c.width, c.height);
  return c.toDataURL('image/jpeg', 0.72);
}

/* ---------------- chat ---------------- */
async function send(text, { fromVoice = false } = {}) {
  text = (text || '').trim();
  if (!text || state.mode === 'THINKING') return;
  $('commandInputField').value = '';
  out(`you: ${text}`);
  thinking(true);
  try {
    const image = camFrame();
    const j = await apiPost('/api/chat', { text, image });
    const reply = j.reply || j.error || '(empty reply)';
    out(reply);
    await speak(reply);
  } catch (e) {
    out(`bridge error: ${e.message}`, true);
    setMode('IDLE');
  } finally {
    thinking(false);
    if (fromVoice) armWake();   // resume wake listening after a voice turn
  }
}

/* ---------------- screen vision ---------------- */
async function lookAtScreen() {
  if (state.mode === 'THINKING') return;
  thinking(true);
  try {
    const j = await apiPost('/api/screen', { note: 'Look at my screen. Tell me what you see, any errors or problems, and how to fix them.' });
    out(j.reply || '(no reply)');
    await speak(j.reply || '');
  } catch (e) {
    out(`screen error: ${e.message}`, true);
  } finally {
    thinking(false);
  }
}

/* ---------------- voice input ---------------- */
// Primary: MediaRecorder -> backend STT (works offline of any web-key quotas).
// Wake word: webkitSpeechRecognition continuous scan for "claume"/"jarvis".
function rmsLevel(analyser, buf) {
  analyser.getByteTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
  return Math.sqrt(sum / buf.length);
}

async function recordUtterance() {
  // Records until ~1.4s of silence or 12s cap; returns WAV bytes.
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  src.connect(analyser);
  const buf = new Uint8Array(analyser.fftSize);

  const rec = new MediaRecorder(stream);
  const chunks = [];
  rec.ondataavailable = (e) => chunks.push(e.data);
  const done = new Promise((res) => { rec.onstop = res; });
  rec.start();

  const t0 = performance.now();
  let spoke = false, quiet = 0;
  await new Promise((res) => {
    const tick = () => {
      const lvl = rmsLevel(analyser, buf);
      if (lvl > 0.045) { spoke = true; quiet = 0; }
      else if (spoke) quiet += 50;
      const elapsed = performance.now() - t0;
      if ((spoke && quiet > 1400) || elapsed > 12000) res();
      else setTimeout(tick, 50);
    };
    tick();
  });
  rec.stop();
  await done;
  stream.getTracks().forEach((t) => t.stop());
  ctx.close();

  const blob = new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' });
  // WebM from MediaRecorder — decode & re-encode to 16k mono WAV in-line.
  const ab = await blob.arrayBuffer();
  const actx = new AudioContext();
  const audio = await actx.decodeAudioData(ab);
  const ch = audio.getChannelData(0);
  // resample naive
  const target = 16000;
  const ratio = audio.sampleRate / target;
  const n = Math.floor(ch.length / ratio);
  const pcm = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, ch[Math.floor(i * ratio)]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  const wav = encodeWav(pcm, target);
  actx.close();
  return wav;
}
function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const ws = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  ws(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); ws(8, 'WAVE');
  ws(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  ws(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) v.setInt16(44 + i * 2, samples[i], true);
  return new Uint8Array(buf);
}

async function micOnce() {
  if (state.recording || state.speaking) return;
  state.recording = true;
  $('micBtn').classList.add('mic-on');
  setMode('LISTENING');
  try {
    const wav = await recordUtterance();
    const j = await apiPost('/api/stt', wav, true);
    state.recording = false;
    $('micBtn').classList.remove('mic-on');
    if (j.text) await send(j.text, { fromVoice: true });
    else { setMode('IDLE'); armWake(); }
  } catch (e) {
    state.recording = false;
    $('micBtn').classList.remove('mic-on');
    out(`mic error: ${e.message}`, true);
    setMode('IDLE');
  }
}

/* Wake word via continuous webkitSpeechRecognition (Electron/Chromium has it) */
function armWake() {
  const SR = window.webkitSpeechRecognition || window.SpeechRecognition;
  if (!SR || state.wakeOn) return;
  try {
    const r = new SR();
    r.continuous = true; r.interimResults = true; r.lang = 'en-US';
    r.onresult = (ev) => {
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const t = ev.results[i][0].transcript.toLowerCase();
        if (/\b(claume|clau?mi|jarvis|ja?vis)\b/.test(t)) {
          if (!state.recording && !state.speaking) {
            try { r.stop(); } catch (_) {}
            micOnce();
          }
          return;
        }
        // full-sentence pickup: if SR already produced a final phrase, use it
        if (ev.results[i].isFinal && state.mode === 'IDLE' && !state.speaking) {
          const final = ev.results[i][0].transcript.trim();
          if (final.split(/\s+/).length >= 2) {
            try { r.stop(); } catch (_) {}
            send(final, { fromVoice: true });
          }
        }
      }
    };
    r.onend = () => { if (state.wakeOn) { try { r.start(); } catch (_) {} } };
    r.onerror = () => { /* network hiccups: onend restarts */ };
    state.wake = r;
    state.wakeOn = true;
    $('micBtn').classList.add('mic-on');
    setMode(state.mode === 'SPEAKING' ? 'SPEAKING' : 'IDLE');
  } catch (_) { /* wake unsupported — MIC button remains */ }
}
function disarmWake() {
  state.wakeOn = false;
  try { state.wake && state.wake.stop(); } catch (_) {}
  $('micBtn').classList.remove('mic-on');
}

/* ---------------- master onboarding ---------------- */
async function refreshMaster() {
  const j = await apiGet('/api/master');
  state.master = (j.name || '').trim();
  $('masterName').textContent = state.master || 'unknown';
  if (state.master) {
    $('onboard').classList.remove('on');
    $('masterHint').textContent = `remembered — welcome back, ${state.master}.`;
  } else {
    $('onboard').classList.add('on');
    setTimeout(() => $('onboardInput').focus(), 120);
  }
  return state.master;
}
async function registerMaster() {
  const name = $('onboardInput').value.trim();
  if (!name) { $('onboardErr').textContent = 'I need a name, master.'; return; }
  try {
    await apiPost('/api/master', { name });
    $('onboard').classList.remove('on');
    $('masterHint').textContent = 'identity stored.';
    greet();
  } catch (e) {
    $('onboardErr').textContent = e.message;
  }
}
async function greet() {
  const name = state.master || (await refreshMaster());
  const line = name
    ? `Good to see you again, ${name}. All systems are yours.`
    : 'Systems online. I am claume bot, bound to your claume core.';
  out(line);
  speak(line);
}
function setMasterFromInput() {
  const name = $('masterInput').value.trim();
  if (!name) return;
  apiPost('/api/master', { name })
    .then(() => { $('masterInput').value = ''; refreshMaster(); greet(); })
    .catch((e) => out(e.message, true));
}

/* ---------------- health loop ---------------- */
async function health() {
  try {
    const j = await apiGet('/api/health');
    $('bridgeChip').textContent = 'BRIDGE ONLINE';
    $('bridgeChip').className = 'chip';
    $('bridgeChip').style.color = 'var(--ok)';
    $('bridgeChip').style.borderColor = 'rgba(52,211,153,.3)';
    $('verChip').textContent = `V${j.version}`;
    $('nodeLlm').textContent = j.provider || 'tokenin';
    $('nodeLlm').className = 'ready';
    $('nodeStt').textContent = j.stt ? 'BOUND' : 'OFF';
    $('nodeStt').className = j.stt ? '' : 'off';
    $('nodeTts').textContent = j.tts ? 'BOUND' : 'WEB';
    $('nodeTts').className = j.tts ? 'ready' : 'off';
    $('nodeScreen').textContent = 'READY';
    $('nodeScreen').className = 'ready';
    return true;
  } catch (_) {
    $('bridgeChip').textContent = 'BRIDGE OFFLINE';
    $('bridgeChip').className = 'chip err';
    ['nodeLlm', 'nodeStt', 'nodeTts', 'nodeScreen'].forEach((id) => { $(id).textContent = 'OFF'; $(id).className = 'off'; });
    return false;
  }
}

/* ---------------- boot ---------------- */
async function boot() {
  try { state.port = (window.claumebot && await window.claumebot.pyPort()) || 8765; } catch (_) {}
  loadVoices();
  setMode('BOOTING');
  let up = await health();
  for (let i = 0; i < 12 && !up; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    up = await health();
  }
  if (!up) out('bridge offline — is claumebot_server.py running? (I still work in web-voice mode.)', true);
  await refreshMaster();
  if (state.master) greet();
  await initCamera();
  setMode('IDLE');
  armWake();          // always-listening wake word ("claume" / "jarvis")
  setInterval(health, 10000);
}

/* ---------------- wire events ---------------- */
window.addEventListener('DOMContentLoaded', () => {
  $('btnSend').onclick = () => send($('commandInputField').value);
  $('commandInputField').addEventListener('keydown', (e) => { if (e.key === 'Enter') send($('commandInputField').value); });
  $('micBtn').onclick = () => (state.wakeOn ? disarmWake() : micOnce());
  $('btnScreen').onclick = lookAtScreen;
  $('btnSetMaster').onclick = setMasterFromInput;
  $('onboardBtn').onclick = registerMaster;
  $('onboardInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') registerMaster(); });
  $('voiceSelect').onchange = (e) => { state.ttsVoiceIdx = parseInt(e.target.value, 10) || 0; };
  const tb = (id, act) => { const b = $(id); if (b) b.onclick = () => window.claumebot && window.claumebot.win(act); };
  tb('btnMin', 'minimize'); tb('btnMax', 'maximize'); tb('btnClose', 'close');
  boot();
});
