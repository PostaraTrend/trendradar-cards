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
POST /promo            -> Level Up promo-lane card, Project Harvest (binary JPEG)
POST /host             -> host any rendered card binary; returns image_url + image_url_jpg (1-hour TTL)
GET  /hosted/<id>.png / .jpg -> serves a hosted card (generic, any lane; IG uses the .jpg)
POST /naijalens/render -> Naija Lens photo card (JSON: image_url; photo treatment
                          with quality gate, enhancement pass, hook + credit overlay)

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
app.register_blueprint(newsstand_bp)
app.register_blueprint(traffic_bp)
app.register_blueprint(wahala_bp)
app.register_blueprint(jakpa_bp)
app.register_blueprint(col_bp)
app.register_blueprint(scam_bp)
app.re
