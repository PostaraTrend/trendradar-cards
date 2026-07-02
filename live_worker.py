#!/usr/bin/env python3
"""
Trend Radar NG - Live in-play worker v3 (Match Thread mode)
===========================================================
Always-on Render background worker, OUTSIDE n8n (no execution metering). Polls
API-SPORTS for in-play fixtures and narrates every major match event.

NEW IN v3 - MATCH THREAD MODE (on by default):
  - At kick-off the worker publishes ONE anchor feed post per match
    ("MATCH THREAD ... Follow this post for live updates").
  - Every subsequent event (goals, cards, half-time, extra time, penalties,
    full-time) is published as a COMMENT on that anchor post, so the page feed
    is not flooded and engagement concentrates on a single post.
  - Selected big moments ALSO go to the feed (default: goals and full-time),
    controlled by FEED_EVENTS.
  - If the worker starts mid-match (no anchor yet), it creates the thread
    lazily on the first event it sees, so coverage is never silently dropped.
  - Set THREAD_MODE=false to get exact v2 behaviour (every event to the feed).

Carried over from v2:
  - One API call per cycle covers both leagues (live=1-39).
  - Status milestones fire on OBSERVED transitions, so a restart mid-match does
    not replay milestones that already passed.
  - Finals (FT/AET/PEN) are caught after a match leaves the live feed and are
    RETRIED until the API marks the match final.
  - Per-event on/off env toggles; min-gap throttle between Graph API writes.

Environment variables (set on the Render service):
  APISPORTS_KEY, FB_PAGE_TOKEN                       (required)
  FB_PAGE_ID    default 1250624194793094
  LIVE_LEAGUES  default 1-39   (World Cup + EPL)
  RENDERER_URL  default the /results endpoint
  STATE_PATH    default /data/live_state.json
  POST_FT_CARDS default false  (worker posts FT text; digest owns the card)
  THREAD_MODE   default true   (anchor post + comments)
  FEED_EVENTS   default GOALS,FULLTIME
                categories that ALSO post to the feed while in thread mode.
                Valid: HALFTIME SECONDHALF EXTRATIME FULLTIME GOALS REDCARDS
                       PENALTIES SHOOTOUT   (KICKOFF is always the anchor)
  Per-type toggles, all default true:
    POST_KICKOFF POST_HALFTIME POST_SECONDHALF POST_EXTRATIME
    POST_FULLTIME POST_GOALS POST_REDCARDS POST_PENALTIES POST_SHOOTOUT
"""

import os
import sys
import json
import time
from datetime import datetime, timezone

import requests

API_KEY       = os.environ.get("APISPORTS_KEY", "")
FB_PAGE_ID    = os.environ.get("FB_PAGE_ID", "1250624194793094")
FB_TOKEN      = os.environ.get("FB_PAGE_TOKEN", "")
LEAGUES       = os.environ.get("LIVE_LEAGUES", "1-39")
RENDERER_URL  = os.environ.get("RENDERER_URL", "https://trendradar-cards.onrender.com/results")
STATE_PATH    = os.environ.get("STATE_PATH", "/data/live_state.json")
POST_FT_CARDS = os.environ.get("POST_FT_CARDS", "false").lower() == "true"
THREAD_MODE   = os.environ.get("THREAD_MODE", "true").lower() == "true"
FEED_EVENTS   = set(x.strip().upper() for x in
                    os.environ.get("FEED_EVENTS", "GOALS,FULLTIME").split(",") if x.strip())


def _flag(name):
    return os.environ.get(name, "true").lower() == "true"

FLAGS = {
    "KICKOFF":   _flag("POST_KICKOFF"),
    "HALFTIME":  _flag("POST_HALFTIME"),
    "SECONDHALF":_flag("POST_SECONDHALF"),
    "EXTRATIME": _flag("POST_EXTRATIME"),
    "FULLTIME":  _flag("POST_FULLTIME"),
    "GOALS":     _flag("POST_GOALS"),
    "REDCARDS":  _flag("POST_REDCARDS"),
    "PENALTIES": _flag("POST_PENALTIES"),
    "SHOOTOUT":  _flag("POST_SHOOTOUT"),
}

GRAPH          = "https://graph.facebook.com/v23.0"
APISPORTS_BASE = "https://v3.football.api-sports.io"

POLL_LIVE    = 60
POLL_IDLE    = 300
MIN_POST_GAP = 8
BACKOFF_429  = 90
FINAL_MAX_TRIES = 40   # ~40 cycles to keep retrying a finished match's final
MAX_THREADS     = 60   # anchor post ids kept in state


def log(*a):
    print(datetime.now(timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


# ---- state ----------------------------------------------------------------
def load_state():
    try:
        with open(STATE_PATH) as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("posted_events", [])   # goals, red cards, missed pens
    s.setdefault("milestones", [])      # status milestones f"{fid}:KO" etc.
    s.setdefault("last_status", {})     # fid(str) -> short status
    s.setdefault("seen_live", [])       # fids live last cycle
    s.setdefault("ft_final", [])        # fids whose final was posted
    s.setdefault("pending_final", {})   # fid(str) -> attempts, awaiting final
    s.setdefault("threads", {})         # fid(str) -> anchor post id
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
    try:
        r = requests.get(f"{APISPORTS_BASE}/fixtures", params={"live": LEAGUES},
                         headers={"x-apisports-key": API_KEY}, timeout=15)
        if r.status_code == 429:
            log("WARN API-SPORTS 429; backing off")
            time.sleep(BACKOFF_429)
            return None
        r.raise_for_status()
        return r.json().get("response", [])
    except Exception as e:
        log("WARN fetch_live failed:", e)
        return None


def fetch_fixture(fid):
    try:
        r = requests.get(f"{APISPORTS_BASE}/fixtures", params={"id": fid},
                         headers={"x-apisports-key": API_KEY}, timeout=15)
        r.raise_for_status()
        resp = r.json().get("response", [])
        return resp[0] if resp else None
    except Exception as e:
        log("WARN fetch_fixture failed:", fid, e)
        return None


# ---- Facebook -------------------------------------------------------------
_last_post = [0.0]


def _throttle():
    gap = time.time() - _last_post[0]
    if gap < MIN_POST_GAP:
        time.sleep(MIN_POST_GAP - gap)
    _last_post[0] = time.time()


def post_text(message):
    """Feed post. Returns the new post id on success, else None."""
    _throttle()
    try:
        r = requests.post(f"{GRAPH}/{FB_PAGE_ID}/feed",
                          data={"message": message, "access_token": FB_TOKEN}, timeout=20)
        ok = (r.status_code == 200)
        log("POSTED" if ok else f"FAIL {r.status_code} {r.text[:100]}", repr(message.split(chr(10))[0]))
        if ok:
            try:
                return r.json().get("id")
            except Exception:
                return "unknown"
        return None
    except Exception as e:
        log("WARN post_text failed:", e)
        return None


def post_comment(post_id, message):
    """Comment on an existing post. Returns True on success."""
    _throttle()
    try:
        r = requests.post(f"{GRAPH}/{post_id}/comments",
                          data={"message": message, "access_token": FB_TOKEN}, timeout=20)
        ok = (r.status_code == 200)
        log("COMMENT" if ok else f"FAIL comment {r.status_code} {r.text[:100]}",
            repr(message.split(chr(10))[0]))
        return ok
    except Exception as e:
        log("WARN post_comment failed:", e)
        return False


def post_photo(png_bytes, caption):
    _throttle()
    try:
        r = requests.post(f"{GRAPH}/{FB_PAGE_ID}/photos",
                          data={"caption": caption, "published": "true", "access_token": FB_TOKEN},
                          files={"source": ("card.png", png_bytes, "image/png")}, timeout=40)
        ok = (r.status_code == 200)
        log("POSTED FT card" if ok else f"FAIL FT {r.status_code}")
        return ok
    except Exception as e:
        log("WARN post_photo failed:", e)
        return False


def render_ft_card(fx):
    league, teams, goals = fx["league"], fx["teams"], fx["goals"]
    home, away = teams["home"]["name"], teams["away"]["name"]
    pen = ""
    sc = (fx.get("score") or {}).get("penalty") or {}
    if sc.get("home") is not None and sc.get("away") is not None:
        winner = home if sc["home"] > sc["away"] else away
        pen = f"{winner} won {max(sc['home'], sc['away'])}-{min(sc['home'], sc['away'])} on penalties"
    groups = [{"round": league.get("round", ""), "matches": [{
        "home": home, "away": away, "score": f"{goals.get('home')} - {goals.get('away')}",
        "pen": pen, "home_flag": teams["home"].get("logo"), "away_flag": teams["away"].get("logo")}]}]
    body = {"title": f"{league['name']} Result",
            "date": datetime.now(timezone.utc).strftime("%d %b %Y").lstrip("0"), "groups": groups}
    r = requests.post(RENDERER_URL, json=body, timeout=60)
    r.raise_for_status()
    return r.content


# ---- helpers --------------------------------------------------------------
def _minute(ev):
    t = ev.get("time", {}) or {}
    m = t.get("elapsed")
    if t.get("extra"):
        m = f"{m}+{t['extra']}"
    return m


def event_signature(fid, ev):
    t = ev.get("time", {}) or {}
    team = ev.get("team") or {}
    player = ev.get("player") or {}
    return "|".join(str(x) for x in [fid, t.get("elapsed"), t.get("extra"),
                                     team.get("id"), player.get("id"),
                                     ev.get("type"), ev.get("detail")])


def _teams(fx):
    return fx["teams"]["home"]["name"], fx["teams"]["away"]["name"]


def _score_line(fx):
    home, away = _teams(fx)
    g = fx["goals"]
    return f"{home} {g.get('home')} - {g.get('away')} {away}"


def _lg(fx):
    lg = fx["league"]
    return f"{lg['name']} \u00b7 {lg.get('round', '')}".rstrip(" \u00b7")


def thread_anchor_message(fx):
    home, away = _teams(fx)
    return (f"\U0001F3DF MATCH THREAD\n{home} vs {away}\n{_lg(fx)}\n\n"
            "Follow this post for live coverage. Every goal, card, and key "
            "moment will appear in the comments as it happens.")


def goal_message(fx, ev):
    home, away = _teams(fx)
    g = fx["goals"]
    detail = ev.get("detail") or ""
    scorer = (ev.get("player") or {}).get("name") or ""
    line = f"\u26bd {_minute(ev)}' GOAL\n{home} {g.get('home')} - {g.get('away')} {away}"
    if "Own" in detail:
        line += "\n(own goal)"
    elif scorer:
        line += f"\n{scorer}{' (penalty)' if 'Penalty' in detail else ''}"
    return line + f"\n{_lg(fx)}"


def redcard_message(fx, ev):
    team = (ev.get("team") or {}).get("name", "")
    player = (ev.get("player") or {}).get("name", "")
    return f"\U0001F7E5 {_minute(ev)}' RED CARD\n{player} ({team})\n{_score_line(fx)}"


def penmiss_message(fx, ev):
    team = (ev.get("team") or {}).get("name", "")
    player = (ev.get("player") or {}).get("name", "")
    return f"\u274C {_minute(ev)}' PENALTY MISSED\n{player} ({team})\n{_score_line(fx)}"


def milestone_message(fx, key):
    home, away = _teams(fx)
    s = _score_line(fx)
    lg = _lg(fx)
    if key == "KO":
        return f"\U0001F3C1 KICK-OFF\n{home} vs {away}\n{lg}"
    if key == "HT":
        return f"\u23F8 HALF-TIME\n{s}\n{lg}"
    if key == "2H":
        return f"\u25B6 SECOND HALF UNDERWAY\n{s}"
    if key == "ETS":
        return f"\u23F1 END OF 90 MINUTES\nLevel at {s}. Into extra time."
    if key == "ETHT":
        return f"\u23F8 EXTRA-TIME HALF-TIME\n{s}"
    if key == "ET2":
        return f"\u25B6 EXTRA TIME \u00b7 SECOND HALF\n{s}"
    if key == "PENS":
        return f"\u23F1 END OF EXTRA TIME\n{s}. To penalties."
    return s


def final_message(fx, short):
    home, away = _teams(fx)
    g = fx["goals"]
    base = f"{home} {g.get('home')} - {g.get('away')} {away}"
    lg = _lg(fx)
    if short == "PEN":
        sc = (fx.get("score") or {}).get("penalty") or {}
        pen = ""
        if sc.get("home") is not None and sc.get("away") is not None:
            winner = home if sc["home"] > sc["away"] else away
            pen = f"\n{winner} win {max(sc['home'], sc['away'])}-{min(sc['home'], sc['away'])} on penalties"
        return f"\U0001F3C1 FULL-TIME (penalties)\n{base}{pen}\n{lg}"
    if short == "AET":
        return f"\U0001F3C1 FULL-TIME (after extra time)\n{base}\n{lg}"
    return f"\U0001F3C1 FULL-TIME\n{base}\n{lg}"


# ---- publishing dispatcher -------------------------------------------------
def ensure_thread(fid, fx, state):
    """Return the anchor post id for this fixture, creating it if needed.
    Returns None when thread mode is off or anchor creation failed."""
    if not THREAD_MODE:
        return None
    tid = state["threads"].get(str(fid))
    if tid:
        return tid
    pid = post_text(thread_anchor_message(fx))
    if pid:
        state["threads"][str(fid)] = pid
        # prune oldest entries beyond cap (dict preserves insertion order)
        while len(state["threads"]) > MAX_THREADS:
            state["threads"].pop(next(iter(state["threads"])))
        return pid
    return None


def publish_event(fid, fx, category, message, state):
    """Route one event: comment on the match thread, plus feed when the
    category is in FEED_EVENTS. Falls back to a feed post whenever no thread
    is available. Returns True if the event went out on at least one surface."""
    if not THREAD_MODE:
        return post_text(message) is not None
    tid = ensure_thread(fid, fx, state)
    sent = False
    if tid:
        sent = post_comment(tid, message)
    if category in FEED_EVENTS or not tid:
        if post_text(message) is not None:
            sent = True
    return sent


# ---- cycle ----------------------------------------------------------------
# Milestone rules: (current_status, allowed_previous_statuses) -> (key, toggle)
_TRANSITIONS = [
    ("1H", ("NS", "TBD"),   "KO",   "KICKOFF"),
    ("HT", ("1H",),         "HT",   "HALFTIME"),
    ("2H", ("HT",),         "2H",   "SECONDHALF"),
    ("ET", ("2H",),         "ETS",  "EXTRATIME"),
    ("BT", ("ET",),         "ETHT", "EXTRATIME"),
    ("ET", ("BT",),         "ET2",  "EXTRATIME"),
    ("P",  ("ET", "BT"),    "PENS", "SHOOTOUT"),
]


def process_cycle(live, state):
    posted = set(state["posted_events"])
    milestones = set(state["milestones"])
    last_status = state["last_status"]
    ft_final = set(state["ft_final"])
    pending = dict(state["pending_final"])
    current = set()

    for fx in live:
        fid = fx["fixture"]["id"]
        current.add(fid)
        cur = fx["fixture"]["status"]["short"]
        prev = last_status.get(str(fid))

        if prev is not None and prev != cur:
            for c_status, prevs, key, toggle in _TRANSITIONS:
                if cur == c_status and prev in prevs:
                    mk = f"{fid}:{key}"
                    if FLAGS[toggle] and mk not in milestones:
                        if key == "KO" and THREAD_MODE:
                            # kick-off IS the anchor post in thread mode
                            if ensure_thread(fid, fx, state):
                                milestones.add(mk)
                        else:
                            if publish_event(fid, fx, toggle, milestone_message(fx, key), state):
                                milestones.add(mk)
                    break
        last_status[str(fid)] = cur

        for ev in fx.get("events", []) or []:
            etype = ev.get("type")
            detail = ev.get("detail") or ""
            sig = event_signature(fid, ev)
            if etype == "Goal" and "Missed" not in detail:
                if FLAGS["GOALS"] and sig not in posted and \
                        publish_event(fid, fx, "GOALS", goal_message(fx, ev), state):
                    posted.add(sig)
            elif etype == "Goal" and "Missed" in detail:
                if FLAGS["PENALTIES"] and sig not in posted and \
                        publish_event(fid, fx, "PENALTIES", penmiss_message(fx, ev), state):
                    posted.add(sig)
            elif etype == "Card" and ("Red" in detail or "Second Yellow" in detail):
                if FLAGS["REDCARDS"] and sig not in posted and \
                        publish_event(fid, fx, "REDCARDS", redcard_message(fx, ev), state):
                    posted.add(sig)

    # matches that left the live feed -> queue for a confirmed final
    for fid in set(state["seen_live"]) - current:
        if fid not in ft_final and str(fid) not in pending:
            pending[str(fid)] = 0

    # resolve pending finals (retried until the API marks them final)
    for fid_s in list(pending.keys()):
        fid = int(fid_s)
        pending[fid_s] += 1
        fx = fetch_fixture(fid)
        short = fx["fixture"]["status"]["short"] if fx else None
        if short in ("FT", "AET", "PEN"):
            if FLAGS["FULLTIME"]:
                if publish_event(fid, fx, "FULLTIME", final_message(fx, short), state):
                    ft_final.add(fid)
                    pending.pop(fid_s, None)
            else:
                ft_final.add(fid)
                pending.pop(fid_s, None)
            if POST_FT_CARDS and fx:
                try:
                    post_photo(render_ft_card(fx), _score_line(fx))
                except Exception as e:
                    log("WARN FT card failed:", fid, e)
        elif pending[fid_s] >= FINAL_MAX_TRIES:
            log("WARN giving up on final for", fid)
            pending.pop(fid_s, None)

    state["posted_events"] = list(posted)[-1200:]
    state["milestones"] = list(milestones)[-600:]
    state["ft_final"] = list(ft_final)[-300:]
    state["pending_final"] = pending
    state["seen_live"] = list(current)
    return current


def main():
    if not API_KEY or not FB_TOKEN:
        log("FATAL missing APISPORTS_KEY or FB_PAGE_TOKEN env var")
        sys.exit(1)
    on = [k for k, v in FLAGS.items() if v]
    log("live worker v3 starting; leagues", LEAGUES,
        "| thread mode:", THREAD_MODE,
        "| feed events:", ",".join(sorted(FEED_EVENTS)) if THREAD_MODE else "ALL",
        "| FT cards:", POST_FT_CARDS,
        "| events on:", ",".join(on))
    state = load_state()
    while True:
        live = fetch_live()
        if live is None:
            time.sleep(POLL_IDLE)
            continue
        current = process_cycle(live, state)
        save_state(state)
        time.sleep(POLL_LIVE if (current or state["pending_final"]) else POLL_IDLE)


if __name__ == "__main__":
    main()
