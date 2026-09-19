"""Reference archive: understand one source video before adapting it (port of hypit's reference-video flow).

One archive per reference video, reusable by any number of products:

  references/<ref_id>/
    source.mp4            the reference (git-ignored)
    probe.json            duration, size, fps
    transcript.json       word-level speech (evidence, not interpretation)
    cuts.json             scene-detect cuts (threshold 0.3)
    boundaries.json       fine visual-change candidates (12/s, 0.1) - candidates, not shot labels
    evidence/             overview grids, before/after grids for every cut, one dense grid per spoken line
    ANALYSIS.md           whole-piece understanding: what it wants, arc, systems, roles to preserve
    TIMELINE.md           what happens when, tied to words, and how each relationship lands in an adaptation
    PROGRESS.md           only while understanding is in progress: open questions and next look

Commands:
  init      <video> <ref_id> [--transcript words.json | --transcribe [--vad]]   (runs locally; transcription uses conda env ugc_asr)
            copy the source, probe, cuts, boundaries, transcript, all evidence grids, then scaffold
  scaffold  <ref_id>      (re)write ANALYSIS/TIMELINE/PROGRESS skeletons from the facts; never overwrites
                          a document that no longer contains TODO markers
  check     <ref_id>      is the archive complete enough to adapt from?
  tile      <ref_id> ...  shortcut for scripts/media.py tile on this archive (e.g. --around "phrase" --every 0.1)

The agent's work between scaffold and check: read the overview grids end to end, form the whole-piece
reading in ANALYSIS.md, then go section by section in TIMELINE.md, re-sampling any doubtful passage
(`tile --around ... --every 0.1`), and revise ANALYSIS when a close look changes it. Record open
questions in PROGRESS.md; delete it when nothing is left to examine.

None of these images may be given to an image or video model.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import media  # noqa: E402

TODO = "<!-- TODO"
SENTENCE_END = re.compile(r"[,，。.!！?？;；:：、]$")
LINE_GAP = 0.35


# ---------------------------------------------------------------- facts

def asr_python() -> str:
    """Python of the local transcription env (conda ugc_asr); override with UGC_ASR_PYTHON."""
    for candidate in (os.environ.get("UGC_ASR_PYTHON"), "D:/anaconda/envs/ugc_asr/python.exe",
                      str(Path.home() / "anaconda3/envs/ugc_asr/bin/python")):
        if candidate and Path(candidate).exists():
            return candidate
    return sys.executable

def archive(ref_id: str) -> Path:
    return REPO / "references" / ref_id


def detect_cuts(video: str, threshold: float = 0.3) -> list[dict]:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", video, "-vf",
                          f"select='gt(scene,{threshold})',metadata=print", "-an", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    cuts, t = [], None
    for line in out.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
        m = re.search(r"lavfi\.scene_score=([\d.]+)", line)
        if m and t is not None:
            cuts.append({"t": round(t, 3), "score": round(float(m.group(1)), 3)})
    return cuts


def spoken_lines(words: list[dict]) -> list[dict]:
    """Group words into spoken lines at punctuation or pauses longer than LINE_GAP."""
    lines, current = [], []
    for i, w in enumerate(words):
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or SENTENCE_END.search(str(w["word"]).strip()) or nxt["start"] - w["end"] > LINE_GAP:
            text = "".join(str(x["word"]) for x in current)
            lines.append({"start": current[0]["start"], "end": current[-1]["end"], "text": text.strip(),
                          "low_confidence": [x["word"] for x in current if x.get("score", 1) < 0.5]})
            current = []
    return [l for l in lines if l["text"]]


def load_facts(root: Path) -> dict:
    probe = json.loads((root / "probe.json").read_text(encoding="utf-8"))
    words = media.load_words(str(root / "transcript.json")) if (root / "transcript.json").exists() else []
    cuts = json.loads((root / "cuts.json").read_text(encoding="utf-8")) if (root / "cuts.json").exists() else []
    lines = spoken_lines(words) if words else []
    return {"probe": probe, "words": words, "cuts": cuts, "lines": lines}


# ---------------------------------------------------------------- evidence

def build_evidence(root: Path, facts: dict) -> dict:
    video = str(root / "source.mp4")
    words = facts["words"] or None
    duration = facts["probe"]["duration"]
    ev = root / "evidence"
    made = {"overview": [], "cuts": [], "lines": []}

    # whole piece, 1 frame/s, paged 4x3
    per_page, t, page = 12, 0.0, 1
    while t < duration:
        times = [round(t + i, 3) for i in range(per_page) if t + i < duration]
        name = f"overview/overview_{page:02d}_{times[0]:05.1f}-{times[-1]:05.1f}s.jpg"
        media.build_grid(video, times, 240, 4, words, ev / name)
        made["overview"].append(name)
        t += per_page
        page += 1

    # every cut: 0.5s before to 0.5s after, 0.125s apart
    for c in facts["cuts"]:
        a, b = max(0.0, c["t"] - 0.5), min(duration, c["t"] + 0.5)
        times = [round(a + i * 0.125, 3) for i in range(int((b - a) / 0.125)) if a + i * 0.125 < duration]
        name = f"cuts/cut_{c['t']:06.3f}s.jpg"
        media.build_grid(video, times, 200, 4, words, ev / name)
        made["cuts"].append(name)

    # every spoken line: padded 0.3s, 4 frames/s
    for i, line in enumerate(facts["lines"], start=1):
        a, b = max(0.0, line["start"] - 0.3), min(duration, line["end"] + 0.3)
        times = [round(a + k * 0.25, 3) for k in range(int((b - a) / 0.25) + 1) if a + k * 0.25 < duration]
        name = f"lines/L{i:02d}_{line['start']:05.2f}-{line['end']:05.2f}s.jpg"
        media.build_grid(video, times, 200, 4, words, ev / name)
        made["lines"].append(name)
        line["evidence"] = f"evidence/{name}"

    (ev / "index.json").write_text(json.dumps(made, ensure_ascii=False, indent=1), encoding="utf-8")
    return made


# ---------------------------------------------------------------- documents

def todo(text: str) -> str:
    return f"{TODO}: {text} -->"


def scaffold(root: Path, facts: dict, force: bool = False) -> list[str]:
    probe, lines, cuts = facts["probe"], facts["lines"], facts["cuts"]
    ev_index = json.loads((root / "evidence/index.json").read_text(encoding="utf-8")) \
        if (root / "evidence/index.json").exists() else {"overview": [], "cuts": [], "lines": []}
    chars = sum(len(re.sub(r"\W", "", l["text"])) for l in lines)
    speech = (lines[-1]["end"] - lines[0]["start"]) if lines else 0
    written = []

    def write(name: str, body: str) -> None:
        path = root / name
        if path.exists() and not force and TODO not in path.read_text(encoding="utf-8"):
            return  # already filled in by the agent
        path.write_text(body, encoding="utf-8")
        written.append(name)

    overview = "\n".join(f"- `evidence/{n}`" for n in ev_index["overview"])
    cut_rows = "\n".join(
        f"| {c['t']:.2f}s | {c['score']} | `evidence/cuts/cut_{c['t']:06.3f}s.jpg` | {todo('跳剪还是插入镜头?给了什么新信息?')} |"
        for c in cuts)
    arc_rows = "\n".join(f"| {l['start']:.2f}–{l['end']:.2f}s | {l['text']} | {todo('情绪')} | {todo('作用')} |"
                         for l in lines)
    write("ANALYSIS.md", f"""# ANALYSIS — {root.name}

整条片为什么有效。事实和解读分开写;时间点在 `TIMELINE.md`,逐词时间在 `transcript.json`。
**这里的一切只用来理解原片,原片画面不交给任何生成模型。**

| 事实 | 值 |
|---|---|
| 时长 / 画幅 | {probe['duration']}s / {probe['width']}x{probe['height']} @ {probe['fps']}fps |
| 出镜方式 | {todo('看宫格判断,三选一:generated_fictional(有人对镜头说话)/ hands_only(只有手)/ none(只有商品,画外音)')} |
| 台词 | {len(lines)} 句,约 {chars} 字/词,约 {chars / speech if speech else 0:.1f} 个/秒 |
| 切点(scene>0.3) | {len(cuts)} 个 |

先按顺序看完全片宫格,再写下面各节:

{overview}

## 它想让观众得到什么

{todo('一两句话:观众看完会得出什么结论?片子有没有明说?')}

## 情绪弧线

| 时间 | 台词 | 情绪 | 作用 |
|---|---|---|---|
{arc_rows}

{todo('合并成几个大段,写清前后顺序为什么不能换')}

## 各个元素在做什么

| 切点 | 分数 | 证据 | 类型与作用 |
|---|---|---|---|
{cut_rows}

- **主画面**:{todo('谁、什么景别、机位是否固定、跳剪的作用')}
- **插入镜头**:{todo('每个插入镜头给了什么新信息')}
- **贯穿全片的道具/物件**:{todo('从头到尾在画面里、无声强调什么')}
- **动作和台词的对齐**:{todo('每个卖点配了什么手上的证据动作,落在哪个词')}
- **字幕 / 花字**:{todo('样式、位置、重点词有没有变色')}
- **声音**:{todo('背景音乐、人声、音效')}

## 改编时要保留的作用(不是形式)

{todo('编号列出,每条是一个作用而不是一个具体画面')}

## 已知不能照搬的

{todo('原片宣称、原品牌、原博主的亲身经历;对照 product.json 的 forbidden_claims')}
""")

    sections = []
    for i, l in enumerate(lines, start=1):
        inside = [c["t"] for c in cuts if l["start"] - 0.3 <= c["t"] <= l["end"] + 0.3]
        cut_note = ("切点:" + "、".join(f"{t:.2f}s(`evidence/cuts/cut_{t:06.3f}s.jpg`)" for t in inside) + "\n") if inside else ""
        low = f"转写低置信度:{'、'.join(l['low_confidence'])},对照字幕核对。\n" if l["low_confidence"] else ""
        sections.append(f"""## {l['start']:.2f}–{l['end']:.2f} · {todo('阶段名')}

> {l['text']}

证据:`{l.get('evidence', '')}`
{cut_note}{low}
镜头:{todo('景别 | 机位高度与角度(平视 / 斜俯约 45° / 正俯;第一人称还是对面拍)| 运动(固定 / 手持晃动 / 推近 / 跟手)| 构图(主体在哪、占多大)')}

{todo('画面里有什么、谁在动、动作落在哪个词、对观众起什么作用')}

→ 改编:{todo('这个关系在我们片子里怎么落;时间跟新台词的词走')}
""")
    write("TIMELINE.md", f"""# TIMELINE — {root.name}

按原片时间分段(初稿按台词句子切;相邻几句属于同一个作用时合并,段内有插入镜头时拆开)。
每段写:画面里有什么、谁在动、跟哪个词对齐、对观众起什么作用;"→ 改编"说明它在我们片子里怎么落。

""" + "\n".join(sections))

    open_q = []
    for l in lines:
        if l["low_confidence"]:
            open_q.append(f"- [ ] {l['start']:.2f}s 转写低置信度:{'、'.join(l['low_confidence'])}")
    for c in cuts:
        open_q.append(f"- [ ] {c['t']:.2f}s 切点是跳剪还是插入镜头")
    open_q.append("- [ ] ANALYSIS 各节写完后,按 TIMELINE 逐段加密复看,回头修正 ANALYSIS")
    write("PROGRESS.md", f"""# PROGRESS — {root.name}

写完、没有要再看的地方时删掉本文件。

## 还没弄清的

{chr(10).join(open_q)}

## 下一步

先看 `evidence/overview/`,写 ANALYSIS 的前两节。
补看某一段:`python scripts/reference_archive.py tile {root.name} --around "<台词>" --every 0.1`
""")
    return written


# ---------------------------------------------------------------- check

def check(root: Path) -> list[str]:
    problems = []
    for name in ("ANALYSIS.md", "TIMELINE.md"):
        path = root / name
        if not path.exists():
            problems.append(f"缺少 {name}")
            continue
        text = path.read_text(encoding="utf-8")
        left = text.count(TODO)
        if left:
            problems.append(f"{name} 还有 {left} 处 TODO")
    tl = root / "TIMELINE.md"
    if tl.exists():
        for block in re.split(r"\n(?=## )", tl.read_text(encoding="utf-8")):
            if not block.startswith("## "):
                continue
            head = block.splitlines()[0]
            if not re.search(r"\d+(\.\d+)?\s*[–-]\s*\d+(\.\d+)?", head):
                problems.append(f"TIMELINE 段落缺时间范围:{head}")
            cam = re.search(r"^镜头[::](.+)$", block, re.M)
            if not cam or TODO in cam.group(1) or cam.group(1).count("|") + cam.group(1).count("｜") < 3:
                problems.append(f"TIMELINE 段落缺'镜头:景别 | 角度 | 运动 | 构图':{head}")
            if "→ 改编" not in block:
                problems.append(f"TIMELINE 段落缺 '→ 改编':{head}")
            for ref in re.findall(r"`(evidence/[^`]+)`", block):
                if (root / "evidence").exists() and not (root / ref).exists():
                    problems.append(f"证据不存在:{ref}")
    an = root / "ANALYSIS.md"
    if an.exists():
        text = an.read_text(encoding="utf-8")
        if not re.search(r"\|\s*出镜方式\s*\|[^|]*(generated_fictional|hands_only|none)", text):
            problems.append("ANALYSIS 事实表缺'出镜方式'(generated_fictional / hands_only / none),它决定要不要出镜人")
        for heading in ("它想让观众得到什么", "情绪弧线", "各个元素在做什么", "改编时要保留的作用"):
            if heading not in text:
                problems.append(f"ANALYSIS 缺少一节:{heading}")
    if (root / "PROGRESS.md").exists():
        problems.append("PROGRESS.md 还在(还有没看完的问题,或者写完后忘了删)")
    return problems


# ---------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("video")
    i.add_argument("ref_id")
    i.add_argument("--transcript", help="existing word-level transcript to copy in")
    i.add_argument("--transcribe", action="store_true", help="run scripts/transcribe.py (GPU server)")
    i.add_argument("--vad", action="store_true")
    s = sub.add_parser("scaffold")
    s.add_argument("ref_id")
    s.add_argument("--force", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("ref_id")
    t = sub.add_parser("tile")
    t.add_argument("ref_id")
    args, rest = ap.parse_known_args()
    root = archive(args.ref_id)

    if args.cmd == "init":
        (root / "evidence").mkdir(parents=True, exist_ok=True)
        if not (root / "source.mp4").exists():
            shutil.copy2(args.video, root / "source.mp4")
        video = str(root / "source.mp4")
        (root / "probe.json").write_text(json.dumps(media.probe(video), indent=2), encoding="utf-8")
        (root / "cuts.json").write_text(json.dumps(detect_cuts(video), indent=1), encoding="utf-8")
        (root / "boundaries.json").write_text(json.dumps(media.boundaries(video), indent=1), encoding="utf-8")
        if args.transcript:
            shutil.copy2(args.transcript, root / "transcript.json")
        elif args.transcribe:
            audio = root / "audio.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", str(audio)],
                           check=True)
            cmd = [asr_python(), str(REPO / "scripts/transcribe.py"), str(audio), str(root / "transcript.json")]
            subprocess.run(cmd + (["--vad"] if args.vad else []), check=True)
        facts = load_facts(root)
        made = build_evidence(root, facts)
        written = scaffold(root, facts)
        print(json.dumps({"archive": str(root.relative_to(REPO)), "lines": len(facts["lines"]),
                          "cuts": len(facts["cuts"]), "evidence": {k: len(v) for k, v in made.items()},
                          "scaffolded": written}, ensure_ascii=False, indent=2))
    elif args.cmd == "scaffold":
        print(scaffold(root, load_facts(root), args.force))
    elif args.cmd == "check":
        problems = check(root)
        for p in problems:
            print("  -", p)
        print("READY" if not problems else f"{len(problems)} 项未完成")
        sys.exit(0 if not problems else 1)
    elif args.cmd == "tile":
        def opt(name: str) -> str | None:
            return rest[rest.index(name) + 1] if name in rest else None
        if opt("--to") is None:
            label = opt("--around") or f"{opt('--start') or 0}-{opt('--end') or 'end'}s"
            slug = re.sub(r"[^\w.-]+", "_", label).strip("_")[:40] or "look"
            rest += ["--to", str(root / "evidence" / "looks" / f"{slug}.jpg")]
        cmd = [sys.executable, str(Path(__file__).parent / "media.py"), "tile", str(root / "source.mp4"),
               "--transcript", str(root / "transcript.json")] + rest
        sys.exit(subprocess.run(cmd).returncode)

if __name__ == "__main__":
    main()
