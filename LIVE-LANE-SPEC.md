# Build Spec - TRNG Live In-Play Lane (World Cup + EPL)

**Owner:** Celestine Oamen
**Page:** Trend Radar NG (Page ID 1250624194793094)
**Leagues:** World Cup (1) + EPL (39), fetched together as `live=1-39`
**Runs on:** Render background worker (NOT n8n) - see rationale below
**Status:** Reference worker written and unit-tested (goal dedup verified). Not yet deployed.

---

## Why this does not run on n8n

The n8n Cloud Starter plan allows 2,500 executions per month and halts every
workflow the moment the cap is reached, with no grace period. A polling lane is
the worst fit for that model: a once-per-minute poll is roughly 43,000 runs per
month, and even a windowed five-minute poll during the tournament would exceed
the entire monthly cap on its own. Because hitting the cap pauses ALL lanes
(Naija Tech, results digest, wisdom, reflection), running the live poller on n8n
would put the whole account at risk.

The polling loop therefore lives on Render, where the card renderer already runs.
A Render background worker is a long-running process, so it is not metered per
execution and can poll continuously without touching the n8n quota.

## Relationship to the results digest lane

The existing results lane posts a full-time digest at 08:00 and 23:00 Lagos.
Full-time therefore overlaps. The worker exposes `POST_FT_CARDS`:
- `true`  -> the worker posts a per-match full-time card the moment a match ends.
- `false` -> the worker posts goals only, and the twice-daily digest owns
             full-time (no duplication).
Decide once. If in doubt, start with `false` and let the digest handle full-time.

---

## Architecture

    Render background worker (always on)
      loop:
        GET api-sports  fixtures?live=1-39      (one call covers both leagues)
        for each live fixture:
            for each Goal event not already posted:
                POST facebook  /{page}/feed      (fast text alert)
                mark goal signature as posted
        for each fixture that was live last cycle but is gone now (finished):
            if POST_FT_CARDS: render FT card via /results, POST /{page}/photos
        persist state, then sleep
      adaptive sleep: 60s while any match is live, 300s while nothing is on

Text goal alerts go to the `/feed` endpoint (plain message, no image). The
full-time card reuses the existing `/results` renderer and goes to `/photos`.

## Data source (API-SPORTS)

- Base `https://v3.football.api-sports.io`, header `x-apisports-key`.
- `fixtures?live=1-39` returns every in-play fixture in both leagues with the
  `events` array embedded, refreshed every 15 seconds. One call per cycle.
- Goal events: `type == "Goal"`; `detail` is one of `Normal Goal`, `Penalty`,
  `Own Goal`. The live scoreline is `fixture.goals.home / away` and is always
  correct - the worker uses that for the scoreline and only names a scorer for
  normal and penalty goals, never for own goals.
- Full-time: `fixture.status.short` in `FT`, `AET`, `PEN`. Finished matches drop
  out of `live=`, so the worker detects completion by noticing a fixture that
  was live last cycle and is gone this cycle, then fetches its final via
  `fixtures?id=`.
- Quota: one call per 60s while live is about 1,440 calls per day worst case,
  which is well inside any paid plan. Idle cycles slow to 300s to be a good
  citizen. Handle HTTP 429 by backing off (already built in).

## State / dedup schema

Persisted as JSON at `STATE_PATH` (default `/data/live_state.json`, which needs a
small Render persistent disk so it survives restarts):

    {
      "posted_goals": ["<fixtureId>|<elapsed>|<extra>|<teamId>|<playerId>|<detail>", ...],
      "ft_posted":    [<fixtureId>, ...],
      "seen_live":    [<fixtureId>, ...]
    }

The goal signature is stable across polls, so a goal is posted exactly once even
if the same event keeps reappearing in the live feed (verified by unit test).
Lists are trimmed (last 800 goals / 300 fixtures) so the file cannot grow without
bound. Without a disk the worker still works in memory, but a restart mid-match
could repost recent goals - the disk is the safe option.

## Environment variables (set on the Render service, never hard-code)

    APISPORTS_KEY   the API-SPORTS key (same one the results lane uses)
    FB_PAGE_TOKEN   the Trend Radar NG Facebook Page access token
    FB_PAGE_ID      1250624194793094  (default)
    LIVE_LEAGUES    1-39              (default: World Cup + EPL)
    RENDERER_URL    https://trendradar-cards.onrender.com/results  (default)
    STATE_PATH      /data/live_state.json  (default; needs a Render disk)
    POST_FT_CARDS   true | false      (see digest overlap above)

## Anti-spam / rate limits

- `MIN_POST_GAP` (8s) enforces a minimum gap between Facebook posts. World Cup is
  low-volume, but a Saturday of ten simultaneous EPL 15:00 kickoffs can produce a
  burst of goals; the gap plus one-goal-per-signature keeps the page from
  flooding. Raise the gap if the EPL season still feels too bursty in August.
- Facebook may occasionally throw the transient -3 error on a post. The worker
  logs the failure and simply retries that goal on the next cycle (the signature
  is only marked posted on a 200), so nothing is lost and nothing double-posts.

## Deployment on Render

1. Put `live_worker.py` and a `requirements.txt` containing `requests` in a repo
   (a new folder in `trendradar-cards`, or a small new repo).
2. Create a new Render service of type **Background Worker** (not Web Service).
   Start command: `python live_worker.py`.
3. Add the environment variables above.
4. Add a small **persistent disk** mounted at `/data` (a few hundred MB is plenty)
   so `live_state.json` survives restarts and deploys.
5. Deploy. The worker logs each poll and each post to the Render log stream.

## Testing plan

1. Deploy with `POST_FT_CARDS=false` first so you validate goal alerts alone.
2. During a live World Cup match, watch the Render logs: you should see a poll
   line every 60s and a `POSTED goal` line shortly after each real goal, matching
   the actual match. Confirm the goal appears on the page once, not repeatedly.
3. Let a match finish and confirm no duplicate FT (digest still owns it).
4. Only after goals are proven, flip `POST_FT_CARDS=true` if you want per-match
   FT cards, and re-verify there is no duplication you dislike against the digest.

## Known edge cases

- Own goals: reported under the conceding team by API-SPORTS. The worker avoids
  crediting a scorer on own goals to prevent mis-attribution; it shows only the
  scoreline plus "(own goal)".
- VAR-disallowed goals: rare, but a goal can be added then removed. Low risk for
  v1; if it ever posts a phantom goal, that is the cause. A later enhancement can
  reconcile against the scoreline before posting.
- Restart mid-match without a disk: possible re-post of very recent goals. The
  persistent disk removes this.
- Token / key rotation: update the Render environment variables when you rotate,
  the same way you update the n8n credentials.

## Future enhancements (not in v1)

- Kickoff, half-time, and red-card posts for more texture.
- La Liga (140) and Serie A (135) by extending `LIVE_LEAGUES` once those seasons
  resume in August (they simply return nothing until then).
- Goal cards (rendered) instead of text, if you want the live feed on-brand.
- Reconcile posted goals against the final scoreline to self-heal VAR reversals.
