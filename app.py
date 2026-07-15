"""
Trend Radar NG — Headline Card Render Service
=============================================
GET  /            -> health check ("ok")
GET/POST /card        -> news card (binary PNG, or JPEG with ?format=jpg)
GET/POST /wisdom      -> wisdom-lane card (binary PNG, or JPEG with ?format=jpg)
GET/POST /reflection  -> reflection-lane card (binary PNG, or JPEG with ?format=jpg)
GET/POST /health      -> health & wellness lane card (binary PNG, or JPEG with ?format=jpg)
POST /render/newsstand -> News Stand & Weather Report lane card (binary PNG)
POST /render/traffic   -> Traffic Watch lane card (binary PNG)
POST /render/peoples-voice -> People's Voice lane card (binary PNG, or JPEG with format=jpg)
GET  /render/creator-card -> Creator Tips lane card (binary JPEG; IG-compatible directly)
GET  /render/advertorial -> Advertorial lane card, SOP-ADV-001 (binary JPEG, or PNG with ?format=png)
GET/POST /render/verdict -> People's Verdict lane card (binary PNG, or JPEG with format=jpg)
GET/POST /render/gist  -> Gist Machine Pidgin lane card (binary PNG, or JPEG with format=jpg)
GET/POST /render/agent -> Trend Agent lane card (binary PNG, or JPEG with format=jpg)
GET  /render/verdict/health -> People's Verdict lane health check (added Jul 2026)
GET  /render/agent/health -> Trend Agent lane health check (added Jul 2026)
GET/POST /render/blessing -> Daily Blessing lane card (binary PNG, or JPEG with format=jpg)
GET  /render/blessing/health -> Daily Blessing lane health check (added Jul 2026)
POST /col/render       -> Cost of Living lane card (JSON: hosted image_url PNG + image_url_jpg)
GET  /col/image/<id>.png / .jpg -> serves a rendered COL card (1-hour TTL)
POST /scam/render      -> Shine Your Eye scam-alert card (JSON: hosted image_url PNG + image_url_jpg)
GET  /scam/image/<id>.png / .jpg -> serves a rendered Shine Your Eye card (1-hour TTL)
POST /promo            -> Level Up promo-lane card, Project Harvest (binary JPEG)
POST /host             -> host any rendered card binary; returns image_url + image_url_jpg (1-hour TTL)
GET  /hosted/<id>.png / .jpg -> serves a hosted card (generic, any lane; IG uses the .jpg)
POST /naijalens/render -> Naija Lens photo card (JSON: image_url; photo treatment
                          with quality gate, enhancement pass, hook + credit overlay)
POST /naturals/render  -> Naija Naturals nature card (JSON: image_url; photo treatment
                          with quality gate, enhancement pass, location bar + credit)
POST /mk/card          -> Mama's Kitchen recipe card (binary PNG)
GET  /mk/last-card     -> serves the most recently rendered Mama's Kitchen card
GET  /mk/health        -> Mama's Kitchen lane health check
GET  /brief/health     -> Naija Daily Brief lane health check (added Jul 2026)
POST /brief/render     -> Naija Daily Brief card (JSON: hosted url; static/brief/)
GET  /postara/health   -> PostaraTrend Autopilot lanes health check (added Jul 2026)
POST /receipts/render  -> Autopilot Receipts card (JSON: hosted url; static/postara/)
POST /tips/render      -> SMB Tips card (JSON: hosted url; static/postara/)

format=jpg (added Jul 2026): the Instagram Content Publishing API only accepts
JPEG via image_url, while Facebook accepts the PNG cards as-is. Any card route
in this file returns a JPEG when the request carries format=jpg (query param or
body field); every existing caller that does not send it keeps receiving the
same PNG as before.

COL lane (added Jul 2026): unlike the binary-returning routes above, /col/render
returns JSON with hosted URLs, because the COL n8n workflow publishes by handing
Meta a fetchable URL. It returns both image_url (PNG, for Facebook) and
image_url_jpg (JPEG, for Instagram). NOTE: the hosted images live in worker
memory — this service must keep running with a single gunicorn worker
(WEB_CONCURRENCY=1) or COL image serving breaks.

Shine Your Eye lane (added Jul 2026): same hosted-URL pattern as COL —
/scam/render returns JSON with image_url (PNG, Facebook) and image_url_jpg
(JPEG, Instagram). Inherits the single-worker constraint above.

Level Up promo lane (added Jul 2026, Project Harvest / SOP-HRV-001): /promo
returns the card binary directly (JPEG); the Publisher workflow posts that
binary to /host and publishes via the hosted image_url_jpg.

Naija Lens lane (added Jul 2026): /naijalens/render accepts JSON
(photo_url, hook_line1, hook_line2, credit, optional slide_tag), downloads the
photo, applies the quality gate (min 1500px short side, 422 on failure), the
enhancement pass, and the locked treatment, then returns JSON with a hosted
image_url served from /static/naijalens/. JPEG output, IG-compatible directly.

Creator Tips lane (added Jul 2026): /render/creator-card takes GET query
params (pill, tip_no, headline, body) and returns the card binary directly as
JPEG — the same URL therefore serves both the workflow's binary download for
Facebook and Instagram's image_url ingestion, with no format=jpg needed.

Mama's Kitchen lane (added Jul 2026): /mk/card renders the recipe card
(binary PNG) and stores the latest render in worker memory; /mk/last-card
serves it so the n8n Vision Gate can fetch the finished card for the AI
photo-match check before publishing. Inherits the single-worker constraint.

Advertorial lane (added Jul 2026, SOP-ADV-001): /render/advertorial takes GET
query params (headline, body, advertiser, brand_color, is_sample, powered_by)
and returns the card binary directly as JPEG (PNG with ?format=png) — the same
URL serves both the workflow's binary download for Facebook and Instagram's
image_url ingestion, like Creator Tips. Every card carries a permanent
"Sponsored" strip; is_sample=true adds the SAMPLE CAMPAIGN ribbon and
powered_by renders the white-label attribution line. Route lives in
advertorial_route.py, registered via register_advertorial(app).

Naija Daily Brief lane (added Jul 2026): /brief/render accepts JSON
(date_label, traffic, weather, football) and returns JSON with a hosted url
served from /static/brief/. JPEG output. Empty slots render a grey quiet
fallback; contractions in any slot return 422 (house style gate).
Route lives in daily_brief_cards.py, blueprint brief_bp.

PostaraTrend Autopilot lanes (added Jul 2026): /receipts/render and
/tips/render accept JSON and return JSON with a hosted url served from
/static/postara/. JPEG output, PostaraTrend branding, same contraction gate.
Routes live in postara_cards.py, blueprint postara_bp.

People's Verdict lane (added Jul 2026): /render/verdict accepts JSON
(title, summary, camps [{label, pct}], comments_count, date_label) and returns
the card binary directly (PNG default, JPEG with format=jpg). Navy/gold card
with a SHARE OF VOICE bar chart of the community camps. Same contraction gate
as the other lanes (422; possessives pass). Stateless — no hosting, no worker
memory. Route lives in verdict_card.py, blueprint verdict_bp.

Trend Agent lane (added Jul 2026): /render/agent renders the agent's own
"Radar" card — near-black ink with the house-gold radar sweep and contact
blip, format badge chip (EXPLAINER / HOT TAKE / LISTICLE / DEBATE), serif
headline. Accepts `category` as an alias for `badge` so the pre-repoint
workflow payload keeps working. Contraction gate ON (422; possessives pass) —
this is an English lane. Binary PNG default, JPEG with format=jpg. Stateless.
Route lives in agent_card.py, blueprint agent_bp.

Daily Blessing lane (added Jul 2026): /render/blessing renders the blessing
card — dawn palette (indigo to amber, rising glow) for slot=MORNING, dusk
palette (night violet, quiet stars) for slot=EVENING. Centered devotional
layout: DAILY BLESSING masthead, format chip (MORNING BLESSING / DECLARATION /
VERSE OF HOPE / EVENING GRACE / GRATITUDE / REST PRAYER), serif pull quote,
theme line. Interfaith by design — light-based motifs only. Contraction gate
ON (422; possessives pass). Binary PNG default, JPEG with format=jpg.
Stateless. Route lives in blessing_card.py, blueprint blessing_bp.
"""

from flask import Flask, request, send_file, Response
from io import BytesIO
from datetime import datetime
import json as _json
import os

from trend_radar_card import build_card, build_wisdom_card, build_reflection_card, build_results_card
from health_card import render_health_card
from newsstand_card import newsstand_bp
from traffic_card import traffic_bp
from peoples_voice_card import render_peoples_voice
from col_card import col_bp

app = Flask(__name__)
from wahala_card import wahala_bp
from jakpa_card import jakpa_bp
from scam_card import scam_bp
from HRV_promo_blueprint import promo_bp
from naijalens_route import naijalens          # NAIJA LENS (added Jul 2026)
from heritage_route import heritage            # HERITAGE (added Jul 2026)
from naturals_route import naturals            # NAIJA NATURALS (added Jul 2026)
from creator_cards import creator_bp           # CREATOR TIPS (added Jul 2026)
from mamas_kitchen_cards import mk_bp          # MAMA'S KITCHEN (added Jul 2026)
from advertorial_route import register_advertorial  # ADVERTORIAL (added Jul 2026, SOP-ADV-001)
from daily_brief_cards import brief_bp         # NAIJA DAILY BRIEF (added Jul 2026)
from postara_cards import postara_bp           # POSTARATREND AUTOPILOT (added Jul 2026)
from verdict_card import verdict_bp            # PEOPLE'S VERDICT (added Jul 2026)
from gist_card import gist_bp                  # GIST MACHINE (added Jul 2026)
from agent_card import agent_bp                # TREND AGENT (added Jul 2026)
from blessing_card import blessing_bp         # DAILY BLESSING (added Jul 2026)
app.register_blueprint(newsstand_bp)
app.register_blueprint(traffic_bp)
app.register_blueprint(wahala_bp)
app.register_blueprint(jakpa_bp)
app.register_blueprint(col_bp)
app.register_blueprint(scam_bp)
app.register_blueprint(promo_bp)
app.register_blueprint(naijalens)              # NAIJA LENS (added Jul 2026)
app.register_blueprint(heritage)               # HERITAGE (added Jul 2026)
app.register_blueprint(naturals)               # NAIJA NATURALS (added Jul 2026)
app.register_blueprint(creator_bp)             # CREATOR TIPS (added Jul 2026)
app.register_blueprint(mk_bp)                  # MAMA'S KITCHEN (added Jul 2026)
register_advertorial(app)                      # ADVERTORIAL (added Jul 2026, SOP-ADV-001)
app.register_blueprint(brief_bp)               # NAIJA DAILY BRIEF (added Jul 2026)
app.register_blueprint(postara_bp)             # POSTARATREND AUTOPILOT (added Jul 2026)
app.register_blueprint(verdict_bp)             # PEOPLE'S VERDICT (added Jul 2026)
app.register_blueprint(gist_bp)                # GIST MACHINE (added Jul 2026)
app.register_blueprint(agent_bp)               # TREND AGENT (added Jul 2026)
app.register_blueprint(blessing_bp)            # DAILY BLESSING (added Jul 2026)

MAX_HEADLINE = 240
ALLOWED = {"POLITICS", "ENTERTAINMENT", "EPL", "FOOTBALL", "ECONOMY", "GOSPEL", "DIASPORA", "TECH"}


def _source(req):
    """Return a dict of params from JSON body, raw JSON string, or form values.
    n8n sometimes posts a body that Flask does not auto-parse into a dict, so we
    parse defensively and always hand back something with .get()."""
    data = req.get_json(silent=True)
    if isinstance(data, dict):
        return data
    raw = req.get_data(as_text=True) or ""
    if raw.strip():
        try:
            parsed = _json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return req.values


def _send_image(img, base_name, src):
    """Serve a rendered Pillow image as PNG (default) or JPEG (format=jpg).
    Instagram's image_url ingestion accepts JPEG only; Facebook photo posts
    accept the PNGs unchanged, so PNG remains the default for every existing
    caller. JPEG conversion flattens transparency onto RGB before saving."""
    fmt = (src.get("format") or request.args.get("format") or "").strip().lower()
    buf = BytesIO()
    if fmt in ("jpg", "jpeg"):
        img.convert("RGB").save(buf, "JPEG", quality=92)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg",
                         download_name=f"{base_name}.jpg")
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name=f"{base_name}.png")


def _params(src):
    headline = (src.get("headline") or "").strip()[:MAX_HEADLINE]
    source = (src.get("source") or "").strip() or "the source"
    category = (src.get("category") or "POLITICS").strip().upper()
    if category not in ALLOWED:
        category = "POLITICS"
    date_str = (src.get("date") or "").strip() or datetime.now().strftime("%-d %b %Y")
    handle = (src.get("handle") or "fb.com/TrendRadarNG").strip()
    return headline, source, category, date_str, handle


def _wisdom_params(src):
    proverb  = (src.get("proverb_original") or src.get("proverb") or "").strip()
    meaning  = (src.get("meaning") or "").strip()
    language = (src.get("language") or "").strip()
    date_str = (src.get("date") or "").strip()
    handle   = (src.get("handle") or "fb.com/TrendRadarNG").strip()
    return proverb, meaning, language, date_str, handle


def _reflection_params(src):
    theme    = (src.get("theme_title") or "").strip()
    quote    = (src.get("pull_quote") or "").strip()
    date_str = (src.get("date") or "").strip()
    handle   = (src.get("handle") or "fb.com/TrendRadarNG").strip()
    return theme, quote, date_str, handle


@app.get("/")
def health():
    return "ok", 200


@app.route("/card", methods=["GET", "POST"])
def card():
    src = _source(request)
    headline, source, category, date_str, handle = _params(src)
    if not headline:
        return Response('{"error":"headline is required"}', status=400,
                        mimetype="application/json")
    img = build_card(headline, source, category, date_str, handle)
    return _send_image(img, "trendradar_card", src)


@app.route("/wisdom", methods=["GET", "POST"])
def wisdom():
    src = _source(request)
    proverb, meaning, language, date_str, handle = _wisdom_params(src)
    if not proverb:
        return Response('{"error":"proverb_original is required"}', status=400,
                        mimetype="application/json")
    img = build_wisdom_card(proverb, meaning, language, date_str, handle)
    return _send_image(img, "trendradar_wisdom", src)


@app.route("/reflection", methods=["GET", "POST"])
def reflection():
    src = _source(request)
    theme, quote, date_str, handle = _reflection_params(src)
    if not quote:
        return Response('{"error":"pull_quote is required"}', status=400,
                        mimetype="application/json")
    img = build_reflection_card(theme, quote, date_str, handle)
    return _send_image(img, "trendradar_reflection", src)


def _health_params(src):
    headline = (src.get("headline") or "").strip()[:MAX_HEADLINE]
    source   = (src.get("source") or "").strip() or "the source"
    date_str = (src.get("date") or "").strip() or datetime.now().strftime("%-d %b %Y")
    handle   = (src.get("handle") or "fb.com/TrendRadarNG").strip()
    return headline, source, date_str, handle


@app.route("/health", methods=["GET", "POST"])
def health_lane():
    src = _source(request)
    headline, source, date_str, handle = _health_params(src)
    if not headline:
        return Response('{"error":"headline is required"}', status=400,
                        mimetype="application/json")
    platform = "ig" if handle.startswith("@") else "fb"
    img = render_health_card(headline, source, date_str, platform=platform)
    return _send_image(img, "trendradar_health", src)


def _results_params(src):
    title = (src.get("title") or "Results").strip()
    date_str = (src.get("date") or "").strip()
    handle = (src.get("handle") or "fb.com/TrendRadarNG").strip()
    groups = src.get("groups")
    if isinstance(groups, str):
        try:
            groups = _json.loads(groups)
        except Exception:
            groups = []
    if not isinstance(groups, list):
        groups = []
    return title, groups, date_str, handle


@app.route("/results", methods=["GET", "POST"])
def results():
    src = _source(request)
    title, groups, date_str, handle = _results_params(src)
    if not groups:
        return Response('{"error":"groups is required"}', status=400,
                        mimetype="application/json")
    img = build_results_card(title, groups, date_str, handle)
    return _send_image(img, "trendradar_results", src)


def _peoples_voice_params(src):
    edition  = (src.get("edition_text") or "").strip()
    date_str = (src.get("date_text") or "").strip()
    question = (src.get("question") or "").strip() or None
    cta      = (src.get("cta_text") or "Drop Your Answer In The Comments").strip()
    return edition, date_str, question, cta


@app.route("/render/peoples-voice", methods=["GET", "POST"])
def peoples_voice():
    src = _source(request)
    edition, date_str, question, cta = _peoples_voice_params(src)
    if not edition or not date_str:
        return Response('{"error":"edition_text and date_text are required"}',
                        status=400, mimetype="application/json")
    img = render_peoples_voice(edition, date_str, question, cta_text=cta)
    return _send_image(img, "trendradar_peoples_voice", src)




# ---------------------------------------------------------------------------
# Generic IG hosting (added Jul 2026): POST any rendered card's binary here;
# get back hosted image_url (PNG) + image_url_jpg (JPEG) for lanes whose
# render routes return binary images (newsstand/weather, traffic, etc.).
# Same in-memory store pattern as COL/SYE; inherits single-worker constraint.
# ---------------------------------------------------------------------------
import time as _time
import uuid as _uuid
from flask import jsonify as _jsonify, url_for as _url_for
from PIL import Image as _PILImage

_HOSTED_STORE = {}
_HOSTED_TTL_SECONDS = 3600


def _gc_hosted():
    now = _time.time()
    for k in [k for k, (_, ts) in _HOSTED_STORE.items() if now - ts > _HOSTED_TTL_SECONDS]:
        _HOSTED_STORE.pop(k, None)


@app.post("/host")
def host_image():
    """Accepts a raw binary image body (the card PNG a workflow just rendered)
    and returns hosted URLs Meta can fetch."""
    _gc_hosted()
    data = request.get_data()
    if not data or len(data) < 100:
        return Response('{"error":"binary image body required"}', status=400,
                        mimetype="application/json")
    image_id = _uuid.uuid4().hex
    _HOSTED_STORE[image_id] = (data, _time.time())
    return _jsonify({
        "image_id": image_id,
        "image_url": _url_for("hosted_png", image_id=image_id, _external=True),
        "image_url_jpg": _url_for("hosted_jpg", image_id=image_id, _external=True),
    })


@app.get("/hosted/<image_id>.png")
def hosted_png(image_id):
    entry = _HOSTED_STORE.get(image_id)
    if not entry:
        return Response('{"error":"expired or unknown image id"}', status=404,
                        mimetype="application/json")
    return send_file(BytesIO(entry[0]), mimetype="image/png",
                     download_name=f"trng_hosted_{image_id}.png")


@app.get("/hosted/<image_id>.jpg")
def hosted_jpg(image_id):
    entry = _HOSTED_STORE.get(image_id)
    if not entry:
        return Response('{"error":"expired or unknown image id"}', status=404,
                        mimetype="application/json")
    img = _PILImage.open(BytesIO(entry[0])).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92)
    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg",
                     download_name=f"trng_hosted_{image_id}.jpg")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
