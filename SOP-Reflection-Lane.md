# SOP — Trend Radar NG — Reflection Lane (v1.0)

**Lane:** Reflection (weekly)
**Page:** Trend Radar NG — Page ID `1250624194793094`
**Cadence:** One post per week — Sunday 08:00 `Africa/Lagos`
**Format:** Photo post (1080×1350, 4:5). Never a reel.
**Model:** `claude-sonnet-4-6`
**Status:** Build — voice approved, pending credential mapping and a soak.

---

## 1. Purpose and difference from the news lanes

The five news lanes (Politics, Economy, Entertainment, Football, Gospel) pull from RSS and publish headline cards. The Reflection lane does **not** pull RSS and does **not** select an article. It is a generative lane with a weekly trigger that:

1. Reads the last seven days of the **Post Log** (across all lanes) as its soil.
2. Distils a single unifying thread for the week.
3. Composes one dignified reflection (long caption) and one pull-quote card.
4. Publishes once, on Sunday morning.

The objective is to draw people together and speak to conscience — to those who govern, those who are governed, and the young who will inherit the nation. It names no one, blames no one, takes no side, and makes no defensive statement. Africa-scope reflections are reserved for the occasional week that genuinely earns a continental angle.

## 2. Editorial guardrails (the core of the lane)

The whole bet of this lane is the voice. The guardrails live in the system prompt (`reflection-system-prompt.md`, v1.0). The non-negotiables:

- No named or implied person, government, party, ethnic group, religion, region, or institution as being at fault.
- No accusation, blame, partisanship, slogan, or rebuttal.
- Every challenge framed as shared and collective.
- All contractions expanded (do not, cannot, we are).
- Civic and humanist register — devotional language stays in the Gospel lane.
- Opening posture and ending type rotate week to week (de-duplicated against recent runs via `last_themes`).
- Africa only when the week earns it; never rank or compare nations.
- `reflection_body` 250–350 words; `pull_quote` ≤18 words; `theme_title` 2–5 words.

## 3. Workflow nodes (`trng-reflection-lane.json`)

| # | Node | Type | Role |
|---|------|------|------|
| 1 | Schedule — Weekly Sunday 08:00 | Schedule Trigger | Cron `0 8 * * 0`, timezone Africa/Lagos |
| 2 | Read News Post Log | Google Sheets (read) | The weekly soil — `Topic` column, news Post Log |
| 3 | Read Reflection Log | Google Sheets (read) | This lane's own history, for de-duplication |
| 4 | Build Prompt Inputs | Code | `week_headlines` from the news log (7 days); `last_themes` + ending type + scope from the Reflection Log |
| 5 | Claude — Reflection | HTTP Request | Anthropic Messages API, system prompt v1.0 |
| 6 | Parse Reflection | Code | Parses JSON; carries `scope`; derives `ending_type`, `week_of`, `word_count`, guardrail `flags` |
| 7 | Render Card | HTTP Request | POST to `/reflection`, returns `image_url` |
| 8 | Facebook — Publish Photo | HTTP Request | Graph `/{page-id}/photos`, caption = `reflection_body` |
| 9 | Log Success | Google Sheets (append) | Writes the full 12-column row to the Reflection Log |

The reads are chained (Schedule → News → Reflection → Build) so both sheets are loaded before the prompt is assembled.

## 4. Two-sheet architecture

This lane uses **two** sheets, deliberately separated:

- **News Post Log** (`1prMrvr…6PQs`, tab `Post Log`) — read only. Supplies the weekly soil from its `Topic` column (last 7 days). The reflection reflects on what the country actually lived through.
- **Reflection Log** (`1eXuQ3D…451Q`, tab `Reflection Log`) — this lane's dedicated home. Read for de-duplication and written to on publish. Twelve columns:

`timestamp | week_of | theme_title | pull_quote | reflection_body | scope | ending_type | word_count | flags | image_url | facebook_url | status`

- `reflection_body` is also the Facebook caption.
- `scope` (`nigeria` / `africa`) lets you monitor the "Africa occasional" rule at a glance over time.
- `ending_type` and recent `theme_title`s feed next week's de-duplication so the lane never develops a tic.
- `week_of` is the weekly key — the lane should not post twice in one `week_of`.
- `flags` records non-blocking guardrail warnings (possible contraction, pull-quote over 18 words, length out of range).

## 5. Card renderer (`/reflection`)

New endpoint on `trendradar-cards.onrender.com`, parallel to `/wisdom`. Template `reflection_card.html`: 1080×1350, deep ink-to-forest calm palette deliberately distinct from the news branding, muted-gold "REFLECTION" eyebrow, `theme_title` heading, `pull_quote` as centred hero, gold horizon line, "Trend Radar NG" wordmark and date in the footer. Noto Sans (already loaded for diacritics). Full-bleed, no watermark. The route saves the PNG and returns a public `image_url` for the Facebook node to fetch.

## 6. Activation checklist

1. Import `trng-reflection-lane.json` into n8n.
2. Map credentials: `REPLACE_GS_CRED_ID` (Google Sheets — must have access to BOTH sheets), `REPLACE_ANTHROPIC_CRED_ID` (Anthropic `x-api-key`), `REPLACE_FB_TOKEN_CRED_ID` (TRNG never-expiring Page token).
3. Confirm the news Post Log still uses `Topic` for headline text and `Date` for the timestamp; adjust the keys in **Build Prompt Inputs** if those headers differ.
4. Add the `/reflection` route to the renderer service and redeploy; confirm `GET /cards/<file>.png` serves publicly.
5. **Pin a test run:** execute the workflow manually once, read the output, confirm the voice and that the `flags` column came back empty, and eyeball the card before going live.
6. Set the workflow active. Observe a 14-day soak (two posts) before treating the lane as stable.

## 7. Review discipline

Because this lane speaks in the nation's voice under the TRNG brand, every post is read before it is trusted to run unattended during the soak. After the soak, spot-check monthly for: any drift toward naming or blame, any contraction slipping through, repetition of opening posture or ending type, and any manufactured African angle. The `flags` column is the first place to look.
