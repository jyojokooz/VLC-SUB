import os
import warnings
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()

warnings.simplefilter("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import threading
import subprocess
import sys
import re

import ust_settings as config
from utils import clean_path, format_timestamp, parse_srt, get_available_subtitles, detect_paired_file, generate_ass_content, resource_path, get_ffmpeg_path

# Cleaned up imports (Removed offline references)
from engines import transcribe_audio_chunk, translate_batch, detect_sync_offset
from vlc_integration import launch_vlc_preview, apply_subtitle_to_vlc, install_vlc_extension, remove_vlc_extension, get_vlc_ext_path
from ui_windows import show_srt_preview, show_style_preview, open_history
from security import save_api_key, load_api_key
from embed_subtitles import burn_subtitles_into_video

# PIL for thumbnail display (optional — graceful fallback if not installed)
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

_thumb_img_ref = None  # Prevent garbage collection of the thumbnail PhotoImage

# ── Widget globals — set in __main__, used by helper functions ──────────────
app            = None
progress_bar   = None
progress_label = None
progress_var   = None
stage_label    = None
status_label   = None

# ============================================================
# THREAD-SAFE UI QUEUE
# ============================================================
# Tkinter widgets must ONLY be touched from the main thread.
# Background threads post callables here; _pump_ui() drains them every 30ms.
import queue as _queue
_ui_queue = _queue.Queue()

def _ui(fn):
    """Post a UI update from ANY thread — safely executed on the main thread."""
    _ui_queue.put(fn)

def _pump_ui():
    """Main-thread pump: drain the UI queue and reschedule itself."""
    try:
        while True:
            fn = _ui_queue.get_nowait()
            try:
                fn()
            except Exception:
                pass
    except _queue.Empty:
        pass
    if app:
        app.after(30, _pump_ui)   # reschedule

# ============================================================
# HELPER / CALLBACKS
# ============================================================

# ── Global busy-lock: prevents double-clicks across all operations ─────────
_busy           = False
_busy_animation_id = None
_stop_event     = None          # threading.Event — set to cancel current task
_task_id        = 0             # increments each time a new operation starts

def _all_action_buttons():
    """Return every action button that should be locked while busy."""
    try:
        return [gen_btn, fast_dl_btn, trans_btn, auto_sync_btn, sync_btn,
                export_ass_btn, burn_btn]
    except NameError:
        return []

def _apply_busy(flag, stage_text=""):
    """Runs on the MAIN THREAD — directly updates all widgets for busy state."""
    global _busy, _stop_event, _task_id
    for btn in _all_action_buttons():
        try:
            btn.config(state=tk.DISABLED if flag else tk.NORMAL)
        except Exception:
            pass
    try:
        if flag:
            stop_btn.config(text="⏹ Stop", state=tk.NORMAL)
            stop_btn.pack(side=tk.LEFT, padx=(8, 0), ipadx=6, ipady=4)
        else:
            stop_btn.pack_forget()
    except Exception:
        pass
    if flag:
        try: stage_label.config(text=stage_text, fg=config.VLC_ORANGE)
        except: pass
        try: progress_var.set(0)
        except: pass
        try: progress_label.config(text="")
        except: pass
    else:
        try: stage_label.config(text="", fg="#555")
        except: pass

def set_busy(flag, stage_text=""):
    """
    Called from ANY thread. Updates _busy/_stop_event/_task_id immediately
    (thread-safe primitives), then posts widget updates to the UI queue.
    """
    global _busy, _stop_event, _task_id
    _busy = flag
    if flag:
        _task_id += 1
        _stop_event = threading.Event()
    else:
        _stop_event = None
    _ui(lambda: _apply_busy(flag, stage_text))

def _force_stop_ui():
    """Runs on MAIN THREAD — immediately reset UI to idle (called by Stop button)."""
    global _busy, _stop_event
    _busy = False
    _stop_event = None
    for btn in _all_action_buttons():
        try: btn.config(state=tk.NORMAL)
        except: pass
    try:
        stop_btn.pack_forget()
        stop_btn.config(text="⏹ Stop", state=tk.NORMAL)
    except: pass
    try:
        progress_bar.stop()
        progress_bar.config(mode="determinate", style="Orange.Horizontal.TProgressbar")
    except: pass
    try:
        progress_var.set(0)
        progress_label.config(text="")
        stage_label.config(text="⏹ Stopped", fg="#888")
        status_label.config(text="Status: ⏹ Stopped — ready for new operation.")
    except: pass

def _request_stop():
    """Called on MAIN THREAD when user clicks ⏹ Stop."""
    global _stop_event
    if _stop_event:
        _stop_event.set()
    try:
        from engines import abort_all_sessions
        abort_all_sessions()
    except Exception:
        pass
    _force_stop_ui()   # already on main thread — call directly

def is_stopped():
    """Returns True if a stop has been requested — tasks should check this."""
    return _stop_event is not None and _stop_event.is_set()

def _safe_unbusy(my_task_id):
    """
    Called from a background thread's finally block.
    Only resets the UI if no newer operation has started.
    """
    if _task_id == my_task_id:
        _ui(lambda: _apply_busy(False))

# ── Progress helpers — safe from any thread via _ui() ───────────────────────
def update_status(text):
    _ui(lambda: status_label.config(text=f"Status: {text}") if status_label else None)

def update_progress(done, total, label=""):
    pct = int((done / total) * 100) if total > 0 else 0
    lbl = f"  {done}/{total} {label}  ({pct}%)" if label else f"{pct}%"
    def _do():
        try: progress_var.set(pct)
        except: pass
        try: progress_label.config(text=lbl)
        except: pass
    _ui(_do)

def set_progress_indeterminate(on=True):
    """Switch progress bar between determinate and indeterminate (pulse) mode."""
    def _do():
        try:
            if on:
                progress_bar.config(mode="indeterminate",
                                    style="Indeterminate.Horizontal.TProgressbar")
                progress_bar.start(12)
                progress_label.config(text="  Please wait…")
            else:
                progress_bar.stop()
                progress_bar.config(mode="determinate",
                                    style="Orange.Horizontal.TProgressbar")
        except Exception:
            pass
    _ui(_do)

def populate_all_tabs(srt_path):
    _ui(lambda: trans_srt_var.set(srt_path))
    _ui(lambda: sync_srt_var.set(srt_path))
    _ui(lambda: custom_srt_var.set(srt_path))

# ── Validation helpers ──────────────────────────────────────────────────────
def _require(condition, title, message):
    """Show error dialog and return False if condition is not met."""
    if not condition:
        messagebox.showerror(title, message)
        return False
    return True

def _warn_busy():
    # With the Stop button available, just silently block (button is already disabled)
    return _busy


# ============================================================
# SUBTITLE CLEANING HELPERS
# ============================================================
def _script_name(ch):
    """Return the Unicode block/script name for character ch (for mixed-script detection)."""
    import unicodedata
    try:
        name = unicodedata.name(ch, "")
    except Exception:
        return "UNKNOWN"
    # Map Unicode names to broad script categories
    if name.startswith("TAMIL"):            return "TAMIL"
    if name.startswith("MALAYALAM"):        return "MALAYALAM"
    if name.startswith("DEVANAGARI"):       return "DEVANAGARI"
    if name.startswith("TELUGU"):           return "TELUGU"
    if name.startswith("KANNADA"):          return "KANNADA"
    if name.startswith("GUJARATI"):         return "GUJARATI"
    if name.startswith("GURMUKHI"):         return "GURMUKHI"
    if name.startswith("BENGALI"):          return "BENGALI"
    if name.startswith("ORIYA"):            return "ORIYA"
    if name.startswith("SINHALA"):          return "SINHALA"
    if name.startswith("CYRILLIC"):         return "CYRILLIC"
    if name.startswith("ARABIC"):           return "ARABIC"
    if name.startswith("HEBREW"):           return "HEBREW"
    if name.startswith("THAI"):             return "THAI"
    if name.startswith("LATIN"):            return "LATIN"
    if name.startswith("CJK") or name.startswith("HIRAGANA") or name.startswith("KATAKANA"):
        return "CJK"
    return "OTHER"


# Scripts that are considered "clean" mixed content (common in subtitles)
_ALLOWED_SCRIPTS_ALWAYS = {"LATIN", "OTHER"}  # punctuation, digits, emoji etc.

def _is_script_char(ch):
    """True for alphabetic chars AND Unicode combining/modifier marks (e.g. Tamil vowel signs)."""
    import unicodedata as _ud
    return ch.isalpha() or _ud.category(ch) in ('Mc', 'Mn', 'Me')


def _dominant_script(text):
    """Return the most frequent non-Latin/non-punct script in `text`, or None."""
    from collections import Counter
    counts = Counter()
    for ch in text:
        if _is_script_char(ch):
            s = _script_name(ch)
            if s not in _ALLOWED_SCRIPTS_ALWAYS:
                counts[s] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _clean_mixed_script(text, source_lang_code=None):
    """
    Strip individual characters/tokens that belong to a *different* Unicode script
    from the dominant script of the line.

    Example: "ஸ்ரியார் Эங்க சென்று" → "ஸ்ரியார்  சென்று"
             "வmera மா"              → "வ மா"   (Latin 'm','e','r','a' removed)

    This catches Whisper hallucinations that mix Cyrillic/Latin letters into
    Tamil/Malayalam/Devanagari words without deleting entire words that are
    legitimately in another language (e.g. English words in a Tamil dialogue).
    """
    if not text:
        return text

    dominant = _dominant_script(text)
    if dominant is None:
        # Pure Latin / punctuation line — leave as-is
        return text

    # Count characters per script across the whole line (include combining marks)
    total_alpha = sum(1 for ch in text if _is_script_char(ch))
    if total_alpha == 0:
        return text

    dominant_count = sum(
        1 for ch in text if _is_script_char(ch) and _script_name(ch) == dominant
    )
    dominant_ratio = dominant_count / total_alpha

    # If the dominant script is <40% of alphabetics, the line is genuinely
    # multilingual (e.g. English-only dialogue in a Tamil film) — keep it.
    if dominant_ratio < 0.40:
        return text

    # Strip characters that belong to a foreign script IF they are isolated
    # (i.e. surrounded by dominant-script chars or whitespace).
    # We work at the word level: if a word's chars are mostly from the dominant
    # script but contain foreign intrusions, strip the foreign chars.
    cleaned_words = []
    for word in text.split():
        alpha_in_word = [ch for ch in word if _is_script_char(ch)]
        if not alpha_in_word:
            cleaned_words.append(word)
            continue

        word_scripts_set = set(_script_name(ch) for ch in alpha_in_word)
        # If this single word contains BOTH the dominant script AND a foreign script,
        # it's a fused hallucination (e.g. "வmera", "challengeனால") — strip foreign chars.
        # For this check, LATIN is treated as foreign when dominant is an Indic script.
        _indic = {"TAMIL","MALAYALAM","DEVANAGARI","TELUGU","KANNADA","GUJARATI",
                  "GURMUKHI","BENGALI","ORIYA","SINHALA"}
        if dominant in _indic:
            _safe_in_word = {dominant}  # only dominant is safe; Latin = foreign for fused check
        else:
            _safe_in_word = {dominant} | _ALLOWED_SCRIPTS_ALWAYS

        foreign_in_word = word_scripts_set - _safe_in_word - {"OTHER"}
        is_fused = bool(foreign_in_word) and dominant in word_scripts_set

        if is_fused:
            # Strip the foreign chars; keep dominant chars + non-script chars (punct etc.)
            # For the strip, only keep chars in _safe_in_word (excludes LATIN for Indic)
            # plus non-script chars (spaces, digits, punctuation are handled by split)
            stripped = "".join(
                ch for ch in word
                if not _is_script_char(ch) or _script_name(ch) in _safe_in_word
            )
            if stripped.strip():
                cleaned_words.append(stripped)
            # else: became empty (e.g. a fully-garbage fused token) — drop it
        else:
            word_dom = sum(1 for ch in alpha_in_word if _script_name(ch) == dominant)
            word_dom_ratio = word_dom / len(alpha_in_word)
            if word_dom_ratio >= 0.5:
                # Word is mostly dominant script (but uniform) — keep as-is
                cleaned_words.append(word)
            else:
                # Word is entirely in a foreign script — keep whole word
                # (genuine foreign-language dialogue, e.g. English in a Tamil film)
                cleaned_words.append(word)

    return " ".join(cleaned_words).strip()


def _clean_subtitle_text(text, max_phrase_repeat=3, source_lang_code=None):
    """
    Remove Whisper hallucination loops AND mixed-script garbage chars.
    Whisper sometimes outputs: 'X X X X X' or 'ABC. ABC. ABC.'
    Also strips isolated Cyrillic/Latin chars mixed into Indic script lines.
    """
    if not text:
        return text

    # 0. Strip mixed-script garbage first (char-level intrusions)
    text = _clean_mixed_script(text, source_lang_code)
    if not text:
        return text

    # 1. Collapse exact word-sequence loops (e.g. "it is it is it is" → "it is")
    words = text.split()
    if len(words) > 6:
        # Try window sizes from 2..8 words
        for window in range(2, min(9, len(words) // 2 + 1)):
            new_words = []
            i = 0
            while i < len(words):
                phrase = words[i:i + window]
                count = 1
                j = i + window
                while j + window <= len(words) and words[j:j + window] == phrase:
                    count += 1
                    j += window
                new_words.extend(phrase * min(count, max_phrase_repeat))
                i = j if count > max_phrase_repeat else i + 1
            if len(new_words) < len(words) * 0.7:
                text = " ".join(new_words)
                words = new_words
                break

    # 2. Collapse repeated sentence fragments split by punctuation
    parts = re.split(r'(?<=[.!?])\s+', text)
    if len(parts) > 1:
        seen, deduped = [], []
        for p in parts:
            norm = p.strip().lower()
            if norm not in seen:
                seen.append(norm)
                deduped.append(p.strip())
            elif deduped.count(p.strip()) < max_phrase_repeat:
                deduped.append(p.strip())
        text = " ".join(deduped)

    return text.strip()


def _split_long_subtitle(text, start, end, max_chars=80):
    """
    Split a subtitle segment whose text exceeds max_chars into evenly-timed pieces.
    Returns a list of segment dicts.
    """
    if len(text) <= max_chars:
        return [{"start": start, "end": end, "text": text}]

    # Try to split on sentence boundaries first, then on commas, then hard-wrap
    duration = end - start
    words = text.split()
    lines, current = [], []
    for word in words:
        current.append(word)
        if len(" ".join(current)) >= max_chars:
            # Back off one word if possible to stay under limit
            if len(current) > 1:
                lines.append(" ".join(current[:-1]))
                current = [current[-1]]
            else:
                lines.append(" ".join(current))
                current = []
    if current:
        lines.append(" ".join(current))

    if not lines:
        return [{"start": start, "end": end, "text": text}]

    seg_dur = duration / len(lines)
    result = []
    for idx, line in enumerate(lines):
        result.append({
            "start": start + idx * seg_dur,
            "end":   start + (idx + 1) * seg_dur,
            "text":  line
        })
    return result


# ============================================================
# WORKFLOW LOGIC
# ============================================================
def run_generation():
    if _warn_busy(): return

    video_path       = clean_path(gen_video_var.get().strip())
    target_lang      = gen_lang_var.get()
    api_key          = api_key_var.get().strip()
    provider         = provider_var.get()
    custom_url       = custom_url_var.get().strip()
    romanize         = gen_romanize_var.get()
    source_lang_name = gen_source_lang_var.get()
    source_lang_code = config.WHISPER_LANGUAGES.get(source_lang_name)

    # ── Validation ────────────────────────────────────────────────────────
    if not _require(video_path, "❌ No Video Selected",
                    "Please browse and select a video file first.\n\n"
                    "Supported formats: MP4, MKV, AVI, TS, MOV, WMV"):
        return
    if not _require(os.path.exists(video_path), "❌ File Not Found",
                    f"The selected video file does not exist:\n{video_path}\n\n"
                    "Please re-select the file."):
        return
    # ── .Vsub Cloud: proxy server holds the API keys — user needs nothing ──
    _using_cloud = ".Vsub Cloud" in provider
    if _using_cloud:
        # Redirect to the .Vsub backend proxy
        provider   = "Custom API (OpenAI Format)"
        custom_url = config.VSUB_CLOUD_URL
        api_key    = config.VSUB_CLOUD_TOKEN   # empty string = open server
    else:
        if not _require(api_key, "❌ API Key Missing",
                        "Please enter your API key.\n\n"
                        "• Groq (Free): Get a key at https://console.groq.com\n"
                        "• OpenAI: Get a key at https://platform.openai.com\n\n"
                        "Paste the key in the API Key field, then click 💾 Save."):
            return
        if "Custom" in provider and not _require(
                custom_url.startswith("http"), "❌ Invalid Custom URL",
                "Custom API URL must start with http:// or https://\n\n"
                "Example: https://api.openai.com/v1/audio/transcriptions"):
            return
        save_api_key(api_key)

    def _task():
        import concurrent.futures as _cf
        from engines import chunks_are_cached, save_cache_meta, clear_cache

        try:
            set_busy(True, "🎬 Stage 1 of 4 — Preparing Audio")
            _my_id = _task_id   # capture after set_busy increments it

            # ── Cloud preflight check ──────────────────────────────────────
            if _using_cloud:
                update_status("🌐 Checking .Vsub Cloud server…")
                import requests as _req
                _health_url = config.VSUB_CLOUD_URL.replace("/transcribe", "/health")
                try:
                    _hr = _req.get(_health_url, timeout=15)
                    if _hr.status_code == 200:
                        _hj = _hr.json()
                        _groq = _hj.get("pools", {}).get("groq", {})
                        if _groq.get("total", 0) == 0:
                            raise Exception(
                                "🌐 .Vsub Cloud: No Groq API keys configured on the server!\n\n"
                                "Fix:\n"
                                "  1. Go to render.com → your vsub-cloud service\n"
                                "  2. Environment → set VSUB_GROQ_KEYS = gsk_your_key_here\n"
                                "  3. Save Changes (server auto-restarts)"
                            )
                        update_status(
                            f"✅ Cloud ready — {_groq.get('available', 0)}/{_groq.get('total', 0)} keys available"
                        )
                    else:
                        raise Exception(
                            f"🌐 .Vsub Cloud server returned error {_hr.status_code}.\n\n"
                            "Check render.com logs for details."
                        )
                except _req.exceptions.ConnectionError:
                    raise Exception(
                        "🌐 Cannot reach .Vsub Cloud server.\n\n"
                        f"URL: {config.VSUB_CLOUD_URL}\n\n"
                        "• Check the URL in ⚙ Settings → .Vsub Cloud Server\n"
                        "• Make sure the service is running on render.com"
                    )
                except _req.exceptions.Timeout:
                    raise Exception(
                        "🌐 .Vsub Cloud server timed out (15s).\n\n"
                        "The server may be waking from sleep — wait 30 seconds and try again."
                    )
            # ── End preflight ──────────────────────────────────────────────
            os.makedirs(config.TEMP_DIR, exist_ok=True)

            segment_time = config.AUDIO_SEGMENT_TIME
            ffmpeg_path  = get_ffmpeg_path()
            cf_flag      = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

            # ── Stage 1: Audio compression ─────────────────────────────────
            if chunks_are_cached(video_path, segment_time, config.TEMP_DIR):
                update_status("⚡ Cached audio found — skipping compression")
                update_progress(100, 100, "cached")
            else:
                set_busy(True, "🎙 Stage 1 of 4 — Compressing Audio")
                clear_cache(config.TEMP_DIR)
                chunk_pattern = os.path.join(config.TEMP_DIR, "chunk_%03d.m4a")

                # ── Get video duration for progress display ─────────────────
                total_secs = 0
                try:
                    probe = subprocess.run(
                        [ffmpeg_path, "-i", video_path],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        creationflags=cf_flag, timeout=15
                    )
                    dm = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)',
                                   probe.stderr.decode("utf-8", errors="ignore"))
                    if dm:
                        total_secs = (int(dm.group(1)) * 3600 +
                                      int(dm.group(2)) * 60 + float(dm.group(3)))
                except Exception:
                    pass

                # ── Fast ffmpeg: NO loudnorm (single-pass, Whisper handles audio fine) ──
                # loudnorm requires 2 internal passes and doubles compression time.
                # Using -q:a 2 (VBR) instead of CBR for faster encoding.
                cmd = [ffmpeg_path, "-y", "-i", video_path,
                       "-vn", "-c:a", "aac", "-q:a", "2",
                       "-ar", "16000", "-ac", "1",
                       "-f", "segment", "-segment_time", str(segment_time),
                       chunk_pattern]

                try:
                    import time as _time
                    t_start = _time.time()
                    proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        creationflags=cf_flag
                    )

                    # ── Stream stderr for real-time time= progress ──────────
                    stderr_lines = []
                    for raw in proc.stderr:
                        if is_stopped():
                            proc.kill()
                            raise Exception("⏹ Stopped by user.")
                        line = raw.decode("utf-8", errors="ignore")
                        stderr_lines.append(line)

                        # Parse   time=HH:MM:SS.ms   from ffmpeg output
                        tm = re.search(r'time=(\d+):(\d+):([\d.]+)', line)
                        if tm:
                            done_s = (int(tm.group(1)) * 3600 +
                                      int(tm.group(2)) * 60 + float(tm.group(3)))
                            elapsed = _time.time() - t_start
                            if total_secs > 0:
                                pct = min(99, int(done_s / total_secs * 100))
                                eta = ""
                                if done_s > 2 and pct > 0:
                                    eta_s = int(elapsed / (done_s / total_secs) - elapsed)
                                    eta = f"  ETA {eta_s}s"
                                update_progress(pct, 100)
                                update_status(
                                    f"🎙 Compressing… {done_s/60:.1f}/{total_secs/60:.1f} min"
                                    f"  ({pct}%){eta}"
                                )
                            else:
                                elapsed_str = f"{int(elapsed)}s"
                                update_status(
                                    f"🎙 Compressing… {done_s/60:.1f} min done"
                                    f"  ({elapsed_str} elapsed)"
                                )

                    proc.wait()
                    if proc.returncode != 0:
                        err_detail = "".join(stderr_lines)[-400:]
                        raise Exception(
                            "FFmpeg failed to read the video.\n\n"
                            "Possible causes:\n"
                            "• File is corrupted or incomplete\n"
                            "• Unsupported codec\n\n"
                            f"Detail: {err_detail}"
                        )
                except FileNotFoundError:
                    raise Exception(
                        "ffmpeg.exe not found!\n\n"
                        "Make sure the app is installed correctly and ffmpeg is in the bin/ folder."
                    )

                set_progress_indeterminate(False)
                update_progress(100, 100, "compressed")
                save_cache_meta(video_path, segment_time, config.TEMP_DIR)

            chunks = sorted([f for f in os.listdir(config.TEMP_DIR)
                             if f.endswith('.m4a') and not f.startswith('_')])
            if not chunks:
                raise Exception(
                    "No audio was extracted from this video.\n\n"
                    "The file may have no audio track, or be in an unsupported format."
                )

            # ── Stage 2: Transcription ─────────────────────────────────────
            lang_info = f" [{source_lang_name}]" if source_lang_code else " [Auto-Detect]"
            set_busy(True, f"☁️ Stage 2 of 4 — Transcribing{lang_info}")
            update_progress(0, len(chunks), "parts")
            update_status(f"Transcribing {len(chunks)} chunk(s) via {provider}…")

            all_segments_raw = [None] * len(chunks)
            completed = [0]
            import time as _time
            _t0 = _time.time()

            # Build Whisper initial_prompt to bias transcription toward source language
            # This significantly reduces hallucinated mixed-script output.
            if source_lang_code:
                _whisper_prompt = (
                    f"The following is speech in {source_lang_name}. "
                    f"Please transcribe only in the {source_lang_name} script."
                )
            else:
                _whisper_prompt = None

            def _transcribe_one(idx_chunk):
                i, chunk = idx_chunk
                return i, transcribe_audio_chunk(
                    os.path.join(config.TEMP_DIR, chunk),
                    provider, api_key, source_lang_code, custom_url,
                    prompt=_whisper_prompt,
                    stop_check=is_stopped
                )

            max_workers = min(config.MAX_TRANSCRIPTION_WORKERS, len(chunks))
            _trans_executor = _cf.ThreadPoolExecutor(max_workers=max_workers)
            try:
                futures = {_trans_executor.submit(_transcribe_one, (i, c)): i
                           for i, c in enumerate(chunks)}
                for future in _cf.as_completed(futures):
                    if is_stopped():
                        _trans_executor.shutdown(wait=False, cancel_futures=True)
                        raise Exception("⏹ Stopped by user.")
                    i, ai_data = future.result()
                    all_segments_raw[i] = ai_data
                    completed[0] += 1
                    elapsed = int(_time.time() - _t0)
                    # ETA estimate
                    if completed[0] > 0 and len(chunks) > 1:
                        eta_s = int(elapsed / completed[0] * (len(chunks) - completed[0]))
                        eta_str = f"  ETA ~{eta_s}s" if eta_s > 0 else "  almost done"
                    else:
                        eta_str = ""
                    update_progress(completed[0], len(chunks), "parts")
                    update_status(
                        f"☁️ Transcribed {completed[0]}/{len(chunks)} chunk(s)"
                        f"{lang_info}  ⏱ {elapsed}s{eta_str}"
                    )
            finally:
                _trans_executor.shutdown(wait=False, cancel_futures=True)

            # ── Merge segments + clean hallucinations + split long lines ───
            all_segments = []
            for i, ai_data in enumerate(all_segments_raw):
                if ai_data is None:
                    continue
                offset = i * segment_time
                for seg in ai_data.get("segments", []):
                    text = seg["text"].strip()
                    if not text:
                        continue
                    text = _clean_subtitle_text(text, source_lang_code=source_lang_code)
                    if not text:
                        continue
                    # Split segment if it exceeds max display length
                    for sub in _split_long_subtitle(text, seg["start"] + offset,
                                                    seg["end"] + offset):
                        all_segments.append(sub)

            if not all_segments:
                raise Exception(
                    "No speech was detected in this video.\n\n"
                    "Possible causes:\n"
                    "• Video has no spoken dialogue\n"
                    "• Audio is too quiet or in a rare language\n"
                    "• Wrong 'Source Language' selected — try 'Auto Detect'"
                )

            # ── Stage 3: Translation ───────────────────────────────────────
            target_code = config.LANGUAGES.get(target_lang, "en")
            whisper_output_lang = source_lang_code  # None when Auto-Detect
            need_translate = (whisper_output_lang is None) or (target_code != whisper_output_lang)

            if need_translate:
                import time as _time
                mode = "Romanized" if romanize else "Native Script"
                n_lines = len(all_segments)
                set_busy(True, f"🌐 Stage 3 of 4 — Translating → {target_lang}")
                update_progress(0, n_lines, "lines")
                update_status(
                    f"Translating {n_lines} lines → {target_lang} ({mode})"
                    f"  [batch mode — much faster]…"
                )
                _t3 = _time.time()

                def _trans_prog(done, total):
                    if is_stopped():
                        raise Exception("⏹ Stopped by user.")
                    elapsed = int(_time.time() - _t3)
                    if done > 0 and total > done:
                        eta_s = int(elapsed / done * (total - done))
                        eta_str = f"  ETA ~{eta_s}s"
                    else:
                        eta_str = "  almost done"
                    update_progress(done, total, "lines")
                    update_status(
                        f"🌐 Translating {done}/{total} lines → {target_lang}"
                        f"  ⏱ {elapsed}s{eta_str}"
                    )

                translate_batch(all_segments, target_code, romanize,
                                progress_callback=_trans_prog,
                                source_code=whisper_output_lang,
                                stop_check=is_stopped)
                update_progress(len(all_segments), len(all_segments), "lines")
            else:
                set_busy(True, "✅ Stage 3 of 4 — No Translation Needed")
                update_progress(100, 100, "lines")
                update_status(f"Source and target language match — skipping translation.")

            if is_stopped():
                raise Exception("⏹ Stopped by user.")

            # ── Stage 4: Save ──────────────────────────────────────────────
            set_busy(True, "💾 Stage 4 of 4 — Saving Subtitle")
            update_status("Saving subtitle file…")
            set_progress_indeterminate(True)

            srt_content = "".join(
                f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                for i, s in enumerate(all_segments) if s['text']
            )
            suffix   = f"_{target_lang}_Romanized" if romanize else f"_{target_lang}"
            srt_name = f"{os.path.splitext(os.path.basename(video_path))[0]}{suffix}.srt"
            srt_path = clean_path(os.path.join(config.SUB_DIR, srt_name))
            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            set_progress_indeterminate(False)
            update_progress(100, 100)
            update_status(f"✅ Done! {len(all_segments)} subtitle lines → {srt_name}")
            _ui(lambda: stage_label.config(
                text=f"✅ Generated {len(all_segments)} lines", fg="#4CAF50"))

            populate_all_tabs(srt_path)
            apply_subtitle_to_vlc(app, srt_path,
                f"✅ Subtitles Generated!\n{len(all_segments)} lines | {target_lang}",
                video_path)

        except Exception as e:
            set_progress_indeterminate(False)
            err = str(e)
            if "⏹ Stopped" in err:
                update_status("⏹ Stopped.")
                _ui(lambda: stage_label.config(text="⏹ Stopped", fg="#888"))
                _ui(lambda: progress_var.set(0))
                _ui(lambda: progress_label.config(text=""))
            else:
                _ui(lambda: messagebox.showerror("Generation Error", err))
                update_status("❌ Error — see dialog for details.")
                _ui(lambda: stage_label.config(text="❌ Failed", fg="#ff4444"))
        finally:
            _safe_unbusy(_my_id)

    threading.Thread(target=_task, daemon=True).start()


def run_online_search():
    if _warn_busy(): return

    video_path  = clean_path(gen_video_var.get().strip())
    target_lang = gen_lang_var.get()

    if not _require(video_path, "❌ No Video Selected",
                    "Please select a video file first.\n\n"
                    "Online search matches by file hash — the exact same file must be used."):
        return
    if not _require(os.path.exists(video_path), "❌ File Not Found",
                    f"Video file not found:\n{video_path}"):
        return

    def _task():
        try:
            set_busy(True, "🌐 Online Subtitle Search")
            _my_id = _task_id
            set_progress_indeterminate(True)
            from engines import fetch_online_subtitle
            target_code = config.LANGUAGES.get(target_lang, "en")
            out_path = fetch_online_subtitle(video_path, target_code, update_status)
            set_progress_indeterminate(False)
            update_progress(100, 100)
            if out_path:
                update_status(f"✅ Online subtitle downloaded!")
                _ui(lambda: stage_label.config(text="✅ Downloaded", fg="#4CAF50"))
                populate_all_tabs(out_path)
                apply_subtitle_to_vlc(app, out_path, f"✅ Online Subtitle!\n{target_lang}", video_path)
        except Exception as e:
            set_progress_indeterminate(False)
            _ui(lambda: messagebox.showerror("Search Error",
                f"{e}\n\n💡 Tips:\n"
                "• Online subtitles match by file hash — rename won't help\n"
                "• Works best with popular movies/TV shows\n"
                "• Try AI Generate if online search fails"))
            update_status("❌ Online search failed.")
            _ui(lambda: stage_label.config(text="❌ Not Found", fg="#ff4444"))
        finally:
            _safe_unbusy(_my_id)

    threading.Thread(target=_task, daemon=True).start()

def run_translation():
    if _warn_busy(): return

    srt_path    = clean_path(trans_srt_var.get().strip())
    target_lang = trans_lang_var.get()
    romanize    = trans_romanize_var.get()

    if not _require(srt_path, "❌ No Subtitle File",
                    "Please select or browse to an SRT or ASS subtitle file.\n\n"
                    "Tip: Run 'Generate AI' first to create one."):
        return
    if not _require(os.path.exists(srt_path), "❌ File Not Found",
                    f"Subtitle file not found:\n{srt_path}\n\n"
                    "Please re-select the file."):
        return

    def _task():
        try:
            set_busy(True, f"🌐 Translating → {target_lang}")
            _my_id = _task_id
            update_status("Parsing subtitle file…")
            segments = parse_srt(srt_path)
            if not segments:
                raise Exception(
                    "Could not read any subtitle entries from the file.\n\n"
                    "Make sure it is a valid SRT file with timestamps."
                )

            target_code = config.LANGUAGES.get(target_lang, "en")
            mode = "Romanized" if romanize else "Native Script"
            update_status(f"🌐 Translating {len(segments)} lines → {target_lang} ({mode})…")
            update_progress(0, len(segments), "lines")

            def _prog(done, total):
                if is_stopped():
                    raise Exception("⏹ Stopped by user.")
                update_progress(done, total, "lines")
                update_status(f"🌐 Translating {done}/{total} → {target_lang}")

            translate_batch(segments, target_code, romanize,
                            progress_callback=_prog, stop_check=is_stopped)
            update_progress(len(segments), len(segments), "lines")

            srt_content = "".join(
                f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                for i, s in enumerate(segments)
            )
            base      = os.path.splitext(os.path.basename(srt_path))[0]
            suffix    = f"_{target_lang}_Romanized" if romanize else f"_{target_lang}"
            save_path = clean_path(os.path.join(config.SUB_DIR, f"{base}{suffix}.srt"))
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            update_status(f"✅ Translation Done! {len(segments)} lines → {target_lang}")
            update_progress(100, 100)
            _ui(lambda: stage_label.config(
                text=f"✅ Translated {len(segments)} lines", fg="#4CAF50"))
            populate_all_tabs(save_path)
            apply_subtitle_to_vlc(app, save_path,
                f"✅ Translation Finished!\n{len(segments)} lines → {target_lang}",
                clean_path(gen_video_var.get()))
        except Exception as e:
            _err = str(e)
            if "⏹ Stopped" in _err:
                update_status("⏹ Stopped.")
                _ui(lambda: stage_label.config(text="⏹ Stopped", fg="#888"))
                _ui(lambda: progress_var.set(0))
                _ui(lambda: progress_label.config(text=""))
            else:
                _ui(lambda: messagebox.showerror("Translation Error", _err))
                update_status("❌ Translation failed.")
                _ui(lambda: stage_label.config(text="❌ Failed", fg="#ff4444"))
        finally:
            _safe_unbusy(_my_id)

    threading.Thread(target=_task, daemon=True).start()


def run_auto_sync():
    if _warn_busy(): return

    srt_path   = clean_path(sync_srt_var.get().strip())
    video_path = clean_path(gen_video_var.get().strip())

    if not _require(video_path, "❌ No Video",
                    "Please select a video in Tab 1 — it's needed to analyse the audio timing."):
        return
    if not _require(srt_path and os.path.exists(srt_path), "❌ No Subtitle File",
                    "Please select the SRT subtitle file you want to auto-sync."):
        return

    def _task():
        try:
            set_busy(True, "🔍 Auto-Sync — Analysing Audio")
            _my_id = _task_id
            set_progress_indeterminate(True)
            update_status("Analysing audio for first speech… (~30s)")
            offset, info = detect_sync_offset(video_path, srt_path, update_status)
            set_progress_indeterminate(False)
            if offset is None:
                raise Exception(f"Auto-sync failed:\n{info}")
            offset_str = f"{offset:+.2f}"
            _ui(lambda: sync_offset_var.set(offset_str))
            update_status(f"✅ Auto-detected offset: {offset_str}s — click SYNC & APPLY to save")
            update_progress(100, 100)
            _ui(lambda: stage_label.config(
                text=f"✅ Offset: {offset_str}s detected", fg="#4CAF50"))
            _ui(lambda: messagebox.showinfo(
                "🎯 Auto-Sync Result",
                f"Detected Offset: {offset_str}s\n\n{info}\n\n"
                "✅ Click  ⏱️ SYNC & APPLY  to apply this offset."))
        except Exception as e:
            set_progress_indeterminate(False)
            _ui(lambda: messagebox.showerror("Auto-Sync Error", str(e)))
            update_status("❌ Auto-sync failed.")
            _ui(lambda: stage_label.config(text="❌ Failed", fg="#ff4444"))
        finally:
            _safe_unbusy(_my_id)

    threading.Thread(target=_task, daemon=True).start()


def run_sync():
    if _warn_busy(): return

    srt_path = clean_path(sync_srt_var.get().strip())
    offset_raw = sync_offset_var.get().strip().replace('+', '')

    try:
        offset_val = float(offset_raw)
    except ValueError:
        return messagebox.showerror(
            "❌ Invalid Offset",
            f"'{offset_raw}' is not a valid number.\n\n"
            "Examples:\n"
            "  +2.5  →  delay subtitles by 2.5 seconds\n"
            "  -1.5  →  advance subtitles by 1.5 seconds"
        )

    if not _require(srt_path and os.path.exists(srt_path), "❌ No Subtitle File",
                    "Please select the SRT file you want to shift."):
        return

    def _task():
        try:
            set_busy(True, f"⏱️ Syncing Offset {offset_val:+.2f}s")
            _my_id = _task_id
            set_progress_indeterminate(True)
            update_status("Adjusting timestamps…")
            segments = parse_srt(srt_path)
            for seg in segments:
                seg['start'] = max(0, seg['start'] + offset_val)
                seg['end']   = max(0.001, seg['end'] + offset_val)
                if seg['end'] <= seg['start']:
                    seg['end'] = seg['start'] + 0.5

            srt_content = "".join(
                f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                for i, s in enumerate(segments)
            )
            base      = re.sub(r'_synced$', '', os.path.splitext(os.path.basename(srt_path))[0])
            save_path = clean_path(os.path.join(config.SUB_DIR, f"{base}_synced.srt"))
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            set_progress_indeterminate(False)
            update_progress(100, 100)
            update_status(f"✅ Sync done! Offset: {offset_val:+.2f}s")
            _ui(lambda: stage_label.config(
                text=f"✅ Synced {offset_val:+.2f}s", fg="#4CAF50"))
            populate_all_tabs(save_path)
            apply_subtitle_to_vlc(app, save_path,
                f"✅ Sync Applied!\nOffset: {offset_val:+.2f} seconds",
                clean_path(gen_video_var.get()))
        except Exception as e:
            set_progress_indeterminate(False)
            _ui(lambda: messagebox.showerror("Sync Error", str(e)))
            update_status("❌ Sync failed.")
            _ui(lambda: stage_label.config(text="❌ Failed", fg="#ff4444"))
        finally:
            _safe_unbusy(_my_id)

    threading.Thread(target=_task, daemon=True).start()


def pick_color(var, btn):
    initial = var.get() if var.get().startswith('#') else '#ffffff'
    result  = colorchooser.askcolor(color=initial, title="Pick Color")
    if result and result[1]:
        var.set(result[1])
        btn.config(bg=result[1], fg="white" if result[1].lower() in ['#000000','#111111','#222222','#333333'] else "black")


def run_export_ass():
    if _warn_busy(): return

    srt_path = clean_path(custom_srt_var.get().strip())
    if not _require(srt_path and os.path.exists(srt_path), "❌ No Subtitle File",
                    "Please select an SRT file to style and export.\n\n"
                    "Browse for one, or generate one in Tab 1."):
        return

    def _task():
        try:
            set_busy(True, "🎨 Exporting Styled ASS")
            _my_id = _task_id
            set_progress_indeterminate(True)
            update_status("Generating styled ASS subtitle…")
            segments = parse_srt(srt_path)
            if not segments:
                raise Exception("Could not parse the SRT file.")

            style = {
                "font_name": custom_font_var.get() or "Arial",
                "font_size": custom_size_var.get(),
                "primary_color": custom_text_color_var.get(),
                "outline_color": custom_outline_color_var.get(),
                "background": custom_bg_var.get(),
                "bold": custom_bold_var.get(),
                "italic": custom_italic_var.get(),
                "outline": custom_outline_sz_var.get(),
                "shadow": custom_shadow_var.get(),
                "alignment": 8 if custom_position_var.get() == "top" else 2,
            }
            ass_content = generate_ass_content(segments, style)
            base     = os.path.splitext(os.path.basename(srt_path))[0]
            ass_path = clean_path(os.path.join(config.SUB_DIR, f"{base}_styled.ass"))
            with open(ass_path, 'w', encoding='utf-8') as f:
                f.write(ass_content)

            set_progress_indeterminate(False)
            update_progress(100, 100)
            update_status("✅ Styled ASS subtitle exported!")
            _ui(lambda: stage_label.config(text="✅ ASS Exported", fg="#4CAF50"))
            apply_subtitle_to_vlc(app, ass_path, "✅ Styled Subtitle (.ASS)", clean_path(gen_video_var.get()))
        except Exception as e:
            set_progress_indeterminate(False)
            _ui(lambda: messagebox.showerror("Export Error", str(e)))
            update_status("❌ Export failed.")
            _ui(lambda: stage_label.config(text="❌ Failed", fg="#ff4444"))
        finally:
            _safe_unbusy(_my_id)

    threading.Thread(target=_task, daemon=True).start()


def run_burn_to_video():
    if _warn_busy(): return

    srt_path   = clean_path(custom_srt_var.get().strip())
    video_path = clean_path(gen_video_var.get().strip())

    if not _require(srt_path and os.path.exists(srt_path), "❌ No Subtitle File",
                    "Please select the SRT/ASS file to burn into the video."):
        return
    if not _require(video_path and os.path.exists(video_path), "❌ No Video File",
                    "Please select a video file in Tab 1 first.\n\n"
                    "⚠️  Burn Into Video creates a NEW video file — the original is NOT changed."):
        return

    answer = messagebox.askyesno(
        "🔥 Confirm Burn Into Video",
        "This will permanently embed the subtitles into the video.\n\n"
        "A new video file will be created (original is kept).\n"
        "This may take several minutes depending on video length.\n\n"
        "Continue?"
    )
    if not answer:
        return

    def _task():
        try:
            set_busy(True, "🔥 Burning Subtitles Into Video")
            _my_id = _task_id
            set_progress_indeterminate(True)
            update_status("🔥 Embedding subtitles — this may take several minutes…")

            segments = parse_srt(srt_path)
            if not segments:
                raise Exception("Could not parse the subtitle file.")

            style = {
                "font_name": custom_font_var.get() or "Arial",
                "font_size": custom_size_var.get(),
                "primary_color": custom_text_color_var.get(),
                "outline_color": custom_outline_color_var.get(),
                "background": custom_bg_var.get(),
                "bold": custom_bold_var.get(),
                "italic": custom_italic_var.get(),
                "outline": custom_outline_sz_var.get(),
                "shadow": custom_shadow_var.get(),
                "alignment": 8 if custom_position_var.get() == "top" else 2,
            }
            ass_content = generate_ass_content(segments, style)
            base     = os.path.splitext(os.path.basename(srt_path))[0]
            ass_path = clean_path(os.path.join(config.SUB_DIR, f"{base}_styled.ass"))
            with open(ass_path, 'w', encoding='utf-8') as f:
                f.write(ass_content)

            out_path = burn_subtitles_into_video(video_path, ass_path)

            set_progress_indeterminate(False)
            update_progress(100, 100)
            update_status(f"✅ Subtitles burned into video! → {os.path.basename(out_path)}")
            _ui(lambda: stage_label.config(text="✅ Video Burned", fg="#4CAF50"))
            _ui(lambda: messagebox.showinfo(
                "✅ Embedding Complete",
                f"Subtitles permanently embedded!\n\nSaved to:\n{out_path}"
            ))
        except Exception as e:
            set_progress_indeterminate(False)
            _ui(lambda: messagebox.showerror("Embedding Error", str(e)))
            update_status("❌ Burn failed.")
            _ui(lambda: stage_label.config(text="❌ Failed", fg="#ff4444"))
        finally:
            _ui(lambda: burn_btn.config(text="🔥 Burn Into Video"))
            _safe_unbusy(_my_id)

    threading.Thread(target=_task, daemon=True).start()

def on_video_change(*args):
    v_path = gen_video_var.get().strip()
    subs   = get_available_subtitles(v_path)
    if trans_srt_cb:  trans_srt_cb['values']  = subs
    if sync_srt_cb:   sync_srt_cb['values']   = subs
    if custom_srt_cb: custom_srt_cb['values'] = subs
    best = detect_paired_file(v_path, "srt")
    if best: populate_all_tabs(best)
    elif subs:
        if not trans_srt_var.get(): populate_all_tabs(subs[0])
    # Launch background thread to extract thumbnail + metadata
    threading.Thread(target=update_video_info, args=(v_path,), daemon=True).start()

def browse_srt(var):
    f = filedialog.askopenfilename(filetypes=[("Subtitles", "*.srt *.ass")])
    if f: var.set(clean_path(f))

def browse_video(var):
    f = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mkv *.avi *.ts *.mov *.wmv")])
    if f: var.set(clean_path(f))


# ============================================================
# VIDEO THUMBNAIL + METADATA PANEL
# ============================================================
def update_video_info(video_path):
    """Background thread: extract a thumbnail frame and video metadata, then push to UI."""
    if not video_path or not os.path.exists(video_path):
        _ui(_clear_video_info)
        return

    ffmpeg_path = get_ffmpeg_path()
    cf = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    thumb_path = os.path.join(config.TEMP_DIR, '_preview_thumb.jpg')

    # --- Extract thumbnail frame at ~3 seconds ---
    try:
        subprocess.run(
            [ffmpeg_path, '-y', '-i', video_path,
             '-ss', '3', '-vframes', '1', '-vf', 'scale=210:-1', thumb_path],
            capture_output=True, creationflags=cf, timeout=20
        )
    except Exception:
        pass

    # --- Parse metadata from ffmpeg stderr (no ffprobe needed) ---
    meta = {}
    try:
        result = subprocess.run(
            [ffmpeg_path, '-i', video_path],
            capture_output=True, creationflags=cf, timeout=15
        )
        stderr = result.stderr.decode('utf-8', errors='ignore')

        # Duration
        dm = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', stderr)
        if dm:
            h, m, s = int(dm.group(1)), int(dm.group(2)), float(dm.group(3))
            meta['duration'] = f"{h}h {m}m" if h > 0 else f"{m}m {int(s)}s"

        # Video stream — codec + resolution
        vm = re.search(r'Stream.*?Video:\s*(\w+).*?(\d{3,5})x(\d{3,5})', stderr)
        if vm:
            meta['codec']      = vm.group(1).upper()
            meta['resolution'] = f"{vm.group(2)}\u00d7{vm.group(3)}"

        # FPS
        fps_m = re.search(r'([\d.]+) fps', stderr)
        if fps_m:
            meta['fps'] = fps_m.group(1)

        # Audio codec
        am = re.search(r'Stream.*?Audio:\s*(\w+)', stderr)
        if am:
            meta['audio'] = am.group(1).upper()

        # File size
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        meta['size'] = f"{size_mb:.1f} MB"

    except Exception:
        pass

    _ui(lambda: _update_video_info_ui(thumb_path, meta))


def _clear_video_info():
    """Hide the video info panel."""
    video_info_frame.pack_forget()


def _update_video_info_ui(thumb_path, meta):
    """Runs on main thread: update thumbnail image and metadata text."""
    global _thumb_img_ref

    # --- Thumbnail ---
    resample = getattr(Image, 'LANCZOS', getattr(Image, 'ANTIALIAS', None)) if PIL_AVAILABLE else None
    if PIL_AVAILABLE and os.path.exists(thumb_path) and resample:
        try:
            img = Image.open(thumb_path)
            img.thumbnail((210, 118), resample)
            _thumb_img_ref = ImageTk.PhotoImage(img)
            thumb_label.config(image=_thumb_img_ref, text='', width=210, height=118)
        except Exception:
            thumb_label.config(image='', text='\U0001f3ac', font=('Segoe UI', 22), width=8, height=4)
            _thumb_img_ref = None
    else:
        thumb_label.config(image='', text='\U0001f3ac', font=('Segoe UI', 22), width=8, height=4)
        _thumb_img_ref = None

    # --- Metadata lines ---
    if meta:
        lines = []
        if 'duration'   in meta: lines.append(f"\u23f1  Duration    {meta['duration']}")
        if 'resolution' in meta: lines.append(f"\U0001f4d0  Resolution  {meta['resolution']}")
        if 'codec' in meta:
            c = meta['codec']
            if 'fps' in meta: c += f"  @  {meta['fps']} fps"
            lines.append(f"\U0001f3ac  Video       {c}")
        if 'audio' in meta: lines.append(f"\U0001f50a  Audio       {meta['audio']}")
        if 'size'  in meta: lines.append(f"\U0001f4be  File Size   {meta['size']}")
        info_label.config(text='\n'.join(lines))
    else:
        info_label.config(text="\u26a0\ufe0f  Could not read metadata.")

    video_info_frame.pack(fill=tk.X, padx=12, pady=(4, 10))


# ============================================================
# SETTINGS WINDOW
# ============================================================
def open_settings():
    """Open the Settings popup window with all configuration options."""
    win = tk.Toplevel(app)
    win.title("⚙ Settings — .Vsub")
    win.geometry("480x560")
    win.configure(bg=config.DARK_BG)
    win.resizable(False, False)
    win.transient(app)
    win.grab_set()
    try: win.iconbitmap(resource_path("logo.ico"))
    except: pass

    # ── Header ───────────────────────────────────────────────
    hf = tk.Frame(win, bg=config.DARK_BG); hf.pack(fill=tk.X, padx=20, pady=(14, 4))
    tk.Label(hf, text="⚙ Settings", bg=config.DARK_BG, fg=config.VLC_ORANGE,
             font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)

    body = tk.Frame(win, bg=config.PANEL_BG, bd=1, relief=tk.SOLID)
    body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 12))

    def section(parent, title):
        tk.Label(parent, text=title, bg=config.PANEL_BG, fg=config.VLC_ORANGE,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Frame(parent, bg="#333", height=1).pack(fill=tk.X, padx=14, pady=(0, 8))

    def row(parent, label, widget_fn):
        f = tk.Frame(parent, bg=config.PANEL_BG); f.pack(fill=tk.X, padx=14, pady=3)
        tk.Label(f, text=label, bg=config.PANEL_BG, fg="#ccc",
                 font=("Segoe UI", 9), width=18, anchor="w").pack(side=tk.LEFT)
        widget_fn(f)
        return f

    # ── TRANSCRIPTION PROVIDER ───────────────────────────────
    section(body, "🤖  Transcription Provider")

    def _provider_row(f):
        ttk.Combobox(f, textvariable=provider_var,
                     values=[".Vsub Cloud (Free ✨)", "Groq (Lightning Fast)",
                             "OpenAI (Standard)", "Custom API (OpenAI Format)"],
                     state="readonly", width=28).pack(side=tk.LEFT)
    row(body, "Provider:", _provider_row)

    # Cloud info line
    cloud_info = tk.Label(body, text="🌐 Powered by .Vsub Cloud — no API key needed!",
                          bg=config.PANEL_BG, fg="#4CAF50", font=("Segoe UI", 8))
    cloud_info.pack(anchor="w", padx=14, pady=(0, 2))

    # ── API KEY ───────────────────────────────────────────────
    section(body, "🔑  API Key")

    api_frame = tk.Frame(body, bg=config.PANEL_BG)
    api_frame.pack(fill=tk.X, padx=14, pady=3)
    tk.Label(api_frame, text="API Key:", bg=config.PANEL_BG, fg="#ccc",
             font=("Segoe UI", 9), width=18, anchor="w").pack(side=tk.LEFT)
    key_entry = tk.Entry(api_frame, textvariable=api_key_var, show="*", width=26,
                         bg=config.DARK_BG, fg="white", insertbackground="white", border=0)
    key_entry.pack(side=tk.LEFT, ipady=3, padx=(0, 5))
    def on_save_key_settings():
        key = api_key_var.get().strip()
        if key:
            save_api_key(key)
            messagebox.showinfo("Saved", "API Key saved securely!", parent=win)
        else:
            messagebox.showwarning("Empty", "Please paste an API key first.", parent=win)
    tk.Button(api_frame, text="💾 Save", bg="#333", fg="white", relief=tk.FLAT,
              command=on_save_key_settings, padx=5).pack(side=tk.LEFT)

    key_hint = tk.Label(body, text="Get a free Groq key at console.groq.com",
                        bg=config.PANEL_BG, fg="#555", font=("Segoe UI", 7))
    key_hint.pack(anchor="w", padx=14, pady=(0, 4))

    # ── CUSTOM API URL (shown only for Custom provider) ───────
    custom_url_frame = tk.Frame(body, bg=config.PANEL_BG)
    custom_url_frame.pack(fill=tk.X, padx=14, pady=3)
    tk.Label(custom_url_frame, text="API URL:", bg=config.PANEL_BG, fg="#ccc",
             font=("Segoe UI", 9), width=18, anchor="w").pack(side=tk.LEFT)
    tk.Entry(custom_url_frame, textvariable=custom_url_var, width=28,
             bg=config.DARK_BG, fg="white", insertbackground="white", border=0).pack(side=tk.LEFT, ipady=2)

    # ── .VSUB CLOUD SERVER URL ────────────────────────────────
    section(body, "🌐  .Vsub Cloud Server")
    cloud_url_frame = tk.Frame(body, bg=config.PANEL_BG)
    cloud_url_frame.pack(fill=tk.X, padx=14, pady=3)
    tk.Label(cloud_url_frame, text="Server URL:", bg=config.PANEL_BG, fg="#ccc",
             font=("Segoe UI", 9), width=18, anchor="w").pack(side=tk.LEFT)
    cloud_url_entry = tk.Entry(cloud_url_frame, textvariable=vsub_server_url_var, width=28,
                               bg=config.DARK_BG, fg="white", insertbackground="white", border=0)
    cloud_url_entry.pack(side=tk.LEFT, ipady=2)
    def _save_cloud_url():
        new_url = vsub_server_url_var.get().strip()
        if new_url.startswith("http"):
            config.VSUB_CLOUD_URL = new_url
            messagebox.showinfo("Saved", "Cloud URL updated for this session.", parent=win)
        else:
            messagebox.showwarning("Invalid", "URL must start with http:// or https://", parent=win)
    tk.Button(cloud_url_frame, text="✓ Set", bg="#333", fg="white", relief=tk.FLAT,
              command=_save_cloud_url, padx=5).pack(side=tk.LEFT, padx=(5,0))

    # ── PERFORMANCE ───────────────────────────────────────────
    section(body, "⚡  Performance")

    workers_var = tk.IntVar(value=config.MAX_TRANSCRIPTION_WORKERS)
    def _workers_row(f):
        tk.Scale(f, from_=1, to=8, orient=tk.HORIZONTAL, variable=workers_var,
                 bg=config.PANEL_BG, fg="white", highlightthickness=0,
                 troughcolor="#333", activebackground=config.VLC_ORANGE, length=140,
                 command=lambda v: setattr(config, "MAX_TRANSCRIPTION_WORKERS", int(float(v)))
                 ).pack(side=tk.LEFT)
        wl = tk.Label(f, textvariable=workers_var, bg=config.PANEL_BG, fg=config.VLC_ORANGE,
                      font=("Segoe UI", 9, "bold"), width=2)
        wl.pack(side=tk.LEFT, padx=4)
    row(body, "Parallel Workers:", _workers_row)

    chunk_var = tk.IntVar(value=config.AUDIO_SEGMENT_TIME // 60)
    def _chunk_row(f):
        opts = ["3 min", "5 min", "8 min", "10 min"]
        vals = [180, 300, 480, 600]
        cb = ttk.Combobox(f, values=opts, state="readonly", width=10)
        cb.set(f"{config.AUDIO_SEGMENT_TIME // 60} min")
        def _set_chunk(e):
            idx = cb.current()
            if idx >= 0: config.AUDIO_SEGMENT_TIME = vals[idx]
        cb.bind("<<ComboboxSelected>>", _set_chunk)
        cb.pack(side=tk.LEFT)
    row(body, "Chunk Size:", _chunk_row)

    # ── Dynamic UI update (hide/show sections based on provider) ─
    def _update_settings_ui(*_):
        prov = provider_var.get()
        is_cloud  = ".Vsub Cloud" in prov
        is_custom = "Custom" in prov

        if is_cloud:
            cloud_info.pack(anchor="w", padx=14, pady=(0, 2))
        else:
            cloud_info.pack_forget()
        # API key & hint — hidden when cloud
        if is_cloud:
            api_frame.pack_forget()
            key_hint.pack_forget()
        else:
            api_frame.pack(fill=tk.X, padx=14, pady=3)
            key_hint.pack(anchor="w", padx=14, pady=(0, 4))
        # Custom URL — only for Custom provider
        if is_custom:
            custom_url_frame.pack(fill=tk.X, padx=14, pady=3)
        else:
            custom_url_frame.pack_forget()

        # Update main-screen provider badge
        try:
            _refresh_provider_badge()
        except Exception:
            pass

    # ── Close button ─────────────────────────────────────────
    def _on_close():
        try: provider_var.trace_remove("write", _trace_id)
        except Exception: pass
        win.destroy()

    _trace_id = provider_var.trace_add("write", _update_settings_ui)
    _update_settings_ui()

    tk.Button(win, text="✓ Close", bg=config.VLC_ORANGE, fg="black",
              font=("Segoe UI", 10, "bold"), relief=tk.FLAT,
              command=_on_close, padx=20, pady=6).pack(pady=(0, 14))
    win.protocol("WM_DELETE_WINDOW", _on_close)

    win.wait_window()


# ============================================================
# MAIN APPLICATION STARTUP
# ============================================================
if __name__ == '__main__':
    # UI SETUP  (this block runs at module scope — no `global` needed)
    app = tk.Tk()
    app.title(".Vsub — AI Subtitle Toolkit")
    app.geometry("560x720")
    app.configure(bg=config.DARK_BG)
    app.resizable(False, False)

    try: app.iconbitmap(resource_path("logo.ico"))
    except: pass

    style = ttk.Style()
    style.theme_use('clam')
    style.configure('TCombobox', fieldbackground="white", background="white", foreground="black", borderwidth=0)
    style.map('TCombobox', fieldbackground=[('readonly', 'white'), ('focus', 'white')],
              foreground=[('readonly', 'black'), ('focus', 'black')],
              selectbackground=[('readonly', config.VLC_ORANGE)], selectforeground=[('readonly', 'black')])
    style.configure("Orange.Horizontal.TProgressbar", background=config.VLC_ORANGE, troughcolor=config.PANEL_BG, bordercolor=config.DARK_BG, lightcolor=config.VLC_ORANGE, darkcolor=config.VLC_ORANGE)
    # Indeterminate (pulsing) mode uses the same orange theme
    style.configure("Indeterminate.Horizontal.TProgressbar", background=config.VLC_ORANGE, troughcolor="#2a2a2a", bordercolor=config.DARK_BG, lightcolor=config.VLC_ORANGE, darkcolor=config.VLC_ORANGE)

    provider_var      = tk.StringVar(value=".Vsub Cloud (Free ✨)")
    api_key_var       = tk.StringVar(value=load_api_key())
    custom_url_var    = tk.StringVar(value="https://api.openai.com/v1/audio/transcriptions")
    vsub_server_url_var = tk.StringVar(value=config.VSUB_CLOUD_URL)

    gen_video_var     = tk.StringVar()
    gen_lang_var      = tk.StringVar(value="English")
    gen_romanize_var  = tk.BooleanVar(value=False)
    gen_source_lang_var = tk.StringVar(value="Auto Detect (Recommended)")
    trans_srt_var     = tk.StringVar()
    trans_lang_var    = tk.StringVar(value="Malayalam")
    trans_romanize_var = tk.BooleanVar(value=False)
    sync_srt_var      = tk.StringVar()
    sync_offset_var   = tk.StringVar(value="+0.0")
    custom_srt_var        = tk.StringVar()
    custom_font_var       = tk.StringVar(value="Arial")
    custom_size_var       = tk.IntVar(value=20)
    custom_text_color_var = tk.StringVar(value="#FFFFFF")
    custom_outline_color_var = tk.StringVar(value="#000000")
    custom_bg_var         = tk.BooleanVar(value=True)
    custom_bold_var       = tk.BooleanVar(value=False)
    custom_italic_var     = tk.BooleanVar(value=False)
    custom_outline_sz_var = tk.IntVar(value=2)
    custom_shadow_var     = tk.IntVar(value=1)
    custom_position_var   = tk.StringVar(value="bottom")
    progress_var = tk.IntVar(value=0)
    gen_video_var.trace_add("write", on_video_change)

    style_vars = {
        'srt_path': custom_srt_var, 'font_name': custom_font_var, 'font_size': custom_size_var,
        'text_color': custom_text_color_var, 'outline_color': custom_outline_color_var,
        'bg': custom_bg_var, 'bold': custom_bold_var, 'italic': custom_italic_var,
        'outline_sz': custom_outline_sz_var, 'shadow': custom_shadow_var, 'position': custom_position_var
    }

    hdr = tk.Frame(app, bg=config.DARK_BG); hdr.pack(fill=tk.X, padx=20, pady=(14, 5))
    tk.Label(hdr, text=".Vsub — AI Subtitle Toolkit", bg=config.DARK_BG, fg=config.VLC_ORANGE, font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)

    tk.Button(hdr, text="⚙ Settings", bg="#333", fg=config.VLC_ORANGE, relief=tk.FLAT, font=("Segoe UI", 9, "bold"), command=open_settings, padx=8).pack(side=tk.RIGHT, padx=(4, 0))
    tk.Button(hdr, text="📜 History", bg="#333", fg="white", relief=tk.FLAT, font=("Segoe UI", 9), command=lambda: open_history(app, populate_all_tabs), padx=8).pack(side=tk.RIGHT)

    # --- DYNAMIC INSTALL/REMOVE EXTENSION BUTTON ---
    ext_btn = tk.Button(hdr, relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=8)
    ext_btn.pack(side=tk.RIGHT, padx=(0, 10))

    def update_ext_btn():
        if os.path.exists(get_vlc_ext_path()):
            ext_btn.config(text="🗑️ Remove Ext.", bg="#333", fg="#ff4444", command=lambda: [remove_vlc_extension(app), update_ext_btn()])
        else:
            ext_btn.config(text="🔌 Install Ext.", bg="#333", fg=config.VLC_ORANGE, command=lambda: [install_vlc_extension(app), update_ext_btn()])

    update_ext_btn()
    # -----------------------------------------------

    tab_frame = tk.Frame(app, bg=config.DARK_BG); tab_frame.pack(fill=tk.X, padx=20, pady=5)
    def show_tab(idx):
        for i, btn in enumerate(tab_btns):
            btn.config(bg=config.VLC_ORANGE if i == idx else config.PANEL_BG, fg="black" if i == idx else "white", font=("Segoe UI", 8, "bold" if i == idx else "normal"))
        for i, frame in enumerate(frames):
            if i == idx: frame.grid(row=0, column=0, sticky="nsew")
            else: frame.grid_forget()

    tab_labels = ["1. Generate (AI)", "2. Translate", "3. Sync", "4. Customize"]
    tab_btns = [tk.Button(tab_frame, text=t, relief=tk.FLAT, width=13, command=lambda idx=i: show_tab(idx)) for i, t in enumerate(tab_labels)]
    for btn in tab_btns: btn.pack(side=tk.LEFT, padx=2)

    cc = tk.Frame(app, bg=config.PANEL_BG, bd=1, relief=tk.SOLID); cc.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)
    cc.grid_rowconfigure(0, weight=1); cc.grid_columnconfigure(0, weight=1)
    frame_gen, frame_trans, frame_sync, frame_custom = tk.Frame(cc, bg=config.PANEL_BG), tk.Frame(cc, bg=config.PANEL_BG), tk.Frame(cc, bg=config.PANEL_BG), tk.Frame(cc, bg=config.PANEL_BG)
    frames = [frame_gen, frame_trans, frame_sync, frame_custom]

    # Tab 1
    # ── Provider badge (read-only display; user edits in Settings) ───────────
    badge_frame = tk.Frame(frame_gen, bg=config.PANEL_BG); badge_frame.pack(pady=(12, 2))
    tk.Label(badge_frame, text="Provider:", bg=config.PANEL_BG, fg="#aaa",
             font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 6))
    provider_badge = tk.Label(badge_frame, text="", bg="#1a2a1a", fg="#4CAF50",
                              font=("Segoe UI", 9, "bold"), padx=8, pady=3,
                              relief=tk.FLAT, cursor="hand2")
    provider_badge.pack(side=tk.LEFT)
    provider_badge.bind("<Button-1>", lambda e: open_settings())
    tk.Label(badge_frame, text="(⚙ change)", bg=config.PANEL_BG, fg="#555",
             font=("Segoe UI", 8), cursor="hand2").pack(side=tk.LEFT, padx=4)
    badge_frame.winfo_children()[-1].bind("<Button-1>", lambda e: open_settings())

    def _refresh_provider_badge():
        prov = provider_var.get()
        if ".Vsub Cloud" in prov:
            provider_badge.config(text="🌐 .Vsub Cloud (Free ✨)", bg="#1a2a1a", fg="#4CAF50")
        elif "Groq" in prov:
            provider_badge.config(text="⚡ Groq (Lightning Fast)", bg="#1a1a2a", fg="#7c9eff")
        elif "OpenAI" in prov:
            provider_badge.config(text="🤖 OpenAI (Standard)", bg="#1a1a2a", fg="#aaaaff")
        else:
            provider_badge.config(text="🔧 Custom API", bg="#2a2a1a", fg="#ffcc44")

    provider_var.trace_add("write", lambda *_: _refresh_provider_badge())
    _refresh_provider_badge()


    tk.Label(frame_gen, text="Select Video:", bg=config.PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(6, 2))
    f1 = tk.Frame(frame_gen, bg=config.PANEL_BG); f1.pack()
    tk.Entry(f1, textvariable=gen_video_var, width=33, bg=config.DARK_BG, fg="white", border=0).pack(side=tk.LEFT, padx=5, ipady=3)
    tk.Button(f1, text="Browse", command=lambda: browse_video(gen_video_var), bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT)
    tk.Label(frame_gen, text="Audio / Source Language:", bg=config.PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(8, 2))
    ttk.Combobox(frame_gen, textvariable=gen_source_lang_var, values=sorted(config.WHISPER_LANGUAGES.keys()), state="readonly", width=40).pack()
    tk.Label(frame_gen, text="⚠️ Use 'Auto Detect' for non-English videos", bg=config.PANEL_BG, fg="#888", font=("Segoe UI", 8)).pack()
    tk.Label(frame_gen, text="Translate Subtitles To:", bg=config.PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(8, 2))
    ttk.Combobox(frame_gen, textvariable=gen_lang_var, values=sorted(config.LANGUAGES.keys()), state="readonly", width=40).pack()
    tk.Checkbutton(frame_gen, text="Write in English Letters (e.g. Manglish, Hinglish)", variable=gen_romanize_var, bg=config.PANEL_BG, fg="#a0a0a0", activebackground=config.PANEL_BG, selectcolor=config.DARK_BG).pack(pady=(4, 0))

    row_gen = tk.Frame(frame_gen, bg=config.PANEL_BG); row_gen.pack(pady=12)
    gen_btn = tk.Button(row_gen, text="⚡ GENERATE AI", bg=config.VLC_ORANGE, fg="black", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, command=run_generation)
    gen_btn.pack(side=tk.LEFT, ipadx=6, ipady=6)
    fast_dl_btn = tk.Button(row_gen, text="🌐 Fast Online Download", bg="#008CBA", fg="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, command=run_online_search)
    fast_dl_btn.pack(side=tk.LEFT, padx=(4, 0), ipadx=6, ipady=6)
    tk.Button(row_gen, text="👁 Preview", bg="#2a2a2a", fg=config.VLC_ORANGE, relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=4, pady=6, command=lambda: show_srt_preview(app, clean_path(trans_srt_var.get()), "👁 Preview — Generated Subtitle")).pack(side=tk.LEFT, padx=(4, 0))
    tk.Button(row_gen, text="▶ VLC", bg="#2a2a2a", fg="#4CAF50", relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=4, pady=6, command=lambda: launch_vlc_preview(clean_path(gen_video_var.get()), clean_path(trans_srt_var.get()))).pack(side=tk.LEFT, padx=(4, 0))

    # --- VIDEO INFO PANEL (hidden by default; appears when a video is selected) ---
    video_info_frame = tk.Frame(frame_gen, bg="#1c1c1c")
    tk.Frame(video_info_frame, bg="#333", height=1).pack(fill=tk.X, pady=(0, 6))
    vi_inner = tk.Frame(video_info_frame, bg="#1c1c1c")
    vi_inner.pack(fill=tk.X, padx=10)
    thumb_label = tk.Label(vi_inner, bg="#111111", relief=tk.FLAT, anchor="center", width=1, height=1)
    thumb_label.pack(side=tk.LEFT, padx=(0, 12))
    info_label = tk.Label(vi_inner, text="", bg="#1c1c1c", fg="#cccccc",
                          font=("Segoe UI", 9), justify=tk.LEFT, anchor="nw")
    info_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=8)
    # ---------------------------------------------------------------------------

    # Tab 2
    tk.Label(frame_trans, text="Select Subtitle File:", bg=config.PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(28, 2))
    f2 = tk.Frame(frame_trans, bg=config.PANEL_BG); f2.pack()
    trans_srt_cb = ttk.Combobox(f2, textvariable=trans_srt_var, state="normal", width=38)
    trans_srt_cb.pack(side=tk.LEFT, padx=5)
    tk.Button(f2, text="Browse", command=lambda: browse_srt(trans_srt_var), bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT)
    tk.Label(frame_trans, text="Translate To:", bg=config.PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(18, 2))
    ttk.Combobox(frame_trans, textvariable=trans_lang_var, values=sorted(config.LANGUAGES.keys()), state="readonly", width=40).pack()
    tk.Checkbutton(frame_trans, text="Write in English Letters (e.g. Manglish, Hinglish)", variable=trans_romanize_var, bg=config.PANEL_BG, fg="#a0a0a0", activebackground=config.PANEL_BG, selectcolor=config.DARK_BG).pack(pady=(5, 0))

    row_trans = tk.Frame(frame_trans, bg=config.PANEL_BG); row_trans.pack(pady=15)
    trans_btn = tk.Button(row_trans, text="🌐 TRANSLATE & APPLY", bg=config.VLC_ORANGE, fg="black", font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=run_translation)
    trans_btn.pack(side=tk.LEFT, ipadx=10, ipady=6)
    tk.Button(row_trans, text="👁 Preview", bg="#2a2a2a", fg=config.VLC_ORANGE, relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=8, pady=6, command=lambda: show_srt_preview(app, clean_path(trans_srt_var.get()), "👁 Preview — Subtitle File")).pack(side=tk.LEFT, padx=(6, 0))
    tk.Button(row_trans, text="▶ VLC Preview", bg="#2a2a2a", fg="#4CAF50", relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=8, pady=6, command=lambda: launch_vlc_preview(clean_path(gen_video_var.get()), clean_path(trans_srt_var.get()))).pack(side=tk.LEFT, padx=(6, 0))
    tk.Label(frame_trans, text="Supports 60+ languages  •  Long texts auto-chunked", bg=config.PANEL_BG, fg="#555", font=("Segoe UI", 8)).pack()

    # Tab 3
    tk.Label(frame_sync, text="Select Subtitle File:", bg=config.PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(12, 2))
    f3 = tk.Frame(frame_sync, bg=config.PANEL_BG); f3.pack()
    sync_srt_cb = ttk.Combobox(f3, textvariable=sync_srt_var, state="normal", width=38); sync_srt_cb.pack(side=tk.LEFT, padx=5)
    tk.Button(f3, text="Browse", command=lambda: browse_srt(sync_srt_var), bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT)

    af = tk.Frame(frame_sync, bg="#252525"); af.pack(fill=tk.X, padx=15, pady=(10, 5))
    tk.Label(af, text="🤖  AUTO-SYNC", bg="#252525", fg=config.VLC_ORANGE, font=("Segoe UI", 9, "bold")).pack(pady=(8, 2))
    tk.Label(af, text="Analyses your video audio to detect first speech\nand calculates the perfect offset automatically.", bg="#252525", fg="#999", font=("Segoe UI", 8), justify="center").pack()
    auto_sync_btn = tk.Button(af, text="🔍 Auto Detect Offset", bg="#444", fg="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, command=run_auto_sync)
    auto_sync_btn.pack(pady=(6, 10), ipadx=10, ipady=4)

    tk.Label(frame_sync, text="── or set offset manually ──", bg=config.PANEL_BG, fg="#444", font=("Segoe UI", 8)).pack(pady=(2, 0))
    tk.Label(frame_sync, text="Shift Seconds:", bg=config.PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(6, 2))
    tk.Label(frame_sync, text="+2.5 = delay  •  -1.5 = advance", bg=config.PANEL_BG, fg="#777", font=("Segoe UI", 8)).pack()
    tk.Entry(frame_sync, textvariable=sync_offset_var, width=12, bg=config.DARK_BG, fg="white", border=0, justify="center", font=("Segoe UI", 13, "bold")).pack(pady=4, ipady=3)

    row_sync = tk.Frame(frame_sync, bg=config.PANEL_BG); row_sync.pack(pady=10)
    sync_btn = tk.Button(row_sync, text="⏱️ SYNC & APPLY", bg=config.VLC_ORANGE, fg="black", font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=run_sync)
    sync_btn.pack(side=tk.LEFT, ipadx=10, ipady=6)
    tk.Button(row_sync, text="👁 Preview", bg="#2a2a2a", fg=config.VLC_ORANGE, relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=8, pady=6, command=lambda: show_srt_preview(app, clean_path(sync_srt_var.get()), "👁 Preview — Sync File")).pack(side=tk.LEFT, padx=(6, 0))
    tk.Button(row_sync, text="▶ VLC Preview", bg="#2a2a2a", fg="#4CAF50", relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=8, pady=6, command=lambda: launch_vlc_preview(clean_path(gen_video_var.get()), clean_path(sync_srt_var.get()))).pack(side=tk.LEFT, padx=(6, 0))

    # Tab 4
    tk.Label(frame_custom, text="Select SRT File to Style:", bg=config.PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(10, 2))
    f4 = tk.Frame(frame_custom, bg=config.PANEL_BG); f4.pack()
    custom_srt_cb = ttk.Combobox(f4, textvariable=custom_srt_var, state="normal", width=34); custom_srt_cb.pack(side=tk.LEFT, padx=5)
    tk.Button(f4, text="Browse", command=lambda: browse_srt(custom_srt_var), bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT)

    # --- Style Template Row ---
    tmpl_frame = tk.Frame(frame_custom, bg=config.PANEL_BG); tmpl_frame.pack(fill=tk.X, padx=12, pady=(2, 0))
    tk.Label(tmpl_frame, text="Style Template:", bg=config.PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 6))
    template_var = tk.StringVar(value="Default (White + Outline)")
    tmpl_cb = ttk.Combobox(tmpl_frame, textvariable=template_var, values=list(config.STYLE_TEMPLATES.keys()), state="readonly", width=24)
    tmpl_cb.pack(side=tk.LEFT)

    def apply_template(*_):
        tmpl = config.STYLE_TEMPLATES.get(template_var.get())
        if not tmpl: return
        custom_font_var.set(tmpl["font_name"])
        custom_size_var.set(tmpl["font_size"])
        custom_text_color_var.set(tmpl["primary_color"])
        custom_outline_color_var.set(tmpl["outline_color"])
        custom_bg_var.set(tmpl["background"])
        custom_bold_var.set(tmpl["bold"])
        custom_italic_var.set(tmpl["italic"])
        custom_outline_sz_var.set(tmpl["outline"])
        custom_shadow_var.set(tmpl["shadow"])
        custom_position_var.set(tmpl["position"])
        # Refresh color buttons
        try:
            text_color_btn.config(bg=tmpl["primary_color"])
            outline_color_btn.config(bg=tmpl["outline_color"])
        except Exception:
            pass

    tmpl_cb.bind("<<ComboboxSelected>>", apply_template)
    tk.Button(tmpl_frame, text="▶ Apply", bg=config.VLC_ORANGE, fg="black", relief=tk.FLAT,
              font=("Segoe UI", 8, "bold"), command=apply_template).pack(side=tk.LEFT, padx=(5, 0))

    opts = tk.Frame(frame_custom, bg=config.PANEL_BG); opts.pack(fill=tk.X, padx=12, pady=6)
    L = tk.Frame(opts, bg=config.PANEL_BG); L.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
    R = tk.Frame(opts, bg=config.PANEL_BG); R.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    tk.Label(L, text="Font Family:", bg=config.PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
    ttk.Combobox(L, textvariable=custom_font_var, values=config.COMMON_FONTS, state="normal", width=21).pack(anchor="w", pady=(0, 7))
    tk.Label(L, text="Font Size:", bg=config.PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
    sf = tk.Frame(L, bg=config.PANEL_BG); sf.pack(anchor="w", pady=(0, 7))
    size_disp = tk.Label(sf, text=str(custom_size_var.get()), bg=config.PANEL_BG, fg=config.VLC_ORANGE, width=3, font=("Segoe UI", 9, "bold"))
    custom_size_var.trace_add("write", lambda *a: size_disp.config(text=str(custom_size_var.get())))
    tk.Scale(sf, from_=12, to=48, orient=tk.HORIZONTAL, variable=custom_size_var, bg=config.PANEL_BG, fg="white", highlightthickness=0, troughcolor="#333", activebackground=config.VLC_ORANGE, length=115, showvalue=False).pack(side=tk.LEFT)
    size_disp.pack(side=tk.LEFT, padx=4)

    tk.Label(L, text="Text Color:", bg=config.PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
    text_color_btn = tk.Button(L, text="  ■  Pick Color", bg=custom_text_color_var.get(), fg="black", relief=tk.FLAT, font=("Segoe UI", 8), command=lambda: pick_color(custom_text_color_var, text_color_btn)); text_color_btn.pack(anchor="w", pady=(0, 6))
    tk.Label(L, text="Outline Color:", bg=config.PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
    outline_color_btn = tk.Button(L, text="  ■  Pick Color", bg=custom_outline_color_var.get(), fg="white", relief=tk.FLAT, font=("Segoe UI", 8), command=lambda: pick_color(custom_outline_color_var, outline_color_btn)); outline_color_btn.pack(anchor="w", pady=(0, 4))

    tk.Label(R, text="Style:", bg=config.PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
    for txt, var in [("Bold", custom_bold_var), ("Italic", custom_italic_var), ("Shadow Box", custom_bg_var)]:
        tk.Checkbutton(R, text=txt, variable=var, bg=config.PANEL_BG, fg="white", activebackground=config.PANEL_BG, selectcolor=config.DARK_BG, font=("Segoe UI", 9)).pack(anchor="w")
    tk.Label(R, text="Position:", bg=config.PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w", pady=(6, 0))
    for txt, val in [("⬇ Bottom (Default)", "bottom"), ("⬆ Top", "top")]:
        tk.Radiobutton(R, text=txt, variable=custom_position_var, value=val, bg=config.PANEL_BG, fg="white", activebackground=config.PANEL_BG, selectcolor=config.DARK_BG, font=("Segoe UI", 9)).pack(anchor="w")
    tk.Label(R, text="Outline Size (0–4):", bg=config.PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w", pady=(5, 0))
    tk.Scale(R, from_=0, to=4, orient=tk.HORIZONTAL, variable=custom_outline_sz_var, bg=config.PANEL_BG, fg="white", highlightthickness=0, troughcolor="#333", activebackground=config.VLC_ORANGE, length=130).pack(anchor="w")
    tk.Label(R, text="Shadow Size (0–3):", bg=config.PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
    tk.Scale(R, from_=0, to=3, orient=tk.HORIZONTAL, variable=custom_shadow_var, bg=config.PANEL_BG, fg="white", highlightthickness=0, troughcolor="#333", activebackground=config.VLC_ORANGE, length=130).pack(anchor="w")

    def preview_ass_in_vlc():
        srt_path = clean_path(custom_srt_var.get().strip())
        if not srt_path: return messagebox.showerror("Error", "No file selected!")
        base = os.path.splitext(os.path.basename(srt_path))[0]
        ass_path = clean_path(os.path.join(config.SUB_DIR, f"{base}_styled.ass"))
        if os.path.exists(ass_path):
            launch_vlc_preview(clean_path(gen_video_var.get()), ass_path)
        else:
            messagebox.showerror("Not Found", "Please click '🎨 EXPORT' first to generate the styled .ass file before previewing.")

    row_custom = tk.Frame(frame_custom, bg=config.PANEL_BG); row_custom.pack(pady=(8, 3))
    export_ass_btn = tk.Button(row_custom, text="🎨 EXPORT", bg=config.VLC_ORANGE, fg="black", font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=run_export_ass); export_ass_btn.pack(side=tk.LEFT, ipadx=8, ipady=6)
    tk.Button(row_custom, text="👁 SRT", bg="#2a2a2a", fg=config.VLC_ORANGE, relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=6, pady=6, command=lambda: show_srt_preview(app, clean_path(custom_srt_var.get()), "👁 Preview")).pack(side=tk.LEFT, padx=(3, 0))
    tk.Button(row_custom, text="🖥 Style", bg="#1a2a1a", fg="#4CAF50", relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=6, pady=6, command=lambda: show_style_preview(app, style_vars)).pack(side=tk.LEFT, padx=(3, 0))
    tk.Button(row_custom, text="▶ VLC", bg="#2a2a2a", fg="#4CAF50", relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=6, pady=6, command=preview_ass_in_vlc).pack(side=tk.LEFT, padx=(3, 0))
    burn_btn = tk.Button(row_custom, text="🔥 Burn Into Video", bg="#3a1a1a", fg="#ff6b4a", relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=6, pady=6, command=run_burn_to_video); burn_btn.pack(side=tk.LEFT, padx=(3, 0))
    tk.Label(frame_custom, text="ASS format = full styling in VLC  |  Burn Into Video = permanently embedded, hardcoded subtitles", bg=config.PANEL_BG, fg="#555", font=("Segoe UI", 8)).pack()

    bot = tk.Frame(app, bg=config.DARK_BG); bot.pack(fill=tk.X, padx=20, pady=(0, 10))

    # Stage row: current operation name  +  Stop button  +  result badge
    stage_row = tk.Frame(bot, bg=config.DARK_BG); stage_row.pack(fill=tk.X, pady=(2, 0))
    stage_label = tk.Label(stage_row, text="", bg=config.DARK_BG, fg="#555",
                           font=("Segoe UI", 8, "bold"), anchor="w")
    stage_label.pack(side=tk.LEFT)

    # Stop button — created here but NOT packed (set_busy shows/hides it dynamically)
    stop_btn = tk.Button(stage_row, text="⏹ Stop", bg="#8B0000", fg="white",
                         font=("Segoe UI", 8, "bold"), relief=tk.FLAT,
                         command=_request_stop, padx=6)
    # Note: stop_btn is intentionally not packed here; set_busy() packs/forgets it

    # Progress bar — stored as `progress_bar` so set_progress_indeterminate() can control it
    progress_bar = ttk.Progressbar(bot, variable=progress_var, maximum=100, length=520,
                                   mode="determinate", style="Orange.Horizontal.TProgressbar")
    progress_bar.pack(pady=(3, 0))

    # Detail row: x/total items (pct%)
    progress_label = tk.Label(bot, text="", bg=config.DARK_BG, fg=config.VLC_ORANGE,
                              font=("Segoe UI", 8)); progress_label.pack()

    # Status line
    status_label = tk.Label(bot, text="Status: Ready — select a video and click ⚡ GENERATE AI",
                            bg=config.DARK_BG, fg="#888", font=("Segoe UI", 9),
                            wraplength=520, justify="left")
    status_label.pack()

    if len(sys.argv) > 1:
        passed = sys.argv[1]

        if passed.startswith("universalsubtitles://") or (len(sys.argv) > 2 and sys.argv[1] == "--uri"):
            from urllib.parse import urlparse, parse_qs, unquote
            uri = passed if passed.startswith("universalsubtitles://") else sys.argv[2]
            uri = uri.strip('"').rstrip('/')
            parsed = urlparse(uri)
            params = parse_qs(parsed.query)
            video = unquote(params.get("video", [""])[0])
            if video and os.path.isfile(video):
                gen_video_var.set(clean_path(video))
        else:
            passed = clean_path(passed)
            if os.path.isfile(passed):
                if passed.lower().endswith('.srt'):
                    populate_all_tabs(passed)
                    vm = detect_paired_file(passed, "video")
                    if vm: gen_video_var.set(vm)
                else: gen_video_var.set(passed)

    show_tab(0)
    _pump_ui()      # start thread-safe UI queue pump
    app.mainloop()


################################################################################