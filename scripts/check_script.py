"""S5 口播稿硬检查。纯标准库。

用法: python check_script.py <beats.json> <product.json> <script.json>

检查:结构对齐、字数预算、与原稿重合、禁用词、宣称挂证据。任何一项 FAIL 退出码为 1。
"""
import json
import re
import sys
from pathlib import Path

PUNCT = re.compile(r"[\s,。!?、,.!?:;:;\"'“”‘’()()《》…—-]")
# 广告法 + 本品类没有证据的词;按品类扩展
BANNED = ["最", "第一", "顶级", "国家级", "治疗", "减肥", "瘦身", "代餐", "减脂", "控卡",
          "无糖", "低糖", "0糖", "零糖", "蔗糖", "代糖", "乳糖", "希腊", "原价", "限时", "秒杀", "全网"]


def norm(s):
    return PUNCT.sub("", s)


def ngrams(s, n):
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def longest_common(a, b):
    best = ""
    for i in range(len(a)):
        for j in range(i + len(best) + 1, len(a) + 1):
            if a[i:j] in b:
                best = a[i:j]
            else:
                break
    return best


def main():
    beats = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    product = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    script = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    fact_ids = {f["id"] for f in product["facts"]}
    beat_by_id = {b["id"]: b for b in beats["beats"]}
    rate = script.get("time_scale", 1.0)
    tol = script.get("char_tolerance", 0.15)
    replica = script.get("mode", "structure") == "replica"

    fails, warns = [], []
    ref_all = norm("".join(b["ref_text"] for b in beats["beats"]))

    # 结构:每拍都要覆盖,顺序一致
    covered = [bid for line in script["lines"] for bid in line["beats"]]
    expected = [b["id"] for b in beats["beats"] if b["id"] not in script.get("dropped_beats", {})]
    if covered != expected:
        fails.append(f"结构不对齐: 稿子 {covered} vs 节拍表 {expected}")
    for bid, why in script.get("dropped_beats", {}).items():
        warns.append(f"弃用 {bid}: {why}")

    for line in script["lines"]:
        text = norm(line["text"])
        budget = sum(beat_by_id[b]["char_count"] for b in line["beats"]) * rate
        lo, hi = budget * (1 - tol), budget * (1 + tol)
        tag = f"{line['id']}({'+'.join(line['beats'])})"
        status = "ok" if lo <= len(text) <= hi else "FAIL"
        if status == "FAIL":
            fails.append(f"{tag} 字数 {len(text)} 不在 [{lo:.0f}, {hi:.0f}]")
        ref = norm("".join(beat_by_id[b]["ref_text"] for b in line["beats"]))
        g5 = ngrams(text, 5)
        overlap = len(g5 & ngrams(ref_all, 5)) / max(len(g5), 1)
        lcs = longest_common(text, ref_all)
        # replica 模式(测试用,贴原稿句式)只提示重合,不拦;量产必须用 structure 模式
        sink = warns if replica else fails
        if overlap >= 0.10:
            sink.append(f"{tag} 与原稿 5-gram 重合 {overlap:.0%}")
        if len(lcs) >= 6:
            sink.append(f"{tag} 与原稿公共子串过长: '{lcs}'")
        for w in BANNED:
            if w in text.replace("最近", ""):
                fails.append(f"{tag} 含禁用词 '{w}'")
        bad = [c for c in line.get("claims", []) if c not in fact_ids]
        if bad:
            fails.append(f"{tag} 宣称引用不存在的证据 {bad}")
        if re.search(r"\d", line["text"]):
            warns.append(f"{tag} 含阿拉伯数字,H3 念数字不稳,建议写成汉字")
        print(f"{tag:<16} {len(text):>2}字 预算{budget:4.0f} 重合{overlap:4.0%} 最长公共'{lcs}'  {line['text']}")

    for w in warns:
        print("WARN", w)
    for f in fails:
        print("FAIL", f)
    if replica:
        print("MODE replica: 贴原稿句式,只能用于测试,不能批量发布")
    print("PASS" if not fails else f"{len(fails)} FAIL")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
