import os
import subprocess
from utils import clean_path, get_ffmpeg_path


def _escape_path_for_filter(path):
    """Escape a filesystem path so it's safe to drop inside an ffmpeg filtergraph
    string (Windows drive-letter colons and backslashes both need escaping)."""
    p = path.replace('\\', '/')
    p = p.replace(':', '\\:')
    p = p.replace("'", "\\'")
    return p


def burn_subtitles_into_video(video_path, ass_path):
    """Hardcode (burn-in) a styled .ass subtitle file permanently into the video's
    pixels — unlike the existing soft-sub export, this re-encodes the video so the
    subtitles can never be toggled off, similar to inpainting text onto the frames.
    Returns the path to the new video file. Existing features/files are untouched;
    this always writes to a new "_embedded" output file."""
    video_path = clean_path(video_path)
    ass_path   = clean_path(ass_path)

    if not os.path.exists(video_path):
        raise FileNotFoundError("Video not found.")
    if not os.path.exists(ass_path):
        raise FileNotFoundError("Subtitle (.ass) file not found.")

    base, ext = os.path.splitext(video_path)
    out_ext   = ext if ext.lower() in ('.mp4', '.mkv', '.mov') else '.mp4'
    out_path  = f"{base}_embedded{out_ext}"

    vf = f"ass='{_escape_path_for_filter(ass_path)}'"

    ffmpeg_path = get_ffmpeg_path()
    cmd = [
        ffmpeg_path, "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-c:a", "copy",
        out_path
    ]

    cf = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=cf)

    if proc.returncode != 0:
        err_msg = proc.stderr.decode('utf-8', errors='ignore')
        raise Exception(f"FFmpeg embedding failed:\n{err_msg[-500:]}")

    return out_path