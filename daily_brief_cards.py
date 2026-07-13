"""
TRNG — Naija Daily Brief card renderer.

Blueprint: brief_bp
Routes:
    GET  /brief/health   -> {"ok": true}
    POST /brief/render   -> {"url": "<hosted JPEG>", "filename": "..."}

Request JSON for /brief/render:
    {
        "date_label": "Sunday, 12 July 2026",
        "traffic":  "…",   # slot body text, house style, no contractions
        "weather":  "…",
        "football": "…"    # may be empty string -> row renders as QUIET note
    }

House patterns honoured:
    * JPEG output written to static/brief/ on disk (Naija Lens hosted-image pattern)
    * Self-downloading font at import time (genz_cards pattern)
    * Register in app.py:  from daily_brief_cards import brief_bp
                           app.register_blueprint(brief_bp)
      (404 after a clean gunicorn boot means this registration is missing.)
"""

import os
import re
import urllib.request
from datetime import datetime

from flask import Blueprint, jsonify, request, url_for
from PIL import Image, ImageDraw, ImageFont

brief_bp = Blueprint("brief", __name__)

# ---------------------------------------------------------------- fonts ----
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_PATH = os.path.join(FONT_DIR, "Outfit.ttf")
FONT_URL = ("https://raw.githubusercontent.com/google/fonts/main/"
            "ofl/outfit/Outfit%5Bwght%5D.ttf")


def _ensure_font():
    os.makedirs(FONT_DIR, exist_ok=True)
    if not os.path.exists(FONT_PATH):
        req = urllib.request.Request(
            FONT_URL, headers={"User-Agent": "TRNG-card-renderer/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r, \
                open(FONT_PATH, "wb") as f:
            f.write(r.read())


_ensure_font()


def _font(size, weight=800):
    f = ImageFont.truetype(FONT_PATH, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


# ---------------------------------------------------------------- style ----
W = H = 1080
NAVY = (14, 40, 65)        # 0E2841
CREAM = (247, 245, 240)
INK = (24, 32, 44)
WHITE = (255, 255, 255)
SLOT_STYLE = [
    ("TRAFFIC", (245, 166, 35)),    # amber
    ("WEATHER", (48, 136, 136)),    # PostaraTrend teal 308888
    ("FOOTBALL", (24, 160, 112)),   # PostaraTrend emerald 18A070
]
QUIET_TEXT = {
    "TRAFFIC": "Roads are calm across major routes this morning. Enjoy the quiet.",
    "WEATHER": "No notable weather signal today.",
    "FOOTBALL": "No fixture on the radar today. We will bring you the next one.",
}


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        trial = (cur + " " + w_).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, text, max_w, max_lines, start=40, floor=28, weight=600):
    size = start
    while size >= floor:
        f = _font(size, weight)
        lines = _wrap(draw, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
        size -= 2
    f = _font(floor, weight)
    lines = _wrap(draw, text, f, max_w)[:max_lines]
    if lines:
        lines[-1] = lines[-1].rstrip(".") + "…"
    return f, lines


CONTRACTION_RE = re.compile(
    r"\b\w+['\u2019](?:t|s|re|ve|ll|d|m)\b", re.IGNORECASE)


def render_brief_card(date_label, traffic, weather, football, out_dir):
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)

    # header band
    d.rectangle([0, 0, W, 210], fill=NAVY)
    d.text((60, 46), "NAIJA DAILY BRIEF", font=_font(66, 800), fill=WHITE)
    d.text((60, 132), date_label.upper(), font=_font(30, 600),
           fill=(245, 166, 35))
    tag = "TREND RADAR NG"
    tf = _font(26, 700)
    d.text((W - 60 - d.textlength(tag, font=tf), 142), tag,
           font=tf, fill=(150, 190, 210))

    # three slot rows
    bodies = [traffic, weather, football]
    top = 250
    row_h = 240
    for i, ((label, accent), body) in enumerate(zip(SLOT_STYLE, bodies)):
        y = top + i * (row_h + 20)
        quiet = not (body or "").strip()
        text = QUIET_TEXT[label] if quiet else body.strip()
        # card row
        d.rounded_rectangle([50, y, W - 50, y + row_h], radius=18, fill=WHITE,
                            outline=(225, 222, 214), width=2)
        d.rectangle([50, y, 62, y + row_h], fill=accent)
        d.text((92, y + 24), f"{i + 1}.  {label}",
               font=_font(30, 800), fill=accent)
        f, lines = _fit(d, text, max_w=W - 50 - 92 - 40, max_lines=3)
        ty = y + 78
        for ln in lines:
            d.text((92, ty), ln, font=f,
                   fill=INK if not quiet else (120, 126, 134))
            ty += f.size + 12

    # footer
    d.rectangle([0, H - 70, W, H], fill=NAVY)
    foot = "@trendradarng  •  Verified summaries, every morning"
    ff = _font(26, 600)
    d.text(((W - d.textlength(foot, font=ff)) / 2, H - 52), foot,
           font=ff, fill=WHITE)

    os.makedirs(out_dir, exist_ok=True)
    fname = f"brief_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    path = os.path.join(out_dir, fname)
    img.save(path, "JPEG", quality=90)
    return fname, path


# ---------------------------------------------------------------- routes ---
@brief_bp.route("/brief/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "lane": "naija-daily-brief"})


@brief_bp.route("/brief/render", methods=["POST"])
def render_route():
    data = request.get_json(force=True, silent=True) or {}
    date_label = (data.get("date_label") or "").strip()
    if not date_label:
        return jsonify({"error": "date_label is required"}), 400

    # contraction guard: refuse rather than publish off-house-style copy
    for key in ("traffic", "weather", "football"):
        val = (data.get(key) or "")
        if CONTRACTION_RE.search(val):
            return jsonify({"error": f"contraction detected in '{key}' slot",
                            "value": val}), 422

    static_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "static", "brief")
    fname, _ = render_brief_card(
        date_label,
        data.get("traffic", ""),
        data.get("weather", ""),
        data.get("football", ""),
        static_dir,
    )
    return jsonify({
        "filename": fname,
        "url": url_for("static", filename=f"brief/{fname}", _external=True),
    })
