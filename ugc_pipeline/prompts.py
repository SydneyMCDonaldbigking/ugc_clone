from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FIDELITY_INSTRUCTIONS = {
    "reference_lock": (
        "Recreate the product only when the requested interaction cannot be made from preserved source pixels. "
        "Treat every product-identity reference as authoritative. Preserve the same package type, silhouette, "
        "proportions, surfaces, closure, label layout, colours, count, and explicitly listed identity features. "
        "Simplify the pose before allowing any product drift."
    ),
    "pixel_preserve": (
        "Do not synthesize, redraw, restyle, relabel, or reinterpret the product. Generate the presenter and "
        "environment around the placement plan while leaving the product plane unobstructed. The original "
        "product pixels will be composited into that plane after generation. Keep hands and props behind the "
        "reserved product plane unless an explicit foreground mask is supplied. Match the source product pose; "
        "do not invent an unseen angle."
    ),
}


def _find_shot(shot_plan: dict[str, Any], keyframe_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    for segment in shot_plan.get("segments", []):
        if keyframe_id not in [str(value) for value in segment.get("keyframe_ids", [])]:
            continue
        for subshot in segment.get("subshots", []):
            if str(subshot.get("keyframe_id")) == keyframe_id:
                return segment, subshot
        return segment, None
    raise KeyError(f"No shot-plan segment covers keyframe {keyframe_id!r}.")


def _format_reference_roles(segment_request: dict[str, Any]) -> str:
    references = segment_request.get("references", [])
    roles = segment_request.get("reference_roles", {})
    lines = []
    for index, path in enumerate(references, start=1):
        role = roles.get(path, "unspecified")
        lines.append(f"Image {index}: {path} — role={role}.")
    return "\n".join(lines)


def _format_contract(product: dict[str, Any]) -> str:
    identity = product.get("visual_identity", {})
    lines = [f"Product name: {product.get('name', 'unspecified')}"]
    for key in sorted(identity):
        value = identity[key]
        rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        lines.append(f"- {key}: {rendered}")
    return "\n".join(lines)


def _format_acceptance(segment_request: dict[str, Any]) -> str:
    checks = segment_request.get("checks", [])
    placement = segment_request.get("product_placement", {})
    lines = [f"- {check}" for check in checks]
    if placement:
        lines.append(f"- Product placement plan: {json.dumps(placement, ensure_ascii=False, sort_keys=True)}")
    return "\n".join(lines)


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
    mode = segment_request["product_fidelity_mode"]
    if mode not in FIDELITY_INSTRUCTIONS:
        raise ValueError(f"Unsupported product fidelity mode: {mode}")

    action = subshot.get("action") if subshot else segment.get("action")
    values = {
        "REFERENCE_ROLE_MAP": _format_reference_roles(segment_request),
        "SUBJECT": str(segment.get("subject", "")),
        "ACTION": str(action or ""),
        "PERFORMANCE": str(segment.get("performance", "")),
        "PRODUCT_IDENTITY_CONTRACT": _format_contract(product),
        "PRODUCT_FIDELITY_MODE": mode,
        "PRODUCT_FIDELITY_INSTRUCTION": FIDELITY_INSTRUCTIONS[mode],
        "ACCEPTANCE_CONDITIONS": _format_acceptance(segment_request),
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
