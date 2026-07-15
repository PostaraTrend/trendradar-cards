"""
Daily Blessing lane card — Trend Radar NG
GET/POST /render/blessing -> binary PNG (default) or JPEG with format=jpg
GET /render/blessing/health -> {"status": "ok"}

Three moods, one card: a dawn palette for the Morning Blessing (indigo sky
warming to amber, a rising glow on the horizon), a daylight palette for
Midday Strength (deep midday blue, a high gold sun), and a dusk palette for
Evening Grace (deep violet night, quiet stars). Centered, devotional
layout — serif pull quote, format chip, theme line. Interfaith by design:
light-based motifs only, no religious symbols of any faith. 4:5 photo post.

Expected query params (GET) or JSON body (POST):
  pull_quote  (required)  the strongest line, max ~140 chars recommended
  theme_title (optional)  short title line under the quote
  slot        (optional)  MORNING | MIDDAY | EVENING (default MORNING) — picks the palette
  badge       (optional)  format chip: MORNING BLESSING | DECLARATION | VERSE OF HOPE |
                          HOLD ON | MIDDAY STRENGTH | STAY THE COURSE |
                          EVENING GRACE | GRATITUDE | REST PRAYER
                          (default by slot: MORNING BLESSING / MIDDAY STRENGTH / EVENING GRACE)
  date        (optional)  e.g. "15 Jul 2026"
  handle      (optional)  default fb.com/TrendRadarNG

Contraction gate is ON for this route (422 on failure): the lane writes
English. Possessives pass; only genuine contractions are rejected.

Register in app.py, next to the other lanes:
    from blessing_card import blessing_bp
    app.register_blueprint(blessing_bp)
"""
import re
from io import BytesIO
from datetime import datetime

from flask import Blueprint, request, send_file, Response
from PIL import Image, ImageDraw, ImageFont

blessing_bp = Blueprint("blessing", __name__)

W, H = 1080, 1350  # 4:5 photo post
GOLD = (240, 180, 41)          # house gold
CREAM = (247, 241, 228)        # quote white
SOFT = (203, 197, 182)         # muted supporting text
MARGIN = 90
SAFE_W = W - 2 * MARGIN

# dawn (morning): pre-dawn indigo warming toward an amber horizon
DAWN_TOP = (21, 26, 56)
DAWN_BOTTOM = (84, 54, 18)
# day (midday): deep working-hours blue under a high sun
DAY_TOP = (24, 50, 100)
DAY_BOTTOM = (13, 27, 56)
# dusk (evening): deep night violet settling into indigo
DUSK_TOP = (13, 17, 44)
DUSK_BOTTOM = (44, 32, 78)

FONT_CANDIDATES = {
    "bold": ["Poppins-Bold.ttf", "fonts/Poppins-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "medium": ["Poppins-Medium.ttf", "fonts/Poppins-Medium.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "regular": ["Poppins-Regular.ttf", "fonts/Poppins-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "serif": ["PlayfairDisplay-Bold.ttf", "fonts/PlayfairDisplay-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}

BADGES = {"MORNING BLESSING", "DECLARATION", "VERSE OF HOPE",
          "HOLD ON", "MIDDAY STRENGTH", "STAY THE COURSE",
          "EVENING GRACE", "GRATITUDE", "REST PRAYER"}

# House rule: no contractions in English lanes. Possessives pass.
_APO = "['\u2019`]"
_CONTRACTION_PATTERNS = [
    re.compile(r"\b\w+n" + _APO + r"t\b", re.IGNORECASE),
    re.compile(r"\b\w+" + _APO + r"(re|ve|ll|m|d)\b", re.IGNORECASE),
    re.compile(r"\b(it|that|there|here|what|who|he|she|let|where|how|when|one)"
               + _APO + r"s\b", re.IGNORECASE),
]


def _find_contractions(text):
    hits = []
    for pat in _CONTRACTION_PATTERNS:
        hits.extend(m.group(0) for m in pat.finditer(text or ""))
    return hits


def _font(kind, size):
    for path in FONT_CANDIDATES[kind]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_px(d, text, font, max_w, max_lines=None):
    words = str(text).split()
    lines, cur = [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and d.textlength(last + " \u2026", font=font) > max_w:
            last = last[:-1].rstrip()
        lines[-1] = (last + " \u2026") if last else "\u2026"
    return lines


def _tracked_center(d, y, text, font, fill, tracking=7):
    widths = [d.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = (W - total) / 2
    for ch, w_ in zip(text, widths):
        d.text((x, y), ch, font=font, fill=fill)
        x += w_ + tracking
    return total


def _center(d, y, text, font, fill):
    w_ = d.textlength(text, font=font)
    d.text(((W - w_) / 2, y), text, font=font, fill=fill)


def _blend(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _gradient(img, top, bottom):
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=_blend(top, bottom, y / H))


def _dawn_motif(d):
    """A rising glow low on the card — soft gold rings above the horizon."""
    cx, cy = W // 2, H - 118
    for r, t in ((300, 0.16), (220, 0.24), (150, 0.36), (90, 0.55)):
        color = _blend(DAWN_BOTTOM, GOLD, t)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=4)
    d.line([(MARGIN, cy), (W - MARGIN, cy)], fill=_blend(DAWN_BOTTOM, GOLD, 0.7), width=3)


def _day_motif(d):
    """A high sun in the working sky — gold disc and short rays, top right."""
    x, y, r = 856, 186, 34
    d.ellipse([x - r, y - r, x + r, y + r], fill=GOLD)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
        n = (dx * dx + dy * dy) ** 0.5
        ux, uy = dx / n, dy / n
        d.line([(x + ux * (r + 10), y + uy * (r + 10)),
                (x + ux * (r + 26), y + uy * (r + 26))], fill=GOLD, width=4)
    d.ellipse([x - r - 16, y - r - 16, x + r + 16, y + r + 16],
              outline=_blend(DAY_TOP, GOLD, 0.45), width=3)


def _dusk_motif(d):
    """Quiet stars in the upper sky and one bright evening star."""
    pts = [(140, 150), (260, 96), (410, 170), (560, 84), (700, 150),
           (840, 104), (950, 190), (200, 260), (520, 250), (880, 280),
           (330, 330), (760, 350), (120, 400), (980, 420)]
    for i, (x, y) in enumerate(pts):
        r = 3 if i % 3 else 4
        color = _blend(DUSK_TOP, CREAM, 0.5 if i % 2 else 0.7)
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)
    # the evening star
    x, y = 810, 210
    d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=GOLD)
    d.line([(x - 18, y), (x + 18, y)], fill=GOLD, width=2)
    d.line([(x, y - 18), (x, y + 18)], fill=GOLD, width=2)


def build_blessing_card(pull_quote, theme_title, slot, badge, date_label, handle):
    palettes = {
        "MORNING": (DAWN_TOP, DAWN_BOTTOM, _dawn_motif),
        "MIDDAY": (DAY_TOP, DAY_BOTTOM, _day_motif),
        "EVENING": (DUSK_TOP, DUSK_BOTTOM, _dusk_motif),
    }
    top, bottom, motif = palettes.get(slot, palettes["MORNING"])
    img = Image.new("RGB", (W, H))
    _gradient(img, top, bottom)
    d = ImageDraw.Draw(img)
    motif(d)

    # masthead — centered, letterspaced gold
    y = 108
    _tracked_center(d, y, "DAILY BLESSING", _font("bold", 38), GOLD, tracking=9)
    y += 62
    d.rounded_rectangle([(W - 130) / 2, y, (W + 130) / 2, y + 8], radius=4, fill=GOLD)
    if date_label:
        f_date = _font("regular", 28)
        d.text((W - MARGIN - d.textlength(date_label, font=f_date), 70),
               date_label, font=f_date, fill=SOFT)
    y += 56

    # format chip — centered, gold outline
    f_badge = _font("bold", 30)
    bw = d.textlength(badge, font=f_badge)
    pad_x, pad_y = 26, 13
    x0 = (W - bw - 2 * pad_x) / 2
    d.rounded_rectangle([x0, y, x0 + bw + 2 * pad_x, y + 30 + 2 * pad_y],
                        radius=(30 + 2 * pad_y) / 2, outline=GOLD, width=3)
    d.text((x0 + pad_x, y + pad_y), badge, font=f_badge, fill=GOLD)
    y += 30 + 2 * pad_y + 84

    # pull quote — serif, centered, autoscaled
    stage_bottom = H - 380
    t_size = 78
    while t_size >= 44:
        f_q = _font("serif", t_size)
        lines = _wrap_px(d, pull_quote, f_q, SAFE_W, max_lines=6)
        line_h = int(t_size * 1.28)
        if y + len(lines) * line_h <= stage_bottom:
            break
        t_size -= 5
    for line in lines:
        _center(d, y, line, f_q, CREAM)
        y += line_h

    # theme line under a short divider
    y += 40
    d.rounded_rectangle([(W - 90) / 2, y, (W + 90) / 2, y + 6], radius=3, fill=GOLD)
    if theme_title:
        y += 34
        _center(d, y, theme_title, _font("medium", 34), SOFT)

    # footer
    fy = H - 128
    d.line([(MARGIN, fy), (W - MARGIN, fy)], fill=GOLD, width=2)
    d.text((MARGIN, fy + 34), handle, font=_font("medium", 32), fill=GOLD)
    right = "Blessings for everyone."
    f_right = _font("regular", 30)
    d.text((W - MARGIN - d.textlength(right, font=f_right), fy + 36),
           right, font=f_right, fill=SOFT)
    return img


def _src(req):
    if req.method == "POST":
        body = req.get_json(silent=True) or {}
        merged = dict(req.args)
        merged.update({k: v for k, v in body.items() if v is not None})
        return merged
    return dict(req.args)


@blessing_bp.route("/render/blessing", methods=["GET", "POST"])
def blessing():
    src = _src(request)
    pull_quote = (src.get("pull_quote") or "").strip()
    if not pull_quote:
        return Response('{"error": "pull_quote is required"}', status=400,
                        mimetype="application/json")

    theme_title = (src.get("theme_title") or "").strip()
    hits = _find_contractions(pull_quote + " " + theme_title)
    if hits:
        return Response(
            '{"error": "contractions are not allowed on this lane", '
            '"found": "' + ", ".join(sorted(set(hits))) + '"}',
            status=422, mimetype="application/json")

    slot = (src.get("slot") or "MORNING").strip().upper()
    if slot not in ("MORNING", "MIDDAY", "EVENING"):
        slot = "MORNING"
    badge = (src.get("badge") or "").strip().upper()
    if badge not in BADGES:
        badge = {"MORNING": "MORNING BLESSING", "MIDDAY": "MIDDAY STRENGTH",
                 "EVENING": "EVENING GRACE"}[slot]
    date_label = (src.get("date") or datetime.utcnow().strftime("%-d %b %Y")).strip()
    handle = (src.get("handle") or "fb.com/TrendRadarNG").strip()

    img = build_blessing_card(pull_quote[:160], theme_title[:70], slot, badge,
                              date_label, handle)
    fmt = (src.get("format") or "").lower()
    buf = BytesIO()
    if fmt in ("jpg", "jpeg"):
        img.convert("RGB").save(buf, "JPEG", quality=92)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg",
                         download_name="blessing_card.jpg")
    img.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name="blessing_card.png")


@blessing_bp.route("/render/blessing/health", methods=["GET"])
def blessing_health():
    return Response('{"status": "ok"}', mimetype="application/json")
