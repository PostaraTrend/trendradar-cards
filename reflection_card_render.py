#!/usr/bin/env python3
"""
Trend Radar NG — Reflection-lane card renderer
==============================================
Standalone module so the main trend_radar_card.py does not need editing.
It reuses that module's brand helpers and only adds the reflection layout.
"""
from PIL import Image, ImageDraw

from trend_radar_card import (
    background, radar_overlay, tracked, tracked_width, wrap_to_width,
    rounded, font, font_for, _wisdom_fit, _wisdom_centered,
    F_SEMI, F_XBOLD, F_BOLD, F_MED, F_REG,
    INK, MUTE, GREEN, LINE, W, H, W2, H2, PAD, SCALE,
)

REFLECT = (150, 178, 224)
REFLECT_D = (96, 120, 168)


def build_reflection_card(theme_title, pull_quote, date_str="",
                          handle="fb.com/TrendRadarNG", **_ignored):
    accent = REFLECT
    img = background()
    img = radar_overlay(img)
    d = ImageDraw.Draw(img)
    cx = W2 // 2

    if date_str:
        f_date = font(F_MED, 20)
        dw = d.textlength(date_str, font=f_date)
        d.text((W2 - PAD - dw, PAD + 2 * SCALE), date_str, font=f_date, fill=MUTE)

    f_cat = font(F_SEMI, 22)
    cat_label = "REFLECTION"
    cat_w = tracked_width(d, cat_label, f_cat, 6)
    cat_y = PAD + 30 * SCALE
    tracked(d, (cx - cat_w / 2, cat_y), cat_label, f_cat, accent, 6)
    rule_y = cat_y + 52 * SCALE
    d.rectangle([cx - 35 * SCALE, rule_y, cx + 35 * SCALE, rule_y + 5 * SCALE], fill=accent)

    f_mark = font(F_XBOLD, 150)
    mark = "\u201C"
    mw = d.textlength(mark, font=f_mark)
    mark_y = rule_y + 30 * SCALE
    d.text((cx - mw / 2, mark_y), mark, font=f_mark, fill=REFLECT_D)

    region_top = mark_y + 130 * SCALE
    region_bot = H2 - PAD - 250 * SCALE
    max_w = W2 - 2 * PAD
    qf, qlines, qlh = _wisdom_fit(d, pull_quote, True, max_w, (region_bot - region_top) * 0.78,
                                  start=78, min_size=42, line_mult=1.26, max_lines=6)
    block_h = len(qlines) * qlh
    y = region_top + ((region_bot - region_top) - block_h) / 2
    y = _wisdom_centered(d, qlines, qf, qlh, y, INK, cx)

    if theme_title:
        rmid = y + 34 * SCALE
        d.rectangle([cx - 28 * SCALE, rmid, cx + 28 * SCALE, rmid + 4 * SCALE], fill=accent)
        tf = font_for(theme_title, F_MED, 30)
        tlines = wrap_to_width(d, theme_title, tf, max_w)
        tlh = (tf.getbbox("Ag")[3] - tf.getbbox("Ag")[1]) * 1.3
        _wisdom_centered(d, tlines, tf, tlh, rmid + 30 * SCALE, MUTE, cx)

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

    foot_y = H2 - PAD - 38 * SCALE
    d.line([PAD, foot_y - 26 * SCALE, W2 - PAD, foot_y - 26 * SCALE], fill=LINE, width=2 * SCALE)
    f_hand = font(F_SEMI, 22)
    d.text((PAD, foot_y), handle, font=f_hand, fill=GREEN)
    f_tag = font(F_REG, 19)
    tag = "Reflection, curated."
    tagw = d.textlength(tag, font=f_tag)
    d.text((W2 - PAD - tagw, foot_y + 2 * SCALE), tag, font=f_tag, fill=MUTE)

    return img.resize((W, H), Image.LANCZOS)
