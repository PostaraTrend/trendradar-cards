"""
health_card.py — Trend Radar NG · Health & Wellness lane card renderer
Concept: "Clinical Calm" (approved 2 Jul 2026)

Drop-in module for the trendradar-cards Flask service.
Integration (in app.py, inside the /card route):

    from health_card import render_health_card

    if category.upper() == "HEALTH":
        img = render_health_card(headline=headline, source=source,
                                 date=date, platform=platform)  # platform: "fb" | "ig"
        buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
        return send_file(buf, mimetype="image/png")

Fonts required alongside the service (same folder or fonts/ dir):
    Poppins-Bold.ttf, Poppins-SemiBold.ttf, Poppins-Medium.ttf, Poppins-Regular.ttf
"""

import os
from PIL import Image, ImageDraw, ImageFont

# ---------- palette ----------
BG_TOP        = (9, 42, 40)      # deep clinical teal
BG_BOTTOM     = (15, 58, 54)
GREEN         = (46, 204, 143)   # HEALTH lane accent #2ECC8F
GREEN_SOFT    = (126, 231, 189)
TEXT_PRIMARY  = (240, 250, 247)
TEXT_MUTED    = (160, 196, 190)
CHIP_FILL     = (14, 66, 58)

W, H = 1080, 1350
MARGIN = 92

FONT_DIR = os.environ.get("FONT_DIR", os.path.dirname(os.path.abspath(__file__)))

def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    path = os.path.join(FONT_DIR, f"Poppins-{weight}.ttf")
    if not os.path.exists(path):
        path = os.path.join(FONT_DIR, "fonts", f"Poppins-{weight}.ttf")
    return ImageFont.truetype(path, size)

def _wrap(draw, text, font, max_width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def _ecg(draw, y0, x0, x1, color, width):
    """Horizontal ECG pulse line: flat - small dip - tall spike - rebound - flat."""
    pts, x = [], x0
    while x < x1:
        pts.extend([(x, y0), (x + 42, y0), (x + 55, y0 - 15),
                    (x + 68, y0 + 36), (x + 81, y0 - 68),
                    (x + 94, y0 + 23), (x + 107, y0), (x + 158, y0)])
        x += 158
    draw.line(pts, fill=color, width=width, joint="curve")

def render_health_card(headline: str, source: str, date: str,
                       platform: str = "fb") -> Image.Image:
    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)

    # vertical gradient
    for y in range(H):
        t = y / H
        d.line([0, y, W, y], fill=(
            int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
            int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
            int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)))

    # concentric quarter-rings, top-left, very subtle
    for r in range(140, 620, 48):
        d.arc([-r, -r, r, r], 0, 100, fill=(30, 84, 78), width=2)

    # ---------- kicker ----------
    ky = 96
    d.ellipse([MARGIN, ky + 6, MARGIN + 17, ky + 23], fill=GREEN)
    kf = _font("SemiBold", 28)
    d.text((MARGIN + 34, ky), "HEALTH & WELLNESS · NIGERIA", font=kf, fill=GREEN_SOFT)
    df = _font("Medium", 24)
    dw = d.textlength(date, font=df)
    d.text((W - MARGIN - dw, ky + 2), date, font=df, fill=TEXT_MUTED)
    d.rectangle([MARGIN, ky + 48, MARGIN + 74, ky + 54], fill=GREEN)

    # ---------- headline (auto-size 84 -> 64 to fit 5 lines max) ----------
    max_w = W - 2 * MARGIN
    size = 84
    while size >= 64:
        hf = _font("Bold", size)
        lines = _wrap(d, headline, hf, max_w)
        if len(lines) <= 5:
            break
        size -= 4
    line_h = int(size * 1.32)
    hy = 300
    for ln in lines:
        d.text((MARGIN, hy), ln, font=hf, fill=TEXT_PRIMARY)
        hy += line_h

    # ---------- source chip (pill) ----------
    cf = _font("SemiBold", 30)
    chip_text = f"According to {source}"
    cw = d.textlength(chip_text, font=cf)
    cy = 905
    d.rounded_rectangle([MARGIN, cy, MARGIN + cw + 64, cy + 66],
                        radius=33, fill=CHIP_FILL, outline=GREEN, width=2)
    d.text((MARGIN + 32, cy + 15), chip_text, font=cf, fill=TEXT_PRIMARY)

    # ---------- ECG pulse line ----------
    _ecg(d, 1075, -30, W + 40, GREEN, 5)

    # ---------- footer ----------
    footer_left = "fb.com/TrendRadarNG" if platform == "fb" else "@trendradarng"
    ff = _font("SemiBold", 26)
    d.text((MARGIN, 1185), footer_left, font=ff, fill=GREEN_SOFT)
    disc = "Health, curated. Always consult a professional."
    df2 = _font("Regular", 23)
    d.text((MARGIN, 1237), disc, font=df2, fill=TEXT_MUTED)

    return img


if __name__ == "__main__":
    # local test render, both platforms
    for p in ("fb", "ig"):
        card = render_health_card(
            headline="NCDC issues Lassa fever advisory as cases decline in three states",
            source="NCDC", date="2 Jul 2026", platform=p)
        card.save(f"health_card_test_{p}.png")
    print("test cards written")
