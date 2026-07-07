"""
People's Voice card renderer — TRNG (v1.3, Poppins match, resilient font loading)
Drop-in module for the trendradar-cards Flask/Pillow service.
Fonts: Poppins Bold/SemiBold/Medium in the repo's fonts/ folder.
"""
import os
import random
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350  # portrait

NAVY_TOP    = (10, 22, 44)
NAVY_BOTTOM = (16, 38, 74)
WHITE       = (240, 244, 250)
AMBER       = (245, 166, 35)
GOLD        = (222, 178, 92)
BLUE        = (108, 148, 220)

_BASE = os.path.dirname(os.path.abspath(__file__))

def _font_path(name):
    """Find a font in fonts/ or the repo root; fail with a helpful listing."""
    for cand in (os.path.join(_BASE, "fonts", name), os.path.join(_BASE, name)):
        if os.path.exists(cand):
            return cand
    fonts_dir = os.path.join(_BASE, "fonts")
    listing = sorted(os.listdir(fonts_dir)) if os.path.isdir(fonts_dir) else "NO fonts/ folder"
    raise FileNotFoundError(
        f"Font {name} not found. fonts/ contains: {listing}. "
        f"Repo root contains: {sorted(f for f in os.listdir(_BASE) if not f.startswith('.'))[:40]}")

def F(name, size): return ImageFont.truetype(_font_path(name), size)

def _tracked(d, y, text, font, fill, tracking, cx):
    widths = [d.textlength(c, font=font) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for c, w in zip(text, widths):
        d.text((x, y), c, font=font, fill=fill)
        x += w + tracking

def render_peoples_voice(edition_text, date_text, question=None,
                         cta_text="DROP YOUR ANSWER IN THE COMMENTS", seed=7):
    img = Image.new("RGB", (W, H), NAVY_TOP)
    d = ImageDraw.Draw(img)

    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(
            int(NAVY_TOP[0] + (NAVY_BOTTOM[0] - NAVY_TOP[0]) * t),
            int(NAVY_TOP[1] + (NAVY_BOTTOM[1] - NAVY_TOP[1]) * t),
            int(NAVY_TOP[2] + (NAVY_BOTTOM[2] - NAVY_TOP[2]) * t)))

    rng = random.Random(seed)
    for _ in range(130):
        x, y = rng.randint(0, W - 1), rng.randint(0, H - 1)
        r = rng.choice([1, 1, 2])
        shade = rng.choice([(200, 214, 240), (120, 138, 175), (80, 96, 130)])
        d.ellipse([x, y, x + r, y + r], fill=shade)

    cx = W // 2

    # radar rings: faint wide outer, mid, bright inner, amber dot
    ry = 185
    d.ellipse([cx-110, ry-110, cx+110, ry+110], outline=(52, 74, 118), width=2)
    d.ellipse([cx-70,  ry-70,  cx+70,  ry+70],  outline=(88, 118, 180), width=2)
    d.ellipse([cx-40,  ry-40,  cx+40,  ry+40],  outline=(140, 175, 240), width=3)
    d.ellipse([cx-7,   ry-7,   cx+7,   ry+7],   fill=(150, 110, 62))

    # masthead
    _tracked(d, 355, "THE PEOPLE'S VOICE", F("Poppins-Bold.ttf", 46), WHITE, 5, cx)

    # edition line — auto-shrink so long edition names never overflow
    ed = edition_text.upper()
    size = 84
    while size > 48:
        ef = F("Poppins-Bold.ttf", size)
        total = sum(d.textlength(c, font=ef) for c in ed) + 7 * (len(ed) - 1)
        if total <= W - 140:
            break
        size -= 4
    _tracked(d, 490, ed, ef, AMBER, 7, cx)

    # date pill — thin outline
    pf = F("Poppins-SemiBold.ttf", 30)
    ptext = date_text.upper()
    ptw = d.textlength(ptext, font=pf)
    pw, ph = ptw + 84, 66
    px, py = cx - pw / 2, 655
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=ph / 2, outline=GOLD, width=2)
    d.text((cx - ptw / 2, py + (ph - 44) / 2), ptext, font=pf, fill=GOLD)

    # tagline
    _tracked(d, 785, "YOUR VOICE. YOUR NEWS. YOUR NIGERIA.",
             F("Poppins-SemiBold.ttf", 24), BLUE, 3, cx)

    # question block
    if question:
        d.line([(cx - 55, 880), (cx + 55, 880)], fill=(70, 96, 150), width=2)
        size = 50
        while size >= 30:
            qf = F("Poppins-SemiBold.ttf", size)
            words, lines, cur = question.split(), [], ""
            maxw = W - 190
            for w_ in words:
                trial = (cur + " " + w_).strip()
                if d.textlength(trial, font=qf) <= maxw:
                    cur = trial
                else:
                    lines.append(cur); cur = w_
            lines.append(cur)
            line_h = size + 18
            if line_h * len(lines) <= 320 and len(lines) <= 5:
                break
            size -= 4
        qy = 925
        for ln in lines:
            lw = d.textlength(ln, font=qf)
            d.text((cx - lw / 2, qy), ln, font=qf, fill=WHITE)
            qy += line_h
        _tracked(d, qy + 42, cta_text.upper(),
                 F("Poppins-Medium.ttf", 23), GOLD, 3, cx)

    return img

if __name__ == "__main__":
    img = render_peoples_voice(
        edition_text="Second Edition",
        date_text="Wednesday, 8 July  \u00b7  12:00 PM WAT",
        question="What is the one thing you would fix in Nigeria tomorrow if you had the power?")
    img.save("pv_sample_v2.png")
    print("rendered v2")
