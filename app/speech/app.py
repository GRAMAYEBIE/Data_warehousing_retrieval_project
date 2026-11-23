"""Local speech-to-text for the assistant's microphone button.

The browser records a short question and sends the audio here (through the web server's
nginx, on the internal Docker network only). faster-whisper transcribes it on this
machine: the voice never leaves the platform. The text goes back to the question box,
where the person reads and edits it before sending; nothing is asked on their behalf.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

MODEL = os.environ.get("SPEECH_MODEL", "base")  # tiny, base, small: size against accuracy
MAX_BYTES = 10 * 1024 * 1024  # about 5 minutes of compressed audio
app = FastAPI(title="MetroMove speech-to-text", version="1.0.0")
_model = None
_lock = threading.Lock()


class Transcript(BaseModel):
    text: str
    language: str
    seconds: float


class Health(BaseModel):
    status: str
    model: str
    loaded: bool


def model():
    """Loaded on first use (and at start-up in the background): the first download of the
    model files goes to the volume mounted on HF_HOME."""
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            _model = WhisperModel(MODEL, device="cpu", compute_type="int8")
        return _model


@app.on_event("startup")
def preload() -> None:
    threading.Thread(target=model, daemon=True).start()


@app.get("/health")
def health() -> Health:
    return Health(status="ok", model=MODEL, loaded=_model is not None)


@app.post("/transcribe")
async def transcribe(request: Request) -> Transcript:
    """Audio in the request body (webm, ogg, wav, mp4 or mp3, as the browser records it)."""
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "no audio")
    if len(audio) > MAX_BYTES:
        raise HTTPException(413, "recording too long")
    start = time.monotonic()
    with tempfile.NamedTemporaryFile(suffix=".audio") as f:
        f.write(audio)
        f.flush()
        segments, info = model().transcribe(
            f.name,
            beam_size=1,
            vad_filter=True,  # silences at the start and end are ignored
            initial_prompt=(
                "Questions about New York taxi trips: trips, revenue, fares, tips, "
                "Manhattan, Brooklyn, Queens, the Bronx, JFK, LaGuardia, pickup zones."
            ),
        )
        text = " ".join(s.text.strip() for s in segments).strip()
    return Transcript(text=text, language=info.language, seconds=round(time.monotonic() - start, 2))
