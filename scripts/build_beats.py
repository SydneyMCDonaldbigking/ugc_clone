"""S3 节拍表:词级时间 + 切点 + 人工标注 → beats.json。纯标准库,本地可跑。

用法: python build_beats.py <work_dir> <labels.json>

labels.json 是 agent 看帧后写的标注,每拍给出时间窗和功能,文本/字数/停顿由本脚本从
words.json 里按时间窗自动取,避免手抄出错。corrections 用烧录字幕修正 ASR 错字。
"""
import json
import sys
from pathlib import Path


def main():
    work = Path(sys.argv[1])
    labels = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    words_doc = json.loads((work / "words.json").read_text(encoding="utf-8"))
    cuts = json.loads((work / "cuts.json").read_text(encoding="utf-8"))
    probe = json.loads((work / "probe.json").read_text(encoding="utf-8"))

    words = [w for s in words_doc["segments"] for w in s["words"]]
    punct = ",。!?、,.!? "

    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    num, den = video["r_frame_rate"].split("/")
    duration = float(probe["format"]["duration"])

    beats = []
    spoken_chars = 0
    for i, lab in enumerate(labels["beats"]):
        t0, t1 = lab["t"]
        ws = [w for w in words if t0 <= (w["start"] + w["end"]) / 2 < t1]
        asr_text = "".join(w["word"] for w in ws)
        ref_text = lab.get("ref_text_corrected") or asr_text
        chars = sum(1 for c in ref_text if c not in punct)
        spoken_chars += chars
        speech_start = ws[0]["start"] if ws else t0
        speech_end = ws[-1]["end"] if ws else t1
        nxt = labels["beats"][i + 1]["t"][0] if i + 1 < len(labels["beats"]) else duration
        nxt_ws = [w for w in words if w["start"] >= speech_end]
        pause = round(((nxt_ws[0]["start"] if nxt_ws else duration) - speech_end) * 1000)
        beats.append({
            "id": lab["id"],
            "t_start": t0,
            "t_end": t1,
            "speech": [round(speech_start, 2), round(speech_end, 2)],
            "function": lab["function"],
            **({"hook_type": lab["hook_type"]} if "hook_type" in lab else {}),
            "char_count": chars,
            "cps": round(chars / max(speech_end - speech_start, 0.1), 1),
            "intensity": lab.get("intensity"),
            "pause_after_ms": max(pause, 0),
            "cuts_inside": [c["t"] for c in cuts if t0 < c["t"] < t1],
            "shot": lab["shot"],
            "visual_action": lab["visual_action"],
            "visual_sync": lab.get("visual_sync"),
            "caption_emphasis": lab.get("caption_emphasis"),
            "proof_category": lab.get("proof_category"),
            "notes": lab.get("notes"),
            "ref_text": ref_text,
            "asr_text": asr_text,
        })

    speech_time = words[-1]["end"] - words[0]["start"]
    out = {
        "schema": "beats/v0.1",
        "source": {"file": labels["source"], "duration": round(duration, 2),
                   "fps": round(int(num) / int(den), 2),
                   "size": f'{video["width"]}x{video["height"]}'},
        "speech_rate_cps": round(spoken_chars / speech_time, 1),
        "total_chars": spoken_chars,
        "cuts": [c["t"] for c in cuts],
        "structure_notes": labels.get("structure_notes", []),
        "beats": beats,
    }
    (work / "beats.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{out['source']}  {out['speech_rate_cps']} 字/秒  共 {spoken_chars} 字")
    for b in beats:
        print(f"{b['id']:>3} {b['t_start']:5.2f}-{b['t_end']:5.2f} {b['function']:<28} "
              f"{b['char_count']:>2}字 {b['cps']}字/s 停{b['pause_after_ms']}ms 切{b['cuts_inside']}  {b['ref_text']}")


if __name__ == "__main__":
    main()
