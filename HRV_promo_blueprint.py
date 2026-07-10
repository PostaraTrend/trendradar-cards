"""
HRV-promo-blueprint.py — Level Up promo card renderer for Trend Radar NG
Project Harvest (SOP-HRV-001) — endpoint: POST /promo

Canvas: 1080x1350 (4:5). TRNG navy base #0E2841, emerald accent #1DBE84,
Poppins, badge pill, "POWERED BY POSTARATREND" footer strip.

SETUP — the ONLY manual step: register the blueprint in the app factory
(the main file where the other lanes are registered), two lines:
    from HRV_promo_blueprint import promo_bp
    app.register_blueprint(promo_bp)
Save this file in the repo as HRV_promo_blueprint.py (underscores, so the
import line above works as written). Fonts are discovered automatically.
"""

import io
import textwrap
from flask import Blueprint, request, send_file, jsonify
from PIL import Image, ImageDraw, ImageFont

promo_bp = Blueprint("promo", __name__)

# ---- Palette -----------------------------------------------------------
NAVY = (14, 40, 65)          # #0E2841 base
NAVY_DEEP = (10, 27, 46)     # #0A1B2E footer strip
EMERALD = (29, 190, 132)     # #1DBE84 accent
MINT = (143, 235, 201)       # #8FEBC9 small highlights
CLOUD = (234, 242, 247)      # #EAF2F7 body text
MUTED = (159, 179, 196)      # #9FB3C4 secondary

W, H = 1080, 1350

# ---- Fonts (automatic discovery — no editing needed) --------------------
# Search order: PROMO_FONT_DIR env var, ./fonts next to this file, ../fonts,
# common repo layouts, then system font directories. First hit wins.
import os

def _find_font_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("PROMO_FONT_DIR", ""),
        os.path.join(here, "fonts"),
        os.path.join(here, "static", "fonts"),
        os.path.join(here, "assets", "fonts"),
        os.path.join(here, "..", "fonts"),
        "fonts",
        "/usr/share/fonts/truetype/google-fonts",
        "/usr/share/fonts/truetype/poppins",
    ]
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "Poppins-Bold.ttf")):
            return c
    # Last resort: walk the repo tree for Poppins-Bold.ttf
    for root, _dirs, files in os.walk(os.path.join(here, "..")):
        if "Poppins-Bold.ttf" in files:
            return root
    raise OSError("Poppins fonts not found. Set PROMO_FONT_DIR or place Poppins-*.ttf in a fonts/ directory.")

FONT_DIR = _find_font_dir()

def _font(name, size):
    candidates = [name]
    if "SemiBold" in name:
        candidates += ["Poppins-Medium.ttf", "Poppins-Bold.ttf"]
    for c in candidates:
        try:
            return ImageFont.truetype(f"{FONT_DIR}/{c}", size)
        except OSError:
            continue
    raise OSError(f"No usable font found for {name} in {FONT_DIR}")

def _fonts():
    return {
        "badge": _font("Poppins-SemiBold.ttf", 34),
        "headline": _font("Poppins-Bold.ttf", 84),
        "headline_sm": _font("Poppins-Bold.ttf", 68),
        "subline": _font("Poppins-Regular.ttf", 44),
        "cta": _font("Poppins-SemiBold.ttf", 42),
        "brand": _font("Poppins-Bold.ttf", 40),
        "footer": _font("Poppins-SemiBold.ttf", 28),
    }

# ---- Helpers -----------------------------------------------------------

def _wrap(draw, text, font, max_width):
    lines = []
    for chunk in textwrap.wrap(text, width=40):
        if draw.textlength(chunk, font=font) <= max_width:
            lines.append(chunk)
        else:
            words, cur = chunk.split(), ""
            for w_ in words:
                trial = (cur + " " + w_).strip()
                if draw.textlength(trial, font=font) <= max_width:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = w_
            if cur:
                lines.append(cur)
    return lines


def _pill(draw, xy, text, font, fg, bg, pad_x=28, pad_y=14):
    x, y = xy
    tw = draw.textlength(text, font=font)
    th = font.size
    box = [x, y, x + tw + pad_x * 2, y + th + pad_y * 2]
    r = (box[3] - box[1]) // 2
    draw.rounded_rectangle(box, radius=r, fill=bg)
    draw.text((x + pad_x, y + pad_y - 2), text, font=font, fill=fg)
    return box


# ---- Card composition ---------------------------------------------------

def render_promo_card(headline, subline="", badge_text="LEVEL UP", cta_line=""):
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    f = _fonts()
    margin = 72

    # Subtle top rule in emerald
    d.rectangle([0, 0, W, 14], fill=EMERALD)

    # Brand row
    d.text((margin, 58), "TREND", font=f["brand"], fill=CLOUD)
    tw = d.textlength("TREND ", font=f["brand"])
    d.text((margin + tw, 58), "RADAR", font=f["brand"], fill=EMERALD)
    tw2 = d.textlength("TREND RADAR ", font=f["brand"])
    d.text((margin + tw2, 58), "NG", font=f["brand"], fill=CLOUD)

    # Badge pill (top-right)
    badge = (badge_text or "LEVEL UP").upper()
    bw = d.textlength(badge, font=f["badge"]) + 56
    _pill(d, (W - margin - bw, 52), badge, f["badge"], NAVY_DEEP, EMERALD)

    # Headline block (vertically weighted upper-middle)
    hl_font = f["headline"] if len(headline) <= 60 else f["headline_sm"]
    lines = _wrap(d, headline, hl_font, W - margin * 2)
    y = 300
    for ln in lines[:5]:
        d.text((margin, y), ln, font=hl_font, fill=CLOUD)
        y += int(hl_font.size * 1.18)

    # Emerald divider
    y += 26
    d.rectangle([margin, y, margin + 160, y + 10], fill=EMERALD)
    y += 52

    # Subline
    if subline:
        for ln in _wrap(d, subline, f["subline"], W - margin * 2)[:4]:
            d.text((margin, y), ln, font=f["subline"], fill=MUTED)
            y += int(f["subline"].size * 1.35)

    # CTA line above footer
    if cta_line:
        cta_y = H - 320
        for ln in _wrap(d, cta_line, f["cta"], W - margin * 2)[:2]:
            d.text((margin, cta_y), ln, font=f["cta"], fill=MINT)
            cta_y += int(f["cta"].size * 1.3)

    # Footer strip
    d.rectangle([0, H - 130, W, H], fill=NAVY_DEEP)
    d.rectangle([0, H - 130, W, H - 126], fill=EMERALD)
    foot = "POWERED BY POSTARATREND"
    fw = d.textlength(foot, font=f["footer"])
    d.text(((W - fw) / 2, H - 88), foot, font=f["footer"], fill=MUTED)

    return img


# ---- Route --------------------------------------------------------------

@promo_bp.route("/promo", methods=["POST"])
def promo():
    data = request.get_json(silent=True) or {}
    headline = (data.get("headline") or "").strip()
    if not headline:
        return jsonify({"error": "headline is required"}), 400

    img = render_promo_card(
        headline=headline,
        subline=(data.get("subline") or "").strip(),
        badge_text=(data.get("badge_text") or "LEVEL UP").strip(),
        cta_line=(data.get("cta_line") or "").strip(),
    )

    # INTEGRATE (preferred): reuse the shared /host helper so the response
    # returns a hosted JPEG URL like the other lanes, e.g.:
    #     hosted_url = host_image(img)            # existing shared helper
    #     return jsonify({"hosted_url": hosted_url})
    # Fallback below returns the JPEG directly; the Publisher workflow
    # supports either response shape (see HRV-02 Render Card node notes).
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")


# ---- Standalone test mode ------------------------------------------------
# Run `python HRV_promo_blueprint.py` locally to render a sample card to
# promo_test.jpg without starting Flask — useful before pushing.
if __name__ == "__main__":
    card = render_promo_card(
        headline="This page runs itself.",
        subline="Every post on Trend Radar NG is researched, written, designed, and published by one automated system.",
        badge_text="FREE MASTERCLASS",
        cta_line="Free masterclass waitlist now open. Link in comments.",
    )
    card.save("promo_test.jpg", quality=92)
    print("Rendered promo_test.jpg using fonts from:", FONT_DIR)
