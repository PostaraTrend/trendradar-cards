"""
Mama's Kitchen card renderer - TRNG lane blueprint
Endpoint: POST /mk/card
Register in app.py:  from mamas_kitchen_cards import mk_bp ; app.register_blueprint(mk_bp)
Render service notes: WEB_CONCURRENCY=1. A 404 after clean gunicorn boot means
this blueprint was not registered in app.py.
"""

import io
import requests
from flask import Blueprint, request, send_file, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageOps

mk_bp = Blueprint("mk", __name__, url_prefix="/mk")

CARD_W, CARD_H = 1080, 1350
PHOTO_H = 830

CREAM = (250, 238, 218)
BROWN_DEEP = (99, 56, 6)
BROWN_TEXT = (65, 36, 2)
AMBER_SOFT = (250, 199, 117)
AMBER_MID = (186, 117, 23)
GREEN_BADGE = (39, 80, 10)
GREEN_BADGE_TEXT = (234, 243, 222)
GOLD_BADGE = (252, 209, 22)
GOLD_BADGE_TEXT = (61, 42, 2)
SLATE_BADGE = (68, 68, 65)
SLATE_BADGE_TEXT = (241, 239, 232)

FONT_DIR = "/usr/share/fonts/truetype/dejavu"

def _font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(f"{FONT_DIR}/{name}", size)
    except OSError:
        return ImageFont.load_default()

def _fetch_image(url):
    resp = requests.get(url, timeout=25, headers={"User-Agent": "TRNG-MamasKitchen/1.0"})
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")

def _cover_crop(img, target_w, target_h):
    return ImageOps.fit(img, (target_w, target_h), Image.LANCZOS)

def _badge(draw, xy, text, bg, fg, font):
    x, y = xy
    pad_x, pad_y = 26, 14
    tw = draw.textlength(text, font=font)
    box = [x, y, x + tw + pad_x * 2, y + font.size + pad_y * 2]
    draw.rounded_rectangle(box, radius=(font.size + pad_y * 2) // 2, fill=bg)
    draw.text((x + pad_x, y + pad_y), text, font=font, fill=fg)
    return box[2]

def _wrap(draw, text, font, max_w):
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines

@mk_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "lane": "mamas-kitchen", "version": "1.0.0"})

@mk_bp.route("/card", methods=["POST"])
def render_card():
    data = request.get_json(force=True, silent=True) or {}
    required = ["dish_name", "cuisine", "category", "tagline", "image_url"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400

    dish_name = str(data["dish_name"])
    cuisine = str(data["cuisine"]).upper()
    category = str(data["category"]).upper()
    tagline = str(data["tagline"])
    serves = data.get("serves", "")
    time_minutes = data.get("time_minutes", "")
    attribution = str(data.get("attribution", "")).strip()

    try:
        photo = _fetch_image(data["image_url"])
    except Exception as exc:
        return jsonify({"error": f"image fetch failed: {exc}"}), 502

    card = Image.new("RGB", (CARD_W, CARD_H), CREAM)
    draw = ImageDraw.Draw(card)

    header_h = 96
    draw.rectangle([0, 0, CARD_W, header_h], fill=BROWN_DEEP)
    f_brand = _font(42, bold=True)
    f_sub = _font(26)
    draw.text((48, (header_h - f_brand.size) // 2 - 6), "MAMA'S KITCHEN",
              font=f_brand, fill=CREAM)
    sub = "TREND RADAR NG"
    sw = draw.textlength(sub, font=f_sub)
    draw.text((CARD_W - 48 - sw, (header_h - f_sub.size) // 2),
              sub, font=f_sub, fill=AMBER_SOFT)

    photo_fitted = _cover_crop(photo, CARD_W, PHOTO_H)
    card.paste(photo_fitted, (0, header_h))

    if attribution:
        f_attr = _font(22)
        attr_text = attribution[:110]
        aw = draw.textlength(attr_text, font=f_attr)
        ay = header_h + PHOTO_H - 44
        draw.rectangle([0, ay - 8, CARD_W, header_h + PHOTO_H], fill=(0, 0, 0))
        draw.text((CARD_W - 24 - aw, ay), attr_text, font=f_attr, fill=(230, 230, 230))

    y = header_h + PHOTO_H + 36
    f_badge = _font(28, bold=True)
    if cuisine == "NG":
        x_next = _badge(draw, (48, y), "NIGERIAN CLASSIC",
                        GREEN_BADGE, GREEN_BADGE_TEXT, f_badge)
    elif cuisine == "GH":
        x_next = _badge(draw, (48, y), "GHANA CLASSIC",
                        GOLD_BADGE, GOLD_BADGE_TEXT, f_badge)
    else:
        x_next = _badge(draw, (48, y), "SUNDAY ENGLISH",
                        SLATE_BADGE, SLATE_BADGE_TEXT, f_badge)
    _badge(draw, (x_next + 20, y), category, AMBER_SOFT, BROWN_DEEP, f_badge)

    y += f_badge.size + 28 + 30
    f_title = _font(76, bold=True)
    draw.text((48, y), dish_name, font=f_title, fill=BROWN_TEXT)

    y += f_title.size + 26
    f_tag = _font(34)
    tag_lines = _wrap(draw, tagline, f_tag, CARD_W - 96)
    if len(tag_lines) > 2:
        tag_lines = tag_lines[:2]
        while draw.textlength(tag_lines[1] + "…", font=f_tag) > CARD_W - 96:
            tag_lines[1] = tag_lines[1].rsplit(" ", 1)[0]
        tag_lines[1] += "…"
    for line in tag_lines:
        draw.text((48, y), line, font=f_tag, fill=AMBER_MID)
        y += f_tag.size + 12

    footer_y = CARD_H - 88
    draw.line([48, footer_y, CARD_W - 48, footer_y], fill=AMBER_SOFT, width=3)
    f_foot = _font(28)
    left = ""
    if serves and time_minutes:
        left = f"Serves {serves}  ·  {time_minutes} minutes"
    draw.text((48, footer_y + 20), left, font=f_foot, fill=AMBER_MID)
    right = "Recipe in caption"
    rw = draw.textlength(right, font=f_foot)
    draw.text((CARD_W - 48 - rw, footer_y + 20), right, font=f_foot, fill=AMBER_MID)

    buf = io.BytesIO()
    card.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name=f"mk_{dish_name.lower().replace(' ', '_')}.png")
