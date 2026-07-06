"""
Naija Jakpa lane card — Trend Radar NG
GET/POST /render/jakpa -> binary PNG (default) or JPEG with format=jpg

The lane speaks to Nigerians planning to relocate abroad through legal
pathways. Every card tells that journey visually: NIGERIA -> destination
along a dotted flight path, with the story's takeaways on the card face
and a permanent integrity chip - this lane must never look like a visa
promise.

Expected JSON body (POST) or query params (GET):
{
  "headline":    "Canada Raises Express Entry Targets For 2027",   (required)
  "takeaways":   ["...", "...", "..."],  (array, or JSON-string via GET; max 3 shown)
  "destination": "CANADA",               (short label; default "ABROAD")
  "source_line": "Source: CIC News - 6 July 2026",                 (required)
  "handle":      "fb.com/TrendRadarNG"                             (optional)
}
Returns 400 on missing fields, 422 if a contraction reaches the card face
(possessives pass; true contractions are blocked - house rule).

Register in the app factory / main module:
    from jakpa_card import jakpa_bp
    app.register_blueprint(jakpa_bp)
"""
import re
import json as _json
from io import BytesIO

from flask import Blueprint, request, send_file, Response
from PIL import Image, ImageDraw, ImageFont

jakpa_bp = Blueprint("jakpa", __name__)

W, H = 1080, 1350  # 4:5 photo post
NAVY_TOP, NAVY_MID, NAVY_BOT = (6, 18, 38), (10, 33, 62), (13, 43, 80)
GREEN = (0, 168, 89)          # Nigeria green, brightened for dark background
GREEN_SOFT = (74, 222, 128)   # lighter green for accents on navy
WHITE = (255, 255, 255)
BODY_TINT = (225, 233, 240)
MUTE = (170, 185, 200)
CHIP_SKY = (126, 196, 238)    # integrity chip - same family as Wahala's device

# Poppins first (house font), DejaVu fallback so the service never crashes on fonts
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
    """Defensive param parsing, same approach as app.py; GET falls to req.values."""
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


def _wrap_px(d, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def _background():
    col = Image.new("RGB", (1, H))
    cpx = col.load()
    for y in range(H):
        f = y / H
        if f < 0.55:
            g = f / 0.55
            c = tuple(int(NAVY_TOP[i] + (NAVY_MID[i] - NAVY_TOP[i]) * g) for i in range(3))
        else:
            g = (f - 0.55) / 0.45
            c = tuple(int(NAVY_MID[i] + (NAVY_BOT[i] - NAVY_MID[i]) * g) for i in range(3))
        cpx[0, y] = c
    return col.resize((W, H))


def _plane(d, x, y, size, color):
    """Minimal paper-plane glyph pointing right, drawn as two triangles."""
    s = size
    d.polygon([(x, y), (x + s, y + s * 0.32), (x + s * 0.30, y + s * 0.45)], fill=color)
    d.polygon([(x + s * 0.30, y + s * 0.45), (x + s, y + s * 0.32),
               (x + s * 0.42, y + s * 0.78)], fill=color)



# ---- mini flag painters (programmatic - emoji fonts are unreliable in Pillow) ----

def _flag_base(d, x, y, w, h):
    d.rectangle([x - 2, y - 2, x + w + 2, y + h + 2], outline=(255, 255, 255, 90), width=2)


def _flag_nigeria(d, x, y, w, h):
    third = w / 3
    d.rectangle([x, y, x + third, y + h], fill=(0, 135, 81))
    d.rectangle([x + third, y, x + 2 * third, y + h], fill=WHITE)
    d.rectangle([x + 2 * third, y, x + w, y + h], fill=(0, 135, 81))
    _flag_base(d, x, y, w, h)


def _flag_canada(d, x, y, w, h):
    q = w / 4
    d.rectangle([x, y, x + q, y + h], fill=(216, 30, 5))
    d.rectangle([x + q, y, x + 3 * q, y + h], fill=WHITE)
    d.rectangle([x + 3 * q, y, x + w, y + h], fill=(216, 30, 5))
    cx0, cy0, s = x + w / 2, y + h / 2, h * 0.36
    leaf = [(cx0, cy0 - s), (cx0 + s * 0.28, cy0 - s * 0.28), (cx0 + s * 0.85, cy0 - s * 0.45),
            (cx0 + s * 0.55, cy0 + s * 0.1), (cx0 + s * 0.95, cy0 + s * 0.28),
            (cx0 + s * 0.12, cy0 + s * 0.5), (cx0 + s * 0.12, cy0 + s * 0.95),
            (cx0 - s * 0.12, cy0 + s * 0.95), (cx0 - s * 0.12, cy0 + s * 0.5),
            (cx0 - s * 0.95, cy0 + s * 0.28), (cx0 - s * 0.55, cy0 + s * 0.1),
            (cx0 - s * 0.85, cy0 - s * 0.45), (cx0 - s * 0.28, cy0 - s * 0.28)]
    d.polygon(leaf, fill=(216, 30, 5))
    _flag_base(d, x, y, w, h)


def _flag_uk(d, x, y, w, h):
    d.rectangle([x, y, x + w, y + h], fill=(1, 33, 105))
    d.line([x, y, x + w, y + h], fill=WHITE, width=10)
    d.line([x + w, y, x, y + h], fill=WHITE, width=10)
    d.line([x, y, x + w, y + h], fill=(200, 16, 46), width=4)
    d.line([x + w, y, x, y + h], fill=(200, 16, 46), width=4)
    d.line([x + w / 2, y, x + w / 2, y + h], fill=WHITE, width=14)
    d.line([x, y + h / 2, x + w, y + h / 2], fill=WHITE, width=14)
    d.line([x + w / 2, y, x + w / 2, y + h], fill=(200, 16, 46), width=8)
    d.line([x, y + h / 2, x + w, y + h / 2], fill=(200, 16, 46), width=8)
    _flag_base(d, x, y, w, h)


def _flag_usa(d, x, y, w, h):
    stripe = h / 7
    for i in range(7):
        d.rectangle([x, y + i * stripe, x + w, y + (i + 1) * stripe],
                    fill=(178, 34, 52) if i % 2 == 0 else WHITE)
    cw, ch = w * 0.42, stripe * 4
    d.rectangle([x, y, x + cw, y + ch], fill=(60, 59, 110))
    for r in range(3):
        for cst in range(4):
            sx = x + 5 + cst * (cw - 10) / 3
            sy = y + 5 + r * (ch - 10) / 2
            d.ellipse([sx - 1.6, sy - 1.6, sx + 1.6, sy + 1.6], fill=WHITE)
    _flag_base(d, x, y, w, h)


def _flag_eu(d, x, y, w, h):
    d.rectangle([x, y, x + w, y + h], fill=(0, 51, 153))
    import math
    cx0, cy0, r = x + w / 2, y + h / 2, h * 0.30
    for k in range(10):
        a = 2 * math.pi * k / 10 - math.pi / 2
        sx, sy = cx0 + r * math.cos(a), cy0 + r * math.sin(a)
        d.ellipse([sx - 2.4, sy - 2.4, sx + 2.4, sy + 2.4], fill=(255, 204, 0))
    _flag_base(d, x, y, w, h)


_DEST_MAP = {
    "CANADA": "CANADA",
    "UK": "UK", "UNITED KINGDOM": "UK", "BRITAIN": "UK", "ENGLAND": "UK", "SCOTLAND": "UK",
    "USA": "USA", "US": "USA", "UNITED STATES": "USA", "AMERICA": "USA",
    "EUROPE": "EUROPE", "EU": "EUROPE", "SCHENGEN": "EUROPE",
    "GERMANY": "EUROPE", "FRANCE": "EUROPE", "NETHERLANDS": "EUROPE", "PORTUGAL": "EUROPE",
    "SPAIN": "EUROPE", "ITALY": "EUROPE", "IRELAND": "EUROPE", "FINLAND": "EUROPE",
    "SWEDEN": "EUROPE", "NORWAY": "EUROPE", "DENMARK": "EUROPE", "POLAND": "EUROPE",
    "AUSTRIA": "EUROPE", "BELGIUM": "EUROPE", "MALTA": "EUROPE",
}


def _dest_key(destination):
    """Map the story destination onto one of the four flag slots, or None."""
    return _DEST_MAP.get((destination or "").strip().upper())


def build_jakpa_card(headline, takeaways, destination, source_line,
                     handle="fb.com/TrendRadarNG"):
    img = _background()
    d = ImageDraw.Draw(img, "RGBA")
    cx = W // 2
    M = 80

    # Kicker
    d.text((cx, 110), "NAIJA JAKPA", font=_font("bold", 58), fill=GREEN_SOFT, anchor="mm")
    d.line([cx - 130, 158, cx + 130, 158], fill=GREEN, width=4)

    # Journey band: Nigeria flag ----plane----> destination flags (CA UK USA EU)
    jy_top = 200
    fw, fh_flag = 72, 48
    nigeria_x = M
    _flag_nigeria(d, nigeria_x, jy_top, fw, fh_flag)
    f_lbl_ng = _font("bold", 26)
    d.text((nigeria_x + fw / 2, jy_top + fh_flag + 22), "NIGERIA",
           font=f_lbl_ng, fill=WHITE, anchor="mm")

    dests = [("CANADA", _flag_canada), ("UK", _flag_uk),
             ("USA", _flag_usa), ("EUROPE", _flag_eu)]
    gap = 26
    row_w = len(dests) * fw + (len(dests) - 1) * gap
    dest_x0 = W - M - row_w
    f_lbl = _font("medium", 22)
    hi = _dest_key(destination)
    mid_y = jy_top + fh_flag / 2
    for i, (label, painter) in enumerate(dests):
        fx = dest_x0 + i * (fw + gap)
        painter(d, fx, jy_top, fw, fh_flag)
        d.text((fx + fw / 2, jy_top + fh_flag + 20), label,
               font=f_lbl, fill=MUTE if hi != label else GREEN_SOFT, anchor="mm")
        if hi == label:
            try:
                d.rounded_rectangle([fx - 8, jy_top - 8, fx + fw + 8, jy_top + fh_flag + 36],
                                    radius=12, outline=GREEN, width=4)
            except AttributeError:
                d.rectangle([fx - 8, jy_top - 8, fx + fw + 8, jy_top + fh_flag + 36],
                            outline=GREEN, width=4)

    # dotted flight path from Nigeria to the destination row
    path_x0, path_x1 = nigeria_x + fw + 30, dest_x0 - 30
    x = path_x0
    while x < path_x1 - 10:
        d.ellipse([x, mid_y - 3, x + 6, mid_y + 3], fill=(255, 255, 255, 130))
        x += 22
    _plane(d, (path_x0 + path_x1) / 2 - 26, mid_y - 22, 52, GREEN_SOFT)

    # Headline - pixel-measured wrap, auto-shrink, max 4 lines
    max_w = W - 2 * M
    size = 74
    fh, lines = None, []
    while size >= 42:
        fh = _font("bold", size)
        lines = _wrap_px(d, headline.upper(), fh, max_w)
        if len(lines) <= 4:
            break
        size -= 4
    y = 396
    for ln in lines[:4]:
        d.text((cx, y), ln, font=fh, fill=WHITE, anchor="mm")
        y += int(size * 1.26)
    y += 26

    # Takeaways - up to 3, each with a green tick, wrapped to 2 lines max
    f_take = _font("medium", 40)
    tick_r = 9
    for t in (takeaways or [])[:3]:
        t = str(t).strip()
        if not t:
            continue
        tlines = _wrap_px(d, t, f_take, max_w - 60)[:2]
        d.ellipse([M, y - tick_r, M + 2 * tick_r, y + tick_r], fill=GREEN)
        d.line([M + 5, y, M + 8, y + 4], fill=NAVY_TOP, width=3)
        d.line([M + 8, y + 4, M + 14, y - 5], fill=NAVY_TOP, width=3)
        ty = y
        for tl in tlines:
            d.text((M + 46, ty), tl, font=f_take, fill=BODY_TINT, anchor="lm")
            ty += int(40 * 1.3)
        y = ty + 18

    # Integrity chip - permanent honesty device for this lane
    chip = "OFFICIAL INFORMATION — NOT A VISA PROMISE"
    fc = _font("medium", 32)
    tw = d.textlength(chip, font=fc)
    chip_y = max(y + 20, H - 360)
    box = [cx - tw / 2 - 34, chip_y, cx + tw / 2 + 34, chip_y + 68]
    try:
        d.rounded_rectangle(box, radius=34, outline=CHIP_SKY, width=4)
    except AttributeError:
        d.rectangle(box, outline=CHIP_SKY, width=4)
    d.text((cx, chip_y + 34), chip, font=fc, fill=CHIP_SKY, anchor="mm")

    # Source line (mandatory, dated - the lane's spine)
    d.text((cx, H - 210), source_line, font=_font("bold", 38), fill=GREEN_SOFT, anchor="mm")

    # Footer band
    d.rectangle([0, H - 140, W, H - 130], fill=GREEN)
    d.rectangle([0, H - 130, W, H], fill=NAVY_TOP)
    d.text((70, H - 66), handle, font=_font("bold", 36), fill=GREEN_SOFT, anchor="lm")
    d.text((W - 70, H - 66), "Legal pathways, curated.", font=_font("regular", 34),
           fill=MUTE, anchor="rm")
    return img


@jakpa_bp.route("/render/jakpa", methods=["GET", "POST"])
def render_jakpa():
    src = _source(request)
    headline    = (src.get("headline") or "").strip()[:200]
    destination = (src.get("destination") or "ABROAD").strip()[:24]
    source_line = (src.get("source_line") or "").strip()[:120]
    handle      = (src.get("handle") or "fb.com/TrendRadarNG").strip()

    takeaways = src.get("takeaways")
    if isinstance(takeaways, str):
        try:
            takeaways = _json.loads(takeaways)
        except Exception:
            takeaways = [t for t in takeaways.split("||") if t.strip()]
    if not isinstance(takeaways, list):
        takeaways = []

    missing = [k for k, v in (("headline", headline), ("source_line", source_line)) if not v]
    if missing:
        return Response(_json.dumps({"error": "missing fields", "fields": missing}),
                        status=400, mimetype="application/json")
    face_text = " ".join([headline] + [str(t) for t in takeaways])
    if _CONTRACTION.search(face_text):
        return Response('{"error":"contraction detected in card text"}',
                        status=422, mimetype="application/json")

    try:
        img = build_jakpa_card(headline, takeaways, destination, source_line, handle)
        return _send_card(img, "trendradar_jakpa", src)
    except Exception:
        import traceback
        return Response(_json.dumps({"error": "render failed",
                                     "traceback": traceback.format_exc()}),
                        status=500, mimetype="application/json")
