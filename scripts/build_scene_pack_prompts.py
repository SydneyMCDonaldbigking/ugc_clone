"""Compile three positive ImageGen prompts for each scene-pack requirement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

VIEW_DIRECTIONS = {
    "eye_level": (
        "Eye-level or gently low oblique smartphone view that establishes the filming space, "
        "with natural depth and enough clean working surface in the foreground."
    ),
    "oblique_45": (
        "First-person 45-degree high-angle smartphone view of the same space and the same working surface, "
        "with view-dependent parallax, a naturally different crop and shifted prop visibility."
    ),
    "overhead_90": (
        "Direct 90-degree overhead smartphone view of the same working surface, preserving the same material, "
        "colour, grain direction and identifiable tabletop character."
    ),
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _prompt(scene_id: str, scene_lock: dict[str, str], view: str) -> str:
    hard_lock = f"table identity, hard invariant: {scene_lock['surface']}"
    soft_guide = "\n".join(
        f"{field}, soft guide: {scene_lock[field]}"
        for field in ("setting", "backdrop", "lighting", "palette", "fixed_props")
    )
    relationship = (
        "This is the base scene-identity view."
        if view == "eye_level"
        else "Use the accepted eye-level scene image as Image 1. Keep the identical physical table while reconstructing a natural new camera angle; close-up framing and background details may shift."
    )
    return (
        "Use case: photorealistic-natural\n"
        "Asset type: empty three-angle scene identity pack for vertical UGC product keyframes\n"
        f"Scene ID: {scene_id}\n"
        f"Camera view: {VIEW_DIRECTIONS[view]}\n"
        f"View relationship: {relationship}\n"
        "Scene contract:\n"
        f"{hard_lock}\n"
        f"{soft_guide}\n"
        "Composition: vertical 9:16 smartphone photograph, unoccupied filming set, clean usable foreground, "
        "believable home texture and slight candid imperfection. Angle-dependent crop, parallax, focus depth, "
        "visible props and small local exposure differences should feel natural.\n"
        "Content: an empty background plate prepared for later product and hand compositing, with all named "
        "fixed props resting naturally in the environment.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    args = parser.parse_args()

    request_path = args.request if args.request.is_absolute() else REPO_ROOT / args.request
    request = _load(request_path)
    if request.get("background_lock_policy") != "scene_pack_v1":
        raise SystemExit("request does not use background_lock_policy=scene_pack_v1")
    requirements = request.get("scene_pack_requirements")
    if not isinstance(requirements, dict) or not requirements:
        raise SystemExit("request has no scene_pack_requirements")

    written: list[str] = []
    for scene_id, requirement in requirements.items():
        scene_lock = requirement["scene_lock"]
        for view, view_request in requirement["views"].items():
            output = (REPO_ROOT / view_request["prompt_file"]).resolve()
            if REPO_ROOT.resolve() not in output.parents:
                raise SystemExit(f"scene-pack prompt escapes repository: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(_prompt(str(scene_id), scene_lock, str(view)), encoding="utf-8")
            written.append(output.as_posix())
    print(json.dumps({"scene_packs": len(requirements), "prompts": written}, indent=2))


if __name__ == "__main__":
    main()
