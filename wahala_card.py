"""
Wahala Watch lane card — Trend Radar NG
POST /render/wahala -> binary PNG (matches house pattern: send_file, fonts at repo root)

Expected JSON body:
{
  "headline":    "EFCC Probes ... Alleged N4.2 Billion ...",   (required)
  "body":        "Premium Times reports ...",                   (required)
  "stage":       "OFFICIAL_PROBE",                              (required)
  "source_line": "Source: Premium Times - 2 July 2026",         (required)
  "handle":      "fb.com/TrendRadarNG"                          (optional)
}
Returns 400 on missing fields, 422 if a contraction reaches the card face.
"""
import os
import re
import json as _json
import random
import textwrap
from io import BytesIO

from flask import Blueprint, request, send_file, Response
from PIL import Image, ImageDraw, ImageFont

wahala_bp = Blueprint("wahala", __name__)

W, H = 1080, 1350  # 4:5 photo post
NAVY_TOP, NAVY_MID, NAVY_BOT = (6, 18, 38), (10, 33, 62), (13, 43, 80)
WHITE, AMBER, SKY, MUTE = (255, 255, 255), (245, 182, 46), (126, 196, 238), (200, 220, 240)

_HERE = os.path.dirname(os.path.abspath(__file__))
def _font(name, size):
    return ImageFont.truetype(os.path.join(_HERE, name), size)


def _wrap_px(d, text, font, max_w):
    """Greedy word wrap measured in pixels — every returned line fits max_w."""
    words = text.split()
    lines, cur = [], ""
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

STAGE_CHIP = {
    "ACCUSED":        "ALLEGATION — NOT PROVEN",
    "ARRESTED":       "ARRESTED — NOT CONVICTED",
    "CHARGED":        "CHARGED — NOT CONVICTED",
    "ON_TRIAL":       "ON TRIAL — NOT CONVICTED",
    "CONVICTED":      "CONVICTED BY A COURT",
    "OFFICIAL_PROBE": "OFFICIAL PROBE — NOT A CONVICTION",
    "PUBLIC_DISPUTE": "PUBLIC DISPUTE — CLAIMS ON BOTH SIDES",
}

_CONTRACTION = re.compile(r"\b\w+'(s|t|re|ve|ll|d|m)\b", re.IGNORECASE)


def _source(req):
    """Defensive param parsing, same approach as app.py."""
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


def _background(seed=7):
    # 1px-wide gradient column scaled to full size — fast on small instances
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
    base = col.resize((W, H))
    rnd = random.Random(seed)
    d = ImageDraw.Draw(base, "RGBA")
    for _ in range(300):
        x, y = rnd.randrange(W), rnd.randrange(H)
        r = rnd.choice([1, 1, 1, 2, 2, 3])
        col = rnd.choice([(255, 255, 255), (200, 225, 250), (170, 210, 245)])
        d.ellipse([x - r, y - r, x + r, y + r], fill=col + (rnd.randint(60, 200),))
    return base


def build_wahala_card(headline, body, stage, source_line, handle="fb.com/TrendRadarNG"):
    img = _background()
    d = ImageDraw.Draw(img, "RGBA")
    cx = W // 2

    # Kicker
    d.text((cx, 120), "WAHALA WATCH", font=_font("Poppins-Bold.ttf", 58), fill=AMBER, anchor="mm")
    d.line([cx - 120, 168, cx + 120, 168], fill=AMBER, width=4)

    # Headline — pixel-measured wrap, guaranteed to fit, max 4 lines
    max_w = W - 140
    size = 80
    fh, lines = None, []
    while size >= 44:
        fh = _font("Poppins-Bold.ttf", size)
        lines = _wrap_px(d, headline.upper(), fh, max_w)
        if len(lines) <= 4:
            break
        size -= 4
    y = 300
    for ln in lines[:4]:
        d.text((cx, y), ln, font=fh, fill=WHITE, anchor="mm")
        y += int(size * 1.28)

    # Body — pixel-measured wrap, max 3 lines, shrink once if needed
    y += 36
    for bsize in (44, 38):
        fb = _font("Poppins-Medium.ttf", bsize)
        blines = _wrap_px(d, body, fb, max_w)
        if len(blines) <= 3:
            break
    for ln in blines[:3]:
        d.text((cx, y), ln, font=fb, fill=MUTE, anchor="mm")
        y += int(bsize * 1.35)

    # Claim-stage chip (always rendered — the legal honesty device)
    chip = STAGE_CHIP.get((stage or "").upper(), "ALLEGATION — NOT PROVEN")
    fc = _font("Poppins-Medium.ttf", 36)
    tw = d.textlength(chip, font=fc)
    box = [cx - tw / 2 - 36, y + 24, cx + tw / 2 + 36, y + 96]
    try:
        d.rounded_rectangle(box, radius=36, outline=SKY, width=4)
    except AttributeError:  # Pillow < 8.2
        d.rectangle(box, outline=SKY, width=4)
    d.text((cx, y + 60), chip, font=fc, fill=SKY, anchor="mm")

    # Source line (mandatory)
    d.text((cx, H - 220), source_line, font=_font("Poppins-Bold.ttf", 40), fill=AMBER, anchor="mm")

    # Footer
    d.text((70, H - 90), handle, font=_font("Poppins-Bold.ttf", 36), fill=SKY, anchor="lm")
    d.text((W - 70, H - 90), "Nigeria, curated.", font=_font("Poppins-Regular.ttf", 36),
           fill=(200, 215, 235), anchor="rm")
    return img


@wahala_bp.route("/render/wahala", methods=["POST"])
def render_wahala():
    src = _source(request)
    headline    = (src.get("headline") or "").strip()[:240]
    body        = (src.get("body") or "").strip()[:300]
    stage       = (src.get("stage") or "").strip()
    source_line = (src.get("source_line") or "").strip()[:120]
    handle      = (src.get("handle") or "fb.com/TrendRadarNG").strip()

    missing = [k for k, v in (("headline", headline), ("body", body),
                              ("stage", stage), ("source_line", source_line)) if not v]
    if missing:
        return Response(_json.dumps({"error": "missing fields", "fields": missing}),
                        status=400, mimetype="application/json")
    if _CONTRACTION.search(headline + " " + body):
        return Response('{"error":"contraction detected in card text"}',
                        status=422, mimetype="application/json")

    try:
        img = build_wahala_card(headline, body, stage, source_line, handle)
        buf = BytesIO()
        img.save(buf, "PNG", optimize=True)
        buf.seek(0)
        return send_file(buf, mimetype="image/png",
                         download_name="trendradar_wahala.png")
    except Exception:
        import traceback
        return Response(_json.dumps({"error": "render failed",
                                     "traceback": traceback.format_exc()}),
                        status=500, mimetype="application/json")
