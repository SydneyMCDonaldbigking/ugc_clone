import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.composite_product_packshot import composite_packshot


class CompositePackshotTests(unittest.TestCase):
    def test_original_product_pixels_replace_generated_scene(self) -> None:
        scene = Image.new("RGB", (100, 160), (40, 80, 120))
        packshot = Image.new("RGB", (50, 80), "white")
        draw = ImageDraw.Draw(packshot)
        draw.rectangle((10, 10, 39, 69), fill=(230, 225, 210))
        draw.rectangle((15, 35, 34, 50), fill=(12, 90, 180))

        output, placement = composite_packshot(
            scene, packshot, height=60, center_x=50, bottom=120, feather=0
        )

        self.assertEqual(placement, (35, 60, 30, 60))
        self.assertEqual(output.getpixel((50, 100)), (12, 90, 180))
        self.assertEqual(output.getpixel((5, 5)), (40, 80, 120))


if __name__ == "__main__":
    unittest.main()
