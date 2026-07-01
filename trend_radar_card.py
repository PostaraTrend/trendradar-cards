#!/usr/bin/env python3
"""
Trend Radar NG — Headline News-Card Template
============================================
Turns a selected headline + source into an on-brand photo-post image so the
link-free Facebook posts carry a visual instead of plain text.

One function does the work:  render_card(...)  -> writes a PNG.

Brand (Trend Radar NG, standalone page):
  navy   #0a1428   navy2 #0c2038   panel #0f2742   line  #1d4660
  green  #18e0a0   green-dim #18a078   ink #eef6ff   mute #9ab0cb
  Fonts: Poppins (Bold / SemiBold / Medium / Regular)

Output: 1080 x 1350 (4:5 portrait — max mobile feed real estate), rendered at
2x (2160 x 2700) and downsampled with LANCZOS for crisp edges.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
import os, textwrap, math

HERE = os.path.dirname(os.path.abspath(__file__))
# Fonts live right next to this script (flat repo — no subfolder needed).
FONTS = HERE

# If a weight is missing, fall back to the nearest available one so the
# service never crashes on a font that failed to upload.
_FONT_FALLBACKS = {
    "Poppins-ExtraBold.ttf": ["Poppins-Bold.ttf"],
    "Poppins-Bold.ttf":      ["Poppins-ExtraBold.ttf", "Poppins-Medium.ttf"],
    "Poppins-SemiBold.ttf":  ["Poppins-Medium.ttf", "Poppins-Bold.ttf"],
    "Poppins-Medium.ttf":    ["Poppins-Regular.ttf", "Poppins-Bold.ttf"],
    "Poppins-Regular.ttf":   ["Poppins-Medium.ttf"],
    # Noto Sans carries Yoruba glyphs (Ṣ ọ ẹ + tone marks); if it ever fails to
    # upload, degrade to Poppins rather than crash (English still renders).
    "NotoSans-Bold.ttf":     ["Poppins-Bold.ttf"],
    "NotoSans-Regular.ttf":  ["Poppins-Regular.ttf"],
}

# ---- brand ----------------------------------------------------------------
NAVY   = (10, 20, 40)
NAVY2  = (12, 32, 56)
PANEL  = (15, 39, 66)
LINE   = (29, 70, 96)
GREEN  = (24, 224, 160)
GREEN_D= (24, 160, 120)
INK    = (238, 246, 255)
MUTE   = (154, 176, 203)
GOLD   = (231, 196, 132)   # warm gold — gospel cross-glow accent

# per-lane accent for the small category tag (brand stays green overall)
LANE_ACCENT = {
    "POLITICS":      (24, 224, 160),   # radar green
    "ENTERTAINMENT": (245, 196, 81),   # amber
    "EPL":           (110, 168, 255),  # sky
    "FOOTBALL":      (110, 168, 255),
    "ECONOMY":       (48, 200, 184),   # teal
    "GOSPEL":        (181, 152, 255),  # warm violet
    "DIASPORA":      (255, 138, 76),   # coral
    "TECH":          (26, 200, 214),   # electric cyan — Naija Tech
}

SCALE = 2
W, H = 1080, 1350
W2, H2 = W * SCALE, H * SCALE
PAD = 96 * SCALE

def font(name, size):
    for cand in [name] + _FONT_FALLBACKS.get(name, []):
        p = os.path.join(FONTS, cand)
        if os.path.exists(p):
            return ImageFont.truetype(p, size * SCALE)
    return ImageFont.load_default()

F_BOLD   = "Poppins-Bold.ttf"
F_XBOLD  = "Poppins-ExtraBold.ttf"
F_SEMI   = "Poppins-SemiBold.ttf"
F_MED    = "Poppins-Medium.ttf"
F_REG    = "Poppins-Regular.ttf"

# Noto Sans fallback — Poppins lacks the Yoruba dot-below letters (Ṣ ọ ẹ) and
# combining tone marks, which otherwise render as tofu boxes. We switch a text
# element to Noto ONLY when it actually contains those characters, so plain
# English headlines keep the Poppins brand look.
F_NOTO_BOLD = "NotoSans-Bold.ttf"
F_NOTO_REG  = "NotoSans-Regular.ttf"

_NOTO_FOR = {
    F_BOLD:  F_NOTO_BOLD, F_XBOLD: F_NOTO_BOLD, F_SEMI: F_NOTO_BOLD,
    F_MED:   F_NOTO_REG,  F_REG:   F_NOTO_REG,
}

def _needs_noto(text):
    """True if the string has characters Poppins cannot render (Yoruba etc.)."""
    for ch in text or "":
        cp = ord(ch)
        if 0x0300 <= cp <= 0x036F:      # combining diacritical marks (tone)
            return True
        if 0x1E00 <= cp <= 0x1EFF:      # Latin Extended Additional (Ṣ Ẹ Ọ …)
            return True
        if cp >= 0x0250:                # anything past Latin Extended-B
            return True
    return False

def font_for(text, name, size):
    """Pick Noto Sans for this text if it needs it, else the requested Poppins."""
    if _needs_noto(text):
        return font(_NOTO_FOR.get(name, F_NOTO_REG), size)
    return font(name, size)

# ---- background -----------------------------------------------------------
def background():
    """Navy vertical gradient + radial radar-green glow top-right.
    Memory-light: float32 + broadcasting (no full-size repeat) so it fits a 512MB instance."""
    top = np.array(NAVY, dtype=np.float32)
    bot = np.array(NAVY2, dtype=np.float32)
    g = np.array((24, 224, 160), dtype=np.float32)

    yy = np.linspace(0, 1, H2, dtype=np.float32)[:, None]       # (H2,1)
    base = top[None, :] * (1 - yy) + bot[None, :] * yy          # (H2,3)

    cx, cy = W2 * 0.82, H2 * -0.05
    xs = np.arange(W2, dtype=np.float32)[None, :]               # (1,W2)
    ys = np.arange(H2, dtype=np.float32)[:, None]               # (H2,1)
    r = W2 * 0.95
    glow = np.clip(1 - np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) / r, 0, 1) ** 2.2  # (H2,W2)

    arr = glow[:, :, None] * (g[None, None, :] * 0.14)          # (H2,W2,3)
    del glow
    arr += base[:, None, :]
    del base
    np.clip(arr, 0, 255, out=arr)
    return Image.fromarray(arr.astype(np.uint8), "RGB")

def gospel_background():
    """Original night-sky render: warm glow rising behind a cross on a hill,
    deep indigo→violet sky with a faint nebula band. Memory-light float32."""
    top = np.array((12, 14, 36), dtype=np.float32)
    bot = np.array((30, 24, 52), dtype=np.float32)
    yy = np.linspace(0, 1, H2, dtype=np.float32)[:, None]
    base = top[None, :] * (1 - yy) + bot[None, :] * yy

    xs = np.arange(W2, dtype=np.float32)[None, :]
    ys = np.arange(H2, dtype=np.float32)[:, None]

    # warm glow rising from behind the cross (lower-centre-right)
    gx, gy = W2 * 0.64, H2 * 0.80
    rg = H2 * 0.60
    glow = np.clip(1 - np.sqrt((xs - gx) ** 2 + (ys - gy) ** 2) / rg, 0, 1) ** 2.2
    gold = np.array((250, 196, 120), dtype=np.float32)
    arr = base[:, None, :] + glow[:, :, None] * (gold[None, None, :] * 0.26)
    del glow

    # faint violet nebula band on the diagonal (milky-way feel)
    dist = np.abs(ys - (-0.5 * xs + H2 * 0.52)) / (H2 * 0.5)
    neb = np.clip(1 - dist, 0, 1) ** 3.0
    violet = np.array((150, 120, 190), dtype=np.float32)
    arr += neb[:, :, None] * (violet[None, None, :] * 0.09)
    del neb, dist

    np.clip(arr, 0, 255, out=arr)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def gospel_overlay(img):
    """Stars + reinforced halo + dark hill + rim-lit cross + footer scrim."""
    import random as _r
    base = img.convert("RGBA")
    cx = int(W2 * 0.64)
    hill_y = int(H2 * 0.84)

    # reinforce the halo of light behind the cross
    halo = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    halo_cy = int(H2 * 0.68)
    hr = int(W2 * 0.26)
    hd.ellipse([cx - hr, halo_cy - hr, cx + hr, halo_cy + hr], fill=(255, 205, 135, 110))
    halo = halo.filter(ImageFilter.GaussianBlur(55 * SCALE))
    base = Image.alpha_composite(base, halo)

    # starfield (denser toward the top, avoids the bright glow)
    stars = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stars)
    _r.seed(11)
    for _ in range(170):
        x = _r.randint(0, W2)
        y = _r.randint(0, int(H2 * 0.74))
        rad = _r.choice([1, 1, 1, 2, 2, 3]) * (SCALE // 2 or 1)
        a = _r.randint(30, 150)
        sd.ellipse([x - rad, y - rad, x + rad, y + rad], fill=(255, 255, 255, a))
    base = Image.alpha_composite(base, stars)

    ov = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)

    # hill silhouette (smooth mound, highest under the cross)
    pts = [(0, H2)]
    for fx in [0.0, 0.12, 0.28, 0.45, 0.64, 0.8, 1.0]:
        rise = math.exp(-((fx - 0.64) ** 2) / (2 * 0.20 ** 2))
        py = int(H2 * 0.93 - (H2 * 0.93 - hill_y) * rise)
        pts.append((int(W2 * fx), py))
    pts.append((W2, H2))
    d.polygon(pts, fill=(7, 8, 18, 255))

    # cross silhouette, rim-lit gold
    beam_w = int(W2 * 0.030)
    cross_h = int(H2 * 0.26)
    top_y = hill_y - cross_h
    vx0, vx1 = cx - beam_w // 2, cx + beam_w // 2
    arm_w = int(W2 * 0.125)
    arm_y = top_y + int(cross_h * 0.30)
    arm_h = beam_w
    rim = max(2, 3 * SCALE // 2)
    d.rectangle([vx0 - rim, top_y - rim, vx1 + rim, hill_y + rim], fill=(247, 205, 140, 210))
    d.rectangle([cx - arm_w // 2 - rim, arm_y - rim, cx + arm_w // 2 + rim, arm_y + arm_h + rim],
                fill=(247, 205, 140, 210))
    d.rectangle([vx0, top_y, vx1, hill_y], fill=(10, 10, 18, 255))
    d.rectangle([cx - arm_w // 2, arm_y, cx + arm_w // 2, arm_y + arm_h], fill=(10, 10, 18, 255))

    base = Image.alpha_composite(base, ov)

    # bottom scrim so the footer text stays legible over the hill
    scrim = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    sc = ImageDraw.Draw(scrim)
    sh = int(H2 * 0.16)
    for i in range(sh):
        a = int(150 * (i / sh))
        sc.line([(0, H2 - sh + i), (W2, H2 - sh + i)], fill=(6, 7, 16, a))
    base = Image.alpha_composite(base, scrim)

    return base.convert("RGB")


def radar_overlay(img):
    """A crisp radar dial anchored bottom-right as the brand device, plus a soft glow."""
    ov = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    cx, cy = int(W2 * 0.96), int(H2 * 1.02)
    R = int(W2 * 0.62)
    # soft glow under the dial
    glow = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.pieslice([cx - R, cy - R, cx + R, cy + R], 188, 244, fill=GREEN + (24,))
    glow = glow.filter(ImageFilter.GaussianBlur(44 * SCALE))
    ov = Image.alpha_composite(ov, glow)
    # the dial itself, faint
    d2 = ImageDraw.Draw(ov)
    radar_dial(d2, cx, cy, R, GREEN, alpha=30, rings=4, sweep_deg=40,
               crosshair=True, blip=True, lw=2)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

# ---- text helpers ---------------------------------------------------------
def tracked(draw, xy, text, fnt, fill, spacing):
    """Draw letter-spaced text (for small caps labels). Returns total width."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + spacing * SCALE
    return x - xy[0]

def tracked_width(draw, text, fnt, spacing):
    return sum(draw.textlength(ch, font=fnt) for ch in text) + spacing * SCALE * (len(text) - 1)

def wrap_to_width(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def fit_headline(draw, text, max_w, max_h, start=84, min_size=46):
    """Pick the largest Bold size whose wrapped block fits the box.
    Uses Noto Sans Bold instead of Poppins Bold when the headline needs it."""
    head_name = F_NOTO_BOLD if _needs_noto(text) else F_BOLD
    size = start
    while size >= min_size:
        fnt = font(head_name, size)
        lines = wrap_to_width(draw, text, fnt, max_w)
        lh = (fnt.getbbox("Ag")[3] - fnt.getbbox("Ag")[1]) * 1.16
        if len(lines) * lh <= max_h and len(lines) <= 6:
            return fnt, lines, lh
        size -= 3
    fnt = font(head_name, min_size)
    lines = wrap_to_width(draw, text, fnt, max_w)
    lh = (fnt.getbbox("Ag")[3] - fnt.getbbox("Ag")[1]) * 1.16
    return fnt, lines, lh

def rounded(draw, box, radius, **kw):
    draw.rounded_rectangle(box, radius=radius * SCALE, **kw)

def radar_dial(draw, cx, cy, r, color, alpha=255, rings=3, sweep_deg=48,
               crosshair=True, blip=True, lw=2):
    """Draw a crisp radar dial: concentric rings, crosshair, a sweep wedge, a blip."""
    col = color + (alpha,)
    # sweep wedge (filled, soft)
    start = -58
    draw.pieslice([cx - r, cy - r, cx + r, cy + r], start, start + sweep_deg,
                  fill=color + (max(18, alpha // 6),))
    # rings
    for i in range(rings, 0, -1):
        rr = r * i / rings
        draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                     outline=color + (alpha,), width=lw * SCALE)
    # crosshair
    if crosshair:
        ch = color + (max(40, alpha // 2),)
        draw.line([cx - r, cy, cx + r, cy], fill=ch, width=lw * SCALE)
        draw.line([cx, cy - r, cx, cy + r], fill=ch, width=lw * SCALE)
    # sweep edge line
    import math as _m
    ang = _m.radians(start + sweep_deg)
    draw.line([cx, cy, cx + r * _m.cos(ang), cy + r * _m.sin(ang)],
              fill=color + (alpha,), width=lw * SCALE)
    # blip
    if blip:
        bx, by = cx + r * 0.62 * _m.cos(_m.radians(start + sweep_deg - 14)), \
                 cy + r * 0.62 * _m.sin(_m.radians(start + sweep_deg - 14))
        br = max(3 * SCALE, r * 0.09)
        draw.ellipse([bx - br, by - br, bx + br, by + br], fill=color + (alpha,))

# ---- main render ----------------------------------------------------------
def render_card(headline, source, category="POLITICS", date_str="",
                handle="fb.com/TrendRadarNG", out_path="card.png"):
    """Render and save to a PNG path. Returns the path."""
    img = build_card(headline, source, category, date_str, handle)
    img.save(out_path, "PNG")
    return out_path


def build_card(headline, source, category="POLITICS", date_str="",
               handle="fb.com/TrendRadarNG"):
    """Render and return the final 1080x1350 PIL Image (no disk write)."""
    category = category.upper()
    accent = LANE_ACCENT.get(category, GREEN)
    is_gospel = (category == "GOSPEL")
    chip_accent = GOLD if is_gospel else accent
    handle_col = GOLD if is_gospel else GREEN

    if is_gospel:
        img = gospel_background()
        img = gospel_overlay(img)
    else:
        img = background()
        img = radar_overlay(img)
    d = ImageDraw.Draw(img)

    # (No brand pill: the page header already shows "Trend Radar NG" above every
    #  post, so the category line now leads the card.)
    py = PAD

    # date (right)
    if date_str:
        f_date = font(F_MED, 20)
        dw = d.textlength(date_str, font=f_date)
        d.text((W2 - PAD - dw, py + 2 * SCALE), date_str, font=f_date, fill=MUTE)

    # --- category line (leads the card) ---
    f_cat = font(F_SEMI, 22)
    cat_label = "NAIJA TECH" if category == "TECH" else f"{category} \u00b7 NIGERIA"
    cat_y = py
    tracked(d, (PAD, cat_y), cat_label, f_cat, accent, 4)
    # accent rule under category
    rule_y = cat_y + 50 * SCALE
    d.rectangle([PAD, rule_y, PAD + 70 * SCALE, rule_y + 5 * SCALE], fill=accent)

    # --- headline (hero) ---
    box_top = rule_y + 70 * SCALE
    box_bottom = H2 - PAD - 230 * SCALE
    max_w = W2 - 2 * PAD
    max_h = box_bottom - box_top
    f_head, lines, lh = fit_headline(d, headline, max_w, max_h, start=84, min_size=46)
    # vertically center the block in its box
    block_h = len(lines) * lh
    y = box_top + (max_h - block_h) / 2
    for ln in lines:
        d.text((PAD, y), ln, font=f_head, fill=INK)
        y += lh

    # --- source chip ---
    src_text = f"According to {source}"
    f_src = font_for(src_text, F_MED, 26)
    chip_pad = 30 * SCALE
    chip_h = 74 * SCALE
    chip_w = d.textlength(src_text, font=f_src) + chip_pad * 2 + 26 * SCALE
    chip_y = H2 - PAD - 150 * SCALE
    rounded(d, [PAD, chip_y, PAD + chip_w, chip_y + chip_h], 14,
            fill=PANEL, outline=LINE, width=2 * SCALE)
    # green accent bar
    d.rectangle([PAD, chip_y + 14 * SCALE, PAD + 6 * SCALE, chip_y + chip_h - 14 * SCALE],
                fill=chip_accent)
    src_ty = chip_y + (chip_h - (f_src.getbbox("Ag")[3] - f_src.getbbox("Ag")[1])) // 2 - 4 * SCALE
    d.text((PAD + chip_pad + 14 * SCALE, src_ty), src_text, font=f_src, fill=INK)

    # --- footer ---
    foot_y = H2 - PAD - 38 * SCALE
    d.line([PAD, foot_y - 26 * SCALE, W2 - PAD, foot_y - 26 * SCALE], fill=LINE, width=2 * SCALE)
    f_hand = font(F_SEMI, 22)
    d.text((PAD, foot_y), handle, font=f_hand, fill=handle_col)
    f_tag = font(F_REG, 19)
    tag = "Nigeria, curated."
    tagw = d.textlength(tag, font=f_tag)
    d.text((W2 - PAD - tagw, foot_y + 2 * SCALE), tag, font=f_tag, fill=MUTE)

    out = img.resize((W, H), Image.LANCZOS)
    return out



# ---- wisdom lane (Trend Radar navy/radar brand scheme) --------------------
def _wisdom_fit(d, text, bold, max_w, max_h, start, min_size,
                line_mult=1.22, max_lines=6):
    """Largest size whose wrapped block fits the box. Noto-aware for the original."""
    if bold:
        name = F_NOTO_BOLD if _needs_noto(text) else F_BOLD
        size = start
        while size >= min_size:
            fnt = font(name, size)
            lines = wrap_to_width(d, text, fnt, max_w)
            lh = (fnt.getbbox("Ag")[3] - fnt.getbbox("Ag")[1]) * line_mult
            if len(lines) * lh <= max_h and len(lines) <= max_lines:
                return fnt, lines, lh
            size -= 3
        fnt = font(name, min_size)
    else:
        size = start
        while size >= min_size:
            fnt = font_for(text, F_MED, size)
            lines = wrap_to_width(d, text, fnt, max_w)
            lh = (fnt.getbbox("Ag")[3] - fnt.getbbox("Ag")[1]) * line_mult
            if len(lines) * lh <= max_h and len(lines) <= max_lines:
                return fnt, lines, lh
            size -= 3
        fnt = font_for(text, F_MED, min_size)
    lines = wrap_to_width(d, text, fnt, max_w)
    lh = (fnt.getbbox("Ag")[3] - fnt.getbbox("Ag")[1]) * line_mult
    return fnt, lines, lh


def _wisdom_centered(d, lines, fnt, lh, y, fill, cx):
    for ln in lines:
        w = d.textlength(ln, font=fnt)
        d.text((cx - w / 2, y), ln, font=fnt, fill=fill)
        y += lh
    return y


def build_wisdom_card(proverb, meaning, language="", date_str="",
                      handle="fb.com/TrendRadarNG", **_ignored):
    """Wisdom-lane card in the Trend Radar navy/radar brand scheme. Proverb in
    Noto Sans (carries the dot-below marks), warm-gold wisdom accent, white-on-green
    follow button. Extra kwargs (image_class, image_url) accepted and ignored."""
    accent = GOLD
    img = background()
    img = radar_overlay(img)
    d = ImageDraw.Draw(img)
    cx = W2 // 2

    # --- category line: LANGUAGE \u00b7 WISDOM (centered) ---
    f_cat = font(F_SEMI, 22)
    cat_label = f"{(language or 'PROVERB').upper()} \u00b7 WISDOM"
    cat_w = tracked_width(d, cat_label, f_cat, 4)
    cat_y = PAD + 30 * SCALE
    tracked(d, (cx - cat_w / 2, cat_y), cat_label, f_cat, accent, 4)
    rule_y = cat_y + 52 * SCALE
    d.rectangle([cx - 35 * SCALE, rule_y, cx + 35 * SCALE, rule_y + 5 * SCALE], fill=accent)

    # --- hero: proverb (big) + meaning (lighter), centered as a block ---
    region_top = rule_y + 40 * SCALE
    region_bot = H2 - PAD - 210 * SCALE
    max_w = W2 - 2 * PAD
    pf, plines, plh = _wisdom_fit(d, proverb, True, max_w, (region_bot - region_top) * 0.62,
                                  start=92, min_size=44, line_mult=1.22, max_lines=6)
    mf, mlines, mlh = _wisdom_fit(d, meaning, False, max_w, (region_bot - region_top) * 0.30,
                                  start=40, min_size=26, line_mult=1.3, max_lines=4)
    gap = 76 * SCALE
    block_h = len(plines) * plh + gap + len(mlines) * mlh
    y = region_top + ((region_bot - region_top) - block_h) / 2
    y = _wisdom_centered(d, plines, pf, plh, y, INK, cx)
    rmid = y + 40 * SCALE
    d.rectangle([cx - 28 * SCALE, rmid, cx + 28 * SCALE, rmid + 4 * SCALE], fill=accent)
    y += gap
    _wisdom_centered(d, mlines, mf, mlh, y, MUTE, cx)

    # --- CTA button: white text on darker green ---
    cta = "FOLLOW FOR DAILY WISDOM"
    f_cta = font(F_BOLD, 20)
    cta_tw = tracked_width(d, cta, f_cta, 3)
    cta_pad_x = 44 * SCALE
    cta_pill_w = cta_tw + cta_pad_x * 2
    cta_pill_h = 60 * SCALE
    cta_x0 = cx - cta_pill_w / 2
    cta_y0 = H2 - PAD - 155 * SCALE
    rounded(d, [cta_x0, cta_y0, cta_x0 + cta_pill_w, cta_y0 + cta_pill_h], 30, fill=GREEN_D)
    cta_ty = cta_y0 + (cta_pill_h - (f_cta.getbbox("A")[3] - f_cta.getbbox("A")[1])) // 2 - 4 * SCALE
    tracked(d, (cta_x0 + cta_pad_x, cta_ty), cta, f_cta, (255, 255, 255), 3)

    # --- footer (same device as the news cards) ---
    foot_y = H2 - PAD - 38 * SCALE
    d.line([PAD, foot_y - 26 * SCALE, W2 - PAD, foot_y - 26 * SCALE], fill=LINE, width=2 * SCALE)
    f_hand = font(F_SEMI, 22)
    d.text((PAD, foot_y), handle, font=f_hand, fill=GREEN)
    f_tag = font(F_REG, 19)
    tag = "Wisdom, curated."
    tagw = d.textlength(tag, font=f_tag)
    d.text((W2 - PAD - tagw, foot_y + 2 * SCALE), tag, font=f_tag, fill=MUTE)

    return img.resize((W, H), Image.LANCZOS)


# ---- reflection lane (calm civic voice, weekly) ---------------------------
# Distinct from the news lanes: a quieter slate-blue accent and a large opening
# quote mark, with the pull-quote as the hero. Same navy radar brand so it still
# belongs to Trend Radar NG. Uses the shared helpers (background, radar_overlay,
# _wisdom_fit, _wisdom_centered, tracked, rounded) already defined above.
REFLECT = (150, 178, 224)      # calm slate-blue, unique to the reflection lane
REFLECT_D = (96, 120, 168)     # dimmer companion for rules / outline


def build_reflection_card(theme_title, pull_quote, date_str="",
                          handle="fb.com/TrendRadarNG", **_ignored):
    """Reflection-lane card: eyebrow 'REFLECTION', a large quote mark, the
    pull_quote as centered hero, the theme_title beneath. Calm slate accent.
    Extra kwargs accepted and ignored for call-site parity with the other lanes."""
    accent = REFLECT
    img = background()
    img = radar_overlay(img)
    d = ImageDraw.Draw(img)
    cx = W2 // 2

    # date (right, same position as the news card)
    if date_str:
        f_date = font(F_MED, 20)
        dw = d.textlength(date_str, font=f_date)
        d.text((W2 - PAD - dw, PAD + 2 * SCALE), date_str, font=f_date, fill=MUTE)

    # --- eyebrow: REFLECTION (centered, tracked) ---
    f_cat = font(F_SEMI, 22)
    cat_label = "REFLECTION"
    cat_w = tracked_width(d, cat_label, f_cat, 6)
    cat_y = PAD + 30 * SCALE
    tracked(d, (cx - cat_w / 2, cat_y), cat_label, f_cat, accent, 6)
    rule_y = cat_y + 52 * SCALE
    d.rectangle([cx - 35 * SCALE, rule_y, cx + 35 * SCALE, rule_y + 5 * SCALE], fill=accent)

    # --- large opening quote mark, centered, low-key ---
    f_mark = font(F_XBOLD, 150)
    mark = "\u201C"
    mw = d.textlength(mark, font=f_mark)
    mark_y = rule_y + 30 * SCALE
    d.text((cx - mw / 2, mark_y), mark, font=f_mark, fill=REFLECT_D)

    # --- hero: pull_quote (big, centered) ---
    region_top = mark_y + 130 * SCALE
    region_bot = H2 - PAD - 250 * SCALE
    max_w = W2 - 2 * PAD
    qf, qlines, qlh = _wisdom_fit(d, pull_quote, True, max_w, (region_bot - region_top) * 0.78,
                                  start=78, min_size=42, line_mult=1.26, max_lines=6)
    block_h = len(qlines) * qlh
    y = region_top + ((region_bot - region_top) - block_h) / 2
    y = _wisdom_centered(d, qlines, qf, qlh, y, INK, cx)

    # --- small accent rule + theme_title beneath ---
    if theme_title:
        rmid = y + 34 * SCALE
        d.rectangle([cx - 28 * SCALE, rmid, cx + 28 * SCALE, rmid + 4 * SCALE], fill=accent)
        tf = font_for(theme_title, F_MED, 30)
        tlines = wrap_to_width(d, theme_title, tf, max_w)
        tlh = (tf.getbbox("Ag")[3] - tf.getbbox("Ag")[1]) * 1.3
        _wisdom_centered(d, tlines, tf, tlh, rmid + 30 * SCALE, MUTE, cx)

    # --- CTA: quiet outline pill (calmer than the green wisdom pill) ---
    cta = "A WEEKLY REFLECTION"
    f_cta = font(F_BOLD, 20)
    cta_tw = tracked_width(d, cta, f_cta, 3)
    cta_pad_x = 44 * SCALE
    cta_pill_w = cta_tw + cta_pad_x * 2
    cta_pill_h = 60 * SCALE
    cta_x0 = cx - cta_pill_w / 2
    cta_y0 = H2 - PAD - 155 * SCALE
    rounded(d, [cta_x0, cta_y0, cta_x0 + cta_pill_w, cta_y0 + cta_pill_h], 30,
            outline=accent, width=2 * SCALE)
    cta_ty = cta_y0 + (cta_pill_h - (f_cta.getbbox("A")[3] - f_cta.getbbox("A")[1])) // 2 - 4 * SCALE
    tracked(d, (cta_x0 + cta_pad_x, cta_ty), cta, f_cta, accent, 3)

    # --- footer (same device as the other cards) ---
    foot_y = H2 - PAD - 38 * SCALE
    d.line([PAD, foot_y - 26 * SCALE, W2 - PAD, foot_y - 26 * SCALE], fill=LINE, width=2 * SCALE)
    f_hand = font(F_SEMI, 22)
    d.text((PAD, foot_y), handle, font=f_hand, fill=GREEN)
    f_tag = font(F_REG, 19)
    tag = "Reflection, curated."
    tagw = d.textlength(tag, font=f_tag)
    d.text((W2 - PAD - tagw, foot_y + 2 * SCALE), tag, font=f_tag, fill=MUTE)

    return img.resize((W, H), Image.LANCZOS)
# ---- football results scoreboard lane (with flags) -----------------------
import urllib.request as _urlreq
from io import BytesIO as _BytesIO

_FLAG_CACHE = {}

def _fetch_flag(url, target_h):
    """Fetch and resize a flag/crest. Bulletproof: any failure returns None so
    the row renders text-only rather than crashing. Cached per-render."""
    if not url:
        return None
    key = (url, target_h)
    if key in _FLAG_CACHE:
        return _FLAG_CACHE[key]
    try:
        req = _urlreq.Request(url, headers={"User-Agent": "TrendRadarNG/1.0"})
        with _urlreq.urlopen(req, timeout=3) as r:
            data = r.read()
        im = Image.open(_BytesIO(data)).convert("RGBA")
        w, h = im.size
        if h == 0:
            return None
        new_w = max(1, int(w * (target_h / h)))
        im = im.resize((new_w, target_h), Image.LANCZOS)
        _FLAG_CACHE[key] = im
        return im
    except Exception:
        _FLAG_CACHE[key] = None
        return None


def build_results_card(title, groups, date_str="",
                       handle="fb.com/TrendRadarNG", **_ignored):
    """Football results card with country flags. groups is a list of
    {"round": str, "matches": [ {home, away, score, pen, home_flag, away_flag}, ... ]}.
    Falls back to text-only per row if a flag cannot be fetched. Also accepts
    plain-string matches for backward compatibility."""
    accent = LANE_ACCENT.get("FOOTBALL", GREEN)
    img = background()
    img = radar_overlay(img)
    img = img.convert("RGBA")
    d = ImageDraw.Draw(img)

    py = PAD
    if date_str:
        f_date = font(F_MED, 20)
        dw = d.textlength(date_str, font=f_date)
        d.text((W2 - PAD - dw, py + 2 * SCALE), date_str, font=f_date, fill=MUTE)

    f_cat = font(F_SEMI, 22)
    tracked(d, (PAD, py), "FOOTBALL \u00b7 RESULTS", f_cat, accent, 4)
    rule_y = py + 50 * SCALE
    d.rectangle([PAD, rule_y, PAD + 70 * SCALE, rule_y + 5 * SCALE], fill=accent)

    title_y = rule_y + 40 * SCALE
    f_title = font(F_BOLD, 48)
    for ln in wrap_to_width(d, title, f_title, W2 - 2 * PAD):
        d.text((PAD, title_y), ln, font=f_title, fill=INK)
        title_y += (f_title.getbbox("Ag")[3] - f_title.getbbox("Ag")[1]) * 1.15

    y = title_y + 34 * SCALE
    f_round = font(F_SEMI, 24)
    f_row = font(F_MED, 30)
    row_h = 46 * SCALE
    flag_h = 30 * SCALE
    round_gap = 18 * SCALE
    bottom_limit = H2 - PAD - 96 * SCALE

    for g in groups:
        if y > bottom_limit:
            break
        rnd = (g.get("round") or "").strip()
        if rnd:
            d.text((PAD, y), rnd.upper(), font=f_round, fill=accent)
            y += (f_round.getbbox("Ag")[3] - f_round.getbbox("Ag")[1]) + round_gap

        for m in (g.get("matches") or []):
            if y > bottom_limit:
                break

            # Backward-compat: allow a plain string.
            if isinstance(m, str):
                fm = font_for(m, F_MED, 28)
                d.text((PAD, y), m, font=fm, fill=INK)
                y += row_h
                continue

            home = m.get("home", "")
            away = m.get("away", "")
            score = m.get("score", "")
            pen = m.get("pen", "")

            hf = _fetch_flag(m.get("home_flag"), flag_h)
            af = _fetch_flag(m.get("away_flag"), flag_h)

            x = PAD
            mid_y = y + (row_h - flag_h) // 2
            gap = 12 * SCALE

            # home flag
            if hf is not None:
                img.paste(hf, (int(x), int(mid_y)), hf)
                x += hf.width + gap
            # home name
            fh = font_for(home, F_MED, 30)
            d.text((x, y), home, font=fh, fill=INK)
            x += d.textlength(home, font=fh) + gap

            # score (accent, bold)
            fs = font(F_BOLD, 30)
            d.text((x, y), score, font=fs, fill=accent)
            x += d.textlength(score, font=fs) + gap

            # away name
            fa = font_for(away, F_MED, 30)
            d.text((x, y), away, font=fa, fill=INK)
            x += d.textlength(away, font=fa) + gap

            # away flag
            if af is not None:
                img.paste(af, (int(x), int(mid_y)), af)
                x += af.width + gap

            # penalty note on the next line, muted, if present
            if pen:
                y += row_h
                fp = font(F_REG, 22)
                d.text((PAD, y), pen, font=fp, fill=MUTE)
                y += int(row_h * 0.7)
            else:
                y += row_h

        y += round_gap

    d = ImageDraw.Draw(img)  # refresh after pastes
    foot_y = H2 - PAD - 38 * SCALE
    d.line([PAD, foot_y - 26 * SCALE, W2 - PAD, foot_y - 26 * SCALE], fill=LINE, width=2 * SCALE)
    f_hand = font(F_SEMI, 22)
    d.text((PAD, foot_y), handle, font=f_hand, fill=GREEN)
    f_tag = font(F_REG, 19)
    tag = "Results, curated."
    tagw = d.textlength(tag, font=f_tag)
    d.text((W2 - PAD - tagw, foot_y + 2 * SCALE), tag, font=f_tag, fill=MUTE)

    return img.convert("RGB").resize((W, H), Image.LANCZOS)


if __name__ == "__main__":
    samples = [
        dict(headline="Jigawa approves N405 billion 2026 budget with priority on roads and primary healthcare",
             source="Premium Times", category="POLITICS", date_str="26 Jun 2026",
             out_path="outputs/card_politics.png"),
        dict(headline="Burna Boy announces sold-out Lagos homecoming concert to close the year",
             source="Pulse Nigeria", category="ENTERTAINMENT", date_str="26 Jun 2026",
             out_path="outputs/card_entertainment.png"),
        dict(headline="Naira firms against the dollar as CBN clears backlog of matured FX forwards",
             source="Nairametrics", category="ECONOMY", date_str="26 Jun 2026",
             out_path="outputs/card_economy.png"),
        dict(headline="Osimhen on the scoresheet again as his side edge a five-goal thriller",
             source="Complete Sports", category="EPL", date_str="26 Jun 2026",
             out_path="outputs/card_epl.png"),
        dict(headline="Ford rehires 350 veteran engineers after AI quality push falls short",
             source="TechCabal", category="TECH", date_str="30 Jun 2026",
             out_path="outputs/card_tech.png"),
    ]
    for s in samples:
        print("rendered", render_card(**s))
