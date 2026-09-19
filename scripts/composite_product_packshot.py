"""Place an original white-background product packshot into a generated scene.

This is the concrete implementation behind ``pixel_preserve`` keyframes.  The
model may create the presenter, room, hands and glass, but it is not trusted to
retype dense packaging copy.  Product pixels come from the supplied packshot;
the script only removes the connected white background, scales the packshot and
alpha-composites it over the scene.

Example:
  python scripts/composite_product_packshot.py scene.png target_A2_2.png out.png \
      --height 1320 --center-x 470 --bottom 1490
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def packshot_alpha(image: Image.Image, threshold: int = 12, feather: float = 1.0) -> Image.Image:
    """Build an opaque silhouette mask for a product on a plain white background.

    Each product used by this pipeline is a single upright object.  For every
    occupied row we fill the span between its left and right non-white edge.
    This keeps white plastic opaque instead of treating it as background.
    """

    rgb = np.asarray(image.convert("RGB"), dtype=np.int16)
    distance_from_white = np.max(255 - rgb, axis=2)
    edge_pixels = distance_from_white >= threshold
    mask = np.zeros(edge_pixels.shape, dtype=np.uint8)
    occupied_rows: list[int] = []
    left_edges: list[int] = []
    right_edges: list[int] = []

    for y, row in enumerate(edge_pixels):
        xs = np.flatnonzero(row)
        if xs.size >= 8:
            occupied_rows.append(y)
            left_edges.append(int(xs[0]))
            right_edges.append(int(xs[-1]))

    if occupied_rows:
        # White plastic has low edge contrast.  Smooth the detected row edges
        # before filling the silhouette so faint lighting noise cannot create a
        # staircase fringe around the composited bottle.
        window = min(15, len(occupied_rows))
        if window % 2 == 0:
            window -= 1
        if window >= 3:
            pad = window // 2
            kernel = np.ones(window, dtype=np.float64) / window
            left_edges = np.rint(
                np.convolve(np.pad(left_edges, pad, mode="edge"), kernel, mode="valid")
            ).astype(int).tolist()
            right_edges = np.rint(
                np.convolve(np.pad(right_edges, pad, mode="edge"), kernel, mode="valid")
            ).astype(int).tolist()

        for y, left, right in zip(occupied_rows, left_edges, right_edges, strict=True):
            mask[y, left : right + 1] = 255

    alpha = Image.fromarray(mask, mode="L")
    if feather > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(radius=feather))
    return alpha


def composite_packshot(
    scene: Image.Image,
    packshot: Image.Image,
    *,
    height: int,
    center_x: int,
    bottom: int,
    threshold: int = 12,
    feather: float = 1.0,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    alpha = packshot_alpha(packshot, threshold=threshold, feather=feather)
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("No product silhouette was found in the packshot.")

    product = packshot.convert("RGBA").crop(bbox)
    product.putalpha(alpha.crop(bbox))
    width = max(1, round(product.width * height / product.height))
    product = product.resize((width, height), Image.Resampling.LANCZOS)

    x = round(center_x - width / 2)
    y = bottom - height
    if x < 0 or y < 0 or x + width > scene.width or y + height > scene.height:
        raise ValueError(
            f"Placement {(x, y, width, height)} is outside scene size {scene.size}."
        )

    output = scene.convert("RGBA")
    output.alpha_composite(product, dest=(x, y))
    return output.convert("RGB"), (x, y, width, height)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scene", type=Path)
    parser.add_argument("packshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--center-x", type=int, required=True)
    parser.add_argument("--bottom", type=int, required=True)
    parser.add_argument("--threshold", type=int, default=12)
    parser.add_argument("--feather", type=float, default=1.0)
    args = parser.parse_args()

    with Image.open(args.scene) as scene_image, Image.open(args.packshot) as packshot_image:
        output, placement = composite_packshot(
            scene_image,
            packshot_image,
            height=args.height,
            center_x=args.center_x,
            bottom=args.bottom,
            threshold=args.threshold,
            feather=args.feather,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.save(args.output, format="PNG")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "placement": {"x": placement[0], "y": placement[1], "width": placement[2], "height": placement[3]},
                "packshot_sha256": sha256_file(args.packshot),
                "operation": "original packshot pixels scaled and alpha-composited",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
