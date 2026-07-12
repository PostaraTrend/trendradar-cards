# ============================================================================
# SOP-ADV-001 — Advertorial Card Renderer
# Endpoint: GET /render/advertorial
# Add this route to the trendradar-cards Flask app (app.py) and redeploy.
#
# Query parameters:
#   headline     (required) — card headline, wrapped automatically
#   body         (optional) — supporting line
#   advertiser   (required) — advertiser display name
#   brand_color  (optional) — hex without '#', default 112B54
#   is_sample    (optional) — 'true' renders the SAMPLE CAMPAIGN ribbon (rule G2)
#   powered_by   (optional) — e.g. 'PostaraTrend'; renders "Powered by <value>"
#                under the advertiser name. Leave blank to omit (white-label).
#   format       (optional) — 'jpg' (default) or 'png'
#
# Output: 1080 x 1350 (4:5) photo-post card with a permanent "Sponsored"
# strip (rule G1). Served from memory (BytesIO) — no disk writes, so the
# microsecond-filename rule does not apply to this endpoint.
#
# HOW TO INSTALL:
#   1. Paste everything below the marker into app.py (or import it as a module
#      and call register_advertorial(app)).
#   2. If the repo has a fonts/ folder, add its bold and regular TTF paths to
#      the FONT_CANDIDATES lists below so the card matches the fleet look.
#   3. Commit and push — Render redeploys automatically.
#   4. Test in a browser:
#      /render/advertorial?headline=Test&body=Body+line&advertiser=TRNG+Business&brand_color=112B54&is_sample=false
# ============================================================================

from io import BytesIO

from flask import request, send_file
from PIL import Image, ImageDraw, ImageFont

# --- Font loading: first path that exists wins. Add fleet fonts at the top. -
FONT_CANDIDATES_BOLD = [
    "fonts/Inter-Bold.ttf",
    "fonts/Montserrat-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_CANDIDATES_REGULAR = [
    "fonts/Inter-Regular.ttf",
    "fonts/Montserrat-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(candidates, size):
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw, text, font, max_width):
    """Greedy word wrap measured with the actual font."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = (current + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _hex_to_rgb(value, fallback=(17, 43, 84)):
    value = (value or "").strip().lstrip("#")
    if len(value) == 6:
        try:
            return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return fallback


def register_advertorial(app):
    @app.route("/render/advertorial")
    def render_advertorial():
        headline = request.args.get("headline", "").strip()
        body = request.args.get("body", "").strip()
        advertiser = request.args.get("advertiser", "").strip()
        brand_rgb = _hex_to_rgb(request.args.get("brand_color", "112B54"))
        is_sample = request.args.get("is_sample", "false").lower() == "true"
        powered_by = request.args.get("powered_by", "").strip()
        fmt = request.args.get("format", "jpg").lower()

        W, H = 1080, 1350
        STRIP_H = 96          # bottom "Sponsored" strip (rule G1)
        MARGIN = 84

        img = Image.new("RGB", (W, H), brand_rgb)
        draw = ImageDraw.Draw(img)

        # Subtle darker footer band above the strip for the advertiser block
        band_top = H - STRIP_H - 240
        overlay = Image.new("RGB", (W, H - STRIP_H - band_top),
                            tuple(max(0, c - 22) for c in brand_rgb))
        img.paste(overlay, (0, band_top))

        f_head = _load_font(FONT_CANDIDATES_BOLD, 84)
        f_body = _load_font(FONT_CANDIDATES_REGULAR, 46)
        f_adv = _load_font(FONT_CANDIDATES_BOLD, 52)
        f_powered = _load_font(FONT_CANDIDATES_REGULAR, 32)
        f_strip = _load_font(FONT_CANDIDATES_BOLD, 34)
        f_ribbon = _load_font(FONT_CANDIDATES_BOLD, 40)

        max_text_w = W - 2 * MARGIN

        # Headline (auto-shrink once if it wraps past 5 lines)
        head_lines = _wrap(draw, headline, f_head, max_text_w)
        if len(head_lines) > 5:
            f_head = _load_font(FONT_CANDIDATES_BOLD, 68)
            head_lines = _wrap(draw, headline, f_head, max_text_w)

        y = 150
        for line in head_lines:
            draw.text((MARGIN, y), line, font=f_head, fill=(255, 255, 255))
            y += int(f_head.size * 1.22)

        # Body text
        y += 36
        for line in _wrap(draw, body, f_body, max_text_w):
            draw.text((MARGIN, y), line, font=f_body, fill=(226, 232, 240))
            y += int(f_body.size * 1.35)

        # Advertiser block in the footer band
        adv_y = band_top + 60
        draw.rectangle([MARGIN, adv_y + 8, MARGIN + 10, adv_y + 8 + f_adv.size],
                       fill=(255, 255, 255))
        draw.text((MARGIN + 34, adv_y), advertiser, font=f_adv, fill=(255, 255, 255))

        # Optional corporate attribution line (white-label toggle)
        if powered_by:
            draw.text((MARGIN + 34, adv_y + f_adv.size + 26),
                      "Powered by " + powered_by,
                      font=f_powered, fill=(176, 184, 200))

        # Bottom "Sponsored" strip (rule G1 - permanent, all advertorials)
        draw.rectangle([0, H - STRIP_H, W, H], fill=(15, 17, 21))
        draw.text((MARGIN, H - STRIP_H + 30), "SPONSORED",
                  font=f_strip, fill=(255, 205, 76))
        right_label = "TREND RADAR NIGERIA"
        rl_w = draw.textlength(right_label, font=f_strip)
        draw.text((W - MARGIN - rl_w, H - STRIP_H + 30), right_label,
                  font=f_strip, fill=(200, 205, 215))

        # SAMPLE CAMPAIGN ribbon (rule G2 - mandatory for fictional advertisers)
        if is_sample:
            ribbon_text = "SAMPLE CAMPAIGN — ADVERTISE WITH TRNG"
            rw = int(draw.textlength(ribbon_text, font=f_ribbon)) + 120
            rh = 96
            ribbon = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
            rd = ImageDraw.Draw(ribbon)
            rd.rectangle([0, 0, rw, rh], fill=(190, 24, 40, 255))
            rd.text((60, (rh - f_ribbon.size) // 2), ribbon_text,
                    font=f_ribbon, fill=(255, 255, 255, 255))
            ribbon = ribbon.rotate(30, expand=True)
            img.paste(ribbon, (W - ribbon.width + 150, -60), ribbon)

        buf = BytesIO()
        if fmt == "png":
            img.save(buf, format="PNG")
            mimetype = "image/png"
        else:
            img.save(buf, format="JPEG", quality=92)
            mimetype = "image/jpeg"
        buf.seek(0)
        return send_file(buf, mimetype=mimetype)

    return app


# If pasting directly into app.py where `app` already exists, replace the
# function wrapper above by calling:  register_advertorial(app)
