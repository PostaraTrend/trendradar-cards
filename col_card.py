"""
TRNG — Cost of Living Daily Card
Drop-in Flask blueprint for the trendradar-cards service (Render).

Register in your existing app:
    from col_card import col_bp
    app.register_blueprint(col_bp)

Endpoints:
    POST /col/render   -> generates the card, returns {"image_url": "..."}
    GET  /col/image/<id>.png -> serves the generated PNG (Facebook/IG fetch it here)

The n8n workflow POSTs the day's data to /col/render, then hands the
returned image_url to the Graph API photo endpoints.
"""

import io
import os
import time
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file, url_for
from PIL import Image, ImageDraw, ImageFont

col_bp = Blueprint("col", __name__, url_prefix="/col")

# ---------------------------------------------------------------------------
# BRAND CONFIG — swap these to match the TRNG palette / fonts you already use
# ---------------------------------------------------------------------------
BRAND = {
    "bg": "#0B3D2E",          # deep green base
    "bg_panel": "#0F4A38",    # panel green
    "accent": "#FFC42D",      # naira gold
    "up": "#FF5A5A",          # price up = bad = red
    "down": "#4CD97B",        # price down = good = green
    "flat": "#9FB8AE",
    "text": "#FFFFFF",
    "muted": "#C9DCD4",
    "brand_name": "TREND RADAR NG",
    "card_title": "COST OF LIVING TODAY",
    "footer_cta": "Follow Trend Radar NG for daily prices",
}

# Font paths: point at the fonts already bundled in trendradar-cards if you
# have brand fonts there; DejaVu ships on Render's base image as fallback.
FONT_BOLD = os.environ.get("COL_FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_REG = os.environ.get("COL_FONT_REG", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

W, H = 1080, 1350  # 4:5 photo post (per Meta static-post rule: photo, not reel)

_IMAGE_STORE = {}          # id -> (bytes, created_ts)
_IMAGE_TTL_SECONDS = 3600  # keep images 1h; Graph API fetches within seconds


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _fmt_naira(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if v >= 1000:
        return f"\u20a6{v:,.0f}"
    return f"\u20a6{v:,.2f}".rstrip("0").rstrip(".")


def _arrow(direction):
    return {"up": "\u25b2", "down": "\u25bc"}.get(direction, "\u25cf")


def _dir_color(direction):
    return {"up": BRAND["up"], "down": BRAND["down"]}.get(direction, BRAND["flat"])


def _change_dir(current, previous, threshold=0.001):
    try:
        c, p = float(current), float(previous)
    except (TypeError, ValueError):
        return "flat"
    if p == 0:
        return "flat"
    delta = (c - p) / p
    if delta > threshold:
        return "up"
    if delta < -threshold:
        return "down"
    return "flat"


def render_col_card(data: dict) -> bytes:
    """data schema (all optional except usd_official):
    {
      "date_label": "Tuesday, 7 July 2026",
      "usd_official": 1478.25, "usd_prev": 1470.1,
      "gbp_official": 1990.4,  "gbp_prev": 1985.0,
      "eur_official": 1710.6,  "eur_prev": 1712.2,
      "usd_parallel": 1520,    "parallel_prev": 1515,
      "petrol": 935,           "petrol_prev": 935,
      "staples": [
          {"name": "Rice (50kg)", "price": 92000, "prev": 90000},
          {"name": "Bread (family loaf)", "price": 1800, "prev": 1800},
          {"name": "Garri (paint bucket)", "price": 3200, "prev": 3000}
      ],
      "source_line": "FX: CBN/open.er-api • Fuel & food: TRNG market check"
    }
    """
    img = Image.new("RGB", (W, H), BRAND["bg"])
    d = ImageDraw.Draw(img)

    f_brand = _font(FONT_BOLD, 40)
    f_title = _font(FONT_BOLD, 58)
    f_date = _font(FONT_REG, 32)
    f_label = _font(FONT_REG, 36)
    f_big = _font(FONT_BOLD, 96)
    f_mid = _font(FONT_BOLD, 50)
    f_small = _font(FONT_REG, 30)
    f_item = _font(FONT_REG, 38)
    f_item_price = _font(FONT_BOLD, 42)

    # Header
    d.rectangle([0, 0, W, 8], fill=BRAND["accent"])
    d.text((60, 40), BRAND["brand_name"], font=f_brand, fill=BRAND["accent"])
    d.text((60, 98), BRAND["card_title"], font=f_title, fill=BRAND["text"])
    date_label = data.get("date_label") or datetime.now().strftime("%A, %d %B %Y")
    d.text((60, 172), date_label, font=f_date, fill=BRAND["muted"])

    y = 230

    # --- Dollar hero panel ---
    d.rounded_rectangle([50, y, W - 50, y + 200], radius=28, fill=BRAND["bg_panel"])
    d.text((90, y + 26), "DOLLAR TO NAIRA (official)", font=f_label, fill=BRAND["muted"])
    usd = data.get("usd_official")
    usd_dir = _change_dir(usd, data.get("usd_prev"))
    d.text((90, y + 78), _fmt_naira(usd), font=f_big, fill=BRAND["text"])
    ax = 90 + d.textlength(_fmt_naira(usd), font=f_big) + 30
    d.text((ax, y + 104), _arrow(usd_dir), font=f_mid, fill=_dir_color(usd_dir))

    # Parallel rate chip (only if provided)
    par = data.get("usd_parallel")
    if par not in (None, "", 0, "0"):
        par_dir = _change_dir(par, data.get("parallel_prev"))
        chip = f"Parallel: {_fmt_naira(par)} {_arrow(par_dir)}"
        cw = d.textlength(chip, font=f_small) + 50
        d.rounded_rectangle([W - 60 - cw, y + 26, W - 60, y + 84], radius=20, fill=BRAND["bg"])
        d.text((W - 60 - cw + 25, y + 38), chip, font=f_small, fill=BRAND["accent"])

    y += 230

    # --- GBP / EUR / Petrol row (boxes with no data are hidden; width adapts) ---
    cols = [(label, val, prev) for (label, val, prev) in [
        ("POUND", data.get("gbp_official"), data.get("gbp_prev")),
        ("EURO", data.get("eur_official"), data.get("eur_prev")),
        ("PETROL /L", data.get("petrol"), data.get("petrol_prev")),
    ] if val is not None]
    if cols:
        box_w = (W - 100 - 20 * (len(cols) - 1)) // len(cols)
        for i, (label, val, prev) in enumerate(cols):
            x0 = 50 + i * (box_w + 20)
            d.rounded_rectangle([x0, y, x0 + box_w, y + 165], radius=24, fill=BRAND["bg_panel"])
            d.text((x0 + 28, y + 20), label, font=f_small, fill=BRAND["muted"])
            d.text((x0 + 28, y + 62), _fmt_naira(val), font=f_mid, fill=BRAND["text"])
            ddir = _change_dir(val, prev)
            d.text((x0 + 28, y + 122), f"{_arrow(ddir)} vs yesterday", font=f_small, fill=_dir_color(ddir))
        y += 195

    # --- Staples panel (up to 9 items; hidden entirely when no items provided).
    #     Row height and fonts adapt to the item count so few items render
    #     large and the full nine still clear the footer. ---
    staples = (data.get("staples") or [])[:9]
    if staples:
        n = len(staples)
        footer_top = H - 120
        avail = footer_top - y - 10          # space the panel may occupy
        row_h = min(68, (avail - 84 - 8) // n)
        f_item = _font(FONT_REG, max(28, int(row_h * 0.56)))
        f_item_price = _font(FONT_BOLD, max(30, int(row_h * 0.62)))
        panel_h = 84 + n * row_h + 8
        d.rounded_rectangle([50, y, W - 50, y + panel_h], radius=28, fill=BRAND["bg_panel"])
        d.text((90, y + 24), "FOOD & KITCHEN MARKET CHECK", font=f_label, fill=BRAND["accent"])
        sy = y + 84
        for s in staples:
            d.text((90, sy), s.get("name", ""), font=f_item, fill=BRAND["text"])
            price_txt = _fmt_naira(s.get("price"))
            sdir = _change_dir(s.get("price"), s.get("prev"))
            ptx = W - 110 - d.textlength(price_txt, font=f_item_price) - 46
            d.text((ptx, sy), price_txt, font=f_item_price, fill=BRAND["text"])
            d.text((W - 130, sy + 2), _arrow(sdir), font=f_item, fill=_dir_color(sdir))
            sy += row_h

    # Footer
    d.rectangle([0, H - 120, W, H], fill=BRAND["bg_panel"])
    src = data.get("source_line", "Sources: CBN official FX • TRNG market check")
    d.text((60, H - 100), src, font=f_small, fill=BRAND["muted"])
    d.text((60, H - 56), BRAND["footer_cta"], font=f_small, fill=BRAND["accent"])

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _gc_store():
    now = time.time()
    for k in [k for k, (_, ts) in _IMAGE_STORE.items() if now - ts > _IMAGE_TTL_SECONDS]:
        _IMAGE_STORE.pop(k, None)


@col_bp.route("/render", methods=["POST"])
def render_endpoint():
    _gc_store()
    data = request.get_json(force=True, silent=True) or {}
    try:
        png = render_col_card(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    image_id = uuid.uuid4().hex
    _IMAGE_STORE[image_id] = (png, time.time())
    return jsonify({
        "image_url": url_for("col.serve_image", image_id=image_id, _external=True),
        "image_url_jpg": url_for("col.serve_image_jpg", image_id=image_id, _external=True),
        "image_id": image_id,
    })


@col_bp.route("/image/<image_id>.png", methods=["GET"])
def serve_image(image_id):
    entry = _IMAGE_STORE.get(image_id)
    if not entry:
        return jsonify({"error": "expired or unknown image id"}), 404
    return send_file(io.BytesIO(entry[0]), mimetype="image/png",
                     download_name=f"trng_col_{image_id}.png")


@col_bp.route("/image/<image_id>.jpg", methods=["GET"])
def serve_image_jpg(image_id):
    """Instagram's image_url ingestion accepts JPEG only; convert on demand."""
    entry = _IMAGE_STORE.get(image_id)
    if not entry:
        return jsonify({"error": "expired or unknown image id"}), 404
    img = Image.open(io.BytesIO(entry[0])).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg",
                     download_name=f"trng_col_{image_id}.jpg")
