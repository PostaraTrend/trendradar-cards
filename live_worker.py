#!/usr/bin/env python3
"""
Trend Radar NG - Live in-play worker (World Cup + EPL)
======================================================
Runs as an always-on Render background worker, OUTSIDE n8n, so it does not
consume any n8n Cloud executions. It polls API-SPORTS for in-play fixtures,
detects new goals, and posts them to the Trend Radar NG Facebook page in near
real time. Full-time cards are optional (see POST_FT_CARDS) because the twice
daily results digest lane already covers full-time.

Design goals:
  - One API call per cycle covers every live match in both leagues (live=1-39).
  - Deterministic dedup so a goal is posted exactly once, even across restarts.
  - Adaptive polling: fast while matches are live, slow while nothing is on, so
    the API-SPORTS quota and the Facebook rate limits are both respected.
  - Fail-soft: any single error is logged and the loop continues.

Environment variables (set these in the Render service, never hard-code):
  APISPORTS_KEY   - the API-SPORTS key (the same one the results lane uses)
  FB_PAGE_TOKEN   - the Trend Radar NG Facebook Page access token
  FB_PAGE_ID      - defaults to 1250624194793094
  LIVE_LEAGUES    - defaults to "1-39" (World Cup + EPL)
  RENDERER_URL    - defaults to the /results endpoint on Render
  STATE_PATH      - defaults to /data/live_state.json (needs a Render disk)
  POST_FT_CARDS   - "true" or "false"; default "true"
"""

import os
import sys
import json
import time
from datetime import datetime, timezone

import requests

# ---- configuration --------------------------------------------------------
API_KEY       = os.environ.get("APISPORTS_KEY", "")
FB_PAGE_ID    = os.environ.get("FB_PAGE_ID", "1250624194793094")
FB_TOKEN      = os.environ.get("FB_PAGE_TOKEN", "")
LEAGUES       = os.environ.get("LIVE_LEAGUES", "1-39")   # World Cup (1) + EPL (39)
RENDERER_URL  = os.environ.get("RENDERER_URL", "https://trendradar-cards.onrender.com/results")
STATE_PATH    = os.environ.get("STATE_PATH", "/data/live_state.json")
POST_FT_CARDS = os.environ.get("POST_FT_CARDS", "true").lower() == "true"

GRAPH          = "https://graph.facebook.com/v23.0"
APISPORTS_BASE = "https://v3.football.api-sports.io"

POLL_LIVE    = 60     # seconds between polls while at least one match is live
POLL_IDLE    = 300    # seconds between polls while nothing is live
MIN_POST_GAP = 8      # minimum seconds between two Facebook posts (anti-spam)
BACKOFF_429  = 90     # seconds to wait after an API-SPORTS rate-limit response


def log(*a):
    print(datetime.now(timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


# ---- durable state --------------------------------------------------------
def load_state():
    try:
        with open(STATE_PATH) as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("posted_goals", [])   # list of goal signatures already posted
    s.setdefault("ft_posted", [])      # list of fixture ids whose FT card posted
    s.setdefault("seen_live", [])      # fixture ids that were live last cycle
    return s


def save_state(s):
    try:
        d = os.path.dirname(STATE_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(s, f)
    except Exception as e:
        log("WARN could not persist state:", e)


# ---- API-SPORTS -----------------------------------------------------------
def fetch_live():
    """Return the list of in-play fixtures (events embedded), or None on error."""
    try:
        r = requests.get(f"{APISPORTS_BASE}/fixtures",
                         params={"live": LEAGUES},
                         headers={"x-apisports-key": API_KEY}, timeout=15)
        if r.status_code == 429:
            log("WARN API-SPORTS rate limited (429); backing off")
            time.sleep(BACKOFF_429)
            return None
        r.raise_for_status()
        return r.json().get("response", [])
    except Exception as e:
        log("WARN fetch_live failed:", e)
        return None


def fetch_fixture(fid):
    try:
        r = requests.get(f"{APISPORTS_BASE}/fixtures",
                         params={"id": fid},
                         headers={"x-apisports-key": API_KEY}, timeout=15)
        r.raise_for_status()
        resp = r.json().get("response", [])
        return resp[0] if resp else None
    except Exception as e:
        log("WARN fetch_fixture failed:", fid, e)
        return None


# ---- Facebook posting -----------------------------------------------------
_last_post = [0.0]


def _throttle():
    gap = time.time() - _last_post[0]
    if gap < MIN_POST_GAP:
        time.sleep(MIN_POST_GAP - gap)
    _last_post[0] = time.time()


def post_text(message):
    _throttle()
    try:
        r = requests.post(f"{GRAPH}/{FB_PAGE_ID}/feed",
                          data={"message": message, "access_token": FB_TOKEN},
                          timeout=20)
        ok = (r.status_code == 200)
        log("POSTED goal" if ok else f"FAIL goal {r.status_code} {r.text[:120]}")
        return ok
    except Exception as e:
        log("WARN post_text failed:", e)
        return False


def post_photo(png_bytes, caption):
    _throttle()
    try:
        r = requests.post(f"{GRAPH}/{FB_PAGE_ID}/photos",
                          data={"caption": caption, "published": "true",
                                "access_token": FB_TOKEN},
                          files={"source": ("card.png", png_bytes, "image/png")},
                          timeout=40)
        ok = (r.status_code == 200)
        log("POSTED FT card" if ok else f"FAIL FT {r.status_code} {r.text[:120]}")
        return ok
    except Exception as e:
        log("WARN post_photo failed:", e)
        return False


def render_ft_card(fx):
    """Reuse the existing /results renderer to build a one-match full-time card."""
    league = fx["league"]
    teams = fx["teams"]
    goals = fx["goals"]
    home = teams["home"]["name"]
    away = teams["away"]["name"]
    score = f"{goals.get('home')} - {goals.get('away')}"

    pen = ""
    sc = (fx.get("score") or {}).get("penalty") or {}
    if sc.get("home") is not None and sc.get("away") is not None:
        winner = home if sc["home"] > sc["away"] else away
        pen = f"{winner} won {max(sc['home'], sc['away'])}-{min(sc['home'], sc['away'])} on penalties"

    groups = [{
        "round": league.get("round", ""),
        "matches": [{
            "home": home, "away": away, "score": score, "pen": pen,
            "home_flag": teams["home"].get("logo"),
            "away_flag": teams["away"].get("logo"),
        }],
    }]
    body = {
        "title": f"{league['name']} Result",
        "date": datetime.now(timezone.utc).strftime("%d %b %Y").lstrip("0"),
        "groups": groups,
    }
    r = requests.post(RENDERER_URL, json=body, timeout=60)
    r.raise_for_status()
    return r.content


# ---- formatting -----------------------------------------------------------
def goal_signature(fid, ev):
    """A stable per-goal key so each goal is posted exactly once."""
    t = ev.get("time", {}) or {}
    team = ev.get("team") or {}
    player = ev.get("player") or {}
    return "|".join(str(x) for x in [
        fid, t.get("elapsed"), t.get("extra"),
        team.get("id"), player.get("id"), ev.get("detail"),
    ])


def goal_message(fx, ev):
    """
    Build the goal alert text. The scoreline is taken from fixture.goals (always
    correct), and the scorer is only named for normal or penalty goals. Own goals
    are labelled without attributing a scorer, because API-SPORTS reports the
    own-goal event under the conceding team, which is easy to mis-credit.
    """
    teams = fx["teams"]
    goals = fx["goals"]
    home = teams["home"]["name"]
    away = teams["away"]["name"]

    t = ev.get("time", {}) or {}
    minute = t.get("elapsed")
    if t.get("extra"):
        minute = f"{minute}+{t['extra']}"

    detail = ev.get("detail") or ""
    scorer = (ev.get("player") or {}).get("name") or ""

    line = f"\u26bd {minute}' GOAL\n{home} {goals.get('home')} - {goals.get('away')} {away}"
    if "Own" in detail:
        line += "\n(own goal)"
    elif scorer:
        tag = " (penalty)" if "Penalty" in detail else ""
        line += f"\n{scorer}{tag}"
    line += f"\n{fx['league']['name']} \u00b7 {fx['league'].get('round', '')}"
    return line


def ft_caption(fx):
    teams = fx["teams"]
    goals = fx["goals"]
    return (f"Full-time. {teams['home']['name']} {goals.get('home')} - "
            f"{goals.get('away')} {teams['away']['name']}. {fx['league']['name']}.")


# ---- main loop ------------------------------------------------------------
def process_cycle(live, posted, ft_posted, seen_prev):
    """
    Pure-ish cycle body, separated from the network loop so it can be unit
    tested. Returns the set of fixture ids seen live this cycle. Mutates the
    posted / ft_posted sets in place. Posting side effects go through the
    post_* helpers, which are no-ops in tests when patched out.
    """
    current_ids = set()
    for fx in live:
        fid = fx["fixture"]["id"]
        current_ids.add(fid)
        for ev in fx.get("events", []) or []:
            if ev.get("type") != "Goal":
                continue
            sig = goal_signature(fid, ev)
            if sig in posted:
                continue
            if post_text(goal_message(fx, ev)):
                posted.add(sig)

    if POST_FT_CARDS:
        gone = set(seen_prev) - current_ids
        for fid in gone:
            if fid in ft_posted:
                continue
            fx = fetch_fixture(fid)
            if not fx:
                continue
            short = fx["fixture"]["status"]["short"]
            if short in ("FT", "AET", "PEN"):
                try:
                    png = render_ft_card(fx)
                    if post_photo(png, ft_caption(fx)):
                        ft_posted.add(fid)
                except Exception as e:
                    log("WARN FT render/post failed:", fid, e)

    return current_ids


def main():
    if not API_KEY or not FB_TOKEN:
        log("FATAL missing APISPORTS_KEY or FB_PAGE_TOKEN env var")
        sys.exit(1)

    log("live worker starting; leagues", LEAGUES, "| FT cards:", POST_FT_CARDS)
    state = load_state()
    posted = set(state["posted_goals"])
    ft_posted = set(state["ft_posted"])
    seen_prev = list(state["seen_live"])

    while True:
        live = fetch_live()
        if live is None:
            time.sleep(POLL_IDLE)
            continue

        current_ids = process_cycle(live, posted, ft_posted, seen_prev)
        seen_prev = list(current_ids)

        # Keep the state files bounded so they do not grow without limit.
        state["posted_goals"] = list(posted)[-800:]
        state["ft_posted"] = list(ft_posted)[-300:]
        state["seen_live"] = seen_prev
        save_state(state)

        time.sleep(POLL_LIVE if current_ids else POLL_IDLE)


if __name__ == "__main__":
    main()
