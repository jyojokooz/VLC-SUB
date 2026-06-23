import re
import time
import requests
import subprocess
import os
from deep_translator import GoogleTranslator
from utils import parse_srt
import config

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
    chunks = split_text_for_translation(eng_text, config.MAX_CHARS_PER_CHUNK)
    return " ".join(translate_single_chunk(c, target_code, romanize) for c in chunks)

def transcribe_audio_chunk(chunk_path, provider, api_key, source_lang=None):
    url   = ("https://api.groq.com/openai/v1/audio/transcriptions"
              if "Groq" in provider else "https://api.openai.com/v1/audio/transcriptions")
    model = "whisper-large-v3" if "Groq" in provider else "whisper-1"

    data = {"model": model, "response_format": "verbose_json"}
    if source_lang:
        data["language"] = source_lang

    with open(chunk_path, "rb") as f:
        response = requests.post(
            url, headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (os.path.basename(chunk_path), f, "audio/mp4")},
            data=data, timeout=300
        )
    if response.status_code != 200:
        raise Exception(f"API Error {response.status_code}:\n{response.text[:400]}")
    return response.json()

def detect_sync_offset(video_path, srt_path, status_callback=None):
    segments = parse_srt(srt_path)
    if not segments: return None, "No subtitles found in file."

    first_sub_time = segments[0]['start']
    if status_callback:
        status_callback("Analyzing audio for auto-sync (may take ~30s)...")

    try:
        cf  = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        cmd = [
            "ffmpeg", "-i", video_path, "-t", "300",
            "-af", "silencedetect=noise=-35dB:d=0.3", "-f", "null", "-"
        ]
        result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                                creationflags=cf, timeout=120)
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