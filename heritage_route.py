"""
HERITAGE IN FOCUS renderer endpoint — add to the trendradar-cards Flask app.
POST /heritage/render
  JSON body: {
    "edition_no":     "01",
    "location":       "Marina, Lagos Island",
    "then_year":      "1923",
    "now_year":       "2026",
    "then_photo_url": "https://upload.wikimedia.org/....jpg",   # DIRECT file URL
    "now_photo_url":  "https://upload.wikimedia.org/....jpg",   # DIRECT file URL
    "then_credit":    "The National Archives UK, CO 1069/65 (OGL v1.0)",
    "now_credit":     "Ade Marquis via Wikimedia Commons (CC BY 4.0)",
    "hook":           "The street you drive today, a century ago."  # optional
  }
Returns: { "cover_url": ".../static/heritage/<id>_cover.jpg",
           "slide_url": ".../static/heritage/<id>_slide.jpg" }

PRECAUTIONS BUILT IN
- Wikimedia requires a User-Agent header: set on every download (403 without it).
- Archival quality gate: THEN photo floor 640px short side (period scans are
  small); NOW photo floor 1000px. 422 with reason on failure.
- Credits are burned into the card under each frame — attribution can never be
  dropped by a caption edit.
- All rendered text passes _decontract(): no contractions on any card.
- THEN photo receives a gentle sepia grade; NOW stays natural.
Follows the Naija Lens hosting pattern: JPEG saved under static/heritage/,
served by Flask static; single-worker constraint unaffected (files on disk).
"""
import io, os, time, hashlib, re
import requests as rq
from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance, ImageFilter

heritage = Blueprint("heritage", __name__)

W, H = 1080, 1350
NAVY_TOP = (10, 20, 40)
NAVY_BOT = (16, 34, 66)
GOLD = (224, 168, 74)            # heritage sepia-gold accent
ORANGE = (255, 122, 47)          # TRNG house accent (SWIPE cue, NOW chip)
WHITE = (245, 247, 250)
MUTED = (168, 182, 202)
FOOTER_BG = (8, 16, 32)
FONT_DIR = os.environ.get("FONT_DIR", "fonts")
OUT_DIR = os.path.join("static", "heritage")
os.makedirs(OUT_DIR, exist_ok=True)

UA = {"User-Agent": "TrendRadarNG-HeritageLane/1.0 (https://www.facebook.com/trendradarng; hello@postaratrend.ca)"}

_CONTRACTIONS = [
    (r"\bwe're\b", "we are"), (r"\bWe're\b", "We are"),
    (r"\bdon't\b", "do not"), (r"\bDon't\b", "Do not"),
    (r"\bdoesn't\b", "does not"), (r"\bdidn't\b", "did not"),
    (r"\bit's\b", "it is"), (r"\bIt's\b", "It is"),
    (r"\byou're\b", "you are"), (r"\bYou're\b", "You are"),
    (r"\bthey're\b", "they are"), (r"\bThey're\b", "They are"),
    (r"\bcan't\b", "cannot"), (r"\bCan't\b", "Cannot"),
    (r"\bwon't\b", "will not"), (r"\bWon't\b", "Will not"),
    (r"\bthat's\b", "that is"), (r"\bThat's\b", "That is"),
    (r"\bwhat's\b", "what is"), (r"\bWhat's\b", "What is"),
    (r"\bisn't\b", "is not"), (r"\bIsn't\b", "Is not"),
    (r"\baren't\b", "are not"), (r"\bwasn't\b", "was not"),
    (r"\bweren't\b", "were not"), (r"\bhasn't\b", "has not"),
    (r"\bhaven't\b", "have not"), (r"\bwouldn't\b", "would not"),
    (r"\bshouldn't\b", "should not"), (r"\bcouldn't\b", "could not"),
    (r"\blet's\b", "let us"), (r"\bLet's\b", "Let us"),
    (r"\bI'm\b", "I am"), (r"\bI've\b", "I have"),
    (r"\bwe've\b", "we have"), (r"\bWe've\b", "We have"),
    (r"\byou've\b", "you have"),
]

def _decontract(text):
    for pat, rep in _CONTRACTIONS:
        text = re.sub(pat, rep, text)
    return text

def _font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)

def _fit_text(draw, text, fontname, start_size, max_w, floor=28):
    size = start_size
    while size > floor:
        f = _font(fontname, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(fontname, floor)

def _gradient(draw):
    for y in range(H):
        t = y / H
        draw.line([(0, y), (W, y)], fill=(
            int(NAVY_TOP[0] + (NAVY_BOT[0] - NAVY_TOP[0]) * t),
            int(NAVY_TOP[1] + (NAVY_BOT[1] - NAVY_TOP[1]) * t),
            int(NAVY_TOP[2] + (NAVY_BOT[2] - NAVY_TOP[2]) * t)))

def _stars(draw, seed):
    import random
    random.seed(seed)
    for _ in range(140):
        x, y = random.randint(0, W), random.randint(0, H)
        s = random.choice([1, 1, 1, 2, 2, 3])
        draw.ellipse([x, y, x + s, y + s],
                     fill=(255, 255, 255, random.randint(70, 200)))

def _download(url):
    r = rq.get(url, timeout=45, headers=UA)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")

def _contain(img, box_w, box_h):
    """Aspect-preserving fit inside box, centered on a dark mat."""
    img = ImageOps.contain(img, (box_w, box_h), Image.LANCZOS)
    mat = Image.new("RGB", (box_w, box_h), (14, 22, 38))
    mat.paste(img, ((box_w - img.width) // 2, (box_h - img.height) // 2))
    return mat

def _sepia(img):
    g = ImageOps.grayscale(img)
    sep = ImageOps.colorize(g, black=(28, 20, 10), white=(238, 222, 190),
                            mid=(150, 122, 82))
    return Image.blend(img.convert("RGB"), sep.convert("RGB"), 0.75)

def _enhance(img):
    img = ImageOps.autocontrast(img, cutoff=1)
    return img.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3))

def _footer(d, right_text):
    d.rectangle([0, 1250, W, H], fill=FOOTER_BG)
    d.text((90, 1278), "TREND RADAR NG", font=_font("Poppins-Bold.ttf", 38),
           fill=WHITE)
    f = _font("Poppins-SemiBold.ttf", 34)
    d.text((W - 90, 1284), right_text, font=f, fill=GOLD, anchor="ra")

def _chip(d, x, y, text, bg):
    f = _font("Poppins-Bold.ttf", 38)
    tw = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + tw + 48, y + 66], radius=12, fill=bg)
    d.text((x + 24, y + 10), text, font=f, fill=(20, 24, 34))

# --------------------------------------------------------------------------
@heritage.route("/heritage/render", methods=["POST"])
def render_heritage():
    p = request.get_json(force=True)
    edition = str(p.get("edition_no", "01")).zfill(2)
    location = _decontract(p.get("location", "").strip())
    then_year = str(p.get("then_year", "")).strip()
    now_year = str(p.get("now_year", "2026")).strip()
    then_credit = _decontract(p.get("then_credit", "").strip())
    now_credit = _decontract(p.get("now_credit", "").strip())
    hook = _decontract(p.get("hook",
        "The street you drive today, a century ago.").strip())

    # ---- Precaution: refuse to render without burned-in attribution ----
    if not then_credit or not now_credit:
        return jsonify({"error": "then_credit and now_credit are mandatory"}), 422

    # ---- Download (with Wikimedia-compliant User-Agent) ----
    try:
        then_img = _download(p["then_photo_url"])
        now_img = _download(p["now_photo_url"])
    except Exception as e:
        return jsonify({"error": f"photo download failed: {e}"}), 422

    # ---- Quality gates (archival floor is lower by design) ----
    if min(then_img.size) < 640:
        return jsonify({"error": "THEN photo below archival floor (640px short side)",
                        "size": then_img.size}), 422
    if min(now_img.size) < 1000:
        return jsonify({"error": "NOW photo below quality floor (1000px short side)",
                        "size": now_img.size}), 422

    then_img = _sepia(_enhance(then_img))
    now_img = _enhance(now_img)

    # ================= COVER =================
    cover = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(cover, "RGBA")
    _gradient(d)
    _stars(d, 41)

    kick = f"HERITAGE IN FOCUS  ·  N°{edition}"
    d.text((90, 150), kick, font=_font("Poppins-SemiBold.ttf", 40), fill=GOLD)
    d.rectangle([90, 215, 250, 221], fill=GOLD)

    d.text((84, 300), "Lagos", font=_font("Poppins-Bold.ttf", 128), fill=WHITE)
    d.text((84, 440), "in Time", font=_font("Poppins-Bold.ttf", 128), fill=GOLD)

    sub = f"{location}  ·  {then_year} to {now_year}" if location else \
        "The Evolution of a Mega-City"
    fsub = _fit_text(d, sub, "Poppins-Regular.ttf", 52, W - 180)
    d.text((90, 640), sub, font=fsub, fill=MUTED)

    fh = _fit_text(d, hook, "Poppins-Regular.ttf", 46, W - 180)
    d.text((90, 780), hook, font=fh, fill=WHITE)

    d.text((90, 1050), "SWIPE  →", font=_font("Poppins-SemiBold.ttf", 42),
           fill=ORANGE)
    _footer(d, "We scan the archives so you do not have to.")
    # footer right text can be long; re-render smaller if needed
    # (Poppins 34 fits the tagline at 1080 wide with the wordmark)

    # ================= THEN / NOW SLIDE =================
    slide = Image.new("RGB", (W, H))
    d2 = ImageDraw.Draw(slide, "RGBA")
    _gradient(d2)
    _stars(d2, 7)

    kick2 = f"HERITAGE IN FOCUS  ·  {location.upper()}" if location else \
        "HERITAGE IN FOCUS"
    fk = _fit_text(d2, kick2, "Poppins-SemiBold.ttf", 34, W - 180)
    d2.text((90, 110), kick2, font=fk, fill=GOLD)
    d2.rectangle([90, 165, 250, 171], fill=GOLD)

    fx0, fx1, fh_px = 90, W - 90, 400
    box_w = fx1 - fx0

    # THEN frame
    y_then = 210
    slide.paste(_contain(then_img, box_w, fh_px), (fx0, y_then))
    d2.rounded_rectangle([fx0, y_then, fx1, y_then + fh_px], radius=4,
                         outline=GOLD, width=3)
    _chip(d2, fx0 + 20, y_then + 20, f"THEN  ·  {then_year}", GOLD)
    d2.text((fx0 + 4, y_then + fh_px + 10), _decontract(then_credit),
            font=_font("Poppins-Regular.ttf", 24), fill=MUTED)

    # NOW frame
    y_now = 690
    slide.paste(_contain(now_img, box_w, fh_px), (fx0, y_now))
    d2.rounded_rectangle([fx0, y_now, fx1, y_now + fh_px], radius=4,
                         outline=MUTED, width=3)
    _chip(d2, fx0 + 20, y_now + 20, f"NOW  ·  {now_year}", ORANGE)
    d2.text((fx0 + 4, y_now + fh_px + 10), _decontract(now_credit),
            font=_font("Poppins-Regular.ttf", 24), fill=MUTED)

    cap = f"Same place. {then_year} and {now_year}."
    fc = _font("Poppins-Regular.ttf", 40)
    d2.text((W / 2, 1180), cap, font=fc, fill=WHITE, anchor="ma")
    _footer(d2, f"N°{edition}")

    # ---- Save & return hosted URLs ----
    stamp = hashlib.md5(
        f"{p['then_photo_url']}{time.time()}".encode()).hexdigest()[:16]
    cover_name, slide_name = f"{stamp}_cover.jpg", f"{stamp}_slide.jpg"
    cover.save(os.path.join(OUT_DIR, cover_name), "JPEG", quality=91)
    slide.save(os.path.join(OUT_DIR, slide_name), "JPEG", quality=91)
    base = request.host_url.rstrip("/")
    return jsonify({"cover_url": f"{base}/static/heritage/{cover_name}",
                    "slide_url": f"{base}/static/heritage/{slide_name}"})


# ==========================================================================
# FROM THE ARCHIVES — fully automated single-photo route (Option B)
# POST /heritage/archive
#   JSON body: {
#     "photo_url":  "https://upload.wikimedia.org/....jpg",  # from Commons API
#     "year_label": "1923",              # or "" when unknown -> omitted
#     "title_line": "Lagos Marina",      # short line from Claude
#     "credit":     "Artist Name / The National Archives UK (OGL v1.0)"
#   }
# Returns: { "image_url": ".../static/heritage/<id>_archive.jpg" }
# Archival floor 640px short side; credit is mandatory and burned in.
# ==========================================================================
@heritage.route("/heritage/archive", methods=["POST"])
def render_archive():
    p = request.get_json(force=True)
    year = str(p.get("year_label", "")).strip()
    title_line = _decontract(p.get("title_line", "").strip())
    credit = _decontract(p.get("credit", "").strip())
    if not credit:
        return jsonify({"error": "credit is mandatory"}), 422
    try:
        img = _download(p["photo_url"])
    except Exception as e:
        return jsonify({"error": f"photo download failed: {e}"}), 422
    if min(img.size) < 640:
        return jsonify({"error": "photo below archival floor (640px short side)",
                        "size": img.size}), 422
    img = _sepia(_enhance(img))

    card = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(card, "RGBA")
    _gradient(d)
    _stars(d, 23)

    d.text((90, 100), "HERITAGE IN FOCUS  ·  FROM THE ARCHIVES",
           font=_fit_text(d, "HERITAGE IN FOCUS  ·  FROM THE ARCHIVES",
                          "Poppins-SemiBold.ttf", 36, W - 180), fill=GOLD)
    d.rectangle([90, 158, 250, 164], fill=GOLD)

    fx0, fx1 = 70, W - 70
    fh_px = 760
    y0 = 200
    card.paste(_contain(img, fx1 - fx0, fh_px), (fx0, y0))
    d.rounded_rectangle([fx0, y0, fx1, y0 + fh_px], radius=4,
                        outline=GOLD, width=4)
    if year:
        _chip(d, fx0 + 24, y0 + 24, year, GOLD)
    d.text((fx0 + 4, y0 + fh_px + 12), credit,
           font=_font("Poppins-Regular.ttf", 24), fill=MUTED)

    ft = _fit_text(d, title_line, "Poppins-Bold.ttf", 58, W - 180, floor=34)
    d.text((W / 2, 1060), title_line, font=ft, fill=WHITE, anchor="ma")

    _footer(d, "We scan the archives so you do not have to.")

    name = hashlib.md5(f"{p['photo_url']}{time.time()}".encode()).hexdigest()[:16] + "_archive.jpg"
    card.save(os.path.join(OUT_DIR, name), "JPEG", quality=91)
    base = request.host_url.rstrip("/")
    return jsonify({"image_url": f"{base}/static/heritage/{name}"})
