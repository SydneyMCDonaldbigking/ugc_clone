"""Compile product-agnostic ImageGen prompts from a job's data contracts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ugc_pipeline.io import load_json, resolve_repo_path
from ugc_pipeline.prompts import load_template, render_keyframe_prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", help="Repository-relative job JSON path.")
    parser.add_argument("--keyframe", action="append", help="Compile only this keyframe id; repeat as needed.")
    parser.add_argument("--stdout", action="store_true", help="Print prompts instead of writing prompt files.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = REPO_ROOT
    job = load_json(resolve_repo_path(repo_root, args.job))
    product = load_json(resolve_repo_path(repo_root, job["product"]))
    shot_plan = load_json(resolve_repo_path(repo_root, job["shot_plan"]))
    request = load_json(resolve_repo_path(repo_root, job["keyframe_request"]))
    template_path = resolve_repo_path(repo_root, request["prompt_template"])
    template_text = load_template(template_path)

    selected = set(args.keyframe or request["segments"].keys())
    unknown = selected - set(request["segments"])
    if unknown:
        raise SystemExit(f"Unknown keyframe ids: {sorted(unknown)}")

    for keyframe_id, segment_request in request["segments"].items():
        if keyframe_id not in selected:
            continue
        prompt = render_keyframe_prompt(
            product=product,
            shot_plan=shot_plan,
            request=request,
            keyframe_id=keyframe_id,
            template_text=template_text,
        )
        if args.stdout:
            print(f"--- keyframe {keyframe_id} ---")
            print(prompt, end="")
            continue
        output = resolve_repo_path(repo_root, segment_request["prompt_file"], must_exist=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(prompt, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
