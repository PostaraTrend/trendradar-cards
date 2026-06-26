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

# per-lane accent for the small category tag (brand stays green overall)
LANE_ACCENT = {
    "POLITICS":      (24, 224, 160),   # radar green
    "ENTERTAINMENT": (245, 196, 81),   # amber
    "EPL":           (110, 168, 255),  # sky
    "FOOTBALL":      (110, 168, 255),
    "ECONOMY":       (48, 200, 184),   # teal
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

# ---- background -----------------------------------------------------------
def background():
    """Navy vertical gradient + radial radar-green glow top-right (matches the SOP page)."""
    top = np.array(NAVY, dtype=float)
    bot = np.array(NAVY2, dtype=float)
    yy = np.linspace(0, 1, H2)[:, None, None]
    grad = top[None, None, :] * (1 - yy) + bot[None, None, :] * yy  # H,1,3
    grad = np.repeat(grad, W2, axis=1)

    # radial glow
    cx, cy = int(W2 * 0.82), int(H2 * -0.05)
    yg, xg = np.mgrid[0:H2, 0:W2]
    d = np.sqrt((xg - cx) ** 2 + (yg - cy) ** 2)
    r = W2 * 0.95
    glow = np.clip(1 - d / r, 0, 1) ** 2.2
    g = np.array((24, 224, 160), dtype=float)
    grad += glow[..., None] * g[None, None, :] * 0.14

    arr = np.clip(grad, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")

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
    """Pick the largest Poppins-Bold size whose wrapped block fits the box."""
    size = start
    while size >= min_size:
        fnt = font(F_BOLD, size)
        lines = wrap_to_width(draw, text, fnt, max_w)
        lh = (fnt.getbbox("Ag")[3] - fnt.getbbox("Ag")[1]) * 1.16
        if len(lines) * lh <= max_h and len(lines) <= 6:
            return fnt, lines, lh
        size -= 3
    fnt = font(F_BOLD, min_size)
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

    img = background()
    img = radar_overlay(img)
    d = ImageDraw.Draw(img)

    # --- top: brand pill ---
    f_kick = font(F_BOLD, 21)
    label = "TREND RADAR NG"
    tw = tracked_width(d, label, f_kick, 3)
    pill_h = 58 * SCALE
    pill_w = tw + 96 * SCALE
    py = PAD
    rounded(d, [PAD, py, PAD + pill_w, py + pill_h], 30, fill=GREEN)
    # radar mark (small navy dial inside the green pill)
    mcx = PAD + 38 * SCALE
    mcy = py + pill_h // 2
    mr = 15 * SCALE
    d.ellipse([mcx - mr, mcy - mr, mcx + mr, mcy + mr], outline=NAVY, width=3)
    d.ellipse([mcx - mr*0.55, mcy - mr*0.55, mcx + mr*0.55, mcy + mr*0.55], outline=NAVY, width=3)
    import math as _mm
    _a = _mm.radians(-40)
    d.line([mcx, mcy, mcx + mr*_mm.cos(_a), mcy + mr*_mm.sin(_a)], fill=NAVY, width=3)
    d.ellipse([mcx + mr*0.5 - 3*SCALE, mcy - mr*0.45 - 3*SCALE,
               mcx + mr*0.5 + 3*SCALE, mcy - mr*0.45 + 3*SCALE], fill=NAVY)
    ty = py + (pill_h - (f_kick.getbbox("A")[3] - f_kick.getbbox("A")[1])) // 2 - 6 * SCALE
    tracked(d, (PAD + 62 * SCALE, ty), label, f_kick, NAVY, 3)

    # date (right)
    if date_str:
        f_date = font(F_MED, 20)
        dw = d.textlength(date_str, font=f_date)
        d.text((W2 - PAD - dw, py + 14 * SCALE), date_str, font=f_date, fill=MUTE)

    # --- category line ---
    f_cat = font(F_SEMI, 22)
    cat_label = f"{category} \u00b7 NIGERIA"
    cat_y = py + pill_h + 34 * SCALE
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
    f_src = font(F_MED, 26)
    src_text = f"According to {source}"
    chip_pad = 30 * SCALE
    chip_h = 74 * SCALE
    chip_w = d.textlength(src_text, font=f_src) + chip_pad * 2 + 26 * SCALE
    chip_y = H2 - PAD - 150 * SCALE
    rounded(d, [PAD, chip_y, PAD + chip_w, chip_y + chip_h], 14,
            fill=PANEL, outline=LINE, width=2 * SCALE)
    # green accent bar
    d.rectangle([PAD, chip_y + 14 * SCALE, PAD + 6 * SCALE, chip_y + chip_h - 14 * SCALE],
                fill=accent)
    src_ty = chip_y + (chip_h - (f_src.getbbox("Ag")[3] - f_src.getbbox("Ag")[1])) // 2 - 4 * SCALE
    d.text((PAD + chip_pad + 14 * SCALE, src_ty), src_text, font=f_src, fill=INK)

    # --- footer ---
    foot_y = H2 - PAD - 38 * SCALE
    d.line([PAD, foot_y - 26 * SCALE, W2 - PAD, foot_y - 26 * SCALE], fill=LINE, width=2 * SCALE)
    f_hand = font(F_SEMI, 22)
    d.text((PAD, foot_y), handle, font=f_hand, fill=GREEN)
    f_tag = font(F_REG, 19)
    tag = "Nigeria, curated."
    tagw = d.textlength(tag, font=f_tag)
    d.text((W2 - PAD - tagw, foot_y + 2 * SCALE), tag, font=f_tag, fill=MUTE)

    out = img.resize((W, H), Image.LANCZOS)
    return out


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
    ]
    for s in samples:
        print("rendered", render_card(**s))
