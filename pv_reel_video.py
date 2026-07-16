"""pv_reel_video.py — The People's Voice edition reel renderer (v1.0).

Async narrated promo-reel generator for the PV lane, built on the proven
story_video v2.0 architecture: disk-backed job store with heartbeat,
OOM-safe per-clip encode + stream-copy concat (no multi-input xfade),
pluggable TTS narration with graceful bed-only fallback, ducked audio bed,
single loudnorm pass to -14 LUFS, true-silence tail.

Branding: PV navy starfield, orbit mark, Poppins type, gold/white palette.

Routes (blueprint pv_reel_bp):
  POST /render/pvreel/start        -> {job_id}
  GET  /render/pvreel/status/<id>  -> {status: queued|rendering|done|error, ...}
  GET  /render/pvreel/media/<id>.mp4
  GET  /render/pvreel/health

Env (shared with the story lane so ONE voice signup powers both):
  STORY_TTS_PROVIDER = elevenlabs | google | off   (default off)
  ELEVENLABS_API_KEY, STORY_VOICE_ID, STORY_VOICE_RATE (google only)

Payload (all text fields pass the no-contraction gate, 422 on failure):
{
  "edition_label":  "THIRD EDITION",
  "hook_main":      "One credit alert at month end.",
  "hook_main_2":    "One dream that will not let you sleep.",
  "hook_accent":    "Every Nigerian knows this choice.",
  "context_main":   "...", "context_accent": "...",
  "side_one_title": "SIDE ONE — THE SALARY",
  "side_one_main":  "...", "side_one_main_2": "...",
  "side_one_counter_main": "...", "side_one_counter_accent": "...",
  "side_two_title": "SIDE TWO — THE HUSTLE",
  "side_two_main":  "...", "side_two_main_2": "...",
  "side_two_counter_main": "...", "side_two_counter_accent": "...",
  "third_way_main": "...", "third_way_accent": "...",
  "audience_main":  "...", "audience_accent": "...",
  "question_headline": "SALARY WORK OR PERSONAL HUSTLE?",
  "question_sub":   "Which one is the smarter path in Nigeria today?",
  "window_label":   "FRIDAY, 17 JULY — SUNDAY MIDNIGHT",
  "window_sub":     "Three days. One question. Every voice counts.",
  "cta_main":       "...", "cta_accent": "Real names are not required. Real experience is.",
  "narration":      {"s01": "...", ... "s13": "..."},   # optional; omit any/all
  "bed":            "bed_pv_groove",                     # optional, default first bed_pv*
  "bed_gain":       0.28                                 # optional
}
"""
import io, os, re, json, glob, time, uuid, threading, subprocess, math, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from flask import Blueprint, request, jsonify, send_file

pv_reel_bp = Blueprint("pv_reel", __name__)

# ---------------- constants ----------------
W, H = 720, 1280                    # OOM-proven output size (story v1.3 lesson)
SC = 1.10
BW, BH = int(W*SC), int(H*SC)       # 792 x 1408 scene stills
FPS = 30
FADE = 0.30                         # per-clip fade to black (concat-safe join)
MAX_TOTAL = 180.0                   # 3:00 hard cap (video post, not a 90s reel)
JOB_DIR = os.environ.get("PVREEL_JOB_DIR", "/tmp/pvreel_jobs")
os.makedirs(JOB_DIR, exist_ok=True)

NAVY_TOP = (10, 22, 48); NAVY_BOT = (16, 33, 66)
GOLD = (239, 173, 71); WHITE = (244, 246, 250); MUTE = (150, 168, 200)

REQUIRED = ["edition_label","hook_main","hook_main_2","hook_accent",
    "context_main","context_accent","side_one_title","side_one_main",
    "side_one_main_2","side_one_counter_main","side_one_counter_accent",
    "side_two_title","side_two_main","side_two_main_2","side_two_counter_main",
    "side_two_counter_accent","third_way_main","third_way_accent",
    "audience_main","audience_accent","question_headline","question_sub",
    "window_label","window_sub","cta_main","cta_accent"]

# ---------------- fonts (flat-repo loader: Poppins -> NotoSans -> DejaVu) ----
def _font_path(weight):
    cands = [f"Poppins-{weight}.ttf",
             os.path.join(os.path.dirname(os.path.abspath(__file__)), f"Poppins-{weight}.ttf"),
             "NotoSans-Bold.ttf" if weight in ("Bold","ExtraBold","SemiBold") else "NotoSans-Regular.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
             if weight in ("Bold","ExtraBold","SemiBold") else
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for c in cands:
        if os.path.exists(c): return c
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def FONT(weight, size): return ImageFont.truetype(_font_path(weight), size)
def fonts_ok(): return os.path.exists(_font_path("ExtraBold")) and "Poppins" in _font_path("ExtraBold")

# ---------------- contraction gate (house rule, possessives pass) ----------
_CONTR = re.compile(r"\b\w+[’'](?:t|re|ve|ll|d|m)\b|\b(?:can[’']t|won[’']t|don[’']t|isn[’']t|aren[’']t|it[’']s|let[’']s)\b", re.I)
def contraction_hits(payload):
    hits = []
    for k, v in payload.items():
        if isinstance(v, str) and _CONTR.search(v): hits.append(k)
        if isinstance(v, dict):
            for kk, vv in v.items():
                if isinstance(vv, str) and _CONTR.search(vv): hits.append(f"{k}.{kk}")
    return hits

# ---------------- scene assembly ----------------
def _starfield(seed=17):
    rng = random.Random(seed)
    g = np.zeros((BH, BW, 3), np.uint8)
    top, bot = np.array(NAVY_TOP), np.array(NAVY_BOT)
    for y in range(BH):
        g[y, :] = (top + (bot-top)*(y/BH)).astype(np.uint8)
    im = Image.fromarray(g); d = ImageDraw.Draw(im)
    for _ in range(230):
        x, y = rng.randint(0, BW-1), rng.randint(0, BH-1)
        r = rng.choice([1,1,1,2]); a = rng.randint(70, 200)
        c = tuple(min(255, NAVY_BOT[i]+a) for i in range(3))
        d.ellipse([x-r, y-r, x+r, y+r], fill=c)
    return im
_BG = None
def BG():
    global _BG
    if _BG is None: _BG = _starfield()
    return _BG

def _orbit(d, cx, cy, s=0.72):
    for rr, col in [(120,(70,96,140)), (78,(96,124,170))]:
        r = rr*s; d.ellipse([cx-r,cy-r,cx+r,cy+r], outline=col, width=2)
    r = 34*s; d.ellipse([cx-r,cy-r,cx+r,cy+r], outline=WHITE, width=3)
    r = 12*s; d.ellipse([cx-r,cy-r,cx+r,cy+r], fill=GOLD)

def _wrap(dr, text, font, maxw):
    out, line = [], ""
    for w in text.split():
        t = (line+" "+w).strip()
        if dr.textlength(t, font=font) <= maxw: line = t
        else:
            out.append(line); line = w
    if line: out.append(line)
    return out

def _spaced(dr, cx, y, text, font, fill, tr):
    tot = sum(dr.textlength(c, font=font) for c in text) + tr*(len(text)-1)
    x = cx - tot/2
    for c in text:
        dr.text((x, y), c, font=font, fill=fill)
        x += dr.textlength(c, font=font) + tr

def render_scene(items):
    """items: list of (kind, text). kinds: mark, eyebrow, big, main, accent, pill, foot, gap"""
    im = BG().copy(); dr = ImageDraw.Draw(im); cx = BW//2
    FS = {"eyebrow": FONT("SemiBold", 24), "big": FONT("ExtraBold", 66),
          "main": FONT("SemiBold", 42), "accent": FONT("SemiBold", 42),
          "pill": FONT("SemiBold", 30), "foot": FONT("Medium", 25)}
    LH = {"big": 82, "main": 60, "accent": 60, "pill": 44, "foot": 36, "eyebrow": 40}
    maxw = BW - 170
    rows = []
    for kind, text in items:
        if kind == "gap": rows.append(("gap", None, text)); continue
        if kind == "mark": rows.append(("mark", None, 200)); continue
        ls = [text] if kind == "eyebrow" else _wrap(dr, text, FS[kind], maxw)
        rows.append((kind, ls, LH[kind]*len(ls) + (12 if kind == "eyebrow" else 0)))
    y = (BH - sum(r[2] for r in rows))//2
    for kind, ls, hh in rows:
        if kind == "gap": y += hh; continue
        if kind == "mark": _orbit(dr, cx, y+100); y += hh; continue
        f = FS[kind]
        col = {"eyebrow": GOLD, "big": GOLD, "main": WHITE,
               "accent": GOLD, "pill": GOLD, "foot": MUTE}[kind]
        if kind == "eyebrow":
            _spaced(dr, cx, y, ls[0], f, col, 5); y += hh; continue
        if kind == "pill":
            lw = max(dr.textlength(l, font=f) for l in ls)
            bh = LH["pill"]*len(ls)
            dr.rounded_rectangle([cx-lw/2-38, y-18, cx+lw/2+38, y+bh+12],
                                 radius=(bh+30)//2 if len(ls) == 1 else 30,
                                 outline=GOLD, width=2)
        for l in ls:
            dr.text((cx - dr.textlength(l, font=f)/2, y), l, font=f, fill=col)
            y += LH[kind]
    return im

def build_scenes(p):
    """Returns list of (scene_key, items, default_narration_text)."""
    tagline = "Your Voice. Your News. Your Nigeria."
    s = []
    s.append(("s01", [("mark",0),("gap",50),("eyebrow","THE PEOPLE'S VOICE"),("gap",18),
                      ("big", p["edition_label"]),("gap",26),("foot", tagline)],
              f"The People's Voice. {p['edition_label'].title()}."))
    s.append(("s02", [("main",p["hook_main"]),("gap",20),("main",p["hook_main_2"]),
                      ("gap",30),("accent",p["hook_accent"])],
              f"{p['hook_main']} {p['hook_main_2']} {p['hook_accent']}"))
    s.append(("s03", [("main",p["context_main"]),("gap",30),("accent",p["context_accent"])],
              f"{p['context_main']} {p['context_accent']}"))
    s.append(("s04", [("eyebrow",p["side_one_title"]),("gap",28),("main",p["side_one_main"]),
                      ("gap",20),("main",p["side_one_main_2"])],
              f"{p['side_one_title'].title()}. {p['side_one_main']} {p['side_one_main_2']}"))
    s.append(("s05", [("main",p["side_one_counter_main"]),("gap",30),
                      ("accent",p["side_one_counter_accent"])],
              f"{p['side_one_counter_main']} {p['side_one_counter_accent']}"))
    s.append(("s06", [("eyebrow",p["side_two_title"]),("gap",28),("main",p["side_two_main"]),
                      ("gap",20),("main",p["side_two_main_2"])],
              f"{p['side_two_title'].title()}. {p['side_two_main']} {p['side_two_main_2']}"))
    s.append(("s07", [("main",p["side_two_counter_main"]),("gap",30),
                      ("accent",p["side_two_counter_accent"])],
              f"{p['side_two_counter_main']} {p['side_two_counter_accent']}"))
    s.append(("s08", [("main",p["third_way_main"]),("gap",30),("accent",p["third_way_accent"])],
              f"{p['third_way_main']} {p['third_way_accent']}"))
    s.append(("s09", [("main",p["audience_main"]),("gap",30),("accent",p["audience_accent"])],
              f"{p['audience_main']} {p['audience_accent']}"))
    s.append(("s10", [("eyebrow","THIS WEEKEND WE ASK"),("gap",32),
                      ("big",p["question_headline"]),("gap",32),("main",p["question_sub"])],
              f"This weekend, we ask you directly. {p['question_headline'].title()} {p['question_sub']}"))
    s.append(("s11", [("eyebrow","THE FLOOR IS OPENING"),("gap",36),
                      ("pill",p["window_label"]),("gap",42),("main",p["window_sub"])],
              f"The floor opens {p['window_label'].title()}. {p['window_sub']}"))
    s.append(("s12", [("main",p["cta_main"]),("gap",30),("accent",p["cta_accent"])],
              f"{p['cta_main']} {p['cta_accent']}"))
    s.append(("s13", [("mark",0),("gap",50),("eyebrow","THE PEOPLE'S VOICE"),("gap",22),
                      ("main", tagline),("gap",28),
                      ("foot","Follow TREND RADAR NG  ·  fb.com/TrendRadarNG")],
              "The People's Voice. Your Voice. Your News. Your Nigeria. Follow Trend Radar N G."))
    return s

# ---------------- TTS (shared env with story lane; graceful fallback) -------
def tts_provider(): return os.environ.get("STORY_TTS_PROVIDER", "off").lower()

def tts_scene(text, out_mp3):
    """Returns (ok, error_detail)."""
    prov = tts_provider()
    try:
        if prov == "elevenlabs":
            import urllib.request
            vid = os.environ.get("STORY_VOICE_ID", "").split(",")[0].strip()
            key = os.environ.get("ELEVENLABS_API_KEY", "")
            if not (vid and key): return False
            req = urllib.request.Request(
                f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
                data=json.dumps({"text": text, "model_id": "eleven_multilingual_v2",
                                 "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}).encode(),
                headers={"xi-api-key": key, "Content-Type": "application/json",
                         "Accept": "audio/mpeg"})
            with urllib.request.urlopen(req, timeout=60) as r:
                open(out_mp3, "wb").write(r.read())
            return (os.path.getsize(out_mp3) > 1000, "")
        if prov == "google":
            import urllib.request, base64
            key = os.environ.get("GOOGLE_TTS_API_KEY", "")
            if not key: return False
            body = {"input": {"text": text},
                    "voice": {"languageCode": "en-NG",
                              "name": (os.environ.get("STORY_VOICE_ID", "en-NG-Standard-A").split(",")[0].strip() or "en-NG-Standard-A")},
                    "audioConfig": {"audioEncoding": "MP3",
                                    "speakingRate": float(os.environ.get("STORY_VOICE_RATE", "0.97"))}}
            req = urllib.request.Request(
                f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}",
                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                audio = json.loads(r.read())["audioContent"]
            open(out_mp3, "wb").write(base64.b64decode(audio))
            return (os.path.getsize(out_mp3) > 1000, "")
    except Exception as e:
        body = ""
        try: body = e.read().decode()[:200]
        except Exception: pass
        return (False, f"{type(e).__name__}: {str(e)[:150]} {body}".strip())
    return (False, f"provider {prov} not configured (missing key or voice id)")

def media_dur(path):
    try:
        out = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                              "-of","csv=p=0", path], capture_output=True, text=True)
        return float(out.stdout.strip())
    except Exception:
        return 0.0

def ffmpeg_bin():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

# ---------------- beds ----------------
def list_beds():
    pats = ["audio/bed_pv*.mp3", "bed_pv*.mp3", "audio/bed_*.mp3"]
    for p in pats:
        got = sorted(glob.glob(p))
        if got: return got
    return []

# ---------------- job store (disk-backed, heartbeat) ----------------
def _jpath(jid): return os.path.join(JOB_DIR, f"{jid}.json")
def _jset(jid, **kw):
    st = _jget(jid) or {}
    st.update(kw); st["heartbeat"] = time.time()
    with open(_jpath(jid), "w") as f: json.dump(st, f)
def _jget(jid):
    try: return json.load(open(_jpath(jid)))
    except Exception: return None

# ---------------- render pipeline ----------------
def do_render(jid, p):
    FF = ffmpeg_bin()
    work = os.path.join(JOB_DIR, jid); os.makedirs(work, exist_ok=True)
    try:
        _jset(jid, status="rendering", step="scenes")
        scenes = build_scenes(p)
        narr_in = p.get("narration") or {}
        prov_on = tts_provider() in ("elevenlabs", "google")

        # narration first (durations may depend on it)
        narr_files, narrated = {}, False
        if prov_on:
            _jset(jid, step="narration")
            for key, _items, default_text in scenes:
                text = str(narr_in.get(key) or default_text)
                mp3 = os.path.join(work, f"{key}.mp3")
                ok, err = tts_scene(text, mp3)
                if ok and media_dur(mp3) > 0.3:
                    narr_files[key] = mp3; narrated = True
                else:
                    # STRICT: narration is configured, so a voice failure fails the job
                    # loudly instead of silently publishing a voiceless reel.
                    _jset(jid, status="error",
                          error=f"narration failed on {key}: {err or 'empty audio'}")
                    return

        # scene durations
        durs = {}
        for key, items, default_text in scenes:
            words = sum(len(t.split()) for k, t in items if k not in ("gap", "mark"))
            read = max(6.0, min(16.0, 2.4 + 0.42*words))       # validated reading-speed pacing
            if narrated:
                pad = 1.4
                durs[key] = max(5.0, min(18.0, media_dur(narr_files[key]) + pad))
            else:
                durs[key] = read
        total = sum(durs.values())
        if total > MAX_TOTAL and narrated:                      # squeeze pads, then fail readable
            over = total - MAX_TOTAL
            squeeze = min(0.9, over/len(durs))
            durs = {k: max(4.5, v - squeeze) for k, v in durs.items()}
            total = sum(durs.values())
        if total > MAX_TOTAL:
            _jset(jid, status="error", error=f"total {total:.0f}s exceeds {MAX_TOTAL:.0f}s cap"); return

        # per-scene clips (OOM-safe: one input, fade-to-black, later stream-copy concat)
        _jset(jid, step="clips", total_s=round(total, 1), narrated=narrated)
        concat_lines = []
        for i, (key, items, _t) in enumerate(scenes):
            png = os.path.join(work, f"{key}.png")
            render_scene(items).save(png)
            d = durs[key]; n = max(2, round(d*FPS))
            fin = 0.6 if i == 0 else FADE
            fout = 0.8 if i == len(scenes)-1 else FADE
            vf = (f"scale={BW}:{BH},zoompan=z='1+0.055*on/{n-1}':"
                  f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d={n}:s={W}x{H}:fps={FPS},"
                  f"format=yuv420p,fade=t=in:st=0:d={fin},fade=t=out:st={d-fout:.3f}:d={fout}")
            seg = os.path.join(work, f"{key}.mp4")
            r = subprocess.run([FF, "-nostdin", "-y", "-loglevel", "error", "-i", png,
                                "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
                                "-threads", "1", "-crf", "21", "-g", "60", "-r", str(FPS), seg],
                               capture_output=True, text=True)
            if r.returncode != 0:
                _jset(jid, status="error", error=f"clip {key}: {r.stderr[-300:]}"); return
            concat_lines.append(f"file '{seg}'")
            _jset(jid, step=f"clips {i+1}/{len(scenes)}")
        cat = os.path.join(work, "concat.txt"); open(cat, "w").write("\n".join(concat_lines))
        vid = os.path.join(work, "video.mp4")
        r = subprocess.run([FF, "-nostdin", "-y", "-loglevel", "error", "-f", "concat",
                            "-safe", "0", "-i", cat, "-c", "copy", vid],
                           capture_output=True, text=True)
        if r.returncode != 0:
            _jset(jid, status="error", error=f"concat: {r.stderr[-300:]}"); return

        # audio: bed loop/trim (+ narration placed at scene starts, bed ducked)
        _jset(jid, step="audio")
        beds = list_beds()
        want = p.get("bed")
        bed = next((b for b in beds if want and want in b), beds[0] if beds else None)
        bed_gain = float(p.get("bed_gain", 0.28))
        duck = 0.32                                             # bed multiplier under voice
        out = os.path.join(work, "final.mp4")
        if narrated:
            starts, t0 = {}, 0.0
            for key, _i, _t in scenes:
                starts[key] = t0; t0 += durs[key]
            inputs = [FF, "-nostdin", "-y", "-loglevel", "error", "-i", vid]
            fl, amix = [], []
            if bed:
                inputs += ["-stream_loop", "-1", "-i", bed]
                fl.append(f"[1:a]atrim=0:{total:.3f},volume={bed_gain*duck:.3f}[bed]")
                amix.append("[bed]")
            for k, key in enumerate(scenes):
                key = key[0]
                inputs += ["-i", narr_files[key]]
                idx = (2 if bed else 1) + k
                fl.append(f"[{idx}:a]adelay={int(starts[key]*1000+700)}|{int(starts[key]*1000+700)}[n{k}]")
                amix.append(f"[n{k}]")
            fl.append(f"{''.join(amix)}amix=inputs={len(amix)}:normalize=0,"
                      f"afade=t=out:st={total-1.6:.3f}:d=1.4,loudnorm=I=-14:TP=-1.5[a]")
            cmd = inputs + ["-filter_complex", ";".join(fl), "-map", "0:v", "-map", "[a]",
                            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                            "-t", f"{total:.3f}", "-movflags", "+faststart", out]
        elif bed:
            cmd = [FF, "-nostdin", "-y", "-loglevel", "error", "-i", vid,
                   "-stream_loop", "-1", "-i", bed, "-filter_complex",
                   f"[1:a]atrim=0:{total:.3f},volume={bed_gain:.3f},"
                   f"afade=t=out:st={total-2.2:.3f}:d=2.0,loudnorm=I=-16:TP=-1.5[a]",
                   "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                   "-t", f"{total:.3f}", "-movflags", "+faststart", out]
        else:
            cmd = [FF, "-nostdin", "-y", "-loglevel", "error", "-i", vid, "-c", "copy", out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            _jset(jid, status="error", error=f"audio: {r.stderr[-300:]}"); return
        _jset(jid, status="done", media=out, duration_s=round(media_dur(out), 1),
              narrated=narrated, bed=os.path.basename(bed) if bed else None)
    except Exception as e:
        _jset(jid, status="error", error=str(e)[:300])

# ---------------- routes ----------------
@pv_reel_bp.route("/render/pvreel/start", methods=["POST"])
def pvreel_start():
    p = request.get_json(silent=True) or {}
    missing = [k for k in REQUIRED if not str(p.get(k, "")).strip()]
    if missing:
        return jsonify({"error": "missing fields", "fields": missing}), 422
    hits = contraction_hits(p)
    if hits:
        return jsonify({"error": "contractions found — expand all", "fields": hits}), 422
    jid = uuid.uuid4().hex[:12]
    _jset(jid, status="queued", created=time.time())
    threading.Thread(target=do_render, args=(jid, p), daemon=True).start()
    return jsonify({"job_id": jid, "status": "queued",
                    "narration": tts_provider(), "beds": [os.path.basename(b) for b in list_beds()]})

@pv_reel_bp.route("/render/pvreel/status/<jid>")
def pvreel_status(jid):
    st = _jget(jid)
    if not st:
        return jsonify({"status": "error", "error": "unknown job"}), 404
    if st.get("status") == "rendering" and time.time() - st.get("heartbeat", 0) > 120:
        st["status"] = "error"; st["error"] = "render worker restarted mid-job"
    pub = {k: v for k, v in st.items() if k != "media"}
    return jsonify(pub)

@pv_reel_bp.route("/render/pvreel/media/<jid>.mp4")
def pvreel_media(jid):
    st = _jget(jid)
    if not st or st.get("status") != "done":
        return jsonify({"error": "not ready"}), 404
    return send_file(st["media"], mimetype="video/mp4")

@pv_reel_bp.route("/render/pvreel/health")
def pvreel_health():
    beds = [os.path.basename(b) for b in list_beds()]
    ok = bool(beds) and fonts_ok()
    voice_raw = os.environ.get("STORY_VOICE_ID", "")
    out = {"status": "ok" if ok else "degraded",
           "beds": beds, "poppins": fonts_ok(),
           "narration": {"provider": tts_provider(),
                         "voice_in_use": voice_raw.split(",")[0].strip(),
                         "extra_ids_ignored": max(0, len([v for v in voice_raw.split(",") if v.strip()]) - 1)},
           "ffmpeg": os.path.basename(ffmpeg_bin())}
    if request.args.get("probe") and tts_provider() in ("elevenlabs", "google"):
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), "pvreel_probe.mp3")
        pok, perr = tts_scene("Testing the People's Voice narrator.", tmp)
        out["tts_probe"] = {"ok": bool(pok), "error": perr or None,
                            "audio_seconds": round(media_dur(tmp), 2) if pok else 0}
        if not pok: out["status"] = "degraded"
    return jsonify(out)
