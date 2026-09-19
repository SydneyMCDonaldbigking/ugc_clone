"""带台词标注的抽帧宫格(思路来自 hypit `media tile --transcript`)。服务器 asr_venv 里跑。

每格下方标出:时间码、这一帧正在说的字、前后几个字(当前字高亮)。

用法:
  tile.py <video> <words.json> <out.jpg> --start 0 --end 18 --every 1
  tile.py <video> <words.json> <out.jpg> --around "一定要看好配料表" --every 0.25
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
         "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
         "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
         "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"]


def load_font(size):
    for f in FONTS:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    found = subprocess.run(["fc-match", "-f", "%{file}", ":lang=zh"], capture_output=True, text=True).stdout
    if found:
        return ImageFont.truetype(found, size)
    raise SystemExit("服务器上没找到中文字体(fc-list :lang=zh 为空)")


def load_words(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return [w for s in doc["segments"] for w in s["words"] if w.get("start") is not None]


def locate(words, phrase, padding):
    # 在逐字拼接的文本里找短语,返回它的起止时间
    text, owners = "", []
    for i, w in enumerate(words):
        for ch in w["word"]:
            text += ch
            owners.append(i)
    pos = text.find(phrase)
    if pos < 0:
        raise SystemExit(f"转写里找不到 '{phrase}'")
    first, last = words[owners[pos]], words[owners[pos + len(phrase) - 1]]
    return max(first["start"] - padding, 0), last["end"] + padding


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("words")
    ap.add_argument("out")
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--around")
    ap.add_argument("--padding", type=float, default=0.3)
    ap.add_argument("--every", type=float, default=1.0)
    ap.add_argument("--cell", type=int, default=360)
    ap.add_argument("--columns", type=int, default=6)
    args = ap.parse_args()

    words = load_words(args.words)
    if args.around:
        start, end = locate(words, args.around, args.padding)
    else:
        start, end = args.start, args.end or words[-1]["end"]
    times = []
    t = start
    while t < end:
        times.append(round(t, 3))
        t += args.every

    font = load_font(max(14, args.cell // 20))
    label_h = font.size * 3 + 20
    cells = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, at in enumerate(times):
            path = Path(tmp) / f"{i}.jpg"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", args.video,
                            "-frames:v", "1", "-vf", f"scale={args.cell}:-2", str(path)], check=True)
            pic = Image.open(path).convert("RGB")
            active = [w for w in words if w["start"] <= at < w["end"]]
            near = [w for w in words if w["end"] > at - 1.0 and w["start"] < at + 1.0]
            cells.append((at, pic, active, near))

    pic_h = max(c[1].height for c in cells)
    rows = -(-len(cells) // args.columns)
    sheet = Image.new("RGB", (args.columns * (args.cell + 8) + 8, rows * (pic_h + label_h + 8) + 8), "#0c0c0c")
    draw = ImageDraw.Draw(sheet)
    for i, (at, pic, active, near) in enumerate(cells):
        x = 8 + (i % args.columns) * (args.cell + 8)
        y = 8 + (i // args.columns) * (pic_h + label_h + 8)
        sheet.paste(pic, (x, y))
        ty = y + pic_h + 4
        head = f"{at:6.2f}s  " + ("".join(w["word"] for w in active) or "·")
        draw.text((x + 4, ty), head, font=font, fill="#ffdc80")
        cx = x + 4
        for w in near:
            color = "#ffdc80" if w in active else "#c8c8c8"
            if cx + draw.textlength(w["word"], font=font) > x + args.cell:
                break
            draw.text((cx, ty + font.size + 6), w["word"], font=font, fill=color)
            cx += draw.textlength(w["word"], font=font) + 2
    sheet.save(args.out, quality=88)
    print(f"{args.out}  {len(cells)} 帧  {start:.2f}-{end:.2f}s  每 {args.every}s")


if __name__ == "__main__":
    main()
