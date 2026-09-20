# ugc_clone — Claude Code 说明

分工表和两边共同的规矩在 AGENTS.md(Codex 也读这一份,以它为准):

@AGENTS.md

Codex 默认连续负责第 1–6 步;Claude 只在 `keyframes/READY.json` 已存在且门禁通过后负责第 7–8 步
(H3 生成、重跑、成片技术/台词验收)。做法和踩过的坑在 `.claude/skills/ugc-voiceover-clone/SKILL.md`,
开工前先用这个 skill。用户明确改派时照用户要求,并在 `events.en.jsonl` 记录 `actor`。
