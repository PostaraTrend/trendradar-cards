# TRNG Lane Specification — Health & Wellness

**Status:** Prepared, awaiting activation decision
**Prepared:** 1 July 2026
**Lane kicker:** HEALTH & WELLNESS · NIGERIA
**Accent colour:** Medical green `#2ECC8F` (distinct from Naija Tech cyan `#1AC8D6` and brand sweep green `#3DF0B0`)
**Footer tag:** "Health, curated." + standing disclaimer line (see §4)

---

## 1. Lane mission

Bring verified Nigerian public-health and wellness information to the timeline using the existing TRNG promise: summarise the story and name the source. Counter the herbal-cure and miracle-remedy content that dominates the space by being the credible alternative.

## 2. Source whitelist (closed list — additions require explicit approval)

**Tier 1 — Institutional (alerts, outbreaks, recalls, policy):**
- NCDC — Nigeria Centre for Disease Control (ncdc.gov.ng, @NCDCgov)
- NAFDAC — recalls and public alerts (nafdac.gov.ng)
- Federal Ministry of Health and Social Welfare
- WHO Africa Regional Office (afro.who.int)
- NPHCDA — National Primary Health Care Development Agency (immunisation campaigns)

**Tier 2 — Editorial health desks (reporting and context):**
- Premium Times Health Desk
- TheCable Lifestyle/Health vertical
- Nigeria Health Watch (nigeriahealthwatch.com)

**Tier 3 — Wellness guidance (nutrition, exercise, maternal and mental health):**
- WHO guidance pages only
- NCDC prevention and public-advice content
- Teaching hospital public-education content (LUTH, UCH Ibadan) — case-by-case

**Permanently excluded:** wellness blogs, herbal or traditional remedy pages, supplement marketers, aggregators, unverified WhatsApp-sourced claims, any source that sells the product it writes about.

## 3. Content boundaries

**The lane DOES publish:**
- Outbreak updates and case counts (NCDC framing only)
- NAFDAC recalls and product alerts
- Health policy, budget, and programme news
- Immunisation and screening campaign announcements
- Prevention guidance from Tier 1/3 sources (handwashing, malaria nets, maternal checkups)
- Mental health awareness dates and verified helpline information

**The lane NEVER publishes:**
- Treatment advice, dosage information, or drug comparisons
- "Cures," remedies, or supplement claims of any kind
- Individual case stories involving identifiable patients
- Preliminary or single-study findings framed as settled ("Study says X cures Y")
- Anything the source itself has not stated — no extrapolation

## 4. Summarisation rules (lane-specific prompt additions)

1. Numbers, case counts, and medical terms are reproduced exactly as the source states them — never rounded, never paraphrased.
2. Institutional framing is preserved: "NCDC reports…" not "Nigeria is facing…"
3. No urgency amplification. If the source says "monitoring," the card says "monitoring," not "outbreak fears."
4. Every card carries the source chip (existing pattern) AND the standing footer disclaimer: **"Health information, curated. Always consult a professional."**
5. D4 sentiment/safety gate ON from day one: any item the summariser flags as ambiguous, alarming, or advice-like is suppressed to the review queue, never auto-posted.

## 5. Rollout plan

- **Phase A (weeks 1–3):** Manual soak. RSS feeds monitored in n8n but publish node disabled; every card hand-approved before posting. Target 3–4 posts/week.
- **Phase B:** Tier 1 sources move to auto-publish with D4 gate active. Tier 2/3 remain hand-approved.
- **Phase C:** Full lane automation, same as other lanes, with weekly spot-audit of published cards.

## 6. n8n / Sheets integration notes

- New Page Config row: lane = HEALTH, accent = #2ECC8F, footer_fb = fb.com/TrendRadarNG, footer_ig = @trendradarng
- New Post Log lane value: HEALTH
- RSS feeds to verify at build time: NCDC news feed, NAFDAC alerts feed, Premium Times health category RSS, Nigeria Health Watch feed. (Some institutional sites lack RSS — may require the Apify scraping pattern from SOP-001B.)

## 7. Launch content ideas (first week)

1. Lane introduction card — "A new lane on the radar: Health & Wellness. Verified sources only."
2. Current NCDC surveillance summary (whatever is active at launch)
3. One prevention/wellness card (seasonal: malaria prevention if launching in rainy season)
4. NAFDAC alert if any current recall is active
5. Mental health awareness card with verified helpline
