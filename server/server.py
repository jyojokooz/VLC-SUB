"""
.Vsub Cloud Transcription Server
=================================
A load-balancing proxy that sits between .Vsub users and the AI APIs.
Users never need API keys — they call this server instead.

Deploy on:  Render (free tier), Railway, Fly.io, Heroku, etc.

Usage:
  pip install fastapi uvicorn requests python-multipart
  uvicorn server:app --host 0.0.0.0 --port 8000

Set environment variables:
  VSUB_GROQ_KEYS   = "key1,key2,key3,..."   (comma-separated Groq API keys)
  VSUB_OPENAI_KEYS = "key1,key2,..."         (optional OpenAI fallback keys)
  VSUB_SECRET      = "some-secret-token"     (optional: require from client)
  VSUB_MAX_FILE_MB = "25"                    (max upload size, default 25 MB)
"""

import os
import time
import threading
import logging
import hashlib
from collections import defaultdict
from typing import Optional

import requests
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION  (from environment variables)
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("vsub-server")

def _load_keys(env_name: str) -> list[str]:
    raw = os.getenv(env_name, "")
    return [k.strip() for k in raw.split(",") if k.strip()]

GROQ_KEYS   = _load_keys("VSUB_GROQ_KEYS")
OPENAI_KEYS = _load_keys("VSUB_OPENAI_KEYS")
SECRET      = os.getenv("VSUB_SECRET", "")        # empty = no auth required
MAX_FILE_MB = int(os.getenv("VSUB_MAX_FILE_MB", "25"))

GROQ_URL   = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"

if not GROQ_KEYS and not OPENAI_KEYS:
    log.warning(
        "⚠️  No API keys loaded. Set VSUB_GROQ_KEYS or VSUB_OPENAI_KEYS env vars."
    )

# ─────────────────────────────────────────────────────────────────────────────
# LOAD BALANCER  —  round-robin with 429/error skip & cooldown
# ─────────────────────────────────────────────────────────────────────────────
class KeyPool:
    """
    Thread-safe round-robin pool of API keys.
    Automatically cools down a key for `cooldown_secs` when it hits a 429.
    """
    def __init__(self, keys: list[str], url: str, model: str,
                 cooldown_secs: int = 60):
        self._keys      = keys
        self.url        = url
        self.model      = model
        self._cooldown  = cooldown_secs
        self._lock      = threading.Lock()
        self._idx       = 0
        # key → unix timestamp when cooldown expires (0 = ready)
        self._blocked: dict[str, float] = {k: 0.0 for k in keys}
        self._usage: dict[str, int]     = defaultdict(int)

    def _next_key(self) -> Optional[str]:
        """Return the next available key, or None if all are in cooldown."""
        now = time.time()
        with self._lock:
            n = len(self._keys)
            for _ in range(n):
                key = self._keys[self._idx % n]
                self._idx += 1
                if now >= self._blocked.get(key, 0):
                    return key
        return None          # all keys cooled

    def cooldown(self, key: str, secs: Optional[int] = None):
        """Mark a key as rate-limited."""
        wait = secs if secs else self._cooldown
        with self._lock:
            self._blocked[key] = time.time() + wait
        log.warning(f"Key ...{key[-6:]} rate-limited for {wait}s")

    def status(self) -> dict:
        now = time.time()
        return {
            "total": len(self._keys),
            "available": sum(1 for k in self._keys if now >= self._blocked.get(k, 0)),
            "url": self.url,
            "model": self.model,
        }

    def transcribe(self, audio_bytes: bytes, filename: str,
                   language: Optional[str], prompt: Optional[str]) -> dict:
        """
        Try each available key in round-robin until success or all fail.
        Returns the parsed JSON from the Whisper API.
        Raises HTTPException on total failure.
        """
        tried = 0
        last_error = "No API keys configured."

        while tried < max(len(self._keys), 1):
            key = self._next_key()
            if key is None:
                # All keys are cooling — wait briefly and retry once
                time.sleep(5)
                key = self._next_key()
                if key is None:
                    break

            tried += 1
            data: dict = {"model": self.model, "response_format": "verbose_json"}
            if language:
                data["language"] = language
            if prompt:
                data["prompt"] = prompt

            try:
                resp = requests.post(
                    self.url,
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": (filename, audio_bytes, "audio/mp4")},
                    data=data,
                    timeout=180,
                )
            except requests.exceptions.RequestException as exc:
                last_error = f"Network error: {exc}"
                log.error(f"Key ...{key[-6:]} → {last_error}")
                continue

            if resp.status_code == 200:
                self._usage[key] += 1
                log.info(f"Key ...{key[-6:]} → OK  (uses={self._usage[key]})")
                return resp.json()

            elif resp.status_code == 429:
                # Parse Retry-After if present
                retry_after = resp.headers.get("Retry-After")
                secs = int(retry_after) if retry_after and retry_after.isdigit() else None
                self.cooldown(key, secs)
                last_error = "Rate limited (429)"
                continue

            elif resp.status_code in (401, 403):
                # Bad key — remove from rotation permanently this session
                self.cooldown(key, 86400)  # 24h
                last_error = f"Auth error {resp.status_code}: bad API key"
                log.error(f"Key ...{key[-6:]} invalid — blocked for 24h")
                continue

            else:
                last_error = f"API error {resp.status_code}: {resp.text[:200]}"
                log.warning(f"Key ...{key[-6:]} → {last_error}")
                continue

        raise HTTPException(
            status_code=503,
            detail=(
                f"All API keys exhausted or rate-limited. Last error: {last_error}\n"
                "Please try again in a minute."
            ),
        )


# Build pools
_groq_pool   = KeyPool(GROQ_KEYS,   GROQ_URL,   "whisper-large-v3") if GROQ_KEYS   else None
_openai_pool = KeyPool(OPENAI_KEYS, OPENAI_URL,  "whisper-1")        if OPENAI_KEYS else None


# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITING PER CLIENT IP  (simple in-memory, resets on restart)
# ─────────────────────────────────────────────────────────────────────────────
_ip_lock    = threading.Lock()
_ip_calls   = defaultdict(list)   # ip → [timestamps of recent calls]
IP_LIMIT    = int(os.getenv("VSUB_IP_LIMIT_PER_HOUR", "30"))  # calls/hour/IP

def _check_ip_limit(ip: str):
    now = time.time()
    cutoff = now - 3600
    with _ip_lock:
        calls = [t for t in _ip_calls[ip] if t > cutoff]
        if len(calls) >= IP_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"Free tier limit: {IP_LIMIT} transcriptions per hour per IP. "
                       "Come back in an hour or upgrade to Pro."
            )
        calls.append(now)
        _ip_calls[ip] = calls


# ─────────────────────────────────────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=".Vsub Cloud API",
    description="Load-balanced Whisper transcription proxy for the .Vsub app.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _auth(request: Request):
    """Optional bearer-token auth. Skip if SECRET is not set."""
    if not SECRET:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing token.")


@app.get("/")
def root():
    return {
        "service": ".Vsub Cloud Transcription API",
        "version": "1.0.0",
        "status": "online",
    }


@app.get("/health")
def health():
    pools = {}
    if _groq_pool:
        pools["groq"] = _groq_pool.status()
    if _openai_pool:
        pools["openai"] = _openai_pool.status()
    return {"status": "ok", "pools": pools}


@app.post("/transcribe")
async def transcribe(
    request: Request,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    prompt: Optional[str]   = Form(None),
    provider: Optional[str] = Form("groq"),   # "groq" | "openai" | "auto"
):
    """
    Accepts a Whisper-compatible multipart audio upload.
    Proxies to Groq or OpenAI with load-balanced key rotation.

    Compatible with the OpenAI Whisper API request format —
    the .Vsub client sends the same payload it would to Groq directly.
    """
    _auth(request)

    # Per-IP rate limit
    client_ip = request.client.host if request.client else "unknown"
    _check_ip_limit(client_ip)

    # File size guard
    audio_bytes = await file.read()
    size_mb = len(audio_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f} MB). Max allowed: {MAX_FILE_MB} MB."
        )

    log.info(
        f"[{client_ip}]  transcribe  provider={provider}  "
        f"lang={language}  size={size_mb:.2f}MB"
    )

    filename = file.filename or "audio.m4a"

    # ── Provider selection with fallback ─────────────────────────────────────
    prov = (provider or "groq").lower()

    if prov in ("groq", "auto") and _groq_pool:
        try:
            return _groq_pool.transcribe(audio_bytes, filename, language, prompt)
        except HTTPException:
            if prov == "auto" and _openai_pool:
                log.info("Groq exhausted — falling back to OpenAI")
            else:
                raise

    if (prov in ("openai", "auto")) and _openai_pool:
        return _openai_pool.transcribe(audio_bytes, filename, language, prompt)

    raise HTTPException(
        status_code=503,
        detail="No API keys configured on this server. Contact the administrator."
    )


@app.get("/stats")
def stats(request: Request):
    """Return usage statistics (requires SECRET)."""
    _auth(request)
    now = time.time()
    cutoff = now - 3600
    with _ip_lock:
        active_ips = sum(
            1 for calls in _ip_calls.values()
            if any(t > cutoff for t in calls)
        )
        total_calls_1h = sum(
            len([t for t in calls if t > cutoff])
            for calls in _ip_calls.values()
        )
    return {
        "active_ips_1h": active_ips,
        "calls_1h": total_calls_1h,
        "groq":   _groq_pool.status()   if _groq_pool   else None,
        "openai": _openai_pool.status() if _openai_pool else None,
    }
