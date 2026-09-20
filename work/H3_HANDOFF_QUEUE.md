# H3 Render Handoff Queue

Updated: 2026-09-20

Both jobs have completed local analysis, product facts, scripts, shot plans, Codex ImageGen keyframes, visual QC and the sealed local preflight. Claude should begin at workflow stage 7. Do not regenerate or replace the approved keyframes unless a new visual defect is reported.

Before uploading either job, run this locally and continue only on `PASS`:

```powershell
D:/anaconda/envs/ugc_asr/python.exe -B -m ugc_pipeline preflight inputs/<job>/job.en.json --actor claude
```

## Queue order

1. `crown_almond_bis`
2. `fish_glass`

## 1. Crown Almond Biscuits

- Job ID: `crown_almond_bis_en`
- Status: `keyframes_ready`
- Format: English hands-only product voiceover
- Structure: 4 segments, approximately 20 seconds before final assembly adjustments
- Product message: simple family-sharing snack; show the packet and biscuit; pair with milk; finish with a natural “come give Crown Almond Biscuits a try” CTA
- Restrictions: no price, no unsupported ingredients/nutrition claims, no fabricated personal story, no face
- Packaging: bind the supplied product reference as authoritative; use `fully_preserved` treatment if dense carton copy drifts

Claude inputs:

- Job: `inputs/crown_almond_bis/job.en.json`
- Product facts: `inputs/crown_almond_bis/product.en.json`
- Script: `work/crown_almond_bis/variants/v001/script.en.json`
- Shot plan: `work/crown_almond_bis/variants/v001/shot_plan.json`
- Keyframe QC: `work/crown_almond_bis/keyframes/QC.json`
- Render handoff: `work/crown_almond_bis/keyframes/READY.json`
- Preflight report: `work/crown_almond_bis/PREFLIGHT.json`
- Reference analysis: `references/crown_almond_bis/ANALYSIS.md`
- Reference timeline: `references/crown_almond_bis/TIMELINE.md`

Stage 7 instruction:

> Compile the four English H3 segments from the approved shot plan and READY manifest, bind each approved keyframe plus its listed product reference, render, assemble, transcribe the finished video to verify the English lines, and return the visual result for user review.

## 2. Fish-Pattern Glass

- Job ID: `fish_glass_silent_en`
- Status: `keyframes_ready`
- Format: silent hands-only shot clone
- Structure: 9 story beats expanded to 13 generated clips
- Final source-matched duration: `26.533` seconds
- Expected H3 batches: 4, with no more than 4 clips per batch
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
- Preflight report: `work/fish_glass/PREFLIGHT.json`
- Reference analysis: `references/fish_glass/ANALYSIS.md`
- Reference timeline: `references/fish_glass/TIMELINE.md`

Stage 7 instruction:

> Compile all 13 silent H3 clips from the approved shot plan and READY manifest. Render in four batches, preserve the corrected full-size water pitcher in seg04, then trim and assemble the clips in reference order to exactly 26.533 seconds. Do not create speech, captions or text overlays.

## Completion rules

- Keep `source_job_id` as `null`; both are new full videos.
- Render only while a fresh `preflight --actor claude` returns PASS. A failed integrity check invalidates the active READY and rolls the job back to `awaiting_keyframes`.
- Use only the current approved files referenced by each `READY.json`.
- After rendering, perform technical checks and dialogue verification where applicable.
- User performs the final visual acceptance.
