from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .io import load_json, resolve_repo_path, sha256_file


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
VISUAL_MODES = {"structure_remix", "shot_for_shot"}


@dataclass(frozen=True)
class Issue:
    level: str
    code: str
    path: str
    message: str


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "warning"]

    def error(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue("error", code, path, message))

    def warning(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue("warning", code, path, message))

    def extend(self, other: "ValidationResult") -> None:
        self.issues.extend(other.issues)


def contains_cjk(value: str) -> bool:
    return bool(CJK_RE.search(value))


def count_words(value: str) -> int:
    return len(WORD_RE.findall(value))


def normalized_words(value: str) -> list[str]:
    return [word.lower().replace("’", "'") for word in WORD_RE.findall(value)]


def word_ngrams(value: str, size: int) -> set[tuple[str, ...]]:
    words = normalized_words(value)
    return {tuple(words[index:index + size]) for index in range(max(0, len(words) - size + 1))}


def _require_object(value: Any, result: ValidationResult, path: str) -> bool:
    if not isinstance(value, dict):
        result.error("type.object", path, "Expected an object.")
        return False
    return True


def _require_string(document: dict[str, Any], key: str, result: ValidationResult, path: str) -> str | None:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        result.error("required.string", f"{path}.{key}", "Expected a non-empty string.")
        return None
    return value


def _reject_cjk(value: Any, result: ValidationResult, path: str) -> None:
    if isinstance(value, str):
        if contains_cjk(value):
            result.error("language.cjk", path, "English target artifact contains CJK characters.")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_cjk(child, result, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, child in value.items():
            _reject_cjk(child, result, f"{path}.{key}")


def validate_job(job: Any, repo_root: Path) -> ValidationResult:
    result = ValidationResult()
    if not _require_object(job, result, "job"):
        return result

    schema = _require_string(job, "schema", result, "job")
    if schema and schema != "ugc-job/v1":
        result.error("schema.unsupported", "job.schema", f"Unsupported schema: {schema}")

    _require_string(job, "job_id", result, "job")
    target_language = _require_string(job, "target_language", result, "job")
    if target_language and not target_language.lower().startswith("en"):
        result.error("language.target", "job.target_language", "Target language must be English.")

    mode = _require_string(job, "mode", result, "job")
    if mode and mode != "structure":
        result.error("mode.production", "job.mode", "Production jobs must use structure mode.")

    visual_mode = job.get("visual_mode", "structure_remix")
    if visual_mode not in VISUAL_MODES:
        result.error(
            "visual_mode.invalid",
            "job.visual_mode",
            f"Expected one of {sorted(VISUAL_MODES)}.",
        )
    if visual_mode == "shot_for_shot" and not isinstance(job.get("shot_map"), str):
        result.error(
            "shot_map.required",
            "job.shot_map",
            "shot_for_shot jobs require a repository-relative shot_map path.",
        )

    audio_mode = job.get("audio_mode", "dialogue")
    if audio_mode not in {"dialogue", "silent"}:
        result.error("audio_mode.invalid", "job.audio_mode", "Expected dialogue or silent.")

    variants = job.get("variants")
    if not isinstance(variants, int) or variants < 1:
        result.error("variants.range", "job.variants", "Variants must be a positive integer.")

    segment_duration = job.get("segment_duration_seconds")
    if not isinstance(segment_duration, (int, float)) or not 1 <= segment_duration <= 15:
        result.error("duration.range", "job.segment_duration_seconds", "Segment duration must be 1-15 seconds.")

    max_segments = job.get("max_segments_per_render")
    if not isinstance(max_segments, int) or not 1 <= max_segments <= 20:
        result.error("segments.limit", "job.max_segments_per_render", "A render may contain at most twenty H3 clips.")

    if job.get("image_provider") != "codex-imagegen":
        result.error("provider.image", "job.image_provider", "Default keyframe provider must be codex-imagegen.")

    artifact_keys = ["reference_video", "product", "beats", "script", "shot_plan", "keyframe_request"]
    if isinstance(job.get("h3_clip_plan"), str):
        artifact_keys.append("h3_clip_plan")
    if isinstance(job.get("h3_segments"), str):
        artifact_keys.append("h3_segments")
    if visual_mode == "shot_for_shot":
        artifact_keys.append("shot_map")
    for key in artifact_keys:
        raw_path = job.get(key)
        if not isinstance(raw_path, str) or not raw_path:
            result.error("path.required", f"job.{key}", "Expected a repository-relative path.")
            continue
        try:
            resolve_repo_path(repo_root, raw_path)
        except (ValueError, FileNotFoundError) as exc:
            result.error("path.invalid", f"job.{key}", str(exc))

    # Adaptation starts from an understood reference: its archive must be written up, not half-scaffolded.
    archive = job.get("reference_archive")
    if not isinstance(archive, str) or not archive:
        result.error("reference.archive", "job.reference_archive", "Link the reference archive (references/<ref_id>).")
    else:
        root = (repo_root / archive)
        for name in ("ANALYSIS.md", "TIMELINE.md"):
            doc = root / name
            if not doc.is_file():
                result.error("reference.archive_incomplete", "job.reference_archive", f"{archive}/{name} is missing.")
            elif "<!-- TODO" in doc.read_text(encoding="utf-8"):
                result.error("reference.archive_incomplete", "job.reference_archive",
                             f"{archive}/{name} still has TODO sections; finish the archive first.")
        if (root / "PROGRESS.md").exists():
            result.error("reference.archive_incomplete", "job.reference_archive",
                         f"{archive}/PROGRESS.md still lists open questions.")

    for key in ("state_file", "events_file"):
        raw_path = job.get(key)
        if not isinstance(raw_path, str) or not raw_path:
            result.error("path.required", f"job.{key}", "Expected a repository-relative output path.")
            continue
        try:
            resolve_repo_path(repo_root, raw_path, must_exist=False)
        except ValueError as exc:
            result.error("path.invalid", f"job.{key}", str(exc))

    return result


def validate_product(product: Any) -> ValidationResult:
    result = ValidationResult()
    if not _require_object(product, result, "product"):
        return result
    if product.get("schema") != "product/v1":
        result.error("schema.unsupported", "product.schema", "Expected product/v1.")
    language = _require_string(product, "language", result, "product")
    if language and not language.lower().startswith("en"):
        result.error("language.target", "product.language", "Product facts must be normalized into English.")

    visual_identity = product.get("visual_identity")
    if not isinstance(visual_identity, dict):
        result.error("visual_identity.required", "product.visual_identity", "A product visual identity contract is required.")
    else:
        for key in (
            "packaging_type",
            "silhouette",
            "closure",
            "grip_geometry",
            "handle",
            "front_label",
            "back_label",
        ):
            _require_string(visual_identity, key, result, "product.visual_identity")
        handle = visual_identity.get("handle")
        forbidden_features = visual_identity.get("forbidden_features")
        forbidden_text = " ".join(str(value).lower() for value in forbidden_features or [])
        if isinstance(handle, str) and handle.lower() != "none" and "handle" in forbidden_text:
            result.error(
                "visual_identity.handle",
                "product.visual_identity.handle",
                "The declared handle conflicts with forbidden visual features; describe the real product consistently.",
            )
        if not isinstance(forbidden_features, list) or not forbidden_features:
            result.error(
                "visual_identity.forbidden",
                "product.visual_identity.forbidden_features",
                "At least one forbidden visual feature is required.",
            )

    facts = product.get("facts")
    if not isinstance(facts, list) or not facts:
        result.error("facts.required", "product.facts", "At least one evidence-backed fact is required.")
    else:
        seen: set[str] = set()
        for index, fact in enumerate(facts):
            path = f"product.facts[{index}]"
            if not isinstance(fact, dict):
                result.error("type.object", path, "Expected a fact object.")
                continue
            fact_id = _require_string(fact, "id", result, path)
            _require_string(fact, "text", result, path)
            _require_string(fact, "evidence", result, path)
            _require_string(fact, "evidence_type", result, path)
            if fact_id:
                if fact_id in seen:
                    result.error("facts.duplicate", f"{path}.id", f"Duplicate fact ID: {fact_id}")
                seen.add(fact_id)

    _reject_cjk(product, result, "product")
    return result


def validate_beats(beats: Any) -> ValidationResult:
    result = ValidationResult()
    if not _require_object(beats, result, "beats"):
        return result
    if beats.get("schema") not in {"beats/v0.1", "beats/v1"}:
        result.error("schema.unsupported", "beats.schema", "Expected beats/v0.1 or beats/v1.")
    items = beats.get("beats")
    if not isinstance(items, list) or not items:
        result.error("beats.required", "beats.beats", "At least one beat is required.")
        return result
    previous_end: float | None = None
    seen: set[str] = set()
    for index, beat in enumerate(items):
        path = f"beats.beats[{index}]"
        if not isinstance(beat, dict):
            result.error("type.object", path, "Expected a beat object.")
            continue
        beat_id = _require_string(beat, "id", result, path)
        _require_string(beat, "function", result, path)
        start = beat.get("t_start")
        end = beat.get("t_end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start >= end:
            result.error("beats.time", path, "Beat must have numeric t_start < t_end.")
        elif previous_end is not None and abs(float(start) - previous_end) > 0.03:
            result.error("beats.coverage", path, f"Beat starts at {start}, previous beat ended at {previous_end}.")
        if isinstance(end, (int, float)):
            previous_end = float(end)
        if beat_id:
            if beat_id in seen:
                result.error("beats.duplicate", f"{path}.id", f"Duplicate beat ID: {beat_id}")
            seen.add(beat_id)
    return result


def validate_source_alignment(job: dict[str, Any], beats: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()
    reference_video = job.get("reference_video")
    source = beats.get("source")
    beats_video = source.get("file") if isinstance(source, dict) else None
    if isinstance(reference_video, str) and isinstance(beats_video, str):
        if Path(reference_video).as_posix() != Path(beats_video).as_posix():
            result.error(
                "source.mismatch",
                "beats.source.file",
                f"Beat analysis source {beats_video!r} does not match job reference_video {reference_video!r}.",
            )
    else:
        result.error("source.required", "beats.source.file", "Beat analysis must identify its source video.")
    return result


def validate_script(script: Any, beats: dict[str, Any], product: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()
    if not _require_object(script, result, "script"):
        return result
    if script.get("schema") != "script/v1":
        result.error("schema.unsupported", "script.schema", "Expected script/v1.")
    if not str(script.get("language", "")).lower().startswith("en"):
        result.error("language.target", "script.language", "Script language must be English.")
    if script.get("mode") != "structure":
        result.error("mode.production", "script.mode", "Production scripts must use structure mode.")
    audio_mode = script.get("audio_mode", "dialogue")
    if audio_mode not in {"dialogue", "silent"}:
        result.error("audio_mode.invalid", "script.audio_mode", "Expected dialogue or silent.")

    lines = script.get("lines")
    if not isinstance(lines, list) or not lines:
        result.error("script.lines", "script.lines", "At least one script line is required.")
        return result

    fact_map = {fact.get("id"): fact for fact in product.get("facts", []) if isinstance(fact, dict)}
    beat_ids = [beat.get("id") for beat in beats.get("beats", []) if isinstance(beat, dict)]
    covered: list[str] = []
    all_text: list[str] = []
    forbidden = [str(value).lower() for value in product.get("forbidden_claims", []) if str(value).strip()]

    for index, line in enumerate(lines):
        path = f"script.lines[{index}]"
        if not isinstance(line, dict):
            result.error("type.object", path, "Expected a line object.")
            continue
        raw_text = line.get("text")
        if not isinstance(raw_text, str):
            result.error("required.string", f"{path}.text", "Expected a string.")
            text = ""
        else:
            text = raw_text
        if audio_mode == "dialogue" and not text.strip():
            result.error("required.string", f"{path}.text", "Dialogue mode requires non-empty spoken text.")
        if audio_mode == "silent":
            if text:
                result.error("script.silent_text", f"{path}.text", "Silent mode requires an empty dialogue string.")
            _require_string(line, "visual_direction", result, path)
        line_beats = line.get("beats")
        if not isinstance(line_beats, list) or not all(isinstance(value, str) for value in line_beats):
            result.error("script.beats", f"{path}.beats", "Expected a list of beat IDs.")
            line_beats = []
        covered.extend(line_beats)
        claims = line.get("claims", [])
        if not isinstance(claims, list) or not all(isinstance(value, str) for value in claims):
            result.error("script.claims", f"{path}.claims", "Expected a list of fact IDs.")
            claims = []
        for claim in claims:
            fact = fact_map.get(claim)
            if not fact:
                result.error("claims.unknown", f"{path}.claims", f"Unknown fact ID: {claim}")
            elif not str(fact.get("evidence", "")).strip():
                result.error("claims.evidence", f"{path}.claims", f"Fact {claim} has no evidence.")

        duration = line.get("target_duration_seconds", 5)
        if not isinstance(duration, (int, float)) or duration <= 0:
            result.error("duration.invalid", f"{path}.target_duration_seconds", "Expected a positive duration.")
        elif audio_mode == "dialogue":
            words = count_words(text)
            hard_min = max(1, math.floor(float(duration) * 1.5))
            hard_max = math.ceil(float(duration) * 3.4)
            preferred_min = math.floor(float(duration) * 2.3)
            preferred_max = math.ceil(float(duration) * 3.0)
            if not hard_min <= words <= hard_max:
                result.error(
                    "script.word_budget",
                    f"{path}.text",
                    f"{words} words is outside the hard {hard_min}-{hard_max} range for {duration}s.",
                )
            elif not preferred_min <= words <= preferred_max:
                result.warning(
                    "script.word_pace",
                    f"{path}.text",
                    f"{words} words is outside the preferred {preferred_min}-{preferred_max} range for {duration}s.",
                )

        lowered = text.lower()
        for phrase in forbidden:
            if phrase and phrase in lowered:
                result.error("claims.forbidden", f"{path}.text", f"Forbidden claim: {phrase}")
        if re.search(r"\d", text) and not claims:
            result.error("claims.number", f"{path}.text", "Numeric claims require at least one fact reference.")
        if text:
            all_text.append(text)

    dropped = script.get("dropped_beats", {})
    dropped_ids = list(dropped) if isinstance(dropped, dict) else []
    expected = [beat_id for beat_id in beat_ids if beat_id not in dropped_ids]
    if covered != expected:
        result.error("script.coverage", "script.lines", f"Beat coverage {covered} does not equal {expected}.")

    for left in range(len(all_text)):
        for right in range(left + 1, len(all_text)):
            left_grams = word_ngrams(all_text[left], 3)
            right_grams = word_ngrams(all_text[right], 3)
            overlap = len(left_grams & right_grams) / max(1, min(len(left_grams), len(right_grams)))
            if overlap >= 0.60:
                result.warning(
                    "script.internal_overlap",
                    f"script.lines[{right}].text",
                    f"High word 3-gram overlap ({overlap:.0%}) with line {left + 1}.",
                )

    _reject_cjk(script, result, "script")
    return result


# Frames, grids and anchors cut from the reference video carry the source creator's face, product,
# watermark and captions. An image model absorbs all of it regardless of the declared role, so no
# source-derived image may ever be a keyframe reference (red line: never reference the source video).
SOURCE_DERIVED_MARKERS = ("video_analysis/", "/frames/", "anchor_", "storyboard", "contact.jpg", "tile_", "cuts_")
FORBIDDEN_REFERENCE_ROLES = {"composition_only"}
H3_MIN_SEGMENT_SECONDS = 2
# presenter.mode -> the only keyframe template allowed for it
PRESENTER_TEMPLATES = {
    "generated_fictional": "templates/keyframe_prompt.en.txt",   # someone talks to camera in the source
    "hands_only": "templates/keyframe_prompt.hands-only.en.txt",   # only hands and product in the source
    "none": "templates/keyframe_prompt.product-only.en.txt",       # product only, voice-over
}
# A generated keyframe already carries the image model's version of the product. Feeding it back as a
# reference compounds that drift, so every keyframe is generated fresh from the original photos.
GENERATED_MARKERS = ("/keyframes/",)
SCENE_LOCK_FIELDS = (
    "setting",
    "surface",
    "backdrop",
    "lighting",
    "palette",
    "fixed_props",
)
SCENE_HARD_LOCK_FIELDS = ("surface",)
SCENE_SOFT_GUIDE_FIELDS = ("setting", "backdrop", "lighting", "palette", "fixed_props")


def _valid_scene_lock(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(value.get(field), str) and value[field].strip()
        for field in SCENE_LOCK_FIELDS
    )


def _check_reference_origin(references: Any, roles: Any, result: ValidationResult, path: str) -> None:
    for index, raw_path in enumerate(references if isinstance(references, list) else []):
        normalized = str(raw_path).replace("\\", "/")
        if any(marker in normalized for marker in SOURCE_DERIVED_MARKERS):
            result.error(
                "reference.source_frame",
                f"{path}.references[{index}]",
                f"{raw_path} is derived from the reference video; describe the composition in text instead.",
            )
        if any(marker in "/" + normalized for marker in GENERATED_MARKERS):
            result.error(
                "reference.generated",
                f"{path}.references[{index}]",
                f"{raw_path} is a generated image; use the original presenter and product photos instead.",
            )
    for raw_path, role in (roles.items() if isinstance(roles, dict) else []):
        if role in FORBIDDEN_REFERENCE_ROLES:
            result.error(
                "reference.role_forbidden",
                f"{path}.reference_roles",
                f"Role {role!r} ({raw_path}) is not allowed; composition comes from the shot plan text.",
            )


def validate_shot_plan(plan: Any, script: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()
    if not _require_object(plan, result, "shot_plan"):
        return result
    if plan.get("schema") != "shot-plan/v1":
        result.error("schema.unsupported", "shot_plan.schema", "Expected shot-plan/v1.")
    if not str(plan.get("language", "")).lower().startswith("en"):
        result.error("language.target", "shot_plan.language", "Shot plan language must be English.")
    audio_mode = script.get("audio_mode", "dialogue")
    plan_audio_mode = plan.get("audio_mode", "dialogue")
    if plan_audio_mode != audio_mode:
        result.error("audio_mode.mismatch", "shot_plan.audio_mode", "Shot plan audio_mode must match the approved script.")
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        result.error("shots.required", "shot_plan.segments", "At least one segment is required.")
        return result

    script_by_segment = {
        line.get("segment"): line for line in script.get("lines", []) if isinstance(line, dict)
    }
    seen: set[int] = set()
    for index, segment in enumerate(segments):
        path = f"shot_plan.segments[{index}]"
        if not isinstance(segment, dict):
            result.error("type.object", path, "Expected a segment object.")
            continue
        number = segment.get("segment")
        if not isinstance(number, int) or number < 1:
            result.error("shots.segment", f"{path}.segment", "Expected a positive segment number.")
            continue
        if number in seen:
            result.error("shots.duplicate", f"{path}.segment", f"Duplicate segment: {number}")
        seen.add(number)
        line = script_by_segment.get(number)
        if not line:
            result.error("shots.script", path, f"No script line for segment {number}.")
        elif segment.get("dialogue") != line.get("text"):
            result.error("shots.dialogue", f"{path}.dialogue", "Dialogue must exactly match the approved script.")
        _require_string(segment, "performance", result, path)
        # Direction for H3 (hypit video-direction): one attitude sentence for the passage, plus a few
        # reactions pinned to words that actually occur in this segment's dialogue.
        _require_string(segment, "intention", result, path)
        accents = segment.get("accents", [])
        dialogue_lower = str(segment.get("dialogue", "")).lower()
        if not isinstance(accents, list):
            result.error("shots.accents", f"{path}.accents", "Accents must be a list.")
        else:
            if len(accents) > 3:
                result.warning("shots.accents_many", f"{path}.accents", "More than three accents turns direction into choreography.")
            if audio_mode == "silent" and accents:
                result.error("shots.silent_accents", f"{path}.accents", "Silent mode cannot anchor reactions to dialogue.")
            for accent_index, accent in enumerate(accents):
                accent_path = f"{path}.accents[{accent_index}]"
                if not isinstance(accent, dict) or not str(accent.get("at", "")).strip() or not str(accent.get("reaction", "")).strip():
                    result.error("shots.accent", accent_path, "Each accent needs 'at' (a dialogue phrase) and 'reaction'.")
                elif str(accent["at"]).lower() not in dialogue_lower:
                    result.error("shots.accent_anchor", f"{accent_path}.at", f"'{accent['at']}' does not occur in this segment's dialogue.")
        keyframe_ids = segment.get("keyframe_ids")
        if (
            not isinstance(keyframe_ids, list)
            or not keyframe_ids
            or not all(isinstance(value, str) and value.strip() for value in keyframe_ids)
            or len(set(keyframe_ids)) != len(keyframe_ids)
        ):
            result.error(
                "shots.keyframe_ids",
                f"{path}.keyframe_ids",
                "Expected one or more unique keyframe IDs.",
            )
        if segment.get("keyframe_strategy") != "codex-imagegen-edit":
            result.error("shots.keyframe", f"{path}.keyframe_strategy", "Expected codex-imagegen-edit.")
        references = segment.get("references")
        if not isinstance(references, list) or not references:
            result.error("shots.references", f"{path}.references", "At least one image reference is required.")
        _check_reference_origin(references, None, result, path)
        subshots = segment.get("subshots")
        reference_frames = segment.get("reference_frames")
        if reference_frames is not None and (
            not isinstance(reference_frames, list)
            or not reference_frames
            or not all(isinstance(frame, dict) for frame in reference_frames)
        ):
            result.error(
                "shots.reference_frames",
                f"{path}.reference_frames",
                "reference_frames must be a non-empty list of keyframe descriptions.",
            )
            reference_frames = []
        frame_owners = reference_frames or subshots or [segment]
        for owner in frame_owners:
            camera = str(owner.get("camera") or segment.get("camera") or "") if isinstance(owner, dict) else ""
            if camera.count("|") + camera.count("｜") < 3:
                result.error(
                    "shots.camera",
                    f"{path}.camera",
                    "Every keyframe needs camera 'shot size | height and angle | movement | framing', copied from the source TIMELINE.",
                )
            if not isinstance(owner, dict) or not str(owner.get("first_frame", "")).strip():
                result.error(
                    "shots.first_frame",
                    f"{path}.first_frame",
                    "Every keyframe needs a first_frame: the still moment the image shows, product facing the camera as in its reference photo.",
                )
        if reference_frames:
            frame_ids = [str(frame.get("keyframe_id", "")) for frame in reference_frames]
            if isinstance(keyframe_ids, list) and frame_ids != [str(value) for value in keyframe_ids]:
                result.error(
                    "shots.reference_frame_keyframes",
                    f"{path}.reference_frames",
                    "reference_frames must list the segment keyframe_ids in order.",
                )
        if subshots:
            # A subshot is a timed Picture cue inside a grouped multi-reference H3 clip.
            # Its edit window may be shorter than H3's minimum standalone clip duration.
            durations = [sub.get("duration_seconds") for sub in subshots if isinstance(sub, dict)]
            if len(durations) != len(subshots) or not all(isinstance(value, (int, float)) for value in durations):
                result.error("shots.subshots", f"{path}.subshots", "Every subshot needs a numeric duration_seconds.")
            else:
                if any(value <= 0 for value in durations):
                    result.error(
                        "shots.subshot_duration",
                        f"{path}.subshots",
                        "Timed Picture windows must have positive duration.",
                    )
                if abs(sum(durations) - float(segment.get("duration_seconds", 0))) > 0.01:
                    result.error(
                        "shots.subshot_total",
                        f"{path}.subshots",
                        "Subshot durations must add up to the segment duration.",
                    )
            sub_ids = [str(sub.get("keyframe_id")) for sub in subshots if isinstance(sub, dict)]
            if isinstance(keyframe_ids, list) and sub_ids != [str(value) for value in keyframe_ids]:
                result.error(
                    "shots.subshot_keyframes",
                    f"{path}.subshots",
                    "Subshot keyframe_ids must list the segment keyframe_ids in order.",
                )
        if segment.get("continuity") not in {"hard_cut", "previous_tail"}:
            result.error("shots.continuity", f"{path}.continuity", "Expected hard_cut or previous_tail.")

    if set(script_by_segment) != seen:
        result.error("shots.coverage", "shot_plan.segments", "Shot plan must cover every script segment exactly once.")
    _reject_cjk(plan, result, "shot_plan")
    return result


def validate_keyframe_request(
    request: Any,
    repo_root: Path,
    product: dict[str, Any] | None = None,
) -> ValidationResult:
    result = ValidationResult()
    if not _require_object(request, result, "request"):
        return result
    if request.get("schema") != "keyframe-request/v1":
        result.error("schema.unsupported", "request.schema", "Expected keyframe-request/v1.")
    if request.get("output_aspect_ratio") != "9:16":
        result.error("request.aspect", "request.output_aspect_ratio", "Keyframes must be 9:16.")
    prompt_template = request.get("prompt_template")
    if not isinstance(prompt_template, str) or not prompt_template:
        result.error("request.template", "request.prompt_template", "A reusable prompt template is required.")
    else:
        try:
            resolve_repo_path(repo_root, prompt_template)
        except (ValueError, FileNotFoundError) as exc:
            result.error("path.invalid", "request.prompt_template", str(exc))
    segments = request.get("segments")
    if not isinstance(segments, dict) or not segments:
        result.error("request.segments", "request.segments", "At least one requested segment is required.")
        return result
    scene_master_policy = request.get("background_lock_policy") == "scene_pack_v1"
    scene_pack_requirements = request.get("scene_pack_requirements")
    if scene_master_policy and (not isinstance(scene_pack_requirements, dict) or not scene_pack_requirements):
        result.error(
            "request.scene_pack_requirements",
            "request.scene_pack_requirements",
            "scene_pack_v1 requires one three-view generation request per scene_id.",
        )
    scene_locks: dict[str, dict[str, Any]] = {}
    for segment_id, segment in segments.items():
        path = f"request.segments.{segment_id}"
        if not isinstance(segment, dict):
            result.error("type.object", path, "Expected a request object.")
            continue
        product_presence = segment.get("product_presence", "present")
        if product_presence not in {"present", "absent"}:
            result.error("request.product_presence", f"{path}.product_presence", "Expected present or absent.")
        references = segment.get("references")
        if not isinstance(references, list):
            result.error("request.references", f"{path}.references", "References must be a list.")
        else:
            for index, raw_path in enumerate(references):
                try:
                    resolve_repo_path(repo_root, str(raw_path))
                except (ValueError, FileNotFoundError) as exc:
                    result.error("path.invalid", f"{path}.references[{index}]", str(exc))
        reference_roles = segment.get("reference_roles")
        _check_reference_origin(references, reference_roles, result, path)
        if not isinstance(reference_roles, dict):
            result.error("request.reference_roles", f"{path}.reference_roles", "Reference roles are required.")
        elif isinstance(references, list):
            if set(reference_roles) != set(str(value) for value in references):
                result.error(
                    "request.reference_roles",
                    f"{path}.reference_roles",
                    "Reference-role paths must exactly match the references list.",
                )
            product_refs = [raw_path for raw_path, role in reference_roles.items() if role == "product_identity"]
            expected_product_refs = 1 if product_presence == "present" else 0
            if len(product_refs) != expected_product_refs:
                result.error(
                    "request.product_reference",
                    f"{path}.reference_roles",
                    f"product_presence={product_presence} requires exactly {expected_product_refs} product_identity reference(s).",
                )
            elif product_refs and product is not None and product_refs[0] not in product.get("visual_assets", []):
                result.error(
                    "request.product_reference",
                    f"{path}.reference_roles",
                    "The product_identity reference must come from product.visual_assets.",
                )
            if scene_master_policy:
                scene_refs = [raw_path for raw_path, role in reference_roles.items() if role == "scene_identity"]
                if len(scene_refs) > 1:
                    result.error(
                        "request.scene_master",
                        f"{path}.reference_roles",
                        "scene_pack_v1 allows only one camera-matched scene_identity view per keyframe.",
                    )
                elif not scene_refs:
                    result.warning(
                        "request.scene_pack_pending",
                        f"{path}.reference_roles",
                        "Scene pack is planned but not registered yet; keyframe QC and READY remain blocked.",
                    )
                if len(references) > 3:
                    result.error(
                        "request.reference_limit",
                        f"{path}.references",
                        "A keyframe may bind at most presenter master + scene master + product original.",
                    )
        if scene_master_policy:
            scene_id = segment.get("scene_id")
            scene_lock = segment.get("scene_lock")
            if not isinstance(scene_id, str) or not scene_id.strip():
                result.error("request.scene_id", f"{path}.scene_id", "scene_pack_v1 requires scene_id.")
            if segment.get("scene_view") not in {"eye_level", "oblique_45", "overhead_90"}:
                result.error(
                    "request.scene_view",
                    f"{path}.scene_view",
                    "scene_pack_v1 requires eye_level, oblique_45 or overhead_90.",
                )
            elif not _valid_scene_lock(scene_lock):
                result.error(
                    "request.scene_lock",
                    f"{path}.scene_lock",
                    f"scene_lock requires non-empty fields {list(SCENE_LOCK_FIELDS)}.",
                )
            elif scene_id in scene_locks and scene_locks[scene_id] != scene_lock:
                result.error(
                    "request.scene_lock_mismatch",
                    f"{path}.scene_lock",
                    "Every keyframe sharing a scene_id must use the identical structured scene_lock.",
                )
            else:
                scene_locks[scene_id] = scene_lock
            requirement = scene_pack_requirements.get(scene_id) if isinstance(scene_pack_requirements, dict) else None
            views = requirement.get("views") if isinstance(requirement, dict) else None
            if (
                not isinstance(requirement, dict)
                or requirement.get("scene_lock") != scene_lock
                or requirement.get("base_view") != "eye_level"
                or not isinstance(views, dict)
                or set(views) != {"eye_level", "oblique_45", "overhead_90"}
                or any(
                    not isinstance(view_request, dict)
                    or not isinstance(view_request.get("prompt_file"), str)
                    or not isinstance(view_request.get("output"), str)
                    for view_request in (views.values() if isinstance(views, dict) else [])
                )
            ):
                result.error(
                    "request.scene_pack_requirements",
                    f"request.scene_pack_requirements.{scene_id}",
                    "Scene-pack requirement must carry the same lock and all three canonical views.",
                )
        fidelity_mode = segment.get("product_fidelity_mode")
        allowed_fidelity = {"reference_lock", "pixel_preserve"} if product_presence == "present" else {"not_applicable"}
        if fidelity_mode not in allowed_fidelity:
            result.error(
                "request.fidelity_mode",
                f"{path}.product_fidelity_mode",
                f"product_presence={product_presence} requires one of {sorted(allowed_fidelity)}.",
            )
        placement = segment.get("product_placement")
        if product_presence == "present" and (
            not isinstance(placement, dict) or placement.get("orientation") != "unchanged_from_reference"
        ):
            result.error(
                "request.product_orientation",
                f"{path}.product_placement.orientation",
                "The product must face the camera as in its reference photo (unchanged_from_reference); held or set down follows the source shot.",
            )
        if product_presence == "absent" and placement is not None:
            result.error(
                "request.product_placement",
                f"{path}.product_placement",
                "Product-absent keyframes must not reserve or composite a product placement.",
            )
        if fidelity_mode == "pixel_preserve":
            placement = segment.get("product_placement")
            if not isinstance(placement, dict) or placement.get("pose_source") != "product_identity_reference":
                result.error(
                    "request.product_placement",
                    f"{path}.product_placement",
                    "pixel_preserve requires pose_source=product_identity_reference.",
                )
        prompt_file = segment.get("prompt_file")
        if not isinstance(prompt_file, str) or not prompt_file:
            result.error("request.prompt", f"{path}.prompt_file", "Expected a repository-relative prompt file.")
        else:
            try:
                resolve_repo_path(repo_root, prompt_file)
            except (ValueError, FileNotFoundError) as exc:
                result.error("path.invalid", f"{path}.prompt_file", str(exc))
        output = segment.get("output")
        if not isinstance(output, str) or Path(output).name != output or not output.lower().endswith(".png"):
            result.error("request.output", f"{path}.output", "Output must be a local segNN.png filename.")
    _reject_cjk(request, result, "request")
    return result


def validate_keyframe_coverage(
    request: dict[str, Any],
    shot_plan: dict[str, Any],
    job: dict[str, Any],
    repo_root: Path | None = None,
) -> ValidationResult:
    result = ValidationResult()
    expected: set[str] = set()
    for segment in shot_plan.get("segments", []):
        if not isinstance(segment, dict) or segment.get("keyframe_strategy") != "codex-imagegen-edit":
            continue
        keyframe_ids = segment.get("keyframe_ids")
        if isinstance(keyframe_ids, list) and keyframe_ids:
            expected.update(str(value) for value in keyframe_ids)
        else:
            expected.add(str(segment.get("segment")))
    request_segments = request.get("segments")
    actual = set(request_segments) if isinstance(request_segments, dict) else set()
    if actual != expected:
        result.error(
            "request.coverage",
            "request.segments",
            f"Requested keyframes {sorted(actual)} do not exactly cover shot-plan segments {sorted(expected)}.",
        )

    # How people appear is decided from the reference archive, never assumed: a talking-head source gets
    # a fictional presenter, a hands-only source gets hands only, a product-only source gets nobody.
    presenter = job.get("presenter") if isinstance(job.get("presenter"), dict) else {}
    mode = presenter.get("mode")
    if mode not in PRESENTER_TEMPLATES:
        result.error(
            "presenter.mode",
            "job.presenter.mode",
            f"Set presenter.mode from the reference archive: one of {sorted(PRESENTER_TEMPLATES)}.",
        )
    else:
        if request.get("prompt_template") != PRESENTER_TEMPLATES[mode]:
            result.error(
                "request.template_mode",
                "request.prompt_template",
                f"presenter.mode={mode} requires {PRESENTER_TEMPLATES[mode]}.",
            )
        if mode != "generated_fictional":
            for segment_id, segment in (request_segments.items() if isinstance(request_segments, dict) else []):
                roles = segment.get("reference_roles") if isinstance(segment, dict) else None
                if any(role not in {"product_identity", "scene_identity"} for role in (roles.values() if isinstance(roles, dict) else [])):
                    result.error(
                        "request.presenter_forbidden",
                        f"request.segments.{segment_id}.reference_roles",
                        f"presenter.mode={mode}: the source has no on-camera presenter, so only product and registered scene-pack references are allowed.",
                    )
            if presenter.get("master_image"):
                result.error("presenter.master_forbidden", "job.presenter.master_image",
                             f"presenter.mode={mode} has no presenter master.")

    # Person and scene continuity come from one registered presenter master (no product in it). Every
    # keyframe's presenter reference must be exactly that file; registration pins its hash so keyframes
    # made from an older master are caught.
    master = presenter.get("master_image")
    presenter_roles = {"presenter_identity", "presenter_and_scene_identity"}
    if isinstance(request_segments, dict):
        for segment_id, segment in request_segments.items():
            roles = segment.get("reference_roles") if isinstance(segment, dict) else None
            for raw_path, role in (roles.items() if isinstance(roles, dict) else []):
                if role in presenter_roles and raw_path != master:
                    result.error(
                        "request.presenter_master",
                        f"request.segments.{segment_id}.reference_roles",
                        f"Presenter reference {raw_path} must be the job's presenter master ({master}).",
                    )
    approval = presenter.get("approval")
    if repo_root is not None and isinstance(master, str) and isinstance(approval, dict):
        try:
            master_path = resolve_repo_path(repo_root, master)
        except (ValueError, FileNotFoundError) as exc:
            result.error("presenter.master", "job.presenter.master_image", str(exc))
        else:
            if sha256_file(master_path) != str(approval.get("sha256", "")).lower():
                result.error(
                    "presenter.approval",
                    "job.presenter.approval.sha256",
                    "The presenter master changed after registration; re-register it with scripts/set_presenter_master.py and regenerate keyframes.",
                )

    # Background continuity uses three generated views made from one written setting contract.
    # Source-video frames remain forbidden. Registered hashes prevent silent swaps.
    if request.get("background_lock_policy") == "scene_pack_v1" and isinstance(request_segments, dict):
        registered = job.get("scene_packs")
        registered = registered if isinstance(registered, dict) else {}
        shot_segments = {
            str(segment.get("id")): segment
            for segment in shot_plan.get("segments", [])
            if isinstance(segment, dict)
        }
        for segment_id, segment in request_segments.items():
            if not isinstance(segment, dict):
                continue
            scene_id = segment.get("scene_id")
            entry = registered.get(scene_id) if isinstance(scene_id, str) else None
            roles = segment.get("reference_roles")
            scene_refs = [
                raw_path for raw_path, role in (roles.items() if isinstance(roles, dict) else [])
                if role == "scene_identity"
            ]
            if not isinstance(entry, dict):
                if scene_refs:
                    result.error(
                        "scene_pack.unregistered",
                        f"job.scene_packs.{scene_id}",
                        "A scene_identity reference is present but its three-view pack is not registered.",
                    )
                else:
                    result.warning(
                        "scene_pack.pending",
                        f"job.scene_packs.{scene_id}",
                        "Generate and register the three empty scene-pack views before keyframe generation.",
                    )
                continue
            view = segment.get("scene_view")
            views = entry.get("views")
            view_entry = views.get(view) if isinstance(views, dict) else None
            registered_path = view_entry.get("master_image") if isinstance(view_entry, dict) else None
            if scene_refs != [registered_path]:
                result.error(
                    "request.scene_master",
                    f"request.segments.{segment_id}.reference_roles",
                    f"scene_identity must be the registered {view!r} scene-pack view {registered_path!r}.",
                )
            if segment.get("scene_lock") != entry.get("scene_lock"):
                result.error(
                    "request.scene_lock_mismatch",
                    f"request.segments.{segment_id}.scene_lock",
                    "Keyframe scene_lock must match the registered scene-pack contract.",
                )
            matching_plan = next(
                (
                    item for item in shot_segments.values()
                    if segment_id in [str(value) for value in item.get("keyframe_ids", [])]
                ),
                None,
            )
            matching_frame = next(
                (
                    frame for frame in matching_plan.get("reference_frames", [])
                    if isinstance(frame, dict) and str(frame.get("keyframe_id")) == str(segment_id)
                ),
                None,
            ) if isinstance(matching_plan, dict) else None
            if isinstance(matching_plan, dict) and (
                matching_plan.get("scene_id") != scene_id
                or matching_plan.get("scene_lock") != segment.get("scene_lock")
                or matching_plan.get("scene_pack_id") != scene_id
                or not isinstance(matching_frame, dict)
                or matching_frame.get("scene_view") != view
                or matching_frame.get("scene_master") != registered_path
            ):
                result.error(
                    "shots.scene_master",
                    f"shot_plan.segments.{matching_plan.get('id')}",
                    "Shot plan, request and registered scene-pack view must use one identical background contract.",
                )
            if repo_root is not None and isinstance(registered_path, str) and isinstance(view_entry, dict):
                try:
                    scene_master_path = resolve_repo_path(repo_root, registered_path)
                except (ValueError, FileNotFoundError) as exc:
                    result.error("scene_pack.file", f"job.scene_packs.{scene_id}", str(exc))
                else:
                    if sha256_file(scene_master_path) != str(view_entry.get("sha256", "")).lower():
                        result.error(
                            "scene_pack.approval",
                            f"job.scene_packs.{scene_id}.views.{view}.sha256",
                            "A scene-pack view changed after registration; re-register the pack and regenerate keyframes.",
                        )

    if request.get("pipeline_job_id") != job.get("job_id"):
        result.error(
            "request.job",
            "request.pipeline_job_id",
            "Keyframe request pipeline_job_id must match job.job_id.",
        )
    if request.get("variant_id") != shot_plan.get("variant_id"):
        result.error(
            "request.variant",
            "request.variant_id",
            "Keyframe request variant_id must match shot_plan.variant_id.",
        )
    return result


def validate_ready(ready: Any, ready_path: Path, repo_root: Path) -> ValidationResult:
    result = ValidationResult()
    if not _require_object(ready, result, "ready"):
        return result
    if ready.get("schema") != "keyframe-ready/v1":
        result.error("schema.unsupported", "ready.schema", "Expected keyframe-ready/v1.")
    if ready.get("generator") != "codex-imagegen":
        result.error("ready.generator", "ready.generator", "Expected codex-imagegen.")
    if ready.get("created_by") != "codex":
        result.error("ready.creator", "ready.created_by", "Expected codex.")
    segments = ready.get("segments")
    if not isinstance(segments, dict) or not segments:
        result.error("ready.segments", "ready.segments", "At least one completed keyframe is required.")
        return result
    for segment_id, segment in segments.items():
        path = f"ready.segments.{segment_id}"
        if not isinstance(segment, dict):
            result.error("type.object", path, "Expected a completed keyframe object.")
            continue
        keyframe = segment.get("keyframe")
        if not isinstance(keyframe, str):
            result.error("ready.keyframe", f"{path}.keyframe", "Expected a keyframe filename.")
        else:
            candidate = (ready_path.parent / keyframe).resolve()
            if candidate.parent != ready_path.parent.resolve():
                result.error("ready.keyframe", f"{path}.keyframe", "Keyframe must be in the READY.json directory.")
            elif not candidate.exists():
                result.error("ready.keyframe", f"{path}.keyframe", f"Missing keyframe: {keyframe}")
        for index, raw_path in enumerate(segment.get("extra_refs", [])):
            try:
                resolve_repo_path(repo_root, str(raw_path))
            except (ValueError, FileNotFoundError) as exc:
                result.error("path.invalid", f"{path}.extra_refs[{index}]", str(exc))
    return result


def validate_shot_map(shot_map: Any, job: dict[str, Any]) -> ValidationResult:
    """Validate the exact source edit timeline used by shot_for_shot jobs."""

    result = ValidationResult()
    if not _require_object(shot_map, result, "shot_map"):
        return result
    if shot_map.get("schema") != "shot-map/v1":
        result.error("schema.unsupported", "shot_map.schema", "Expected shot-map/v1.")
    if shot_map.get("visual_mode") != "shot_for_shot":
        result.error("visual_mode.mismatch", "shot_map.visual_mode", "Expected shot_for_shot.")
    if Path(str(shot_map.get("reference_video", ""))).as_posix() != Path(str(job.get("reference_video", ""))).as_posix():
        result.error(
            "source.mismatch",
            "shot_map.reference_video",
            "Shot map must identify the job reference_video.",
        )

    source_duration = shot_map.get("source_duration_seconds")
    if not isinstance(source_duration, (int, float)) or source_duration <= 0:
        result.error("shot_map.duration", "shot_map.source_duration_seconds", "Expected a positive duration.")
        source_duration = None

    shots = shot_map.get("shots")
    if not isinstance(shots, list) or not shots:
        result.error("shot_map.shots", "shot_map.shots", "At least one exact source shot is required.")
        return result

    previous_end = 0.0
    seen: set[str] = set()
    derived_cuts: list[float] = []
    for index, shot in enumerate(shots, start=1):
        path = f"shot_map.shots[{index - 1}]"
        if not isinstance(shot, dict):
            result.error("type.object", path, "Expected an object.")
            continue
        expected_id = f"SH{index:03d}"
        shot_id = shot.get("id")
        if shot_id != expected_id:
            result.error("shot_map.order", f"{path}.id", f"Expected {expected_id}.")
        if isinstance(shot_id, str):
            if shot_id in seen:
                result.error("shot_map.duplicate", f"{path}.id", f"Duplicate shot ID: {shot_id}")
            seen.add(shot_id)
        start = shot.get("source_start_seconds")
        end = shot.get("source_end_seconds")
        duration = shot.get("source_edit_duration_seconds")
        if not all(isinstance(value, (int, float)) for value in (start, end, duration)):
            result.error("shot_map.interval", path, "Shot times and duration must be numeric.")
            continue
        if abs(float(start) - previous_end) > 0.001:
            result.error("shot_map.coverage", f"{path}.source_start_seconds", "Shots must be contiguous.")
        if float(end) <= float(start) or abs((float(end) - float(start)) - float(duration)) > 0.001:
            result.error("shot_map.interval", path, "Expected start < end and duration=end-start.")
        if index > 1:
            derived_cuts.append(round(float(start), 3))
        previous_end = float(end)

    if source_duration is not None and abs(previous_end - float(source_duration)) > 0.001:
        result.error("shot_map.coverage", "shot_map.shots", "Shots must cover the complete source duration.")
    declared_cuts = shot_map.get("cut_times_seconds")
    try:
        normalized_cuts = [round(float(value), 3) for value in declared_cuts]
    except (TypeError, ValueError):
        normalized_cuts = []
    if normalized_cuts != derived_cuts:
        result.error("shot_map.cuts", "shot_map.cut_times_seconds", "Cut times must equal the shot boundaries.")
    return result


def validate_shot_for_shot_coverage(
    shot_map: dict[str, Any],
    plan: dict[str, Any],
    request: dict[str, Any],
    job: dict[str, Any],
) -> ValidationResult:
    """Pin every source microshot to a timed cut inside a small set of H3 clips."""

    result = ValidationResult()
    source_shots = [shot for shot in shot_map.get("shots", []) if isinstance(shot, dict)]
    source_by_id = {str(shot.get("id")): shot for shot in source_shots}
    expected_ids = list(source_by_id)
    plan_segments = [segment for segment in plan.get("segments", []) if isinstance(segment, dict)]
    request_segments = request.get("segments") if isinstance(request.get("segments"), dict) else {}

    actual_ids: list[str] = []
    expected_keyframes: list[str] = []
    previous_source_end = 0.0
    for segment_index, segment in enumerate(plan_segments):
        path = f"shot_plan.segments[{segment_index}]"
        duration = segment.get("duration_seconds")
        if not isinstance(duration, (int, float)) or not 2 <= float(duration) <= 15:
            result.error("shot_for_shot.h3_duration", f"{path}.duration_seconds", "Each H3 clip must last 2-15 seconds.")

        keyframe_ids = segment.get("keyframe_ids") if isinstance(segment.get("keyframe_ids"), list) else []
        if not 1 <= len(keyframe_ids) <= 3:
            result.error(
                "shot_for_shot.reference_count",
                f"{path}.keyframe_ids",
                "Each H3 clip must use one to three generated keyframes and bind only two or three total Pictures.",
            )
        expected_keyframes.extend(str(value) for value in keyframe_ids)

        source_start = segment.get("source_start_seconds")
        source_end = segment.get("source_end_seconds")
        edit_duration = segment.get("source_edit_duration_seconds")
        if not all(isinstance(value, (int, float)) for value in (source_start, source_end, edit_duration)):
            result.error("shot_for_shot.clip_window", path, "Each clip needs numeric source start, end and edit duration.")
            continue
        if abs(float(source_start) - previous_source_end) > 0.001:
            result.error("shot_for_shot.clip_coverage", f"{path}.source_start_seconds", "H3 clip source windows must be contiguous.")
        if float(source_end) <= float(source_start) or abs(float(source_end) - float(source_start) - float(edit_duration)) > 0.001:
            result.error("shot_for_shot.clip_window", path, "Expected source_start < source_end and edit duration=end-start.")
        if isinstance(duration, (int, float)) and float(duration) + 0.001 < float(edit_duration):
            result.error("shot_for_shot.clip_too_short", f"{path}.duration_seconds", "The H3 render must cover its complete source edit window.")
        previous_source_end = float(source_end)

        timed_shots = segment.get("timed_shots")
        if not isinstance(timed_shots, list) or not timed_shots:
            result.error("shot_for_shot.timed_shots", f"{path}.timed_shots", "Each H3 clip needs timed microshots.")
            continue
        previous_clip_end = 0.0
        for timed_index, timed in enumerate(timed_shots):
            timed_path = f"{path}.timed_shots[{timed_index}]"
            if not isinstance(timed, dict):
                result.error("type.object", timed_path, "Expected a timed microshot object.")
                continue
            source_id = str(timed.get("source_shot_id", ""))
            actual_ids.append(source_id)
            source = source_by_id.get(source_id)
            if source is None:
                result.error("shot_for_shot.unknown_source", f"{timed_path}.source_shot_id", f"Unknown source shot {source_id}.")
                continue
            for field in ("source_start_seconds", "source_end_seconds"):
                value = timed.get(field)
                expected = source.get(field)
                if not isinstance(value, (int, float)) or abs(float(value) - float(expected)) > 0.001:
                    result.error("shot_for_shot.timing", f"{timed_path}.{field}", f"Expected {expected}.")
            clip_start = timed.get("clip_start_seconds")
            clip_end = timed.get("clip_end_seconds")
            expected_clip_start = round(float(source["source_start_seconds"]) - float(source_start), 3)
            expected_clip_end = round(float(source["source_end_seconds"]) - float(source_start), 3)
            if not isinstance(clip_start, (int, float)) or abs(float(clip_start) - expected_clip_start) > 0.001:
                result.error("shot_for_shot.clip_timing", f"{timed_path}.clip_start_seconds", f"Expected {expected_clip_start}.")
            if not isinstance(clip_end, (int, float)) or abs(float(clip_end) - expected_clip_end) > 0.001:
                result.error("shot_for_shot.clip_timing", f"{timed_path}.clip_end_seconds", f"Expected {expected_clip_end}.")
            if isinstance(clip_start, (int, float)) and abs(float(clip_start) - previous_clip_end) > 0.001:
                result.error("shot_for_shot.clip_timing", f"{timed_path}.clip_start_seconds", "Timed microshots must be contiguous.")
            if isinstance(clip_end, (int, float)):
                previous_clip_end = float(clip_end)
            picture_id = str(timed.get("picture_keyframe_id", ""))
            if picture_id not in [str(value) for value in keyframe_ids]:
                result.error("shot_for_shot.picture", f"{timed_path}.picture_keyframe_id", "Timed shot must use a keyframe from its H3 clip.")
        if abs(previous_clip_end - float(edit_duration)) > 0.001:
            result.error("shot_for_shot.clip_timing", f"{path}.timed_shots", "Timed microshots must fill the source edit window.")

    if actual_ids != expected_ids:
        result.error(
            "shot_for_shot.coverage",
            "shot_plan.segments",
            f"Timed source shots {actual_ids} do not exactly equal {expected_ids}.",
        )
    if abs(previous_source_end - float(shot_map.get("source_duration_seconds", 0))) > 0.001:
        result.error("shot_for_shot.clip_coverage", "shot_plan.segments", "H3 clip windows must cover the full source duration.")
    if list(request_segments) != expected_keyframes:
        result.error(
            "shot_for_shot.request_order",
            "request.segments",
            "Keyframe request order must match all H3 clip keyframes in order.",
        )

    render_plan = job.get("render_plan")
    if not isinstance(render_plan, dict):
        result.error("shot_for_shot.render_plan", "job.render_plan", "shot_for_shot jobs require a render_plan.")
    else:
        h3_count = len(plan_segments)
        expected_batches = math.ceil(h3_count / int(job.get("max_segments_per_render", 4))) if h3_count else 0
        checks = {
            "keyframe_count": len(expected_keyframes),
            "h3_clip_count": h3_count,
            "expected_h3_batches": expected_batches,
            "edit_to_source_duration_seconds": shot_map.get("source_duration_seconds"),
        }
        for field, expected in checks.items():
            value = render_plan.get(field)
            if not isinstance(value, (int, float)) or abs(float(value) - float(expected)) > 0.001:
                result.error("shot_for_shot.render_plan", f"job.render_plan.{field}", f"Expected {expected}.")
    return result


def validate_ready_against_request(
    ready: Any,
    request: dict[str, Any],
    job: dict[str, Any],
) -> ValidationResult:
    result = ValidationResult()
    if not isinstance(ready, dict):
        return result
    if ready.get("job") != request.get("job"):
        result.error("ready.job", "ready.job", "READY job must match the keyframe request job.")
    if ready.get("variant_id") != request.get("variant_id"):
        result.error("ready.variant", "ready.variant_id", "READY variant must match the keyframe request.")
    if ready.get("source_job_id") != request.get("source_job_id"):
        result.error("ready.source_job", "ready.source_job_id", "READY source_job_id must match the keyframe request.")
    pipeline_job_id = ready.get("pipeline_job_id")
    if pipeline_job_id is not None and pipeline_job_id != job.get("job_id"):
        result.error("ready.pipeline_job", "ready.pipeline_job_id", "READY pipeline_job_id must match job.job_id.")
    job_audio_mode = job.get("audio_mode", "dialogue")
    ready_audio_mode = ready.get("audio_mode")
    if ready_audio_mode is not None and ready_audio_mode != job_audio_mode:
        result.error("ready.audio_mode", "ready.audio_mode", "READY audio_mode must match the job.")
    if job_audio_mode == "silent" and ready_audio_mode != "silent":
        result.error("ready.audio_mode", "ready.audio_mode", "Silent jobs must declare audio_mode=silent in READY.")

    ready_segments = ready.get("segments")
    request_segments = request.get("segments")
    if not isinstance(ready_segments, dict) or not isinstance(request_segments, dict):
        return result
    if set(ready_segments) != set(request_segments):
        result.error(
            "ready.coverage",
            "ready.segments",
            "READY.json must cover every requested keyframe exactly once.",
        )
        return result
    for segment_id, requested in request_segments.items():
        completed = ready_segments.get(segment_id)
        path = f"ready.segments.{segment_id}"
        if not isinstance(requested, dict) or not isinstance(completed, dict):
            continue
        if completed.get("keyframe") != requested.get("output"):
            result.error("ready.output", f"{path}.keyframe", "READY keyframe must match the requested output filename.")
        roles = requested.get("reference_roles")
        product_refs = [
            raw_path for raw_path, role in (roles.items() if isinstance(roles, dict) else [])
            if role == "product_identity"
        ]
        extra_refs = completed.get("extra_refs", [])
        if extra_refs != product_refs:
            result.error(
                "ready.product_refs",
                f"{path}.extra_refs",
                "READY extra_refs must exactly match the requested product_identity reference order.",
            )
    return result


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def validate_keyframe_qc(
    qc: Any,
    qc_path: Path,
    request: dict[str, Any],
) -> ValidationResult:
    result = ValidationResult()
    if not _require_object(qc, result, "qc"):
        return result
    if qc.get("schema") != "keyframe-qc/v1":
        result.error("schema.unsupported", "qc.schema", "Expected keyframe-qc/v1.")
    if qc.get("result") != "pass":
        result.error("qc.result", "qc.result", "Every keyframe must pass visual inspection before READY.json.")

    requested = request.get("segments")
    expected_ids = set(requested) if isinstance(requested, dict) else set()
    qc_segments = qc.get("segments")
    actual_ids = set(qc_segments) if isinstance(qc_segments, dict) else set()
    if actual_ids != expected_ids:
        result.error(
            "qc.coverage",
            "qc.segments",
            f"QC segments {sorted(actual_ids)} do not exactly cover requested keyframes {sorted(expected_ids)}.",
        )
    if not isinstance(qc_segments, dict):
        return result

    if request.get("background_lock_policy") == "scene_pack_v1":
        expected_scenes: dict[str, list[str]] = {}
        for segment_id, requested_segment in (requested.items() if isinstance(requested, dict) else []):
            if not isinstance(requested_segment, dict):
                continue
            expected_scenes.setdefault(str(requested_segment.get("scene_id")), []).append(str(segment_id))
        reviews = qc.get("scene_consistency")
        if not isinstance(reviews, dict) or set(reviews) != set(expected_scenes):
            result.error(
                "qc.scene_consistency",
                "qc.scene_consistency",
                "QC must contain one cross-keyframe scene consistency review per scene_id.",
            )
        else:
            for scene_id, keyframes in expected_scenes.items():
                review = reviews.get(scene_id)
                path = f"qc.scene_consistency.{scene_id}"
                if not isinstance(review, dict) or review.get("result") != "pass":
                    result.error("qc.scene_consistency", path, "Scene consistency review must pass.")
                    continue
                if review.get("keyframes") != keyframes:
                    result.error("qc.scene_coverage", f"{path}.keyframes", "Scene review must list every keyframe in request order.")
                if review.get("scene_views") != ["eye_level", "oblique_45", "overhead_90"]:
                    result.error(
                        "qc.scene_views",
                        f"{path}.scene_views",
                        "QC must inspect all three registered scene-pack views before comparing keyframes.",
                    )
                if review.get("variation_policy") != "closeup_flexible":
                    result.error(
                        "qc.scene_variation",
                        f"{path}.variation_policy",
                        "Scene review must allow natural close-up and background-bokeh variation while locking one physical table.",
                    )
                if review.get("hard_match_fields") != list(SCENE_HARD_LOCK_FIELDS):
                    result.error(
                        "qc.scene_hard_lock",
                        f"{path}.hard_match_fields",
                        "QC must hard-match the physical tabletop identity across every keyframe.",
                    )
                if review.get("soft_guide_fields") != list(SCENE_SOFT_GUIDE_FIELDS):
                    result.error(
                        "qc.scene_soft_guides",
                        f"{path}.soft_guide_fields",
                        "QC must review setting, backdrop, lighting, palette and fixed props as flexible continuity guides.",
                    )
        for segment_id, requested_segment in (requested.items() if isinstance(requested, dict) else []):
            roles = requested_segment.get("reference_roles") if isinstance(requested_segment, dict) else None
            scene_refs = [
                path for path, role in (roles.items() if isinstance(roles, dict) else [])
                if role == "scene_identity"
            ]
            if len(scene_refs) != 1:
                result.error(
                    "qc.scene_reference",
                    f"request.segments.{segment_id}.reference_roles",
                    "QC cannot pass until the keyframe binds exactly one registered scene-pack view.",
                )

    for segment_id, segment in qc_segments.items():
        path = f"qc.segments.{segment_id}"
        if not isinstance(segment, dict):
            result.error("type.object", path, "Expected a QC segment object.")
            continue
        requested_segment = requested.get(segment_id, {}) if isinstance(requested, dict) else {}
        filename = segment.get("file")
        if not isinstance(filename, str) or Path(filename).name != filename:
            result.error("qc.file", f"{path}.file", "Expected a local keyframe filename.")
            continue
        if requested_segment.get("output") != filename:
            result.error("qc.output", f"{path}.file", "QC filename must match the requested output.")
        candidate = (qc_path.parent / filename).resolve()
        if candidate.parent != qc_path.parent.resolve() or not candidate.is_file():
            result.error("qc.file", f"{path}.file", f"Missing keyframe: {filename}")
            continue
        expected_hash = segment.get("sha256")
        if not isinstance(expected_hash, str) or sha256_file(candidate) != expected_hash.lower():
            result.error("qc.hash", f"{path}.sha256", f"QC hash does not match {filename}.")
        dimensions = _png_dimensions(candidate)
        if dimensions is None:
            result.error("qc.png", f"{path}.file", f"{filename} is not a valid PNG image.")
        else:
            width, height = dimensions
            if segment.get("width") != width or segment.get("height") != height:
                result.error(
                    "qc.dimensions",
                    path,
                    f"QC dimensions do not match {filename}: actual {width}x{height}.",
                )
            if width < 720 or height < 1280:
                result.error("qc.resolution", path, f"Keyframe {filename} is below the 720x1280 minimum.")
            if abs((width / height) - (9 / 16)) > 0.01:
                result.error("qc.aspect", path, f"Keyframe {filename} is not 9:16 (actual {width}x{height}).")
        checks = segment.get("checks")
        if not isinstance(checks, list) or not checks or not all(isinstance(value, str) and value for value in checks):
            result.error("qc.checks", f"{path}.checks", "Visual inspection checks are required.")
        else:
            request_checks = requested_segment.get("checks")
            if isinstance(request_checks, list) and len(checks) < len(request_checks):
                result.error(
                    "qc.checks_incomplete",
                    f"{path}.checks",
                    "QC must record at least as many visual checks as the keyframe request requires.",
                )
    return result


def load_bundle(job_path: Path, repo_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    job = load_json(job_path)
    product = load_json(resolve_repo_path(repo_root, job["product"]))
    beats = load_json(resolve_repo_path(repo_root, job["beats"]))
    script = load_json(resolve_repo_path(repo_root, job["script"]))
    shot_plan = load_json(resolve_repo_path(repo_root, job["shot_plan"]))
    request = load_json(resolve_repo_path(repo_root, job["keyframe_request"]))
    return job, product, beats, script, shot_plan, request


def validate_bundle(job_path: Path, repo_root: Path) -> tuple[ValidationResult, dict[str, Any]]:
    result = ValidationResult()
    try:
        job = load_json(job_path)
    except Exception as exc:
        result.error("json.job", str(job_path), str(exc))
        return result, {}

    result.extend(validate_job(job, repo_root))
    if not result.ok:
        return result, {"job": job}

    try:
        job, product, beats, script, shot_plan, request = load_bundle(job_path, repo_root)
    except Exception as exc:
        result.error("bundle.load", str(job_path), str(exc))
        return result, {"job": job}

    result.extend(validate_product(product))
    result.extend(validate_beats(beats))
    result.extend(validate_source_alignment(job, beats))
    result.extend(validate_script(script, beats, product))
    if job.get("audio_mode", "dialogue") != script.get("audio_mode", "dialogue"):
        result.error("audio_mode.mismatch", "script.audio_mode", "Script audio_mode must match job.audio_mode.")
    result.extend(validate_shot_plan(shot_plan, script))
    result.extend(validate_keyframe_request(request, repo_root, product))
    result.extend(validate_keyframe_coverage(request, shot_plan, job, repo_root))
    bundle = {
        "job": job,
        "product": product,
        "beats": beats,
        "script": script,
        "shot_plan": shot_plan,
        "request": request,
    }
    if job.get("visual_mode", "structure_remix") == "shot_for_shot":
        try:
            shot_map = load_json(resolve_repo_path(repo_root, job["shot_map"]))
        except Exception as exc:
            result.error("shot_map.load", "job.shot_map", str(exc))
        else:
            result.extend(validate_shot_map(shot_map, job))
            result.extend(validate_shot_for_shot_coverage(shot_map, shot_plan, request, job))
            bundle["shot_map"] = shot_map
    return result, bundle
