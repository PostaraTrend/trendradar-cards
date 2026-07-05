#!/usr/bin/env python3
"""
Trend Radar NG - Live in-play worker v3.3 (Match Thread mode + Claude voice)
============================================================================
Always-on Render background worker, OUTSIDE n8n (no execution metering). Polls
API-SPORTS for in-play fixtures and narrates every major match event.

NEW IN v3.3 - GOAL CONFIRMATION LAYER (anti ghost-goal):
- API-SPORTS registers goal events BEFORE VAR checks resolve and BEFORE the
  fixture score updates. Result observed July 5, 2026 (Brazil vs Norway): a
  3' "goal" was posted with a stale 0-0 score, then silently retracted by the
  API after VAR disallowed it. The final score proved it never counted.
- Fix: GOAL events are now held in a pending queue and published only after
  they have survived GOAL_CONFIRM_CYCLES consecutive polls AND the fixture
  score agrees with the count of goal events (the "settled" signal). A goal
  that vanishes from the events array while pending is dropped with a log
  line and never reaches the page.
- Re-timed duplicates: API-SPORTS sometimes shifts a goal's minute after the
  fact (79' <-> 80'). A goal whose team + player match an already-posted goal
  within two minutes is treated as the same goal and never posts twice.
- Force-publish safety valve: a goal that persists GOAL_CONFIRM_MAX cycles is
  published even if the score check never settles, so a real goal can never
  be lost to an API accounting quirk.
- Shootout exception: during penalty shootouts (status P) events fire
  rapid-fire and are never VAR-retracted, so they bypass the delay entirely.
- All other event types (kick-off, half-time, full-time, red cards) keep
  instant publishing - they are never retracted by the API.
- New env vars (set on the Render service):
      GOAL_CONFIRM_CYCLES  default 2  (polls a goal must survive; 0 disables
                           the layer and restores v3.2 instant behaviour)
      GOAL_CONFIRM_MAX     default 5  (force-publish ceiling)
- Latency cost: roughly 2 x POLL_LIVE = ~2 minutes on goal comments. Ghost
  goals cost audience trust; two minutes does not.

Carried over from v3.2 - CLAUDE COMMENTARY LAYER:
- Every event message keeps its factual template line (score, minute, names
  come from the API, never from the model - zero hallucination risk on facts)
  and appends ONE short Claude-written commentary line in the Trend Radar NG
  voice: energetic Nigerian English, no contractions.
- Fail-safe by design: any Claude error, timeout, over-length reply, or
  contraction slip falls back silently to the plain template message.
  A Claude outage can never delay, block, or spam the thread.
- Env vars: ANTHROPIC_API_KEY (optional), CLAUDE_COMMENTARY (default true),
  CLAUDE_MODEL (default claude-haiku-4-5-20251001).

Carried over from v3/v3.1:
- At kick-off the worker publishes ONE anchor feed post per match; every
  subsequent event is a COMMENT on that anchor. Selected big moments ALSO go
  to the feed (default: goals and full-time) via FEED_EVENTS.
- Mid-match (re)starts anchor immediately on first sighting (v3.1).
- One API call per cycle covers both leagues (live=1-39).
- Status milestones fire on OBSERVED transitions; finals are retried until
  the API marks the match final; per-event toggles; min-gap throttle.

Environment variables (set on the Render service):
    APISPORTS_KEY, FB_PAGE_TOKEN (required)
    ANTHROPIC_API_KEY            (required for v3.2 flavor lines)
    FB_PAGE_ID     default 1250624194793094
    LIVE_LEAGUES   default 1-39 (World Cup + EPL)
    RENDERER_URL   default the /results endpoint
    STATE_PATH     default /data/live_state.json
    POST_FT_CARDS  default false (worker posts FT text; digest owns the card)
    THREAD_MODE    default true (anchor post + comments)
    GOAL_CONFIRM_CYCLES  default 2 (v3.3, see above)
    GOAL_CONFIRM_MAX     default 5 (v3.3, see above)
    FEED_EVENTS    default GOALS,FULLTIME
        categories that ALSO post to the feed while in thread mode.
        Valid: HALFTIME SECONDHALF EXTRATIME FULLTIME GOALS REDCARDS
               PENALTIES SHOOTOUT (KICKOFF is always the anchor)
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

API_KEY = os.environ.get("APISPORTS_KEY", "")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "1250624194793094")
FB_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
LEAGUES = os.environ.get("LIVE_LEAGUES", "1-39")
RENDERER_URL = os.environ.get("RENDERER_URL", "https://trendradar-cards.onrender.com/results")
STATE_PATH = os.environ.get("STATE_PATH", "/data/live_state.json")
POST_FT_CARDS = os.environ.get("POST_FT_CARDS", "false").lower() == "true"
THREAD_MODE = os.environ.get("THREAD_MODE", "true").lower() == "true"
FEED_EVENTS = set(x.strip().upper() for x in
                  os.environ.get("FEED_EVENTS", "GOALS,FULLTIME").split(",") if x.strip())

# ---- v3.3: goal confirmation configuration ---------------------------------
def _int_env(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


GOAL_CONFIRM_CYCLES = _int_env("GOAL_CONFIRM_CYCLES", 2)   # polls a goal must survive
GOAL_CONFIRM_MAX = _int_env("GOAL_CONFIRM_MAX", 5)         # force-publish ceiling

# ---- v3.2: Claude commentary configuration ---------------------------------
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_COMMENTARY = os.environ.get("CLAUDE_COMMENTARY", "true").lower() == "true"
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_TIMEOUT = 12          # seconds; a slow model reply must never stall polling
CLAUDE_MAX_CHARS = 240       # over-length replies are dropped, template stands alone

CLAUDE_SYSTEM = (
    "You write ONE short live-commentary line for Trend Radar NG, a Nigerian "
    "football page on Facebook. The factual line (minute, score, player) is "
    "already shown above your line, so DO NOT repeat the score or the minute.\n"
    "Voice: energetic Nigerian English with warm banter; a light Pidgin touch "
    "is welcome when it lands naturally; at most one emoji.\n"
    "HARD RULES:\n"
    "1. NEVER use contractions. Write 'do not', 'it is', 'they are' - never "
    "'don't', 'it's', 'they're'. Possessives like 'Osimhen's strike' are fine.\n"
    "2. Do not invent any fact beyond the event described. No injuries, no "
    "assists, no crowd details you were not given.\n"
    "3. One or two short sentences, maximum 200 characters.\n"
    "4. Output ONLY the commentary line. No quotes, no preamble, no hashtags."
)

# Contraction fragments that trigger fallback (possessive apostrophes pass).
_CONTRACTION_HITS = ("n't", "'re", "'ll", "'ve", "'m ", "it's", "that's",
                     "there's", "let's", "he's", "she's", "what's", "who's",
                     "here's", "we'd", "i'd", "you'd", "they'd")


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

GRAPH = "https://graph.facebook.com/v23.0"
APISPORTS_BASE = "https://v3.football.api-sports.io"
POLL_LIVE = 60
POLL_IDLE = 300
MIN_POST_GAP = 8
BACKOFF_429 = 90
FINAL_MAX_TRIES = 40   # ~40 cycles to keep retrying a finished match's final
MAX_THREADS = 60       # anchor post ids kept in state
MAX_PENDING_GOALS = 60 # pending confirmation entries kept in state
INPLAY = ("1H", "HT", "2H", "ET", "BT", "P")  # statuses that warrant a thread


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
    s.setdefault("pending_goals", {})   # v3.3: event sig -> polls survived
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


# ---- v3.2: Claude flavor line ----------------------------------------------

def claude_flavor(event_desc):
    """Return one short Naija-voiced commentary line, or None on ANY problem.
    None means the caller publishes the plain template message - the worker
    must never lose an event because the flavor layer hiccupped."""
    if not (CLAUDE_COMMENTARY and ANTHROPIC_KEY):
        return None
    try:
        r = requests.post(
            CLAUDE_URL,
            headers={"x-api-key": ANTHROPIC_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": CLAUDE_MODEL,
                  "max_tokens": 120,
                  "system": CLAUDE_SYSTEM,
                  "messages": [{"role": "user", "content": event_desc}]},
            timeout=CLAUDE_TIMEOUT)
        if r.status_code != 200:
            log("WARN claude status", r.status_code, r.text[:80])
            return None
        parts = r.json().get("content", []) or []
        text = "".join(p.get("text", "") for p in parts
                       if p.get("type") == "text").strip().strip('"').strip()
        if not text or len(text) > CLAUDE_MAX_CHARS or "\n" in text:
            return None
        low = text.lower()
        if any(h in low for h in _CONTRACTION_HITS):
            return None    # no-contractions rule is absolute; fall back
        return text
    except Exception as e:
        log("WARN claude_flavor failed:", e)
        return None


def with_flavor(base_message, event_desc):
    """Append the Claude line to the factual template when available."""
    fl = claude_flavor(event_desc)
    return f"{base_message}\n\n{fl}" if fl else base_message


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


# ---- v3.3: goal confirmation helpers ----------------------------------------

def _sig_parts(sig):
    """Split a signature back into its 7 components, or None if malformed.
    Order: fid, elapsed, extra, team_id, player_id, type, detail."""
    p = sig.split("|")
    return p if len(p) == 7 else None


def _fuzzy_posted(fid, ev, posted):
    """True when a goal by the same team + player was already posted within
    two minutes of this event. API-SPORTS re-times goal events retroactively
    (a 79' goal can become an 80' goal), which changes the signature; without
    this guard a re-timed goal would publish twice."""
    team = str((ev.get("team") or {}).get("id"))
    player = str((ev.get("player") or {}).get("id"))
    try:
        el = int((ev.get("time") or {}).get("elapsed"))
    except (TypeError, ValueError):
        return False
    for sig in posted:
        p = _sig_parts(sig)
        if not p or p[0] != str(fid) or p[5] != "Goal":
            continue
        if "Missed" in (p[6] or ""):
            continue
        if p[3] == team and p[4] == player:
            try:
                if abs(int(p[1]) - el) <= 2:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _score_settled(fx):
    """True when the fixture score agrees with the number of goal events.
    This is the signal that API-SPORTS has finished settling the incident
    (VAR resolved, score field updated). Shootout events carry a
    'Penalty Shootout' comment and never count toward the fixture score,
    so they are excluded."""
    g = fx.get("goals") or {}
    total = (g.get("home") or 0) + (g.get("away") or 0)
    n = 0
    for ev in fx.get("events", []) or []:
        if ev.get("type") != "Goal":
            continue
        if "Missed" in (ev.get("detail") or ""):
            continue
        if "Shootout" in (ev.get("comments") or ""):
            continue
        n += 1
    return n == total


def _teams(fx):
    return fx["teams"]["home"]["name"], fx["teams"]["away"]["name"]


def _score_line(fx):
    home, away = _teams(fx)
    g = fx["goals"]
    return f"{home} {g.get('home')} - {g.get('away')} {away}"


def _lg(fx):
    lg = fx["league"]
    return f"{lg['name']} \u00b7 {lg.get('round', '')}".rstrip(" \u00b7")


def thread_anchor_message(fx, midmatch=False):
    home, away = _teams(fx)
    head = f"\U0001F3DF MATCH THREAD\n{home} vs {away}\n{_lg(fx)}"
    if midmatch:
        head += f"\n\nThis match is underway. Latest score: {_score_line(fx)}."
    return (head + "\n\nFollow this post for live coverage. Every goal, card, "
            "and key moment will appear in the comments as it happens.")


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


# ---- v3.2: event descriptions fed to Claude ---------------------------------

def _desc_goal(fx, ev):
    detail = ev.get("detail") or ""
    scorer = (ev.get("player") or {}).get("name") or "unknown scorer"
    team = (ev.get("team") or {}).get("name", "")
    kind = "own goal" if "Own" in detail else ("penalty" if "Penalty" in detail else "goal")
    return (f"Event: {kind} in minute {_minute(ev)} by {scorer} ({team}). "
            f"Score now {_score_line(fx)}. Competition: {_lg(fx)}.")


def _desc_redcard(fx, ev):
    player = (ev.get("player") or {}).get("name", "a player")
    team = (ev.get("team") or {}).get("name", "")
    return (f"Event: red card in minute {_minute(ev)} for {player} ({team}). "
            f"Score {_score_line(fx)}. Competition: {_lg(fx)}.")


def _desc_penmiss(fx, ev):
    player = (ev.get("player") or {}).get("name", "a player")
    team = (ev.get("team") or {}).get("name", "")
    return (f"Event: penalty missed in minute {_minute(ev)} by {player} ({team}). "
            f"Score {_score_line(fx)}. Competition: {_lg(fx)}.")


_MILESTONE_DESC = {
    "HT":  "Event: half-time whistle.",
    "2H":  "Event: second half has just kicked off.",
    "ETS": "Event: ninety minutes complete, match level, heading into extra time.",
    "ETHT": "Event: half-time in extra time.",
    "ET2": "Event: second half of extra time under way.",
    "PENS": "Event: extra time complete, the match goes to a penalty shootout.",
}


def _desc_milestone(fx, key):
    base = _MILESTONE_DESC.get(key, "Event: match status update.")
    return f"{base} Score {_score_line(fx)}. Competition: {_lg(fx)}."


def _desc_final(fx, short):
    how = {"PEN": "decided on penalties", "AET": "after extra time"}.get(short, "at full time")
    return (f"Event: full-time whistle, match finished {how}. "
            f"Final score {_score_line(fx)}. Competition: {_lg(fx)}.")


# ---- publishing dispatcher -------------------------------------------------

def ensure_thread(fid, fx, state):
    """Return the anchor post id for this fixture, creating it if needed.
    Returns None when thread mode is off or anchor creation failed."""
    if not THREAD_MODE:
        return None
    tid = state["threads"].get(str(fid))
    if tid:
        return tid
    midmatch = fx["fixture"]["status"]["short"] != "1H" or bool(fx.get("events"))
    pid = post_text(thread_anchor_message(fx, midmatch=midmatch))
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
    ("1H", ("NS", "TBD"), "KO", "KICKOFF"),
    ("HT", ("1H",), "HT", "HALFTIME"),
    ("2H", ("HT",), "2H", "SECONDHALF"),
    ("ET", ("2H",), "ETS", "EXTRATIME"),
    ("BT", ("ET",), "ETHT", "EXTRATIME"),
    ("ET", ("BT",), "ET2", "EXTRATIME"),
    ("P", ("ET", "BT"), "PENS", "SHOOTOUT"),
]


def process_cycle(live, state):
    posted = set(state["posted_events"])
    milestones = set(state["milestones"])
    last_status = state["last_status"]
    ft_final = set(state["ft_final"])
    pending = dict(state["pending_final"])
    pending_goals = dict(state["pending_goals"])   # v3.3
    seen_goal_sigs = set()                          # v3.3: goal sigs seen this cycle
    current = set()

    for fx in live:
        fid = fx["fixture"]["id"]
        current.add(fid)
        cur = fx["fixture"]["status"]["short"]
        prev = last_status.get(str(fid))

        # v3.1: first sighting of an in-play match -> create the thread now,
        # so a worker (re)started mid-match anchors immediately, event or not.
        if THREAD_MODE and cur in INPLAY and str(fid) not in state["threads"]:
            ensure_thread(fid, fx, state)

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
                            msg = with_flavor(milestone_message(fx, key),
                                              _desc_milestone(fx, key))  # v3.2
                            if publish_event(fid, fx, toggle, msg, state):
                                milestones.add(mk)
                    break
        last_status[str(fid)] = cur

        for ev in fx.get("events", []) or []:
            etype = ev.get("type")
            detail = ev.get("detail") or ""
            sig = event_signature(fid, ev)
            if etype == "Goal" and "Missed" not in detail:
                if FLAGS["GOALS"] and sig not in posted:
                    # ---- v3.3: goal confirmation layer -----------------
                    seen_goal_sigs.add(sig)
                    if _fuzzy_posted(fid, ev, posted):
                        # re-timed duplicate of an already-posted goal:
                        # mark handled so it never publishes twice
                        log("SKIP re-timed duplicate goal", sig)
                        posted.add(sig)
                        pending_goals.pop(sig, None)
                    elif cur == "P" or GOAL_CONFIRM_CYCLES <= 0:
                        # shootout kicks fire rapidly and are never
                        # VAR-retracted; layer disabled -> v3.2 behaviour
                        msg = with_flavor(goal_message(fx, ev), _desc_goal(fx, ev))
                        if publish_event(fid, fx, "GOALS", msg, state):
                            posted.add(sig)
                    else:
                        n = pending_goals.get(sig, 0) + 1
                        confirmed = n > GOAL_CONFIRM_CYCLES and _score_settled(fx)
                        forced = n > GOAL_CONFIRM_MAX
                        if confirmed or forced:
                            if forced and not confirmed:
                                log("FORCE publishing goal after",
                                    n, "cycles (score never settled)", sig)
                            msg = with_flavor(goal_message(fx, ev), _desc_goal(fx, ev))
                            if publish_event(fid, fx, "GOALS", msg, state):
                                posted.add(sig)
                                pending_goals.pop(sig, None)
                            else:
                                pending_goals[sig] = n
                        else:
                            pending_goals[sig] = n
                            log("HOLD goal awaiting confirmation",
                                f"cycle {n}/{GOAL_CONFIRM_CYCLES + 1}", sig)
            elif etype == "Goal" and "Missed" in detail:
                if FLAGS["PENALTIES"] and sig not in posted:
                    msg = with_flavor(penmiss_message(fx, ev), _desc_penmiss(fx, ev))  # v3.2
                    if publish_event(fid, fx, "PENALTIES", msg, state):
                        posted.add(sig)
            elif etype == "Card" and ("Red" in detail or "Second Yellow" in detail):
                if FLAGS["REDCARDS"] and sig not in posted:
                    msg = with_flavor(redcard_message(fx, ev), _desc_redcard(fx, ev))  # v3.2
                    if publish_event(fid, fx, "REDCARDS", msg, state):
                        posted.add(sig)

    # v3.3: prune the pending-goal queue
    for sig in list(pending_goals.keys()):
        p = _sig_parts(sig)
        p_fid = int(p[0]) if p and p[0].isdigit() else None
        if p_fid in current and sig not in seen_goal_sigs:
            # the event vanished from the API while the match is still live:
            # VAR disallowed it (or the API withdrew it) BEFORE we published.
            # This is the July 5 Brazil-Norway ghost goal, now suppressed.
            log("DROP goal retracted before publish (VAR)", sig)
            pending_goals.pop(sig)
        elif p_fid not in current:
            # match left the live feed with the goal still unconfirmed; the
            # full-time post will carry the authoritative final score.
            log("DROP unconfirmed goal at match end (FT post covers score)", sig)
            pending_goals.pop(sig)
    while len(pending_goals) > MAX_PENDING_GOALS:
        pending_goals.pop(next(iter(pending_goals)))

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
                msg = with_flavor(final_message(fx, short), _desc_final(fx, short))  # v3.2
                if publish_event(fid, fx, "FULLTIME", msg, state):
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
    state["pending_goals"] = pending_goals   # v3.3
    state["seen_live"] = list(current)
    return current


def main():
    if not API_KEY or not FB_TOKEN:
        log("FATAL missing APISPORTS_KEY or FB_PAGE_TOKEN env var")
        sys.exit(1)
    on = [k for k, v in FLAGS.items() if v]
    claude_state = ("ON model " + CLAUDE_MODEL) if (CLAUDE_COMMENTARY and ANTHROPIC_KEY) else \
                   ("DISABLED" if not CLAUDE_COMMENTARY else "NO KEY (template-only)")
    goal_confirm_state = (f"ON ({GOAL_CONFIRM_CYCLES} cycles, force at {GOAL_CONFIRM_MAX})"
                          if GOAL_CONFIRM_CYCLES > 0 else "OFF (instant)")
    log("live worker v3.3 starting; leagues", LEAGUES,
        "| thread mode:", THREAD_MODE,
        "| feed events:", ",".join(sorted(FEED_EVENTS)) if THREAD_MODE else "ALL",
        "| FT cards:", POST_FT_CARDS,
        "| claude commentary:", claude_state,
        "| goal confirmation:", goal_confirm_state,
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
