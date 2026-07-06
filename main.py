import os
import warnings
import multiprocessing

# MUST BE ADDED FOR WINDOWS EXECUTABLES USING ML/THREADS
if __name__ == '__main__':
    multiprocessing.freeze_support()

warnings.simplefilter("ignore")
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN_WARNING"] = "1"
os.environ["PYTHONWARNINGS"] = "ignore"

import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import threading
import subprocess
import concurrent.futures
import sys
import re

# Try to suppress huggingface_hub warnings
try:
    import huggingface_hub.utils.logging
    huggingface_hub.utils.logging.set_verbosity_error()
except Exception:
    pass

# Custom Modular Imports
import ust_settings as config
from utils import clean_path, format_timestamp, parse_srt, get_available_subtitles, detect_paired_file, generate_ass_content, resource_path, get_ffmpeg_path
from engines import transcribe_audio_chunk, transcribe_offline, translate_text, translate_batch, detect_sync_offset, check_offline_available

# UPDATED: We now import get_vlc_ext_path
from vlc_integration import launch_vlc_preview, apply_subtitle_to_vlc, install_vlc_extension, remove_vlc_extension, get_vlc_ext_path
from ui_windows import show_srt_preview, show_style_preview, open_history

# Secure API Key Storage
from security import save_api_key, load_api_key


# ============================================================
# HELPER / CALLBACKS
# ============================================================
def update_status(text):
    if app and status_label:
        app.after(0, lambda: status_label.config(text=f"Status: {text}"))

def update_progress(done, total, label=""):
    pct = int((done / total) * 100) if total > 0 else 0
    if app and progress_var:  app.after(0, lambda: progress_var.set(pct))
    if label and app and progress_label:
        app.after(0, lambda: progress_label.config(text=f"{done}/{total} {label}"))

def populate_all_tabs(srt_path):
    app.after(0, lambda: trans_srt_var.set(srt_path))
    app.after(0, lambda: sync_srt_var.set(srt_path))
    app.after(0, lambda: custom_srt_var.set(srt_path))


# ============================================================
# WORKFLOW LOGIC
# ============================================================
def run_generation():
    video_path       = clean_path(gen_video_var.get().strip())
    target_lang      = gen_lang_var.get()
    api_key          = api_key_var.get().strip()
    provider         = provider_var.get()
    romanize         = gen_romanize_var.get()
    source_lang_name = gen_source_lang_var.get()
    source_lang_code = config.WHISPER_LANGUAGES.get(source_lang_name)
    is_offline       = "Offline" in provider
    offline_model_name_ui = offline_model_var.get()

    if not video_path: return messagebox.showerror("Error", "Please select a video file!")
    if not os.path.exists(video_path): return messagebox.showerror("Error", "Video file not found!")

    # API key only required for cloud providers
    if not is_offline:
        if not api_key: return messagebox.showerror("Error", "Please enter your API Key!")
        save_api_key(api_key)

    def _task():
        try:
            app.after(0, lambda: gen_btn.config(state=tk.DISABLED))
            if os.path.exists(config.TEMP_DIR):
                for fn in os.listdir(config.TEMP_DIR):
                    try: os.remove(os.path.join(config.TEMP_DIR, fn))
                    except: pass

            update_status("Compressing audio for AI (Wait ~15s)...")
            chunk_pattern = os.path.join(config.TEMP_DIR, "chunk_%03d.m4a")
            cf  = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            
            ffmpeg_path = get_ffmpeg_path()
            segment_time = str(config.AUDIO_SEGMENT_TIME)
            cmd = [ffmpeg_path, "-y", "-i", video_path, "-vn", "-c:a", "aac", "-b:a", "64k",
                   "-ar", "16000", "-ac", "1", "-af", "loudnorm", "-f", "segment",
                   "-segment_time", segment_time, chunk_pattern]

            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=cf)
                if proc.returncode != 0:
                    raise Exception(f"FFmpeg failed. Is the file a valid video?\n\n{proc.stderr.decode('utf-8', errors='ignore')[-400:]}")
            except FileNotFoundError:
                raise Exception("ffmpeg.exe not found! Make sure ffmpeg.exe is in the app folder.")

            chunks = sorted([f for f in os.listdir(config.TEMP_DIR) if f.endswith('.m4a')])
            if not chunks:
                raise Exception("No audio chunks extracted — the video may have no audio track.")

            all_segments = []
            for i, chunk in enumerate(chunks):
                lang_info = f" ({source_lang_name})" if source_lang_code else " (Auto-Detect)"

                if is_offline:
                    # Offline: use faster-whisper locally
                    model_name = config.OFFLINE_MODEL_SIZES.get(offline_model_name_ui, "medium")
                    update_status(f"🖥️ Transcribing Part {i+1}/{len(chunks)} locally{lang_info}...")
                    update_progress(i, len(chunks), "parts")
                    ai_data = transcribe_offline(
                        os.path.join(config.TEMP_DIR, chunk),
                        model_size=model_name,
                        source_lang=source_lang_code,
                        status_callback=update_status,
                        progress_callback=update_progress
                    )
                else:
                    # Cloud API: Groq or OpenAI
                    update_status(f"☁️ Transcribing Part {i+1}/{len(chunks)}{lang_info}...")
                    update_progress(i, len(chunks), "parts")
                    ai_data = transcribe_audio_chunk(
                        os.path.join(config.TEMP_DIR, chunk), provider, api_key, source_lang_code
                    )

                offset = i * config.AUDIO_SEGMENT_TIME
                for seg in ai_data.get("segments", []):
                    text = seg["text"].strip()
                    if text:
                        all_segments.append({"start": seg["start"] + offset, "end": seg["end"] + offset, "text": text})

            if not all_segments: raise Exception("No speech detected.")

            target_code = config.LANGUAGES.get(target_lang, "en")
            if target_code != "en":
                mode = "Manglish/Hinglish" if romanize else "Native Script"
                update_status(f"🌐 Batch translating {len(all_segments)} lines ({mode})...")
                update_progress(0, 100, "%")
                translate_batch(all_segments, target_code, romanize)
                update_progress(100, 100, "%")

            srt_content = "".join(f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                                  for i, s in enumerate(all_segments) if s['text'])
            suffix   = f"_{target_lang}_Romanized" if romanize else f"_{target_lang}"
            srt_name = f"{os.path.splitext(os.path.basename(video_path))[0]}{suffix}.srt"
            srt_path = clean_path(os.path.join(config.SUB_DIR, srt_name))

            with open(srt_path, 'w', encoding='utf-8') as f: f.write(srt_content)
            for fn in os.listdir(config.TEMP_DIR):
                try: os.remove(os.path.join(config.TEMP_DIR, fn))
                except: pass

            update_status(f"✅ Done! {len(all_segments)} subtitle lines generated.")
            update_progress(100, 100, "%")
            populate_all_tabs(srt_path)
            
            # Apply subtitle to VLC
            apply_subtitle_to_vlc(app, srt_path, f"✅ Subtitles Generated!\n{len(all_segments)} lines | {target_lang}", video_path)

        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Generation Error", str(e)))
            update_status("Error occurred.")
        finally:
            app.after(0, lambda: gen_btn.config(state=tk.NORMAL))
    threading.Thread(target=_task, daemon=True).start()


def run_online_search():
    video_path = clean_path(gen_video_var.get().strip())
    target_lang = gen_lang_var.get()
    
    if not video_path: return messagebox.showerror("Error", "Please select a video file!")
    if not os.path.exists(video_path): return messagebox.showerror("Error", "Video file not found!")
    
    def _task():
        try:
            app.after(0, lambda: fast_dl_btn.config(state=tk.DISABLED))
            from engines import fetch_online_subtitle
            target_code = config.LANGUAGES.get(target_lang, "en")
            out_path = fetch_online_subtitle(video_path, target_code, update_status)
            if out_path:
                populate_all_tabs(out_path)
                # Apply subtitle to VLC
                apply_subtitle_to_vlc(app, out_path, f"✅ Online Subtitle Downloaded!\n{target_lang}", video_path)
        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Search Error", str(e)))
            update_status("Error occurred.")
        finally:
            app.after(0, lambda: fast_dl_btn.config(state=tk.NORMAL))
            
    threading.Thread(target=_task, daemon=True).start()


def run_translation():
    srt_path    = clean_path(trans_srt_var.get().strip())
    target_lang = trans_lang_var.get()
    romanize    = trans_romanize_var.get()
    if not srt_path or not os.path.exists(srt_path): return messagebox.showerror("Error", "Valid SRT file not found!")

    def _task():
        try:
            app.after(0, lambda: trans_btn.config(state=tk.DISABLED))
            update_status("Parsing SRT file...")
            segments = parse_srt(srt_path)
            if not segments: raise Exception("Could not parse the SRT file.")

            target_code = config.LANGUAGES.get(target_lang, "en")
            errors = 0
            if target_code != "en":
                mode = "Manglish/Hinglish" if romanize else "Native Script"
                update_status(f"🌐 Batch translating {len(segments)} lines to {target_lang} ({mode})...")
                update_progress(0, 100, "%")
                translate_batch(segments, target_code, romanize)
                update_progress(100, 100, "%")

            srt_content = "".join(f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                                  for i, s in enumerate(segments))
            base      = os.path.splitext(os.path.basename(srt_path))[0]
            suffix    = f"_{target_lang}_Romanized" if romanize else f"_{target_lang}"
            save_path = clean_path(os.path.join(config.SUB_DIR, f"{base}{suffix}.srt"))

            with open(save_path, 'w', encoding='utf-8') as f: f.write(srt_content)
            note = f"\n⚠️ {errors} errors" if errors else ""
            update_status(f"✅ Translation Done!{note}")
            update_progress(100, 100, "%")
            populate_all_tabs(save_path)
            
            # Apply subtitle to VLC
            apply_subtitle_to_vlc(app, save_path, f"✅ Translation Finished!\n{len(segments)} lines → {target_lang}{note}", clean_path(gen_video_var.get()))
        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Translation Error", str(e)))
            update_status("Error occurred.")
        finally:
            app.after(0, lambda: trans_btn.config(state=tk.NORMAL))
    threading.Thread(target=_task, daemon=True).start()


def run_auto_sync():
    srt_path   = clean_path(sync_srt_var.get().strip())
    video_path = clean_path(gen_video_var.get().strip())
    if not srt_path or not video_path: return messagebox.showerror("Error", "Select Video in Tab 1 and an SRT file here!")

    def _task():
        try:
            app.after(0, lambda: auto_sync_btn.config(state=tk.DISABLED, text="Analyzing..."))
            offset, info = detect_sync_offset(video_path, srt_path, update_status)
            if offset is None:
                app.after(0, lambda: messagebox.showerror("Auto-Sync Failed", info))
                update_status("Auto-sync failed.")
                return
            offset_str = f"{offset:+.2f}"
            app.after(0, lambda: sync_offset_var.set(offset_str))
            update_status(f"✅ Auto-detected offset: {offset_str}s")
            app.after(0, lambda: messagebox.showinfo("🎯 Auto-Sync Result", f"Detected Offset: {offset_str}s\n\n{info}\nClick 'SYNC & APPLY' to save!"))
        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Error", str(e)))
            update_status("Error.")
        finally:
            app.after(0, lambda: auto_sync_btn.config(state=tk.NORMAL, text="🔍 Auto Detect Offset"))
    threading.Thread(target=_task, daemon=True).start()


def run_sync():
    srt_path = clean_path(sync_srt_var.get().strip())
    try: offset_val = float(sync_offset_var.get().strip().replace('+', ''))
    except ValueError: return messagebox.showerror("Error", "Offset must be a number")
    if not srt_path or not os.path.exists(srt_path): return messagebox.showerror("Error", "SRT file not found!")

    def _task():
        try:
            app.after(0, lambda: sync_btn.config(state=tk.DISABLED))
            update_status("Adjusting SRT timestamps...")
            segments = parse_srt(srt_path)
            for seg in segments:
                seg['start'] = max(0, seg['start'] + offset_val)
                seg['end']   = max(0.001, seg['end'] + offset_val)
                if seg['end'] <= seg['start']: seg['end'] = seg['start'] + 0.5

            srt_content = "".join(f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                                  for i, s in enumerate(segments))
            base      = re.sub(r'_synced$', '', os.path.splitext(os.path.basename(srt_path))[0])
            save_path = clean_path(os.path.join(config.SUB_DIR, f"{base}_synced.srt"))
            with open(save_path, 'w', encoding='utf-8') as f: f.write(srt_content)

            update_status(f"✅ Sync done! Offset: {offset_val:+.2f}s")
            update_progress(100, 100, "%")
            populate_all_tabs(save_path)
            
            # Apply subtitle to VLC
            apply_subtitle_to_vlc(app, save_path, f"✅ Sync Applied!\nOffset: {offset_val:+.2f} seconds", clean_path(gen_video_var.get()))
        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Sync Error", str(e)))
            update_status("Error.")
        finally:
            app.after(0, lambda: sync_btn.config(state=tk.NORMAL))
    threading.Thread(target=_task, daemon=True).start()


def pick_color(var, btn):
    initial = var.get() if var.get().startswith('#') else '#ffffff'
    result  = colorchooser.askcolor(color=initial, title="Pick Color")
    if result and result[1]:
        var.set(result[1])
        btn.config(bg=result[1], fg="white" if result[1].lower() in ['#000000','#111111','#222222','#333333'] else "black")


def run_export_ass():
    srt_path = clean_path(custom_srt_var.get().strip())
    if not srt_path or not os.path.exists(srt_path): return messagebox.showerror("Error", "File not found!")

    def _task():
        try:
            app.after(0, lambda: export_ass_btn.config(state=tk.DISABLED))
            update_status("Generating styled ASS subtitle...")
            segments = parse_srt(srt_path)
            if not segments: raise Exception("Could not parse SRT file.")

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
            base        = os.path.splitext(os.path.basename(srt_path))[0]
            ass_path    = clean_path(os.path.join(config.SUB_DIR, f"{base}_styled.ass"))
            with open(ass_path, 'w', encoding='utf-8') as f: f.write(ass_content)

            update_status("✅ Styled ASS subtitle exported!")
            update_progress(100, 100, "%")
            
            # Apply subtitle to VLC
            apply_subtitle_to_vlc(app, ass_path, "✅ Styled Subtitle Exported as .ASS", clean_path(gen_video_var.get()))
        except Exception as e:
            app.after(0, lambda: messagebox.showerror("Export Error", str(e)))
            update_status("Error.")
        finally:
            app.after(0, lambda: export_ass_btn.config(state=tk.NORMAL))
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

def browse_srt(var):
    f = filedialog.askopenfilename(filetypes=[("Subtitles", "*.srt *.ass")])
    if f: var.set(clean_path(f))

def browse_video(var):
    f = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mkv *.avi *.ts *.mov *.wmv")])
    if f: var.set(clean_path(f))


# ============================================================
# MAIN APPLICATION STARTUP
# ============================================================
if __name__ == '__main__':
    # UI SETUP
    app = tk.Tk()
    app.title("Universal Subtitles Toolkit (VLC Edition)")
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
    style.configure("Orange.Horizontal.TProgressbar", background=config.VLC_ORANGE, troughcolor="white", bordercolor="white", lightcolor=config.VLC_ORANGE, darkcolor=config.VLC_ORANGE)

    provider_var      = tk.StringVar(value="Offline (Local - No API Key)")
    offline_model_var = tk.StringVar(value=config.DEFAULT_OFFLINE_MODEL)
    api_key_var       = tk.StringVar(value=load_api_key())

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
    tk.Label(hdr, text="UNIVERSAL SUBTITLE TOOLKIT", bg=config.DARK_BG, fg=config.VLC_ORANGE, font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
    
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
    tk.Label(frame_gen, text="Provider & API Key:", bg=config.PANEL_BG, fg="white", font=("Segoe UI", 9)).pack(pady=(12, 2))
    provider_cb = ttk.Combobox(frame_gen, textvariable=provider_var, values=["Offline (Local - No API Key)", "Groq (Lightning Fast)", "OpenAI (Standard)"], state="readonly", width=40)
    provider_cb.pack()

    dynamic_frame = tk.Frame(frame_gen, bg=config.PANEL_BG)
    dynamic_frame.pack(pady=4)

    f_api = tk.Frame(dynamic_frame, bg=config.PANEL_BG)
    tk.Entry(f_api, textvariable=api_key_var, show="*", width=35, bg=config.DARK_BG, fg="white", insertbackground="white", border=0).pack(side=tk.LEFT, ipady=3, padx=(0, 5))

    def on_save_key():
        key = api_key_var.get().strip()
        if key:
            save_api_key(key)
            messagebox.showinfo("Saved", "API Key saved securely!")
        else:
            messagebox.showwarning("Empty", "Please paste an API key first.")

    tk.Button(f_api, text="💾 Save", bg="#333", fg="white", relief=tk.FLAT, command=on_save_key, padx=5).pack(side=tk.LEFT)

    f_model_container = tk.Frame(dynamic_frame, bg=config.PANEL_BG)
    f_model = tk.Frame(f_model_container, bg=config.PANEL_BG)
    f_model.pack()
    tk.Label(f_model, text="Model Size:", bg=config.PANEL_BG, fg="#ccc", font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 5))
    ttk.Combobox(f_model, textvariable=offline_model_var, values=list(config.OFFLINE_MODEL_SIZES.keys()), state="readonly", width=25).pack(side=tk.LEFT, padx=(0, 5))

    def on_download_model():
        model_name_ui = offline_model_var.get()
        model_size = config.OFFLINE_MODEL_SIZES.get(model_name_ui, "medium")
        
        def _dl_task():
            config.CANCEL_DOWNLOAD = False
            app.after(0, lambda: update_progress(0, 100))
            app.after(0, lambda: dl_btn.config(state=tk.DISABLED))
            app.after(0, lambda: del_btn.config(state=tk.DISABLED))
            app.after(0, lambda: cancel_btn.config(state=tk.NORMAL))
            
            try:
                from engines import download_offline_model
                success = download_offline_model(model_size, update_status, update_progress)
                if success:
                    app.after(0, lambda: messagebox.showinfo("Success", f"Model '{model_size}' downloaded successfully!"))
            except Exception as e:
                if "cancelled" in str(e).lower():
                    pass  
                else:
                    app.after(0, lambda: messagebox.showerror("Download Error", str(e)))
            finally:
                app.after(0, lambda: dl_btn.config(state=tk.NORMAL))
                app.after(0, lambda: del_btn.config(state=tk.NORMAL))
                app.after(0, lambda: cancel_btn.config(state=tk.DISABLED))
                
        threading.Thread(target=_dl_task, daemon=True).start()

    def on_cancel_download():
        config.CANCEL_DOWNLOAD = True
        dl_btn.config(state=tk.NORMAL)
        del_btn.config(state=tk.NORMAL)
        cancel_btn.config(state=tk.DISABLED)
        update_status("Download cancelled.")
        update_progress(0, 100)

    def on_delete_model():
        model_name_ui = offline_model_var.get()
        model_size = config.OFFLINE_MODEL_SIZES.get(model_name_ui, "medium")
        
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete the '{model_size}' model?\nYou will have to download it again to use offline transcription."):
            try:
                from engines import delete_offline_model
                deleted = delete_offline_model(model_size)
                if deleted:
                    messagebox.showinfo("Success", f"Model '{model_size}' deleted successfully.")
                else:
                    messagebox.showinfo("Info", f"Model '{model_size}' not found or already deleted.")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    dl_btn = tk.Button(f_model, text="📥 Download", bg="#333", fg="white", relief=tk.FLAT, font=("Segoe UI", 8), command=on_download_model, padx=5)
    dl_btn.pack(side=tk.LEFT, padx=(0, 5))
    cancel_btn = tk.Button(f_model, text="⏹ Cancel", bg="#333", fg="white", relief=tk.FLAT, font=("Segoe UI", 8), command=on_cancel_download, padx=5, state=tk.DISABLED)
    cancel_btn.pack(side=tk.LEFT, padx=(0, 5))
    del_btn = tk.Button(f_model, text="🗑️ Delete", bg="#333", fg="#ff4444", relief=tk.FLAT, font=("Segoe UI", 8), command=on_delete_model, padx=5)
    del_btn.pack(side=tk.LEFT)

    model_loc_path = os.path.join(os.path.expanduser("~"), ".cache", "universalsubtitles", "models")
    f_loc = tk.Frame(f_model_container, bg=config.PANEL_BG)
    f_loc.pack(pady=(4, 0))
    model_loc_label = tk.Label(f_loc, text=f"Location: {model_loc_path}", bg=config.PANEL_BG, fg="#777", font=("Segoe UI", 7))
    model_loc_label.pack(side=tk.LEFT)

    def _open_folder():
        if os.path.exists(model_loc_path):
            os.startfile(model_loc_path)
        else:
            os.makedirs(model_loc_path, exist_ok=True)
            os.startfile(model_loc_path)

    tk.Button(f_loc, text="📂 Open Folder", bg="#444", fg="white", relief=tk.FLAT, font=("Segoe UI", 7), command=_open_folder, padx=4, pady=0).pack(side=tk.LEFT, padx=(5,0))

    def update_dynamic_ui(*args):
        if "Offline" in provider_var.get():
            f_api.pack_forget()
            f_model_container.pack()
        else:
            f_model_container.pack_forget()
            f_api.pack()

    provider_var.trace_add("write", update_dynamic_ui)
    update_dynamic_ui()  
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
    tk.Label(frame_custom, text="ASS format = full styling in VLC", bg=config.PANEL_BG, fg="#555", font=("Segoe UI", 8)).pack()

    bot = tk.Frame(app, bg=config.DARK_BG); bot.pack(fill=tk.X, padx=20, pady=(0, 10))
    ttk.Progressbar(bot, variable=progress_var, maximum=100, length=520, mode='determinate', style="Orange.Horizontal.TProgressbar").pack()
    progress_label = tk.Label(bot, text="", bg=config.DARK_BG, fg=config.VLC_ORANGE, font=("Segoe UI", 9)); progress_label.pack()
    status_label = tk.Label(bot, text="Status: Ready", bg=config.DARK_BG, fg="#888", font=("Segoe UI", 9)); status_label.pack()

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
    app.mainloop()