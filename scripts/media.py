"""Inspect a reference video at the scale a question needs (port of hypit `media`).

Subcommands (all times in seconds):
  probe       <video>                                   duration, size, fps, audio
  boundaries  <video> [--rate 12] [--threshold 0.1] [--json out]
                                                        adjacent-frame change candidates (not shot labels)
  frames      <video> --at 6.9,7.3 | --every 0.5 [range] --to <dir>
  tile        <video> [range] [--every s | --frames n] [--transcript words.json] --to <grid.jpg>
  tiles       <video> [range | --ranges ranges.json] [--every s | --frames n] --rows 3 --to <dir>
  cut         <video> --start s --end s --to <clip.mp4>

Range: --start/--end, or --around "<phrase>" with --transcript (plus --occurrence n, --padding 0.3).
Without --every, a grid samples --frames evenly spaced midpoints (default 4-9, 1.5 per second).
Grid cells carry a timecode, the word being spoken at that frame and its nearby words (current one
highlighted), so picture changes can be read against speech.

Everything written here is for reading the source only; none of it may be given to an image or
video model as a reference.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TILE_COLUMNS = 3
TILE_CELL_WIDTH = 480
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


# ---------------------------------------------------------------- basics

def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, check=True)


def probe(video: str) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries",
               "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", video]).stdout
    data = json.loads(out)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    num, den = (v.get("r_frame_rate", "0/1").split("/") + ["1"])[:2]
    return {
        "path": video,
        "duration": round(float(data["format"]["duration"]), 3),
        "width": v.get("width"),
        "height": v.get("height"),
        "fps": round(int(num) / max(int(den), 1), 3),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def load_words(path: str | None) -> list[dict] | None:
    if not path:
        return None
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    words = doc["segments"] if "segments" in doc else doc
    flat = [w for s in words for w in s.get("words", [])] if words and "words" in words[0] else words
    return [w for w in flat if w.get("start") is not None and w.get("end") is not None]


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    try:
        found = run(["fc-match", "-f", "%{file}", ":lang=zh"]).stdout.decode()
        if found:
            return ImageFont.truetype(found, size)
    except (OSError, subprocess.CalledProcessError):
        pass
    return ImageFont.load_default()


def timecode(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:06.3f}"


# ---------------------------------------------------------------- sampling

def phrase_ranges(words: list[dict], phrase: str) -> list[tuple[float, float]]:
    # Match on the concatenated word text so Chinese (one word per character) and English both work.
    target = "".join(phrase.split()).lower()
    text, owners = "", []
    for index, w in enumerate(words):
        for ch in "".join(str(w["word"]).split()).lower():
            text += ch
            owners.append(index)
    matches, pos = [], text.find(target)
    while pos >= 0 and target:
        first, last = words[owners[pos]], words[owners[pos + len(target) - 1]]
        matches.append((first["start"], last["end"]))
        pos = text.find(target, pos + 1)
    return matches


def sample_range(args, duration: float, words: list[dict] | None) -> tuple[float, float]:
    if args.around:
        if words is None:
            sys.exit("--around requires --transcript")
        matches = phrase_ranges(words, args.around)
        if not matches:
            sys.exit(f"No timed phrase matches {args.around!r}")
        if len(matches) > 1 and args.occurrence is None:
            listing = ", ".join(f"{i + 1}: {a:.2f}-{b:.2f}s" for i, (a, b) in enumerate(matches))
            sys.exit(f"The phrase occurs {len(matches)} times: {listing}. Choose --occurrence <n>.")
        start, end = matches[(args.occurrence or 1) - 1]
        return max(0.0, start - args.padding), min(duration, end + args.padding)
    start = args.start or 0.0
    end = args.end if args.end is not None else duration
    if not 0 <= start < end <= duration + 1e-6:
        sys.exit(f"range must satisfy 0 <= start < end <= {duration}")
    return start, min(end, duration)


def frame_count(seconds: float) -> int:
    return max(4, min(9, round(seconds * 1.5)))


def sample_times(args, duration: float, words: list[dict] | None) -> list[float]:
    if getattr(args, "at", None):
        times = [float(t) for t in args.at.split(",")]
        return [t for t in times if t < duration]
    start, end = sample_range(args, duration, words)
    if args.every:
        n = math.ceil((end - start) / args.every)
        return [round(start + i * args.every, 3) for i in range(n) if start + i * args.every < end]
    n = args.frames or frame_count(end - start)
    return [round(start + (i + 0.5) * (end - start) / n, 3) for i in range(n)]


# ---------------------------------------------------------------- rendering

def grab(video: str, at: float, target: Path, width: int | None = None) -> None:
    vf = ["-vf", f"scale={width}:-2"] if width else []
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", video, "-frames:v", "1", *vf, "-q:v", "2", str(target)])


def words_at(words: list[dict] | None, at: float) -> tuple[list[dict], list[dict]]:
    if not words:
        return [], []
    active = [w for w in words if w["start"] <= at < w["end"]]
    context = [w for w in words if w["end"] > at - 1.0 and w["start"] < at + 1.0]
    return active, context


def draw_label(cell_width: int, at: float, words: list[dict] | None) -> Image.Image:
    f = font(max(14, cell_width // 24))
    active, context = words_at(words, at)
    lines = [(f"{timecode(at)}  " + ("".join(w["word"] for w in active) or "·"), "#ffdc80")]
    height = 8 + (f.size + 6) * (2 if words is not None else 1) + 6
    label = Image.new("RGB", (cell_width, height), "#0c0c0c")
    d = ImageDraw.Draw(label)
    d.text((8, 6), lines[0][0], font=f, fill=lines[0][1])
    x, y = 8, 6 + f.size + 6
    for w in context:
        text = str(w["word"])
        width = d.textlength(text, font=f)
        if x + width > cell_width - 8:
            break
        d.text((x, y), text, font=f, fill="#ffdc80" if w in active else "#c8c8c8")
        x += width + max(2, f.size // 5)
    return label


def build_grid(video: str, times: list[float], cell: int, columns: int, words: list[dict] | None, to: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cells = []
        for i, at in enumerate(times):
            path = Path(tmp) / f"{i}.jpg"
            grab(video, at, path, cell)
            cells.append((Image.open(path).convert("RGB"), draw_label(cell, at, words)))
    pic_h = max(p.height for p, _ in cells)
    lab_h = max(l.height for _, l in cells)
    rows = math.ceil(len(cells) / columns)
    sheet = Image.new("RGB", (columns * (cell + 8) + 8, rows * (pic_h + lab_h + 8) + 8), "#0c0c0c")
    for i, (pic, lab) in enumerate(cells):
        x = 8 + (i % columns) * (cell + 8)
        y = 8 + (i // columns) * (pic_h + lab_h + 8)
        sheet.paste(pic, (x, y))
        sheet.paste(lab, (x, y + pic_h))
    to.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(to, quality=88)


def boundaries(video: str, rate: float = 12, threshold: float = 0.1) -> list[dict]:
    raw = run(["ffmpeg", "-v", "error", "-i", video, "-vf", f"fps={rate},scale=32:32,format=rgb24",
               "-f", "rawvideo", "-"]).stdout
    stride = 32 * 32 * 3
    frames = [raw[i:i + stride] for i in range(0, len(raw) - stride + 1, stride)]
    out = []
    for i in range(1, len(frames)):
        score = sum(abs(a - b) for a, b in zip(frames[i], frames[i - 1])) / stride / 255
        if score >= threshold:
            out.append({"t": round(i / rate, 3), "score": round(score, 3)})
    return out


# ---------------------------------------------------------------- commands

def add_range(p: argparse.ArgumentParser) -> None:
    p.add_argument("--start", type=float)
    p.add_argument("--end", type=float)
    p.add_argument("--around")
    p.add_argument("--occurrence", type=int)
    p.add_argument("--padding", type=float, default=0.3)
    p.add_argument("--every", type=float)
    p.add_argument("--frames", type=int)
    p.add_argument("--transcript")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe").add_argument("video")
    b = sub.add_parser("boundaries")
    b.add_argument("video")
    b.add_argument("--rate", type=float, default=12)
    b.add_argument("--threshold", type=float, default=0.1)
    b.add_argument("--json")
    f = sub.add_parser("frames")
    f.add_argument("video")
    f.add_argument("--at")
    add_range(f)
    f.add_argument("--to", required=True)
    for name in ("tile", "tiles"):
        t = sub.add_parser(name)
        t.add_argument("video")
        add_range(t)
        t.add_argument("--cell", type=int)
        t.add_argument("--columns", type=int, default=TILE_COLUMNS)
        t.add_argument("--to", required=True)
        if name == "tiles":
            t.add_argument("--rows", type=int, default=3)
            t.add_argument("--ranges", help='JSON [{"id","start","end","every"|"frames"}]')
    c = sub.add_parser("cut")
    c.add_argument("video")
    add_range(c)
    c.add_argument("--to", required=True)
    args = ap.parse_args()

    info = probe(args.video)
    if args.cmd == "probe":
        print(json.dumps(info, indent=2))
        return
    if args.cmd == "boundaries":
        found = boundaries(args.video, args.rate, args.threshold)
        if args.json:
            Path(args.json).write_text(json.dumps({"rate": args.rate, "threshold": args.threshold,
                                                   "candidates": found}, indent=1), encoding="utf-8")
        print(f"{len(found)} visual-change candidates at {args.rate}/s; scores are not shot labels")
        for c in found[:40]:
            print(f"  {c['t']:7.3f}s  score {c['score']}")
        return

    words = load_words(getattr(args, "transcript", None))
    if args.cmd == "cut":
        start, end = sample_range(args, info["duration"], words)
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", args.video, "-t", f"{end - start:.3f}",
             "-c:v", "libx264", "-crf", "18", "-c:a", "aac", args.to])
        print(f"{args.to}  {start:.2f}-{end:.2f}s")
        return
    if args.cmd == "frames":
        to = Path(args.to)
        to.mkdir(parents=True, exist_ok=True)
        times = sample_times(args, info["duration"], words)
        for t in times:
            grab(args.video, t, to / f"{t:07.3f}s.jpg")
        print(f"{to}  {len(times)} frames")
        return

    cell = args.cell or max(80, min(TILE_CELL_WIDTH, info["width"] or TILE_CELL_WIDTH))
    if args.cmd == "tile":
        times = sample_times(args, info["duration"], words)
        build_grid(args.video, times, cell, args.columns, words, Path(args.to))
        print(f"{args.to}  {len(times)} frames  {times[0]:.2f}-{times[-1]:.2f}s")
        return

    # tiles: page one range, or one grid set per entry of --ranges
    to = Path(args.to)
    to.mkdir(parents=True, exist_ok=True)
    if args.ranges:
        specs = json.loads(Path(args.ranges).read_text(encoding="utf-8"))
    else:
        start, end = sample_range(args, info["duration"], words)
        specs = [{"id": "range", "start": start, "end": end}]
    per_page = args.columns * args.rows
    written = []
    for spec in specs:
        local = argparse.Namespace(**{**vars(args), "around": None, "start": spec["start"], "end": spec["end"],
                                     "every": spec.get("every", args.every), "frames": spec.get("frames", args.frames)})
        times = sample_times(local, info["duration"], words)
        for page in range(math.ceil(len(times) / per_page)):
            chunk = times[page * per_page:(page + 1) * per_page]
            name = f"{spec.get('id', 'range')}_{page + 1:02d}.jpg"
            build_grid(args.video, chunk, cell, args.columns, words, to / name)
            written.append({"file": name, "start": chunk[0], "end": chunk[-1], "frames": len(chunk)})
    (to / "index.json").write_text(json.dumps(written, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{to}  {len(written)} grids")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
