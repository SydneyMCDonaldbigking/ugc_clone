from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .io import load_json, resolve_repo_path, sha256_file


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")


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

    variants = job.get("variants")
    if not isinstance(variants, int) or variants < 1:
        result.error("variants.range", "job.variants", "Variants must be a positive integer.")

    segment_duration = job.get("segment_duration_seconds")
    if not isinstance(segment_duration, (int, float)) or not 1 <= segment_duration <= 10:
        result.error("duration.range", "job.segment_duration_seconds", "Segment duration must be 1-10 seconds.")

    max_segments = job.get("max_segments_per_render")
    if not isinstance(max_segments, int) or not 1 <= max_segments <= 4:
        result.error("segments.limit", "job.max_segments_per_render", "A render may contain at most four segments.")

    if job.get("image_provider") != "codex-imagegen":
        result.error("provider.image", "job.image_provider", "Default keyframe provider must be codex-imagegen.")

    for key in ("reference_video", "product", "beats", "script", "shot_plan", "keyframe_request"):
        raw_path = job.get(key)
        if not isinstance(raw_path, str) or not raw_path:
            result.error("path.required", f"job.{key}", "Expected a repository-relative path.")
            continue
        try:
            resolve_repo_path(repo_root, raw_path)
        except (ValueError, FileNotFoundError) as exc:
            result.error("path.invalid", f"job.{key}", str(exc))

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
        text = _require_string(line, "text", result, path) or ""
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
        else:
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
# A generated keyframe already carries the image model's version of the product. Feeding it back as a
# reference compounds that drift, so every keyframe is generated fresh from the original photos.
GENERATED_MARKERS = ("/keyframes/",)


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
        frame_owners = subshots if subshots else [segment]
        for owner in frame_owners:
            if not isinstance(owner, dict) or not str(owner.get("first_frame", "")).strip():
                result.error(
                    "shots.first_frame",
                    f"{path}.first_frame",
                    "Every keyframe needs a first_frame: the still moment the image shows, product upright in its reference view.",
                )
        if subshots:
            # Each subshot is compiled into its own H3 segment (no cut inside an H3 segment),
            # so each must meet the H3 minimum and together they must fill the planned duration.
            durations = [sub.get("duration_seconds") for sub in subshots if isinstance(sub, dict)]
            if len(durations) != len(subshots) or not all(isinstance(value, (int, float)) for value in durations):
                result.error("shots.subshots", f"{path}.subshots", "Every subshot needs a numeric duration_seconds.")
            else:
                if any(value < H3_MIN_SEGMENT_SECONDS for value in durations):
                    result.error(
                        "shots.subshot_duration",
                        f"{path}.subshots",
                        f"Each subshot becomes one H3 segment and must last at least {H3_MIN_SEGMENT_SECONDS} s.",
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
    for segment_id, segment in segments.items():
        path = f"request.segments.{segment_id}"
        if not isinstance(segment, dict):
            result.error("type.object", path, "Expected a request object.")
            continue
        references = segment.get("references")
        if not isinstance(references, list) or not references:
            result.error("request.references", f"{path}.references", "At least one reference is required.")
        else:
            for index, raw_path in enumerate(references):
                try:
                    resolve_repo_path(repo_root, str(raw_path))
                except (ValueError, FileNotFoundError) as exc:
                    result.error("path.invalid", f"{path}.references[{index}]", str(exc))
        reference_roles = segment.get("reference_roles")
        _check_reference_origin(references, reference_roles, result, path)
        if not isinstance(reference_roles, dict) or not reference_roles:
            result.error("request.reference_roles", f"{path}.reference_roles", "Reference roles are required.")
        elif isinstance(references, list):
            if set(reference_roles) != set(str(value) for value in references):
                result.error(
                    "request.reference_roles",
                    f"{path}.reference_roles",
                    "Reference-role paths must exactly match the references list.",
                )
            product_refs = [raw_path for raw_path, role in reference_roles.items() if role == "product_identity"]
            if len(product_refs) != 1:
                result.error(
                    "request.product_reference",
                    f"{path}.reference_roles",
                    "Exactly one product_identity reference is required per keyframe.",
                )
            elif product is not None and product_refs[0] not in product.get("visual_assets", []):
                result.error(
                    "request.product_reference",
                    f"{path}.reference_roles",
                    "The product_identity reference must come from product.visual_assets.",
                )
        fidelity_mode = segment.get("product_fidelity_mode")
        if fidelity_mode not in {"reference_lock", "pixel_preserve"}:
            result.error(
                "request.fidelity_mode",
                f"{path}.product_fidelity_mode",
                "Expected reference_lock or pixel_preserve.",
            )
        placement = segment.get("product_placement")
        if not isinstance(placement, dict) or placement.get("orientation") != "unchanged_from_reference":
            result.error(
                "request.product_orientation",
                f"{path}.product_placement.orientation",
                "The product must appear in the same view as its reference photo (unchanged_from_reference).",
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

    # Person and scene continuity come from one registered presenter master (no product in it). Every
    # keyframe's presenter reference must be exactly that file; registration pins its hash so keyframes
    # made from an older master are caught.
    presenter = job.get("presenter") if isinstance(job.get("presenter"), dict) else {}
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
        checks = segment.get("checks")
        if not isinstance(checks, list) or not checks or not all(isinstance(value, str) and value for value in checks):
            result.error("qc.checks", f"{path}.checks", "Visual inspection checks are required.")
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
    result.extend(validate_shot_plan(shot_plan, script))
    result.extend(validate_keyframe_request(request, repo_root, product))
    result.extend(validate_keyframe_coverage(request, shot_plan, job, repo_root))
    return result, {
        "job": job,
        "product": product,
        "beats": beats,
        "script": script,
        "shot_plan": shot_plan,
        "request": request,
    }
