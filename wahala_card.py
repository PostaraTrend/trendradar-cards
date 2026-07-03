"""
Wahala Watch card renderer — drop-in module for the trendradar-cards Flask service.

Install: place this file as wahala_card.py in the repo, then in app.py:
    from wahala_card import wahala_bp
    app.register_blueprint(wahala_bp)

Endpoint:
    POST /render/wahala
    JSON body: { "headline": str, "body": str, "stage": str, "source_line": str }
    Returns:   { "image_url": "<public URL of rendered PNG>" }

Adjust FONT paths and the save/upload block to match how the existing lane
renderers in this repo persist and serve images (same pattern as the other lanes).
"""
import io, os, math, random, textwrap, uuid
from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFilter, ImageFont

wahala_bp = Blueprint("wahala", __name__)

W, H = 1080, 1350  # 4:5 photo post per TRNG publishing rules
NAVY_TOP, NAVY_MID, NAVY_BOT = (6, 18, 38), (10, 33, 62), (13, 43, 80)
WHITE, AMBER, SKY, MUTE = (255, 255, 255), (245, 182, 46), (126, 196, 238), (200, 220, 240)

FONT_DIR = os.environ.get("FONT_DIR", "/usr/share/fonts/truetype/google-fonts")
def F(name, size): return ImageFont.truetype(os.path.join(FONT_DIR, name), size)

STAGE_CHIP = {
    "ACCUSED":        "ALLEGATION — NOT PROVEN",
    "ARRESTED":       "ARRESTED — NOT CONVICTED",
    "CHARGED":        "CHARGED — NOT CONVICTED",
    "ON_TRIAL":       "ON TRIAL — NOT CONVICTED",
    "CONVICTED":      "CONVICTED BY A COURT",
    "OFFICIAL_PROBE": "OFFICIAL PROBE — NOT A CONVICTION",
    "PUBLIC_DISPUTE": "PUBLIC DISPUTE — CLAIMS ON BOTH SIDES",
}

def _background(seed=None):
    base = Image.new("RGB", (W, H))
    px = base.load()
    for y in range(H):
        f = y / H
        if f < 0.55:
            g = f / 0.55
            c = tuple(int(NAVY_TOP[i] + (NAVY_MID[i] - NAVY_TOP[i]) * g) for i in range(3))
        else:
            g = (f - 0.55) / 0.45
            c = tuple(int(NAVY_MID[i] + (NAVY_BOT[i] - NAVY_MID[i]) * g) for i in range(3))
        for x in range(W):
            px[x, y] = c
    rnd = random.Random(seed or 7)
    d = ImageDraw.Draw(base, "RGBA")
    for _ in range(300):
        x, y = rnd.randrange(W), rnd.randrange(H)
        r = rnd.choice([1, 1, 1, 2, 2, 3])
        d.ellipse([x - r, y - r, x + r, y + r],
                  fill=rnd.choice([(255, 255, 255), (200, 225, 250), (170, 210, 245)]) + (rnd.randint(60, 200),))
    return base.convert("RGBA")

def render_wahala_card(headline: str, body: str, stage: str, source_line: str) -> Image.Image:
    img = _background()
    d = ImageDraw.Draw(img, "RGBA")
    cx = W // 2

    # Kicker
    d.text((cx, 120), "WAHALA WATCH", font=F("Poppins-Bold.ttf", 58), fill=AMBER, anchor="mm")
    d.line([cx - 120, 168, cx + 120, 168], fill=AMBER, width=4)

    # Headline — wrap to max 4 lines, autosize
    size = 80
    while size > 52:
        fh = F("Poppins-Bold.ttf", size)
        lines = textwrap.wrap(headline.upper(), width=int(26 * 76 / size))
        if len(lines) <= 4 and all(d.textlength(l, font=fh) <= W - 120 for l in lines):
            break
        size -= 4
    y = 300
    for ln in lines[:4]:
        d.text((cx, y), ln, font=fh, fill=WHITE, anchor="mm")
        y += int(size * 1.28)

    # Body — wrap to max 3 lines
    fb = F("Poppins-Medium.ttf", 44)
    y += 36
    for ln in textwrap.wrap(body, width=44)[:3]:
        d.text((cx, y), ln, font=fb, fill=MUTE, anchor="mm")
        y += 60

    # Claim-stage chip (legal honesty device — always rendered)
    chip = STAGE_CHIP.get(stage, "ALLEGATION — NOT PROVEN")
    fc = F("Poppins-Medium.ttf", 36)
    tw = d.textlength(chip, font=fc)
    d.rounded_rectangle([cx - tw / 2 - 36, y + 24, cx + tw / 2 + 36, y + 96],
                        radius=36, outline=SKY, width=4)
    d.text((cx, y + 60), chip, font=fc, fill=SKY, anchor="mm")

    # Source line (mandatory)
    d.text((cx, H - 220), source_line, font=F("Poppins-Bold.ttf", 40), fill=AMBER, anchor="mm")

    # Footer
    d.text((70, H - 90), "fb.com/TrendRadarNG", font=F("Poppins-Bold.ttf", 36), fill=SKY, anchor="lm")
    d.text((W - 70, H - 90), "Nigeria, curated.", font=F("Poppins-Regular.ttf", 36),
           fill=(200, 215, 235), anchor="rm")
    return img.convert("RGB")

@wahala_bp.route("/render/wahala", methods=["POST"])
def render_endpoint():
    data = request.get_json(force=True)
    for key in ("headline", "body", "stage", "source_line"):
        if not data.get(key):
            return jsonify({"error": f"missing field: {key}"}), 400
    # Refuse contractions on the card face (style rule enforcement at the last line of defense)
    import re
    if re.search(r"\b\w+'(s|t|re|ve|ll|d|m)\b", data["headline"] + " " + data["body"]):
        return jsonify({"error": "contraction detected in card text"}), 422

    img = render_wahala_card(data["headline"], data["body"], data["stage"], data["source_line"])

    # ---- PERSIST: replace this block with the same storage pattern the other
    # ---- lane renderers in this repo use (static dir + public URL, or S3, etc.)
    fname = f"wahala_{uuid.uuid4().hex[:12]}.png"
    outdir = os.environ.get("CARD_OUTPUT_DIR", "static/cards")
    os.makedirs(outdir, exist_ok=True)
    img.save(os.path.join(outdir, fname), "PNG")
    base_url = os.environ.get("PUBLIC_BASE_URL", "https://PASTE_CARD_SERVICE.onrender.com")
    return jsonify({"image_url": f"{base_url}/{outdir}/{fname}"})
