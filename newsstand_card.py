"""
TRNG News Stand card layout — add to the trendradar-cards Flask service.

Endpoint: POST /render/newsstand
Body (JSON): {
  "badge": "WEATHER ALERT",
  "location_line": "Lagos, Nigeria",
  "report_text": "Heavy rainfall is expected in Lagos today...",
  "timestamp_display": "Thursday, 2 July 2026 \u2014 6:00 AM WAT",
  "footer_text": "WEATHER WATCH \u2022 TREND RADAR NG"   # or "EYEWITNESS REPORT \u2022 TREND RADAR NG"
}
Returns: image/png, 1080 x 1350 (4:5 photo post)

Register in your app factory / main module:
    from newsstand_card import newsstand_bp
    app.register_blueprint(newsstand_bp)
"""

import io
import json as _json
from flask import Blueprint, request, send_file, jsonify
from PIL import Image, ImageDraw, ImageFont

newsstand_bp = Blueprint("newsstand", __name__)


def _body(req):
    """Defensive body parsing — matches the _source() pattern in app.py,
    because n8n sometimes posts JSON that Flask does not auto-parse."""
    data = req.get_json(silent=True)
    if isinstance(data, dict):
        return data
    raw = req.get_data(as_text=True) or ""
    if raw.strip():
        try:
            parsed = _json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return req.values

# ---- Canvas + palette -------------------------------------------------------
W, H = 1080, 1350
NAVY = (14, 40, 65)          # #0E2841 house navy
NAVY_DEEP = (9, 28, 47)
AMBER = (245, 158, 11)       # #F59E0B News Stand lane accent
WHITE = (255, 255, 255)
BODY_TINT = (225, 233, 240)
MUTED = (170, 185, 200)

# ---- Fonts: Poppins first (house font), DejaVu fallback ---------------------
FONT_CANDIDATES = {
    "bold": [
        "fonts/Poppins-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "regular": [
        "fonts/Poppins-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}

def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES[kind]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()

def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        test = (cur + " " + w_).strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = w_
    lines.append(cur)
    return lines

# ---- Endpoint ----------------------------------------------------------------
@newsstand_bp.route("/render/newsstand", methods=["POST"])
def render_newsstand():
    p = _body(request)
    badge = (p.get("badge") or "NEWS STAND").upper()[:20]
    location_line = (p.get("location_line") or "")[:40]
    report_text = (p.get("report_text") or "")[:280]
    timestamp_display = p.get("timestamp_display") or ""
    footer_text = p.get("footer_text") or "EYEWITNESS REPORT \u2022 TREND RADAR NG"

    if not report_text or not location_line:
        return jsonify({"error": "location_line and report_text are required"}), 400

    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)

    # Subtle vertical gradient (navy -> deep navy)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(
            int(NAVY[c] + (NAVY_DEEP[c] - NAVY[c]) * t) for c in range(3)
        ))

    f_badge = _font("bold", 40)
    f_loc = _font("bold", 66)
    f_body = _font("regular", 50)
    f_time = _font("regular", 36)
    f_footer = _font("bold", 38)
    f_logo = _font("bold", 44)

    M = 80  # outer margin

    # Badge pill (amber)
    bb = d.textbbox((0, 0), badge, font=f_badge)
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    px, py = 36, 22
    d.rounded_rectangle([M, M, M + bw + 2 * px, M + bh + 2 * py], radius=16, fill=AMBER)
    d.text((M + px, M + py - bb[1]), badge, font=f_badge, fill=NAVY_DEEP)

    # Location line (auto-shrink if it would overflow)
    loc_y = M + bh + 2 * py + 60
    loc_font = f_loc
    while d.textlength(location_line, font=loc_font) > W - 2 * M and loc_font.size > 40:
        loc_font = _font("bold", loc_font.size - 4)
    d.text((M, loc_y), location_line, font=loc_font, fill=WHITE)

    # Amber rule
    rule_y = loc_y + loc_font.size + 34
    d.rectangle([M, rule_y, M + 140, rule_y + 8], fill=AMBER)

    # Body text
    body_y = rule_y + 70
    for line in _wrap(d, report_text, f_body, W - 2 * M):
        d.text((M, body_y), line, font=f_body, fill=BODY_TINT)
        body_y += 74

    # Timestamp
    if timestamp_display:
        d.text((M, body_y + 40), timestamp_display, font=f_time, fill=MUTED)

    # Footer strip with amber rule above it
    strip_h = 130
    d.rectangle([0, H - strip_h - 10, W, H - strip_h], fill=AMBER)
    d.rectangle([0, H - strip_h, W, H], fill=NAVY_DEEP)
    fb2 = d.textbbox((0, 0), footer_text, font=f_footer)
    d.text(
        ((W - (fb2[2] - fb2[0])) / 2,
         H - strip_h + (strip_h - (fb2[3] - fb2[1])) / 2 - fb2[1]),
        footer_text, font=f_footer, fill=WHITE,
    )

    # TRNG mark bottom-right (swap for logo asset paste when ready)
    logo = "TRNG"
    lb = d.textbbox((0, 0), logo, font=f_logo)
    lw, lh = lb[2] - lb[0], lb[3] - lb[1]
    lx, ly = W - M - lw - 40, H - strip_h - 10 - lh - 60
    d.rounded_rectangle([lx - 20, ly - 14, lx + lw + 20, ly + lh + 14],
                        radius=12, outline=AMBER, width=4)
    d.text((lx, ly - lb[1]), logo, font=f_logo, fill=AMBER)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name="newsstand_card.png")
