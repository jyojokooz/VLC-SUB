import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import subprocess
import os
import requests
import threading
import math
import shutil
import concurrent.futures
import re
import time
import sys
from deep_translator import GoogleTranslator

# ============================================================
# CONFIGURATION
# ============================================================
MAX_TRANSLATION_WORKERS = 8
MAX_CHARS_PER_CHUNK = 3000
VLC_ORANGE = "#ff8c00"
DARK_BG = "#121212"
PANEL_BG = "#1e1e1e"

# ============================================================
# DIRECTORY SETUP
# ============================================================
try:
    if os.name == 'nt' and os.getenv('APPDATA'):
        BASE_DIR = os.path.join(os.getenv('APPDATA'), 'UniversalSubtitles')
    else:
        BASE_DIR = os.path.join(os.path.expanduser('~'), 'Documents', 'UniversalSubtitles')
    TEMP_DIR = os.path.join(BASE_DIR, "temp_audio")
    SUB_DIR  = os.path.join(BASE_DIR, "subtitles")
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(SUB_DIR,  exist_ok=True)
except Exception:
    TEMP_DIR = os.path.join(os.getcwd(), "temp_audio")
    SUB_DIR  = os.path.join(os.getcwd(), "subtitles")
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(SUB_DIR,  exist_ok=True)

# ============================================================
# LANGUAGE DICTIONARIES
# ============================================================
LANGUAGES = {
    "Afrikaans": "af", "Albanian": "sq", "Amharic": "am", "Arabic": "ar",
    "Armenian": "hy", "Azerbaijani": "az", "Basque": "eu", "Belarusian": "be",
    "Bengali": "bn", "Bosnian": "bs", "Bulgarian": "bg", "Catalan": "ca",
    "Cebuano": "ceb", "Chinese (Simplified)": "zh-CN", "Chinese (Traditional)": "zh-TW",
    "Croatian": "hr", "Czech": "cs", "Danish": "da", "Dutch": "nl", "English": "en",
    "Estonian": "et", "Filipino": "tl", "Finnish": "fi", "French": "fr", "Georgian": "ka",
    "German": "de", "Greek": "el", "Gujarati": "gu", "Hebrew": "he", "Hindi": "hi",
    "Hungarian": "hu", "Icelandic": "is", "Indonesian": "id", "Irish": "ga", "Italian": "it",
    "Japanese": "ja", "Javanese": "jv", "Kannada": "kn", "Kazakh": "kk", "Khmer": "km",
    "Korean": "ko", "Latin": "la", "Latvian": "lv", "Lithuanian": "lt", "Macedonian": "mk",
    "Malay": "ms", "Malayalam": "ml", "Marathi": "mr", "Mongolian": "mn", "Nepali": "ne",
    "Norwegian": "no", "Persian": "fa", "Polish": "pl", "Portuguese": "pt", "Punjabi": "pa",
    "Romanian": "ro", "Russian": "ru", "Serbian": "sr", "Sinhala": "si", "Slovak": "sk",
    "Slovenian": "sl", "Spanish": "es", "Swahili": "sw", "Swedish": "sv", "Tamil": "ta",
    "Telugu": "te", "Thai": "th", "Turkish": "tr", "Ukrainian": "uk", "Urdu": "ur",
    "Vietnamese": "vi", "Welsh": "cy"
}

# Whisper supports these; None = auto-detect (best choice)
WHISPER_LANGUAGES = {
    "Auto Detect (Recommended)": None,
    "Afrikaans": "af", "Arabic": "ar", "Armenian": "hy", "Azerbaijani": "az",
    "Belarusian": "be", "Bosnian": "bs", "Bulgarian": "bg", "Catalan": "ca",
    "Chinese": "zh", "Croatian": "hr", "Czech": "cs", "Danish": "da",
    "Dutch": "nl", "English": "en", "Estonian": "et", "Finnish": "fi",
    "French": "fr", "Galician": "gl", "German": "de", "Greek": "el",
    "Hebrew": "he", "Hindi": "hi", "Hungarian": "hu", "Icelandic": "is",
    "Indonesian": "id", "Italian": "it", "Japanese": "ja", "Kannada": "kn",
    "Kazakh": "kk", "Korean": "ko", "Latvian": "lv", "Lithuanian": "lt",
    "Macedonian": "mk", "Malay": "ms", "Malayalam": "ml", "Marathi": "mr",
    "Maori": "mi", "Nepali": "ne", "Norwegian": "no", "Persian": "fa",
    "Polish": "pl", "Portuguese": "pt", "Romanian": "ro", "Russian": "ru",
    "Serbian": "sr", "Slovak": "sk", "Slovenian": "sl", "Spanish": "es",
    "Swahili": "sw", "Swedish": "sv", "Tagalog": "tl", "Tamil": "ta",
    "Telugu": "te", "Thai": "th", "Turkish": "tr", "Ukrainian": "uk",
    "Urdu": "ur", "Vietnamese": "vi", "Welsh": "cy", "Yoruba": "yo"
}

COMMON_FONTS = [
    "Arial", "Segoe UI", "Calibri", "Verdana", "Tahoma", "Trebuchet MS",
    "Times New Roman", "Georgia", "Courier New", "Impact", "Comic Sans MS",
    "Helvetica Neue", "Open Sans", "Roboto", "Ubuntu"
]

# ============================================================
# GLOBAL WIDGET REFERENCES (assigned later in UI section)
# ============================================================
app = None
gen_btn = trans_btn = sync_btn = auto_sync_btn = export_ass_btn = None
trans_srt_cb = sync_srt_cb = custom_srt_cb = None
status_label = progress_var = progress_label = None
text_color_btn = outline_color_btn = None

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def format_timestamp(seconds):
    seconds = max(0, seconds)
    h  = math.floor(seconds / 3600)
    m  = math.floor((seconds % 3600) / 60)
    s  = math.floor(seconds % 60)
    ms = math.floor((seconds - math.floor(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def format_ass_timestamp(seconds):
    """SRT → ASS timestamp (H:MM:SS.cc centiseconds)."""
    seconds = max(0, seconds)
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100: cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def time_to_sec(t_str):
    t_str = t_str.replace('.', ',')
    if ',' not in t_str: t_str += ',000'
    h, m, s_ms = t_str.split(':')
    s, ms = s_ms.split(',')
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0

def clean_path(path):
    if not path: return ""
    return os.path.normpath(path.replace("\\\\", "\\").replace("//", "/"))

def detect_paired_file(filepath, file_type):
    if not filepath: return ""
    base = os.path.splitext(filepath)[0]
    if file_type == "video":
        for ext in ['.mp4', '.mkv', '.avi', '.ts', '.mov', '.wmv']:
            if os.path.exists(base + ext): return base + ext
    elif file_type == "srt":
        if os.path.exists(base + ".srt"): return base + ".srt"
    return ""

def get_available_subtitles(video_path):
    subs = []
    if video_path and os.path.exists(video_path):
        v_dir = os.path.dirname(video_path)
        if os.path.exists(v_dir):
            for f in os.listdir(v_dir):
                if f.lower().endswith(('.srt', '.ass')):
                    subs.append(os.path.normpath(os.path.join(v_dir, f)))
    if os.path.exists(SUB_DIR):
        for f in os.listdir(SUB_DIR):
            if f.lower().endswith(('.srt', '.ass')):
                subs.append(os.path.normpath(os.path.join(SUB_DIR, f)))
    return list(dict.fromkeys(subs))

def update_status(text):
    if app and status_label:
        app.after(0, lambda: status_label.config(text=f"Status: {text}"))

def update_progress(done, total, label=""):
    pct = int((done / total) * 100) if total > 0 else 0
    if app and progress_var:  app.after(0, lambda: progress_var.set(pct))
    if label and app and progress_label:
        app.after(0, lambda: progress_label.config(text=f"{done}/{total} {label}"))

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ============================================================
# SRT PARSER
# ============================================================
def parse_srt(filepath):
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    blocks  = re.split(r'\n\s*\n', content.strip())
    parsed  = []
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            times = lines[1].split(' --> ')
            if len(times) == 2:
                try:
                    parsed.append({
                        "index": lines[0].strip(),
                        "start": time_to_sec(times[0].strip()),
                        "end":   time_to_sec(times[1].strip()),
                        "text":  '\n'.join(lines[2:]).strip()
                    })
                except Exception:
                    pass
    return parsed

# ============================================================
# TRANSLATION ENGINE  — FIXED: proper text chunking
# ============================================================
def split_text_for_translation(text, max_chars=3000):
    """Split long text into sentence-boundary chunks to stay under API limits."""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, current = [], ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current: chunks.append(current)
            if len(sentence) > max_chars:
                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i:i + max_chars])
                current = ""
            else:
                current = sentence
    if current: chunks.append(current)
    return chunks if chunks else [text]

def translate_single_chunk(text, target_code, romanize=False):
    """Translate one chunk with retry logic."""
    for _ in range(3):
        try:
            if not romanize:
                res = GoogleTranslator(source='auto', target=target_code).translate(text)
                if res: return res
            else:
                url    = "https://translate.googleapis.com/translate_a/single"
                params = {"client": "gtx", "sl": "auto", "tl": target_code,
                          "dt": ["t", "rm"], "q": text}
                resp   = requests.get(url, params=params, timeout=15)
                if resp.status_code == 200:
                    data     = resp.json()
                    romanized = "".join(p[2] for p in data[0] if len(p) > 2 and p[2])
                    normal    = "".join(p[0] for p in data[0] if p[0])
                    return romanized.strip() or normal.strip() or text
        except Exception:
            time.sleep(1.5)
    return text

def translate_text(eng_text, target_code, romanize=False):
    if target_code == "en" or not eng_text.strip():
        return eng_text
    chunks = split_text_for_translation(eng_text, MAX_CHARS_PER_CHUNK)
    return " ".join(translate_single_chunk(c, target_code, romanize) for c in chunks)

# ============================================================
# TRANSCRIPTION  — FIXED: language no longer hardcoded to English
# ============================================================
def transcribe_audio_chunk(chunk_path, provider, api_key, source_lang=None):
    """
    source_lang=None  → Whisper auto-detects the spoken language (best for non-English).
    source_lang='en'  → Force English transcription.
    """
    url   = ("https://api.groq.com/openai/v1/audio/transcriptions"
              if "Groq" in provider
              else "https://api.openai.com/v1/audio/transcriptions")
    model = "whisper-large-v3" if "Groq" in provider else "whisper-1"

    data = {"model": model, "response_format": "verbose_json"}
    if source_lang:          # only pass language when explicitly set; None = auto
        data["language"] = source_lang

    with open(chunk_path, "rb") as f:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (os.path.basename(chunk_path), f, "audio/mp4")},
            data=data,
            timeout=300
        )
    if response.status_code != 200:
        raise Exception(f"API Error {response.status_code}:\n{response.text[:400]}")
    return response.json()

# ============================================================
# AUTO SYNC  — NEW: FFmpeg speech-detection
# ============================================================
def detect_sync_offset(video_path, srt_path):
    """
    Use FFmpeg silencedetect to find the first speech moment in the video,
    then compare against the first subtitle timestamp to compute the offset.
    """
    segments = parse_srt(srt_path)
    if not segments:
        return None, "No subtitles found in file."

    first_sub_time = segments[0]['start']
    update_status("Analyzing audio for auto-sync (may take ~30s)...")

    try:
        cf  = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        cmd = [
            "ffmpeg", "-i", video_path,
            "-t", "300",                          # analyse first 5 min only
            "-af", "silencedetect=noise=-35dB:d=0.3",
            "-f", "null", "-"
        ]
        result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                                creationflags=cf, timeout=120)
        stderr = result.stderr.decode('utf-8', errors='ignore')

        # silence_end marks when silence stops → speech starts
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
# ASS SUBTITLE GENERATION  — NEW
# ============================================================
def hex_to_ass_color(hex_color, alpha=0):
    """Convert #RRGGBB → ASS &HAABBGGRR format."""
    hx = hex_color.lstrip('#')
    if len(hx) == 3: hx = ''.join(c*2 for c in hx)
    r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

def generate_ass_content(segments, style):
    primary   = hex_to_ass_color(style['primary_color'])
    outline_c = hex_to_ass_color(style['outline_color'])
    bg_alpha  = 0x60 if style['background'] else 0xFF
    back      = hex_to_ass_color("#000000", alpha=bg_alpha)
    bold      = -1 if style['bold']   else 0
    italic    = -1 if style['italic'] else 0

    header = (
        "[Script Info]\n"
        "; Generated by Universal Subtitle Toolkit (VLC Edition)\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style['font_name']},{style['font_size']},"
        f"{primary},&H000000FF,{outline_c},{back},"
        f"{bold},{italic},0,0,100,100,0,0,1,"
        f"{style['outline']},{style['shadow']},{style['alignment']},10,10,10,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events = ""
    for seg in segments:
        text = seg['text'].replace('\n', '\\N').strip()
        if text:
            events += (
                f"Dialogue: 0,"
                f"{format_ass_timestamp(seg['start'])},"
                f"{format_ass_timestamp(seg['end'])},"
                f"Default,,0,0,0,,{text}\n"
            )
    return header + events

# ============================================================
# VLC HELPER
# ============================================================
def apply_subtitle_to_vlc(subtitle_path, success_message):
    try:
        if os.name == 'nt':
            subprocess.Popen(f'explorer /select,"{clean_path(subtitle_path)}"')
    except Exception:
        pass
    app.after(0, lambda: messagebox.showinfo(
        "✅ Success",
        f"{success_message}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 TO APPLY IN VLC:\n"
        "The file is highlighted in Explorer.\n"
        "DRAG & DROP it into your VLC window!"
    ))

def populate_all_tabs(srt_path):
    """Set the SRT path in Translate, Sync, and Customize tabs (thread-safe)."""
    app.after(0, lambda: trans_srt_var.set(srt_path))
    app.after(0, lambda: sync_srt_var.set(srt_path))
    app.after(0, lambda: custom_srt_var.set(srt_path))

# ============================================================
# WORKFLOW: GENERATE (Tab 1)
# ============================================================
def run_generation():
    video_path       = clean_path(gen_video_var.get().strip())
    target_lang      = gen_lang_var.get()
    api_key          = api_key_var.get().strip()
    provider         = provider_var.get()
    romanize         = gen_romanize_var.get()
    source_lang_name = gen_source_lang_var.get()
    source_lang_code = WHISPER_LANGUAGES.get(source_lang_name)  # None → auto-detect

    if not video_path:          return messagebox.showerror("Error", "Please select a video file!")
    if not os.path.exists(video_path): return messagebox.showerror("Error", "Video file not found!")
    if not api_key:             return messagebox.showerror("Error", "Please enter your API Key!")

    def _task():
        try:
            app.after(0, lambda: gen_btn.config(state=tk.DISABLED))
            # Clear temp directory
            if os.path.exists(TEMP_DIR):
                for fn in os.listdir(TEMP_DIR):
                    try: os.remove(os.path.join(TEMP_DIR, fn))
                    except: pass

            update_status("Compressing audio for AI (Wait ~15s)...")
            chunk_pattern = os.path.join(TEMP_DIR, "chunk_%03d.m4a")
            cf  = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            cmd = ["ffmpeg", "-y", "-i", video_path, "-vn", "-c:a", "aac", "-b:a", "64k",
                   "-ar", "16000", "-ac", "1", "-af", "loudnorm", "-f", "segment",
                   "-segment_time", "600", chunk_pattern]

            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=cf)
            if proc.returncode != 0:
                err = proc.stderr.decode('utf-8', errors='ignore')
                raise Exception(f"FFmpeg failed. Is the file a valid video?\n\n{err[-400:]}")

            chunks = sorted([f for f in os.listdir(TEMP_DIR) if f.endswith('.m4a')])
            if not chunks:
                raise Exception("No audio chunks extracted — the video may have no audio track.")

            all_segments = []
            for i, chunk in enumerate(chunks):
                lang_info = f" ({source_lang_name})" if source_lang_code else " (Auto-Detect)"
                update_status(f"Transcribing Part {i+1}/{len(chunks)}{lang_info}...")
                update_progress(i, len(chunks), "parts")

                ai_data = transcribe_audio_chunk(
                    os.path.join(TEMP_DIR, chunk), provider, api_key, source_lang_code
                )
                offset = i * 600
                for seg in ai_data.get("segments", []):
                    text = seg["text"].strip()
                    if text:
                        all_segments.append({
                            "start": seg["start"] + offset,
                            "end":   seg["end"]   + offset,
                            "text":  text
                        })

            if not all_segments:
                raise Exception(
                    "No speech detected.\n"
                    "Try selecting the correct Source Language or check audio quality."
                )

            target_code = LANGUAGES.get(target_lang, "en")
            if target_code != "en":
                mode = "Manglish/Hinglish" if romanize else "Native Script"
                update_status(f"Translating {len(all_segments)} lines ({mode})...")
                completed = 0

                def do_trans(seg):
                    seg["text"] = translate_text(seg["text"], target_code, romanize)
                    return seg

                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_TRANSLATION_WORKERS) as exe:
                    futures = [exe.submit(do_trans, seg) for seg in all_segments]
                    for _ in concurrent.futures.as_completed(futures):
                        completed += 1
                        update_progress(completed, len(all_segments), "lines")

            srt_content = "".join(
                f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                for i, s in enumerate(all_segments) if s['text']
            )
            suffix   = f"_{target_lang}_Romanized" if romanize else f"_{target_lang}"
            srt_name = f"{os.path.splitext(os.path.basename(video_path))[0]}{suffix}.srt"
            srt_path = clean_path(os.path.join(SUB_DIR, srt_name))

            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            for fn in os.listdir(TEMP_DIR):
                try: os.remove(os.path.join(TEMP_DIR, fn))
                except: pass

            update_status(f"✅ Done! {len(all_segments)} subtitle lines generated.")
            update_progress(100, 100, "%")
            populate_all_tabs(srt_path)
            apply_subtitle_to_vlc(srt_path, f"✅ Subtitles Generated!\n{len(all_segments)} lines | {target_lang}")

        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Generation Error", str(e)))
            update_status("Error occurred.")
        finally:
            app.after(0, lambda: gen_btn.config(state=tk.NORMAL))

    threading.Thread(target=_task, daemon=True).start()

# ============================================================
# WORKFLOW: TRANSLATE (Tab 2)
# ============================================================
def run_translation():
    srt_path    = clean_path(trans_srt_var.get().strip())
    target_lang = trans_lang_var.get()
    romanize    = trans_romanize_var.get()

    if not srt_path:                    return messagebox.showerror("Error", "Please select an SRT file!")
    if not os.path.exists(srt_path):    return messagebox.showerror("Error", f"File not found:\n{srt_path}")

    def _task():
        try:
            app.after(0, lambda: trans_btn.config(state=tk.DISABLED))
            update_status("Parsing SRT file...")
            segments = parse_srt(srt_path)
            if not segments:
                raise Exception("Could not parse the SRT file. Check if it is a valid .srt format.")

            target_code = LANGUAGES.get(target_lang, "en")
            errors = 0

            if target_code != "en":
                mode = "Manglish/Hinglish" if romanize else "Native Script"
                update_status(f"Translating {len(segments)} lines to {target_lang} ({mode})...")
                completed = 0

                def do_trans(seg):
                    nonlocal errors
                    try:
                        seg["text"] = translate_text(seg["text"], target_code, romanize)
                    except Exception:
                        errors += 1
                    return seg

                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_TRANSLATION_WORKERS) as exe:
                    futures = [exe.submit(do_trans, seg) for seg in segments]
                    for _ in concurrent.futures.as_completed(futures):
                        completed += 1
                        update_progress(completed, len(segments), "lines")

            srt_content = "".join(
                f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                for i, s in enumerate(segments)
            )
            base      = os.path.splitext(os.path.basename(srt_path))[0]
            suffix    = f"_{target_lang}_Romanized" if romanize else f"_{target_lang}"
            save_path = clean_path(os.path.join(SUB_DIR, f"{base}{suffix}.srt"))

            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            note = f"\n⚠️ {errors} lines kept original (translation error)" if errors else ""
            update_status(f"✅ Translation Done!{' (with ' + str(errors) + ' errors)' if errors else ''}")
            update_progress(100, 100, "%")
            populate_all_tabs(save_path)
            apply_subtitle_to_vlc(save_path, f"✅ Translation Finished!\n{len(segments)} lines → {target_lang}{note}")

        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Translation Error", str(e)))
            update_status("Error occurred.")
        finally:
            app.after(0, lambda: trans_btn.config(state=tk.NORMAL))

    threading.Thread(target=_task, daemon=True).start()

# ============================================================
# WORKFLOW: AUTO-SYNC (Tab 3)
# ============================================================
def run_auto_sync():
    srt_path   = clean_path(sync_srt_var.get().strip())
    video_path = clean_path(gen_video_var.get().strip())

    if not srt_path:                    return messagebox.showerror("Error", "Please select an SRT file!")
    if not video_path:                  return messagebox.showerror("Error", "Please select a video in Tab 1 first!")
    if not os.path.exists(srt_path):    return messagebox.showerror("Error", "SRT file not found!")
    if not os.path.exists(video_path):  return messagebox.showerror("Error", "Video file not found!")

    def _task():
        try:
            app.after(0, lambda: auto_sync_btn.config(state=tk.DISABLED, text="Analyzing..."))
            offset, info = detect_sync_offset(video_path, srt_path)

            if offset is None:
                app.after(0, lambda: messagebox.showerror("Auto-Sync Failed", info))
                update_status("Auto-sync failed.")
                return

            offset_str = f"{offset:+.2f}"
            app.after(0, lambda: sync_offset_var.set(offset_str))
            update_status(f"✅ Auto-detected offset: {offset_str}s")
            app.after(0, lambda: messagebox.showinfo(
                "🎯 Auto-Sync Result",
                f"Detected Offset:  {offset_str} seconds\n\n{info}\n\n"
                "The offset has been pre-filled.\n"
                "Click  'SYNC & APPLY'  to apply it!"
            ))
        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Error", str(e)))
            update_status("Error.")
        finally:
            app.after(0, lambda: auto_sync_btn.config(state=tk.NORMAL, text="🔍 Auto Detect Offset"))

    threading.Thread(target=_task, daemon=True).start()

# ============================================================
# WORKFLOW: MANUAL SYNC (Tab 3)
# ============================================================
def run_sync():
    srt_path = clean_path(sync_srt_var.get().strip())
    try:
        offset_val = float(sync_offset_var.get().strip().replace('+', ''))
    except ValueError:
        return messagebox.showerror("Error", "Offset must be a number  (e.g. 2.5 or -1.5)")

    if not srt_path:                  return messagebox.showerror("Error", "Please select an SRT file!")
    if not os.path.exists(srt_path):  return messagebox.showerror("Error", "SRT file not found!")

    def _task():
        try:
            app.after(0, lambda: sync_btn.config(state=tk.DISABLED))
            update_status("Adjusting SRT timestamps...")
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
            save_path = clean_path(os.path.join(SUB_DIR, f"{base}_synced.srt"))

            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            update_status(f"✅ Sync done! Offset: {offset_val:+.2f}s")
            update_progress(100, 100, "%")
            populate_all_tabs(save_path)
            apply_subtitle_to_vlc(save_path, f"✅ Sync Applied!\nOffset: {offset_val:+.2f} seconds")

        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Sync Error", str(e)))
            update_status("Error.")
        finally:
            app.after(0, lambda: sync_btn.config(state=tk.NORMAL))

    threading.Thread(target=_task, daemon=True).start()

# ============================================================
# WORKFLOW: EXPORT STYLED ASS (Tab 4)
# ============================================================
def pick_color(var, btn):
    initial = var.get() if var.get().startswith('#') else '#ffffff'
    result  = colorchooser.askcolor(color=initial, title="Pick Color")
    if result and result[1]:
        var.set(result[1])
        btn.config(bg=result[1], fg="white" if result[1].lower() in ['#000000','#111111','#222222','#333333'] else "black")

def run_export_ass():
    srt_path = clean_path(custom_srt_var.get().strip())
    if not srt_path:                  return messagebox.showerror("Error", "Please select an SRT file!")
    if not os.path.exists(srt_path):  return messagebox.showerror("Error", f"File not found:\n{srt_path}")

    def _task():
        try:
            app.after(0, lambda: export_ass_btn.config(state=tk.DISABLED))
            update_status("Generating styled ASS subtitle...")

            segments = parse_srt(srt_path)
            if not segments:
                raise Exception("Could not parse SRT file. Check the file format.")

            style = {
                "font_name":     custom_font_var.get() or "Arial",
                "font_size":     custom_size_var.get(),
                "primary_color": custom_text_color_var.get(),
                "outline_color": custom_outline_color_var.get(),
                "background":    custom_bg_var.get(),
                "bold":          custom_bold_var.get(),
                "italic":        custom_italic_var.get(),
                "outline":       custom_outline_sz_var.get(),
                "shadow":        custom_shadow_var.get(),
                "alignment":     8 if custom_position_var.get() == "top" else 2,
            }

            ass_content = generate_ass_content(segments, style)
            base        = os.path.splitext(os.path.basename(srt_path))[0]
            ass_path    = clean_path(os.path.join(SUB_DIR, f"{base}_styled.ass"))

            with open(ass_path, 'w', encoding='utf-8') as f:
                f.write(ass_content)

            update_status("✅ Styled ASS subtitle exported!")
            update_progress(100, 100, "%")
            apply_subtitle_to_vlc(
                ass_path,
                "✅ Styled Subtitle Exported as .ASS\n\n"
                "VLC fully supports ASS with custom fonts,\n"
                "colors, position & more!"
            )
        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Export Error", str(e)))
            update_status("Error.")
        finally:
            app.after(0, lambda: export_ass_btn.config(state=tk.NORMAL))

    threading.Thread(target=_task, daemon=True).start()

# ============================================================
# PREVIEW FUNCTIONS
# ============================================================
def show_srt_preview(srt_var_getter, title="👁 Subtitle Preview"):
    """Open a scrollable, colour-coded preview of an SRT file."""
    srt_path = clean_path(srt_var_getter())
    if not srt_path:
        return messagebox.showerror("Preview", "No subtitle file selected!")
    if not os.path.exists(srt_path):
        return messagebox.showerror("Preview", f"File not found:\n{srt_path}")
    try:
        segments = parse_srt(srt_path)
    except Exception as e:
        return messagebox.showerror("Preview", f"Could not read file:\n{e}")

    pw = tk.Toplevel(app)
    pw.title(title)
    pw.geometry("620x520")
    pw.configure(bg=DARK_BG)
    pw.transient(app)
    pw.resizable(True, True)

    # ── Header ──
    hf = tk.Frame(pw, bg=DARK_BG); hf.pack(fill=tk.X, padx=15, pady=(10, 4))
    tk.Label(hf, text=os.path.basename(srt_path), bg=DARK_BG, fg=VLC_ORANGE,
             font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
    tk.Label(hf, text=f"  {len(segments)} lines", bg=DARK_BG, fg="#888",
             font=("Segoe UI", 9)).pack(side=tk.LEFT)

    # ── Search bar ──
    sf = tk.Frame(pw, bg=DARK_BG); sf.pack(fill=tk.X, padx=15, pady=(0, 4))
    search_var = tk.StringVar()
    tk.Label(sf, text="Search:", bg=DARK_BG, fg="#888", font=("Segoe UI", 8)).pack(side=tk.LEFT)
    search_entry = tk.Entry(sf, textvariable=search_var, width=28,
                            bg="#2a2a2a", fg="white", insertbackground="white",
                            border=0, font=("Segoe UI", 9))
    search_entry.pack(side=tk.LEFT, padx=5, ipady=2)
    match_label = tk.Label(sf, text="", bg=DARK_BG, fg=VLC_ORANGE, font=("Segoe UI", 8))
    match_label.pack(side=tk.LEFT)

    # ── Text widget ──
    tf = tk.Frame(pw, bg=DARK_BG); tf.pack(fill=tk.BOTH, expand=True, padx=15, pady=4)
    vsb = tk.Scrollbar(tf); vsb.pack(side=tk.RIGHT, fill=tk.Y)
    txt = tk.Text(tf, bg="#0d0d0d", fg="white", font=("Consolas", 9),
                  yscrollcommand=vsb.set, border=0, highlightthickness=0,
                  wrap=tk.WORD, selectbackground=VLC_ORANGE, cursor="arrow")
    txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    vsb.config(command=txt.yview)

    txt.tag_configure("idx",   foreground="#555",     font=("Consolas", 8))
    txt.tag_configure("time",  foreground=VLC_ORANGE, font=("Consolas", 9, "bold"))
    txt.tag_configure("body",  foreground="#e8e8e8",  font=("Consolas", 9))
    txt.tag_configure("sep",   foreground="#252525")
    txt.tag_configure("found", background="#ff8c0055", foreground="white")

    for seg in segments:
        txt.insert(tk.END, f"[{seg['index']}]  ", "idx")
        txt.insert(tk.END,
            f"{format_timestamp(seg['start'])}  →  {format_timestamp(seg['end'])}\n",
            "time")
        txt.insert(tk.END, f"{seg['text']}\n", "body")
        txt.insert(tk.END, "─" * 70 + "\n", "sep")
    txt.config(state=tk.DISABLED)

    # ── Search logic ──
    def do_search(*_):
        txt.tag_remove("found", "1.0", tk.END)
        q = search_var.get().strip()
        if not q:
            match_label.config(text=""); return
        count = 0
        start = "1.0"
        while True:
            pos = txt.search(q, start, nocase=True, stopindex=tk.END)
            if not pos: break
            end = f"{pos}+{len(q)}c"
            txt.tag_add("found", pos, end)
            if count == 0: txt.see(pos)
            count += 1
            start = end
        match_label.config(text=f"{count} match{'es' if count != 1 else ''}")
    search_var.trace_add("write", do_search)
    search_entry.bind("<Return>", do_search)

    # ── Bottom buttons ──
    bf = tk.Frame(pw, bg=DARK_BG); bf.pack(fill=tk.X, padx=15, pady=(4, 10))
    tk.Button(bf, text="📋 Copy All", bg="#333", fg="white", relief=tk.FLAT,
              font=("Segoe UI", 9), padx=8, pady=4,
              command=lambda: (
                  pw.clipboard_clear(),
                  pw.clipboard_append(open(srt_path, encoding='utf-8').read())
              )).pack(side=tk.LEFT, padx=(0, 5))
    tk.Button(bf, text="📝 Open in Notepad", bg="#333", fg="white", relief=tk.FLAT,
              font=("Segoe UI", 9), padx=8, pady=4,
              command=lambda: subprocess.Popen(["notepad", srt_path])).pack(side=tk.LEFT)
    tk.Button(bf, text="Close", bg=VLC_ORANGE, fg="black", relief=tk.FLAT,
              font=("Segoe UI", 9, "bold"), padx=12, pady=4,
              command=pw.destroy).pack(side=tk.RIGHT)


def show_style_preview():
    """Live canvas preview simulating how the subtitle will look on screen."""
    pw = tk.Toplevel(app)
    pw.title("🖥 Live Style Preview")
    pw.geometry("660x420")
    pw.configure(bg=DARK_BG)
    pw.transient(app)
    pw.resizable(False, False)

    tk.Label(pw, text="Live Style Preview", bg=DARK_BG, fg=VLC_ORANGE,
             font=("Segoe UI", 11, "bold")).pack(pady=(10, 4))
    tk.Label(pw, text="Adjust settings in Tab 4 then click Refresh",
             bg=DARK_BG, fg="#555", font=("Segoe UI", 8)).pack(pady=(0, 6))

    CWIDTH, CHEIGHT = 620, 280
    canvas = tk.Canvas(pw, width=CWIDTH, height=CHEIGHT, bg="#000",
                       highlightthickness=2, highlightbackground="#333")
    canvas.pack(padx=20)

    # Retrieve first real subtitle line for preview, or use sample
    def get_preview_text(entry_widget):
        t = entry_widget.get().strip()
        if t: return t
        sp = clean_path(custom_srt_var.get().strip())
        if sp and os.path.exists(sp):
            segs = parse_srt(sp)
            if segs: return segs[0]['text'].replace('\n', ' ')[:60]
        return "Sample Subtitle — Your text appears here"

    def draw(preview_text=""):
        canvas.delete("all")
        # — cinematic background —
        canvas.create_rectangle(0, 0, CWIDTH, CHEIGHT, fill="#08080f", outline="")
        # decorative scan-lines
        for y in range(0, CHEIGHT, 4):
            canvas.create_line(0, y, CWIDTH, y, fill="#0d0d15", width=1)
        # subtle vignette strips
        canvas.create_rectangle(0, 0, CWIDTH, 30, fill="#000000", outline="")
        canvas.create_rectangle(0, CHEIGHT-30, CWIDTH, CHEIGHT, fill="#000000", outline="")
        # fake video content lines
        for i, yl in enumerate([55, 80, 105, 130, 155]):
            shade = "#111128" if i % 2 == 0 else "#0e0e22"
            canvas.create_rectangle(30, yl, CWIDTH-30, yl+16, fill=shade, outline="")

        font_name   = custom_font_var.get() or "Arial"
        font_size   = custom_size_var.get()
        bold_flag   = "bold"   if custom_bold_var.get()   else ""
        italic_flag = "italic" if custom_italic_var.get() else ""
        weight      = " ".join(filter(None, [bold_flag, italic_flag])) or "normal"
        try:
            fnt = (font_name, font_size, weight)
            canvas.create_text(CWIDTH//2, 10, text=fnt[0], fill="#0",
                               font=fnt)  # dry-run to catch bad font
        except Exception:
            fnt = ("Arial", font_size, weight)

        text_col    = custom_text_color_var.get()
        outline_col = custom_outline_color_var.get()
        outline_sz  = custom_outline_sz_var.get()
        shadow_sz   = custom_shadow_var.get()
        pos         = custom_position_var.get()
        display_txt = preview_text or get_preview_text(entry_widget)

        cx = CWIDTH // 2
        cy = 38 if pos == "top" else CHEIGHT - 38

        # shadow box
        if custom_bg_var.get():
            try:
                tw = len(display_txt) * font_size * 0.48
                th = font_size + 12
                canvas.create_rectangle(
                    cx - tw//2 - 10, cy - th//2 - 2,
                    cx + tw//2 + 10, cy + th//2 + 2,
                    fill="#000000", outline="", stipple="gray50"
                )
            except Exception:
                pass

        # shadow glow
        if shadow_sz > 0:
            for d in range(shadow_sz, 0, -1):
                alpha = "#1a1a1a" if d == shadow_sz else "#0d0d0d"
                canvas.create_text(cx + d*2, cy + d*2, text=display_txt,
                                   fill=alpha, font=fnt, anchor="center")

        # outline strokes
        if outline_sz > 0:
            for dx in range(-outline_sz, outline_sz + 1):
                for dy in range(-outline_sz, outline_sz + 1):
                    if abs(dx) + abs(dy) >= outline_sz:
                        canvas.create_text(cx + dx, cy + dy, text=display_txt,
                                           fill=outline_col, font=fnt, anchor="center")

        # main text
        canvas.create_text(cx, cy, text=display_txt,
                           fill=text_col, font=fnt, anchor="center")

        # position indicator
        indicator = "▲ Top" if pos == "top" else "▼ Bottom"
        canvas.create_text(CWIDTH - 8, CHEIGHT - 8, text=indicator,
                           fill="#333", font=("Segoe UI", 7), anchor="se")

    # — controls row —
    ctrl = tk.Frame(pw, bg=DARK_BG); ctrl.pack(fill=tk.X, padx=20, pady=8)
    tk.Label(ctrl, text="Preview text:", bg=DARK_BG, fg="#888",
             font=("Segoe UI", 9)).pack(side=tk.LEFT)
    entry_widget = tk.Entry(ctrl, width=32, bg="#2a2a2a", fg="white",
                            insertbackground="white", border=0, font=("Segoe UI", 9))
    entry_widget.insert(0, "Sample subtitle text – preview here")
    entry_widget.pack(side=tk.LEFT, padx=6, ipady=2)
    tk.Button(ctrl, text="🔄 Refresh", bg="#333", fg="white", relief=tk.FLAT,
              font=("Segoe UI", 9, "bold"), padx=8, pady=3,
              command=lambda: draw(entry_widget.get().strip())).pack(side=tk.LEFT)
    tk.Button(ctrl, text="Use 1st subtitle line", bg="#252525", fg="#aaa",
              relief=tk.FLAT, font=("Segoe UI", 8), padx=6, pady=3,
              command=lambda: [entry_widget.delete(0, tk.END),
                               entry_widget.insert(0, get_preview_text(entry_widget)),
                               draw()]).pack(side=tk.LEFT, padx=4)

    draw()  # initial render

# ============================================================
# DYNAMIC UPDATES
# ============================================================
def on_video_change(*args):
    v_path = gen_video_var.get().strip()
    subs   = get_available_subtitles(v_path)

    if trans_srt_cb:  trans_srt_cb['values']  = subs
    if sync_srt_cb:   sync_srt_cb['values']   = subs
    if custom_srt_cb: custom_srt_cb['values']  = subs

    best = detect_paired_file(v_path, "srt")
    if best:
        trans_srt_var.set(best)
        sync_srt_var.set(best)
        custom_srt_var.set(best)
    elif subs:
        if not trans_srt_var.get():  trans_srt_var.set(subs[0])
        if not sync_srt_var.get():   sync_srt_var.set(subs[0])
        if not custom_srt_var.get(): custom_srt_var.set(subs[0])

def browse_srt(var):
    f = filedialog.askopenfilename(filetypes=[("Subtitles", "*.srt *.ass")])
    if f: var.set(clean_path(f))

def browse_video(var):
    f = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mkv *.avi *.ts *.mov *.wmv")])
    if f: var.set(clean_path(f))

# ============================================================
# HISTORY WINDOW
# ============================================================
def open_history():
    hw = tk.Toplevel(app)
    hw.title("Subtitle History")
    hw.geometry("540x400")
    hw.configure(bg=DARK_BG)
    hw.transient(app)

    tk.Label(hw, text="Generated Subtitles History", bg=DARK_BG, fg=VLC_ORANGE,
             font=("Segoe UI", 12, "bold")).pack(pady=10)

    lf = tk.Frame(hw, bg=DARK_BG)
    lf.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
    sb = tk.Scrollbar(lf)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    lb = tk.Listbox(lf, bg=PANEL_BG, fg="white", yscrollcommand=sb.set,
                    selectbackground=VLC_ORANGE, selectforeground="black",
                    border=0, highlightthickness=1, highlightbackground="#333",
                    font=("Segoe UI", 9))
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.config(command=lb.yview)

    def refresh():
        lb.delete(0, tk.END)
        if os.path.exists(SUB_DIR):
            files = sorted(
                [f for f in os.listdir(SUB_DIR) if f.lower().endswith(('.srt', '.ass'))],
                key=lambda x: os.path.getmtime(os.path.join(SUB_DIR, x)), reverse=True
            )
            for f in files: lb.insert(tk.END, f)
    refresh()

    def load_sel():
        sel = lb.curselection()
        if not sel: return
        populate_all_tabs(os.path.join(SUB_DIR, lb.get(sel[0])))
        messagebox.showinfo("Loaded", "Subtitle loaded into all tabs!", parent=hw)

    def del_sel():
        sel = lb.curselection()
        if not sel: return
        fn = lb.get(sel[0])
        if messagebox.askyesno("Confirm", f"Delete '{fn}'?", parent=hw):
            os.remove(os.path.join(SUB_DIR, fn)); refresh()

    def export_sel():
        sel = lb.curselection()
        if not sel: return
        fn  = lb.get(sel[0])
        ext = os.path.splitext(fn)[1]
        dst = filedialog.asksaveasfilename(
            defaultextension=ext, initialfile=fn,
            title="Save As…", filetypes=[("Subtitle", f"*{ext}")], parent=hw
        )
        if dst:
            shutil.copy(os.path.join(SUB_DIR, fn), dst)
            messagebox.showinfo("Success", "Exported successfully!", parent=hw)

    bf = tk.Frame(hw, bg=DARK_BG)
    bf.pack(fill=tk.X, pady=10, padx=15)
    for txt, cmd, col in [
        ("📂 Load into Tabs", load_sel,  "#2196F3"),
        ("💾 Save As…",       export_sel, "#4CAF50"),
        ("🗑️ Delete",          del_sel,   "#cc0000"),
        ("📁 Open Folder",    lambda: os.startfile(SUB_DIR), "#444"),
    ]:
        tk.Button(bf, text=txt, bg=col, fg="white", font=("Segoe UI", 9, "bold"),
                  relief=tk.FLAT, command=cmd, padx=6, pady=5).pack(
                  side=tk.LEFT, expand=True, fill=tk.X, padx=3)

# ============================================================
# ██████████   MAIN UI SETUP   ██████████
# ============================================================
app = tk.Tk()
app.title("Universal Subtitles Toolkit (VLC Edition)")
app.geometry("560x720")
app.configure(bg=DARK_BG)
app.resizable(False, False)

try:
    app.iconbitmap(resource_path("logo.ico"))
except Exception:
    pass

style = ttk.Style()
style.theme_use('clam')
style.configure('TCombobox', fieldbackground="white", background="white",
                foreground="black", borderwidth=0)
style.map('TCombobox',
    fieldbackground=[('readonly', 'white'), ('focus', 'white')],
    foreground=[('readonly', 'black'), ('focus', 'black')],
    selectbackground=[('readonly', VLC_ORANGE)],
    selectforeground=[('readonly', 'black')])

# --- VARIABLES ---
provider_var      = tk.StringVar(value="Groq (Lightning Fast)")
api_key_var       = tk.StringVar()
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

# --- HEADER ---
hdr = tk.Frame(app, bg=DARK_BG)
hdr.pack(fill=tk.X, padx=20, pady=(14, 5))
tk.Label(hdr, text="UNIVERSAL SUBTITLE TOOLKIT", bg=DARK_BG, fg=VLC_ORANGE,
         font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
tk.Button(hdr, text="📜 History", bg="#333", fg="white", relief=tk.FLAT,
          font=("Segoe UI", 9), command=open_history, padx=8).pack(side=tk.RIGHT)

# --- TAB BAR ---
tab_frame = tk.Frame(app, bg=DARK_BG)
tab_frame.pack(fill=tk.X, padx=20, pady=5)

def show_tab(idx):
    for i, btn in enumerate(tab_btns):
        btn.config(
            bg=VLC_ORANGE if i == idx else PANEL_BG,
            fg="black"   if i == idx else "white",
            font=("Segoe UI", 8, "bold" if i == idx else "normal")
        )
    for i, frame in enumerate(frames):
        if i == idx: frame.grid(row=0, column=0, sticky="nsew")
        else:        frame.grid_forget()

tab_labels = ["1. Generate (AI)", "2. Translate", "3. Sync", "4. Customize"]
tab_btns = [
    tk.Button(tab_frame, text=t, relief=tk.FLAT, width=13,
              command=lambda idx=i: show_tab(idx))
    for i, t in enumerate(tab_labels)
]
for btn in tab_btns:
    btn.pack(side=tk.LEFT, padx=2)

# --- CONTENT AREA ---
cc = tk.Frame(app, bg=PANEL_BG, bd=1, relief=tk.SOLID)
cc.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)
cc.grid_rowconfigure(0, weight=1)
cc.grid_columnconfigure(0, weight=1)

frame_gen    = tk.Frame(cc, bg=PANEL_BG)
frame_trans  = tk.Frame(cc, bg=PANEL_BG)
frame_sync   = tk.Frame(cc, bg=PANEL_BG)
frame_custom = tk.Frame(cc, bg=PANEL_BG)
frames = [frame_gen, frame_trans, frame_sync, frame_custom]

# ============================================================
# TAB 1 — GENERATE (AI)
# ============================================================
tk.Label(frame_gen, text="Provider & API Key:", bg=PANEL_BG, fg="white",
         font=("Segoe UI", 9)).pack(pady=(12, 2))
ttk.Combobox(frame_gen, textvariable=provider_var,
             values=["Groq (Lightning Fast)", "OpenAI (Standard)"],
             state="readonly", width=40).pack()
tk.Entry(frame_gen, textvariable=api_key_var, show="*", width=43,
         bg=DARK_BG, fg="white", insertbackground="white", border=0).pack(pady=4, ipady=3)

tk.Label(frame_gen, text="Select Video:", bg=PANEL_BG, fg="white",
         font=("Segoe UI", 9)).pack(pady=(6, 2))
f1 = tk.Frame(frame_gen, bg=PANEL_BG); f1.pack()
tk.Entry(f1, textvariable=gen_video_var, width=33,
         bg=DARK_BG, fg="white", border=0).pack(side=tk.LEFT, padx=5, ipady=3)
tk.Button(f1, text="Browse", command=lambda: browse_video(gen_video_var),
          bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT)

tk.Label(frame_gen, text="Audio / Source Language:", bg=PANEL_BG, fg="white",
         font=("Segoe UI", 9)).pack(pady=(8, 2))
ttk.Combobox(frame_gen, textvariable=gen_source_lang_var,
             values=sorted(WHISPER_LANGUAGES.keys()),
             state="readonly", width=40).pack()
tk.Label(frame_gen, text="⚠️ Use 'Auto Detect' for non-English videos",
         bg=PANEL_BG, fg="#888", font=("Segoe UI", 8)).pack()

tk.Label(frame_gen, text="Translate Subtitles To:", bg=PANEL_BG, fg="white",
         font=("Segoe UI", 9)).pack(pady=(8, 2))
ttk.Combobox(frame_gen, textvariable=gen_lang_var,
             values=sorted(LANGUAGES.keys()), state="readonly", width=40).pack()
tk.Checkbutton(frame_gen, text="Write in English Letters (e.g. Manglish, Hinglish)",
               variable=gen_romanize_var, bg=PANEL_BG, fg="#a0a0a0",
               activebackground=PANEL_BG, selectcolor=DARK_BG).pack(pady=(4, 0))

row_gen = tk.Frame(frame_gen, bg=PANEL_BG); row_gen.pack(pady=12)
gen_btn = tk.Button(row_gen, text="⚡ GENERATE SUBTITLES", bg=VLC_ORANGE, fg="black",
                    font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=run_generation)
gen_btn.pack(side=tk.LEFT, ipadx=10, ipady=6)
tk.Button(row_gen, text="👁 Preview", bg="#2a2a2a", fg=VLC_ORANGE, relief=tk.FLAT,
          font=("Segoe UI", 9, "bold"), padx=8, pady=6,
          command=lambda: show_srt_preview(
              lambda: trans_srt_var.get(),
              "👁 Preview — Generated Subtitle"
          )).pack(side=tk.LEFT, padx=(6, 0))

# ============================================================
# TAB 2 — TRANSLATE
# ============================================================
tk.Label(frame_trans, text="Select Subtitle File:", bg=PANEL_BG, fg="white",
         font=("Segoe UI", 9)).pack(pady=(28, 2))
f2 = tk.Frame(frame_trans, bg=PANEL_BG); f2.pack()
trans_srt_cb = ttk.Combobox(f2, textvariable=trans_srt_var, state="normal", width=38)
trans_srt_cb.pack(side=tk.LEFT, padx=5)
tk.Button(f2, text="Browse", command=lambda: browse_srt(trans_srt_var),
          bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT)

tk.Label(frame_trans, text="Translate To:", bg=PANEL_BG, fg="white",
         font=("Segoe UI", 9)).pack(pady=(18, 2))
ttk.Combobox(frame_trans, textvariable=trans_lang_var,
             values=sorted(LANGUAGES.keys()), state="readonly", width=40).pack()
tk.Checkbutton(frame_trans, text="Write in English Letters (e.g. Manglish, Hinglish)",
               variable=trans_romanize_var, bg=PANEL_BG, fg="#a0a0a0",
               activebackground=PANEL_BG, selectcolor=DARK_BG).pack(pady=(5, 0))

row_trans = tk.Frame(frame_trans, bg=PANEL_BG); row_trans.pack(pady=15)
trans_btn = tk.Button(row_trans, text="🌐 TRANSLATE & APPLY", bg=VLC_ORANGE, fg="black",
                      font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=run_translation)
trans_btn.pack(side=tk.LEFT, ipadx=10, ipady=6)
tk.Button(row_trans, text="👁 Preview", bg="#2a2a2a", fg=VLC_ORANGE, relief=tk.FLAT,
          font=("Segoe UI", 9, "bold"), padx=8, pady=6,
          command=lambda: show_srt_preview(
              lambda: trans_srt_var.get(),
              "👁 Preview — Subtitle File"
          )).pack(side=tk.LEFT, padx=(6, 0))
tk.Label(frame_trans, text="Supports 60+ languages  •  Long texts auto-chunked for reliability",
         bg=PANEL_BG, fg="#555", font=("Segoe UI", 8)).pack()

# ============================================================
# TAB 3 — SYNC
# ============================================================
tk.Label(frame_sync, text="Select Subtitle File:", bg=PANEL_BG, fg="white",
         font=("Segoe UI", 9)).pack(pady=(12, 2))
f3 = tk.Frame(frame_sync, bg=PANEL_BG); f3.pack()
sync_srt_cb = ttk.Combobox(f3, textvariable=sync_srt_var, state="normal", width=38)
sync_srt_cb.pack(side=tk.LEFT, padx=5)
tk.Button(f3, text="Browse", command=lambda: browse_srt(sync_srt_var),
          bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT)

# Auto-sync card
af = tk.Frame(frame_sync, bg="#252525")
af.pack(fill=tk.X, padx=15, pady=(10, 5))
tk.Label(af, text="🤖  AUTO-SYNC", bg="#252525", fg=VLC_ORANGE,
         font=("Segoe UI", 9, "bold")).pack(pady=(8, 2))
tk.Label(af, text="Analyses your video audio to detect first speech\nand calculates the perfect offset automatically.",
         bg="#252525", fg="#999", font=("Segoe UI", 8), justify="center").pack()
auto_sync_btn = tk.Button(af, text="🔍 Auto Detect Offset", bg="#444", fg="white",
                          font=("Segoe UI", 9, "bold"), relief=tk.FLAT, command=run_auto_sync)
auto_sync_btn.pack(pady=(6, 10), ipadx=10, ipady=4)

tk.Label(frame_sync, text="── or set offset manually ──", bg=PANEL_BG, fg="#444",
         font=("Segoe UI", 8)).pack(pady=(2, 0))
tk.Label(frame_sync, text="Shift Seconds:", bg=PANEL_BG, fg="white",
         font=("Segoe UI", 9)).pack(pady=(6, 2))
tk.Label(frame_sync, text="+2.5 = delay  •  -1.5 = advance", bg=PANEL_BG, fg="#777",
         font=("Segoe UI", 8)).pack()
tk.Entry(frame_sync, textvariable=sync_offset_var, width=12, bg=DARK_BG, fg="white",
         border=0, justify="center", font=("Segoe UI", 13, "bold")).pack(pady=4, ipady=3)

row_sync = tk.Frame(frame_sync, bg=PANEL_BG); row_sync.pack(pady=10)
sync_btn = tk.Button(row_sync, text="⏱️ SYNC & APPLY", bg=VLC_ORANGE, fg="black",
                     font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=run_sync)
sync_btn.pack(side=tk.LEFT, ipadx=10, ipady=6)
tk.Button(row_sync, text="👁 Preview", bg="#2a2a2a", fg=VLC_ORANGE, relief=tk.FLAT,
          font=("Segoe UI", 9, "bold"), padx=8, pady=6,
          command=lambda: show_srt_preview(
              lambda: sync_srt_var.get(),
              "👁 Preview — Sync File"
          )).pack(side=tk.LEFT, padx=(6, 0))

# ============================================================
# TAB 4 — CUSTOMIZE
# ============================================================
tk.Label(frame_custom, text="Select SRT File to Style:", bg=PANEL_BG, fg="white",
         font=("Segoe UI", 9)).pack(pady=(10, 2))
f4 = tk.Frame(frame_custom, bg=PANEL_BG); f4.pack()
custom_srt_cb = ttk.Combobox(f4, textvariable=custom_srt_var, state="normal", width=34)
custom_srt_cb.pack(side=tk.LEFT, padx=5)
tk.Button(f4, text="Browse", command=lambda: browse_srt(custom_srt_var),
          bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT)

# Two-column option grid
opts = tk.Frame(frame_custom, bg=PANEL_BG)
opts.pack(fill=tk.X, padx=12, pady=6)
L = tk.Frame(opts, bg=PANEL_BG); L.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
R = tk.Frame(opts, bg=PANEL_BG); R.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

# ── LEFT COLUMN ──
tk.Label(L, text="Font Family:", bg=PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
ttk.Combobox(L, textvariable=custom_font_var, values=COMMON_FONTS,
             state="normal", width=21).pack(anchor="w", pady=(0, 7))

tk.Label(L, text="Font Size:", bg=PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
sf = tk.Frame(L, bg=PANEL_BG); sf.pack(anchor="w", pady=(0, 7))
size_disp = tk.Label(sf, text=str(custom_size_var.get()), bg=PANEL_BG, fg=VLC_ORANGE,
                     width=3, font=("Segoe UI", 9, "bold"))
custom_size_var.trace_add("write", lambda *a: size_disp.config(text=str(custom_size_var.get())))
tk.Scale(sf, from_=12, to=48, orient=tk.HORIZONTAL, variable=custom_size_var,
         bg=PANEL_BG, fg="white", highlightthickness=0, troughcolor="#333",
         activebackground=VLC_ORANGE, length=115, showvalue=False).pack(side=tk.LEFT)
size_disp.pack(side=tk.LEFT, padx=4)

tk.Label(L, text="Text Color:", bg=PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
text_color_btn = tk.Button(L, text="  ■  Pick Color", bg=custom_text_color_var.get(),
                           fg="black", relief=tk.FLAT, font=("Segoe UI", 8),
                           command=lambda: pick_color(custom_text_color_var, text_color_btn))
text_color_btn.pack(anchor="w", pady=(0, 6))

tk.Label(L, text="Outline Color:", bg=PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
outline_color_btn = tk.Button(L, text="  ■  Pick Color", bg=custom_outline_color_var.get(),
                              fg="white", relief=tk.FLAT, font=("Segoe UI", 8),
                              command=lambda: pick_color(custom_outline_color_var, outline_color_btn))
outline_color_btn.pack(anchor="w", pady=(0, 4))

# ── RIGHT COLUMN ──
tk.Label(R, text="Style:", bg=PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
for txt, var in [("Bold", custom_bold_var), ("Italic", custom_italic_var), ("Shadow Box", custom_bg_var)]:
    tk.Checkbutton(R, text=txt, variable=var, bg=PANEL_BG, fg="white",
                   activebackground=PANEL_BG, selectcolor=DARK_BG,
                   font=("Segoe UI", 9)).pack(anchor="w")

tk.Label(R, text="Position:", bg=PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w", pady=(6, 0))
for txt, val in [("⬇ Bottom (Default)", "bottom"), ("⬆ Top", "top")]:
    tk.Radiobutton(R, text=txt, variable=custom_position_var, value=val,
                   bg=PANEL_BG, fg="white", activebackground=PANEL_BG,
                   selectcolor=DARK_BG, font=("Segoe UI", 9)).pack(anchor="w")

tk.Label(R, text="Outline Size (0–4):", bg=PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w", pady=(5, 0))
tk.Scale(R, from_=0, to=4, orient=tk.HORIZONTAL, variable=custom_outline_sz_var,
         bg=PANEL_BG, fg="white", highlightthickness=0, troughcolor="#333",
         activebackground=VLC_ORANGE, length=130).pack(anchor="w")

tk.Label(R, text="Shadow Size (0–3):", bg=PANEL_BG, fg="#aaa", font=("Segoe UI", 8)).pack(anchor="w")
tk.Scale(R, from_=0, to=3, orient=tk.HORIZONTAL, variable=custom_shadow_var,
         bg=PANEL_BG, fg="white", highlightthickness=0, troughcolor="#333",
         activebackground=VLC_ORANGE, length=130).pack(anchor="w")

row_custom = tk.Frame(frame_custom, bg=PANEL_BG); row_custom.pack(pady=(8, 3))
export_ass_btn = tk.Button(row_custom, text="🎨 EXPORT AS STYLED .ASS", bg=VLC_ORANGE, fg="black",
                           font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=run_export_ass)
export_ass_btn.pack(side=tk.LEFT, ipadx=10, ipady=6)
tk.Button(row_custom, text="👁 Preview SRT", bg="#2a2a2a", fg=VLC_ORANGE, relief=tk.FLAT,
          font=("Segoe UI", 9, "bold"), padx=8, pady=6,
          command=lambda: show_srt_preview(
              lambda: custom_srt_var.get(),
              "👁 Preview — Subtitle Content"
          )).pack(side=tk.LEFT, padx=(5, 0))
tk.Button(row_custom, text="🖥 Style Preview", bg="#1a2a1a", fg="#4CAF50", relief=tk.FLAT,
          font=("Segoe UI", 9, "bold"), padx=8, pady=6,
          command=show_style_preview).pack(side=tk.LEFT, padx=(5, 0))
tk.Label(frame_custom, text="ASS format = full styling in VLC  (font, color, position, outline)",
         bg=PANEL_BG, fg="#555", font=("Segoe UI", 8)).pack()

# ============================================================
# BOTTOM STATUS BAR
# ============================================================
bot = tk.Frame(app, bg=DARK_BG)
bot.pack(fill=tk.X, padx=20, pady=(0, 10))
ttk.Progressbar(bot, variable=progress_var, maximum=100, length=520, mode='determinate').pack()
progress_label = tk.Label(bot, text="", bg=DARK_BG, fg=VLC_ORANGE, font=("Segoe UI", 9))
progress_label.pack()
status_label = tk.Label(bot, text="Status: Ready", bg=DARK_BG, fg="#888", font=("Segoe UI", 9))
status_label.pack()

# ============================================================
# LAUNCH — handle file passed via command-line (drag-and-drop)
# ============================================================
if len(sys.argv) > 1:
    passed = clean_path(sys.argv[1])
    if os.path.isfile(passed):
        if passed.lower().endswith('.srt'):
            populate_all_tabs(passed)
            vm = detect_paired_file(passed, "video")
            if vm: gen_video_var.set(vm)
        else:
            gen_video_var.set(passed)

show_tab(0)
app.mainloop()