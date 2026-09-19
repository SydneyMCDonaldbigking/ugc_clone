"""S2 转写对齐:faster-whisper 逐词时间戳。服务器 asr_venv 里跑。

用法:
  /opt/ugc_clone/asr_venv/bin/python transcribe.py <audio.wav> <out_words.json> [--model large-v3]

环境:asr_venv 是基于 h3director 的 --system-site-packages venv,复用它的 torch 和
nvidia 运行库,只额外装 faster-whisper / yt-dlp,不改 h3director。
WhisperX 装不上(新版锁 torch 2.8,旧版的 pyannote 3 不兼容 torchaudio 2.9),
所以这里直接用它底层的 faster-whisper,时间戳来自交叉注意力 DTW,中文按字/词输出。
"""
import argparse
import glob
import json
import os
import sys

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 新版 huggingface_hub 默认走 Xet 直连 hf.co,会绕过镜像并报 401
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def preload_cuda_libs():
    # ctranslate2 要 cuBLAS 12 / cuDNN 9,从 torch 附带的 nvidia 包里加载,免得配 LD_LIBRARY_PATH
    import ctypes
    import site
    roots = site.getsitepackages()
    for pattern in ("nvidia/cublas/lib/libcublas.so.*", "nvidia/cublas/lib/libcublasLt.so.*",
                    "nvidia/cudnn/lib/libcudnn*.so.*"):
        for root in roots:
            for path in sorted(glob.glob(os.path.join(root, pattern))):
                try:
                    ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


# 不给提示词时 large-v3 常输出繁体,这句能把它拉回简体
ZH_PROMPT = "以下是普通话的句子,使用简体中文。"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("out")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--language", default="zh")
    ap.add_argument("--prompt", default=ZH_PROMPT)
    # 有背景音乐时 large-v3 会整段幻觉成"请不吝点赞订阅转发",开 VAD 先切出人声
    ap.add_argument("--vad", action="store_true")
    args = ap.parse_args()

    preload_cuda_libs()
    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, device="cuda", compute_type="float16")
    seg_iter, info = model.transcribe(
        args.audio, language=args.language, word_timestamps=True,
        initial_prompt=args.prompt, vad_filter=args.vad, beam_size=5,
        vad_parameters={"min_silence_duration_ms": 300} if args.vad else None,
        condition_on_previous_text=False,
    )

    segments = []
    for seg in seg_iter:
        words = [{
            "word": w.word.strip(),
            "start": round(w.start, 3),
            "end": round(w.end, 3),
            "score": round(w.probability, 3),
        } for w in (seg.words or []) if w.word.strip()]
        segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": words,
        })

    out = {
        "schema": "words/v0.1",
        "audio": os.path.basename(args.audio),
        "duration": round(info.duration, 3),
        "engine": "faster-whisper",
        "model": args.model,
        "language": args.language,
        "segments": segments,
        "stats": {
            "segments": len(segments),
            "words": sum(len(s["words"]) for s in segments),
            "low_confidence_words": sum(1 for s in segments for w in s["words"] if w["score"] < 0.5),
        },
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    for s in segments:
        print(f"[{s['start']:6.2f} - {s['end']:6.2f}] {s['text']}")
    print(json.dumps(out["stats"], ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
