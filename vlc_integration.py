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

def install_vlc_extension(app):
    # 1. Locate the .lua file bundled inside the PyInstaller executable
    lua_source = resource_path("universal_subtitles.lua")
    if not os.path.exists(lua_source):
        return messagebox.showerror("Error", "Could not find universal_subtitles.lua inside the application files.")

    # 2. Get the REAL AppData path (Bypassing the MSIX Sandbox)
    # os.getenv('APPDATA') points to the sandbox. expanduser('~') points to the real C:\Users\Username
    real_appdata = os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
    default_vlc_path = os.path.join(real_appdata, 'vlc', 'lua', 'extensions')

    # 3. Pre-create the VLC folders so the user doesn't have to
    try:
        os.makedirs(default_vlc_path, exist_ok=True)
    except Exception:
        pass

    # 4. Explain what is happening to the user
    msg = (
        "To use the extension in VLC, we need to copy it to VLC's plugin folder.\n\n"
        "In the next window, the correct folder should already be selected. "
        "Just click 'Select Folder' to allow the installation."
    )
    messagebox.showinfo("Install VLC Extension", msg, parent=app)

    # 5. Open Directory Picker (Because the user manually clicks "Select", Windows allows it to bypass the sandbox)
    target_dir = filedialog.askdirectory(
        initialdir=default_vlc_path if os.path.exists(default_vlc_path) else real_appdata,
        title="Select VLC Extensions Folder",
        parent=app
    )

    if not target_dir:
        return # User clicked Cancel

    # 6. Copy the file
    try:
        destination_file = os.path.join(target_dir, "universal_subtitles.lua")
        shutil.copy2(lua_source, destination_file)
        messagebox.showinfo(
            "✅ Installation Complete", 
            f"Extension successfully installed to:\n{destination_file}\n\n"
            "Please completely close and restart VLC Player to see it under the 'View' menu.", 
            parent=app
        )
    except Exception as e:
        messagebox.showerror("Installation Failed", f"Could not copy file:\n{str(e)}", parent=app)