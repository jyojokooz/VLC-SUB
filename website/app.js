/**
 * .Vsub Web App — three transcription tiers, one results panel.
 *
 *   1. On-device  — Whisper (Transformers.js) on WebGPU/WASM. No account,
 *                   no key, no upload, no limit. The default and the $0 path.
 *   2. Cloud trial — small clips go to the .Vsub proxy (Groq Whisper), which
 *                   applies a per-IP daily quota. Nothing to install.
 *   3. BYOK        — the user's own Groq/OpenAI key, called straight from the
 *                   browser. Unlimited for them, $0 for us.
 *
 * A Pro subscription (higher cloud limits, no key) is not wired yet: it needs
 * a billing provider and server-side entitlements.
 */

// ─────────────────────────────────────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────────────────────────────────────
const TRANSFORMERS_CDN = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.7.2';
const VSUB_CLOUD_URL = 'https://vlc-sub.onrender.com/transcribe';
const GROQ_API_URL = 'https://api.groq.com/openai/v1/audio/transcriptions';
const OPENAI_API_URL = 'https://api.openai.com/v1/audio/transcriptions';
const SAMPLE_RATE = 16000;
const CLOUD_MAX_MB = 25;   // server-side cap for the free cloud trial

const DEVICE_CONFIG = {
  webgpu: { device: 'webgpu', dtype: { encoder_model: 'fp32', decoder_model_merged: 'q4' } },
  wasm: { device: 'wasm', dtype: 'q8' },
};

// Google Translate (unofficial, free — same as the desktop app uses)
const GT_URL = 'https://translate.googleapis.com/translate_a/t';

// ─────────────────────────────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────────────────────────────
const files = { browser: null, cloud: null, byok: null };

let activeMode = 'browser';
let generatedSRT = '';
let generatedVTT = '';
let stopSignal = false;
let transcriber = null;
let transcriberKey = '';
let chosenDevice = null;
let transformers = null;
let ticker = null;
let tickStart = 0;
let cloudAbort = null;

// ─────────────────────────────────────────────────────────────────────────────
// MODE SWITCHING
// ─────────────────────────────────────────────────────────────────────────────
function switchMode(mode) {
  activeMode = mode;
  document.querySelectorAll('.mode-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tier-btn').forEach(b => b.classList.remove('active'));
  const panel = document.getElementById('panel-' + mode);
  const btn = document.querySelector(`[data-mode="${mode}"]`);
  if (panel) panel.classList.add('active');
  if (btn) btn.classList.add('active');
  document.getElementById('results-panel').classList.remove('show');
}

// ─────────────────────────────────────────────────────────────────────────────
// FILE SELECTION
// ─────────────────────────────────────────────────────────────────────────────
function setupDropZone(zoneId, inputId, nameId, sizeId, mode) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  if (!zone || !input) return;

  const accept = f => { files[mode] = f; showFileInfo(f, nameId, sizeId); };
  input.addEventListener('change', () => { if (input.files[0]) accept(input.files[0]); });

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const f = e.dataTransfer.files[0];
    if (f) accept(f);
  });
}

function showFileInfo(file, nameId, sizeId) {
  document.getElementById(nameId).textContent = file.name;
  document.getElementById(sizeId).textContent = (file.size / 1024 / 1024).toFixed(1) + ' MB';
  const info = document.getElementById(nameId).closest('.file-selected');
  if (info) info.classList.add('show');
}

setupDropZone('drop-zone', 'file-input', 'file-name-label', 'file-size-label', 'browser');
setupDropZone('drop-zone-cloud', 'file-input-cloud', 'file-name-cloud', 'file-size-cloud', 'cloud');
setupDropZone('drop-zone-byok', 'file-input-byok', 'file-name-byok', 'file-size-byok', 'byok');

// ─────────────────────────────────────────────────────────────────────────────
// UI HELPERS  (suffix '' = on-device panel, '-cloud', '-byok')
// ─────────────────────────────────────────────────────────────────────────────
/**
 * pct === null shows an indeterminate bar, used while Whisper is listening
 * (there is no honest percentage to report there).
 */
function setProgress(suffix, pct, status, detail) {
  const bar = document.getElementById('prog-bar' + suffix);
  const pctEl = document.getElementById('prog-pct' + suffix);
  const stat = document.getElementById('prog-status' + suffix);
  const det = document.getElementById('prog-detail' + suffix);
  if (bar) {
    const track = bar.parentElement;
    if (pct === null) {
      track.classList.add('indeterminate');
      if (pctEl) pctEl.textContent = '···';
    } else {
      track.classList.remove('indeterminate');
      bar.style.width = pct + '%';
      if (pctEl) pctEl.textContent = pct + '%';
    }
  }
  if (stat) stat.textContent = status;
  if (det) det.textContent = detail || '';
}

function showProgress(suffix) {
  const el = document.getElementById('progress-area' + suffix);
  if (el) el.classList.add('show');
}

function logMsg(suffix, msg, cls) {
  const box = document.getElementById('log-box' + suffix);
  if (!box) return;
  box.classList.add('show');
  const line = document.createElement('div');
  if (cls) line.className = cls;
  line.textContent = msg;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function clearLog(suffix) {
  const box = document.getElementById('log-box' + suffix);
  if (box) box.innerHTML = '';
}

function setBusy(suffix, busy) {
  const gen = document.getElementById('btn-generate' + suffix);
  const stop = document.getElementById('btn-stop' + suffix);
  if (gen) gen.disabled = busy;
  if (stop) busy ? stop.classList.add('show') : stop.classList.remove('show');
}

function showResults(srtText) {
  generatedSRT = srtText;
  generatedVTT = srtToVTT(srtText);
  const preview = document.getElementById('srt-preview');
  preview.textContent = srtText.slice(0, 3000) + (srtText.length > 3000 ? '\n...' : '');
  document.getElementById('results-panel').classList.add('show');
  document.getElementById('results-panel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function fmtClock(sec) {
  const total = Math.max(0, Math.floor(sec));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// SRT / VTT GENERATION
// ─────────────────────────────────────────────────────────────────────────────
function formatTimeSRT(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  const ms = Math.round((sec - Math.floor(sec)) * 1000);
  return `${pad(h)}:${pad(m)}:${pad(s)},${pad(ms, 3)}`;
}

function formatTimeVTT(sec) {
  return formatTimeSRT(sec).replace(',', '.');
}

function pad(n, len = 2) {
  return String(n).padStart(len, '0');
}

function segmentsToSRT(segments) {
  return segments
    .map((s, i) =>
      `${i + 1}\n${formatTimeSRT(s.start)} --> ${formatTimeSRT(s.end)}\n${s.text.trim()}\n`
    )
    .join('\n');
}

function srtToVTT(srt) {
  return 'WEBVTT\n\n' + srt.replace(/,(\d{3})/g, '.$1');
}

// Whisper labels non-speech audio with bracketed markers; those are not
// subtitles and must not end up in the SRT.
const NO_SPEECH_RE = /^[\[(]\s*(blank_?audio|silence|music|inaudible|no speech|applause|sound effect)\b[^\])]*[\])]$/i;

function isNoSpeech(text) {
  return NO_SPEECH_RE.test(text.trim());
}

function buildSegments(result, duration) {
  const chunks = (result.chunks || []).filter(c => c.text && c.text.trim() && !isNoSpeech(c.text));
  if (!chunks.length) {
    const text = (result.text || '').trim();
    return text && !isNoSpeech(text) ? [{ start: 0, end: duration || 3, text }] : [];
  }
  return chunks.map(c => {
    const [rawStart, rawEnd] = c.timestamp || [];
    const start = Number.isFinite(rawStart) ? rawStart : 0;
    let end = Number.isFinite(rawEnd) ? rawEnd : (Number.isFinite(rawStart) ? rawStart + 3 : (duration || 3));
    if (duration && end > duration) end = duration;
    if (end <= start) end = start + (duration ? Math.min(3, Math.max(0.5, duration - start)) : 3);
    return {
      start,
      end,
      // A literal "-->" inside a cue would corrupt the SRT structure.
      text: c.text.trim().replace(/-->/g, '→'),
    };
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// AUDIO DECODE — Whisper needs 16 kHz mono Float32 samples
// ─────────────────────────────────────────────────────────────────────────────
async function decodeAudio(file) {
  const bytes = await file.arrayBuffer();
  const Ctx = window.AudioContext || window.webkitAudioContext;
  let ctx;
  try { ctx = new Ctx({ sampleRate: SAMPLE_RATE }); } catch { ctx = new Ctx(); }

  let buffer;
  try {
    buffer = await ctx.decodeAudioData(bytes);
  } catch {
    throw new Error(
      "This browser can't decode that file. On-device mode handles MP4/MOV, WebM, MP3, WAV, M4A, OGG and FLAC — convert MKV/AVI first (the Desktop app opens those directly)."
    );
  } finally {
    ctx.close();
  }

  let samples;
  if (buffer.numberOfChannels === 1) {
    samples = buffer.getChannelData(0);
  } else {
    const len = buffer.length;
    samples = new Float32Array(len);
    for (let c = 0; c < buffer.numberOfChannels; c++) {
      const data = buffer.getChannelData(c);
      for (let i = 0; i < len; i++) samples[i] += data[i];
    }
    for (let i = 0; i < len; i++) samples[i] /= buffer.numberOfChannels;
  }

  if (buffer.sampleRate !== SAMPLE_RATE) {
    samples = await resample(samples, buffer.sampleRate, SAMPLE_RATE);
  }
  return samples;
}

async function resample(samples, fromRate, toRate) {
  const length = Math.ceil(samples.length * toRate / fromRate);
  const ctx = new OfflineAudioContext(1, length, toRate);
  const buffer = ctx.createBuffer(1, samples.length, fromRate);
  buffer.copyToChannel(samples, 0);
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(ctx.destination);
  src.start();
  const rendered = await ctx.startRendering();
  return rendered.getChannelData(0);
}

// ─────────────────────────────────────────────────────────────────────────────
// DEVICE / MODEL LOADING
// ─────────────────────────────────────────────────────────────────────────────
async function detectDevice() {
  if (chosenDevice) return chosenDevice;
  chosenDevice = 'wasm';
  try {
    if (navigator.gpu && navigator.gpu.requestAdapter) {
      const adapter = await navigator.gpu.requestAdapter();
      if (adapter) chosenDevice = 'webgpu';
    }
  } catch {
    chosenDevice = 'wasm';
  }
  return chosenDevice;
}

const downloadTotals = new Map();

function modelProgress(p) {
  if (p.status === 'progress' && p.total) {
    downloadTotals.set(p.file, { loaded: p.loaded, total: p.total });
    let loaded = 0, total = 0;
    for (const v of downloadTotals.values()) { loaded += v.loaded; total += v.total; }
    const pct = total ? Math.round(loaded / total * 100) : 0;
    setProgress('', Math.min(99, pct), 'Downloading model (once)…',
      `${(loaded / 1e6).toFixed(1)} / ${(total / 1e6).toFixed(1)} MB — cached by your browser`);
  } else if (p.status === 'initiate') {
    setProgress('', 0, 'Downloading model (once)…', p.file || '');
  } else if (p.status === 'done') {
    setProgress('', 99, 'Finishing model load…', '');
  }
}

async function loadTranscriber() {
  const modelId = document.getElementById('model-select').value;
  let device = await detectDevice();
  let key = modelId + '|' + device;
  if (transcriber && transcriberKey === key) return transcriber;

  if (!transformers) {
    setProgress('', 0, 'Starting AI engine…', '');
    transformers = await import(TRANSFORMERS_CDN);
    transformers.env.allowLocalModels = false;
    transformers.env.useBrowserCache = true;
  }

  const build = (dev) => transformers.pipeline('automatic-speech-recognition', modelId, {
    ...DEVICE_CONFIG[dev],
    progress_callback: modelProgress,
  });

  downloadTotals.clear();
  logMsg('', `Loading ${modelId} on ${device === 'webgpu' ? 'WebGPU' : 'CPU (WebAssembly)'}…`);

  try {
    transcriber = await build(device);
  } catch (err) {
    if (device !== 'webgpu') throw err;
    // Some GPUs/adapter limits reject the WebGPU build — CPU still works.
    logMsg('', `⚠ WebGPU unavailable (${err.message}). Falling back to CPU…`, 'log-warn');
    device = chosenDevice = 'wasm';
    transcriber = await build(device);
  }

  transcriberKey = modelId + '|' + device;
  return transcriber;
}

function startTicker() {
  stopTicker();
  tickStart = Date.now();
  ticker = setInterval(() => {
    const elapsed = (Date.now() - tickStart) / 1000;
    setProgress('', null, 'Transcribing on your device…',
      `Elapsed ${fmtClock(elapsed)} · keep this tab open`);
  }, 1000);
}

function stopTicker() {
  if (ticker) { clearInterval(ticker); ticker = null; }
}

// ─────────────────────────────────────────────────────────────────────────────
// 1. ON-DEVICE TRANSCRIPTION
// ─────────────────────────────────────────────────────────────────────────────
async function startBrowserTranscription() {
  const file = files.browser;
  if (!file) { alert('Please select a video or audio file first.'); return; }

  stopSignal = false;
  setBusy('', true);
  showProgress('');
  clearLog('');
  document.getElementById('log-box').classList.add('show');

  try {
    setProgress('', 3, 'Reading audio…', 'Decoding locally — nothing is uploaded');
    const audio = await decodeAudio(file);
    if (!audio.length) throw new Error('That file contains no audio track.');
    const duration = audio.length / SAMPLE_RATE;
    logMsg('', `✔ Audio decoded: ${fmtClock(duration)}`, 'log-ok');
    if (stopSignal) throw new Error('Stopped by user.');

    const pipe = await loadTranscriber();
    if (stopSignal) throw new Error('Stopped by user.');

    startTicker();
    const lang = document.getElementById('src-lang-select').value;

    const result = await pipe(audio, {
      return_timestamps: true,
      chunk_length_s: 30,
      stride_length_s: 5,
      task: 'transcribe',
      language: lang && lang !== 'auto' ? lang : undefined,
      // Throwing here aborts generation almost immediately when Stop is hit.
      callback_function: () => { if (stopSignal) throw new Error('Stopped by user.'); },
    });

    stopTicker();
    if (stopSignal) throw new Error('Stopped by user.');

    const segments = buildSegments(result, duration);
    if (!segments.length) throw new Error('No speech detected in that file.');

    setProgress('', 96, 'Building subtitles…', '');
    const srt = segmentsToSRT(segments);

    setProgress('', 100, '✅ Done!', segments.length + ' subtitle lines generated');
    logMsg('', `✔ ${segments.length} subtitle lines generated — 100% on your device.`, 'log-ok');
    showResults(srt);

  } catch (err) {
    stopTicker();
    if (err.message === 'Stopped by user.') {
      logMsg('', '⏹ Stopped.', 'log-warn');
      setProgress('', 0, 'Stopped.', '');
    } else {
      logMsg('', '✖ Error: ' + err.message, 'log-err');
      setProgress('', 0, '❌ Error — see log', '');
      console.error(err);
    }
  } finally {
    setBusy('', false);
  }
}

function stopTranscription() {
  if (stopSignal) return;
  stopSignal = true;
  logMsg('', '⏹ Stopping…', 'log-warn');
}

// ─────────────────────────────────────────────────────────────────────────────
// 2. CLOUD TRIAL — small clips through the .Vsub proxy (server applies quota)
// ─────────────────────────────────────────────────────────────────────────────
async function startCloudTranscription() {
  const file = files.cloud;
  if (!file) { alert('Please select a file.'); return; }

  if (file.size > CLOUD_MAX_MB * 1024 * 1024) {
    alert(
      `The free cloud trial accepts clips up to ${CLOUD_MAX_MB} MB (roughly 10 minutes).\n\n` +
      'For longer files use "On-device" (unlimited, no upload) or "Bring your own key".'
    );
    return;
  }

  setBusy('-cloud', true);
  showProgress('-cloud');
  clearLog('-cloud');
  document.getElementById('log-box-cloud').classList.add('show');
  cloudAbort = new AbortController();

  try {
    const lang = document.getElementById('src-lang-cloud').value;
    logMsg('-cloud', 'Uploading to .Vsub Cloud…');
    setProgress('-cloud', 10, 'Uploading…', `File: ${(file.size / 1e6).toFixed(1)} MB`);

    const form = new FormData();
    form.append('file', file, file.name);
    if (lang) form.append('language', lang);
    form.append('provider', 'groq');

    const resp = await fetch(VSUB_CLOUD_URL, {
      method: 'POST',
      body: form,
      signal: cloudAbort.signal,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || 'Server error ' + resp.status);
    }

    const remaining = resp.headers.get('X-Vsub-Free-Remaining');
    if (remaining !== null) {
      logMsg('-cloud', `Free cloud credits left today: ${remaining}`, 'log-ok');
    }

    setProgress('-cloud', 70, 'Transcribing in the cloud…', 'Groq Whisper Large V3 Turbo');
    const data = await resp.json();
    setProgress('-cloud', 90, 'Building SRT…', '');

    const segments = (data.segments || [])
      .map(s => ({ start: s.start, end: s.end, text: s.text }))
      .filter(s => s.text && s.text.trim());
    if (!segments.length && data.text && data.text.trim()) {
      segments.push({ start: 0, end: 0, text: data.text.trim() });
    }
    if (!segments.length) throw new Error('No speech detected in that file.');

    let srt = segmentsToSRT(segments);

    const transLang = document.getElementById('trans-lang-cloud').value;
    if (transLang) {
      setProgress('-cloud', 93, 'Translating…', '→ ' + transLang);
      srt = await translateSRTText(srt, transLang);
    }

    setProgress('-cloud', 100, '✅ Done!', segments.length + ' lines');
    logMsg('-cloud', `✔ ${segments.length} lines generated!`, 'log-ok');
    showResults(srt);

  } catch (err) {
    if (err.name === 'AbortError') {
      logMsg('-cloud', '⏹ Stopped.', 'log-warn');
      setProgress('-cloud', 0, 'Stopped.', '');
    } else {
      logMsg('-cloud', '✖ ' + err.message, 'log-err');
      setProgress('-cloud', 0, '❌ Error — see log', '');
    }
  } finally {
    setBusy('-cloud', false);
    cloudAbort = null;
  }
}

function stopCloudTranscription() {
  if (cloudAbort) cloudAbort.abort();
  setBusy('-cloud', false);
}

// ─────────────────────────────────────────────────────────────────────────────
// 3. BYOK — the user's own key, browser → Groq/OpenAI directly
// ─────────────────────────────────────────────────────────────────────────────
const BYOK_STORAGE = 'vsub_byok_key';

function saveBYOK() {
  const key = document.getElementById('byok-key').value.trim();
  if (!key) { alert('Please enter your API key.'); return; }
  localStorage.setItem(BYOK_STORAGE, key);
  alert('✅ Key saved in this browser only (localStorage).');
}

function clearBYOK() {
  localStorage.removeItem(BYOK_STORAGE);
  document.getElementById('byok-key').value = '';
}

async function startBYOKTranscription() {
  const file = files.byok;
  const key = document.getElementById('byok-key').value.trim() || localStorage.getItem(BYOK_STORAGE) || '';
  if (!key) { alert('Please enter and save your API key first.'); return; }
  if (!file) { alert('Please select a file.'); return; }

  const provider = document.getElementById('byok-provider').value;
  const lang = document.getElementById('src-lang-byok').value;
  const url = provider === 'groq' ? GROQ_API_URL : OPENAI_API_URL;
  const model = provider === 'groq' ? 'whisper-large-v3-turbo' : 'whisper-1';

  if (file.size > 100 * 1024 * 1024) {
    alert('That file is over 100 MB. Split it, or use On-device mode.');
    return;
  }

  setBusy('-byok', true);
  showProgress('-byok');
  clearLog('-byok');
  document.getElementById('log-box-byok').classList.add('show');
  logMsg('-byok', 'Sending directly to ' + provider + '…');
  setProgress('-byok', 10, 'Uploading to ' + provider + '…', 'Your key never touches our server');

  try {
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('model', model);
    form.append('response_format', 'verbose_json');
    if (lang) form.append('language', lang);

    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + key },
      body: form,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      let msg = err?.error?.message || 'API error ' + resp.status;
      if (resp.status === 401) msg = 'That API key was rejected. Check it and try again.';
      if (resp.status === 429) msg = 'Your ' + provider + ' quota is exhausted. Wait a minute or check your plan.';
      throw new Error(msg);
    }

    setProgress('-byok', 80, 'Processing response…', '');
    const data = await resp.json();
    const segs = (data.segments || [])
      .map(s => ({ start: s.start, end: s.end, text: s.text }))
      .filter(s => s.text && s.text.trim());
    if (!segs.length && data.text && data.text.trim()) {
      segs.push({ start: 0, end: 0, text: data.text.trim() });
    }
    if (!segs.length) throw new Error('No speech detected in that file.');

    const srt = segmentsToSRT(segs);
    setProgress('-byok', 100, '✅ Done!', segs.length + ' lines');
    logMsg('-byok', `✔ ${segs.length} lines from ${provider}`, 'log-ok');
    showResults(srt);

  } catch (err) {
    logMsg('-byok', '✖ ' + err.message, 'log-err');
    setProgress('-byok', 0, '❌ Error — see log', '');
    if (err instanceof TypeError) {
      logMsg('-byok', 'Network/CORS error — the provider may be blocking browser calls. On-device mode works without a key.', 'log-warn');
    }
  } finally {
    setBusy('-byok', false);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// TRANSLATION — Google Translate (free, unofficial — same as desktop app)
// ─────────────────────────────────────────────────────────────────────────────
async function translateSRTText(srtText, targetLang) {
  const lines = srtText.split('\n');
  const textLines = [];

  lines.forEach((line, i) => {
    const trimmed = line.trim();
    if (trimmed && !/^\d+$/.test(trimmed) && !trimmed.includes('-->')) {
      textLines.push({ i, text: trimmed });
    }
  });

  if (!textLines.length) return srtText;

  const BATCH = 80;
  for (let off = 0; off < textLines.length; off += BATCH) {
    const batch = textLines.slice(off, off + BATCH);
    const params = new URLSearchParams({ sl: 'auto', tl: targetLang, client: 'gtx' });
    batch.forEach(b => params.append('q', b.text));

    const resp = await fetch(GT_URL + '?' + params.toString());
    if (!resp.ok) break;
    const data = await resp.json();

    const results = Array.isArray(data)
      ? data.map(item => Array.isArray(item) ? item[0] : String(item))
      : [String(data)];

    results.forEach((translated, j) => {
      if (batch[j]) lines[batch[j].i] = translated;
    });
  }

  return lines.join('\n');
}

async function translateSRT(evt) {
  const lang = document.getElementById('translate-to').value;
  if (!lang || !generatedSRT) return;
  const btn = (evt && evt.currentTarget) || document.getElementById('btn-translate');
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = '🌐 Translating…';

  try {
    const translated = await translateSRTText(generatedSRT, lang);
    generatedSRT = translated;
    generatedVTT = srtToVTT(translated);
    document.getElementById('srt-preview').textContent =
      translated.slice(0, 3000) + (translated.length > 3000 ? '\n…' : '');
    btn.textContent = '✅ Translated!';
    setTimeout(() => { btn.textContent = '🌐 Translate'; btn.disabled = false; }, 2000);
  } catch {
    btn.textContent = '❌ Failed';
    setTimeout(() => { btn.textContent = '🌐 Translate'; btn.disabled = false; }, 2000);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// DOWNLOAD HELPERS
// ─────────────────────────────────────────────────────────────────────────────
function downloadFile(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 3000);
}

function downloadSRT() {
  if (!generatedSRT) return;
  downloadFile(generatedSRT, 'subtitles.srt', 'text/srt;charset=utf-8');
}

function downloadVTT() {
  if (!generatedVTT) return;
  downloadFile(generatedVTT, 'subtitles.vtt', 'text/vtt;charset=utf-8');
}

function copyToClipboard() {
  navigator.clipboard?.writeText(generatedSRT)
    .then(() => { alert('Copied to clipboard!'); })
    .catch(() => alert('Copy failed — try selecting text manually.'));
}

// ─────────────────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────────────────
(async function initDeviceBadge() {
  const badge = document.getElementById('device-badge');
  if (!badge) return;
  const device = await detectDevice();
  badge.textContent = device === 'webgpu' ? '⚡ WebGPU ready' : '🖥️ CPU (WebAssembly)';
})();

const savedKey = localStorage.getItem(BYOK_STORAGE);
if (savedKey) {
  const el = document.getElementById('byok-key');
  if (el) el.value = savedKey;
}

// Particle effect (reuse from main script.js)
const pc = document.getElementById('particles');
if (pc && !pc.children.length) {
  for (let i = 0; i < 15; i++) {
    const p = document.createElement('div');
    p.className = 'particle';
    p.style.left = Math.random() * 100 + '%';
    p.style.top = (Math.random() * 100 + 100) + '%';
    p.style.animationDuration = (8 + Math.random() * 15) + 's';
    p.style.animationDelay = (Math.random() * 10) + 's';
    pc.appendChild(p);
  }
}
