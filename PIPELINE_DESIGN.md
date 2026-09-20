# English UGC Clone Pipeline — End-to-End Design

Status: design only  
Date: 2026-09-19  
Default output language: English  
Reference implementation baseline: `ugc_clone_pipeline` current `main`

## 1. Objective

Turn one proven short-form product video into multiple English UGC ads for a different, evidence-backed product while preserving only reusable structure:

- timing and beat order;
- hook type and information order;
- shot purpose and dialogue-to-visual alignment;
- intensity, pacing, and continuity rules.

The pipeline must not inherit the original creator's face, voice, exact script, product, brand, unsupported claims, or personal experience.

The finished system begins with a reference video plus product evidence and ends with:

- one or more English scripts;
- per-segment ImageGen reference frames;
- rendered H3 segments and assembled video;
- English captions;
- technical, language, claim, and human-review reports;
- a resumable record of every artifact and retry.

## 2. Fixed decisions

These are design constraints, not open questions.

1. Reference videos may contain any language. Source transcription stays isolated in analysis artifacts.
2. All new audience-facing output is English only: voice-over, dialogue, captions, CTA, price copy, on-screen overlays, and H3 dialogue tags. `audio_mode` describes the final edit; `render_plan.h3_audio_mode` separately describes whether H3 itself speaks. Exact-timing `shot_for_shot` clips render silent and receive one continuous English master voice-over after trimming.
   A visually driven source may instead declare `audio_mode: silent`; then dialogue is empty, each script line carries an English `visual_direction`, and neither H3 nor the final edit receives dialogue.
3. Production variants use `structure` mode. `replica` remains test-only and cannot enter the publishing path.
4. H3 clips default to about 5 seconds, may be 2–15 seconds each, and a submission contains at most 20 clips. Internal microshots may be shorter than 2 seconds.
5. Product claims must resolve to an evidence-bearing fact ID. Unknown values stay `null`; they are never inferred.
6. Codex uses the ImageGen tool built into the current session. The pipeline does not integrate OpenAI Image API or OpenRouter for the default keyframe path.
7. For `shot_for_shot`, Codex stops only after image inspection, atomic creation of `READY.json`, deterministic compilation of `h3_clip_plan.json` and `segments.json`, semantic validation, integrity sealing with `keyframe-status`, and a passing local `preflight`.
8. Claude Code owns server transfer, rendering, reruns, assembly, and final QA only after rerunning `preflight --actor claude` successfully. It consumes sealed `shot_for_shot` prompts without editing their timing or Picture order.
9. Generated packaging text is not trusted. Dense labels use original pixels, `fully_preserved`, or a static packshot fallback.
10. Nothing is auto-published. A human approval state is mandatory.
12. How people appear follows the reference, never a default: `presenter.mode` is `generated_fictional` (someone talks to camera), `hands_only` or `none` (voice-over), read from the archive's ANALYSIS and enforced by `validate` (template and reference roles must match the mode; only `generated_fictional` gets a presenter master).
11. No image cut from the source video is ever given to an image model or to H3, in any role. The source video is analysed as text (transcript, beats, shot descriptions) only.

## 3. Responsibility model

The authoritative, stage-by-stage owner table (who, where, command, output, done-signal) is at the top of `AGENTS.md`; this section summarises it.

| Actor | Owns | Stops at |
| --- | --- | --- |
| Operator | Supplies the reference video, product images, verified product facts, price, market, and final approval | Approves or rejects the final deliverable |
| Codex | Default owner of all local pre-render work: source analysis and transcription, beat construction, product evidence, English script generation, shot planning, keyframe request creation, built-in ImageGen, image QC, `READY.json`, deterministic shot-for-shot H3 compilation, integrity sealing and preflight | `keyframes_ready` with a passing `PREFLIGHT.json` |
| Claude Code | Starts only after its own passing preflight; consumes the sealed shot-for-shot submission package and owns server transfer, rendering, reruns, assembly, and technical/dialogue QA | Produces a final review package |
| Local workstation | Transcription (conda env `ugc_asr`, RTX 4070), reference archive, scripts, keyframes, H3 prompt compilation | Hands finished scripts and keyframes to the server |
| GPU server | H3 generation and upscaling only | Returns artifacts and machine report |

No actor silently takes over another actor's stage. The default handoff is Codex → Claude at a validated, integrity-sealed `READY.json` plus passing `PREFLIGHT.json`; handoffs happen through versioned JSON files and artifact hashes.

Codex authors the planning stages (transcription/archive, beats, product evidence, English script, shot plan and keyframe request) by default and continues directly into ImageGen. The operator may explicitly reassign a stage; whoever writes an artifact records `"actor": "codex"` or `"claude"` in the event log. Server transfer, H3 and final QA stay with Claude.

## 4. Top-level flow

```text
S0  Create job
 ↓
S1  Ingest and inspect reference media
 ↓
S2  Source-language transcription and timing
 ↓
S3  Beat extraction and structural sanitization
 ↓
S4  Product evidence normalization into English
 ↓
S5  English structure-mode script variants
 ↓
S6  Shot planning and keyframe requests
 ↓
S7  Codex ImageGen keyframes → READY.json → integrity seal → PREFLIGHT.json
 ↓
S8  Keyframe intake and H3 prompt compilation
 ↓
S9  Segment rendering and targeted reruns
 ↓
S10 Assembly, English captions, and delivery encoding
 ↓
S11 Automated QA → human review → approved/rejected
```

## 5. Job state machine

Canonical states:

```text
created
ingested
transcribed
beats_ready
facts_ready
scripts_ready
shots_ready
awaiting_keyframes
keyframes_ready
rendering
rendered
assembled
qa_passed
human_review
approved
rejected
blocked
```

Rules:

- A stage may advance only when its output contract passes validation.
- A retry increments `attempt` but does not erase previous artifacts.
- A stage is idempotent: identical input hashes reuse the existing artifact.
- `blocked` requires a recorded reason and required operator action.
- `approved` is the only state eligible for manual publishing.
- Publishing is outside this repository's scope.

## 6. Directory contract

The design extends the existing layout instead of replacing it.

```text
inputs/<job>/
  job.json
  ref_video.mp4
  product.en.json
  product_front.png
  product_back.png
  product_detail_*.png
  scene_pack/                       registered empty eye-level / oblique / overhead scene anchors
  presenter_master.png              optional existing identity anchor

work/<job>/
  state.json
  probe.json
  audio.wav
  words.source.json
  cuts.json
  labels.json
  beats.json
  variants/
    v001/
      script.en.json
      shot_plan.json
      keyframes/
        REQUEST.json
        seg01.png
        seg02.png
        seg03.png
        seg04.png
        READY.json
        READY.invalidated.<UTC>.json
      PREFLIGHT.json
      segments.json
      segments.server.json
      render_manifest.json
    v002/
      ...
  events.jsonl

out/<job>/
  v001/
    final.mp4
    captions.en.srt
    report.json
    review.json
  v002/
    ...
```

Raw videos, product images, generated images, and rendered outputs remain ignored by Git. Schemas, prompts, code, and non-sensitive reports may be versioned.

## 7. Core data contracts

### 7.1 `job.json`

```json
{
  "schema": "ugc-job/v1",
  "job_id": "a2-milk-en-001",
  "reference_video": "inputs/a2-milk-en-001/ref_video.mp4",
  "source_language": "auto",
  "target_language": "en-AU",
  "mode": "structure",
  "variants": 3,
  "segment_duration_seconds": 5,
  "max_segments_per_render": 4,
  "product": "inputs/a2-milk-en-001/product.en.json",
  "presenter": {
    "mode": "generated_fictional",
    "master_image": null
  },
  "image_provider": "codex-imagegen",
  "video_provider": "h3",
  "human_review_required": true
}
```

Validation:

- `target_language` must start with `en`.
- `mode` must be `structure` for production jobs.
- durations and segment counts must respect the H3 memory limit.
- referenced files must resolve inside the job or repository workspace.

### 7.2 `product.en.json`

```json
{
  "schema": "product/v1",
  "language": "en-AU",
  "name": "a2 Full Cream Milk",
  "brand": "a2",
  "spec": {"volume_ml": 2000, "pack_qty": 6},
  "price": {"currency": "AUD", "unit_price": 6.79},
  "facts": [
    {
      "id": "F1",
      "text": "Naturally free from A1 protein.",
      "evidence": "target_A2_2.png",
      "evidence_type": "package_label"
    }
  ],
  "forbidden_claims": [
    "weight loss",
    "medical benefit",
    "lowest price"
  ],
  "visual_assets": ["target_A2_1.png", "target_A2_2.png"]
}
```

Every `facts[]` entry requires a non-empty evidence reference. Translation into English changes wording, not factual scope.

### 7.3 `script.en.json`

```json
{
  "schema": "script/v1",
  "language": "en-AU",
  "mode": "structure",
  "variant_id": "v001",
  "lines": [
    {
      "id": "L1",
      "segment": 1,
      "beats": ["B1", "B2"],
      "text": "My husband thought I had won the lottery when he saw all this milk.",
      "claims": [],
      "target_duration_seconds": 5,
      "delivery": "Playful, conversational, medium-fast pace."
    }
  ]
}
```

Hard gates:

- no CJK characters in audience-facing fields;
- all beat IDs covered once and in order unless a dropped beat has a reason;
- every claim ID exists and has evidence;
- no forbidden claim or unsupported number;
- natural English target rate of roughly 2.3–3.0 words per second;
- a 5-second segment normally targets 12–15 words, with a configurable hard ceiling;
- no exact phrase of eight or more words copied from an English reference transcript;
- pairwise word 3-gram overlap between variants stays below the configured diversity threshold.

### 7.4 `shot_plan.json`

```json
{
  "schema": "shot-plan/v1",
  "language": "en",
  "variant_id": "v001",
  "segments": [
    {
      "id": "S03",
      "duration_seconds": 5,
      "dialogue": "Check the ingredient panel: it contains milk and no added fillers.",
      "shot_type": "product_label_closeup",
      "subject": "One hand supporting the bottle without changing its verified silhouette.",
      "action": "Hold completely still with the back label square to camera.",
      "continuity": "hard_cut",
      "keyframe_strategy": "codex-imagegen-edit",
      "references": [
        "inputs/a2_test/presenter.jpg",
        "target_A2_2.png"
      ],
      "preserve": ["bottle shape", "blue cap", "back label placement"],
      "exclude": ["second hand", "other products", "generated packaging text"],
      "label_policy": "original_pixels_or_fully_preserved"
    }
  ]
}
```

Each segment describes one continuous action. Cuts inside a segment are invalid.

### 7.5 `REQUEST.json`

Written by Codex after shot planning and consumed by Codex's ImageGen stage. A user-directed alternate author records its actor in the event log.

```json
{
  "schema": "keyframe-request/v1",
  "job": "a2_test",
  "variant_id": "v001",
  "source_job_id": "a2-replica-004",
  "output_aspect_ratio": "9:16",
  "segments": {
    "3": {
      "prompt_file": "work/a2_test/keyframes/seg03_prompt.txt",
      "references": [
        "inputs/a2_test/presenter.jpg",
        "target_A2_2.png"
      ],
      "output": "seg03.png",
      "checks": [
        "exactly one hand",
        "back label faces camera",
        "no other product",
        "no original creator"
      ]
    }
  }
}
```

### 7.6 `READY.json`

Written by Codex only after every listed image exists and has been inspected.

```json
{
  "schema": "keyframe-ready/v1",
  "job": "a2_test",
  "variant_id": "v001",
  "source_job_id": "a2-replica-004",
  "segments": {
    "3": {
      "keyframe": "seg03.png",
      "extra_refs": ["target_A2_2.png"],
      "notes": "Exactly one hand; back label square to camera; dense text must use the original product image path."
    }
  },
  "generator": "codex-imagegen",
  "created_by": "codex"
}
```

`READY.json` is a proposed completion signal, not a scratch file. It must be written after all images and QC, preferably atomically through a temporary file followed by a same-directory rename. It authorizes no render until `keyframe-status` seals the inputs and `preflight` writes a passing `PREFLIGHT.json`.

## 8. Stage specifications

### S0 — Create job

Input:

- reference video or URL;
- product images;
- operator-confirmed facts and price;
- requested variant count and market locale.

Actions:

- allocate a unique job ID;
- create the directory skeleton;
- write `job.json` and initial `state.json`;
- record hashes for immutable inputs.

Gate:

- required assets exist;
- target language is English;
- production mode is `structure`;
- no secret is stored in the job directory.

### S1 — Ingest and inspect media

Reuse `scripts/prep.sh` to produce:

- `probe.json`;
- 16 kHz mono `audio.wav`;
- timestamped overview frames;
- paginated contact sheets;
- candidate cuts and before/after comparison sheets;
- `analysis.json` from `scripts/analyze_reference_video.py`.

Gate:

- video and audio streams exist;
- duration is readable;
- audio is not silent;
- `analysis.json`, `beats.json`, and `job.reference_video` identify the same source file;
- cut candidates receive manual or agent confirmation.

### S2 — Source transcription

Reuse `scripts/transcribe.py`, but treat source language independently from target language.

Rules:

- source language may be auto-detected or explicitly supplied;
- `words.source.json` is analysis-only;
- background-music recovery may use filtering, VAD, and segmented passes;
- repaired or merged timing must carry provenance notes.

Gate:

- every retained spoken token has a time range;
- low-confidence and manually corrected spans are recorded;
- source text never becomes target copy by default.

### S3a — Reference archive: ANALYSIS.md and TIMELINE.md

Ported from hypit's reference-video flow. One archive per reference video under `references/<ref_id>/`, reusable by every product adapted from it; `job.reference_archive` links it and `validate` refuses a job whose archive still has TODO sections or a PROGRESS.md.

1. `scripts/reference_archive.py init <video> <ref_id> (--transcribe [--vad] | --transcript <json>)` writes probe, cuts, boundaries, transcript, evidence grids (paged overview, before/after every cut, one dense grid per spoken line — all word-labelled via `scripts/media.py`) and scaffolds ANALYSIS/TIMELINE/PROGRESS with the facts filled in and interpretation left as TODO.
2. The agent reads the overview end to end and writes ANALYSIS (what the viewer should conclude, arc, what each system does, roles to preserve), then TIMELINE section by section, re-sampling doubtful passages with `reference_archive.py tile <ref_id> --around "<phrase>" --every 0.1`, and revises ANALYSIS when a close look changes it.
3. Open questions live in PROGRESS.md; when none remain it is deleted and `reference_archive.py check <ref_id>` prints READY.
4. Adaptation preserves the role and recreates the form; timing binds to words in the new script, not to source seconds. The archive's images never go to a generation model.

### S3 — Beat extraction and sanitization

Inputs:

- source words;
- cuts;
- inspected frames;
- human/agent labels.

Output:

- `beats.json` with function, timing, shot type, intensity, word/character budget, visual action, and synchronization intent.

Sanitization rule:

- exact source wording stays in a restricted comparison field or companion artifact;
- the script generator receives structural fields, not the original copy.

Gate:

- beat windows cover the full timeline without overlap or gaps;
- every beat has a function and shot purpose;
- every source-brand or creator-specific feature is excluded.

### S4 — Product evidence normalization

Actions:

- extract candidate product facts from packaging and operator input;
- translate only verified facts into English;
- attach evidence type and path;
- record forbidden claims and unknown values.

Gate:

- every fact has evidence;
- prices, quantities, ingredients, and nutrition numbers exactly match evidence;
- no personal-use claim is invented for a fictional presenter.

### S5 — Generate English script variants

Actions:

- combine structural beats with English product facts;
- create the requested number of `structure` variants;
- fit each line to its segment duration;
- preserve information order while varying wording, hook expression, and transitions.

Validation order:

1. English-only gate;
2. beat coverage and order;
3. duration/word-count budget;
4. claim-to-evidence resolution;
5. forbidden-claim scan;
6. source-copy overlap;
7. cross-variant diversity.

Only the failing line is regenerated. Passing lines remain unchanged.

### S6 — Plan shots and request keyframes

For every line, produce:

- shot scale and camera position;
- one continuous action;
- one beat-specific performance state covering expression, gaze, posture, and physical effort;
- visible hands and product count;
- presenter visibility;
- reference roles;
- continuity policy;
- label preservation policy;
- negative constraints;
- English H3 dialogue.

Codex writes `REQUEST.json`, advances the job to `awaiting_keyframes`, and continues directly into the ImageGen stage.

Coverage gate:

- every source hard cut is mapped to a target segment or explicitly marked as intentionally omitted;
- every shot-plan segment whose strategy is `codex-imagegen-edit` appears exactly once in `REQUEST.json`;
- a script segment may declare multiple `keyframe_ids` when the reference structure contains a meaningful hard-cut insert, such as quantity display followed by a product hero close-up;
- product proof and product display are separate visual functions: a back-label evidence shot never replaces a front-label hero close-up;
- a partial keyframe request is invalid unless the omitted segment explicitly reuses an already approved keyframe;
- source-video identity, variant ID, prompt path, reference paths, and output filename are validated before handoff.

### S7 — Codex ImageGen keyframes

Codex workflow:

1. Read `AGENTS.md`, `REQUEST.json`, prompt file, and all referenced images.
2. Compile each prompt from `templates/keyframe_prompt.en.txt`, the shot plan, reference-role metadata, and the current product's `visual_identity`; never hand-author a product-specific shared template.
3. Inspect the analyzed reference-video storyboards and every image reference before editing.
4. Reject the request if it does not cover every ImageGen segment in the shot plan or if reference roles are ambiguous.
5. Reuse one fictional presenter identity across every segment.
6. Select the declared fidelity path: `reference_lock` for interaction-heavy lifestyle shots, or `pixel_preserve` for identity-critical product planes.
7. Before keyframes, generate and register one empty three-view scene pack (`eye_level`, `oblique_45`, `overhead_90`) from the written source-setting description. Then generate each fresh 9:16 keyframe from the camera-matched scene view, the registered presenter master when applicable, and the original product photo. In `pixel_preserve`, treat the model output as the scene layer, then run `scripts/composite_product_packshot.py` so the displayed package and dense label come from the original packshot pixels. Record the packshot hash and placement in QC; if clean extraction is not possible, use H3 `fully_preserved` or the static packshot fallback instead of accepting redrawn copy.
8. Inspect each result for identity, hands, product shape/count, composition, original-brand leakage, and unwanted text.
9. Iterate only the failed image.
10. Save final images as `segNN.png`.
11. Write `READY.json` after all images and QC.
12. For `shot_for_shot`, run `build_timed_h3_prompts.py` to deterministically compile the final `segments.json` from the validated shot plan, H3 clip plan and READY image paths.
13. Run `keyframe-status --actor codex`; it must reject any cut-time, Picture-order, image-list or prompt drift before sealing every render-authorizing input by SHA256.
14. Run `preflight --actor codex`; stop only after it writes `PREFLIGHT.json` with `status: pass`. Do not submit H3 or modify Claude's rendering orchestration.

Keyframe rules:

- never use a frame containing the original creator as an identity reference;
- never ask ImageGen to faithfully redraw dense packaging copy;
- if exact label text is required, use the real packshot compositor; if its extraction cannot pass QC, state that Claude must bind the original image as `fully_preserved` or use the packshot fallback;
- prompts and handoff notes are written in English for all new jobs;
- generated overlay text is prohibited.
- the reusable template must remain product-agnostic: no package type, brand, shape, closure, label, handle, or material may be hard-coded in it;
- every reference has one declared role (`product_identity` or presenter/scene identity), and exactly one product-identity reference is required per keyframe;
- **no reference image may come from the source video** — no frames, anchors, grids or storyboards. They carry the source creator's face, product, watermark and captions, and an image model absorbs them whatever role is declared. Composition is described in the shot text only. `validate` rejects such paths and the `composition_only` role (`reference.source_frame`, `reference.role_forbidden`);
- product-specific language is injected only from `product.visual_identity`, the shot plan, and the current request's acceptance checks;
- `pixel_preserve` is mandatory when exact package pixels matter and the pose can match an available product reference; ImageGen supplies the scene while `scripts/composite_product_packshot.py` supplies the visible original product pixels;
- if a requested pose has no matching product view, simplify the pose, request another source view, or fall back to a static packshot—never hallucinate unseen product geometry;
- product geometry comes from a product-specific visual identity contract before any keyframe prompt is written;
- every keyframe is inspected against that contract; an invented handle, opening, closure, package type, or silhouette is an automatic rejection;
- a failed image's filename and concrete defect are retained in `ATTEMPTS.json`, while the failed binary is deleted after review; the next attempt is a **fresh generation from the registered scene-pack view, original presenter master and product photo** with an adjusted shot description — never an edit of the failed keyframe, and never with another keyframe as a reference;
- **scene continuity comes from one registered three-view scene pack**: Codex describes the reference setting in text, generates an empty `eye_level` base, then derives `oblique_45` and `overhead_90` views around the same physical table. `surface` is the hard identity lock; setting, backdrop, lighting, palette and props are soft guides. Close-ups may keep the product crisp while crop, parallax, visible props, slight local exposure and shallow-depth background bokeh vary. Each keyframe binds the view matching its camera; `scripts/set_scene_pack.py` pins all three hashes and `QC.json.scene_consistency` rejects only a changed table identity;
- **person continuity comes from one presenter master**: a single approved image of the fictional presenter in the job's scene with no product in it. Every applicable keyframe binds that file, its camera-matched scene-pack view and the original product photo. The scene pack and presenter master are the only generated images allowed as references; registration pins their hashes and `validate` fails if any file changes afterwards;
- **the source video's expressions and setting are copied as text**: the agent reads the storyboards and writes each shot's expression, posture and scene type into `performance` and `first_frame`. The frames themselves never go to the image model;
- keyframe prompts stay short and positive (about 150 words): only the still first-frame scene, the expression, and "copy the product from Image N". Forbidden features and the QC checklist stay in `REQUEST.json` for inspection and are not sent to the model, because naming a feature ("no handle") primes it;
- the product keeps the orientation of its reference photo (front or back square to the camera); whether it is held or set down, and the camera angle, follow the source shot recorded in TIMELINE (`镜头:` line) and the shot plan's required `camera` field (`shot size | height and angle | movement | framing`). Lifting, tilting and pouring happen in H3, not in the keyframe;
- `READY.json` is forbidden while `QC.json.result` is not `pass`, any request key lacks a QC entry, or any QC hash differs from the current image;
- after sealing, any changed, added, or missing render input invalidates the handoff: the active READY is recoverably renamed `READY.invalidated.<UTC>.json`, an event records the actor/reason/diff, and state returns to `awaiting_keyframes`;
- presenter shots must capture a speaking or reacting instant with beat-specific facial expression, gaze, asymmetric posture, and believable object weight;
- repeating the same closed-mouth smile across segments is a QC failure, even when identity and product continuity pass;
- prompts must prohibit catalogue posing, frozen symmetrical posture, and generic polite smiles.

### S8 — Sealed H3 package intake

Claude Code actions:

- run `preflight inputs/<job>/job.en.json --actor claude` before any upload or paid render, and stop unless it passes;
- validate `READY.json` and every referenced file through that gate;
- confirm 9:16 orientation, readable file, and expected segment set;
- confirm the sealed `h3_clip_plan.json` groups composition assets rather than treating one keyframe as one video;
- confirm every sealed clip binds 2–3 total Pictures and that `segments.json` exactly matches the deterministic compiler output;
- confirm every generated Picture in a clip shares the same sealed physical tabletop identity; close-up framing and background details may vary, but timing instructions do not make conflicting table surfaces compatible;
- do not hand-edit Picture order, prompt text, cut seconds or image paths after preflight. Requested changes go back to the approved shot plan, are recompiled by Codex, and are sealed again;
- for ordinary non-shot-for-shot talking-head work, English H3 dialogue remains `(S1) <d>[English] ...</d>` and requires the documented short live test. Exact-timing `shot_for_shot` H3 clips remain silent and receive the approved continuous English master voice-over after trimming;
- after fetch, require `scripts/check_shot_rhythm.py` to compare actual hard cuts with the Hypit timing master before assembly;
- create `segments.server.json` with resolved server paths.

The current renderer treats the generated image as the primary H3 reference frame. True custom-first-frame execution is not required by this design and does not justify modifying the dirty external renderer repository.

### S9 — Render and rerun segments

Rules:

- maximum 20 H3 clips per render job, each 2–15 seconds under the current server configuration;
- an H3 clip may contain several short internal hard cuts; after fetch, reject a `shot_for_shot` clip if an expected cut is missing or drifts more than 0.13 seconds, or if an unplanned hard cut is detected;
- original hard cuts do not use previous-tail continuity;
- continuous presenter scenes may use previous-tail only when reference numbering is recomputed;
- a segment failure triggers a segment rerun, not a full regeneration;
- reference changes use a single-segment rerun;
- every submission records job ID, source job ID, seed, profile, prompt hash, reference hashes, elapsed time, and reported cost.

Failure categories:

- dialogue mismatch;
- identity drift;
- wrong product;
- product deformation;
- extra hands/fingers;
- label failure;
- continuity failure;
- technical render failure.

The retry strategy is category-specific rather than generic.

### S10 — Assembly and captions

Actions:

- combine accepted segments;
- add English captions from the approved English script, corrected against output ASR timing;
- add price/CTA overlays in post-production rather than asking H3 to render text;
- encode the delivery copy;
- compute SHA-256.

Gate:

- no Chinese characters in captions, CTA, or overlay payloads;
- audio/video duration remains within tolerance;
- output meets the target resolution and size policy.

### S11 — QA and review

Automated checks:

- video/audio streams, codec, dimensions, fps, duration;
- black frames and freezes;
- English-only scan across all audience-facing JSON/SRT fields;
- output ASR versus approved English script;
- claim IDs versus product facts;
- artifact hashes and missing files.

Human checks:

- fictional presenter consistency;
- product identity and shape;
- packaging integrity;
- hand anatomy and object count;
- action completion;
- natural English delivery;
- absence of the original creator/brand;
- commercial and legal acceptability.

Machine success advances to `human_review`, never directly to `approved`.

## 9. Retry and fallback policy

| Failure | Retry unit | Primary response | Fallback |
| --- | --- | --- | --- |
| Unsupported or non-English script line | One line | Regenerate from the same beats/facts | Operator rewrites line |
| Keyframe identity drift | One image | Fresh generation from the presenter master | Regenerate presenter master after approval |
| Extra hand or wrong product count | One image | Fresh generation with a simpler first_frame (fewer objects, product upright on the counter) | Simplify composition |
| Product geometry or label drift | One segment | Switch to `pixel_preserve`: generate the scene, then composite the original packshot pixels; if extraction cannot pass QC, render with only the product image as H3 `fully_preserved` (validated on a2 seg 3) | `packshot_clip.sh` static slow push |
| Requested product angle has no source view | One segment | Simplify to an available product-reference pose | Request another product view |
| H3 dialogue mismatch | One segment | Tighten English dialogue tag and rerun | Replace audio in a later approved extension |
| H3 object deformation | One segment | Simplify action and strengthen keyframe/product refs | Static packshot segment |
| Server interruption | Current render stage | Resume from recorded source job/artifacts | Requeue after health check |
| Final QA failure | Failed segment/artifact | Route to the owning stage | Human rejection |

Each stage has a retry budget. Exceeding it changes the job to `blocked` or sends it to human review; it does not loop indefinitely.

## 10. Idempotency, cache, and provenance

Artifact cache keys include:

- normalized stage input JSON;
- input file SHA-256 values;
- model/provider/profile identifier;
- prompt version;
- seed where applicable.

`state.json` records:

```json
{
  "job_id": "a2-milk-en-001",
  "state": "awaiting_keyframes",
  "revision": 7,
  "updated_at": "2026-09-19T08:00:00Z",
  "stages": {
    "scripts": {"status": "passed", "attempt": 1, "artifact": "..."},
    "shots": {"status": "passed", "attempt": 1, "artifact": "..."},
    "keyframes": {"status": "waiting", "attempt": 0}
  }
}
```

Events append to `events.jsonl`; state changes never depend only on terminal output.

## 11. Concurrency and queue policy

- Product jobs may be planned concurrently.
- Keyframes for one presenter are generated in a controlled sequence so identity can be compared against the same master.
- The single 4090 H3 worker processes one heavy render/upscale job at a time unless measured capacity proves otherwise.
- ASR runs on the local workstation; the GPU server is reserved for H3.
- Full renders and reruns use separate queue priorities; final-blocking reruns outrank new variants.
- A lock file or atomic state transition prevents duplicate submission of the same render manifest.

## 12. Observability and production metrics

Every job report should include:

- stage durations;
- ImageGen attempts per keyframe;
- H3 attempts per segment;
- full versus partial rerender count;
- GPU elapsed time and reported cost;
- script validation failures by category;
- keyframe and video defects by category;
- automated QA result;
- human verdict and notes.

Initial target metrics, explicitly not current claims:

- zero unsupported claims reaching render;
- zero CJK characters in target-facing artifacts;
- 100% resumability after an interrupted non-destructive stage;
- at least 70% first-pass segment acceptance during the first production trial;
- fewer than two H3 attempts per accepted segment on average;
- human review under ten minutes per 20-second video after the workflow stabilizes.

## 13. Security, privacy, and compliance

- No API keys, passwords, cookies, or SSH credentials enter Git or job JSON.
- Original creator frames cannot be used as presenter references.
- Original creator audio cannot be cloned.
- Generated presenters must remain fictional.
- Exact original dialogue is restricted to comparison and similarity checking.
- Claims require product evidence.
- Personal experience statements are prohibited for fictional presenters.
- Input and output media stay ignored by Git.
- Deletion and publication are explicit operator actions, outside automatic stages.

## 14. Command surface

The eventual CLI should be small and stage-oriented:

```text
ugc-pipeline init <job.json>
ugc-pipeline validate <job>
ugc-pipeline advance <job> --until awaiting_keyframes
ugc-pipeline keyframe-status <job>
ugc-pipeline preflight <job> --actor <codex|claude>
ugc-pipeline resume <job>
ugc-pipeline rerun <job> --segment 3
ugc-pipeline qa <job>
ugc-pipeline status <job>
```

`--dry-run` must resolve inputs, validate schemas, build plans, and print intended external actions without calling ImageGen, H3, or any paid service.

ImageGen itself remains an agent stage, not a CLI/API call. `advance --until awaiting_keyframes` therefore stops intentionally and waits for Codex to produce `READY.json`.

## 15. Test strategy

Unit tests:

- English-only validator;
- beat coverage and ordering;
- word-duration budgets;
- evidence resolution;
- forbidden claims;
- variant similarity;
- path containment;
- state transitions;
- cache keys;
- `REQUEST.json`, `QC.json`, `READY.json`, integrity snapshot and preflight validation.

Integration tests without paid generation:

- run the two historical jobs through schema adapters;
- produce an English A2 dry-run through `awaiting_keyframes`;
- inject fixture keyframes and continue through an H3 submission dry-run;
- simulate missing image, bad hash, stale sealed input, recoverable READY invalidation, duplicate READY, interrupted render, and partial report;
- verify resume does not duplicate submissions.

Live acceptance test:

- one A2 English `structure` variant;
- four inspected ImageGen frames;
- four English H3 segments;
- English ASR match report;
- final technical QA;
- human approval or explicit rejection with defect labels.

Batch acceptance test:

- three English structure variants for one product;
- diversity validation passes;
- shared product and presenter assets are reused;
- a deliberately failed segment is rerun without regenerating the other segments;
- every cost and retry is traceable.

## 16. Implementation phases

### Phase A — Contracts and English gates

Status: implemented for the local planning bundle.

- add JSON schemas;
- add `job.json` and `state.json`;
- update script validation for English words and CJK rejection;
- normalize one product file into English;
- add dry-run validation.

### Phase B — Planning and resumability

Status: implemented through `awaiting_keyframes`; render-stage orchestration is still external.

- implement the state machine and event log;
- generate English scripts and shot plans;
- add hashes, cache checks, and retry bookkeeping;
- write `REQUEST.json`.

### Phase C — Codex ImageGen handoff

Status: local generation, QC, atomic READY handoff, integrity sealing and render preflight are implemented. Automatic Claude watcher pickup has not yet produced an English H3 output in this repository.

- validate the existing Claude watcher contract;
- run the first A2 segment through built-in ImageGen;
- inspect and iterate the image;
- write `READY.json` atomically;
- seal the exact render inputs and pass preflight;
- verify Claude resumes from the handoff.

### Phase D — H3 execution and targeted recovery

Status: proven only by the historical Chinese `replica` jobs; the English structure path is pending.

- compile keyframes and product references into H3 prompts;
- enforce English dialogue tags;
- record render manifests;
- implement category-specific single-segment reruns;
- assemble accepted segments.

### Phase E — QA and batching

Status: historical technical QA exists, but English output ASR, unified review and batching remain pending.

- add output ASR comparison and English captions;
- unify technical and human review reports;
- add queueing and variant-level batching;
- run live and batch acceptance tests.

Cancelled item: building an OpenAI Image API or OpenRouter keyframe integration. Built-in Codex ImageGen is the selected keyframe mechanism.

## 17. Definition of done

The pipeline is designed and implemented when all of the following are true:

- a new job can be initialized from documented inputs;
- every stage has a validated input, output, gate, retry rule, and owner;
- reference text is separated from generation input;
- new audience-facing content is English only;
- every product claim is evidence-backed;
- Codex can take a new job continuously from ingestion through `awaiting_keyframes`;
- Codex can generate and inspect frames, seal the exact render inputs, and produce a passing `PREFLIGHT.json`;
- Claude can resume without manual path reconstruction;
- a failed segment can be rerun independently;
- an interrupted job resumes without duplicate paid work;
- automated QA produces a report but cannot bypass human approval;
- one live English structure variant and one three-variant batch pass the acceptance tests.

## 18. First implementation target

Use `a2_test` as the migration case because it already has:

- front and back product images;
- a generated fictional presenter;
- beats, script, and four H3 prompts;
- a known label-closeup failure;
- successful single-segment rerun history;
- an active Codex-to-Claude sealed READY plus preflight handoff convention.

The first local milestone is complete: local jobs can reach validated, integrity-sealed READY handoffs with passing preflight reports. The next live milestone is for Claude to consume one of those handoffs, return an English H3 segment, and pass transcript plus human visual review. The first batch milestone remains one accepted three-variant English structure run.
