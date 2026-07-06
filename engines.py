import re
import time
import requests
import subprocess
import os
import sys
import math
from deep_translator import GoogleTranslator

# --- UPDATED: Added get_ffmpeg_path ---
from utils import parse_srt, resource_path, get_ffmpeg_path
import ust_settings as config

# ============================================================
# OFFLINE TRANSCRIPTION (faster-whisper)
# ============================================================

# Cache the loaded model so we don't reload it for every chunk
_offline_model_cache = {"model": None, "model_size": None}

def get_offline_model_dir():
    """Get the directory where offline whisper models are stored."""
    model_dir = os.path.join(os.path.expanduser("~"), ".cache", "universalsubtitles", "models")
    os.makedirs(model_dir, exist_ok=True)
    return model_dir

def check_offline_available():
    """Check if faster-whisper is installed."""
    try:
        import faster_whisper
        return True
    except ImportError:
        return False

def transcribe_offline(chunk_path, model_size="medium", source_lang=None, status_callback=None, progress_callback=None):
    """
    Transcribe audio using faster-whisper (local, offline).
    Auto-detects NVIDIA GPU and uses CUDA if available, otherwise CPU.
    Returns data in the same format as the API response for compatibility.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise Exception(
            "Offline transcription requires 'faster-whisper'.\n\n"
            "Please install it:\n"
            "  pip install faster-whisper\n\n"
            "For GPU acceleration, also install CUDA toolkit."
        )

    # Load or reuse cached model
    if _offline_model_cache["model"] is None or _offline_model_cache["model_size"] != model_size:
        model_dir = get_offline_model_dir()
        
        # --- Monkey Patch tqdm to get download progress ---
        original_tqdm = None
        try:
            import tqdm.auto
            original_tqdm = tqdm.auto.tqdm
            
            class CustomTqdm(original_tqdm):
                def update(self, n=1):
                    super().update(n)
                    if self.total and progress_callback and status_callback:
                        pct = int((self.n / self.total) * 100)
                        # Ensure we don't spam updates for small changes, just general progress
                        if hasattr(self, '_last_pct') and self._last_pct == pct:
                            return
                        self._last_pct = pct
                        mb_done = int(self.n / (1024 * 1024))
                        mb_total = int(self.total / (1024 * 1024))
                        status_callback(f"Downloading model... {pct}% ({mb_done}MB / {mb_total}MB)")
                        progress_callback(pct, 100, "%")
            
            tqdm.auto.tqdm = CustomTqdm
        except Exception:
            pass # Ignore patching errors

        # Attempt to load with CUDA (GPU), fallback to CPU if no compatible GPU
        try:
            if status_callback:
                status_callback(f"Trying to load '{model_size}' model on GPU...")
            model = WhisperModel(
                model_size,
                device="cuda",
                compute_type="float16",
                download_root=model_dir
            )
            if status_callback:
                status_callback("🚀 Loaded on GPU successfully!")
        except Exception:
            if status_callback:
                status_callback(f"GPU not available or failed. Loading '{model_size}' on CPU...")
            model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8",
                download_root=model_dir
            )
        
        # --- Restore tqdm ---
        if original_tqdm:
            try:
                tqdm.auto.tqdm = original_tqdm
            except: pass

        _offline_model_cache["model"] = model
        _offline_model_cache["model_size"] = model_size
    else:
        model = _offline_model_cache["model"]

    # Transcribe
    transcribe_kwargs = {
        "beam_size": 5,
        "vad_filter": True,  # Voice Activity Detection — skips silence, much faster
        "vad_parameters": {"min_silence_duration_ms": 500}
    }
    if source_lang:
        transcribe_kwargs["language"] = source_lang

    segments_gen, info = model.transcribe(chunk_path, **transcribe_kwargs)

    # Convert to the same format as the API response
    segments_list = []
    for seg in segments_gen:
        text = seg.text.strip()
        if text:
            segments_list.append({
                "start": seg.start,
                "end": seg.end,
                "text": text
            })

    return {"segments": segments_list}


def check_offline_model_exists(model_size):
    """Check if the specific offline model is already downloaded."""
    model_dir = get_offline_model_dir()
    # model storage uses this format typically for huggingface hub downloads
    expected_dir = os.path.join(model_dir, f"models--Systran--faster-whisper-{model_size}")
    return os.path.exists(expected_dir)


def download_offline_model(model_size, status_callback=None, progress_callback=None):
    """Download an offline model with real progress and cancel support."""
    if check_offline_model_exists(model_size):
        if status_callback: status_callback(f"Model '{model_size}' is already downloaded.")
        if progress_callback: progress_callback(100, 100, "%")
        return True

    model_dir = get_offline_model_dir()
    repo_id = f"Systran/faster-whisper-{model_size}"

    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError:
        raise Exception("huggingface_hub is not installed.")

    if status_callback: status_callback(f"Fetching file list for '{model_size}' model...")
    if progress_callback: progress_callback(0, 100, "%")

    # Get list of files in the model repo
    api = HfApi()
    repo_files = api.list_repo_files(repo_id)

    total_files = len(repo_files)
    
    import tqdm.auto
    import inspect
    import huggingface_hub.file_download
    
    class DownloadTqdm(tqdm.auto.tqdm):
        current_i = 0
        total_files_cnt = 1
        current_filename = ""
        
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._last_pct = -1
            
        def update(self, n=1):
            super().update(n)
            if self.total and progress_callback and status_callback:
                file_pct = self.n / self.total
                overall_pct = int(((self.__class__.current_i + file_pct) / self.__class__.total_files_cnt) * 100)
                
                if getattr(config, 'CANCEL_DOWNLOAD', False):
                    raise Exception("Download cancelled by user.")
                    
                if self._last_pct == overall_pct:
                    return
                self._last_pct = overall_pct
                
                mb_done = int(self.n / (1024 * 1024))
                mb_total = int(self.total / (1024 * 1024))
                
                status_callback(f"Downloading file {self.__class__.current_i+1}/{self.__class__.total_files_cnt}: {self.__class__.current_filename} ({mb_done}MB / {mb_total}MB)")
                progress_callback(overall_pct, 100, "%")

    for i, filename in enumerate(repo_files):
        # Check cancel between each file
        if getattr(config, 'CANCEL_DOWNLOAD', False):
            raise Exception("Download cancelled by user.")

        DownloadTqdm.current_i = i
        DownloadTqdm.total_files_cnt = total_files
        DownloadTqdm.current_filename = filename

        pct = int((i / total_files) * 100)
        if status_callback: status_callback(f"Downloading file {i+1}/{total_files}: {filename}")
        if progress_callback: progress_callback(pct, 100, "%")

        kwargs = {}
        if 'tqdm_class' in inspect.signature(hf_hub_download).parameters:
            kwargs['tqdm_class'] = DownloadTqdm

        original_tqdm_fd = getattr(huggingface_hub.file_download, 'tqdm', None)
        if original_tqdm_fd is not None:
            setattr(huggingface_hub.file_download, 'tqdm', DownloadTqdm)

        try:
            hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                cache_dir=model_dir,
                **kwargs
            )
        finally:
            if original_tqdm_fd is not None:
                setattr(huggingface_hub.file_download, 'tqdm', original_tqdm_fd)

    if status_callback: status_callback("✅ Model downloaded successfully!")
    if progress_callback: progress_callback(100, 100, "%")
    return True


def delete_offline_model(model_size):
    """Delete the downloaded model to save space."""
    import shutil
    model_dir = get_offline_model_dir()
    prefix = f"models--Systran--faster-whisper-{model_size}"
    deleted = False
    
    if os.path.exists(model_dir):
        for item in os.listdir(model_dir):
            if item == prefix or item.endswith(f"faster-whisper-{model_size}"):
                path = os.path.join(model_dir, item)
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    deleted = True
                except Exception:
                    pass
                
    # Also clear cache if it was loaded
    if _offline_model_cache["model_size"] == model_size:
        _offline_model_cache["model"] = None
        _offline_model_cache["model_size"] = None
        
    return deleted


# ============================================================
# API TRANSCRIPTION (Groq / OpenAI) — with retry on rate limit
# ============================================================

def transcribe_audio_chunk(chunk_path, provider, api_key, source_lang=None):
    url   = ("https://api.groq.com/openai/v1/audio/transcriptions"
              if "Groq" in provider else "https://api.openai.com/v1/audio/transcriptions")
    model = "whisper-large-v3" if "Groq" in provider else "whisper-1"

    data = {"model": model, "response_format": "verbose_json"}
    if source_lang:
        data["language"] = source_lang

    max_retries = 4
    for attempt in range(max_retries):
        try:
            with open(chunk_path, "rb") as f:
                response = requests.post(
                    url, headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (os.path.basename(chunk_path), f, "audio/mp4")},
                    data=data, timeout=300
                )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                # Rate limited — wait with exponential backoff and retry
                wait_time = min(30, (2 ** attempt) * 5)  # 5s, 10s, 20s, 30s
                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                    continue
                else:
                    raise Exception(
                        f"{provider} API Rate Limit: You've hit the usage quota.\n\n"
                        "💡 Solutions:\n"
                        "• Wait a few minutes and try again\n"
                        "• Switch to 'Offline (Local)' mode — no limits!\n"
                        "• Check your Groq/OpenAI plan & billing"
                    )
            elif response.status_code == 401:
                raise Exception(f"{provider} API Error: Invalid API Key. Please verify your credentials.")
            else:
                raise Exception(f"API Error {response.status_code}:\n{response.text[:400]}")

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise Exception(f"{provider} API timed out after multiple attempts. Try 'Offline (Local)' mode for large files.")
        except requests.exceptions.ConnectionError:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise Exception("Network connection error. Check your internet connection or use 'Offline (Local)' mode.")

    # Should not reach here, but just in case
    raise Exception(f"Failed to transcribe after {max_retries} attempts.")


# ============================================================
# TRANSLATION — with batching and exponential backoff
# ============================================================

def split_text_for_translation(text, max_chars=3000):
    if len(text) <= max_chars: return [text]
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
    """Translate a single text chunk with exponential backoff retry."""
    max_retries = 4
    for attempt in range(max_retries):
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
                elif resp.status_code == 429:
                    # Google rate limited — wait longer
                    wait_time = min(30, (2 ** attempt) * 2)  # 2s, 4s, 8s, 16s
                    time.sleep(wait_time)
                    continue
        except Exception:
            wait_time = min(15, (2 ** attempt) * 1.5)  # 1.5s, 3s, 6s, 12s
            time.sleep(wait_time)
    return text  # Return original if all retries fail

def translate_text(eng_text, target_code, romanize=False):
    if target_code == "en" or not eng_text.strip():
        return eng_text
    chunks = split_text_for_translation(eng_text, config.MAX_CHARS_PER_CHUNK)
    return " ".join(translate_single_chunk(c, target_code, romanize) for c in chunks)

def translate_batch(segments, target_code, romanize=False, batch_size=None):
    """
    Translate subtitle segments in batches for 10x fewer API calls.
    Uses concurrent.futures for lightning fast parallel translation.
    
    Returns the segments list with translated text in-place.
    """
    if target_code == "en":
        return segments

    if batch_size is None:
        batch_size = config.TRANSLATION_BATCH_SIZE

    SEPARATOR = " ||| "
    total = len(segments)
    
    import concurrent.futures

    def process_batch(batch_start):
        batch_end = min(batch_start + batch_size, total)
        batch = segments[batch_start:batch_end]
        combined = SEPARATOR.join(seg["text"] for seg in batch)
        translated = translate_single_chunk(combined, target_code, romanize)
        
        result_batch = []
        if translated and SEPARATOR in translated:
            parts = translated.split(SEPARATOR)
            if len(parts) == len(batch):
                for i, part in enumerate(parts):
                    result_batch.append((batch_start + i, part.strip()))
                return result_batch
                
        # Fallback: translate individually if the separator gets mangled
        for i, seg in enumerate(batch):
            result_batch.append((batch_start + i, translate_single_chunk(seg["text"], target_code, romanize)))
        return result_batch

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.MAX_TRANSLATION_WORKERS) as executor:
        futures = [executor.submit(process_batch, start) for start in range(0, total, batch_size)]
        for future in concurrent.futures.as_completed(futures):
            for idx, text in future.result():
                segments[idx]["text"] = text

    return segments


# ============================================================
# SYNC DETECTION (Fixed)
# ============================================================

def detect_sync_offset(video_path, srt_path, status_callback=None):
    segments = parse_srt(srt_path)
    if not segments: return None, "No subtitles found in file."

    first_sub_time = segments[0]['start']
    if status_callback:
        status_callback("Analyzing audio for auto-sync (may take ~30s)...")

    try:
        cf  = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        # Use our new foolproof path finder
        ffmpeg_path = get_ffmpeg_path()
        
        cmd = [
            ffmpeg_path, "-i", video_path, "-t", "300",
            "-af", "silencedetect=noise=-35dB:d=0.3", "-f", "null", "-"
        ]
        
        try:
            result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                                    creationflags=cf, timeout=120)
        except FileNotFoundError:
            return None, "ffmpeg.exe is missing! Please make sure ffmpeg.exe is in the application folder."
            
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
    """
    Fetch an online subtitle using subliminal (hash based).
    Returns path to downloaded SRT if successful, None otherwise.
    """
    try:
        from subliminal import download_best_subtitles, region, scan_video
        from babelfish import Language
    except ImportError:
        raise Exception("Subliminal is not installed. Run 'pip install subliminal'")
        
    if status_callback: status_callback("Scanning video hash...")
    
    # Configure cache (only once; ignore if already configured)
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "universalsubtitles", "subliminal")
    os.makedirs(cache_dir, exist_ok=True)
    try:
        region.configure('dogpile.cache.dbm', arguments={'filename': os.path.join(cache_dir, 'cache.dbm')})
    except Exception:
        pass  # already configured
    
    video = scan_video(video_path)
    if not video:
        raise Exception("Could not parse video metadata for hash.")
        
    if status_callback: status_callback(f"Searching for '{target_lang}' subtitles online...")
    
    # babelfish needs 3-letter ISO-639-3 codes (e.g. "eng"), not 2-letter (e.g. "en")
    # Use fromalpha2() for 2-letter codes, fall back to direct constructor for 3-letter
    try:
        lang = Language.fromalpha2(target_lang)
    except Exception:
        try:
            lang = Language(target_lang)
        except Exception:
            lang = Language('eng')  # ultimate fallback
    
    langs = {lang}
    
    # Try downloading best subtitles
    subtitles = download_best_subtitles([video], langs)
    
    if video in subtitles and subtitles[video]:
        best_sub = subtitles[video][0]
        if status_callback: status_callback("Saving subtitle...")
        
        # Write the subtitle content directly to our output path
        base = os.path.splitext(os.path.basename(video_path))[0]
        out_path = os.path.join(config.SUB_DIR, f"{base}_{target_lang}_online.srt")
        
        # Get the raw subtitle content and write it ourselves
        content = best_sub.content
        if content:
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='replace')
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(content)
            if status_callback: status_callback(f"✅ Subtitle downloaded instantly!")
            return out_path
        
        # Fallback: use subliminal's save mechanism
        from subliminal.core import save_subtitles
        save_subtitles(video, [best_sub], single=True, directory=config.SUB_DIR, encoding='utf-8')
        
        # Find the saved file
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