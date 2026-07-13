"""
People's Verdict lane card — Trend Radar NG
GET/POST /render/verdict -> binary PNG (default) or JPEG with format=jpg
GET /render/verdict/health -> {"status": "ok"}

Collates a People's Voice comment thread into a verdict card: title,
distilled verdict, and a SHARE OF VOICE bar chart of the community's
camps. Navy/gold, 4:5 photo post.

Expected JSON body (POST) or query params (GET):
{
  "title":      "Japa Is a Tool — Your Family Decides What It Builds",  (required)
  "summary":    "35-55 word distilled verdict",                          (required)
  "camps":      [{"label": "...", "pct": 50}, ...],  (array or JSON-string via GET; max 3 shown)
  "comments_count": 87,                    (optional; omitted -> stat line skipped)
  "date_label": "Monday, 13 July 2026",    (optional)
  "handle":     "fb.com/TrendRadarNG"      (optional)
}
Returns 400 on missing fields, 422 if a contraction reaches the card face
(possessives pass; true contractions are blocked - house rule).

Register in the app factory / main module, next to the other lanes:
    from verdict_card import verdict_bp
    app.register_blueprint(verdict_bp)
"""
import re
import json as _json
from io import BytesIO

from flask import Blueprint, request, send_file, Response
from PIL import Image, ImageDraw, ImageFont

verdict_bp = Blueprint("verdict", __name__)

W, H = 1080, 1350  # 4:5 photo post
NAVY = (14, 40, 65)           # #0E2841
NAVY_TRACK = (30, 58, 88)     # bar chart track
GOLD = (240, 180, 41)         # #F0B429
WHITE = (255, 255, 255)
SOFT = (203, 213, 225)        # muted body text
MARGIN = 80
SAFE_W = W - 2 * MARGIN

FONT_CANDIDATES = {
    "bold": ["Poppins-Bold.ttf", "fonts/Poppins-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "medium": ["Poppins-Medium.ttf", "fonts/Poppins-Medium.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "regular": ["Poppins-Regular.ttf", "fonts/Poppins-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}


def _font(kind, size):
    for path in FONT_CANDIDATES[kind]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


# Possessive 's is allowed; true contractions ('t, 're, 've, 'll, 'd, 'm) are blocked.
_CONTRACTION = re.compile(r"\b\w+'(t|re|ve|ll|d|m)\b", re.IGNORECASE)


def _source(req):
    """Defensive param parsing, same approach as the other lanes."""
    data = req.get_json(silent=True)
    if isinstance(data, dict):
        return data
    raw = req.get_data(as_text=True) or ""
    if raw.strip():
        try:
            parsed = _json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return req.values


def _send_card(img, base_name, src):
    """PNG by default; JPEG with format=jpg (Instagram ingestion requires JPEG)."""
    fmt = (src.get("format") or request.args.get("format") or "").strip().lower()
    buf = BytesIO()
    if fmt in ("jpg", "jpeg"):
        img.convert("RGB").save(buf, "JPEG", quality=92)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg", download_name=f"{base_name}.jpg")
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name=f"{base_name}.png")


def _wrap_px(d, text, font, max_w, max_lines=None):
    words, lines, cur = str(text).split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
            if max_lines and len(lines) == max_lines:
                break
    if cur and (not max_lines or len(lines) < max_lines):
        lines.append(cur)
    truncated = len(" ".join(lines)) < len(" ".join(words))
    if truncated and lines:
        last = lines[-1]
        while last and d.textlength(last + " …", font=font) > max_w:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-2]
        lines[-1] = (last + " …").strip()
    return lines, truncated


def build_verdict_card(title, summary, camps, comments_count, date_label,
                       handle="fb.com/TrendRadarNG"):
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img, "RGBA")

    # Subtle deterministic starfield, kept out of the text zone
    seed = 1250624
    for _ in range(90):
        seed = (seed * 1103515245 + 12345) % (2 ** 31)
        x = seed % W
        seed = (seed * 1103515245 + 12345) % (2 ** 31)
        y = seed % H
        if 130 < y < H - 140:
            continue
        d.ellipse([x, y, x + 2, y + 2], fill=(40, 70, 100))

    # Top gold bar + kicker
    d.rectangle([0, 0, W, 14], fill=GOLD)
    d.text((MARGIN, 84), "P E O P L E ' S   V E R D I C T",
           font=_font("bold", 46), fill=GOLD)

    y = 84 + 46 + 26
    if date_label:
        d.text((MARGIN, y), str(date_label), font=_font("regular", 30), fill=SOFT)
        y += 30 + 44
    else:
        y += 30

    # Title: max 3 lines with chart, 4 without; auto-shrink before truncating
    has_chart = bool(camps)
    max_t = 3 if has_chart else 4
    t_size = 62
    f_title = _font("bold", t_size)
    title_lines, t_trunc = _wrap_px(d, title, f_title, SAFE_W, max_t)
    while t_trunc and t_size > 44:
        t_size -= 6
        f_title = _font("bold", t_size)
        title_lines, t_trunc = _wrap_px(d, title, f_title, SAFE_W, max_t)
    for line in title_lines:
        d.text((MARGIN, y), line, font=f_title, fill=WHITE)
        y += t_size + 16

    # Gold divider
    y += 22
    d.rectangle([MARGIN, y, MARGIN + 180, y + 8], fill=GOLD)
    y += 8 + 44

    # Summary: max 4 lines with chart, 9 without
    f_body = _font("regular", 40)
    body_lines, _ = _wrap_px(d, summary, f_body, SAFE_W, 4 if has_chart else 9)
    for line in body_lines:
        d.text((MARGIN, y), line, font=f_body, fill=SOFT)
        y += 40 + 18

    if has_chart:
        # ---- SHARE OF VOICE bars ----
        y += 26
        d.text((MARGIN, y), "S H A R E   O F   V O I C E",
               font=_font("bold", 32), fill=GOLD)
        y += 32 + 30

        f_label = _font("medium", 34)
        f_pct = _font("bold", 34)
        track_h = 26
        rows = sorted(camps, key=lambda c: -float(c.get("pct", 0) or 0))[:3]
        for c in rows:
            label = str(c.get("label", "")).strip()
            try:
                pct = max(0.0, min(100.0, float(c.get("pct", 0) or 0)))
            except (TypeError, ValueError):
                pct = 0.0
            pct_txt = "{}%".format(int(round(pct)))
            pw = d.textlength(pct_txt, font=f_pct)
            lab_lines, _ = _wrap_px(d, label, f_label, SAFE_W - pw - 30, 1)
            d.text((MARGIN, y), lab_lines[0] if lab_lines else "", font=f_label, fill=WHITE)
            d.text((W - MARGIN - pw, y), pct_txt, font=f_pct, fill=GOLD)
            y += 34 + 12
            try:
                d.rounded_rectangle([MARGIN, y, MARGIN + SAFE_W, y + track_h],
                                    radius=13, fill=NAVY_TRACK)
                fill_w = int(SAFE_W * pct / 100.0)
                if fill_w > track_h:
                    d.rounded_rectangle([MARGIN, y, MARGIN + fill_w, y + track_h],
                                        radius=13, fill=GOLD)
                elif fill_w > 0:
                    d.ellipse([MARGIN, y, MARGIN + track_h, y + track_h], fill=GOLD)
            except AttributeError:
                d.rectangle([MARGIN, y, MARGIN + SAFE_W, y + track_h], fill=NAVY_TRACK)
                d.rectangle([MARGIN, y, MARGIN + int(SAFE_W * pct / 100.0), y + track_h], fill=GOLD)
            y += track_h + 30

        if comments_count:
            d.text((MARGIN, y), "Collated from {} community voices".format(comments_count),
                   font=_font("medium", 30), fill=SOFT)
    else:
        if comments_count:
            d.text((MARGIN, H - 210),
                   "Collated from {} community voices".format(comments_count),
                   font=_font("medium", 34), fill=GOLD)

    # Footer band
    d.rectangle([0, H - 96, W, H - 86], fill=GOLD)
    f_footer = _font("medium", 30)
    footer = "PEOPLE'S VERDICT  \u2022  TREND RADAR NG"
    fw = d.textlength(footer, font=f_footer)
    d.text(((W - fw) // 2, H - 68), footer, font=f_footer, fill=WHITE)
    return img


@verdict_bp.route("/render/verdict/health", methods=["GET"])
def verdict_health():
    return Response('{"status":"ok","lane":"peoples-verdict"}',
                    mimetype="application/json")


@verdict_bp.route("/render/verdict", methods=["GET", "POST"])
def render_verdict():
    src = _source(request)
    title = (src.get("title") or "").strip()[:200]
    summary = (src.get("summary") or "").strip()[:600]
    date_label = (src.get("date_label") or "").strip()[:60]
    handle = (src.get("handle") or "fb.com/TrendRadarNG").strip()
    comments_count = src.get("comments_count") or ""

    camps = src.get("camps")
    if isinstance(camps, str):
        try:
            camps = _json.loads(camps)
        except Exception:
            camps = []
    if not isinstance(camps, list):
        camps = []
    camps = [c for c in camps if isinstance(c, dict) and str(c.get("label", "")).strip()]

    missing = [k for k, v in (("title", title), ("summary", summary)) if not v]
    if missing:
        return Response(_json.dumps({"error": "missing fields", "fields": missing}),
                        status=400, mimetype="application/json")
    face_text = " ".join([title, summary] + [str(c.get("label", "")) for c in camps])
    if _CONTRACTION.search(face_text):
        return Response('{"error":"contraction detected in card text"}',
                        status=422, mimetype="application/json")

    try:
        img = build_verdict_card(title, summary, camps, comments_count, date_label, handle)
        return _send_card(img, "trendradar_verdict", src)
    except Exception:
        import traceback
        return Response(_json.dumps({"error": "render failed",
                                     "traceback": traceback.format_exc()}),
                        status=500, mimetype="application/json")
