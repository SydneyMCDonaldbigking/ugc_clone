from __future__ import annotations

from pathlib import Path
from typing import Any


# Keyframe prompts are kept short and positive: image models redraw whatever a prompt keeps naming,
# so forbidden features ("no handle") and the QC checklist stay in REQUEST.json for inspection and are
# never sent to the model. The product keeps the orientation of its reference photo (front or back
# square to the camera, not turned to an unseen side); whether it is held or set down, and the camera
# angle, follow the source's shot. Motion (lifting, tilting, pouring) is left to H3.
FIDELITY_INSTRUCTIONS = {
    "reference_lock": "Keep it identical to the reference photo; simplify the pose rather than change the product.",
    "pixel_preserve": (
        "Use the supplied product photo as the package identity authority and keep its visible face unchanged; "
        "reject the result if the package, label layout or dense copy drifts."
    ),
}

# Positive visual fields only; handle/grip/forbidden entries describe what to reject, not what to draw.
PROMPT_IDENTITY_FIELDS = ("packaging_type", "closure")


def _find_shot(shot_plan: dict[str, Any], keyframe_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    for segment in shot_plan.get("segments", []):
        if keyframe_id not in [str(value) for value in segment.get("keyframe_ids", [])]:
            continue
        for subshot in segment.get("subshots", []):
            if str(subshot.get("keyframe_id")) == keyframe_id:
                return segment, subshot
        for frame in segment.get("reference_frames", []):
            if str(frame.get("keyframe_id")) == keyframe_id:
                return segment, frame
        return segment, None
    raise KeyError(f"No shot-plan segment covers keyframe {keyframe_id!r}.")


ROLE_LABELS = {
    "product_identity": "the product",
    "presenter_identity": "the presenter: face, hair, outfit and room",
    "presenter_and_scene_identity": "the presenter: face, hair, outfit and room",
    "scene_identity": "the approved empty scene master: background, surface, props, palette and light",
}


def _format_reference_roles(
    segment_request: dict[str, Any], *, exclude_roles: set[str] | None = None
) -> str:
    references = segment_request.get("references", [])
    roles = segment_request.get("reference_roles", {})
    lines = []
    included = [path for path in references if roles.get(path) not in (exclude_roles or set())]
    for index, path in enumerate(included, start=1):
        role = roles.get(path, "unspecified")
        lines.append(f"Image {index}: {ROLE_LABELS.get(role, role)}.")
    return "\n".join(lines)


def _describe_product(product: dict[str, Any]) -> str:
    identity = product.get("visual_identity", {})
    parts = [str(identity[key]) for key in PROMPT_IDENTITY_FIELDS if identity.get(key)]
    return ", ".join(parts) or "as shown"


def _scene_lock_block(segment_request: dict[str, Any]) -> str:
    scene_image = _image_label(segment_request, {"scene_identity"}, "")
    if not scene_image:
        if segment_request.get("scene_id") and segment_request.get("scene_lock"):
            raise ValueError("Register the three-view scene pack before compiling keyframe prompts.")
        return ""
    scene_lock = segment_request["scene_lock"]
    soft = "; ".join(
        f"{label}: {scene_lock[key]}"
        for key, label in (
            ("setting", "setting"),
            ("backdrop", "backdrop"),
            ("lighting", "lighting"),
            ("palette", "palette"),
            ("fixed_props", "prop family"),
        )
    )
    return (
        f"Background master: use {scene_image} for this camera angle. Hard invariant: this is the same physical "
        f"tabletop in every keyframe — surface: {scene_lock['surface']}. Soft continuity guide: {soft}. "
        "For close-ups, keep the product and active hands crisp while natural changes in crop, parallax, visible props, "
        "slight local exposure and shallow-depth background bokeh are welcome."
    )


def _image_label(segment_request: dict[str, Any], wanted_roles: set[str], fallback: str) -> str:
    roles = segment_request.get("reference_roles", {})
    for index, path in enumerate(segment_request.get("references", []), start=1):
        if roles.get(path) in wanted_roles:
            return f"Image {index}"
    return fallback


def render_keyframe_prompt(
    *,
    product: dict[str, Any],
    shot_plan: dict[str, Any],
    request: dict[str, Any],
    keyframe_id: str,
    template_text: str,
) -> str:
    segment_request = request["segments"][keyframe_id]
    segment, subshot = _find_shot(shot_plan, keyframe_id)
    product_presence = segment_request.get("product_presence", "present")
    mode = segment_request.get("product_fidelity_mode", "reference_lock")
    if product_presence not in {"present", "absent"}:
        raise ValueError(f"Unsupported product presence: {product_presence}")
    if product_presence == "present" and mode not in FIDELITY_INSTRUCTIONS:
        raise ValueError(f"Unsupported product fidelity mode: {mode}")
    if product_presence == "absent" and mode != "not_applicable":
        raise ValueError("Product-absent keyframes must use product_fidelity_mode=not_applicable")

    shot = subshot if subshot else segment
    first_frame = shot.get("first_frame") or segment.get("first_frame")
    if not first_frame:
        raise ValueError(f"Keyframe {keyframe_id!r} needs a first_frame description in the shot plan.")
    product_image = _image_label(segment_request, {"product_identity"}, "the product reference")
    description = _describe_product(product)
    if product_presence == "present":
        product_instruction = (
            f"Product: {product.get('name', 'the product')}, copied exactly from {product_image} - "
            f"{description}. {FIDELITY_INSTRUCTIONS[mode]}"
        )
    else:
        product_instruction = (
            "Frame content: show only the described rice, cookware, hands and locked scene for this source shot; "
            "the retail package is outside this shot."
        )
    values = {
        "REFERENCE_ROLE_MAP": _format_reference_roles(segment_request),
        "FIRST_FRAME": str(first_frame),
        "CAMERA": str(shot.get("camera") or segment.get("camera", "")),
        "PERFORMANCE": str(shot.get("performance") or segment.get("performance", "")),
        "PRODUCT_NAME": str(product.get("name", "the product")),
        "PRODUCT_IMAGE": _image_label(segment_request, {"product_identity"}, "the product reference"),
        "SCENE_LOCK_BLOCK": _scene_lock_block(segment_request),
        "PRESENTER_IMAGE": _image_label(
            segment_request, {"presenter_identity", "presenter_and_scene_identity"}, "the presenter master"
        ),
        "PRODUCT_DESCRIPTION": _describe_product(product),
        "PRODUCT_FIDELITY_INSTRUCTION": FIDELITY_INSTRUCTIONS.get(mode, ""),
        "PRODUCT_INSTRUCTION": product_instruction,
    }
    rendered = template_text
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    unresolved = [token for token in rendered.split() if token.startswith("{{")]
    if unresolved:
        raise ValueError(f"Unresolved prompt tokens: {unresolved}")
    return rendered.rstrip() + "\n"


def load_template(path: Path) -> str:
    return path.read_text(encoding="utf-8")
