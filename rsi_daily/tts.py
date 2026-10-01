"""한국어 음성: edge-tts → gTTS → 무음(자막만) 순으로 폴백."""
from __future__ import annotations

import asyncio
import logging
import subprocess
import wave
from pathlib import Path

import numpy as np

from . import config as C

log = logging.getLogger("tts")
SR = 24000


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                          "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


async def _edge(text: str, path: Path) -> None:
    import edge_tts
    await edge_tts.Communicate(text, C.TTS_VOICE, rate=C.TTS_RATE).save(str(path))


def synth(text: str, path: Path) -> tuple[Path | None, float, str]:
    """반환: (오디오 경로 또는 None, 길이(초), 엔진)"""
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            asyncio.run(_edge(text, path))
            if path.exists() and path.stat().st_size > 1000:
                return path, _duration(path), "edge"
        except Exception as e:  # noqa: BLE001
            log.warning("edge-tts 실패(%d): %s", attempt + 1, e)
    try:
        from gtts import gTTS
        gTTS(text, lang="ko").save(str(path))
        return path, _duration(path), "gtts"
    except Exception as e:  # noqa: BLE001
        log.warning("gTTS 실패: %s → 무음", e)
    return None, max(1.6, len(text) / 7.0), "silent"


def decode(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def mix_timeline(clips: list[tuple[float, Path | None]], total: float, out: Path) -> Path:
    buf = np.zeros(int((total + 0.5) * SR), dtype=np.float32)
    for start, p in clips:
        if p is None:
            continue
        a = decode(p)
        i = int(start * SR)
        j = min(len(buf), i + len(a))
        buf[i:j] += a[: j - i]
    buf = np.clip(buf, -1, 1)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((buf * 32767).astype(np.int16).tobytes())
    return out
