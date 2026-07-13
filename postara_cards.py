"""
PostaraTrend page card renderer — Autopilot Receipts + SMB Tips.

Blueprint: postara_bp
Routes:
    GET  /postara/health
    POST /receipts/render   {"week_label","posts","lanes","human_touches","top_lane"}
    POST /tips/render       {"tip_number","tip_title","tip_body"}

Same house patterns as daily_brief_cards.py: self-downloading Outfit font,
contraction guard (422), microsecond JPEG filenames, static/postara/ output.
Register in app.py:  from postara_cards import postara_bp
                     app.register_blueprint(postara_bp)
"""

import os
import re
import urllib.request
from datetime import datetime

from flask import Blueprint, jsonify, request, url_for
from PIL import Image, ImageDraw, ImageFont

postara_bp = Blueprint("postara", __name__)

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_PATH = os.path.join(FONT_DIR, "Outfit.ttf")
FONT_URL = ("https://raw.githubusercontent.com/google/fonts/main/"
            "ofl/outfit/Outfit%5Bwght%5D.ttf")


def _ensure_font():
    os.makedirs(FONT_DIR, exist_ok=True)
    if not os.path.exists(FONT_PATH):
        req = urllib.request.Request(
            FONT_URL, headers={"User-Agent": "PostaraTrend-card-renderer/1.0"})
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


W = H = 1080
NAVY = (24, 56, 104)        # 183868 — PostaraTrend brand navy
DEEP = (14, 34, 66)
EMERALD = (24, 160, 112)    # 18A070
AMBER = (245, 166, 35)
CREAM = (247, 245, 240)
WHITE = (255, 255, 255)
GREY = (150, 168, 196)

CONTRACTION_RE = re.compile(
    r"\b\w+['\u2019](?:t|s|re|ve|ll|d|m)\b", re.IGNORECASE)


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


def _fit(draw, text, max_w, max_lines, start=46, floor=30, weight=600):
    size = start
    while size >= floor:
        f = _font(size, weight)
        lines = _wrap(draw, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
        size -= 2
    f = _font(floor, weight)
    return f, _wrap(draw, text, f, max_w)[:max_lines]


def _save(img, out_dir, prefix):
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    path = os.path.join(out_dir, fname)
    img.save(path, "JPEG", quality=90)
    return fname, path


def render_receipts_card(week_label, posts, lanes, human_touches,
                         top_lane, out_dir):
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    # subtle deep band top and bottom
    d.rectangle([0, 0, W, 170], fill=DEEP)
    d.rectangle([0, H - 90, W, H], fill=DEEP)

    d.text((60, 44), "AUTOPILOT RECEIPTS", font=_font(52, 800), fill=WHITE)
    d.text((60, 116), week_label.upper(), font=_font(26, 600), fill=AMBER)

    # hero number
    hero = str(posts)
    hf = _font(300, 800)
    hw = d.textlength(hero, font=hf)
    d.text(((W - hw) / 2, 200), hero, font=hf, fill=EMERALD)
    sub = "POSTS PUBLISHED THIS WEEK"
    sf = _font(34, 700)
    d.text(((W - d.textlength(sub, font=sf)) / 2, 560), sub,
           font=sf, fill=WHITE)

    # stat row
    stats = [
        (str(lanes), "content lanes"),
        (str(human_touches), "human touches"),
        (top_lane, "busiest lane"),
    ]
    col_w = (W - 120) / 3
    y0 = 680
    for i, (big, small) in enumerate(stats):
        cx = 60 + i * col_w + col_w / 2
        bf = _font(64 if len(big) <= 3 else 40, 800)
        d.text((cx - d.textlength(big, font=bf) / 2, y0), big,
               font=bf, fill=AMBER)
        smf = _font(24, 600)
        d.text((cx - d.textlength(small, font=smf) / 2, y0 + 84), small,
               font=smf, fill=GREY)

    line = "Designed once. Publishing daily. Zero staff required."
    lf, lines = _fit(d, line, W - 160, 2, start=34, floor=26, weight=600)
    ty = 860
    for ln in lines:
        d.text(((W - d.textlength(ln, font=lf)) / 2, ty), ln,
               font=lf, fill=WHITE)
        ty += lf.size + 10

    foot = "postaratrend.ca  •  Autopilot Social for small business"
    ff = _font(24, 600)
    d.text(((W - d.textlength(foot, font=ff)) / 2, H - 62), foot,
           font=ff, fill=GREY)
    return _save(img, out_dir, "receipts")


def render_tip_card(tip_number, tip_title, tip_body, out_dir):
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 190], fill=NAVY)
    d.text((60, 42), f"SMB TIP #{tip_number}", font=_font(56, 800),
           fill=WHITE)
    d.text((60, 122), "PRACTICAL SOCIAL MEDIA, NO JARGON",
           font=_font(24, 600), fill=AMBER)

    # title
    tf, tlines = _fit(d, tip_title, W - 160, 3, start=58, floor=40,
                      weight=800)
    y = 260
    for ln in tlines:
        d.text((80, y), ln, font=tf, fill=(24, 32, 44))
        y += tf.size + 12
    d.rectangle([80, y + 14, 320, y + 22], fill=EMERALD)
    y += 60

    # body
    bf, blines = _fit(d, tip_body, W - 160, 8, start=38, floor=28,
                      weight=500)
    for ln in blines:
        d.text((80, y), ln, font=bf, fill=(60, 70, 84))
        y += bf.size + 14

    d.rectangle([0, H - 90, W, H], fill=NAVY)
    foot = "postaratrend.ca  •  Your page, publishing itself"
    ff = _font(24, 600)
    d.text(((W - d.textlength(foot, font=ff)) / 2, H - 62), foot,
           font=ff, fill=GREY)
    return _save(img, out_dir, "tip")


def _guard(data, keys):
    for key in keys:
        val = str(data.get(key) or "")
        if CONTRACTION_RE.search(val):
            return key, val
    return None, None


@postara_bp.route("/postara/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "lanes": ["autopilot-receipts", "smb-tips"]})


@postara_bp.route("/receipts/render", methods=["POST"])
def receipts_route():
    data = request.get_json(force=True, silent=True) or {}
    for req_key in ("week_label", "posts", "lanes", "human_touches"):
        if str(data.get(req_key, "")).strip() == "":
            return jsonify({"error": f"{req_key} is required"}), 400
    bad_key, bad_val = _guard(data, ("week_label", "top_lane"))
    if bad_key:
        return jsonify({"error": f"contraction detected in '{bad_key}'",
                        "value": bad_val}), 422
    static_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "static", "postara")
    fname, _ = render_receipts_card(
        data["week_label"], data["posts"], data["lanes"],
        data["human_touches"], data.get("top_lane", "—"), static_dir)
    return jsonify({"filename": fname,
                    "url": url_for("static", filename=f"postara/{fname}",
                                   _external=True)})


@postara_bp.route("/tips/render", methods=["POST"])
def tips_route():
    data = request.get_json(force=True, silent=True) or {}
    for req_key in ("tip_number", "tip_title", "tip_body"):
        if str(data.get(req_key, "")).strip() == "":
            return jsonify({"error": f"{req_key} is required"}), 400
    bad_key, bad_val = _guard(data, ("tip_title", "tip_body"))
    if bad_key:
        return jsonify({"error": f"contraction detected in '{bad_key}'",
                        "value": bad_val}), 422
    static_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "static", "postara")
    fname, _ = render_tip_card(
        data["tip_number"], data["tip_title"], data["tip_body"], static_dir)
    return jsonify({"filename": fname,
                    "url": url_for("static", filename=f"postara/{fname}",
                                   _external=True)})
