import os
import subprocess
import shutil
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
from utils import clean_path, resource_path

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
        messagebox.showerror("VLC Preview", "No valid video file selected.\nPlease select a video in Tab 1 first!")
        return
    if not srt_path or not os.path.exists(srt_path):
        messagebox.showerror("VLC Preview", f"No valid subtitle file found at:\n{srt_path}")
        return
        
    vlc = get_vlc_path()
    if not vlc:
        messagebox.showerror("VLC Not Found", "Could not locate vlc.exe.\nPlease ensure VLC is installed in the default directory.")
        return
        
    try:
        cf = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        vid = clean_path(video_path)
        sub = clean_path(srt_path)
        
        # Using a raw string guarantees VLC parses the quotes properly on Windows!
        cmd = f'"{vlc}" --one-instance --no-playlist-enqueue "{vid}" --sub-file="{sub}"'
        
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=cf
        )
    except Exception as e:
        messagebox.showerror("Error", f"Could not launch VLC:\n{e}")

def apply_subtitle_to_vlc(app, subtitle_path, success_message, video_path=None):
    def _execute():
        if video_path and os.path.exists(video_path):
            # Launch VLC seamlessly
            launch_vlc_preview(video_path, subtitle_path)
            # Show success prompt AFTER commanding VLC to open
            messagebox.showinfo("✅ Success", f"{success_message}\n\n▶️ Subtitle sent to VLC Player!")
        else:
            try:
                if os.name == 'nt':
                    cf = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    cmd = f'explorer /select,"{clean_path(subtitle_path)}"'
                    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=cf)
            except Exception:
                pass
            messagebox.showinfo("✅ Success", f"{success_message}\n\n📌 TO APPLY IN VLC:\nThe file is highlighted in Explorer.\nDRAG & DROP it into your VLC window!")

    app.after(0, _execute)

def get_vlc_ext_path():
    """Helper to get the exact path where the Lua extension should live."""
    return os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming', 'vlc', 'lua', 'extensions', 'universal_subtitles.lua')

def install_vlc_extension(app):
    lua_source = resource_path("universal_subtitles.lua")
    if not os.path.exists(lua_source):
        return messagebox.showerror("Error", "Could not find universal_subtitles.lua inside the application files.")

    ext_file = get_vlc_ext_path()
    target_dir = os.path.dirname(ext_file)

    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception:
        pass

    msg = "This will install the auto-load extension directly into VLC's plugin folder.\n\nClick OK to install it automatically."
    if messagebox.askokcancel("Install VLC Extension", msg, parent=app):
        try:
            shutil.copy2(lua_source, ext_file)
            messagebox.showinfo("✅ Installation Complete", f"Extension installed successfully!\n\nPlease completely close and restart VLC Player.", parent=app)
        except Exception as e:
            messagebox.showerror("Installation Failed", f"Could not copy file:\n{str(e)}", parent=app)

def remove_vlc_extension(app):
    ext_file = get_vlc_ext_path()
    if os.path.exists(ext_file):
        if messagebox.askokcancel("Remove Extension", "Are you sure you want to remove the VLC extension?", parent=app):
            try:
                os.remove(ext_file)
                messagebox.showinfo("✅ Removed", "The VLC Extension was successfully removed.\n\nPlease completely close and restart VLC Player.", parent=app)
            except Exception as e:
                messagebox.showerror("Error", f"Could not remove extension:\n{e}", parent=app)