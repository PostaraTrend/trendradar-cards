# naturals_route.py — Naija Naturals card renderer
# Register in app.py with:  app.register_blueprint(naturals)
# Contract mirrors naijalens_route: POST /naturals/render
#   Request:  { "photo_url": ..., "location": ..., "credit": "Photo: Name via Pexels" }
#   Response: { "image_url": ... }
# Treatment: full-bleed 1080x1350, half-sun lane mark top-left,
# slim bottom location bar with gold edge tick. No scrim hook (distinct from Naija Lens).

import io
import os
import time
import requests
from flask import Blueprint, request, jsonify, url_for
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance, ImageFilter

naturals = Blueprint("naturals", __name__)

W, H = 1080, 1350
MIN_SHORT_SIDE = 1500
GOLD = (244, 196, 92)
NAVY = (8, 14, 24)
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
RENDER_DIR = os.path.join(os.path.dirname(__file__), "static", "renders")
os.makedirs(RENDER_DIR, exist_ok=True)


def _font(name, size):
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    except OSError:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size
        )


def _download(url):
    resp = requests.get(url, timeout=45)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def _crop_4x5(img):
    # Center crop to 4:5 with a slight upward bias so skies and horizons survive.
    target = W / H
    w, h = img.size
    if w / h > target:
        new_w = int(h * target)
        x = (w - new_w) // 2
        img = img.crop((x, 0, x + new_w, h))
    else:
        new_h = int(w / target)
        y = max(0, int((h - new_h) * 0.40))
        img = img.crop((0, y, w, y + new_h))
    return img.resize((W, H), Image.LANCZOS)


def _enhance(img):
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Color(img).enhance(1.12)
    img = ImageEnhance.Contrast(img).enhance(1.04)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=90, threshold=3))
    return img


def _treatment(img, location, credit):
    d = ImageDraw.Draw(img, "RGBA")

    # Top-left lane mark: half sun over horizon line
    cx, cy = 96, 86
    d.arc([cx - 20, cy - 20, cx + 20, cy + 20], 180, 360, fill=GOLD + (255,), width=5)
    d.line([(cx - 30, cy), (cx + 30, cy)], fill=(255, 255, 255, 220), width=4)
    d.text((146, 62), "NAIJA NATURALS", font=_font("Poppins-Bold.ttf", 30),
           fill=(255, 255, 255, 240))
    d.text((146, 100), "BY TREND RADAR NG", font=_font("Poppins-Medium.ttf", 18),
           fill=(255, 255, 255, 175))

    # Slim bottom location bar with gold edge tick
    bar_y = H - 96
    d.rectangle([0, bar_y, W, H], fill=NAVY + (200,))
    d.rectangle([0, bar_y, 10, H], fill=GOLD + (255,))
    d.text((44, bar_y + 18), location.upper()[:42],
           font=_font("Poppins-SemiBold.ttf", 30), fill=(255, 255, 255, 255))
    # Credit arrives fully formed from Parse Selection ("Photo: Name via Pexels")
    d.text((44, bar_y + 58), credit,
           font=_font("Poppins-Medium.ttf", 18), fill=(255, 255, 255, 160))
    return img


@naturals.route("/naturals/render", methods=["POST"])
def render_naturals():
    data = request.get_json(force=True, silent=True) or {}
    photo_url = data.get("photo_url")
    location = data.get("location", "THE AFRICAN WILD")
    credit = data.get("credit", "Photo: Pexels")

    if not photo_url:
        return jsonify({"error": "photo_url is required"}), 400

    try:
        photo = _download(photo_url)
    except Exception as exc:
        return jsonify({"error": "download failed", "detail": str(exc)}), 502

    if min(photo.size) < MIN_SHORT_SIDE:
        return jsonify({
            "error": "quality gate",
            "detail": "short side {}px is below {}px minimum".format(
                min(photo.size), MIN_SHORT_SIDE)
        }), 422

    card = _treatment(_enhance(_crop_4x5(photo)), location, credit)

    filename = "naturals_{}.jpg".format(int(time.time()))
    card.save(os.path.join(RENDER_DIR, filename), "JPEG", quality=92)

    image_out = request.host_url.rstrip("/") + url_for(
        "static", filename="renders/" + filename)
    return jsonify({"image_url": image_out}), 200
