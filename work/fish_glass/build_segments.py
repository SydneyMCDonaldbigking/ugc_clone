"""Compile six timed multi-reference H3 clips for fish_glass_silent_en.

Keyframes are composition references, not a one-keyframe/one-video instruction.
Each H3 clip binds two or three total pictures and the prompt assigns every
composition picture an explicit time window. Only scheduled cuts are allowed.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ugc_pipeline.h3_plan import validate_h3_clip_plan  # noqa: E402


SERVER = "/opt/ugc_clone/jobs/fish_glass"
KEYFRAME_SERVER_DIR = f"{SERVER}/keyframes"
INPUT_SERVER_DIR = f"{SERVER}/inputs"


def _time(value: float) -> str:
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


job = json.loads((ROOT / "inputs/fish_glass/job.en.json").read_text(encoding="utf-8"))
request = json.loads((ROOT / job["keyframe_request"]).read_text(encoding="utf-8"))
ready = json.loads((ROOT / "work/fish_glass/keyframes/READY.json").read_text(encoding="utf-8"))
plan = json.loads((ROOT / job["h3_clip_plan"]).read_text(encoding="utf-8"))
validate_h3_clip_plan(plan, job, request, ROOT)


segments = []
for clip in plan["clips"]:
    keyframe_ids = [str(value) for value in clip["keyframe_ids"]]
    reference_paths = [
        f"{KEYFRAME_SERVER_DIR}/{ready['segments'][keyframe_id]['keyframe']}"
        for keyframe_id in keyframe_ids
    ]
    product_reference = clip.get("product_reference")
    if product_reference:
        reference_paths.append(f"{INPUT_SERVER_DIR}/{Path(product_reference).name}")

    subject_lines = []
    retention_lines = []
    for cue in clip["cues"]:
        picture = cue["picture"]
        subject_lines.append(
            f"<Picture {picture}> is the composition authority for {_time(cue['start_seconds'])}-"
            f"{_time(cue['end_seconds'])} seconds: {cue['action']}"
        )
        retention_lines.append(
            f"<Picture {picture}>: fully_preserved only during its assigned time window; preserve its "
            "camera angle, framing, glass proportions, fish pattern, hands, props and light."
        )
    if product_reference:
        product_picture = len(reference_paths)
        subject_lines.append(
            f"<Picture {product_picture}> is the product identity authority for the target glass throughout the clip."
        )
        retention_lines.append(
            f"<Picture {product_picture}>: attribute_transfer throughout; preserve the double-wall silhouette, "
            "open rim, thick clear base and repeated frosted fish motifs, but ignore its original background."
        )

    timeline_lines = []
    for cue in clip["cues"]:
        picture = cue["picture"]
        transition = cue["transition"]
        transition_text = "start on" if transition == "start" else (
            "use the foreground glass wipe to cut to" if transition == "foreground_wipe_cut" else "hard cut to"
        )
        timeline_lines.append(
            f"{_time(cue['start_seconds'])}-{_time(cue['end_seconds'])} seconds - {transition_text} "
            f"<Picture {picture}>; {cue['action']}"
        )
    trim_duration = float(clip["trim_duration_seconds"])
    render_duration = float(clip["duration_seconds"])
    if render_duration - trim_duration > 0.001:
        timeline_lines.append(
            f"{_time(trim_duration)}-{_time(render_duration)} seconds - hold the final composition steady as "
            "disposable trim padding; introduce no new action or cut."
        )

    cut_count = max(0, len(clip["cues"]) - 1)
    cut_verb = "happens" if cut_count == 1 else "happen"
    prompt = f"""subject_definitions:
{chr(10).join(subject_lines)}

retention_analysis:
{chr(10).join(retention_lines)}

detailed_description:
Generate one vertical {int(render_duration) if render_duration.is_integer() else render_duration}-second video. Follow this Picture timeline literally. The {cut_count} scheduled internal cut{'s' if cut_count != 1 else ''} {cut_verb} only at the named times; every cut is a clean edit into the next Picture composition, never a morph or an invented camera move.

timed_picture_timeline:
{chr(10).join(timeline_lines)}

soundscape: quiet room tone with the natural sounds of ice, liquid, glass and handling only. No speech, singing, voice-over or music.

Only the scheduled hands and short forearms appear; no face, head or torso. No subtitles, captions, watermarks, price labels or extra brands. Preserve the target glass shape and fish pattern across every scheduled cut. Use exactly the listed cuts and no others. Do not morph one Picture into another.""".strip()

    segments.append({
        "id": clip["id"],
        "prompt": prompt,
        "duration_seconds": clip["duration_seconds"],
        "trim_to_seconds": clip["trim_duration_seconds"],
        "references": reference_paths,
    })

output = Path(__file__).parent / "segments.json"
output.write_text(json.dumps(segments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(
    json.dumps(
        {
            "output": output.as_posix(),
            "h3_clips": len(segments),
            "approved_keyframes": sum(len(clip["keyframe_ids"]) for clip in plan["clips"]),
            "total_edit_duration_seconds": plan["total_edit_duration_seconds"],
        },
        indent=2,
    )
)
