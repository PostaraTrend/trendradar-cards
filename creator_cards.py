"""
TRNG Creator Tips card renderer — creator_cards.py
Blueprint: creator_bp
Route: GET /render/creator-card
Params:
    pill      - pill text, e.g. CREATOR TIPS or TOOL SPOTLIGHT
    tip_no    - top-right label, e.g. TIP 001 or TOOL 005
    headline  - main statement (auto-sized, wrapped)
    body      - supporting line (wrapped)
    v         - optional cache buster, ignored
Returns: 1080x1080 JPEG (Instagram media containers require JPEG)

Register in app.py:
    from creator_cards import creator_bp
    app.register_blueprint(creator_bp)
"""

import io
import os
from flask import Blueprint, request, send_file
from PIL import Image, ImageDraw, ImageFont

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

creator_bp = Blueprint("creator_cards", __name__)

# --- PostaraTrend brand ---
NAVY = "#183868"
EMERALD = "#18A070"
EMERALD_DARK = "#04342C"
MINT = "#9FE1CB"
TEAL = "#308888"
WHITE = "#FFFFFF"

W = H = 1080
MARGIN = 70

# Bundled fonts first (fonts/ directory beside this module), then system paths.
FONT_CANDIDATES_BOLD = [
    os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
FONT_CANDIDATES_REG = [
    os.path.join(_FONT_DIR, "DejaVuSans.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _font(candidates, size):
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw, text, font, max_width):
    """Greedy word wrap to pixel width."""
    words = text.split()
    lines, line = [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit_headline(draw, text, max_width, max_height):
    """Shrink headline font until the wrapped block fits."""
    for size in range(78, 39, -4):
        font = _font(FONT_CANDIDATES_BOLD, size)
        lines = _wrap(draw, text, font, max_width)
        line_h = int(size * 1.28)
        if len(lines) * line_h <= max_height:
            return font, lines, line_h
    font = _font(FONT_CANDIDATES_BOLD, 40)
    return font, _wrap(draw, text, font, max_width), int(40 * 1.28)


@creator_bp.route("/render/creator-card")
def render_creator_card():
    # Length caps: this is a public endpoint, and no legitimate tip exceeds these.
    pill = request.args.get("pill", "CREATOR TIPS").upper()[:24]
    tip_no = request.args.get("tip_no", "").upper()[:12]
    headline = request.args.get("headline", "").strip()[:160]
    body = request.args.get("body", "").strip()[:320]

    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)

    # --- Header: pill left, tip number right ---
    pill_font = _font(FONT_CANDIDATES_BOLD, 30)
    pad_x, pad_y = 26, 14
    pw = d.textlength(pill, font=pill_font)
    d.rounded_rectangle(
        [MARGIN, MARGIN, MARGIN + pw + 2 * pad_x, MARGIN + 30 + 2 * pad_y],
        radius=10, fill=EMERALD,
    )
    d.text((MARGIN + pad_x, MARGIN + pad_y - 2), pill, font=pill_font, fill=EMERALD_DARK)

    if tip_no:
        no_font = _font(FONT_CANDIDATES_BOLD, 30)
        nw = d.textlength(tip_no, font=no_font)
        d.text((W - MARGIN - nw, MARGIN + pad_y - 2), tip_no, font=no_font, fill=MINT)

    # --- Footer: rule, site, brand ---
    foot_font = _font(FONT_CANDIDATES_BOLD, 34)
    brand_font = _font(FONT_CANDIDATES_REG, 26)
    foot_y = H - MARGIN - 44
    d.line([MARGIN, foot_y - 30, W - MARGIN, foot_y - 30], fill=TEAL, width=3)
    d.text((MARGIN, foot_y), "postaratrend.ca", font=foot_font, fill=WHITE)
    bw = d.textlength("Trend Radar NG", font=brand_font)
    d.text((W - MARGIN - bw, foot_y + 6), "Trend Radar NG", font=brand_font, fill=MINT)

    # --- Content block, vertically centered between header and footer ---
    max_text_w = W - 2 * MARGIN
    top_bound = MARGIN + 110
    bottom_bound = foot_y - 70
    zone_h = bottom_bound - top_bound

    h_font, h_lines, h_line_h = _fit_headline(d, headline, max_text_w, int(zone_h * 0.62))
    b_font = _font(FONT_CANDIDATES_REG, 36)
    b_lines = _wrap(d, body, b_font, max_text_w)
    b_line_h = int(36 * 1.5)

    block_h = len(h_lines) * h_line_h + (34 if body else 0) + len(b_lines) * b_line_h
    y = top_bound + max(0, (zone_h - block_h) // 2)

    for line in h_lines:
        d.text((MARGIN, y), line, font=h_font, fill=WHITE)
        y += h_line_h
    y += 34
    for line in b_lines:
        d.text((MARGIN, y), line, font=b_font, fill=MINT)
        y += b_line_h

    buf = io.BytesIO()
    # JPEG, not PNG: the Instagram media container endpoint accepts JPEG only,
    # and Facebook accepts JPEG too, so one format serves both branches.
    img.save(buf, format="JPEG", quality=92)
    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")
