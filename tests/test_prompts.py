from __future__ import annotations

import copy
import unittest
from pathlib import Path

from ugc_pipeline.io import load_json
from ugc_pipeline.prompts import load_template, render_keyframe_prompt


ROOT = Path(__file__).resolve().parents[1]


class PromptCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.product = load_json(ROOT / "inputs/a2_test/product.en.json")
        self.shot_plan = load_json(ROOT / "work/a2_test/variants/v001/shot_plan.json")
        self.request = load_json(ROOT / "work/a2_test/keyframes/REQUEST.json")
        self.template = load_template(ROOT / "templates/keyframe_prompt.en.txt")

    def test_template_is_product_agnostic(self) -> None:
        lower = self.template.lower()
        for hard_coded_term in ("a2", "milk", "bottle", "groove", "handle"):
            self.assertNotIn(hard_coded_term, lower)

    def test_product_contract_is_injected(self) -> None:
        prompt = render_keyframe_prompt(
            product=self.product,
            shot_plan=self.shot_plan,
            request=self.request,
            keyframe_id="4",
            template_text=self.template,
        )
        self.assertIn("a2 Milk Full Cream 2L", prompt)
        self.assertIn("Copy the label as-is", prompt)
        self.assertLess(len(prompt.split()), 200)
        for noise in ("handle", "forbidden", "composited", "Acceptance"):
            self.assertNotIn(noise.lower(), prompt.lower())
        self.assertNotIn("composited", prompt)
        self.assertIn("Image 2: the product.", prompt)

    def test_same_template_accepts_another_package_type(self) -> None:
        product = copy.deepcopy(self.product)
        product["name"] = "Example Skin Serum"
        product["visual_identity"] = {
            "packaging_type": "amber glass dropper vial",
            "silhouette": "small cylindrical vial",
            "closure": "black rubber dropper",
            "grip_geometry": "smooth round wall",
            "handle": "none",
            "front_label": "cream paper label",
            "back_label": "small ingredients label",
            "forbidden_features": ["pump dispenser", "plastic jar"],
        }
        prompt = render_keyframe_prompt(
            product=product,
            shot_plan=self.shot_plan,
            request=self.request,
            keyframe_id="4",
            template_text=self.template,
        )
        self.assertIn("amber glass dropper vial", prompt)
        self.assertNotIn("pump dispenser", prompt)  # forbidden features stay in QC, not in the prompt


if __name__ == "__main__":
    unittest.main()
