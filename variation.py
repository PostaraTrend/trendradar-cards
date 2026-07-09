"""
TRNG Cost of Living — Daily Variation Module
=============================================
Drop-in module for the trendradar-cards Flask renderer (COL blueprint).

Purpose: ensure no two COL cards ever hash close together under Facebook
perceptual-hash fingerprinting, while keeping the Trend Radar NG brand
identity (masthead, fonts, green family) fully stable.

Design principles:
  * Deterministic per calendar day (Africa/Lagos). Re-rendering the same
    card twice on the same day produces an identical image — safe for
    n8n retries and manual re-runs.
  * Different every day: accent scheme, tagline, badge text, row order,
    and a micro-offset all rotate on independent cycles, so the combined
    layout fingerprint has a repeat cycle of several months.
  * Brand-safe: masthead text, fonts, and the core TRNG green identity
    never change. Variation is confined to accents and arrangement.

Integration (see INTEGRATION.md):
    from variation import get_daily_variation
    v = get_daily_variation()          # today, Africa/Lagos
    v = get_daily_variation(date(2026, 7, 10))   # explicit date
"""

import random
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

LAGOS = ZoneInfo("Africa/Lagos")


# ---------------------------------------------------------------------------
# Accent schemes — all within the TRNG green family.
# core_green is the anchor and should remain the dominant surface colour.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AccentScheme:
    name: str
    header_band: str      # masthead band background
    badge_fill: str       # "DAILY PRICES" pill background
    badge_text: str       # pill text colour
    rule_line: str        # gold/accent rule under masthead
    fx_strip_bg: str      # fuel & FX strip background
    fx_tile_border: str   # border on FX tiles
    row_stripe: str       # alternating row background
    price_color: str      # price text colour


ACCENT_SCHEMES = [
    AccentScheme(
        name="classic_gold",
        header_band="#0B3D2E",
        badge_fill="#F2C94C",
        badge_text="#0B3D2E",
        rule_line="#F2C94C",
        fx_strip_bg="#0B3D2E",
        fx_tile_border="#F2C94C",
        row_stripe="#F2F7F4",
        price_color="#0B3D2E",
    ),
    AccentScheme(
        name="deep_emerald",
        header_band="#0E4D3A",
        badge_fill="#E8C547",
        badge_text="#123524",
        rule_line="#DFAF2B",
        fx_strip_bg="#123524",
        fx_tile_border="#DFAF2B",
        row_stripe="#EEF5F0",
        price_color="#123524",
    ),
    AccentScheme(
        name="forest_cream",
        header_band="#14532D",
        badge_fill="#FBF3D5",
        badge_text="#14532D",
        rule_line="#C9A227",
        fx_strip_bg="#0F3D22",
        fx_tile_border="#FBF3D5",
        row_stripe="#F6F3E8",
        price_color="#14532D",
    ),
    AccentScheme(
        name="pine_amber",
        header_band="#0A2E23",
        badge_fill="#F5A623",
        badge_text="#0A2E23",
        rule_line="#F5A623",
        fx_strip_bg="#0D3A2C",
        fx_tile_border="#F5A623",
        row_stripe="#F1F6F2",
        price_color="#0A2E23",
    ),
    AccentScheme(
        name="moss_sand",
        header_band="#1B4332",
        badge_fill="#E9DCC0",
        badge_text="#1B4332",
        rule_line="#B08D2E",
        fx_strip_bg="#153726",
        fx_tile_border="#E9DCC0",
        row_stripe="#F4F1EA",
        price_color="#1B4332",
    ),
]


# ---------------------------------------------------------------------------
# Rotating copy elements. All strings publish-ready: no contractions.
# ---------------------------------------------------------------------------

TAGLINES = [
    "what the market is charging today",
    "prices as the market dey call am today",
    "today across Nigerian markets",
    "checked and compiled for today",
    "what your money can buy today",
    "market rates for today, verified",
    "straight from the market, no hype",
]

BADGE_TEXTS = [
    "DAILY PRICES",
    "TODAY'S PRICES",
    "MARKET CHECK",
    "PRICE WATCH",
]

FOOTER_LINES = [
    "Sources: CBN official window \u2022 published market reports \u2022 for information only",
    "CBN official window and published market reports \u2022 information only",
    "Compiled from CBN official rates and published market reports",
    "Data: CBN official window \u2022 market reports \u2022 informational use only",
]

SECTION_TITLES = [
    "FOOD & KITCHEN",
    "FOOD & KITCHEN MARKET CHECK",
    "KITCHEN MARKET CHECK",
    "FOOD MARKET CHECK",
]


# ---------------------------------------------------------------------------
# Variation engine
# ---------------------------------------------------------------------------

@dataclass
class DailyVariation:
    day: date
    scheme: AccentScheme
    tagline: str
    badge_text: str
    footer_line: str
    section_title: str
    row_order: list = field(default_factory=list)   # permutation indices
    x_jitter: int = 0    # px, apply to a decorative element only
    y_jitter: int = 0    # px, apply to a decorative element only

    def shuffle_rows(self, items: list) -> list:
        """Return food/kitchen rows in this day's order.

        Pass the list of row dicts/tuples exactly as loaded from the
        sheet; ordering is deterministic for the day.
        """
        rng = random.Random(f"{self.day.isoformat()}-rows")
        order = list(range(len(items)))
        rng.shuffle(order)
        # Persist the permutation for logging/debug
        self.row_order = order
        return [items[i] for i in order]


def get_daily_variation(day: date | None = None) -> DailyVariation:
    """Return the deterministic variation bundle for a given Lagos day."""
    if day is None:
        day = datetime.now(LAGOS).date()

    # Independent cycles → combined repeat period is the LCM of the
    # component cycles (5 schemes × 7 taglines × 4 badges × 4 footers
    # × 4 section titles), far beyond any practical fingerprint window.
    ordinal = day.toordinal()
    scheme = ACCENT_SCHEMES[ordinal % len(ACCENT_SCHEMES)]
    tagline = TAGLINES[ordinal % len(TAGLINES)]
    badge = BADGE_TEXTS[ordinal % len(BADGE_TEXTS)]
    footer = FOOTER_LINES[(ordinal // 2) % len(FOOTER_LINES)]
    section = SECTION_TITLES[(ordinal // 3) % len(SECTION_TITLES)]

    # Micro-jitter for one decorative element (e.g. the badge pill or a
    # corner ornament). Never apply to text blocks or data rows.
    rng = random.Random(f"{day.isoformat()}-jitter")
    x_j = rng.randint(-6, 6)
    y_j = rng.randint(-4, 4)

    return DailyVariation(
        day=day,
        scheme=scheme,
        tagline=tagline,
        badge_text=badge,
        footer_line=footer,
        section_title=section,
        x_jitter=x_j,
        y_jitter=y_j,
    )


if __name__ == "__main__":
    # Quick preview of the next 14 days of variation
    from datetime import timedelta
    start = datetime.now(LAGOS).date()
    for i in range(14):
        d = start + timedelta(days=i)
        v = get_daily_variation(d)
        print(
            f"{d}  scheme={v.scheme.name:<13} badge={v.badge_text:<15}"
            f" tagline={v.tagline[:38]:<40} jitter=({v.x_jitter},{v.y_jitter})"
        )
