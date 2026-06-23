import os
import subprocess
import tkinter.messagebox as messagebox
from utils import clean_path

def get_vlc_path():
    paths = [
        os.path.join(os.environ.get('PROGRAMW6432', 'C:\\Program Files'), 'VideoLAN', 'VLC', 'vlc.exe'),
        os.path.join(os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'), 'VideoLAN', 'VLC', 'vlc.exe'),
        os.path.join(os.environ.get('PROGRAMFILES', 'C:\\Program Files'), 'VideoLAN', 'VLC', 'vlc.exe')
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

def launch_vlc_preview(video_path, srt_path):
    if not video_path or not os.path.exists(video_path):
        return messagebox.showerror("VLC Preview", "No valid video file selected.\nPlease select a video in Tab 1 first!")
    if not srt_path or not os.path.exists(srt_path):
        return messagebox.showerror("VLC Preview", "No valid subtitle file selected.")
        
    vlc = get_vlc_path()
    if not vlc:
        return messagebox.showerror("VLC Not Found", "Could not locate vlc.exe.\nPlease ensure VLC is installed in the default directory.")
        
    try:
        subprocess.Popen([vlc, video_path, f"--sub-file={srt_path}"])
    except Exception as e:
        messagebox.showerror("Error", f"Could not launch VLC:\n{e}")

def apply_subtitle_to_vlc(app, subtitle_path, success_message):
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