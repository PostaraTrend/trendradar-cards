<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>app.py</title>
<style>
:root{color-scheme:dark;}*{box-sizing:border-box;}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0a1428;color:#eef6ff;padding:16px;}
.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px;flex-wrap:wrap;}
.title{font-weight:600;font-size:15px;}.title small{color:#9ab0cb;font-weight:400;display:block;font-size:12px;margin-top:2px;}
button{background:#18e0a0;color:#0a1428;border:0;border-radius:10px;padding:11px 18px;font-size:14px;font-weight:700;cursor:pointer;}
button:hover{opacity:.85;}button.done{background:#18e0a0;}
textarea{width:100%;height:58vh;min-height:300px;resize:vertical;background:#0c2038;color:#cfe3ff;border:1px solid #1d4660;border-radius:12px;padding:12px;font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:12px;line-height:1.5;white-space:pre;overflow:auto;tab-size:4;}
.hint{color:#9ab0cb;font-size:12px;margin-top:8px;}
</style></head><body>
<div class="bar"><div class="title">app.py (file 1 of 2)<small>The Flask service. Routes + ALLOWED set with TECH.</small></div>
<button id="b" onclick="c()">Copy file</button></div>
<textarea id="t" readonly spellcheck="false">&quot;&quot;&quot;
Trend Radar NG — Headline Card Render Service
=============================================
GET  /            -&gt; health check (&quot;ok&quot;)
GET/POST /card        -&gt; news card (binary PNG)
GET/POST /wisdom      -&gt; wisdom-lane card (binary PNG)
GET/POST /reflection  -&gt; reflection-lane card (binary PNG)
&quot;&quot;&quot;

from flask import Flask, request, send_file, Response
from io import BytesIO
from datetime import datetime
import json as _json
import os

from trend_radar_card import build_card, build_wisdom_card, build_reflection_card

app = Flask(__name__)

MAX_HEADLINE = 240
ALLOWED = {&quot;POLITICS&quot;, &quot;ENTERTAINMENT&quot;, &quot;EPL&quot;, &quot;FOOTBALL&quot;, &quot;ECONOMY&quot;, &quot;GOSPEL&quot;, &quot;DIASPORA&quot;, &quot;TECH&quot;}


def _source(req):
    &quot;&quot;&quot;Return a dict of params from JSON body, raw JSON string, or form values.
    n8n sometimes posts a body that Flask does not auto-parse into a dict, so we
    parse defensively and always hand back something with .get().&quot;&quot;&quot;
    data = req.get_json(silent=True)
    if isinstance(data, dict):
        return data
    raw = req.get_data(as_text=True) or &quot;&quot;
    if raw.strip():
        try:
            parsed = _json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return req.values


def _params(src):
    headline = (src.get(&quot;headline&quot;) or &quot;&quot;).strip()[:MAX_HEADLINE]
    source = (src.get(&quot;source&quot;) or &quot;&quot;).strip() or &quot;the source&quot;
    category = (src.get(&quot;category&quot;) or &quot;POLITICS&quot;).strip().upper()
    if category not in ALLOWED:
        category = &quot;POLITICS&quot;
    date_str = (src.get(&quot;date&quot;) or &quot;&quot;).strip() or datetime.now().strftime(&quot;%-d %b %Y&quot;)
    handle = (src.get(&quot;handle&quot;) or &quot;fb.com/TrendRadarNG&quot;).strip()
    return headline, source, category, date_str, handle


def _wisdom_params(src):
    proverb  = (src.get(&quot;proverb_original&quot;) or src.get(&quot;proverb&quot;) or &quot;&quot;).strip()
    meaning  = (src.get(&quot;meaning&quot;) or &quot;&quot;).strip()
    language = (src.get(&quot;language&quot;) or &quot;&quot;).strip()
    date_str = (src.get(&quot;date&quot;) or &quot;&quot;).strip()
    handle   = (src.get(&quot;handle&quot;) or &quot;fb.com/TrendRadarNG&quot;).strip()
    return proverb, meaning, language, date_str, handle


def _reflection_params(src):
    theme    = (src.get(&quot;theme_title&quot;) or &quot;&quot;).strip()
    quote    = (src.get(&quot;pull_quote&quot;) or &quot;&quot;).strip()
    date_str = (src.get(&quot;date&quot;) or &quot;&quot;).strip()
    handle   = (src.get(&quot;handle&quot;) or &quot;fb.com/TrendRadarNG&quot;).strip()
    return theme, quote, date_str, handle


@app.get(&quot;/&quot;)
def health():
    return &quot;ok&quot;, 200


@app.route(&quot;/card&quot;, methods=[&quot;GET&quot;, &quot;POST&quot;])
def card():
    src = _source(request)
    headline, source, category, date_str, handle = _params(src)
    if not headline:
        return Response(&#x27;{&quot;error&quot;:&quot;headline is required&quot;}&#x27;, status=400,
                        mimetype=&quot;application/json&quot;)
    img = build_card(headline, source, category, date_str, handle)
    buf = BytesIO()
    img.save(buf, &quot;PNG&quot;, optimize=True)
    buf.seek(0)
    return send_file(buf, mimetype=&quot;image/png&quot;,
                     download_name=&quot;trendradar_card.png&quot;)


@app.route(&quot;/wisdom&quot;, methods=[&quot;GET&quot;, &quot;POST&quot;])
def wisdom():
    src = _source(request)
    proverb, meaning, language, date_str, handle = _wisdom_params(src)
    if not proverb:
        return Response(&#x27;{&quot;error&quot;:&quot;proverb_original is required&quot;}&#x27;, status=400,
                        mimetype=&quot;application/json&quot;)
    img = build_wisdom_card(proverb, meaning, language, date_str, handle)
    buf = BytesIO()
    img.save(buf, &quot;PNG&quot;, optimize=True)
    buf.seek(0)
    return send_file(buf, mimetype=&quot;image/png&quot;,
                     download_name=&quot;trendradar_wisdom.png&quot;)


@app.route(&quot;/reflection&quot;, methods=[&quot;GET&quot;, &quot;POST&quot;])
def reflection():
    src = _source(request)
    theme, quote, date_str, handle = _reflection_params(src)
    if not quote:
        return Response(&#x27;{&quot;error&quot;:&quot;pull_quote is required&quot;}&#x27;, status=400,
                        mimetype=&quot;application/json&quot;)
    img = build_reflection_card(theme, quote, date_str, handle)
    buf = BytesIO()
    img.save(buf, &quot;PNG&quot;, optimize=True)
    buf.seek(0)
    return send_file(buf, mimetype=&quot;image/png&quot;,
                     download_name=&quot;trendradar_reflection.png&quot;)


if __name__ == &quot;__main__&quot;:
    app.run(host=&quot;0.0.0.0&quot;, port=int(os.environ.get(&quot;PORT&quot;, 8000)))
</textarea>
<div class="hint">GitHub: open app.py, pencil, select all (Ctrl+A), delete, paste, commit to main.</div>
<script>
function c(){var t=document.getElementById('t'),b=document.getElementById('b');t.focus();t.select();t.setSelectionRange(0,t.value.length);
function k(){b.textContent='Copied \u2713';b.classList.add('done');setTimeout(function(){b.textContent='Copy file';b.classList.remove('done');},2000);}
try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t.value).then(k,function(){document.execCommand('copy');k();});}else{document.execCommand('copy');k();}}catch(e){document.execCommand('copy');k();}}
</script></body></html>
