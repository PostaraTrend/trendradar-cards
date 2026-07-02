# Health & Wellness Lane — 10-Minute Setup

## Files in this package
1. `health_lane_n8n_workflow.json` — importable workflow (SOAK mode: publish node disabled)
2. `health_lane_config.json` — Page Config row values + renderer payload spec
3. `health_lane_selector_prompt.txt` — lane-tuned Claude selector prompt (safety rules baked in)
4. `TRNG-Health-Wellness-Lane-Spec.md` — full spec (already delivered)

## Setup steps
1. **n8n → Workflows → Import from File** → select the workflow JSON.
2. Open the **Lane Prompt** node → paste the full contents of `health_lane_selector_prompt.txt` into the template string.
3. Attach credentials on 3 nodes: both Google Sheets nodes (TRNG Google Sheets) and the Claude node (Anthropic header auth, key from admin@postaratrend.ca account).
4. Replace 3 placeholders: `REPLACE_WITH_TRNG_SHEET_ID` (2 nodes), `REPLACE_WITH_PAGE_ID` and page token on the FB Publish node.
5. **Google Sheets → Page Config** → add a row using the values in `health_lane_config.json → page_config_row`.
6. **Run once manually.** Check: feeds return items (any 404 feed → delete that RSS node or fix URL), selector returns valid JSON, a REVIEW row lands in Post Log.
7. **Flask renderer:** confirm `/render` accepts the payload in `renderer_payload_template` (accent `#2ECC8F`). If the renderer does not yet take an accent parameter, hardcode the HEALTH lane color server-side — one dict entry.

## SOAK → LIVE
- SOAK (now): pipeline runs twice daily (7am/3pm WAT), cards land in Post Log with status REVIEW. You post the good ones manually. Target 2–3 weeks per the lane spec.
- LIVE: enable the "FB Publish" node, set Page Config publish_mode to LIVE. Tier 2 feeds stay under review per spec Phase B if you want the graduated path.

## Known open items
- NCDC has no public RSS — add via the Apify scraper pattern (SOP-001B) later; the lane works without it for soak.
- All feed URLs follow standard WordPress patterns but are marked verify — step 6 confirms them.
- IG publish is intentionally absent — that arrives with the Phase-12 build after Meta verification/app review.
