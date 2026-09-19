"""用 OpenRouter 图像模型按分镜出 H3 参考帧。纯标准库,本地跑。

用法:
  python gen_keyframe.py --prompt-file shot.txt --image presenter.jpg --image back.png \
      --out work/a2_test/keyframes/seg03.png [--model openai/gpt-5.4-image-2] [--n 2]

key 只从这两处读取,脚本不打印、不落盘:
  1. 环境变量 OPENROUTER_API_KEY
  2. 文件 %USERPROFILE%\\.config\\openrouter\\key(只放 key 一行)

输入图片按 --image 的顺序依次对应提示词里的"图1、图2……"。
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://openrouter.ai/api/v1/chat/completions"


def api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        f = Path.home() / ".config" / "openrouter" / "key"
        if f.exists():
            key = f.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit("没有 OpenRouter key:设置 OPENROUTER_API_KEY,或写到 ~/.config/openrouter/key")
    return key


def data_url(path):
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def call(model, prompt, images, aspect):
    content = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in images]
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": aspect},
    }
    req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "X-Title": "ugc_clone_pipeline",
    })
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"OpenRouter HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--image", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="openai/gpt-5.4-image-2")
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--n", type=int, default=1, help="出几张候选,文件名加 _1、_2")
    args = ap.parse_args()

    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for i in range(1, args.n + 1):
        t0 = time.time()
        resp = call(args.model, prompt, args.image, args.aspect)
        msg = resp["choices"][0]["message"]
        images = msg.get("images") or []
        if not images:
            raise SystemExit(f"没有返回图片。模型回复: {str(msg.get('content'))[:300]}")
        url = images[0]["image_url"]["url"]
        raw = base64.b64decode(url.split(",", 1)[1])
        target = out if args.n == 1 else out.with_name(f"{out.stem}_{i}{out.suffix}")
        target.write_bytes(raw)
        usage = resp.get("usage", {})
        print(f"{target}  {len(raw)//1024}KB  {time.time()-t0:.0f}s  cost={usage.get('cost')}")


if __name__ == "__main__":
    main()
