"""
NAIJA LENS renderer endpoint — add to the trendradar-cards Flask app.
POST /naijalens/render
  JSON body: {
    "photo_url":   "https://images.pexels.com/....jpeg",   # original size URL
    "hook_line1":  "5:40 AM. Yaba.",                        # white line
    "hook_line2":  "She was here before the sun.",          # gold line
    "credit":      "Photo: Chinedu A. via Pexels",
    "slide_tag":   ""                                       # optional e.g. "1/3"
  }
Returns: { "image_url": "https://trendradar-cards.onrender.com/static/naijalens/<file>.jpg" }

Quality gate: rejects photos under 1500px on the short side (422 response).
Enhancement pass: center-crop to 4:5, Lanczos to 1080x1350, gentle
autocontrast, +6% colour, unsharp mask AFTER resize.
"""
import io, os, time, hashlib
import requests as rq
from flask import Blueprint, request, jsonify, url_for
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance, ImageFilter

naijalens = Blueprint("naijalens", __name__)

W, H = 1080, 1350
GOLD = (244, 196, 92)
WHITE = (255, 255, 255)
CREDIT_COL = (220, 225, 232)
FONT_DIR = os.environ.get("FONT_DIR", "fonts")   # Poppins already shipped with renderer
OUT_DIR = os.path.join("static", "naijalens")
os.makedirs(OUT_DIR, exist_ok=True)

def _font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)

def _fit_text(draw, text, fontname, start_size, max_w):
    """Shrink font until the line fits max_w. Hard floor 34px."""
    size = start_size
    while size > 34:
        f = _font(fontname, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(fontname, 34)

@naijalens.route("/naijalens/render", methods=["POST"])
def render_naijalens():
    p = request.get_json(force=True)
    photo_url = p["photo_url"]
    hook1 = p.get("hook_line1", "").strip()
    hook2 = p.get("hook_line2", "").strip()
    credit = p.get("credit", "").strip()
    slide_tag = p.get("slide_tag", "").strip()

    # ---- Download ----
    r = rq.get(photo_url, timeout=30)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")

    # ---- Quality gate ----
    if min(img.size) < 1500:
        return jsonify({"error": "photo below quality floor (1500px short side)",
                        "size": img.size}), 422

    # ---- Center-crop to 4:5 then Lanczos resize ----
    tgt = W / H
    w0, h0 = img.size
    if w0 / h0 > tgt:                       # too wide
        nw = int(h0 * tgt)
        x0 = (w0 - nw) // 2
        img = img.crop((x0, 0, x0 + nw, h0))
    else:                                    # too tall
        nh = int(w0 / tgt)
        y0 = int((h0 - nh) * 0.35)           # bias crop upward (faces sit high)
        img = img.crop((0, y0, w0, y0 + nh))
    img = img.resize((W, H), Image.LANCZOS)

    # ---- Enhancement pass ----
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Color(img).enhance(1.06)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=3))

    # ---- Treatment ----
    d = ImageDraw.Draw(img, "RGBA")
    # bottom scrim
    for y in range(1020, H):
        a = int(205 * (y - 1020) / (H - 1020))
        d.line([(0, y), (W, y)], fill=(8, 14, 24, a))
    # top-left soft scrim behind the mark
    for y in range(0, 160):
        a = int(90 * (1 - y / 160))
        d.line([(0, y), (W, y)], fill=(8, 14, 24, a))
    # ripple mark + lane tag
    cx, cy = 96, 88
    for i, rr in enumerate([14, 26]):
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=(255, 255, 255, 180 - 60 * i), width=3)
    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=GOLD + (255,))
    d.text((136, 68), "NAIJA LENS", font=_font("Poppins-Bold.ttf", 30),
           fill=(255, 255, 255, 235))
    d.text((136, 106), "A TRUE NIGERIAN STORY", font=_font("Poppins-Medium.ttf", 18),
           fill=(255, 255, 255, 170))
    if slide_tag:
        d.text((W - 80, 68), slide_tag, font=_font("Poppins-Bold.ttf", 34),
               fill=GOLD + (230,), anchor="ra")
    # hooks (auto-shrink to fit)
    max_w = W - 160
    f1 = _fit_text(d, hook1, "Poppins-SemiBold.ttf", 50, max_w)
    f2 = _fit_text(d, hook2, "Poppins-SemiBold.ttf", 50, max_w)
    d.text((80, 1104), hook1, font=f1, fill=WHITE + (255,))
    d.text((80, 1104 + f1.size + 16), hook2, font=f2, fill=GOLD + (255,))
    # credit
    d.text((80, 1272), credit, font=_font("Poppins-Regular.ttf", 23),
           fill=CREDIT_COL + (205,))

    # ---- Save & return URL ----
    name = hashlib.md5(f"{photo_url}{time.time()}".encode()).hexdigest()[:16] + ".jpg"
    path = os.path.join(OUT_DIR, name)
    img.save(path, "JPEG", quality=91)
    base = request.host_url.rstrip("/")
    return jsonify({"image_url": f"{base}/static/naijalens/{name}"})
