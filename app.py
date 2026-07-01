"""
Trend Radar NG - Headline Card Render Service
GET  /            health check
GET/POST /card        news card (binary PNG)
GET/POST /wisdom      wisdom-lane card (binary PNG)
GET/POST /reflection  reflection-lane card (binary PNG)
"""

from flask import Flask, request, send_file, Response
from io import BytesIO
from datetime import datetime
import json as _json
import os

from trend_radar_card import build_card, build_wisdom_card, build_reflection_card

app = Flask(__name__)

MAX_HEADLINE = 240
ALLOWED = {"POLITICS", "ENTERTAINMENT", "EPL", "FOOTBALL", "ECONOMY", "GOSPEL", "DIASPORA", "TECH"}


def _source(req):
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
    proverb = (src.get("proverb_original") or src.get("proverb") or "").strip()
    meaning = (src.get("meaning") or "").strip()
    language = (src.get("language") or "").strip()
    date_str = (src.get("date") or "").strip()
    handle = (src.get("handle") or "fb.com/TrendRadarNG").strip()
    return proverb, meaning, language, date_str, handle


def _reflection_params(src):
    theme = (src.get("theme_title") or "").strip()
    quote = (src.get("pull_quote") or "").strip()
    date_str = (src.get("date") or "").strip()
    handle = (src.get("handle") or "fb.com/TrendRadarNG").strip()
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
    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name="trendradar_card.png")


@app.route("/wisdom", methods=["GET", "POST"])
def wisdom():
    src = _source(request)
    proverb, meaning, language, date_str, handle = _wisdom_params(src)
    if not proverb:
        return Response('{"error":"proverb_original is required"}', status=400,
                        mimetype="application/json")
    img = build_wisdom_card(proverb, meaning, language, date_str, handle)
    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name="trendradar_wisdom.png")


@app.route("/reflection", methods=["GET", "POST"])
def reflection():
    src = _source(request)
    theme, quote, date_str, handle = _reflection_params(src)
    if not quote:
        return Response('{"error":"pull_quote is required"}', status=400,
                        mimetype="application/json")
    img = build_reflection_card(theme, quote, date_str, handle)
    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name="trendradar_reflection.png")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
