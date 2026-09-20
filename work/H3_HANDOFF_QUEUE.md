# H3 Render Handoff Queue

Updated: 2026-09-20

Both jobs have completed local analysis, product facts, scripts, shot plans, Codex ImageGen keyframes, visual QC and the sealed local preflight. Claude should begin at workflow stage 7. Do not regenerate or replace the approved keyframes unless a new visual defect is reported.

Before uploading either job, run this locally and continue only on `PASS`:

```powershell
D:/anaconda/envs/ugc_asr/python.exe -B -m ugc_pipeline preflight inputs/<job>/job.en.json --actor claude
```

## Queue order

1. `crown_almond_bis_shot_for_shot`
2. `fish_glass`

## 1. Crown Almond Biscuits

- Job ID: `crown_almond_bis_sfs_en`
- Status: `keyframes_ready`
- Format: English hands-only shot-for-shot product voiceover
- Structure: 21 Hypit source microshots grouped into 4 timed multi-reference H3 clips; 8 approved generated keyframes total
- Final source-matched duration: `19.033` seconds
- Expected H3 jobs: 1 job containing 4 clips; every clip binds two generated composition frames plus the original product image
- Product message: simple family-sharing snack; show the packet and biscuit; pair with milk; finish with a natural “come give Crown Almond Biscuits a try” CTA
- Restrictions: no price, no unsupported ingredients/nutrition claims, no fabricated personal story, no face
- Packaging: bind the supplied product reference as authoritative; use `fully_preserved` treatment if dense carton copy drifts

Claude inputs:

- Job: `inputs/crown_almond_bis/job.shot-for-shot.en.json`
- Product facts: `inputs/crown_almond_bis/product.en.json`
- Script: `work/crown_almond_bis_shot_for_shot/variants/v001/script.en.json`
- Shot map: `work/crown_almond_bis_shot_for_shot/shot_map.json`
- Shot plan: `work/crown_almond_bis_shot_for_shot/variants/v001/shot_plan.json`
- Keyframe QC: `work/crown_almond_bis_shot_for_shot/keyframes/QC.json`
- Render handoff: `work/crown_almond_bis_shot_for_shot/keyframes/READY.json`
- Timed H3 grouping: `work/crown_almond_bis_shot_for_shot/h3_clip_plan.json`
- Compiled prompts: `work/crown_almond_bis_shot_for_shot/segments.json`
- Preflight report: `work/crown_almond_bis_shot_for_shot/PREFLIGHT.json`
- Reference analysis: `references/crown_almond_bis/ANALYSIS.md`
- Reference timeline: `references/crown_almond_bis/TIMELINE.md`

Stage 7 instruction:

> Use the sealed `segments.json`: render 4 silent H3 clips in one job, not 8 or 21 separate videos. Each prompt contains all Hypit-derived internal cuts for its source window. Trim to 5.800 / 4.633 / 5.134 / 3.466 seconds, assemble without retiming to exactly 19.033 seconds, add one continuous approved English voice-over, then run `check_shot_rhythm.py` and voice/text QA before user review.

## 2. Fish-Pattern Glass

- Job ID: `fish_glass_silent_en`
- Status: `keyframes_ready`
- Format: silent hands-only shot clone
- Structure: 9 story beats represented by 13 approved keyframes, grouped into 10 scene-compatible timed H3 clips
- Final source-matched duration: `26.533` seconds
- Expected H3 jobs: 1 job containing 10 clips; each clip binds 2–3 Pictures and keeps one tabletop/scene anchor
- Audio rule: no dialogue, voiceover, vocal performance, subtitles or caption overlays; music or natural ambience only
- Edit rule: preserve the reference shot order and each `source_edit_duration_seconds`
- Corrected shot: `seg04` uses a realistic full-size 1.5-litre household glass water pitcher, about 1.7–2 times the target glass width; do not use an earlier miniature-pitcher version

Claude inputs:

- Job: `inputs/fish_glass/job.en.json`
- Product facts: `inputs/fish_glass/product.en.json`
- Silent visual script: `work/fish_glass/variants/v001/script.en.json`
- Shot plan: `work/fish_glass/variants/v001/shot_plan.json`
- Keyframe QC: `work/fish_glass/keyframes/QC.json`
- Render handoff: `work/fish_glass/keyframes/READY.json`
- Timed H3 grouping: `work/fish_glass/h3_clip_plan.json`
- Compiled prompts: `work/fish_glass/segments.json`
- Preflight report: `work/fish_glass/PREFLIGHT.json`
- Reference analysis: `references/fish_glass/ANALYSIS.md`
- Reference timeline: `references/fish_glass/TIMELINE.md`

Stage 7 instruction:

> Use the already compiled `work/fish_glass/segments.json`: render 10 silent H3 clips in one job, not 13 separate videos. Each prompt maps its 2–3 Pictures to explicit second ranges and never mixes conflicting tabletop or scene anchors. Preserve the corrected full-size water pitcher in H04/seg04, trim each result to `trim_to_seconds`, and assemble in order to exactly 26.533 seconds. Do not create speech, captions or text overlays.

## Completion rules

- Keep `source_job_id` as `null`; both are new full videos.
- Render only while a fresh `preflight --actor claude` returns PASS. A failed integrity check invalidates the active READY and rolls the job back to `awaiting_keyframes`.
- Use only the current approved files referenced by each `READY.json`.
- After rendering, perform technical checks and dialogue verification where applicable.
- User performs the final visual acceptance.
