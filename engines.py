import re
import time
import hashlib
import json
import threading
import requests
import subprocess
import os
import concurrent.futures
from deep_translator import GoogleTranslator
from utils import parse_srt, get_ffmpeg_path
import ust_settings as config

# ============================================================
# SESSION ABORT  —  close all active HTTP sessions to cancel in-flight requests
# ============================================================
_session_lock    = threading.Lock()
_active_sessions: list = []

def _new_session():
    """Create a requests.Session and register it so abort_all_sessions() can close it."""
    s = requests.Session()
    with _session_lock:
        _active_sessions.append(s)
    return s

def _release_session(s):
    """Unregister and close a session when the request is done."""
    with _session_lock:
        try:
            _active_sessions.remove(s)
        except ValueError:
            pass
    try:
        s.close()
    except Exception:
        pass

def abort_all_sessions():
    """
    Close every active HTTP session immediately.
    This interrupts in-flight requests.post() / requests.get() calls
    with a ConnectionError, unblocking any waiting threads instantly.
    """
    with _session_lock:
        sessions = list(_active_sessions)
        _active_sessions.clear()
    for s in sessions:
        try:
            s.close()
        except Exception:
            pass

# ============================================================
# AUDIO CACHE  —  skip re-compression if video unchanged
# ============================================================

def _video_hash(video_path):
    """Fast hash: mtime + size (no full read needed)."""
    try:
        st = os.stat(video_path)
        raw = f"{video_path}|{st.st_mtime}|{st.st_size}"
        return hashlib.md5(raw.encode()).hexdigest()
    except Exception:
        return None

def _cache_meta_path(temp_dir):
    return os.path.join(temp_dir, "_cache_meta.json")

def chunks_are_cached(video_path, segment_time, temp_dir):
    """Return True when cached chunks for this exact video+settings exist."""
    meta_path = _cache_meta_path(temp_dir)
    if not os.path.exists(meta_path):
        return False
    try:
        with open(meta_path, "r") as f:
            meta = json.load(f)
        if (meta.get("hash") != _video_hash(video_path) or
                meta.get("segment_time") != segment_time):
            return False
        # At least one chunk must be present
        chunks = sorted([fn for fn in os.listdir(temp_dir) if fn.endswith(".m4a")
                         and not fn.startswith("_")])
        return bool(chunks)
    except Exception:
        return False

def save_cache_meta(video_path, segment_time, temp_dir):
    meta = {"hash": _video_hash(video_path), "segment_time": segment_time}
    try:
        with open(_cache_meta_path(temp_dir), "w") as f:
            json.dump(meta, f)
    except Exception:
        pass

def clear_cache(temp_dir):
    """Remove all chunk files and cache meta."""
    if not os.path.exists(temp_dir):
        return
    for fn in os.listdir(temp_dir):
        try:
            os.remove(os.path.join(temp_dir, fn))
        except Exception:
            pass

# ============================================================
# API TRANSCRIPTION (Groq / OpenAI / Custom)
# ============================================================

# Sound-event tags that Whisper may output — keep them as subtitle events
SOUND_EVENT_RE = re.compile(r'^\[.+?\]$')

def transcribe_audio_chunk(chunk_path, provider, api_key, source_lang=None,
                           custom_url=None, prompt=None, stop_check=None):
    if "Groq" in provider:
        url   = "https://api.groq.com/openai/v1/audio/transcriptions"
        model = "whisper-large-v3"
    elif "OpenAI" in provider:
        url   = "https://api.openai.com/v1/audio/transcriptions"
        model = "whisper-1"
    else:
        url   = custom_url if custom_url else "https://api.openai.com/v1/audio/transcriptions"
        model = "whisper-1"

    data = {"model": model, "response_format": "verbose_json"}
    if source_lang:
        data["language"] = source_lang
    if prompt and prompt.strip():
        data["prompt"] = prompt.strip()

    max_retries = 4
    for attempt in range(max_retries):
        # ── Stop check at the top of every retry attempt ─────────────────
        if stop_check and stop_check():
            raise Exception("⏹ Stopped by user.")

        sess = _new_session()
        try:
            with open(chunk_path, "rb") as f:
                response = sess.post(
                    url, headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (os.path.basename(chunk_path), f, "audio/mp4")},
                    data=data, timeout=180          # 3 min — enough for large chunks
                )
        except requests.exceptions.ConnectionError:
            # Session was closed by abort_all_sessions() — treat as stop signal
            if stop_check and stop_check():
                raise Exception("⏹ Stopped by user.")
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise Exception("Network connection error. Check your internet connection or URL.")
        except requests.exceptions.Timeout:
            if stop_check and stop_check():
                raise Exception("⏹ Stopped by user.")
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise Exception(f"{provider} API timed out after multiple attempts.")
        finally:
            _release_session(sess)

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            wait_time = min(30, (2 ** attempt) * 5)
            if attempt < max_retries - 1:
                time.sleep(wait_time)
                continue
            raise Exception(
                f"{provider} API Rate Limit: You've hit the usage quota.\n\n"
                "💡 Solutions:\n"
                "• Wait a few minutes and try again\n"
                "• Check your API provider plan & billing"
            )
        elif response.status_code == 401:
            # Distinguish cloud mode (empty key) from user key error
            if not api_key:
                body = ""
                try: body = response.json().get("detail", "")
                except Exception: pass
                raise Exception(
                    "🌐 .Vsub Cloud Server Error: Groq API key on the server is invalid or missing.\n\n"
                    "Fix this in your Render dashboard:\n"
                    "  1. Go to render.com → your vsub-cloud service\n"
                    "  2. Click Environment → edit VSUB_GROQ_KEYS\n"
                    "  3. Paste a valid key from console.groq.com\n"
                    "  4. Click Save Changes → server restarts automatically\n\n"
                    f"Server detail: {body}" if body else
                    "  4. Click Save Changes → server restarts automatically"
                )
            raise Exception(f"{provider} API Error: Invalid API Key. Please verify your credentials.")
        else:
            raise Exception(f"API Error {response.status_code}:\n{response.text[:400]}")

    raise Exception(f"Failed to transcribe after {max_retries} attempts.")

# ============================================================
# TRANSLATION  —  batch-first, fast, pure target language
# ============================================================

# ============================================================
# TRANSLATION  —  direct Google Translate API (true batch, instant)
# ============================================================

# Language code normalization for the direct API
_LANG_REMAP_DIRECT = {
    "chinese (simplified)":  "zh-CN",
    "chinese (traditional)": "zh-TW",
    "javanese":  "jv",
    "cebuano":   "ceb",
    "zh-CN":     "zh-CN",
    "zh-TW":     "zh-TW",
}

_SOUND_RE = re.compile(r'^\[.+?\]$')

# ── Batch limits for the direct Google endpoint ───────────────────────────
# translate.googleapis.com/translate_a/t accepts many q= params in one call.
# Safe limits: ~128 texts OR ~12 000 chars per request.
_MAX_BATCH_LINES = 100
_MAX_BATCH_CHARS = 10000

# ─────────────────────────────────────────────────────────────────────────────
# FAST PATH: direct Google Translate endpoint — ONE HTTP call for ALL texts
# ─────────────────────────────────────────────────────────────────────────────
def _gt_batch_direct(texts, target_code):
    """
    True single-request batch translation via the internal Google Translate API.
    Sends all `texts` as separate `q=` parameters in ONE GET request.
    ~10x faster than individual calls.

    Returns a list of translated strings the same length as `texts`.
    Raises on HTTP error so caller can fall back to deep_translator.
    """
    url    = "https://translate.googleapis.com/translate_a/t"
    # Build param list manually: multiple q= values
    params = [("sl", "auto"), ("tl", target_code), ("client", "gtx")]
    for t in texts:
        params.append(("q", t))

    sess = _new_session()
    try:
        resp = sess.get(url, params=params, timeout=30)
    finally:
        _release_session(sess)

    if resp.status_code != 200:
        raise Exception(f"Google API returned {resp.status_code}")

    data = resp.json()
    # Response format varies:
    #   Single text:  "translated string"
    #   Multi text:   ["t1", "t2", ...]  OR  [["t1"], ["t2"], ...]
    if isinstance(data, str):
        return [data]
    if not isinstance(data, list):
        raise Exception("Unexpected response format")

    results = []
    for item in data:
        if isinstance(item, list):
            results.append(item[0] if item else "")
        else:
            results.append(str(item) if item else "")

    if len(results) != len(texts):
        raise Exception(f"Length mismatch: got {len(results)}, expected {len(texts)}")

    return results


def _gt_batch_fallback(texts, target_code):
    """
    Fallback: deep_translator (runs N parallel individual calls).
    Used only when the direct API fails.
    """
    from deep_translator import GoogleTranslator
    tgt = target_code
    # deep_translator uses different names for some codes
    _remap = {"zh-CN": "chinese (simplified)", "zh-TW": "chinese (traditional)",
              "jv": "javanese", "ceb": "cebuano"}
    tgt = _remap.get(target_code, target_code)
    try:
        results = GoogleTranslator(source="auto", target=tgt).translate_batch(texts)
        return [r or t for r, t in zip(results, texts)]
    except Exception:
        return texts   # last resort: originals


def _gt_batch(texts, target_code):
    """
    Translate a batch of texts. Tries the fast direct API first,
    falls back to deep_translator if it fails.
    """
    try:
        return _gt_batch_direct(texts, target_code)
    except Exception:
        return _gt_batch_fallback(texts, target_code)


def _romanize_batch(texts, target_code):
    """
    Romanize multiple texts via Google unofficial API (joined by newline).
    Single HTTP call; splits result back by newline.
    """
    joined = "\n".join(texts)
    url    = "https://translate.googleapis.com/translate_a/single"
    params = {"client": "gtx", "sl": "auto", "tl": target_code,
              "dt": ["t", "rm"], "q": joined}
    sess = _new_session()
    try:
        resp = sess.get(url, params=params, timeout=20)
    finally:
        _release_session(sess)
    if resp.status_code != 200:
        return texts
    data = resp.json()
    romanized = "".join(p[2] for p in data[0] if len(p) > 2 and p[2])
    normal    = "".join(p[0] for p in data[0] if p[0])
    combined  = (romanized or normal).strip()
    parts     = combined.split("\n")
    if len(parts) == len(texts):
        return [p.strip() for p in parts]
    return texts   # length mismatch — keep originals


def _translate_one(text, target_code, romanize):
    """Single-line fallback for individual retries."""
    if not text.strip():
        return text
    for attempt in range(3):
        try:
            if romanize:
                return _romanize_batch([text], target_code)[0]
            else:
                return _gt_batch([text], target_code)[0]
        except Exception:
            time.sleep(min(8, (2 ** attempt) * 1.5))
    return text


def _make_batches(indices, texts):
    """
    Group (index, text) pairs into batches that fit within Google's limits.
    Returns list of (batch_indices, batch_texts).
    """
    batches, cur_idxs, cur_texts, cur_chars = [], [], [], 0
    for idx, text in zip(indices, texts):
        char_len = len(text) + 1   # +1 for join separator
        if cur_texts and (cur_chars + char_len > _MAX_BATCH_CHARS
                          or len(cur_texts) >= _MAX_BATCH_LINES):
            batches.append((cur_idxs, cur_texts))
            cur_idxs, cur_texts, cur_chars = [], [], 0
        cur_idxs.append(idx)
        cur_texts.append(text)
        cur_chars += char_len
    if cur_texts:
        batches.append((cur_idxs, cur_texts))
    return batches


def translate_batch(segments, target_code, romanize=False,
                    batch_size=None, progress_callback=None,
                    source_code=None, stop_check=None):
    """
    Translate all subtitle segments into target_code using BATCH requests.

    Strategy:
      • Groups up to 40 lines / 4500 chars per Google Translate call
      • Parallel batches via ThreadPoolExecutor
      • Sound events [like this] are skipped (kept as-is)
      • Falls back to individual translation if a batch fails

    source_code : if provided and equals target_code, skip entirely.
    stop_check  : callable() → bool; workers bail when True.
    """
    if source_code and target_code and source_code == target_code:
        return segments

    import concurrent.futures as _cf

    total = len(segments)
    done  = [0]

    # ── Separate sound events (skip) from translatable lines ─────────────
    to_translate_idxs  = []
    to_translate_texts = []
    for i, seg in enumerate(segments):
        t = seg["text"].strip()
        if t and not _SOUND_RE.match(t):
            to_translate_idxs.append(i)
            to_translate_texts.append(t)

    if not to_translate_idxs:
        return segments

    # ── Build batches ─────────────────────────────────────────────────────
    batches = _make_batches(to_translate_idxs, to_translate_texts)
    n_batches = len(batches)
    batches_done = [0]

    def _translate_batch_job(batch_idxs, batch_texts):
        """Translate one batch; returns (batch_idxs, translated_texts)."""
        if stop_check and stop_check():
            return batch_idxs, batch_texts   # keep originals on stop
        max_retries = 3
        for attempt in range(max_retries):
            if stop_check and stop_check():
                return batch_idxs, batch_texts
            try:
                if romanize:
                    results = _romanize_batch(batch_texts, target_code)
                else:
                    results = _gt_batch(batch_texts, target_code)
                # Validate — length must match
                if len(results) == len(batch_texts):
                    return batch_idxs, results
                # Mismatch: fall back to individual
                break
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(min(8, (2 ** attempt) * 2))
        # Fallback: translate individually
        results = []
        for text in batch_texts:
            if stop_check and stop_check():
                results.append(text)
            else:
                results.append(_translate_one(text, target_code, romanize))
        return batch_idxs, results

    # ── Run batches in parallel ───────────────────────────────────────────
    max_w    = min(config.MAX_TRANSLATION_WORKERS, n_batches)
    executor = _cf.ThreadPoolExecutor(max_workers=max_w)
    try:
        future_map = {
            executor.submit(_translate_batch_job, bi, bt): (bi, bt)
            for bi, bt in batches
        }
        for future in _cf.as_completed(future_map):
            idxs, translated = future.result()
            for seg_idx, text in zip(idxs, translated):
                segments[seg_idx]["text"] = text
            batches_done[0] += 1
            done[0] += len(idxs)
            if progress_callback:
                try:
                    progress_callback(done[0], total)
                except Exception:
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    return segments


def translate_text(text, target_code, romanize=False):
    """Translate a single free-form text string."""
    if target_code == "en" or not text.strip():
        return text
    try:
        return _translate_one(text, target_code, romanize)
    except Exception:
        return text


# ============================================================
# SYNC DETECTION
# ============================================================

def detect_sync_offset(video_path, srt_path, status_callback=None):
    segments = parse_srt(srt_path)
    if not segments: return None, "No subtitles found in file."

    first_sub_time = segments[0]['start']
    if status_callback:
        status_callback("Analyzing audio for auto-sync (may take ~30s)...")

    try:
        cf  = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        ffmpeg_path = get_ffmpeg_path()
        
        cmd = [
            ffmpeg_path, "-i", video_path, "-t", "300",
            "-af", "silencedetect=noise=-35dB:d=0.3", "-f", "null", "-"
        ]
        
        try:
            result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                                    creationflags=cf, timeout=120)
        except FileNotFoundError:
            return None, "ffmpeg.exe is missing! Please make sure it is properly bundled with the application."
            
        stderr = result.stderr.decode('utf-8', errors='ignore')

        silence_ends = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', stderr)]
        first_speech = silence_ends[0] if silence_ends else 0.0

        offset = round(first_speech - first_sub_time, 2)
        info   = (f"First speech at {first_speech:.2f}s  |  "
                  f"First subtitle at {first_sub_time:.2f}s  |  "
                  f"Suggested offset: {offset:+.2f}s")
        return offset, info
    except subprocess.TimeoutExpired:
        return None, "Audio analysis timed out."
    except Exception as e:
        return None, f"Auto-detect failed: {e}"


# ============================================================
# ONLINE SUBTITLE FETCHING
# ============================================================

def fetch_online_subtitle(video_path, target_lang="en", status_callback=None):
    try:
        from subliminal import download_best_subtitles, region, scan_video
        from babelfish import Language
    except ImportError:
        raise Exception("Subliminal is not installed. Run 'pip install subliminal'")
        
    if status_callback: status_callback("Scanning video hash...")
    
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "universalsubtitles", "subliminal")
    os.makedirs(cache_dir, exist_ok=True)
    try:
        region.configure('dogpile.cache.dbm', arguments={'filename': os.path.join(cache_dir, 'cache.dbm')})
    except Exception:
        pass  
    
    video = scan_video(video_path)
    if not video:
        raise Exception("Could not parse video metadata for hash.")
        
    if status_callback: status_callback(f"Searching for '{target_lang}' subtitles online...")
    
    try:
        lang = Language.fromalpha2(target_lang)
    except Exception:
        try:
            lang = Language(target_lang)
        except Exception:
            lang = Language('eng')  
    
    langs = {lang}
    subtitles = download_best_subtitles([video], langs)
    
    if video in subtitles and subtitles[video]:
        best_sub = subtitles[video][0]
        if status_callback: status_callback("Saving subtitle...")
        
        base = os.path.splitext(os.path.basename(video_path))[0]
        out_path = os.path.join(config.SUB_DIR, f"{base}_{target_lang}_online.srt")
        
        content = best_sub.content
        if content:
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='replace')
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(content)
            if status_callback: status_callback(f"✅ Subtitle downloaded instantly!")
            return out_path
        
        from subliminal.core import save_subtitles
        save_subtitles(video, [best_sub], single=True, directory=config.SUB_DIR, encoding='utf-8')
        
        video_base = os.path.splitext(os.path.basename(video.name))[0]
        for candidate in [
            os.path.join(config.SUB_DIR, f"{video_base}.srt"),
            os.path.join(config.SUB_DIR, f"{video_base}.{target_lang}.srt"),
        ]:
            if os.path.exists(candidate):
                import shutil
                shutil.move(candidate, out_path)
                if status_callback: status_callback(f"✅ Subtitle downloaded instantly!")
                return out_path
        return None
    else:
        raise Exception(f"No '{target_lang}' subtitle found online for this video.\nTip: Subtitles are matched by file hash — try a well-known movie or TV show.")