"""
Trend Radar NG — Headline Card Render Service
=============================================
Tiny web service that turns a headline into an on-brand PNG card.

Endpoints
---------
GET  /            -> health check ("ok")
GET  /card        -> render a card, returns image/png
POST /card        -> same, accepts JSON body

Query params / JSON keys (all optional except headline):
  headline   (required)  the article title  -> selector's selected_title
  source     (required)  outlet name        -> e.g. "Premium Times"
  category               POLITICS | ENTERTAINMENT | EPL | ECONOMY | GOSPEL  (default POLITICS)
  date                   e.g. "26 Jun 2026"  (default: today, server TZ)
  handle                 footer handle       (default fb.com/TrendRadarNG)

Examples
--------
  /card?headline=Naira+firms+against+the+dollar&source=Nairametrics&category=ECONOMY

n8n usage (recommended, robust against cold starts):
  1) HTTP Request node -> GET this /card URL with the params -> response = binary PNG
  2) Facebook publish  -> POST /{page-id}/photos  (multipart: source=<binary>,
     caption=<commentary>, published=true, access_token=<PAGE token>)
"""

from flask import Flask, request, send_file, Response
from io import BytesIO
from datetime import datetime
import os

from trend_radar_card import build_card, build_wisdom_card

app = Flask(__name__)

MAX_HEADLINE = 240          # guardrail
ALLOWED = {"POLITICS", "ENTERTAINMENT", "EPL", "FOOTBALL", "ECONOMY", "GOSPEL", "DIASPORA"}


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


@app.get("/")
def health():
    return "ok", 200


@app.route("/card", methods=["GET", "POST"])
def card():
    src = request.get_json(silent=True) or request.values
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
    src = request.get_json(silent=True) or request.values
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



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
