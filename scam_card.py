"""
TRNG — Shine Your Eye (Scam Alert) Card
Drop-in Flask blueprint for the trendradar-cards service (Render).

Register alongside the COL blueprint:
    from scam_card import scam_bp
    app.register_blueprint(scam_bp)

Endpoints:
    POST /scam/render          -> generates the card, returns {"image_url": "...", "image_url_jpg": "..."}
    GET  /scam/image/<id>.png  -> serves the generated PNG (Facebook fetches this)
    GET  /scam/image/<id>.jpg  -> JPEG conversion (Instagram fetches this — IG accepts JPEG only)
"""

import io
import os
import time
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file, url_for
from PIL import Image, ImageDraw, ImageFont

scam_bp = Blueprint("scam", __name__, url_prefix="/scam")

BRAND = {
    "bg": "#1C0F10",           # deep warning maroon-black
    "bg_panel": "#2A1517",
    "alert": "#E23B3B",        # alert red
    "accent": "#FFC42D",       # TRNG gold (brand continuity)
    "safe": "#4CD97B",         # protection-tips green
    "text": "#FFFFFF",
    "muted": "#D8C3C3",
    "brand_name": "TREND RADAR NG",
    "lane_name": "SHINE YOUR EYE",
    "footer_cta": "Share this to protect your people",
}

FONT_BOLD = os.environ.get("SCAM_FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_REG = os.environ.get("SCAM_FONT_REG", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

W, H = 1080, 1350  # photo post (Meta static post rule)

_IMAGE_STORE = {}
_IMAGE_TTL_SECONDS = 3600

ALERT_TYPES = {
    "PONZI ALERT": "#E23B3B",
    "JOB SCAM": "#E2743B",
    "FRAUD TRICK": "#E23B6E",
    "FAKE RECRUITMENT": "#B93BE2",
    "SCAM ALERT": "#E23B3B",  # generic fallback
}


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _wrap(draw, text, font, max_width):
    """Greedy word-wrap using actual rendered widths."""
    words = (text or "").split()
    lines, cur = [], ""
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


def render_scam_card(data: dict) -> bytes:
    """data schema:
    {
      "alert_type": "PONZI ALERT",           # see ALERT_TYPES keys
      "headline": "…",                        # 1 sentence
      "facts": ["…", "…", "…"],               # up to 3 short bullets
      "protection": ["…", "…"],               # up to 2 short bullets
      "source_name": "EFCC",                  # printed on card — required
      "date_label": "Tuesday, 7 July 2026"    # optional
    }
    Fonts auto-shrink through three size tiers so long alerts fit
    without truncating the protection tips.
    """
    img = Image.new("RGB", (W, H), BRAND["bg"])
    d = ImageDraw.Draw(img)

    def measure(head_size, body_size):
        """Return (total_height_needed, prepared_layout) for a size tier."""
        fh = _font(FONT_BOLD, head_size)
        fb = _font(FONT_REG, body_size)
        lh_head = head_size + 14
        lh_body = body_size + 12
        head_lines = _wrap(d, data.get("headline", ""), fh, W - 120)[:4]
        fact_lines = [_wrap(d, x, fb, W - 220)[:3] for x in (data.get("facts") or [])[:3]]
        tip_lines = [_wrap(d, x, fb, W - 220)[:3] for x in (data.get("protection") or [])[:2]]
        h = 240
        h += len(head_lines) * lh_head + 24
        h += 84 + sum(len(fl) * lh_body + 18 for fl in fact_lines) + 10 + 26
        h += 84 + sum(len(tl) * lh_body + 18 for tl in tip_lines) + 10
        return h, (fh, fb, lh_head, lh_body, head_lines, fact_lines, tip_lines)

    layout = None
    for head_size, body_size in [(54, 38), (50, 35), (46, 32)]:
        total, prepared = measure(head_size, body_size)
        layout = prepared
        if total <= H - 150:  # must clear the footer
            break

    fh, fb, lh_head, lh_body, head_lines, fact_lines, tip_lines = layout

    f_brand = _font(FONT_BOLD, 38)
    f_lane = _font(FONT_BOLD, 60)
    f_badge = _font(FONT_BOLD, 40)
    f_sect = _font(FONT_BOLD, 36)
    f_small = _font(FONT_REG, 30)

    alert_type = (data.get("alert_type") or "SCAM ALERT").upper()
    badge_color = ALERT_TYPES.get(alert_type, BRAND["alert"])

    # Top alert strip
    d.rectangle([0, 0, W, 14], fill=badge_color)
    d.text((60, 44), BRAND["brand_name"], font=f_brand, fill=BRAND["accent"])
    d.text((60, 100), BRAND["lane_name"], font=f_lane, fill=BRAND["text"])
    date_label = data.get("date_label") or datetime.now().strftime("%A, %d %B %Y")
    d.text((60, 178), date_label, font=f_small, fill=BRAND["muted"])

    # Alert badge
    bw = d.textlength(alert_type, font=f_badge) + 70
    d.rounded_rectangle([W - 60 - bw, 60, W - 60, 130], radius=18, fill=badge_color)
    d.text((W - 60 - bw + 35, 74), alert_type, font=f_badge, fill=BRAND["text"])

    y = 240

    # Headline
    for line in head_lines:
        d.text((60, y), line, font=fh, fill=BRAND["text"])
        y += lh_head
    y += 24

    # Facts panel — "WETIN DEY HAPPEN"
    panel_h = 84 + sum(len(fl) * lh_body + 18 for fl in fact_lines) + 10
    d.rounded_rectangle([50, y, W - 50, y + panel_h], radius=28, fill=BRAND["bg_panel"])
    d.text((90, y + 26), "WETIN DEY HAPPEN", font=f_sect, fill=badge_color)
    fy = y + 84
    for fl in fact_lines:
        d.ellipse([92, fy + 14, 112, fy + 34], fill=badge_color)
        for line in fl:
            d.text((136, fy), line, font=fb, fill=BRAND["text"])
            fy += lh_body
        fy += 18
    y += panel_h + 26

    # Protection panel — "PROTECT YOURSELF"
    panel_h2 = 84 + sum(len(tl) * lh_body + 18 for tl in tip_lines) + 10
    panel_h2 = min(panel_h2, (H - 140) - y)  # hard stop above footer
    d.rounded_rectangle([50, y, W - 50, y + panel_h2], radius=28, fill=BRAND["bg_panel"])
    d.text((90, y + 26), "PROTECT YOURSELF", font=f_sect, fill=BRAND["safe"])
    ty = y + 84
    for tl in tip_lines:
        if ty + len(tl) * lh_body > y + panel_h2 - 10:
            break
        d.text((92, ty - 2), "\u2713", font=f_sect, fill=BRAND["safe"])
        for line in tl:
            d.text((136, ty), line, font=fb, fill=BRAND["text"])
            ty += lh_body
        ty += 18

    # Footer
    d.rectangle([0, H - 130, W, H], fill=BRAND["bg_panel"])
    src = f"Source: {data.get('source_name', 'Verified report')}"
    d.text((60, H - 108), src, font=f_small, fill=BRAND["muted"])
    d.text((60, H - 62), BRAND["footer_cta"], font=f_small, fill=BRAND["accent"])

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _gc_store():
    now = time.time()
    for k in [k for k, (_, ts) in _IMAGE_STORE.items() if now - ts > _IMAGE_TTL_SECONDS]:
        _IMAGE_STORE.pop(k, None)


@scam_bp.route("/render", methods=["POST"])
def render_endpoint():
    _gc_store()
    data = request.get_json(force=True, silent=True) or {}
    if not (data.get("headline") and data.get("source_name")):
        return jsonify({"error": "headline and source_name are required"}), 400
    try:
        png = render_scam_card(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    image_id = uuid.uuid4().hex
    _IMAGE_STORE[image_id] = (png, time.time())
    return jsonify({
        "image_url": url_for("scam.serve_image", image_id=image_id, _external=True),
        "image_url_jpg": url_for("scam.serve_image_jpg", image_id=image_id, _external=True),
        "image_id": image_id,
    })


@scam_bp.route("/image/<image_id>.png", methods=["GET"])
def serve_image(image_id):
    entry = _IMAGE_STORE.get(image_id)
    if not entry:
        return jsonify({"error": "expired or unknown image id"}), 404
    return send_file(io.BytesIO(entry[0]), mimetype="image/png",
                     download_name=f"trng_scam_{image_id}.png")


@scam_bp.route("/image/<image_id>.jpg", methods=["GET"])
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
                     download_name=f"trng_scam_{image_id}.jpg")
