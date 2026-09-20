"""Compare the speaking voice across rendered clips (no speaker model needed).

H3 has no voice-reference input: the voice is decided by the prompt and the seed, so clips rendered in
separate jobs can come out as different people. The reliable fix is to render one video as ONE job;
this script is the check for material that was already split.

For each file it measures, over voiced frames only:
  f0_median   pitch in Hz (autocorrelation)     - the strongest speaker cue here
  f0_iqr      pitch spread
  centroid    spectral centroid in Hz           - rough timbre/brightness

Usage: voice_check.py a.wav b.wav [...]   (16 kHz mono wav, e.g. from ffmpeg -vn -ac 1 -ar 16000)
A pitch difference over about 15 percent usually means a different voice; listen to confirm.
"""

from __future__ import annotations

import sys
import wave

import numpy as np

SR = 16000
FRAME = 1024
HOP = 512
F0_MIN, F0_MAX = 70, 400


def read_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        if w.getframerate() != SR or w.getnchannels() != 1:
            raise SystemExit(f"{path}: expected 16 kHz mono")
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0


def frame_f0(frame: np.ndarray) -> float:
    frame = frame - frame.mean()
    corr = np.correlate(frame, frame, mode="full")[len(frame) - 1:]
    lo, hi = SR // F0_MAX, SR // F0_MIN
    if corr[0] <= 0 or hi >= len(corr):
        return 0.0
    peak = int(np.argmax(corr[lo:hi])) + lo
    return SR / peak if corr[peak] / corr[0] > 0.3 else 0.0


def measure(path: str) -> dict:
    x = read_wav(path)
    f0s, centroids = [], []
    for start in range(0, len(x) - FRAME, HOP):
        frame = x[start:start + FRAME]
        if np.sqrt((frame ** 2).mean()) < 0.01:      # silence
            continue
        f0 = frame_f0(frame)
        if f0:
            f0s.append(f0)
            spec = np.abs(np.fft.rfft(frame * np.hanning(FRAME)))
            freqs = np.fft.rfftfreq(FRAME, 1 / SR)
            centroids.append(float((spec * freqs).sum() / max(spec.sum(), 1e-9)))
    if not f0s:
        return {"file": path, "voiced_frames": 0}
    f0s = np.array(f0s)
    return {
        "file": path,
        "voiced_frames": len(f0s),
        "f0_median": round(float(np.median(f0s)), 1),
        "f0_iqr": round(float(np.percentile(f0s, 75) - np.percentile(f0s, 25)), 1),
        "centroid": round(float(np.median(centroids)), 1),
    }


def main() -> None:
    paths = sys.argv[1:]
    if len(paths) < 1:
        raise SystemExit(__doc__)
    stats = [measure(p) for p in paths]
    for s in stats:
        print(s)
    usable = [s for s in stats if s.get("voiced_frames")]
    if len(usable) > 1:
        f0 = [s["f0_median"] for s in usable]
        spread = (max(f0) - min(f0)) / min(f0)
        print(f"\npitch spread across files: {spread:.1%}")
        print("likely the same voice" if spread < 0.15 else "LIKELY DIFFERENT VOICES - re-render as one job")


if __name__ == "__main__":
    main()
