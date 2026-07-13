"""
People's Verdict card renderer — Trend Radar NG
Blueprint for the trendradar-cards Flask service.

Register in app.py:
    from verdict_card import verdict_bp
    app.register_blueprint(verdict_bp)

Routes:
    GET  /verdict/health
    POST /verdict/render   (JSON body)
    GET  /verdict/render   (query params, for browser testing)

Params: title, summary, comments_count, date_label, format (png|jpg)
Returns: {"url": "<public url>", "filename": "..."}
"""

import os
import io
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from PIL import Image, ImageDraw, ImageFont

verdict_bp = Blueprint("verdict", __name__)

# ---- Brand ----
NAVY = (14, 40, 65)        # #0E2841
GOLD = (240, 180, 41)      # #F0B429
WHITE = (255, 255, 255)
SOFT = (203, 213, 225)     # muted body text

W, H = 1080, 1350
MARGIN = 80
SAFE_W = W - 2 * MARGIN    # 920px safe text width

FONT_DIRS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts"),
    "fonts",
    "/app/fonts",
    "/usr/share/fonts/truetype/poppins",
    "/usr/share/fonts/truetype/dejavu",
]


def _font(size, weight="regular"):
    names = {
        "bold": ["Poppins-Bold.ttf", "DejaVuSans-Bold.ttf"],
        "semibold": ["Poppins-SemiBold.ttf", "Poppins-Bold.ttf", "DejaVuSans-Bold.ttf"],
        "regular": ["Poppins-Regular.ttf", "DejaVuSans.ttf"],
    }[weight]
    for d in FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _text_w(draw, text, font):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l


def _wrap(draw, text, font, max_width, max_lines):
    """Pixel-measured word wrap. Returns (lines, truncated_flag)."""
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _text_w(draw, trial, font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    truncated = len(" ".join(lines)) < len(" ".join(words))
    if truncated and lines:
        last = lines[-1]
        while _text_w(draw, last + "...", font) > max_width and " " in last:
            last = last.rsplit(" ", 1)[0]
        lines[-1] = last + "..."
    return lines, truncated


def _draw_card(title, summary, comments_count, date_label, camps=None):
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)

    # Subtle deterministic starfield (matches Receipts card family)
    seed = 1250624
    for i in range(90):
        seed = (seed * 1103515245 + 12345) % (2 ** 31)
        x = seed % W
        seed = (seed * 1103515245 + 12345) % (2 ** 31)
        y = seed % H
        if 130 < y < H - 140:
            continue  # keep the text zone clean
        d.ellipse([x, y, x + 2, y + 2], fill=(40, 70, 100))

    # Top gold bar
    d.rectangle([0, 0, W, 14], fill=GOLD)

    # Kicker
    f_kicker = _font(46, "bold")
    kicker = "P E O P L E ' S   V E R D I C T"
    d.text((MARGIN, 84), kicker, font=f_kicker, fill=GOLD)

    # Date label
    y = 84 + 46 + 26
    if date_label:
        f_date = _font(30, "regular")
        d.text((MARGIN, y), str(date_label), font=f_date, fill=SOFT)
        y += 30 + 44
    else:
        y += 30

    # Title (max 3 lines with chart, 4 without; shrink font if it will not fit)
    max_t = 3 if camps else 4
    t_size = 62
    f_title = _font(t_size, "bold")
    title_lines, t_trunc = _wrap(d, title, f_title, SAFE_W, max_t)
    while t_trunc and t_size > 44:
        t_size -= 6
        f_title = _font(t_size, "bold")
        title_lines, t_trunc = _wrap(d, title, f_title, SAFE_W, max_t)
    for line in title_lines:
        d.text((MARGIN, y), line, font=f_title, fill=WHITE)
        y += t_size + 16

    # Gold divider
    y += 22
    d.rectangle([MARGIN, y, MARGIN + 180, y + 8], fill=GOLD)
    y += 8 + 44

    # Summary (max 4 lines with chart, 9 without)
    f_body = _font(40, "regular")
    body_lines, _ = _wrap(d, summary, f_body, SAFE_W, 4 if camps else 9)
    for line in body_lines:
        d.text((MARGIN, y), line, font=f_body, fill=SOFT)
        y += 40 + 18

    if camps:
        # ---- Share of voice bar chart ----
        y += 26
        f_head = _font(32, "bold")
        d.text((MARGIN, y), "S H A R E   O F   V O I C E", font=f_head, fill=GOLD)
        y += 32 + 30

        f_label = _font(34, "semibold")
        f_pct = _font(34, "bold")
        track_h = 26
        # top 3 camps by percentage
        rows = sorted(camps, key=lambda c: -float(c.get("pct", 0)))[:3]
        for c in rows:
            label = str(c.get("label", "")).strip()
            try:
                pct = max(0, min(100, float(c.get("pct", 0))))
            except (TypeError, ValueError):
                pct = 0
            pct_txt = "{}%".format(int(round(pct)))
            pw = _text_w(d, pct_txt, f_pct)
            # label row: label left, percentage right
            lab_lines, _ = _wrap(d, label, f_label, SAFE_W - pw - 30, 1)
            d.text((MARGIN, y), lab_lines[0] if lab_lines else "", font=f_label, fill=WHITE)
            d.text((W - MARGIN - pw, y), pct_txt, font=f_pct, fill=GOLD)
            y += 34 + 12
            # bar track + gold fill
            d.rounded_rectangle([MARGIN, y, MARGIN + SAFE_W, y + track_h], radius=13, fill=(30, 58, 88))
            fill_w = int(SAFE_W * pct / 100.0)
            if fill_w > track_h:
                d.rounded_rectangle([MARGIN, y, MARGIN + fill_w, y + track_h], radius=13, fill=GOLD)
            elif fill_w > 0:
                d.ellipse([MARGIN, y, MARGIN + track_h, y + track_h], fill=GOLD)
            y += track_h + 30

        # stat under the chart
        if comments_count:
            f_stat = _font(30, "semibold")
            d.text((MARGIN, y), "Collated from {} community voices".format(comments_count), font=f_stat, fill=SOFT)
    else:
        # Stat line (chartless layout)
        if comments_count:
            f_stat = _font(34, "semibold")
            stat = "Collated from {} community voices".format(comments_count)
            sy = H - 210
            d.text((MARGIN, sy), stat, font=f_stat, fill=GOLD)

    # Footer
    d.rectangle([0, H - 96, W, H - 86], fill=GOLD)
    f_footer = _font(30, "semibold")
    footer = "PEOPLE'S VERDICT  \u2022  TREND RADAR NG"
    fw = _text_w(d, footer, f_footer)
    d.text(((W - fw) // 2, H - 68), footer, font=f_footer, fill=WHITE)

    return img


def _save_and_url(img, fmt):
    fmt = "jpg" if str(fmt).lower() in ("jpg", "jpeg") else "png"
    fname = "verdict_{}.{}".format(datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f"), fmt)
    static_dir = os.path.join(current_app.root_path, "static", "cards")
    os.makedirs(static_dir, exist_ok=True)
    path = os.path.join(static_dir, fname)
    if fmt == "jpg":
        img.convert("RGB").save(path, "JPEG", quality=92)
    else:
        img.save(path, "PNG")
    base = request.host_url.rstrip("/")
    return {"url": "{}/static/cards/{}".format(base, fname), "filename": fname}


@verdict_bp.route("/verdict/health", methods=["GET"])
def verdict_health():
    return jsonify({"status": "ok", "lane": "peoples-verdict"})


@verdict_bp.route("/verdict/render", methods=["GET", "POST"])
def verdict_render():
    data = request.get_json(silent=True) or {}
    g = lambda k, default="": data.get(k, request.args.get(k, default))
    title = g("title", "The People Have Spoken")
    summary = g("summary", "")
    comments_count = g("comments_count", "")
    date_label = g("date_label", "")
    fmt = g("format", "png")
    camps = data.get("camps")
    if camps is None:
        import json as _json
        raw_c = request.args.get("camps", "")
        if raw_c:
            try:
                camps = _json.loads(raw_c)
            except ValueError:
                camps = None
    if camps is not None and not isinstance(camps, list):
        camps = None
    if not summary:
        return jsonify({"error": "summary is required"}), 400
    img = _draw_card(title, summary, comments_count, date_label, camps)
    return jsonify(_save_and_url(img, fmt))
