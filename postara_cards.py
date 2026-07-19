"""
PostaraTrend page card renderer — the PostaraTrend card family.

Blueprint: postara_bp   (name unchanged — registers exactly as before)
Routes:
    GET  /postara/health
    POST /receipts/render   {"week_label","posts","lanes","human_touches","top_lane"}
    POST /tips/render       {"tip_number","tip_title","tip_body"}
    POST /render/postara    {"layout","badge","headline","kicker","date", ...}
                            layout=headline -> badge + headline + kicker
                            layout=stats    -> badge + figure + unit + headline + lanes[]

v2.0 (Jul 2026)
    - Brand tokens taken verbatim from PostaraTrend/Landing-Page@main index.html :root.
      The previous NAVY/EMERALD were approximations and AMBER/CREAM were not brand
      colours at all (amber is TRNG's accent).
    - Bricolage Grotesque 800 (wordmark + headline) + Geist (body), matching the site.
    - Canvas 1080x1350 (4:5) per the house publishing rule for photo posts.
    - NO import-time font download. Fonts are committed to the repo root. The old
      _ensure_font() ran at import and could raise on a cold boot, which would take
      app.py — and therefore every TRNG lane — down with it. Font loading is now lazy
      and falls back to DejaVu rather than raising.
    - Route signatures, payload keys and JSON responses are unchanged.

Register in app.py:  from postara_cards import postara_bp
                     app.register_blueprint(postara_bp)
"""

import os
import random
import re
from datetime import datetime

from flask import Blueprint, jsonify, request, url_for
from PIL import Image, ImageChops, ImageDraw, ImageFont

postara_bp = Blueprint("postara", __name__)

# ---------------------------------------------------------------- fonts
# The repo is flat: fonts live at the repo root. Root first, fonts/ second,
# DejaVu last. Never raise at import time.
_HERE = os.path.dirname(os.path.abspath(__file__))
_DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _find(name):
    for cand in (os.path.join(_HERE, name),
                 os.path.join(_HERE, "fonts", name)):
        if os.path.exists(cand):
            return cand
    return None


BRICOLAGE = _find("BricolageGrotesque.ttf")
GEIST_REG = _find("Geist-Regular.ttf")
GEIST_MED = _find("Geist-Medium.ttf")


def _fallback(size):
    try:
        return ImageFont.truetype(_DEJAVU, size)
    except Exception:
        return ImageFont.load_default()


def bric(size, weight=800):
    """Bricolage Grotesque — variable (opsz 12-96, wght 200-800, wdth 75-100)."""
    if not BRICOLAGE:
        return _fallback(size)
    try:
        f = ImageFont.truetype(BRICOLAGE, size)
        f.set_variation_by_axes([min(96, max(12, size)), weight, 100])
        return f
    except Exception:
        return _fallback(size)


def geist(size, med=False):
    path = GEIST_MED if med else GEIST_REG
    if not path:
        return _fallback(size)
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return _fallback(size)


def fonts_ready():
    return bool(BRICOLAGE and GEIST_REG and GEIST_MED)


# ------------------------------------------------------- brand tokens
# Source: PostaraTrend/Landing-Page@main index.html  :root
NAVY = (26, 58, 107)      # --navy  #1A3A6B
ND = (17, 43, 84)         # --nd    #112B54
NBG = (19, 48, 90)        # --nbg   #13305A   (site body background)
GREEN = (29, 158, 117)    # --green #1D9E75
DKG = (15, 110, 86)       # --dkg   #0F6E56
LTG = (93, 202, 165)      # --ltg   #5DCAA5
PLG = (163, 228, 204)     # --plg   #A3E4CC
WHITE = (255, 255, 255)
DIM = (255, 255, 255, 199)      # rgba(255,255,255,.78)
MUT = (255, 255, 255, 128)      # rgba(255,255,255,.5)
LN = (29, 158, 117, 64)         # rgba(29,158,117,.25)

W, H = 1080, 1350
MARGIN = 84

# Known badges per lane. Unknown badge falls back to the house chip rather
# than 422 — same tolerance as civic_card.
BADGES = {
    # Trend Pulse Canada
    "TREND PULSE", "RISING SIGNAL", "MARKET READ", "WHAT IT MEANS",
    # The Suppression Log
    "SUPPRESSION LOG", "QUALITY GATE", "WHAT WE REFUSED", "GATE REPORT",
    # Fleet Proof / Autopilot Receipts
    "RECEIPTS", "FLEET PROOF",
    # Calgary SMB Signal
    "FIELD SIGNAL", "SCAN REPORT",
    # SMB Tips / site Insights
    "SMB TIP", "INSIGHT",
}
BADGE_FALLBACK = "POSTARATREND"

CONTRACTION_RE = re.compile(
    r"(?:\b\w+['\u2019](?:t|re|ve|ll|d|m)\b)"
    r"|(?:\b(?:it|that|what|here|there|he|she|who|let|this)['\u2019]s\b)",
    re.IGNORECASE)
# Two arms, because a bare 's is ambiguous:
#   arm 1 — unambiguous auxiliaries (can't, we've, you're, they'll, it'd, I'm)
#   arm 2 — only the pronoun/interrogative forms of 's (it's, that's, what's...)
# A possessive must pass: "the platform's decision" is not a contraction, and
# 422-ing on it would block legitimate copy.


# ------------------------------------------------------------ helpers
def _tracked(draw, xy, text, font, fill, tracking=0.0):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


def _tracked_w(draw, text, font, tracking=0.0):
    if not text:
        return 0
    return sum(draw.textlength(c, font=font) + tracking for c in text) - tracking


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


def _grain(img, amount=9):
    """Film grain. The site runs fractalNoise at .035 with mix-blend-mode:overlay.
    Zero-mean delta — a 0-255 noise blend washes the navy toward grey."""
    rnd = random.Random(7)
    n = Image.new("L", (140, 140))
    n.putdata([128 + rnd.randint(-amount, amount) for _ in range(140 * 140)])
    n = n.resize((W, H), Image.NEAREST)
    return ImageChops.overlay(img, Image.merge("RGB", (n, n, n)))


def _save(img, out_dir, prefix):
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
    fname = f"{prefix}_{stamp}.png"
    path = os.path.join(out_dir, fname)
    img.save(path, "PNG")
    # Instagram's image_url ingestion accepts JPEG only; Facebook takes the PNG
    # as-is. Write a JPEG twin alongside so the IG publisher can point at it.
    # RGB flatten mirrors the app-wide _send_image() helper. Additive: the PNG
    # and its url() are unchanged, so every existing Facebook lane is untouched.
    img.convert("RGB").save(
        os.path.join(out_dir, f"{prefix}_{stamp}.jpg"), "JPEG", quality=92)
    return fname, path


def _static_dir():
    return os.path.join(_HERE, "static", "postara")


# ------------------------------------------------------- card furniture
def _logo(draw, x, y, size):
    """The site's inline SVG mark: rounded navy tile, four ascending bars,
    arrowhead. Original viewBox 0 0 120 120."""
    s = size / 120.0

    def r(x0, y0, w0, h0, rad, fill):
        draw.rounded_rectangle(
            [x + x0 * s, y + y0 * s, x + (x0 + w0) * s, y + (y0 + h0) * s],
            radius=max(1, rad * s), fill=fill)

    r(0, 0, 120, 120, 24, NAVY)
    r(20, 70, 16, 30, 3, LTG)
    r(42, 50, 16, 50, 3, GREEN)
    r(64, 30, 16, 70, 3, DKG)
    r(86, 14, 16, 86, 3, WHITE)
    draw.polygon([(x + 94 * s, y + 10 * s), (x + 84 * s, y + 18 * s),
                  (x + 104 * s, y + 18 * s)], fill=DKG)


def _base():
    img = Image.new("RGBA", (W, H), NBG + (255,))
    d = ImageDraw.Draw(img)
    for i in range(300):                       # nav-band wash, like the site
        d.line([0, i, W, i], fill=ND + (int(70 * (1 - i / 300)),))
    return img, d


def _masthead(img, d):
    y = MARGIN
    _logo(d, MARGIN, y, 92)
    tx = MARGIN + 92 + 26
    f = bric(46, 800)
    d.text((tx, y + 4), "Postara", font=f, fill=WHITE)
    d.text((tx + d.textlength("Postara", font=f), y + 4), "Trend",
           font=f, fill=GREEN)
    _tracked(d, (tx + 3, y + 62), "TECHNOLOGIES", geist(17, med=True),
             LTG, tracking=4.2)


def _badge(d, label, y):
    label = (label or "").strip().upper()
    if label not in BADGES:
        label = BADGE_FALLBACK
    f = geist(21, med=True)
    tw = _tracked_w(d, label, f, 3.0)
    h = 52
    d.rounded_rectangle([MARGIN, y, MARGIN + tw + 52, y + h],
                        radius=h // 2, outline=GREEN, width=2)
    _tracked(d, (MARGIN + 26, y + 15), label, f, LTG, tracking=3.0)
    return y + h


def _hairline(img, y):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).line([MARGIN, y, W - MARGIN, y], fill=LN, width=2)
    img.alpha_composite(ov)


def _headline(d, text, y_top, y_max, start=82, floor=44):
    size = start
    while size >= floor:
        f = bric(size, 800)
        lines = _wrap(d, text, f, W - MARGIN * 2)
        lh = int(size * 1.16)
        if len(lines) <= 4 and y_top + lh * len(lines) <= y_max:
            for i, ln in enumerate(lines):
                d.text((MARGIN, y_top + i * lh), ln, font=f, fill=WHITE)
            return y_top + lh * len(lines)
        size -= 3
    f = bric(floor, 800)
    lines = _wrap(d, text, f, W - MARGIN * 2)[:4]
    lh = int(floor * 1.16)
    for i, ln in enumerate(lines):
        d.text((MARGIN, y_top + i * lh), ln, font=f, fill=WHITE)
    return y_top + lh * len(lines)


def _footer(img, d, date_str=""):
    y = H - MARGIN - 62
    _hairline(img, y - 30)
    _tracked(d, (MARGIN, y), "N 51.0447 · W 114.0719 · SIG ↑",
             geist(18, med=True), LTG, tracking=1.6)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d2 = ImageDraw.Draw(ov)
    f = geist(18)
    txt = "postaratrend.ca · Calgary, Alberta"
    d2.text((W - MARGIN - d2.textlength(txt, font=f), y), txt, font=f, fill=MUT)
    if date_str:
        d2.text((W - MARGIN - d2.textlength(date_str, font=f), y - 34),
                date_str, font=f, fill=MUT)
    img.alpha_composite(ov)
    for i in range(180):                       # rising accent rule
        t = i / 180
        c = tuple(int(LTG[k] + (GREEN[k] - LTG[k]) * t) for k in range(3))
        d.line([MARGIN + i, y + 46, MARGIN + i, y + 49], fill=c)


# ------------------------------------------------------------- layouts
def _body(d, text, y_top, y_max, start=26, floor=18):
    """Wrapped, autoscaling body/kicker text. SMB Tips pushes long-form copy
    through this, so it must wrap — an unwrapped line runs off the canvas."""
    size = start
    while size >= floor:
        f = geist(size)
        lines = _wrap(d, text, f, W - MARGIN * 2)
        lh = int(size * 1.38)
        if y_top + lh * len(lines) <= y_max:
            return f, lines, lh
        size -= 1
    f = geist(floor)
    lines = _wrap(d, text, f, W - MARGIN * 2)
    lh = int(floor * 1.38)
    max_lines = max(1, (y_max - y_top) // lh)
    return f, lines[:max_lines], lh


def _kicker_height(d, text, start=26):
    if not text:
        return 0
    f = geist(start)
    lines = _wrap(d, text, f, W - MARGIN * 2)
    return 34 + int(start * 1.38) * len(lines)     # hairline gap + block


def render_headline_card(badge, headline, kicker, out_dir, date_str="",
                         prefix="postara"):
    img, d = _base()
    _masthead(img, d)
    y = _badge(d, badge, 300)
    kicker = (kicker or "").strip()
    body_floor = H - MARGIN - 190                   # keep clear of the footer
    # Reserve the kicker's space first, so a long body cannot be pushed off-card.
    reserve = _kicker_height(d, kicker) + 40 if kicker else 0
    y = _headline(d, headline, y + 54, body_floor - reserve)
    if kicker:
        _hairline(img, y + 40)
        f, lines, lh = _body(d, kicker, y + 74, body_floor)
        ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d2 = ImageDraw.Draw(ov)
        for i, ln in enumerate(lines):
            d2.text((MARGIN, y + 74 + i * lh), ln, font=f, fill=DIM)
        img.alpha_composite(ov)
    _footer(img, d, date_str)
    return _save(_grain(img.convert("RGB")), out_dir, prefix)


def render_stats_card(badge, figure, unit, headline, lanes, out_dir,
                      date_str="", prefix="postara"):
    img, d = _base()
    _masthead(img, d)
    y = _badge(d, badge, 300)
    f = bric(230, 800)
    d.text((MARGIN, y + 44), str(figure), font=f, fill=WHITE)
    fw = d.textlength(str(figure), font=f)
    if unit:
        d.text((MARGIN + fw + 18, y + 150), str(unit), font=bric(46, 800),
               fill=GREEN)
    y2 = y + 294
    _hairline(img, y2)
    y2 = _headline(d, headline, y2 + 40, H - 460, start=64, floor=40)
    ys = y2 + 60
    f2 = geist(22, med=True)
    for i, item in enumerate((lanes or [])[:6]):
        if isinstance(item, dict):
            name, n = item.get("name", ""), item.get("count", "")
        else:
            name, n = item[0], item[1]
        yy = ys + i * 46
        if yy > H - MARGIN - 150:
            break
        d.text((MARGIN, yy), str(name), font=f2, fill=LTG)
        nt = str(n)
        d.text((W - MARGIN - d.textlength(nt, font=f2), yy), nt, font=f2,
               fill=WHITE)
    _footer(img, d, date_str)
    return _save(_grain(img.convert("RGB")), out_dir, prefix)


# ------------------------------------------ legacy lanes, re-skinned
def render_receipts_card(week_label, posts, lanes, human_touches,
                         top_lane, out_dir):
    return render_stats_card(
        "RECEIPTS", posts, "posts",
        "Published this week. Zero manual touches.",
        [("Content lanes", lanes), ("Human touches", human_touches),
         ("Busiest lane", top_lane)],
        out_dir, date_str=str(week_label or ""), prefix="receipts")


def render_tip_card(tip_number, tip_title, tip_body, out_dir):
    return render_headline_card(
        "SMB TIP", tip_title, tip_body, out_dir,
        date_str=f"No. {tip_number}", prefix="tip")


# -------------------------------------------------------------- routes
def _guard(data, keys):
    for key in keys:
        val = str(data.get(key) or "")
        if CONTRACTION_RE.search(val):
            return key, val
    return None, None


def _url(fname):
    jpg = fname.rsplit(".", 1)[0] + ".jpg"
    return jsonify({"filename": fname,
                    "url": url_for("static", filename=f"postara/{fname}",
                                   _external=True),
                    "url_jpg": url_for("static", filename=f"postara/{jpg}",
                                       _external=True)})


@postara_bp.route("/postara/health", methods=["GET"])
def health():
    return jsonify({
        "ok": bool(fonts_ready()),
        "version": "2.1",
        "lanes": ["autopilot-receipts", "smb-tips", "trend-pulse",
                  "suppression-log", "fleet-proof", "calgary-smb-signal",
                  "insight"],
        "fonts": {"bricolage": bool(BRICOLAGE), "geist_regular": bool(GEIST_REG),
                  "geist_medium": bool(GEIST_MED)},
        "canvas": f"{W}x{H}",
        "badges": sorted(BADGES),
    })


@postara_bp.route("/receipts/render", methods=["POST"])
def receipts_route():
    data = request.get_json(force=True, silent=True) or {}
    for k in ("week_label", "posts", "lanes", "human_touches"):
        if str(data.get(k, "")).strip() == "":
            return jsonify({"error": f"{k} is required"}), 400
    bad_key, bad_val = _guard(data, ("week_label", "top_lane"))
    if bad_key:
        return jsonify({"error": f"contraction detected in '{bad_key}'",
                        "value": bad_val}), 422
    fname, _ = render_receipts_card(
        data["week_label"], data["posts"], data["lanes"],
        data["human_touches"], data.get("top_lane", "—"), _static_dir())
    return _url(fname)


@postara_bp.route("/tips/render", methods=["POST"])
def tips_route():
    data = request.get_json(force=True, silent=True) or {}
    for k in ("tip_number", "tip_title", "tip_body"):
        if str(data.get(k, "")).strip() == "":
            return jsonify({"error": f"{k} is required"}), 400
    bad_key, bad_val = _guard(data, ("tip_title", "tip_body"))
    if bad_key:
        return jsonify({"error": f"contraction detected in '{bad_key}'",
                        "value": bad_val}), 422
    fname, _ = render_tip_card(
        data["tip_number"], data["tip_title"], data["tip_body"], _static_dir())
    return _url(fname)


@postara_bp.route("/render/postara", methods=["POST"])
def postara_route():
    data = request.get_json(force=True, silent=True) or {}
    layout = str(data.get("layout") or "headline").strip().lower()
    if str(data.get("headline", "")).strip() == "":
        return jsonify({"error": "headline is required"}), 400
    bad_key, bad_val = _guard(data, ("headline", "kicker", "unit"))
    if bad_key:
        return jsonify({"error": f"contraction detected in '{bad_key}'",
                        "value": bad_val}), 422
    date_str = str(data.get("date") or "")
    try:
        if layout == "stats":
            if str(data.get("figure", "")).strip() == "":
                return jsonify({"error": "figure is required for layout=stats"}), 400
            fname, _ = render_stats_card(
                data.get("badge"), data["figure"], data.get("unit", ""),
                data["headline"], data.get("lanes") or [], _static_dir(),
                date_str)
        elif layout == "headline":
            fname, _ = render_headline_card(
                data.get("badge"), data["headline"], data.get("kicker", ""),
                _static_dir(), date_str)
        else:
            return jsonify({"error": "layout must be 'headline' or 'stats'"}), 400
    except Exception as exc:                      # noqa: BLE001
        return jsonify({"error": f"render failed: {exc}"}), 500
    return _url(fname)
