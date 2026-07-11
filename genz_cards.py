"""
genz_cards.py — Gen Z Weekend Lane card renderer (Trend Radar NG)  v1.1
========================================================================
Drop-in Flask blueprint for the trendradar-cards renderer.

v1.1 QC fixes:
  - Mixed-color word-level rendering: gold phrase can sit anywhere in the
    take without dropping trailing text
  - JPEG output by default (Instagram image_url requires JPEG);
    append &format=png for PNG
  - Hard reserve zones: headline auto-fits so body text can never collide
    with vote pills, CTA, or wordmark
  - Checkbox scales with item font size

Endpoints (GET so the URL itself IS the image — no storage needed):

  GET /genz/take?text=...&gold=...&serial=001[&format=png]
  GET /genz/childhood?headline=...&i1=...&i2=...&i3=...[&format=png]

Registration in your existing app.py:

    from genz_cards import genz_bp
    app.register_blueprint(genz_bp)

Fonts self-bootstrap on first request into ./fonts.
"""

import io
import os
import urllib.request

from flask import Blueprint, request, send_file
from PIL import Image, ImageDraw, ImageFont

genz_bp = Blueprint("genz", __name__)

W = H = 1080
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

FONT_SOURCES = {
    "Poppins-ExtraBold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-ExtraBold.ttf",
    "Poppins-SemiBold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-SemiBold.ttf",
    "Poppins-Medium.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Medium.ttf",
}

# Palette
BG_TAKE_TOP = (16, 10, 24)
BG_TAKE_BOT = (44, 18, 52)
BG_KID_TOP = (6, 18, 12)
BG_KID_BOT = (13, 44, 28)
FLAG_GREEN = (0, 158, 96)
GREEN = (0, 190, 110)
GOLD = (242, 183, 5)
CREAM = (245, 241, 232)
MUTED = (168, 186, 174)


def _ensure_fonts():
    os.makedirs(FONT_DIR, exist_ok=True)
    for name, url in FONT_SOURCES.items():
        path = os.path.join(FONT_DIR, name)
        if not os.path.exists(path):
            urllib.request.urlretrieve(url, path)


def _font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


def _gradient(top, bot):
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line(
            [(0, y), (W, y)],
            fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)),
        )
    return img, d


def _spine(d):
    d.rectangle([0, 0, 14, H], fill=FLAG_GREEN)
    d.rectangle([14, 0, 22, H], fill=CREAM)
    d.rectangle([22, 0, 36, H], fill=FLAG_GREEN)


def _letterspaced(d, xy, text, fnt, fill, tracking=8):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill)
        x += d.textlength(ch, font=fnt) + tracking
    return x


def _ls_width(d, text, fnt, tracking=8):
    if not text:
        return 0
    return sum(d.textlength(c, font=fnt) + tracking for c in text) - tracking


def _wrap(d, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        trial = (cur + " " + w_).strip()
        if d.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def _block(d, x, y, text, fnt, fill, max_w, leading):
    for line in _wrap(d, text, fnt, max_w):
        d.text((x, y), line, font=fnt, fill=fill)
        y += leading
    return y


def _block_height(d, text, fnt, max_w, leading):
    return len(_wrap(d, text, fnt, max_w)) * leading


def _header(d, left_label, right_label=""):
    eb = _font("Poppins-SemiBold.ttf", 34)
    _letterspaced(d, (96, 84), left_label, eb, GOLD)
    if right_label:
        tw = _ls_width(d, right_label, eb, 6)
        _letterspaced(d, (W - 96 - tw, 84), right_label, eb, MUTED, tracking=6)
    d.line([(96, 148), (W - 96, 148)], fill=(255, 255, 255), width=2)


def _wordmark(d):
    wm = _font("Poppins-ExtraBold.ttf", 40)
    text = "TREND RADAR NG"
    tw = d.textlength(text, font=wm)
    d.text((W - 96 - tw, H - 122), text, font=wm, fill=CREAM)


def _pill(d, x, y, w_, h_, text, fnt, fill_bg, fill_txt, outline=None):
    d.rounded_rectangle(
        [x, y, x + w_, y + h_], radius=h_ // 2, fill=fill_bg, outline=outline, width=5
    )
    tw = d.textlength(text, font=fnt)
    d.text(
        (x + (w_ - tw) / 2, y + (h_ - fnt.size * 1.35) / 2 + 4),
        text,
        font=fnt,
        fill=fill_txt,
    )


def _img_response(img, fmt):
    buf = io.BytesIO()
    if fmt == "png":
        img.save(buf, format="PNG")
        mime = "image/png"
    else:
        img.save(buf, format="JPEG", quality=90)
        mime = "image/jpeg"
    buf.seek(0)
    return send_file(buf, mimetype=mime)


# ---------- Rate This Take: word-level mixed-color rendering ----------

def _take_tokens(text, gold):
    """Split the take into (word, is_gold) tokens. The gold phrase may sit
    anywhere in the sentence; nothing before or after it is lost."""
    if gold and gold in text:
        i = text.index(gold)
        before = text[:i].split()
        goldw = gold.split()
        after = text[i + len(gold):].split()
    else:
        words = text.split()
        before, goldw, after = words[:-2], words[-2:], []
    return (
        [(w, False) for w in before]
        + [(w, True) for w in goldw]
        + [(w, False) for w in after]
    )


def _fit_take(d, tokens, max_w, max_h):
    """Shrink until total block height fits the reserved quote zone."""
    size = 92
    while size >= 54:
        fnt = _font("Poppins-ExtraBold.ttf", size)
        space = d.textlength(" ", font=fnt)
        lines, cur = 1, 0
        for w, _ in tokens:
            ww = d.textlength(w, font=fnt)
            add = ww if cur == 0 else ww + space
            if cur + add > max_w and cur > 0:
                lines += 1
                cur = ww
            else:
                cur += add
        leading = int(size * 1.28) + 16
        if lines * leading <= max_h:
            return fnt, leading
        size -= 6
    return _font("Poppins-ExtraBold.ttf", 54), int(54 * 1.28) + 16


def _draw_take(d, x0, y, tokens, fnt, max_w, leading):
    space = d.textlength(" ", font=fnt)

    def flush(line, y):
        x = x0
        run_start = None
        run_end = None
        for idx, (w, g, ww) in enumerate(line):
            d.text((x, y), w, font=fnt, fill=GOLD if g else CREAM)
            if g:
                if run_start is None:
                    run_start = x
                run_end = x + ww
            next_gold = idx + 1 < len(line) and line[idx + 1][1]
            if g and not next_gold and run_start is not None:
                uy = y + fnt.size * 1.14
                d.rectangle([run_start, uy, run_end, uy + 12], fill=GOLD)
                run_start = None
            x += ww + space
        return y + leading

    line, cur_w = [], 0
    for w, g in tokens:
        ww = d.textlength(w, font=fnt)
        add = ww if not line else ww + space
        if cur_w + add > max_w and line:
            y = flush(line, y)
            line, cur_w = [], 0
            add = ww
        line.append((w, g, ww))
        cur_w += add
    if line:
        y = flush(line, y)
    return y


@genz_bp.route("/genz/take", methods=["GET", "POST"])
def rate_this_take():
    _ensure_fonts()
    src = request.get_json(silent=True) or request.args
    text = (src.get("text") or "").strip()
    gold = (src.get("gold") or "").strip()
    serial = (src.get("serial") or "001").strip()
    fmt = (src.get("format") or "jpg").lower()
    if not text:
        return {"error": "text is required"}, 400

    img, d = _gradient(BG_TAKE_TOP, BG_TAKE_BOT)
    _spine(d)
    _header(d, "RATE THIS TAKE", "NO " + serial)

    max_w = W - 192
    # Reserved zones (bottom-up): wordmark band from H-140; pills 110px tall
    # ending 20px above it; sub text (max 2 lines) above pills; quote above sub.
    pill_y_max = H - 140 - 20 - 110          # 810
    sub_zone = 2 * 62 + 36                    # 160
    quote_top = 240
    quote_max_h = pill_y_max - sub_zone - quote_top - 24  # 386

    tokens = _take_tokens(text, gold)
    quote, leading = _fit_take(d, tokens, max_w, quote_max_h)
    y = _draw_take(d, 96, quote_top, tokens, quote, max_w, leading)
    y += 24

    sub = _font("Poppins-Medium.ttf", 46)
    y = _block(d, 96, y, "Hot take or pure nonsense? Cast your vote.", sub, MUTED, max_w, 62)
    y += 36

    pill_y = min(y, pill_y_max)
    pf = _font("Poppins-ExtraBold.ttf", 52)
    _pill(d, 96, pill_y, 400, 110, "GBAM!", pf, GOLD, (20, 14, 4))
    _pill(d, 544, pill_y, 400, 110, "MTCHEEW", pf, None, CREAM, outline=CREAM)
    _wordmark(d)
    return _img_response(img, fmt)


@genz_bp.route("/genz/childhood", methods=["GET", "POST"])
def childhood_check():
    _ensure_fonts()
    src = request.get_json(silent=True) or request.args
    headline = (src.get("headline") or "If you remember these, your knee don old small:").strip()
    fmt = (src.get("format") or "jpg").lower()
    items = [
        (src.get("i1") or "").strip(),
        (src.get("i2") or "").strip(),
        (src.get("i3") or "").strip(),
    ]
    items = [i for i in items if i]
    if not items:
        return {"error": "at least i1 is required"}, 400

    img, d = _gradient(BG_KID_TOP, BG_KID_BOT)
    _spine(d)
    _header(d, "NAIJA CHILDHOOD CHECK")

    max_w = W - 192
    # Reserved zones: wordmark band from H-140; CTA (max 2 lines of 58)
    # sits directly above it.
    cta_top = H - 140 - (2 * 58) - 24         # 800
    footer_top = cta_top - 12                 # items must end above this

    head_size = 78
    while head_size > 52:
        head = _font("Poppins-ExtraBold.ttf", head_size)
        if len(_wrap(d, headline, head, max_w)) <= 3:
            break
        head_size -= 6
    head = _font("Poppins-ExtraBold.ttf", head_size)
    y = 220
    y = _block(d, 96, y, headline, head, CREAM, max_w, int(head_size * 1.28))
    y += 36

    item_size = 52
    while item_size > 34:
        item_f = _font("Poppins-Medium.ttf", item_size)
        leading = int(item_size * 1.27)
        bs = int(item_size * 1.04)
        total = sum(
            _block_height(d, it, item_f, max_w - bs - 34, leading) + 28 for it in items
        )
        if y + total <= footer_top:
            break
        item_size -= 4
    item_f = _font("Poppins-Medium.ttf", item_size)
    leading = int(item_size * 1.27)

    for it in items:
        bs = int(item_size * 1.04)
        d.rounded_rectangle([96, y + 6, 96 + bs, y + 6 + bs], radius=12, outline=GOLD, width=6)
        cx = 96 + bs * 0.22
        cy = y + 6 + bs * 0.52
        d.line([(cx, cy), (cx + bs * 0.2, cy + bs * 0.26)], fill=GOLD, width=8)
        d.line([(cx + bs * 0.2, cy + bs * 0.26), (cx + bs * 0.58, cy - bs * 0.3)], fill=GOLD, width=8)
        y = _block(d, 96 + bs + 34, y, it, item_f, CREAM, max_w - bs - 34, leading)
        y += 28

    cta = _font("Poppins-SemiBold.ttf", 44)
    n = len(items)
    _block(
        d, 96, min(y + 12, cta_top),
        "How many did you live through? Score yourself out of " + str(n) + " below.",
        cta, GREEN, max_w, 58,
    )
    _wordmark(d)
    return _img_response(img, fmt)
