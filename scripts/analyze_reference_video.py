"""Analyze a reference video before writing a shot plan or generating keyframes.

The script uses ffprobe/ffmpeg for deterministic decoding and Pillow only for
storyboard layout. It writes:

* ``analysis.json`` with stream metadata, sampling times, and hard-cut candidates
* ``storyboard_XX.jpg`` pages with timestamped frames
* ``cuts_XX.jpg`` pages showing frames immediately before and after each cut

Everything written here is for reading the source only. None of these images may be
passed to an image model or to H3 as a reference, in any role: they carry the source
creator's face, product, watermark and captions. ``ugc_pipeline validate`` rejects them.

Example:
    python scripts/analyze_reference_video.py ref_video_2.mp4 work/a2_test/video_analysis
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PTS_RE = re.compile(r"pts_time:([0-9.]+)")
SCORE_RE = re.compile(r"lavfi\.scene_score=([0-9.]+)")


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"Required executable is unavailable: {name}")
    return path


def run_json(command: list[str]) -> dict:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def probe_video(ffprobe: str, video: Path) -> dict:
    doc = run_json(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=filename,duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,nb_frames",
            "-of",
            "json",
            str(video),
        ]
    )
    stream = next(item for item in doc["streams"] if item["codec_type"] == "video")
    numerator, denominator = stream["r_frame_rate"].split("/")
    return {
        "file": video.as_posix(),
        "duration_seconds": round(float(doc["format"]["duration"]), 6),
        "file_size_bytes": int(doc["format"]["size"]),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": round(int(numerator) / int(denominator), 6),
        "frame_count": int(stream.get("nb_frames") or 0),
        "codec": stream.get("codec_name"),
    }


def detect_cuts(ffmpeg: str, video: Path, threshold: float) -> list[dict]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-i",
        str(video),
        "-vf",
        f"select=gt(scene\\,{threshold}),metadata=print",
        "-an",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    cuts: list[dict] = []
    pending_time: float | None = None
    for line in completed.stderr.splitlines():
        pts = PTS_RE.search(line)
        if pts:
            pending_time = float(pts.group(1))
        score = SCORE_RE.search(line)
        if score and pending_time is not None:
            cuts.append(
                {
                    "time_seconds": round(pending_time, 3),
                    "scene_score": round(float(score.group(1)), 6),
                }
            )
            pending_time = None
    return cuts


def sample_times(duration: float, interval: float) -> list[float]:
    count = int(math.floor(duration / interval)) + 1
    values = [round(index * interval, 3) for index in range(count)]
    final = round(max(duration - 0.05, 0), 3)
    if not values or final - values[-1] >= interval * 0.25:
        values.append(final)
    return values


def extract_frame(ffmpeg: str, video: Path, at: float, destination: Path, width: int) -> None:
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            str(destination),
        ],
        check=True,
    )


def font(size: int) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def build_pages(
    ffmpeg: str,
    video: Path,
    times: list[float],
    output_dir: Path,
    prefix: str,
    labels: list[str] | None,
    columns: int,
    rows: int,
    cell_width: int,
) -> list[str]:
    page_size = columns * rows
    output_paths: list[str] = []
    label_font = font(22)
    with tempfile.TemporaryDirectory(prefix="ugc-video-analysis-") as temp_dir:
        temp = Path(temp_dir)
        extracted: list[tuple[float, Image.Image]] = []
        for index, at in enumerate(times):
            path = temp / f"frame-{index:04d}.jpg"
            extract_frame(ffmpeg, video, at, path, cell_width)
            with Image.open(path) as raw:
                extracted.append((at, raw.convert("RGB").copy()))

        for page_index, start in enumerate(range(0, len(extracted), page_size), start=1):
            page_frames = extracted[start : start + page_size]
            image_height = max(frame.height for _, frame in page_frames)
            label_height = 42
            gap = 8
            canvas = Image.new(
                "RGB",
                (
                    columns * (cell_width + gap) + gap,
                    rows * (image_height + label_height + gap) + gap,
                ),
                "#111111",
            )
            draw = ImageDraw.Draw(canvas)
            for local_index, (at, frame) in enumerate(page_frames):
                global_index = start + local_index
                x = gap + (local_index % columns) * (cell_width + gap)
                y = gap + (local_index // columns) * (image_height + label_height + gap)
                canvas.paste(frame, (x, y))
                text = labels[global_index] if labels else f"{at:06.2f}s"
                draw.text((x + 6, y + image_height + 7), text, font=label_font, fill="#ffd166")
            destination = output_dir / f"{prefix}_{page_index:02d}.jpg"
            canvas.save(destination, quality=92)
            output_paths.append(destination.as_posix())
    return output_paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--scene-threshold", type=float, default=0.32)
    parser.add_argument("--cut-offset", type=float, default=0.08)
    args = parser.parse_args()

    if args.interval <= 0:
        raise SystemExit("--interval must be greater than zero")
    if not 0 < args.scene_threshold <= 1:
        raise SystemExit("--scene-threshold must be within (0, 1]")
    if not args.video.is_file():
        raise SystemExit(f"Video does not exist: {args.video}")

    ffprobe = require_tool("ffprobe")
    ffmpeg = require_tool("ffmpeg")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    metadata = probe_video(ffprobe, args.video)
    cuts = detect_cuts(ffmpeg, args.video, args.scene_threshold)
    times = sample_times(metadata["duration_seconds"], args.interval)
    storyboard_pages = build_pages(
        ffmpeg,
        args.video,
        times,
        args.output_dir,
        "storyboard",
        None,
        columns=6,
        rows=2,
        cell_width=240,
    )

    cut_times: list[float] = []
    cut_labels: list[str] = []
    for index, cut in enumerate(cuts, start=1):
        at = cut["time_seconds"]
        before = max(0, at - args.cut_offset)
        after = min(metadata["duration_seconds"] - 0.01, at + args.cut_offset)
        cut_times.extend([before, after])
        cut_labels.extend([f"CUT {index}  {before:06.2f}s  BEFORE", f"CUT {index}  {after:06.2f}s  AFTER"])
    cut_pages = (
        build_pages(
            ffmpeg,
            args.video,
            cut_times,
            args.output_dir,
            "cuts",
            cut_labels,
            columns=4,
            rows=2,
            cell_width=300,
        )
        if cut_times
        else []
    )

    analysis = {
        "schema": "reference-video-analysis/v1",
        "video": metadata,
        "sampling": {
            "interval_seconds": args.interval,
            "times_seconds": times,
            "storyboard_pages": storyboard_pages,
        },
        "cut_detection": {
            "scene_threshold": args.scene_threshold,
            "cut_offset_seconds": args.cut_offset,
            "cuts": cuts,
            "comparison_pages": cut_pages,
        },
    }
    analysis_path = args.output_dir / "analysis.json"
    analysis_path.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"analysis": analysis_path.as_posix(), "cuts": cuts, "pages": storyboard_pages}, indent=2))


if __name__ == "__main__":
    main()
