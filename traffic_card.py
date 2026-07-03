"""
Trend Radar NG — Traffic Watch card renderer
=============================================
Drop-in blueprint for the existing trendradar-cards Flask app (Render).

Install (2 lines in your existing app.py):
    from traffic_card import traffic_bp
    app.register_blueprint(traffic_bp)

Endpoint:
    POST /render/traffic
    Content-Type: application/json
    {
      "city": "Lagos",
      "generated_at": "Thursday, 02 July 2026 · 07:00 WAT",
      "platform": "facebook",            # "facebook" -> fb.com/TrendRadarNG footer
                                          # "instagram" -> @trendradarng footer
      "corridors": [
        {"name": "Third Mainland Bridge", "status": "HEAVY",
         "current_kmh": 14, "freeflow_kmh": 62},
        ...
      ],
      "alert": "Optional one-line incident note shown under the header"
    }

    Returns: image/png, 1080x1350 (4:5), branded card.

Fonts: Poppins is loaded from FONT_DIR (env var, default ./fonts). Falls back
to DejaVu if Poppins TTFs are absent so the endpoint never 500s on fonts.
"""

import io
import os
from datetime import datetime

from flask import Blueprint, request, send_file
from PIL import Image, ImageDraw, ImageFont

traffic_bp = Blueprint("traffic", __name__)

# ---------------------------------------------------------------- constants
W, H = 1080, 1350
SS = 2  # 2x supersampling, downscaled at the end (house style)

NAVY = (14, 40, 65)          # #0E2841 brand navy
NAVY_DEEP = (9, 28, 47)
CARD_ROW = (20, 52, 82)
CARD_ROW_ALT = (17, 46, 74)
WHITE = (255, 255, 255)
MUTED = (150, 172, 196)
TEAL = (26, 188, 156)
EMERALD = (46, 204, 113)

STATUS_STYLE = {
    "FREE FLOW":  {"fill": (46, 204, 113),  "text": (10, 40, 25)},
    "SLOW":       {"fill": (245, 176, 65),  "text": (60, 40, 5)},
    "HEAVY":      {"fill": (231, 76, 60),   "text": (255, 240, 238)},
    "STANDSTILL": {"fill": (192, 57, 43),   "text": (255, 235, 233)},
    "CLOSED":     {"fill": (110, 118, 130), "text": (240, 243, 247)},
    "NO DATA":    {"fill": (70, 90, 112),   "text": (200, 214, 228)},
}

FONT_DIR = os.environ.get("FONT_DIR", os.path.join(os.path.dirname(__file__), "fonts"))


def _font(names, size):
    """Try Poppins variants first, then DejaVu fallback. Size is pre-supersample."""
    for n in names:
        p = os.path.join(FONT_DIR, n)
        if os.path.exists(p):
            return ImageFont.truetype(p, size * SS)
    for fb in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(fb):
            return ImageFont.truetype(fb, size * SS)
    return ImageFont.load_default()


def _fonts():
    return {
        "brand": _font(["Poppins-Bold.ttf", "Poppins-SemiBold.ttf"], 34),
        "title": _font(["Poppins-ExtraBold.ttf", "Poppins-Bold.ttf"], 74),
        "sub": _font(["Poppins-Medium.ttf", "Poppins-Regular.ttf"], 30),
        "alert": _font(["Poppins-SemiBold.ttf", "Poppins-Medium.ttf"], 27),
        "row": _font(["Poppins-SemiBold.ttf", "Poppins-Medium.ttf"], 33),
        "speed": _font(["Poppins-Regular.ttf", "Poppins-Light.ttf"], 24),
        "pill": _font(["Poppins-Bold.ttf", "Poppins-SemiBold.ttf"], 24),
        "footer": _font(["Poppins-SemiBold.ttf", "Poppins-Medium.ttf"], 28),
    }


def _radar_motif(d, cx, cy, r):
    """Small radar-dial accent echoing the TRNG avatar."""
    for k in (1.0, 0.66, 0.33):
        rr = int(r * k)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=(*TEAL, 255), width=2 * SS)
    d.line([cx, cy, cx + int(r * 0.72), cy - int(r * 0.62)],
           fill=EMERALD, width=3 * SS)
    d.ellipse([cx - 4 * SS, cy - 4 * SS, cx + 4 * SS, cy + 4 * SS], fill=EMERALD)


def render_traffic_card(payload: dict) -> Image.Image:
    city = payload.get("city", "Lagos")
    generated_at = payload.get("generated_at") or datetime.utcnow().strftime(
        "%A, %d %B %Y")
    platform = (payload.get("platform") or "facebook").lower()
    corridors = payload.get("corridors", [])[:12]
    alert = (payload.get("alert") or "").strip()

    footer_handle = "@trendradarng" if platform == "instagram" else "fb.com/TrendRadarNG"

    img = Image.new("RGB", (W * SS, H * SS), NAVY)
    d = ImageDraw.Draw(img)
    f = _fonts()

    # header band
    header_h = 250 * SS
    d.rectangle([0, 0, W * SS, header_h], fill=NAVY_DEEP)
    d.rectangle([0, header_h - 5 * SS, W * SS, header_h], fill=TEAL)

    pad = 64 * SS
    d.text((pad, 38 * SS), "TREND RADAR NG", font=f["brand"], fill=TEAL)
    d.text((pad, 86 * SS), "TRAFFIC WATCH", font=f["title"], fill=WHITE)
    d.text((pad, 188 * SS), f"{city} Commute Brief  ·  {generated_at}",
           font=f["sub"], fill=MUTED)
    _radar_motif(d, (W - 118) * SS, 118 * SS, 58 * SS)

    y = header_h + 28 * SS

    # optional incident alert strip
    if alert:
        strip_h = 66 * SS
        d.rounded_rectangle([pad, y, (W - 64) * SS, y + strip_h],
                            radius=14 * SS, fill=(120, 38, 32))
        d.text((pad + 24 * SS, y + strip_h // 2), "ALERT  ·  " + alert[:88],
               font=f["alert"], fill=(255, 226, 221), anchor="lm")
        y += strip_h + 24 * SS

    # corridor rows
    footer_h = 96 * SS
    avail = (H * SS - footer_h - 24 * SS) - y
    n = max(len(corridors), 1)
    row_h = min(84 * SS, avail // n)
    gap = 10 * SS

    for i, c in enumerate(corridors):
        top = y + i * row_h
        bottom = top + row_h - gap
        fill = CARD_ROW if i % 2 == 0 else CARD_ROW_ALT
        d.rounded_rectangle([pad, top, (W - 64) * SS, bottom],
                            radius=16 * SS, fill=fill)

        cy = (top + bottom) // 2
        name = str(c.get("name", ""))[:34]
        d.text((pad + 28 * SS, cy), name, font=f["row"], fill=WHITE, anchor="lm")

        status = str(c.get("status", "NO DATA")).upper()
        style = STATUS_STYLE.get(status, STATUS_STYLE["NO DATA"])

        # speed readout (left of pill)
        cur, ff = c.get("current_kmh"), c.get("freeflow_kmh")
        pill_w, pill_h = 232 * SS, 46 * SS
        pill_x1 = (W - 64) * SS - 24 * SS
        pill_x0 = pill_x1 - pill_w
        if cur is not None and status not in ("CLOSED", "NO DATA"):
            spd = f"{int(round(cur))} km/h" + (f" of {int(round(ff))}" if ff else "")
            d.text((pill_x0 - 20 * SS, cy), spd, font=f["speed"],
                   fill=MUTED, anchor="rm")

        d.rounded_rectangle([pill_x0, cy - pill_h // 2, pill_x1, cy + pill_h // 2],
                            radius=pill_h // 2, fill=style["fill"])
        d.text(((pill_x0 + pill_x1) // 2, cy), status, font=f["pill"],
               fill=style["text"], anchor="mm")

    # footer
    d.rectangle([0, H * SS - footer_h, W * SS, H * SS], fill=NAVY_DEEP)
    d.rectangle([0, H * SS - footer_h, W * SS, H * SS - footer_h + 4 * SS], fill=EMERALD)
    d.text((pad, H * SS - footer_h // 2), footer_handle,
           font=f["footer"], fill=WHITE, anchor="lm")
    d.text(((W - 64) * SS, H * SS - footer_h // 2),
           "Data source: TomTom Traffic", font=f["speed"], fill=MUTED, anchor="rm")

    return img.resize((W, H), Image.LANCZOS)


@traffic_bp.route("/render/traffic", methods=["POST"])
def render_traffic():
    payload = request.get_json(force=True, silent=True) or {}
    img = render_traffic_card(payload)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name="trng-traffic-watch.png")


if __name__ == "__main__":
    # local preview: python traffic_card.py -> writes preview.png
    demo = {
        "city": "Lagos",
        "generated_at": "Thursday, 02 July 2026 · 07:00 WAT",
        "platform": "facebook",
        "alert": "Accident reported on Apapa-Oshodi Expressway near Mile 2 inward Apapa",
        "corridors": [
            {"name": "Third Mainland Bridge", "status": "HEAVY", "current_kmh": 14, "freeflow_kmh": 62},
            {"name": "Lekki-Epe Expressway", "status": "STANDSTILL", "current_kmh": 6, "freeflow_kmh": 55},
            {"name": "Ikorodu Road (Ojota)", "status": "SLOW", "current_kmh": 28, "freeflow_kmh": 52},
            {"name": "Apapa-Oshodi Expressway", "status": "HEAVY", "current_kmh": 12, "freeflow_kmh": 58},
            {"name": "Lagos-Ibadan Expy (Berger)", "status": "SLOW", "current_kmh": 31, "freeflow_kmh": 64},
            {"name": "Eko Bridge", "status": "FREE FLOW", "current_kmh": 48, "freeflow_kmh": 55},
            {"name": "Carter Bridge", "status": "SLOW", "current_kmh": 24, "freeflow_kmh": 48},
            {"name": "Agege Motor Road (Oshodi)", "status": "HEAVY", "current_kmh": 11, "freeflow_kmh": 45},
            {"name": "Airport Road", "status": "FREE FLOW", "current_kmh": 42, "freeflow_kmh": 50},
            {"name": "Ozumba Mbadiwe Avenue", "status": "SLOW", "current_kmh": 22, "freeflow_kmh": 46},
            {"name": "Funsho Williams Avenue", "status": "FREE FLOW", "current_kmh": 44, "freeflow_kmh": 52},
            {"name": "Lekki-Ikoyi Link Bridge", "status": "FREE FLOW", "current_kmh": 51, "freeflow_kmh": 60},
        ],
    }
    render_traffic_card(demo).save("preview.png", "PNG")
    print("wrote preview.png")


# ================================================================
# FLASH ALERT CARD  (Phase 2)
# POST /render/traffic-alert
# {
#   "kind": "ROAD CLOSED" | "ACCIDENT" | "BREAKDOWN",
#   "road": "Airport Road",
#   "stretch": "From 22nd Road to 41st Road",
#   "delay_min": 25,                # optional
#   "detected_at": "Friday, 03 July 2026 · 08:12 WAT",
#   "note": "optional extra line from TomTom description",
#   "platform": "facebook" | "instagram"
# }
# ================================================================

ALERT_RED = (196, 46, 38)
ALERT_RED_DEEP = (150, 30, 24)


def render_alert_card(payload: dict) -> Image.Image:
    kind = (payload.get("kind") or "TRAFFIC ALERT").upper()[:20]
    road = (payload.get("road") or "Lagos road network").strip()[:38]
    stretch = (payload.get("stretch") or "").strip()[:70]
    note = (payload.get("note") or "").strip()[:110]
    delay_min = payload.get("delay_min")
    detected_at = payload.get("detected_at") or ""
    platform = (payload.get("platform") or "facebook").lower()
    footer_handle = "@trendradarng" if platform == "instagram" else "fb.com/TrendRadarNG"

    img = Image.new("RGB", (W * SS, H * SS), NAVY)
    d = ImageDraw.Draw(img)
    f = _fonts()
    big = _font(["Poppins-ExtraBold.ttf", "Poppins-Bold.ttf"], 92)
    road_f = _font(["Poppins-Bold.ttf", "Poppins-SemiBold.ttf"], 58)
    kind_f = _font(["Poppins-Bold.ttf", "Poppins-SemiBold.ttf"], 40)
    body_f = _font(["Poppins-Medium.ttf", "Poppins-Regular.ttf"], 34)

    pad = 64 * SS

    # header band (red)
    header_h = 300 * SS
    d.rectangle([0, 0, W * SS, header_h], fill=ALERT_RED_DEEP)
    d.rectangle([0, header_h - 6 * SS, W * SS, header_h], fill=(255, 205, 200))
    d.text((pad, 40 * SS), "TREND RADAR NG", font=f["brand"], fill=(255, 214, 210))
    d.text((pad, 96 * SS), "TRAFFIC ALERT", font=big, fill=WHITE)
    if detected_at:
        d.text((pad, 226 * SS), detected_at, font=f["sub"], fill=(255, 214, 210))
    _radar_motif(d, (W - 118) * SS, 118 * SS, 58 * SS)

    y = header_h + 70 * SS

    # incident kind pill
    pill_h = 66 * SS
    tw = d.textlength(kind, font=kind_f)
    d.rounded_rectangle([pad, y, pad + tw + 72 * SS, y + pill_h],
                        radius=pill_h // 2, fill=ALERT_RED)
    d.text((pad + 36 * SS, y + pill_h // 2), kind, font=kind_f,
           fill=WHITE, anchor="lm")
    y += pill_h + 56 * SS

    # road name (wrap to 2 lines max)
    words, lines, cur = road.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if d.textlength(t, font=road_f) <= (W - 128) * SS:
            cur = t
        else:
            lines.append(cur); cur = wd
    lines.append(cur)
    for ln in lines[:2]:
        d.text((pad, y), ln, font=road_f, fill=WHITE)
        y += 84 * SS
    y += 12 * SS

    if stretch:
        d.text((pad, y), stretch, font=body_f, fill=MUTED)
        y += 62 * SS

    if delay_min:
        d.text((pad, y), f"Estimated delay: about {int(delay_min)} minutes",
               font=body_f, fill=(245, 176, 65))
        y += 62 * SS

    if note:
        y += 14 * SS
        d.rounded_rectangle([pad, y, (W - 64) * SS, y + 96 * SS],
                            radius=16 * SS, fill=CARD_ROW)
        d.text((pad + 26 * SS, y + 48 * SS), note, font=f["alert"],
               fill=(220, 232, 244), anchor="lm")
        y += 130 * SS

    # advisory line
    d.text((pad, H * SS - 96 * SS - 130 * SS),
           "Plan an alternative route where possible.",
           font=body_f, fill=TEAL)

    # footer
    footer_h = 96 * SS
    d.rectangle([0, H * SS - footer_h, W * SS, H * SS], fill=NAVY_DEEP)
    d.rectangle([0, H * SS - footer_h, W * SS, H * SS - footer_h + 4 * SS], fill=EMERALD)
    d.text((pad, H * SS - footer_h // 2), footer_handle, font=f["footer"],
           fill=WHITE, anchor="lm")
    d.text(((W - 64) * SS, H * SS - footer_h // 2),
           "Data source: TomTom Traffic", font=f["speed"], fill=MUTED, anchor="rm")

    return img.resize((W, H), Image.LANCZOS)


@traffic_bp.route("/render/traffic-alert", methods=["POST"])
def render_traffic_alert():
    payload = request.get_json(force=True, silent=True) or {}
    img = render_alert_card(payload)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name="trng-traffic-alert.png")
