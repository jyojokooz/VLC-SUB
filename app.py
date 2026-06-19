import tkinter as tk
from tkinter import filedialog, messagebox, ttk
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

# --- CONFIGURATION ---
MAX_TRANSLATION_WORKERS = 15 
VLC_ORANGE = "#ff8c00"
DARK_BG = "#121212"
PANEL_BG = "#1e1e1e"

# --- SAFE DIRECTORY CREATION FIX ---
try:
    if os.name == 'nt' and os.getenv('APPDATA'):
        BASE_DIR = os.path.join(os.getenv('APPDATA'), 'UniversalSubtitles')
    else:
        BASE_DIR = os.path.join(os.path.expanduser('~'), 'Documents', 'UniversalSubtitles')
        
    TEMP_DIR = os.path.join(BASE_DIR, "temp_audio")
    SUB_DIR = os.path.join(BASE_DIR, "subtitles")
    
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(SUB_DIR, exist_ok=True)
except Exception as e:
    TEMP_DIR = os.path.join(os.getcwd(), "temp_audio")
    SUB_DIR = os.path.join(os.getcwd(), "subtitles")
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(SUB_DIR, exist_ok=True)

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

app = None
gen_btn = trans_btn = sync_btn = None
trans_srt_cb = sync_srt_cb = None
status_label = progress_var = progress_label = None

# --- HELPERS ---
def format_timestamp(seconds):
    seconds = max(0, seconds)
    hours = math.floor(seconds / 3600)
    minutes = math.floor((seconds % 3600) / 60)
    secs = math.floor(seconds % 60)
    millisecs = math.floor((seconds - math.floor(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"

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
    """Scans the video's directory for available subtitles so the user can easily select them."""
    subs = []
    # Check video directory
    if video_path and os.path.exists(video_path):
        v_dir = os.path.dirname(video_path)
        if os.path.exists(v_dir):
            for f in os.listdir(v_dir):
                if f.lower().endswith('.srt'):
                    subs.append(os.path.normpath(os.path.join(v_dir, f)))
    # Check generated directory
    if os.path.exists(SUB_DIR):
        for f in os.listdir(SUB_DIR):
            if f.lower().endswith('.srt'):
                subs.append(os.path.normpath(os.path.join(SUB_DIR, f)))
    # Return unique list
    return list(dict.fromkeys(subs))

def update_status(text):
    if app and status_label: app.after(0, lambda: status_label.config(text=f"Status: {text}"))

def update_progress(done, total, label=""):
    pct = int((done / total) * 100) if total > 0 else 0
    if app and progress_var: app.after(0, lambda: progress_var.set(pct))
    if label and app and progress_label: app.after(0, lambda: progress_label.config(text=f"{done}/{total} {label}"))

# --- SRT PARSER & TRANSLATOR ---
def parse_srt(filepath):
    with open(filepath, 'r', encoding='utf-8-sig') as f: content = f.read()
    blocks = re.split(r'\n\s*\n', content.strip())
    parsed = []
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            idx = lines[0].strip()
            times = lines[1].split(' --> ')
            if len(times) == 2:
                parsed.append({"index": idx, "start": time_to_sec(times[0].strip()), "end": time_to_sec(times[1].strip()), "text": '\n'.join(lines[2:])})
    return parsed

def translate_text(eng_text, target_code):
    if target_code == "en" or not eng_text.strip(): return eng_text
    for _ in range(3):
        try:
            res = GoogleTranslator(source='auto', target=target_code).translate(eng_text)
            if res: return res
        except Exception:
            time.sleep(0.5)
    return eng_text

def transcribe_audio_chunk(chunk_path, provider, api_key):
    url = "https://api.groq.com/openai/v1/audio/transcriptions" if "Groq" in provider else "https://api.openai.com/v1/audio/transcriptions"
    model = "whisper-large-v3" if "Groq" in provider else "whisper-1"
    with open(chunk_path, "rb") as f:
        response = requests.post(url, headers={"Authorization": f"Bearer {api_key}"}, files={"file": (os.path.basename(chunk_path), f, "audio/mp4")}, data={"model": model, "response_format": "verbose_json", "language": "en"})
        if response.status_code != 200: raise Exception(f"API Error {response.status_code}: {response.text}")
        return response.json()

def apply_subtitle_to_vlc(subtitle_path, success_message):
    """Opens Windows Explorer highlighting the new subtitle to easily drag-and-drop into VLC."""
    try:
        if os.name == 'nt':
            subprocess.Popen(f'explorer /select,"{clean_path(subtitle_path)}"')
    except Exception:
        pass
    app.after(0, lambda: messagebox.showinfo(
        "Success", 
        f"{success_message}\n\n⚠️ IMPORTANT:\nTo avoid restarting your movie, the folder has been opened for you.\n\nSimply DRAG & DROP the highlighted subtitle file directly into your playing VLC window!"
    ))

# --- WORKFLOWS ---
def run_generation():
    video_path = clean_path(gen_video_var.get().strip())
    target_lang = gen_lang_var.get()
    api_key = api_key_var.get().strip()
    provider = provider_var.get()

    if not video_path: return messagebox.showerror("Error", "Please select a video file!")
    if not api_key: return messagebox.showerror("Error", "Please enter your API Key!")

    def _task():
        try:
            if gen_btn: app.after(0, lambda: gen_btn.config(state=tk.DISABLED))
            if os.path.exists(TEMP_DIR):
                for f in os.listdir(TEMP_DIR): os.remove(os.path.join(TEMP_DIR, f))

            update_status("Compressing audio for AI (Wait ~15s)...")
            chunk_pattern = os.path.join(TEMP_DIR, "chunk_%03d.m4a")
            cmd = ["ffmpeg", "-y", "-i", video_path, "-vn", "-c:a", "aac", "-b:a", "64k", "-ar", "16000", "-ac", "1", "-af", "loudnorm", "-f", "segment", "-segment_time", "600", chunk_pattern]
            
            ffmpeg_process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
            if ffmpeg_process.returncode != 0: raise Exception("FFmpeg failed.")

            chunks = sorted([f for f in os.listdir(TEMP_DIR) if f.endswith('.m4a')])
            all_segments = []
            for i, chunk in enumerate(chunks):
                update_status(f"Transcribing Part {i+1} of {len(chunks)} via AI...")
                update_progress(i, len(chunks), "parts")
                ai_data = transcribe_audio_chunk(os.path.join(TEMP_DIR, chunk), provider, api_key)
                offset = i * 600
                for segment in ai_data.get("segments", []):
                    all_segments.append({"start": segment["start"] + offset, "end": segment["end"] + offset, "text": segment["text"].strip()})

            target_code = LANGUAGES.get(target_lang, "en")
            if target_code != "en":
                update_status("Translating subtitles...")
                completed = 0
                def do_trans(seg):
                    seg["text"] = translate_text(seg["text"], target_code)
                    return seg
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_TRANSLATION_WORKERS) as exe:
                    futures = [exe.submit(do_trans, seg) for seg in all_segments]
                    for f in concurrent.futures.as_completed(futures):
                        completed += 1
                        update_progress(completed, len(all_segments), "lines")

            srt_content = "".join([f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n" for i, s in enumerate(all_segments) if s['text']])
            srt_path = clean_path(os.path.join(SUB_DIR, f"{os.path.splitext(os.path.basename(video_path))[0]}_{target_lang}.srt"))
            
            with open(srt_path, 'w', encoding='utf-8') as f: f.write(srt_content)
            for f in os.listdir(TEMP_DIR): os.remove(os.path.join(TEMP_DIR, f))
            
            update_status("Done!")
            update_progress(100, 100, "%")
            app.after(0, lambda: gen_video_var.set(video_path)) # Triggers combobox refresh
            apply_subtitle_to_vlc(srt_path, "Subtitles generated successfully!")

        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Error", str(e)))
            update_status("Error.")
        finally:
            if gen_btn: app.after(0, lambda: gen_btn.config(state=tk.NORMAL))

    threading.Thread(target=_task, daemon=True).start()

def run_translation():
    srt_path = clean_path(trans_srt_var.get().strip())
    target_lang = trans_lang_var.get()
    
    if not srt_path: return messagebox.showerror("Error", "Please select an SRT file!")

    def _task():
        try:
            if trans_btn: app.after(0, lambda: trans_btn.config(state=tk.DISABLED))
            update_status("Parsing SRT File...")
            segments = parse_srt(srt_path)
            
            target_code = LANGUAGES.get(target_lang, "en")
            if target_code != "en":
                update_status("Translating subtitles...")
                completed = 0
                def do_trans(seg):
                    seg["text"] = translate_text(seg["text"], target_code)
                    return seg
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_TRANSLATION_WORKERS) as exe:
                    futures = [exe.submit(do_trans, seg) for seg in segments]
                    for f in concurrent.futures.as_completed(futures):
                        completed += 1
                        update_progress(completed, len(segments), "lines")

            srt_content = "".join([f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n" for i, s in enumerate(segments)])
            base_name = os.path.splitext(os.path.basename(srt_path))[0]
            save_path = clean_path(os.path.join(SUB_DIR, f"{base_name}_{target_lang}.srt"))
            
            with open(save_path, 'w', encoding='utf-8') as f: f.write(srt_content)
            
            update_status("Done!")
            update_progress(100, 100, "%")
            
            # Refresh to show new file
            v_path = gen_video_var.get().strip()
            if v_path: app.after(0, lambda: gen_video_var.set(v_path)) 
            app.after(0, lambda: trans_srt_var.set(save_path))
            
            apply_subtitle_to_vlc(save_path, "Translation finished!")
            
        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Error", str(e)))
            update_status("Error.")
        finally:
            if trans_btn: app.after(0, lambda: trans_btn.config(state=tk.NORMAL))

    threading.Thread(target=_task, daemon=True).start()

def run_sync():
    srt_path = clean_path(sync_srt_var.get().strip())
    try: offset_val = float(sync_offset_var.get().strip())
    except ValueError: return messagebox.showerror("Error", "Offset must be a number (e.g. 2.5 or -1.5)")
    
    if not srt_path: return messagebox.showerror("Error", "Please select an SRT file!")

    def _task():
        try:
            if sync_btn: app.after(0, lambda: sync_btn.config(state=tk.DISABLED))
            update_status("Adjusting SRT Timestamps...")
            segments = parse_srt(srt_path)
            
            for seg in segments:
                seg['start'] = max(0, seg['start'] + offset_val)
                seg['end'] = max(0, seg['end'] + offset_val)

            srt_content = "".join([f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n" for i, s in enumerate(segments)])
            base_name = os.path.splitext(os.path.basename(srt_path))[0]
            save_path = clean_path(os.path.join(SUB_DIR, f"{base_name}_synced.srt"))
            
            with open(save_path, 'w', encoding='utf-8') as f: f.write(srt_content)
            
            update_status("Done!")
            update_progress(100, 100, "%")
            
            v_path = gen_video_var.get().strip()
            if v_path: app.after(0, lambda: gen_video_var.set(v_path)) 
            app.after(0, lambda: sync_srt_var.set(save_path))
            
            apply_subtitle_to_vlc(save_path, "Sync finished!")
            
        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Error", str(e)))
            update_status("Error.")
        finally:
            if sync_btn: app.after(0, lambda: sync_btn.config(state=tk.NORMAL))

    threading.Thread(target=_task, daemon=True).start()

# --- DYNAMIC REFRESH WHEN VIDEO CHANGES ---
def on_video_change(*args):
    v_path = gen_video_var.get().strip()
    subs = get_available_subtitles(v_path)
    
    if trans_srt_cb: trans_srt_cb['values'] = subs
    if sync_srt_cb: sync_srt_cb['values'] = subs
        
    best_match = detect_paired_file(v_path, "srt")
    if best_match:
        trans_srt_var.set(best_match)
        sync_srt_var.set(best_match)
    elif subs and not trans_srt_var.get():
        trans_srt_var.set(subs[0])
        sync_srt_var.set(subs[0])

def browse_srt(var):
    f = filedialog.askopenfilename(filetypes=[("Subtitles", "*.srt")])
    if f: var.set(clean_path(f))

# --- HISTORY WINDOW ---
def open_history():
    history_win = tk.Toplevel(app)
    history_win.title("Subtitle History")
    history_win.geometry("520x350")
    history_win.configure(bg=DARK_BG)
    history_win.transient(app)
    
    tk.Label(history_win, text="Generated Subtitles History", bg=DARK_BG, fg=VLC_ORANGE, font=("Segoe UI", 12, "bold")).pack(pady=10)
    list_frame = tk.Frame(history_win, bg=DARK_BG)
    list_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
    scrollbar = tk.Scrollbar(list_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    listbox = tk.Listbox(list_frame, bg=PANEL_BG, fg="white", yscrollcommand=scrollbar.set, selectbackground=VLC_ORANGE, selectforeground="black", border=0, highlightthickness=1, highlightbackground="#333", font=("Segoe UI", 9))
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.config(command=listbox.yview)
    
    def refresh_list():
        listbox.delete(0, tk.END)
        if os.path.exists(SUB_DIR):
            files = sorted([f for f in os.listdir(SUB_DIR) if f.endswith(".srt")], key=lambda x: os.path.getmtime(os.path.join(SUB_DIR, x)), reverse=True)
            for f in files: listbox.insert(tk.END, f)
    refresh_list()
    
    def delete_selected():
        sel = listbox.curselection()
        if not sel: return
        filename = listbox.get(sel[0])
        if messagebox.askyesno("Confirm", f"Delete {filename}?", parent=history_win):
            os.remove(os.path.join(SUB_DIR, filename))
            refresh_list()

    def export_selected():
        sel = listbox.curselection()
        if not sel: return
        filename = listbox.get(sel[0])
        dest_path = filedialog.asksaveasfilename(defaultextension=".srt", initialfile=filename, title="Save Subtitle As...", filetypes=[("Subtitle Files", "*.srt")], parent=history_win)
        if dest_path:
            shutil.copy(os.path.join(SUB_DIR, filename), dest_path)
            messagebox.showinfo("Success", "Subtitle exported successfully!", parent=history_win)
                
    btn_frame = tk.Frame(history_win, bg=DARK_BG)
    btn_frame.pack(fill=tk.X, pady=15, padx=15)
    tk.Button(btn_frame, text="💾 Save As...", bg="#4CAF50", fg="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, command=export_selected, padx=10, pady=5).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0,5))
    tk.Button(btn_frame, text="🗑️ Delete", bg="#cc0000", fg="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, command=delete_selected, padx=10, pady=5).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0,5))
    tk.Button(btn_frame, text="📂 Folder", bg="#333", fg="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, command=lambda: os.startfile(SUB_DIR), padx=10, pady=5).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0,0))

# --- UI SETUP ---
app = tk.Tk()
app.title("Universal Subtitles Toolkit (VLC Edition)")
app.geometry("520x540")
app.configure(bg=DARK_BG)
app.resizable(False, False)

style = ttk.Style()
style.theme_use('clam')

# FIX FOR THE WHITE TEXT ON WHITE BOX: Forces black text on white background
style.configure('TCombobox', fieldbackground="white", background="white", foreground="black", borderwidth=0)
style.map('TCombobox', 
          fieldbackground=[('readonly', 'white'), ('focus', 'white')], 
          foreground=[('readonly', 'black'), ('focus', 'black')],
          selectbackground=[('readonly', VLC_ORANGE), ('focus', VLC_ORANGE)],
          selectforeground=[('readonly', 'black'), ('focus', 'black')])

provider_var = tk.StringVar(value="Groq (Lightning Fast)")
api_key_var = tk.StringVar()
gen_video_var = tk.StringVar()
gen_lang_var = tk.StringVar(value="English")
trans_srt_var, trans_lang_var = tk.StringVar(), tk.StringVar(value="Malayalam")
sync_srt_var, sync_offset_var = tk.StringVar(), tk.StringVar(value="+0.0")
progress_var = tk.IntVar(value=0)

gen_video_var.trace_add("write", on_video_change) # Triggers folder scan when video path is filled

header_frame = tk.Frame(app, bg=DARK_BG)
header_frame.pack(fill=tk.X, padx=20, pady=(15, 5))
tk.Label(header_frame, text="UNIVERSAL SUBTITLE TOOLKIT", bg=DARK_BG, fg=VLC_ORANGE, font=("Segoe UI", 15, "bold")).pack(side=tk.LEFT)
tk.Button(header_frame, text="📜 History", bg="#333", fg="white", relief=tk.FLAT, font=("Segoe UI", 9), command=open_history, padx=8).pack(side=tk.RIGHT)

tab_frame = tk.Frame(app, bg=DARK_BG)
tab_frame.pack(fill=tk.X, padx=20, pady=5)

def show_tab(idx):
    for i, btn in enumerate(tab_btns): btn.config(bg=VLC_ORANGE if i==idx else PANEL_BG, fg="black" if i==idx else "white", font=("Segoe UI", 9, "bold" if i==idx else "normal"))
    for i, frame in enumerate(frames): frame.grid(row=0, column=0, sticky="nsew") if i==idx else frame.grid_forget()

tab_btns = [tk.Button(tab_frame, text=t, relief=tk.FLAT, width=18, command=lambda idx=i: show_tab(idx)) for i, t in enumerate(["1. Generate (AI)", "2. Translate SRT", "3. Sync SRT"])]
for btn in tab_btns: btn.pack(side=tk.LEFT, padx=3)

content_container = tk.Frame(app, bg=PANEL_BG, bd=1, relief=tk.SOLID)
content_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
content_container.grid_rowconfigure(0, weight=1); content_container.grid_columnconfigure(0, weight=1)

frame_gen, frame_trans, frame_sync = tk.Frame(content_container, bg=PANEL_BG), tk.Frame(content_container, bg=PANEL_BG), tk.Frame(content_container, bg=PANEL_BG)
frames = [frame_gen, frame_trans, frame_sync]

def browse_video(var):
    if f := filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mkv *.avi *.ts *.mov *.wmv")]): var.set(clean_path(f))

# TAB 1
tk.Label(frame_gen, text="Provider & API Key:", bg=PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(15,2))
ttk.Combobox(frame_gen, textvariable=provider_var, values=["Groq (Lightning Fast)", "OpenAI (Standard)"], state="readonly", width=38).pack()
tk.Entry(frame_gen, textvariable=api_key_var, show="*", width=41, bg=DARK_BG, fg="white", insertbackground="white", border=0).pack(pady=5, ipady=3)
tk.Label(frame_gen, text="Select Video:", bg=PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(10,2))
f1 = tk.Frame(frame_gen, bg=PANEL_BG); f1.pack()
tk.Entry(f1, textvariable=gen_video_var, width=31, bg=DARK_BG, fg="white", border=0).pack(side=tk.LEFT, padx=5, ipady=3)
tk.Button(f1, text="Browse", command=lambda: browse_video(gen_video_var), bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT)
tk.Label(frame_gen, text="Translate To:", bg=PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(10,2))
ttk.Combobox(frame_gen, textvariable=gen_lang_var, values=sorted(LANGUAGES.keys()), state="readonly", width=38).pack()
gen_btn = tk.Button(frame_gen, text="GENERATE", bg=VLC_ORANGE, fg="black", font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=run_generation)
gen_btn.pack(pady=20, ipadx=10, ipady=5)

# TAB 2 (NOW A COMBOBOX FOR EASY SELECTION)
tk.Label(frame_trans, text="Select Subtitle from Video Folder:", bg=PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(30,2))
f2 = tk.Frame(frame_trans, bg=PANEL_BG); f2.pack()
trans_srt_cb = ttk.Combobox(f2, textvariable=trans_srt_var, state="normal", width=38)
trans_srt_cb.pack(side=tk.LEFT, padx=5)
tk.Button(f2, text="Browse", command=lambda: browse_srt(trans_srt_var), bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT)
tk.Label(frame_trans, text="Translate To:", bg=PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(20,2))
ttk.Combobox(frame_trans, textvariable=trans_lang_var, values=sorted(LANGUAGES.keys()), state="readonly", width=38).pack()
trans_btn = tk.Button(frame_trans, text="TRANSLATE & APPLY", bg=VLC_ORANGE, fg="black", font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=run_translation)
trans_btn.pack(pady=30, ipadx=10, ipady=5)

# TAB 3 (NOW A COMBOBOX FOR EASY SELECTION)
tk.Label(frame_sync, text="Select Subtitle from Video Folder:", bg=PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(30,2))
f3 = tk.Frame(frame_sync, bg=PANEL_BG); f3.pack()
sync_srt_cb = ttk.Combobox(f3, textvariable=sync_srt_var, state="normal", width=38)
sync_srt_cb.pack(side=tk.LEFT, padx=5)
tk.Button(f3, text="Browse", command=lambda: browse_srt(sync_srt_var), bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT)
tk.Label(frame_sync, text="Shift Time (Seconds):", bg=PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(20,2))
tk.Label(frame_sync, text="(e.g., Use '+2.5' to delay, or '-1.5' to make earlier)", bg=PANEL_BG, fg="#888", font=("Segoe UI", 8)).pack()
tk.Entry(frame_sync, textvariable=sync_offset_var, width=15, bg=DARK_BG, fg="white", border=0, justify="center", font=("Segoe UI", 12)).pack(pady=5, ipady=3)
sync_btn = tk.Button(frame_sync, text="SYNC & APPLY", bg=VLC_ORANGE, fg="black", font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=run_sync)
sync_btn.pack(pady=30, ipadx=10, ipady=5)

# Bottom UI Items
bottom_frame = tk.Frame(app, bg=DARK_BG)
bottom_frame.pack(fill=tk.X, padx=20, pady=(0, 15))
ttk.Progressbar(bottom_frame, variable=progress_var, maximum=100, length=480, mode='determinate').pack()
progress_label = tk.Label(bottom_frame, text="", bg=DARK_BG, fg=VLC_ORANGE, font=("Segoe UI", 9))
progress_label.pack()
status_label = tk.Label(bottom_frame, text="Status: Ready", bg=DARK_BG, fg="#888", font=("Segoe UI", 9))
status_label.pack()

# LAUNCH INITIALIZATION LOGIC
if len(sys.argv) > 1:
    passed_path = clean_path(sys.argv[1])
    if os.path.isfile(passed_path):
        if passed_path.lower().endswith('.srt'):
            trans_srt_var.set(passed_path)
            sync_srt_var.set(passed_path)
            v_match = detect_paired_file(passed_path, "video")
            if v_match: gen_video_var.set(v_match) # This triggers the folder scan!
        else:
            gen_video_var.set(passed_path) # Triggers folder scan and auto-selects subtitles!

show_tab(0)
app.mainloop()