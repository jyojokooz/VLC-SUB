import os
import subprocess
from utils import clean_path, get_ffmpeg_path

def reframe_video(video_path, target_ratio="9:16", mode="Blurred Background (Professional)"):
    video_path = clean_path(video_path)
    if not os.path.exists(video_path):
        raise FileNotFoundError("Video not found.")

    # Parse ratio (e.g., "9:16" -> w=9, h=16)
    try:
        r_w, r_h = target_ratio.split(':')
    except:
        r_w, r_h = "9", "16"

    # Calculate target dimensions that enclose the original video
    # ceil(.../2)*2 ensures the dimensions are even numbers (required by h264)
    tw = f"ceil(max(iw,ih*{r_w}/{r_h})/2)*2"
    th = f"ceil(max(ih,iw*{r_h}/{r_w})/2)*2"

    if mode == "Center Crop (Fill)":
        # Scale to fill the bounding box, then crop to exact box
        vf = f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th}"
    else:
        # Blurred Background (Professional)
        vf = (
            f"[0:v]split=2[bg_in][fg_in];"
            f"[bg_in]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},boxblur=20:20[bg];"
            f"[fg_in]scale={tw}:{th}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )

    base, ext = os.path.splitext(video_path)
    safe_ratio = target_ratio.replace(':', 'x')
    safe_mode = mode.split(' ')[0].lower()
    out_path = f"{base}_reframed_{safe_ratio}_{safe_mode}{ext}"

    ffmpeg_path = get_ffmpeg_path()
    cmd = [
        ffmpeg_path, "-y", "-i", video_path,
        "-filter_complex" if "[0:v]" in vf else "-vf", vf,
        "-c:a", "copy", out_path
    ]

    cf = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=cf)

    if proc.returncode != 0:
        err_msg = proc.stderr.decode('utf-8', errors='ignore')
        raise Exception(f"FFmpeg reframing failed:\n{err_msg[-500:]}")

    return out_path
