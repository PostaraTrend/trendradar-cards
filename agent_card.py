"""
Trend Agent lane card — Trend Radar NG
GET/POST /render/agent -> binary PNG (default) or JPEG with format=jpg
GET /render/agent/health -> {"status": "ok"}

Direction A, "Radar": near-black ink field with a house-gold radar sweep
and a single contact blip — the trend-detected signature. The analytical
sibling of the gist card: same badge chip language and dotted divider,
entirely different temperature. 4:5 photo post.

Expected query params (GET) or JSON body (POST):
  headline   (required)  the agent's headline, max ~200 chars recommended
  badge      (optional)  format chip: EXPLAINER | HOT TAKE | LISTICLE | DEBATE
                         (default EXPLAINER). `category` is accepted as an
                         alias so the v1.2 workflow payload, which sent the
                         format in the category field for /card, works with
                         only the URL repointed.
  date       (optional)  e.g. "15 Jul 2026"
  handle     (optional)  default fb.com/TrendRadarNG

Contraction gate is ON for this route (422 on failure): the Trend Agent
writes English analysis, so the house no-contractions rule applies.
Possessives pass; only genuine contractions are rejected.

Register in app.py, next to the other lanes:
    from agent_card import agent_bp
    app.register_blueprint(agent_bp)
"""
import re
from io import BytesIO
from datetime import datetime

from flask import Blueprint, request, send_file, Response
from PIL import Image, ImageDraw, ImageFont

agent_bp = Blueprint("agent", __name__)

W, H = 1080, 1350  # 4:5 photo post
INK = (16, 19, 24)             # near-black ink background
INK_PANEL = (27, 32, 40)       # footer panel tint
GOLD = (240, 180, 41)          # house gold — the radar color
GOLD_DIM = (101, 79, 31)       # gold blended ~35% onto ink (arc rings)
GOLD_MID = (156, 120, 35)      # gold blended ~60% onto ink (sweep line)
CREAM = (244, 239, 228)        # warm headline white
SOFT = (172, 165, 149)         # muted warm-gray body text
MARGIN = 80
SAFE_W = W - 2 * MARGIN

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

BADGES = {"EXPLAINER", "HOT TAKE", "LISTICLE", "DEBATE",
          "JOB ALERT", "FREE TRAINING", "GRANT ALERT", "CAREER TIP"}  # Better Life AM

# House rule: no contractions in English lanes. Possessives pass.
_APO = "['\u2019`]"
_CONTRACTION_PATTERNS = [
    re.compile(r"\b\w+n" + _APO + r"t\b", re.IGNORECASE),                  # don't, cannot forms
    re.compile(r"\b\w+" + _APO + r"(re|ve|ll|m|d)\b", re.IGNORECASE),      # we're, I've, she'll, I'm, he'd
    re.compile(r"\b(it|that|there|here|what|who|he|she|let|where|how|when|one)"
               + _APO + r"s\b", re.IGNORECASE),                            # it's etc. — possessive 's passes
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


def _tracked_text(d, xy, text, font, fill, tracking=6):
    """Letterspaced masthead text (Pillow has no native tracking)."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + tracking
    return x


def _src(req):
    if req.method == "POST":
        body = req.get_json(silent=True) or {}
        merged = dict(req.args)
        merged.update({k: v for k, v in body.items() if v is not None})
        return merged
    return dict(req.args)


def _radar(d):
    """Gold radar rings off the top-right corner, one sweep, one contact blip."""
    cx, cy = 1150, -70
    for r in (480, 330, 180):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GOLD_DIM, width=3)
    # sweep line toward the lower-left, through the blip
    d.line([(cx, cy), (795, 262)], fill=GOLD_MID, width=4)
    # the contact — a trend detected
    bx, by, br = 862, 200, 13
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=GOLD)
    d.ellipse([bx - br - 12, by - br - 12, bx + br + 12, by + br + 12],
              outline=GOLD_MID, width=3)


def build_agent_card(headline, badge, date_label, handle):
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)

    _radar(d)

    # masthead — letterspaced gold
    y = 100
    _tracked_text(d, (MARGIN, y), "TREND RADAR NG \u2022 ORIGINAL",
                  _font("bold", 36), GOLD, tracking=7)
    y += 96

    # format badge chip — same chip language as the gist card, gold on ink
    f_badge = _font("bold", 34)
    pad_x, pad_y = 26, 14
    bw = d.textlength(badge, font=f_badge)
    d.rounded_rectangle([MARGIN, y, MARGIN + bw + 2 * pad_x, y + 34 + 2 * pad_y],
                        radius=14, fill=GOLD)
    d.text((MARGIN + pad_x, y + pad_y), badge, font=f_badge, fill=INK)
    if date_label:
        f_date = _font("regular", 30)
        d.text((W - MARGIN - d.textlength(date_label, font=f_date), y + pad_y + 4),
               date_label, font=f_date, fill=SOFT)
    y += 34 + 2 * pad_y + 70

    # headline — serif voice, autoscaled until it fits the stage
    stage_bottom = H - 320
    t_size = 92
    while t_size >= 52:
        f_title = _font("serif", t_size)
        lines = _wrap_px(d, headline, f_title, SAFE_W, max_lines=6)
        line_h = int(t_size * 1.22)
        if y + len(lines) * line_h <= stage_bottom:
            break
        t_size -= 6
    for line in lines:
        d.text((MARGIN, y), line, font=f_title, fill=CREAM)
        y += line_h

    # dotted divider — the sibling tell, monochrome gold for the analyst
    y += 36
    dot_x = MARGIN
    for _ in range(9):
        d.ellipse([dot_x, y, dot_x + 12, y + 12], fill=GOLD)
        dot_x += 34

    # tagline
    d.text((MARGIN, y + 42), "Original analysis. No noise.",
           font=_font("medium", 34), fill=SOFT)

    # footer bar
    fy = H - 150
    d.rectangle([0, fy, W, H], fill=INK_PANEL)
    d.rectangle([0, fy, W, fy + 6], fill=GOLD)
    d.text((MARGIN, fy + 52), handle, font=_font("medium", 34), fill=GOLD)
    right = "Trend Radar NG Original"
    f_right = _font("regular", 32)
    d.text((W - MARGIN - d.textlength(right, font=f_right), fy + 54),
           right, font=f_right, fill=SOFT)
    return img


@agent_bp.route("/render/agent", methods=["GET", "POST"])
def agent():
    src = _src(request)
    headline = (src.get("headline") or "").strip()
    if not headline:
        return Response('{"error": "headline is required"}', status=400,
                        mimetype="application/json")

    hits = _find_contractions(headline)
    if hits:
        return Response(
            '{"error": "contractions are not allowed on this lane", '
            '"found": "' + ", ".join(sorted(set(hits))) + '"}',
            status=422, mimetype="application/json")

    badge = (src.get("badge") or src.get("category") or "EXPLAINER").strip().upper()
    if badge not in BADGES:
        badge = "EXPLAINER"
    date_label = (src.get("date") or datetime.utcnow().strftime("%-d %b %Y")).strip()
    handle = (src.get("handle") or "fb.com/TrendRadarNG").strip()

    img = build_agent_card(headline[:220], badge, date_label, handle)
    fmt = (src.get("format") or "").lower()
    buf = BytesIO()
    if fmt in ("jpg", "jpeg"):
        img.convert("RGB").save(buf, "JPEG", quality=92)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg",
                         download_name="agent_card.jpg")
    img.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name="agent_card.png")


@agent_bp.route("/render/agent/health", methods=["GET"])
def agent_health():
    return Response('{"status": "ok"}', mimetype="application/json")
