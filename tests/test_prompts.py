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
        self.assertIn("supplied product photo as the package identity authority", prompt)
        self.assertNotIn("added there after generation", prompt)
        self.assertLess(len(prompt.split()), 200)
        for noise in ("handle", "forbidden", "Acceptance", "composite area"):
            self.assertNotIn(noise.lower(), prompt.lower())

    def test_reference_lock_still_requests_the_product_itself(self) -> None:
        request = copy.deepcopy(self.request)
        request["segments"]["4"]["product_fidelity_mode"] = "reference_lock"
        prompt = render_keyframe_prompt(
            product=self.product,
            shot_plan=self.shot_plan,
            request=request,
            keyframe_id="4",
            template_text=self.template,
        )
        self.assertIn("Product: a2 Milk Full Cream 2L, copied exactly", prompt)
        self.assertNotIn("Product composite area", prompt)

    def test_product_absent_keyframe_omits_product_reference_and_instruction(self) -> None:
        request = copy.deepcopy(self.request)
        segment = request["segments"]["4"]
        segment["product_presence"] = "absent"
        segment["product_fidelity_mode"] = "not_applicable"
        segment.pop("product_placement", None)
        product_paths = [
            path for path, role in segment["reference_roles"].items() if role == "product_identity"
        ]
        segment["references"] = [path for path in segment["references"] if path not in product_paths]
        segment["reference_roles"] = {
            path: role for path, role in segment["reference_roles"].items() if path not in product_paths
        }

        prompt = render_keyframe_prompt(
            product=self.product,
            shot_plan=self.shot_plan,
            request=request,
            keyframe_id="4",
            template_text=self.template,
        )

        self.assertIn("retail package is outside this shot", prompt)
        self.assertNotIn("copied exactly", prompt)
        self.assertNotIn("the product.", prompt)

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

    def test_scene_pack_view_and_structured_lock_are_injected(self) -> None:
        request = copy.deepcopy(self.request)
        segment = request["segments"]["4"]
        scene_path = "inputs/a2_test/presenter.jpg"
        segment["references"].append(scene_path)
        segment["reference_roles"][scene_path] = "scene_identity"
        segment["scene_lock"] = {
            "setting": "A bright compact home kitchen.",
            "surface": "Pale matte natural wood.",
            "backdrop": "Warm-white cabinetry with restrained decor.",
            "lighting": "Soft daylight from camera left.",
            "palette": "Warm ivory, pale wood and white.",
            "fixed_props": "One warm-ivory ceramic plate.",
        }

        prompt = render_keyframe_prompt(
            product=self.product,
            shot_plan=self.shot_plan,
            request=request,
            keyframe_id="4",
            template_text=self.template,
        )

        self.assertIn("approved empty scene master", prompt)
        self.assertIn("surface: Pale matte natural wood", prompt)
        self.assertIn("lighting: Soft daylight from camera left", prompt)
        self.assertIn("background bokeh", prompt)


if __name__ == "__main__":
    unittest.main()
