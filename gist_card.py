"""
Gist Machine lane card — Trend Radar NG
GET/POST /render/gist -> binary PNG (default) or JPEG with format=jpg
GET /render/gist/health -> {"status": "ok"}

The gist lane wears its own outfit: deep plum with hot coral and gold —
warm, playful, unmistakably NOT the navy news card. 4:5 photo post.

Expected query params (GET) or JSON body (POST):
  headline   (required)  Pidgin headline, max ~120 chars recommended
  badge      (optional)  format chip: GIST | TORI | AMEBO CORNER | MAKE WE TALK (default GIST)
  date       (optional)  e.g. "14 Jul 2026"
  handle     (optional)  default fb.com/TrendRadarNG

No contraction gate on this route: the lane writes Nigerian Pidgin, which
has its own norms — the English house rule does not apply here.

Register in app.py, next to the other lanes:
    from gist_card import gist_bp
    app.register_blueprint(gist_bp)
"""
from io import BytesIO
from datetime import datetime

from flask import Blueprint, request, send_file, Response
from PIL import Image, ImageDraw, ImageFont

gist_bp = Blueprint("gist", __name__)

W, H = 1080, 1350  # 4:5 photo post
PLUM = (43, 15, 46)            # deep plum background
PLUM_LIGHT = (66, 25, 70)      # panel tint
CORAL = (255, 94, 91)          # hot coral — the gist color
GOLD = (240, 180, 41)          # house gold accent
CREAM = (255, 244, 234)        # warm headline white
SOFT = (222, 189, 214)         # muted plum-tinted body text
MARGIN = 80
SAFE_W = W - 2 * MARGIN

FONT_CANDIDATES = {
    "bold": ["Poppins-Bold.ttf", "fonts/Poppins-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "medium": ["Poppins-Medium.ttf", "fonts/Poppins-Medium.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "regular": ["Poppins-Regular.ttf", "fonts/Poppins-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}

BADGES = {"GIST", "TORI", "AMEBO CORNER", "MAKE WE TALK"}


def _font(kind, size):
    for path in FONT_CANDIDATES[kind]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_px(d, text, font, max_w, max_lines=None):
    words = str(text).split()
    lines, cur = [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and d.textlength(last + " …", font=font) > max_w:
            last = last[:-1].rstrip()
        lines[-1] = (last + " …") if last else "…"
    return lines


def _src(req):
    if req.method == "POST":
        body = req.get_json(silent=True) or {}
        merged = dict(req.args)
        merged.update({k: v for k, v in body.items() if v is not None})
        return merged
    return dict(req.args)


def build_gist_card(headline, badge, date_label, handle):
    img = Image.new("RGB", (W, H), PLUM)
    d = ImageDraw.Draw(img)

    # coral corner wedge, top-right — the lane's signature shape
    d.polygon([(W, 0), (W - 340, 0), (W, 340)], fill=CORAL)
    d.polygon([(W, 0), (W - 250, 0), (W, 250)], fill=PLUM_LIGHT)
    d.polygon([(W, 0), (W - 165, 0), (W, 165)], fill=GOLD)

    # masthead
    y = 96
    d.text((MARGIN, y), "GIST \u2022 NAIJA", font=_font("bold", 44), fill=CORAL)
    y += 66
    d.rounded_rectangle([MARGIN, y, MARGIN + 150, y + 10], radius=5, fill=GOLD)
    y += 52

    # format badge chip
    f_badge = _font("bold", 34)
    pad_x, pad_y = 26, 14
    bw = d.textlength(badge, font=f_badge)
    d.rounded_rectangle([MARGIN, y, MARGIN + bw + 2 * pad_x, y + 34 + 2 * pad_y],
                        radius=14, fill=CORAL)
    d.text((MARGIN + pad_x, y + pad_y), badge, font=f_badge, fill=PLUM)
    if date_label:
        d.text((W - MARGIN - d.textlength(date_label, font=_font("regular", 30)),
                y + pad_y + 4), date_label, font=_font("regular", 30), fill=SOFT)
    y += 34 + 2 * pad_y + 64

    # headline — autoscale until it fits the stage
    stage_bottom = H - 300
    t_size = 96
    while t_size >= 54:
        f_title = _font("bold", t_size)
        lines = _wrap_px(d, headline, f_title, SAFE_W, max_lines=6)
        line_h = int(t_size * 1.18)
        if y + len(lines) * line_h <= stage_bottom:
            break
        t_size -= 6
    for line in lines:
        d.text((MARGIN, y), line, font=f_title, fill=CREAM)
        y += line_h

    # playful dotted divider under the headline
    y += 34
    dot_x = MARGIN
    for i in range(9):
        color = CORAL if i % 3 else GOLD
        d.ellipse([dot_x, y, dot_x + 14, y + 14], fill=color)
        dot_x += 34

    # tagline
    d.text((MARGIN, y + 44), "Sharp gist, no wound anybody.",
           font=_font("medium", 34), fill=SOFT)

    # footer bar
    fy = H - 150
    d.rectangle([0, fy, W, H], fill=PLUM_LIGHT)
    d.rectangle([0, fy, W, fy + 6], fill=CORAL)
    d.text((MARGIN, fy + 52), handle, font=_font("medium", 34), fill=GOLD)
    right = "Naija gist, curated."
    d.text((W - MARGIN - d.textlength(right, font=_font("regular", 32)), fy + 54),
           right, font=_font("regular", 32), fill=SOFT)
    return img


@gist_bp.route("/render/gist", methods=["GET", "POST"])
def gist():
    src = _src(request)
    headline = (src.get("headline") or "").strip()
    if not headline:
        return Response('{"error": "headline is required"}', status=400,
                        mimetype="application/json")
    badge = (src.get("badge") or "GIST").strip().upper()
    if badge not in BADGES:
        badge = "GIST"
    date_label = (src.get("date") or datetime.utcnow().strftime("%-d %b %Y")).strip()
    handle = (src.get("handle") or "fb.com/TrendRadarNG").strip()

    img = build_gist_card(headline[:180], badge, date_label, handle)
    fmt = (src.get("format") or "").lower()
    buf = BytesIO()
    if fmt == "jpg":
        img.convert("RGB").save(buf, "JPEG", quality=90)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg",
                         download_name="gist_card.jpg")
    img.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name="gist_card.png")


@gist_bp.route("/render/gist/health", methods=["GET"])
def gist_health():
    return Response('{"status": "ok"}', mimetype="application/json")
