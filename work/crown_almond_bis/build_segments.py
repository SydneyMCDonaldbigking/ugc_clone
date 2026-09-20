"""Compile the approved crown_almond_bis_en shot plan into H3 segment prompts (workflow stage 7).

Hands-only English voice-over. <Picture 1> is the approved keyframe and owns framing, camera angle,
table, hands and where everything sits; <Picture 2> is the product photo listed in READY.json and owns
the packaging. Four 5 s clips, one H3 job (server now allows up to 20 segments; upscale is chunked).
"""

import json
from pathlib import Path

SERVER = "/opt/ugc_clone/jobs/crown_almond_bis"
KEY = f"{SERVER}/keyframes"
INP = f"{SERVER}/inputs"
PIC1 = f"{INP}/ref_pic1.jpg"   # packet / biscuit reference
PIC2 = f"{INP}/ref_pic2.jpg"   # retail box reference

BAN = (
    "No face, head or body appears; only hands and forearms. No subtitles, captions, watermarks, "
    "price tags or any added text. The only printing is the packaging already shown in the references, "
    "kept crisp and never re-lettered, translated or invented. No other products or brands. "
    "No extra fingers, no distorted hands. No morphing, no cuts, no scene change."
)


def seg(keyframe, product, product_role, scene, action, dialogue, sound, extra_ban=""):
    prompt = f"""subject_definitions:
<Picture 1> is the authority for this shot: its framing, camera angle, bright neutral home table, lighting, the hands and where everything sits. {scene}
<Picture 2> is the authority for the packaging: {product_role}

retention_analysis:
<Picture 1>: fully_preserved. The video starts exactly on this frame and keeps its composition, camera height and angle, hands, table, background and light.
<Picture 2>: attribute_transfer. The pack shape, colours and printed front panel carry over and stay legible; its plain studio background does not.

detailed_description:
{action} An off-screen voice speaks over the shot, warm and unhurried, (S1) <d>[English] {dialogue}</d>

soundscape: a clear close-mic English voice-over, {sound}, quiet room tone. No music.

{BAN} {extra_ban}""".strip()
    return {"prompt": prompt, "duration_seconds": 5, "references": [keyframe, product]}


SEGMENTS = [
    seg(f"{KEY}/seg01.png", PIC2,
        "the CROWN Almond Biscuits retail box, its front panel artwork and proportions.",
        "Both hands hold the closed retail box close to the lens in a front three-quarter view over a bright neutral table.",
        "The hands hold the box steady for a beat, then lower it onto the table so it settles squarely in the centre of frame with the front panel facing the lens, while the other hand brings one sealed individual packet forward beside it.",
        "Need a simple snack for the table? Meet Crown Almond Biscuits, ready to share.",
        "a light cardboard rustle as the box is set down",
        "The box front panel stays fully visible and never bends, warps or turns away."),
    seg(f"{KEY}/seg02.png", PIC1,
        "the individual white CROWN packet and the golden rectangular almond biscuits inside it.",
        "Both hands hold one intact sealed packet just above an empty shallow cream plate, the retail box softly out of focus behind.",
        "One hand opens the packet along its seam while the other steadies it, and two or three whole biscuits slide out and settle in the centre of the plate; the opened packet is then eased toward the edge of the frame.",
        "Open the box, pass the little packets around, and set the biscuits in the middle.",
        "a crisp foil-and-paper tear and biscuits settling on the plate",
        "The biscuits stay whole and keep their exact shape and colour; nothing crumbles or multiplies."),
    seg(f"{KEY}/seg03.png", PIC1,
        "the golden rectangular almond biscuit, its surface texture, almond pieces and colour.",
        "Two hands hold one whole biscuit close to the lens; a clear glass of plain milk sits lower right beside a small plate with two more biscuits.",
        "Both thumbs meet at the centre of the biscuit and break it once into two clean halves, and one half then moves calmly toward the rim of the milk glass for a light dip.",
        "Show the golden biscuits up close, then break one open and pair it with milk.",
        "a dry snap as the biscuit breaks",
        "The break is one clean movement; the biscuit never bends, melts or changes colour."),
    seg(f"{KEY}/seg04.png", PIC1,
        "the retail box, the sealed white packets and the golden biscuits.",
        "A high-angle tabletop view: the closed box at the back, two sealed packets beside it, a cream plate of biscuits in the centre and a glass of milk at the right.",
        "One hand slides the sharing plate to the exact centre of the table, then lifts a single biscuit toward the lens and holds it completely still, while the other hand rests near an unopened packet; the phone makes one small push and settles.",
        "Put a few out to share, and come give Crown Almond Biscuits a try.",
        "a soft ceramic scrape as the plate slides",
        "Exactly two sealed packets stay in frame and the count never changes."),
]

out = Path(__file__).parent
(out / "segments.json").write_text(json.dumps(SEGMENTS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(len(SEGMENTS), "segments,", sum(s["duration_seconds"] for s in SEGMENTS), "s")
