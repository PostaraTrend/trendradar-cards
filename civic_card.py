"""Your Voice 2027 card — green-white-green Nigerian flag identity.

Routes:
  GET /render/civic         -> PNG 1080x1350
  GET /render/civic/health  -> JSON ok

Query params:
  headline  (required) card title, autoscaling serif, max 3 lines
  badge     (optional) format chip; unknown values fall back to YOUR VOICE 2027
  date      (optional) e.g. '15 Jul 2026'

House rules baked in: contraction gate ON (422; possessives pass),
party-neutral visual identity — the only symbols are the flag colours
and a ballot box. No party colours, no portraits, no logos.
"""

import io
import os
import re
import time

from flask import Blueprint, request, send_file, jsonify
from PIL import Image, ImageDraw, ImageFont

civic_bp = Blueprint("civic", __name__)

W, H = 1080, 1350
PAPER = (250, 250, 247)
GREEN = (0, 135, 81)          # Nigerian flag green
GREEN_DEEP = (0, 104, 63)
INK = (22, 28, 24)
MUTE = (110, 122, 114)

BAND_W = 170                   # flag side bands
COL_X0, COL_X1 = BAND_W + 44, W - BAND_W - 44   # content column

BADGES = {
    "YOUR VOTE COUNTS",
    "KNOW THE PROCESS",
    "CIVIC FACT",
    "FIRST-TIME VOTER",
}
DEFAULT_BADGE = "YOUR VOICE 2027"

# ---------------------------------------------------------------- fonts
_HERE = os.path.dirname(os.path.abspath(__file__))

def _font(candidates, size):
    """Repo-root fonts first (flat repo), then system fallbacks."""
    for name in candidates:
        for base in (_HERE, "/usr/share/fonts/truetype/dejavu"):
            p = os.path.join(base, name)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
    return ImageFont.load_default()

def serif(size):
    return _font(["Prospero-Bold.ttf", "PlayfairDisplay-Bold.ttf",
                  "DejaVuSerif-Bold.ttf"], size)

def sans(size, bold=False):
    if bold:
        return _font(["NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf"], size)
    return _font(["NotoSans-Regular.ttf", "DejaVuSans.ttf"], size)

# ---------------------------------------------------- contraction gate
_CONTRACTIONS = re.compile(
    r"\b(?:aren|can|couldn|didn|doesn|don|hadn|hasn|haven|isn|mustn|"
    r"needn|shan|shouldn|wasn|weren|won|wouldn)[\u2019']t\b"
    r"|\b(?:i|you|we|they|it|that|there|here|he|she|who|what|let)"
    r"[\u2019'](?:ll|re|ve|d|m|s)\b",
    re.IGNORECASE,
)

def _has_contraction(text):
    return bool(_CONTRACTIONS.search(text or ""))

# ----------------------------------------------------------- helpers
def _spaced(t, gap=1):
    return (" " * gap).join(list(t.replace(" ", "  ")))

def _ctext(d, y, text, font, fill, x0=COL_X0, x1=COL_X1):
    w = d.textlength(text, font=font)
    d.text((x0 + ((x1 - x0) - w) / 2, y), text, font=font, fill=fill)

def _wrap(d, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def _fit_headline(d, text, max_w):
    for size in range(78, 43, -4):
        f = serif(size)
        lines = _wrap(d, text, f, max_w)
        if len(lines) <= 3 and all(d.textlength(l, font=f) <= max_w for l in lines):
            return f, lines, size
    f = serif(44)
    return f, _wrap(d, text, f, max_w)[:3], 44

def _ballot_box(d, cx, cy, s, color):
    """Simple neutral ballot box: box with slot and a slip going in."""
    bw, bh = int(s * 1.15), int(s * 0.85)
    x0, y0 = cx - bw // 2, cy - bh // 2 + int(s * 0.18)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(s * 0.10),
                        outline=color, width=6)
    # slot
    sw = int(bw * 0.52)
    d.rounded_rectangle([cx - sw // 2, y0 - 4, cx + sw // 2, y0 + 10],
                        radius=6, fill=color)
    # slip entering the slot, tilted feel via simple rect + check mark
    pw, ph = int(bw * 0.40), int(s * 0.46)
    px0, py0 = cx - pw // 2, y0 - ph - int(s * 0.10)
    d.rounded_rectangle([px0, py0, px0 + pw, py0 + ph], radius=8,
                        outline=color, width=5, fill=PAPER)
    # check mark on the slip
    mx, my = cx, py0 + ph // 2
    d.line([(mx - int(pw * 0.22), my), (mx - int(pw * 0.05), my + int(ph * 0.22)),
            (mx + int(pw * 0.26), my - int(ph * 0.24))], fill=color, width=6)

# ------------------------------------------------------------- render
def _render(headline, badge, date_str):
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    # flag bands
    d.rectangle([0, 0, BAND_W, H], fill=GREEN)
    d.rectangle([W - BAND_W, 0, W, H], fill=GREEN)
    d.line([(BAND_W, 0), (BAND_W, H)], fill=GREEN_DEEP, width=4)
    d.line([(W - BAND_W, 0), (W - BAND_W, H)], fill=GREEN_DEEP, width=4)

    # masthead
    _ctext(d, 84, _spaced("TREND RADAR NG"), sans(24, bold=True), MUTE)
    _ctext(d, 130, _spaced("YOUR VOICE 2027"), sans(40, bold=True), GREEN_DEEP)
    d.line([(W / 2 - 130, 204), (W / 2 + 130, 204)], fill=GREEN, width=3)

    # badge chip
    chip_f = sans(28, bold=True)
    label = badge if badge in BADGES else DEFAULT_BADGE
    tw = d.textlength(label, font=chip_f)
    pad_x, chip_y, chip_h = 26, 244, 54
    cx0 = (W - (tw + pad_x * 2)) / 2
    d.rounded_rectangle([cx0, chip_y, cx0 + tw + pad_x * 2, chip_y + chip_h],
                        radius=27, outline=GREEN, width=3)
    d.text((cx0 + pad_x, chip_y + 11), label, font=chip_f, fill=GREEN)

    # headline
    max_w = COL_X1 - COL_X0
    hf, lines, size = _fit_headline(d, headline, max_w)
    lh = int(size * 1.22)
    block_h = lh * len(lines)
    hy = 400 + (280 - block_h) // 2      # vertically settle in its zone
    for i, ln in enumerate(lines):
        _ctext(d, hy + i * lh, ln, hf, INK)

    # dotted divider
    dy = 740
    for x in range(int(W / 2 - 150), int(W / 2 + 150), 22):
        d.ellipse([x, dy, x + 7, dy + 7], fill=GREEN)

    # ballot box motif
    _ballot_box(d, W // 2, 910, 150, GREEN)

    # tagline
    _ctext(d, 1080, "Your vote. Your voice. Your Nigeria.", serif(38), GREEN_DEEP)

    # footer
    _ctext(d, 1180, _spaced("PARTY NEUTRAL", 1) + "   •   " + _spaced("EVERY NIGERIAN COUNTS", 1),
           sans(20, bold=True), MUTE)
    if date_str:
        _ctext(d, 1240, date_str, sans(26), MUTE)

    return img

# -------------------------------------------------------------- routes
@civic_bp.route("/render/civic")
def render_civic():
    headline = (request.args.get("headline") or "").strip()
    badge = (request.args.get("badge") or "").strip().upper()
    date_str = (request.args.get("date") or "").strip()

    if not headline:
        return jsonify(error="headline is required"), 422
    if len(headline) > 90:
        return jsonify(error="headline too long (max 90 chars)"), 422
    if _has_contraction(headline):
        return jsonify(error="contractions are not allowed in headline"), 422

    img = _render(headline, badge, date_str)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    fname = "civic_%s.png" % str(time.time()).replace(".", "")
    return send_file(buf, mimetype="image/png",
                     download_name=fname)

@civic_bp.route("/render/civic/health")
def civic_health():
    try:
        img = _render("Health Check Headline", "CIVIC FACT", "1 Jan 2027")
        ok = img.size == (W, H)
        return jsonify(status="ok" if ok else "degraded", card="civic",
                       size=list(img.size))
    except Exception as e:                                  # pragma: no cover
        return jsonify(status="error", card="civic", detail=str(e)), 500
