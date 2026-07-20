import re
import time
import requests
import subprocess
import os
from deep_translator import GoogleTranslator
from utils import parse_srt, get_ffmpeg_path
import ust_settings as config

# ============================================================
# API TRANSCRIPTION (Groq / OpenAI / Custom)
# ============================================================

def transcribe_audio_chunk(chunk_path, provider, api_key, source_lang=None, custom_url=None):
    if "Groq" in provider:
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        model = "whisper-large-v3"
    elif "OpenAI" in provider:
        url = "https://api.openai.com/v1/audio/transcriptions"
        model = "whisper-1"
    else: # Custom API (OpenAI Format)
        url = custom_url if custom_url else "https://api.openai.com/v1/audio/transcriptions"
        model = "whisper-1"

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
                wait_time = min(30, (2 ** attempt) * 5)
                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                    continue
                else:
                    raise Exception(
                        f"{provider} API Rate Limit: You've hit the usage quota.\n\n"
                        "💡 Solutions:\n"
                        "• Wait a few minutes and try again\n"
                        "• Check your API provider plan & billing"
                    )
            elif response.status_code == 401:
                raise Exception(f"{provider} API Error: Invalid API Key. Please verify your credentials.")
            else:
                raise Exception(f"API Error {response.status_code}:\n{response.text[:400]}")

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise Exception(f"{provider} API timed out after multiple attempts.")
        except requests.exceptions.ConnectionError:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise Exception("Network connection error. Check your internet connection or URL.")

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
                    wait_time = min(30, (2 ** attempt) * 2)
                    time.sleep(wait_time)
                    continue
        except Exception:
            wait_time = min(15, (2 ** attempt) * 1.5)
            time.sleep(wait_time)
    return text

def translate_text(eng_text, target_code, romanize=False):
    if target_code == "en" or not eng_text.strip():
        return eng_text
    chunks = split_text_for_translation(eng_text, config.MAX_CHARS_PER_CHUNK)
    return " ".join(translate_single_chunk(c, target_code, romanize) for c in chunks)

def translate_batch(segments, target_code, romanize=False, batch_size=None):
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
# SYNC DETECTION
# ============================================================

def detect_sync_offset(video_path, srt_path, status_callback=None):
    segments = parse_srt(srt_path)
    if not segments: return None, "No subtitles found in file."

    first_sub_time = segments[0]['start']
    if status_callback:
        status_callback("Analyzing audio for auto-sync (may take ~30s)...")

    try:
        cf  = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        ffmpeg_path = get_ffmpeg_path()
        
        cmd = [
            ffmpeg_path, "-i", video_path, "-t", "300",
            "-af", "silencedetect=noise=-35dB:d=0.3", "-f", "null", "-"
        ]
        
        try:
            result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                                    creationflags=cf, timeout=120)
        except FileNotFoundError:
            return None, "ffmpeg.exe is missing! Please make sure it is properly bundled with the application."
            
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
    try:
        from subliminal import download_best_subtitles, region, scan_video
        from babelfish import Language
    except ImportError:
        raise Exception("Subliminal is not installed. Run 'pip install subliminal'")
        
    if status_callback: status_callback("Scanning video hash...")
    
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "universalsubtitles", "subliminal")
    os.makedirs(cache_dir, exist_ok=True)
    try:
        region.configure('dogpile.cache.dbm', arguments={'filename': os.path.join(cache_dir, 'cache.dbm')})
    except Exception:
        pass  
    
    video = scan_video(video_path)
    if not video:
        raise Exception("Could not parse video metadata for hash.")
        
    if status_callback: status_callback(f"Searching for '{target_lang}' subtitles online...")
    
    try:
        lang = Language.fromalpha2(target_lang)
    except Exception:
        try:
            lang = Language(target_lang)
        except Exception:
            lang = Language('eng')  
    
    langs = {lang}
    subtitles = download_best_subtitles([video], langs)
    
    if video in subtitles and subtitles[video]:
        best_sub = subtitles[video][0]
        if status_callback: status_callback("Saving subtitle...")
        
        base = os.path.splitext(os.path.basename(video_path))[0]
        out_path = os.path.join(config.SUB_DIR, f"{base}_{target_lang}_online.srt")
        
        content = best_sub.content
        if content:
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='replace')
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(content)
            if status_callback: status_callback(f"✅ Subtitle downloaded instantly!")
            return out_path
        
        from subliminal.core import save_subtitles
        save_subtitles(video, [best_sub], single=True, directory=config.SUB_DIR, encoding='utf-8')
        
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