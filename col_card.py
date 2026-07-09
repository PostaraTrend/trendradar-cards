"""
TRNG — Cost of Living Daily Card (Naija Market Check layout, v2)
================================================================
Drop-in replacement for the original col_card.py. Same registration,
same endpoints, same data schema, same in-memory hosted-URL pattern —
the n8n COL workflow needs NO changes.

    from col_card import col_bp
    app.register_blueprint(col_bp)

Endpoints (unchanged):
    POST /col/render          -> {"image_url": ..., "image_url_jpg": ..., "image_id": ...}
    GET  /col/image/<id>.png  -> PNG (Facebook)
    GET  /col/image/<id>.jpg  -> JPEG (Instagram)

What changed (Jul 2026, anti-fingerprint rebuild):
  * Layout replaced with the light-bodied "Naija Market Check" design —
    the version that survived manual posting on Facebook and published
    cleanly on Instagram. The old dark dollar-hero layout carries a
    suppressed FB perceptual-hash fingerprint and is retired permanently.
  * Daily variation wired in via variation.py (must sit next to this
    file): accent scheme, badge text, tagline, section title, footer
    line, food-row order, and a badge micro-jitter all rotate on
    independent per-day cycles (Africa/Lagos, deterministic — same-day
    re-renders are pixel-identical, so retries stay safe).
  * Brand identity fixed: masthead text, card title, fonts, green
    family, date format, and the sign-off never vary.

Requires: variation.py in the same directory.
Single-worker constraint (in-memory image store) unchanged.
"""

import io
import os
import time
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file, url_for
from PIL import Image, ImageDraw, ImageFont

from variation import get_daily_variation

col_bp = Blueprint("col", __name__, url_prefix="/col")

# ---------------------------------------------------------------------------
# FIXED BRAND IDENTITY — these never vary day to day
# ---------------------------------------------------------------------------
BRAND = {
    "brand_name": "TREND RADAR NG",
    "card_title": "NAIJA MARKET CHECK",
    "footer_cta": "Trend Radar NG \u2014 daily prices, no hype",
    "body_bg": "#FFFFFF",
    "body_text": "#1C1C1C",
    "body_muted": "#6B6B6B",
    "up": "#C0392B",     # price up = bad = red (used subtly on rows)
    "down": "#1E8449",   # price down = good = green
    "flat": "#9AA5A0",
}

# Font paths: brand fonts first (Poppins, bundled with trendradar-cards),
# env override honoured, DejaVu as the Render base-image fallback.
def _find_font(env_key, candidates):
    p = os.environ.get(env_key)
    if p and os.path.exists(p):
        return p
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[-1]

FONT_BOLD = _find_font("COL_FONT_BOLD", [
    os.path.join(os.path.dirname(__file__), "fonts", "Poppins-Bold.ttf"),
    "fonts/Poppins-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
])
FONT_REG = _find_font("COL_FONT_REG", [
    os.path.join(os.path.dirname(__file__), "fonts", "Poppins-Regular.ttf"),
    "fonts/Poppins-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
])

W, H = 1080, 1350  # 4:5 photo post (per Meta static-post rule: photo, not reel)

HEADER_H = 300
FOOTER_H = 110

_IMAGE_STORE = {}          # id -> (bytes, created_ts)
_IMAGE_TTL_SECONDS = 3600  # Graph API fetches within seconds; 1h is ample


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _fmt_naira(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "\u2014"
    if v >= 1000:
        return f"\u20a6{v:,.0f}"
    return f"\u20a6{v:,.2f}".rstrip("0").rstrip(".")


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


def _dir_mark(direction):
    return {"up": "\u25b4", "down": "\u25be"}.get(direction, "")


def _dir_color(direction):
    return {"up": BRAND["up"], "down": BRAND["down"]}.get(direction, BRAND["flat"])


def _fit_text(d, text, font_path, start_size, max_w, min_size=20):
    """Return (text, font) guaranteed to fit within max_w: shrink the font
    down to min_size first, then ellipsize as a last resort. Prevents the
    rotating taglines/footer lines (which vary in length day to day) from
    clipping at the card edge."""
    size = start_size
    f = _font(font_path, size)
    while d.textlength(text, font=f) > max_w and size > min_size:
        size -= 2
        f = _font(font_path, size)
    if d.textlength(text, font=f) > max_w:
        while text and d.textlength(text + "\u2026", font=f) > max_w:
            text = text[:-1]
        text = text.rstrip() + "\u2026"
    return text, f


def render_col_card(data: dict) -> bytes:
    """Same data schema as v1 (all optional except usd_official):
    {
      "date_label": "Thursday, 9 July 2026",
      "usd_official": 1368, "usd_prev": 1370,
      "gbp_official": 1828, "gbp_prev": 1830,
      "eur_official": 1562, "eur_prev": 1560,
      "usd_parallel": 1410, "parallel_prev": 1408,
      "petrol": 1150,       "petrol_prev": 1150,
      "staples": [{"name": "Rice \u2014 50 kg bag", "price": 60000, "prev": 60000}, ...],
      "source_line": "Sources: CBN official window \u2022 published market reports"
    }
    """
    v = get_daily_variation()  # deterministic per Lagos calendar day
    S = v.scheme

    img = Image.new("RGB", (W, H), BRAND["body_bg"])
    d = ImageDraw.Draw(img)

    f_brand = _font(FONT_BOLD, 36)
    f_title = _font(FONT_BOLD, 78)
    f_date = _font(FONT_REG, 32)
    f_badge = _font(FONT_BOLD, 26)
    f_section = _font(FONT_BOLD, 40)
    f_tagline = _font(FONT_REG, 27)
    f_fx_title = _font(FONT_BOLD, 32)
    f_fx_label = _font(FONT_REG, 24)
    f_fx_value = _font(FONT_BOLD, 40)
    f_small = _font(FONT_REG, 26)

    # ------------------------------------------------------------------
    # HEADER BAND (varies: band colour, badge text/fill/position)
    # ------------------------------------------------------------------
    d.rectangle([0, 0, W, HEADER_H], fill=S.header_band)
    d.rectangle([0, 0, W, 8], fill=S.rule_line)

    d.text((70, 44), BRAND["brand_name"], font=f_brand, fill=S.rule_line)
    d.text((70, 100), BRAND["card_title"], font=f_title, fill="#FFFFFF")
    date_label = data.get("date_label") or datetime.now().strftime("%A, %-d %B %Y")
    d.text((70, 210), date_label, font=f_date, fill="#D7E4DD")

    # Badge pill — the ONLY jittered element (\u00b16 px x, \u00b14 px y)
    badge_txt = v.badge_text
    bw = d.textlength(badge_txt, font=f_badge) + 56
    bx1 = W - 70 - bw + v.x_jitter
    by0 = 52 + v.y_jitter
    d.rounded_rectangle([bx1, by0, bx1 + bw, by0 + 56], radius=28,
                        fill=S.badge_fill, outline=S.rule_line, width=2)
    d.text((bx1 + 28, by0 + 13), badge_txt, font=f_badge, fill=S.badge_text)

    # Gold rule closing the header
    d.rectangle([0, HEADER_H - 6, W, HEADER_H], fill=S.rule_line)

    # ------------------------------------------------------------------
    # FX + FUEL PANEL geometry (drawn later, but height needed now)
    # ------------------------------------------------------------------
    fx_items = [(label, val, prev) for (label, val, prev) in [
        ("PETROL /L", data.get("petrol"), data.get("petrol_prev")),
        ("USD", data.get("usd_official"), data.get("usd_prev")),
        ("GBP", data.get("gbp_official"), data.get("gbp_prev")),
        ("EUR", data.get("eur_official"), data.get("eur_prev")),
    ] if val is not None]
    fx_panel_h = 200 if fx_items else 0
    fx_top = H - FOOTER_H - fx_panel_h - 24

    # ------------------------------------------------------------------
    # FOOD & KITCHEN SECTION (varies: title, tagline, row order, stripes)
    # ------------------------------------------------------------------
    y = HEADER_H + 42
    d.text((70, y), v.section_title, font=f_section, fill=S.price_color)
    tag_x = 70 + d.textlength(v.section_title, font=f_section) + 26
    beside_w = W - 70 - tag_x
    if d.textlength(v.tagline, font=f_tagline) <= beside_w:
        # fits beside the section title
        d.text((tag_x, y + 12), v.tagline, font=f_tagline, fill=BRAND["body_muted"])
    else:
        # draw on its own line below, fitted to the full content width
        tag_txt, tag_f = _fit_text(d, v.tagline, FONT_REG, 27, W - 140)
        d.text((70, y + 54), tag_txt, font=tag_f, fill=BRAND["body_muted"])
        y += 40
    y += 72

    staples = (data.get("staples") or [])[:9]
    staples = v.shuffle_rows(staples)  # per-day deterministic order
    if staples:
        n = len(staples)
        avail = fx_top - y - 16
        row_h = max(48, min(74, avail // n))
        f_item = _font(FONT_REG, max(26, int(row_h * 0.46)))
        f_item_price = _font(FONT_BOLD, max(28, int(row_h * 0.50)))
        for i, s in enumerate(staples):
            ry0, ry1 = y, y + row_h
            if i % 2 == 0:
                d.rectangle([50, ry0, W - 50, ry1], fill=S.row_stripe)
            ty = ry0 + (row_h - f_item.size) // 2 - 2
            d.text((84, ty), s.get("name", ""), font=f_item, fill=BRAND["body_text"])
            price_txt = _fmt_naira(s.get("price"))
            sdir = _change_dir(s.get("price"), s.get("prev"))
            mark = _dir_mark(sdir)
            px = W - 96 - d.textlength(price_txt, font=f_item_price)
            if mark:
                px -= 30
            d.text((px, ry0 + (row_h - f_item_price.size) // 2 - 2),
                   price_txt, font=f_item_price, fill=S.price_color)
            if mark:
                d.text((W - 96 - 18, ty + 2), mark, font=f_item, fill=_dir_color(sdir))
            y = ry1

    # ------------------------------------------------------------------
    # FUEL & OFFICIAL FX PANEL (varies: panel bg, tile borders)
    # ------------------------------------------------------------------
    if fx_items:
        d.rounded_rectangle([50, fx_top, W - 50, fx_top + fx_panel_h],
                            radius=24, fill=S.fx_strip_bg)
        d.text((84, fx_top + 22), "FUEL & OFFICIAL FX", font=f_fx_title,
               fill=S.badge_fill if S.badge_fill.upper() not in ("#FFFFFF",) else S.rule_line)
        d.text((84 + d.textlength("FUEL & OFFICIAL FX", font=f_fx_title) + 22,
                fx_top + 30), "CBN official window", font=f_fx_label, fill="#BFD2C8")

        par = data.get("usd_parallel")
        if par not in (None, "", 0, "0"):
            par_txt = f"Parallel: {_fmt_naira(par)}"
            d.text((W - 84 - d.textlength(par_txt, font=f_fx_label), fx_top + 30),
                   par_txt, font=f_fx_label, fill="#BFD2C8")

        tiles_y = fx_top + 76
        tile_h = 96
        gap = 18
        tile_w = (W - 100 - 68 - gap * (len(fx_items) - 1)) // len(fx_items)
        for i, (label, val, prev) in enumerate(fx_items):
            x0 = 84 + i * (tile_w + gap)
            d.rounded_rectangle([x0, tiles_y, x0 + tile_w, tiles_y + tile_h],
                                radius=16, outline=S.fx_tile_border, width=2)
            d.text((x0 + 20, tiles_y + 12), label, font=f_fx_label, fill="#BFD2C8")
            d.text((x0 + 20, tiles_y + 42), _fmt_naira(val), font=f_fx_value, fill="#FFFFFF")

    # ------------------------------------------------------------------
    # FOOTER (varies: sources line)
    # ------------------------------------------------------------------
    d.rectangle([0, H - FOOTER_H, W, H], fill=S.header_band)
    src = data.get("source_line") or v.footer_line
    src_txt, src_f = _fit_text(d, src, FONT_REG, 26, W - 140)
    d.text((70, H - FOOTER_H + 18), src_txt, font=src_f, fill="#D7E4DD")
    d.text((70, H - FOOTER_H + 60), BRAND["footer_cta"], font=f_small, fill=S.rule_line)

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
