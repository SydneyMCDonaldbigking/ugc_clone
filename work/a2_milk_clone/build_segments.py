"""Compile the approved a2_milk_clone_en shot plan into H3 segment prompts (workflow stage 7).

Hands-only English voice-over: the keyframe is <Picture 1> and owns composition, scene, hands and the
product's placement; the product photo is <Picture 2> and owns the package. Dialogue is off-screen.
Six clips are split into two H3 jobs to respect the 20 s / 4 segment limit.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = "/opt/ugc_clone/jobs/a2_milk_clone"
KEY = f"{SERVER}/keyframes"
INP = f"{SERVER}/inputs"

FRONT = f"{INP}/target_A2_1.png"
BACK = f"{INP}/target_A2_2.png"

COMMON_BAN = (
    "No face, head or body appears; only hands and forearms. No subtitles, captions, watermarks, "
    "price tags or any added text. The only printing is the label already shown in the references, "
    "kept crisp and never re-lettered or invented. No other products, bottles, cartons or brands. "
    "No extra fingers, no distorted hands. No morphing, no cuts, no scene change."
)

def seg(keyframe, product, product_role, scene, action, dialogue, sound, duration, extra_ban=""):
    prompt = f"""subject_definitions:
<Picture 1> is the authority for this shot: its framing, camera angle, dim warm desk, lighting, the hands and where the product sits. {scene}
<Picture 2> is the authority for the product itself: the 2-litre white plastic a2 bottle with its wide ribbed blue screw cap and its printed label.

retention_analysis:
<Picture 1>: fully_preserved. The video starts exactly on this frame and keeps its composition, camera height and angle, hands, desk, background and light.
<Picture 2>: {product_role}

detailed_description:
{action} An off-screen voice speaks over the shot, unhurried and factual, (S1) <d>[English] {dialogue}</d>

soundscape: a clear close-mic English voice-over, {sound}, quiet room tone. No music.

{COMMON_BAN} {extra_ban}""".strip()
    return {"prompt": prompt, "duration_seconds": duration, "references": [keyframe, product]}


JOB_A = [
    seg(f"{KEY}/seg01.png", FRONT,
        "attribute_transfer. The bottle shape, blue cap and the green front label with the purple a2 roundel carry over and stay legible; its plain white studio background does not.",
        "One hand holds the chilled bottle close to the lens, front label square to the camera, a blurred laptop keyboard below.",
        "Held at the same first-person angle, the hand makes one small handheld settle and the fingertips turn the bottle a few millimetres until the front label is perfectly square to the lens; condensation stays on the plastic.",
        "Full cream milk, naturally A1 protein free.",
        "a faint plastic creak from the grip", 3,
        "The bottle never tilts, rotates to another side or leaves the hand."),
    seg(f"{KEY}/seg01b.png", FRONT,
        "attribute_transfer. The bottle shape, blue cap and green front label carry over; its white background does not.",
        "One hand holds an empty clear glass low in frame; the other holds the uncapped bottle upright just above it.",
        "After this frame the upper hand lifts and tilts the bottle into one continuous, smooth stream of white milk that fills the glass about halfway; the glass stays steady in the lower hand.",
        "Look at that smooth, steady pour.",
        "the gentle glug of milk pouring into glass", 2,
        "The stream is continuous and never splashes or spills outside the glass; the milk level only rises."),
    seg(f"{KEY}/seg02.png", FRONT,
        "attribute_transfer. The bottle shape, blue cap and green front label carry over on every bottle; the white studio background does not.",
        "A directly overhead view into an open plain cardboard box holding exactly six bottles, both hands on the box edges.",
        "Both hands release the box flaps and sweep once across the two rows of three so the full count reads clearly; the box and the bottles stay exactly where they are.",
        "Six bottles per case.",
        "a light rustle of cardboard", 2,
        "Exactly six bottles, the count never changes, none of them tips over."),
    seg(f"{KEY}/seg02b.png", BACK,
        "fully_preserved. Keep the back label exactly as shown - its purple heading, the two cow illustrations, the nutrition table, the barcode and every line of small print - crisp and never garbled, re-lettered, translated or invented.",
        "Both hands hold the bottle close to the lens with the back label square to the camera, fingertips only at the side edges.",
        "The bottle stays completely still and square to the lens while the camera makes one subtle handheld push toward the ingredient lines; the label text stays sharp the whole time.",
        "Check the panel: only milk, with no additives or permeate.",
        "a faint plastic creak from the grip", 3,
        "The label never blurs, warps or changes."),
]

JOB_B = [
    seg(f"{KEY}/seg03.png", FRONT,
        "attribute_transfer. The bottle shape, blue cap and green front label carry over; its white background does not.",
        "One hand holds the bottle close to the lens with the front label facing the camera; the other holds an empty clear glass lower in frame.",
        "After this frame the hand lifts the bottle, brings it to a controlled pouring angle and completes one clean, steady pour into the glass, which stays planted on the desk; as the glass reaches its level the wrist begins returning the bottle upright.",
        "Per one hundred millilitres, it has three point three grams of protein.",
        "the gentle glug of milk pouring into glass", 5,
        "The stream is continuous and never splashes or spills outside the glass; the milk level only rises."),
    seg(f"{KEY}/seg04.png", FRONT,
        "attribute_transfer. The bottle shape, blue cap and green front label with the visible 2L mark carry over; its white background does not.",
        "A high-angle view of the dim warm desk: the bottle upright with its front label to the camera, a filled glass of milk beside it and a plain cardboard box behind.",
        "The bottle stays upright and still while one hand gently slides the filled glass into its final position beside it, then releases and leaves the frame; the phone makes one subtle handheld push and settles completely still for the last second.",
        "Each bottle is two litres, about eight serves, and costs six dollars seventy-nine.",
        "a soft glass-on-timber tap as the glass settles", 5,
        "Nothing spills; the bottle never tips or slides."),
]

out = Path(__file__).parent
(out / "segments.jobA.json").write_text(json.dumps(JOB_A, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(out / "segments.jobB.json").write_text(json.dumps(JOB_B, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("A", sum(s["duration_seconds"] for s in JOB_A), "s /", len(JOB_A), "segments")
print("B", sum(s["duration_seconds"] for s in JOB_B), "s /", len(JOB_B), "segments")
