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
POST /col/render       -> Cost of Living lane card (JSON: hosted image_url PNG + image_url_jpg)
GET  /col/image/<id>.png / .jpg -> serves a rendered COL card (1-hour TTL)
POST /scam/render      -> Shine Your Eye scam-alert card (JSON: hosted image_url PNG + image_url_jpg)
GET  /scam/image/<id>.png / .jpg -> serves a rendered Shine Your Eye card (1-hour TTL)

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
app.register_blueprint(newsstand_bp)
app.register_blueprint(traffic_bp)
app.register_blueprint(wahala_bp)
app.register_blueprint(jakpa_bp)
app.register_blueprint(col_bp)
app.register_blueprint(scam_bp)

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
