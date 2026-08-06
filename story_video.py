"""
Story Video Renderer — /render/story
Animated storytelling Reels (1080x1920 MP4, H.264 + AAC), shared by every story
lane on this service.

BRANDS: the payload may carry "brand" (trng | postara). The brand sets the
palette, masthead, tagline, sign-off hashtag and the kicker/CTA fallbacks, so
the Nigerian lanes and the Canadian PostaraTrend lane render from one module
without leaking each other's identity. No brand -> trng, which is exactly the
palette this module carried before brands existed. Payload masthead, tagline,
hashtag, kicker and cta still override the brand one string at a time.

VOICE: the payload may carry "voice" (an ElevenLabs id, or a comma-separated
pool). It overrides the STORY_VOICE_ID env var for that render only, so one
lane can change narrator without changing it for every other lane.

Pipeline: scene JSON -> Pillow frames (house style) -> ffmpeg Ken Burns +
crossfades -> audio bed (loudness normalized, faded) -> MP4 served from /tmp.

Async job pattern (single gunicorn worker safe):
  POST /render/story/start          -> {"job_id": "..."}          (returns fast)
  GET  /render/story/status/<id>    -> {"status": "rendering|done|error", "video_url": ...}
  GET  /render/story/media/<id>.mp4 -> the finished video (Meta pulls from here)
  GET  /render/story/health         -> {"status": "ok", ...}

Audio beds live in the repo at audio/bed_<mood>.mp3 (Pixabay tracks committed
alongside their license text). Missing bed -> 422 with the expected path.

Requires: pillow, imageio-ffmpeg (add imageio-ffmpeg to requirements.txt).
"""

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from flask import Blueprint, jsonify, request, send_file
from PIL import Image, ImageDraw, ImageFont

story_bp = Blueprint("story", __name__)

# ---------------------------------------------------------------- constants
OUT_W, OUT_H = 720, 1280             # Reel spec (>=720p, 9:16); 720p keeps x264 inside the 512MB instance
FRAME_W, FRAME_H = 1242, 2208        # 15% oversize for Ken Burns headroom
FPS = 30
XFADE = 0.7                          # crossfade seconds between scenes
MIN_TOTAL, MAX_TOTAL = 15, 90        # publishing rule: reels 15-90s
MAX_SCENES = 10

INK = (16, 19, 24)
INK_LIFT = (26, 30, 38)
GOLD = (240, 180, 41)
GOLD_DIM = (240, 180, 41, 90)
CREAM = (244, 239, 228)
GREY = (168, 172, 180)

# picture-led background (opt-in via payload "bg_image"). Absent -> frames render
# exactly as before. Present -> the photo is cover-fit, mildly desaturated for
# series cohesion, and darkened so the cream body text stays legible.
BG_SCRIM = 0.32       # global black overlay strength over the photo (higher = darker)
BG_DESAT = 0.08       # blend toward greyscale for cohesion (0 = keep full colour)
BG_EDGE_SCRIM = 120   # extra top/bottom darkening 0-255 to seat masthead + footer
BG_TEXT_PLATE = 168   # localised darkening 0-255 behind lower-third body text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
JOB_DIR = os.path.join(tempfile.gettempdir(), "trng_story_jobs")
JOB_TTL = 2 * 60 * 60                # keep finished jobs 2h
os.makedirs(JOB_DIR, exist_ok=True)

JOBS = {}                            # job_id -> dict (single worker: safe)
JOBS_LOCK = threading.Lock()
HEARTBEAT_STALE = 240                # rendering + no heartbeat for this long = worker died


def _status_path(job_id):
    return os.path.join(JOB_DIR, f"{job_id}.status.json")


def _write_status(job_id, **fields):
    """Persist job state to /tmp so a worker restart cannot orphan the job into a 404.
    The file's mtime doubles as the render heartbeat."""
    try:
        with open(_status_path(job_id), "w") as f:
            json.dump(fields, f)
    except OSError:
        pass


def _read_status(job_id):
    try:
        with open(_status_path(job_id)) as f:
            data = json.load(f)
        data["_age"] = time.time() - os.path.getmtime(_status_path(job_id))
        return data
    except (OSError, ValueError):
        return None

MASTHEAD = "TREND RADAR NG  •  HERITAGE STORIES"
TAGLINE = "Stories of Naija. Told with pride."

# ---------------------------------------------------------------- brands
# A lane's identity lives here: colours, masthead, tagline, sign-off hashtag and
# the kicker/CTA fallbacks. A payload with no "brand" resolves to trng, so every
# caller that existed before this table renders byte-identically to before.
BRANDS = {
    "trng": {
        "ink": INK, "ink_lift": INK_LIFT, "accent": GOLD,
        "body": CREAM, "muted": GREY,
        "masthead": MASTHEAD, "tagline": TAGLINE,
        "hashtag": "#TrendRadarNG",
        "kicker": "NIGERIAN FOLKTALE",
        "cta": "Follow Trend Radar NG for more stories.",
    },
    "postara": {
        "ink": (17, 43, 84),            # #112B54 site navy
        "ink_lift": (26, 58, 107),      # #1A3A6B
        "accent": (93, 202, 165),       # #5DCAA5 site green, 7.0:1 on the navy
        "body": (234, 241, 247),        # #EAF1F7 cool white
        "muted": GREY,
        "masthead": "POSTARATREND  •  FIRST NATIONS HERITAGE",
        "tagline": "Stories of this land. Told with respect.",
        "hashtag": "#PostaraTrend",
        "kicker": "FIRST NATIONS HERITAGE",
        "cta": "Follow PostaraTrend for more stories.",
    },
}
DEFAULT_BRAND = "trng"


def _brand(name=None):
    """Resolve a brand name to its token set. Empty or unknown falls back to
    trng, which is exactly the palette this module carried before brands."""
    return BRANDS.get(str(name or DEFAULT_BRAND).strip().lower(), BRANDS[DEFAULT_BRAND])


# ---------------------------------------------------------------- fonts
def _root_font(serif, bold):
    """Flat-repo support: find a matching .ttf at the repo root (fonts live
    flat next to app.py in trendradar-cards — Prospero/Playfair serif,
    NotoSans sans)."""
    try:
        files = [f for f in os.listdir(BASE_DIR) if f.lower().endswith((".ttf", ".otf"))]
    except OSError:
        return None
    hints = ("playfair", "prospero", "serif") if serif else ("notosans", "noto", "inter")
    pool = [f for f in files if any(h in f.lower().replace(" ", "") for h in hints)]
    if not serif:
        pool = [f for f in pool if "serif" not in f.lower()]
    if not pool:
        return None
    want = [f for f in pool if ("bold" in f.lower()) == bold] or pool
    # prefer plain Bold/Regular over Italic/Condensed variants
    want.sort(key=lambda f: ("ital" in f.lower(), "cond" in f.lower(), len(f)))
    return os.path.join(BASE_DIR, want[0])


def _font(size, serif=True, bold=False):
    """House-style font loader with graceful fallback (mirrors card modules)."""
    local = os.path.join(BASE_DIR, "fonts")
    candidates = []
    root = _root_font(serif, bold)
    if serif:
        candidates += [os.path.join(local, "PlayfairDisplay-Bold.ttf" if bold else "PlayfairDisplay-Regular.ttf")]
        if root: candidates.append(root)
        candidates += ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]
    else:
        candidates += [os.path.join(local, "Inter-Bold.ttf" if bold else "Inter-Regular.ttf")]
        if root: candidates.append(root)
        candidates += ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


# ---------------------------------------------------------------- audio beds
def _beds_for_mood(mood):
    """All committed beds for a mood: bed_<mood>.mp3, bed_<mood>_1.mp3, ..."""
    if not os.path.isdir(AUDIO_DIR):
        return []
    pat = re.compile(rf"^bed_{re.escape(mood)}(_\d+)?\.mp3$")
    return sorted(f for f in os.listdir(AUDIO_DIR) if pat.match(f))


def _pick_bed(mood, title, explicit=None):
    """Rotate across the mood's beds. Deterministic on the story title, so a
    re-render of the same story keeps its bed while different stories rotate.
    An explicit payload 'bed' filename overrides rotation."""
    beds = _beds_for_mood(mood)
    if explicit:
        if explicit in beds:
            return os.path.join(AUDIO_DIR, explicit), beds
        return None, beds
    if not beds:
        return None, beds
    import hashlib
    idx = int(hashlib.md5((title or "").encode("utf-8")).hexdigest(), 16) % len(beds)
    return os.path.join(AUDIO_DIR, beds[idx]), beds


# ---------------------------------------------------------------- narration (TTS)
# Phase 2a: a voice reads the story. Controlled by Render env vars — no workflow
# change needed. If TTS fails for any reason, the render falls back to the
# music-bed-only Reel so the lane never breaks on a voice-API hiccup.
#   STORY_TTS_PROVIDER = off | elevenlabs | google   (default off)
#   ELEVENLABS_API_KEY, STORY_VOICE_ID               (ElevenLabs)
#   GOOGLE_TTS_API_KEY, STORY_VOICE_ID e.g. en-NG-Standard-A (Google)
NARR_PAD = 1.4                       # breathing room after each scene's narration
NARR_PAD_MIN = 0.35                  # squeeze floor: the pad shrinks, the voice is never cut
NARR_MIN = 4.0                       # a scene never flashes past, even on a short line
NARR_MAX = 14.0                      # ADVISORY ONLY — a scene longer than this is reported in
                                     # status as a long_scene so the writer can split it. It is
                                     # NOT enforced by clamping: clamping the clip below its own
                                     # narration made build_video's atrim cut the voice mid-sentence.
BED_DUCK = 0.22                      # bed volume under narration


def _tts_cfg(title="", voice_override=""):
    """STORY_VOICE_ID may be a single id or a comma-separated list. A list
    rotates deterministically on the story title (same pattern as bed
    rotation): a re-render of the same story keeps its voice; different
    stories vary across the set.

    voice_override comes from the render payload and wins over the env var, so
    one lane can carry its own narrator without changing the voice every other
    lane on this service hears. A comma-separated override rotates too."""
    source = (voice_override or "").strip() or (os.environ.get("STORY_VOICE_ID") or "")
    raw_voices = [v.strip() for v in source.split(",") if v.strip()]
    if len(raw_voices) > 1:
        import hashlib
        idx = int(hashlib.md5((title or "").encode("utf-8")).hexdigest(), 16) % len(raw_voices)
        voice = raw_voices[idx]
    else:
        voice = raw_voices[0] if raw_voices else ""
    return {
        "provider": (os.environ.get("STORY_TTS_PROVIDER") or "off").strip().lower(),
        "voice": voice,
        "voice_pool": raw_voices,
        "el_key": (os.environ.get("ELEVENLABS_API_KEY") or "").strip(),
        "g_key": (os.environ.get("GOOGLE_TTS_API_KEY") or "").strip(),
    }


def _tts_ready(cfg=None):
    cfg = cfg or _tts_cfg()
    if cfg["provider"] == "elevenlabs":
        return bool(cfg["el_key"] and cfg["voice"])
    if cfg["provider"] == "google":
        return bool(cfg["g_key"])
    if cfg["provider"] == "stub":
        return True
    return False


def _synth_narration(text, out_path, cfg):
    """Write narration audio for one unit of text. Returns (ok, reason)."""
    try:
        if cfg["provider"] == "elevenlabs":
            import requests
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{cfg['voice']}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": cfg["el_key"], "content-type": "application/json"},
                json={"text": text, "model_id": "eleven_multilingual_v2"},
                timeout=60)
            if r.status_code != 200:
                try:
                    detail = r.json().get("detail", {})
                    msg = detail.get("message") if isinstance(detail, dict) else str(detail)
                except Exception:
                    msg = (r.text or "")[:200]
                return False, f"elevenlabs http {r.status_code}: {msg or '(no detail)'}"
            if len(r.content) < 500:
                return False, f"elevenlabs returned {len(r.content)} bytes (too small to be audio)"
            with open(out_path, "wb") as f:
                f.write(r.content)
            return True, None
        if cfg["provider"] == "google":
            import base64
            import requests
            voice = cfg["voice"] or "en-NG-Standard-A"
            r = requests.post(
                "https://texttospeech.googleapis.com/v1/text:synthesize",
                params={"key": cfg["g_key"]},
                json={"input": {"text": text},
                      "voice": {"languageCode": "en-NG", "name": voice},
                      "audioConfig": {"audioEncoding": "MP3",
                                      "speakingRate": float(os.environ.get("STORY_VOICE_RATE", "0.92"))}},
                timeout=60)
            if r.status_code != 200:
                return False, f"google tts http {r.status_code}: {(r.text or '')[:200]}"
            audio = r.json().get("audioContent")
            if not audio:
                return False, "google tts returned no audioContent"
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(audio))
            return True, None
        if cfg["provider"] == "stub":                     # QA only: speech-paced babble
            dur = max(1.2, len(text) * 0.062)
            _run([_ffmpeg_exe(), "-y", "-f", "lavfi",
                  "-i", f"sine=frequency=220:duration={dur:.2f}",
                  "-af", "tremolo=f=5:d=0.8,lowpass=f=1200,volume=0.6",
                  "-c:a", "libmp3lame", "-q:a", "5", out_path])
            return True, None
    except Exception as exc:                               # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:200]}"
    return False, "unknown provider"


def _audio_duration(path):
    """Duration in seconds via ffmpeg stderr parse (no ffprobe in the bundle).
    Tries the stream-info 'Duration: H:MM:SS.ss' line first (present even for
    very short clips), then the progress 'time=' marker as a fallback."""
    res = subprocess.run([_ffmpeg_exe(), "-i", path, "-f", "null", "-"],
                         capture_output=True, text=True)
    err = res.stderr or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", err)
    if not m:
        m = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", err)
    if not m:
        return None
    h, mnt, s = m.groups()
    dur = int(h) * 3600 + int(mnt) * 60 + float(s)
    return dur if dur > 0 else None


# ---------------------------------------------------------------- gates
CONTRACTION_RE = re.compile(
    r"\b\w+['\u2019](?:t|re|ll|ve|d|m)\b|\b(?:it|let|that|there|what|who|here)['\u2019]s\b",
    re.IGNORECASE,
)


def find_contractions(text):
    """Contraction gate — possessives pass, contractions fail (agent-card rule)."""
    return [m.group(0) for m in CONTRACTION_RE.finditer(text or "")]


def validate_payload(p):
    errors = []
    title = (p.get("title") or "").strip()
    scenes = p.get("scenes") or []
    if not title:
        errors.append("title is required")
    if not isinstance(scenes, list) or not (2 <= len(scenes) <= MAX_SCENES):
        errors.append(f"scenes must be a list of 2-{MAX_SCENES} items")
    texts = [title, p.get("kicker", ""), p.get("cta", ""),
             p.get("masthead", ""), p.get("tagline", "")]
    for i, s in enumerate(scenes if isinstance(scenes, list) else []):
        t = (s.get("text") or "").strip() if isinstance(s, dict) else ""
        if not t:
            errors.append(f"scenes[{i}].text is required")
        texts.append(t)
        # optional per-scene picture: a repo-relative or absolute path. Type is
        # checked here; a path that does not resolve is a soft failure at render
        # time (reported in status), never a 422 — same contract as bg_image.
        if isinstance(s, dict) and s.get("image") is not None:
            if not isinstance(s.get("image"), str):
                errors.append(f"scenes[{i}].image must be a string path")
    hits = sorted({h for t in texts for h in find_contractions(t)})
    if hits:
        errors.append("contractions not allowed: " + ", ".join(hits))
    brand = (p.get("brand") or "").strip().lower()
    if brand and brand not in BRANDS:
        # a typo in a Settings cell must not silently ship the wrong brand
        errors.append(f"unknown brand '{brand}' (available: {', '.join(sorted(BRANDS))})")
    mood = (p.get("mood") or "folktale").strip().lower()
    bed, beds = _pick_bed(mood, title, (p.get("bed") or "").strip() or None)
    if bed is None:
        if p.get("bed"):
            errors.append(
                f"requested bed '{p['bed']}' not found for mood '{mood}' "
                f"(available: {', '.join(beds) or 'none'})"
            )
        else:
            errors.append(
                f"no audio beds for mood '{mood}': commit Pixabay tracks as "
                f"audio/bed_{mood}.mp3 (and optionally bed_{mood}_1.mp3, "
                f"bed_{mood}_2.mp3, ...) with their license text"
            )
    secs = p.get("scene_seconds", 6)
    try:
        secs = float(secs)
    except (TypeError, ValueError):
        errors.append("scene_seconds must be a number")
        secs = 6
    if not 3 <= secs <= 12:
        errors.append("scene_seconds must be between 3 and 12")
    n_clips = (len(scenes) if isinstance(scenes, list) else 0) + 2  # title + cta
    total = n_clips * secs
    if total < MIN_TOTAL or total > MAX_TOTAL:
        errors.append(
            f"total duration {total:.1f}s outside publishing rule {MIN_TOTAL}-{MAX_TOTAL}s "
            f"(adjust scene count or scene_seconds)"
        )
    return errors, bed, secs


# ---------------------------------------------------------------- drawing
def _wrap(draw, text, font, max_w):
    words, lines, line = text.split(), [], ""
    for w in words:
        probe = (line + " " + w).strip()
        if draw.textlength(probe, font=font) <= max_w:
            line = probe
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def _fit_serif(draw, text, max_w, max_h, start=104, floor=54, bold=True, spacing=1.28):
    size = start
    while size >= floor:
        f = _font(size, serif=True, bold=bold)
        lines = _wrap(draw, text, f, max_w)
        line_h = int(size * spacing)
        if len(lines) * line_h <= max_h and all(
            draw.textlength(l, font=f) <= max_w for l in lines
        ):
            return f, lines, line_h
        size -= 6
    f = _font(floor, serif=True, bold=bold)
    return f, _wrap(draw, text, f, max_w), int(floor * spacing)


def _letterspaced(draw, xy, text, font, fill, tracking=10, anchor_center_w=None):
    total = sum(draw.textlength(c, font=font) + tracking for c in text) - tracking
    x = (anchor_center_w - total) / 2 if anchor_center_w else xy[0]
    y = xy[1]
    for c in text:
        draw.text((x, y), c, font=font, fill=fill)
        x += draw.textlength(c, font=font) + tracking

def _glow(img, cx, cy, radius, color, peak=46):
    glow = Image.new("L", img.size, 0)
    gd = ImageDraw.Draw(glow)
    steps = 24
    for i in range(steps, 0, -1):
        r = radius * i / steps
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=int(peak * (1 - i / steps)))
    overlay = Image.new("RGB", img.size, color)
    img.paste(Image.composite(overlay, img, glow), (0, 0))


def _is_url(ref):
    """True when a picture reference is an http(s) link rather than a repo path.
    Lanes that generate their art at run time host it and pass links, so both
    kinds of reference have to work side by side."""
    return isinstance(ref, str) and ref.lower().startswith(("http://", "https://"))


def _load_bg(path):
    """Prepare one photographic background for a whole episode: cover-fit to the
    frame, mildly desaturate for series cohesion, then darken with a global scrim
    plus a top/bottom gradient so the masthead, footer and cream body text stay
    legible. Returns a FRAME-sized RGB image, or None if the file cannot be read
    (a missing picture must never fail a render). Intermediates are closed as they
    go, so only one frame-sized image survives the call: the 512MB box holds one,
    not a stack."""
    try:
        if _is_url(path):                               # hosted art, fetched once
            import io                                   # lazy, same style as narration
            import requests
            resp = requests.get(path, timeout=30)
            resp.raise_for_status()
            src = Image.open(io.BytesIO(resp.content))
        else:
            src = Image.open(path)
        src.load()
        src = src.convert("RGB")
    except Exception:                                   # noqa: BLE001
        return None
    tw, th = FRAME_W, FRAME_H
    sw, sh = src.size
    scale = max(tw / sw, th / sh)
    nw, nh = max(int(sw * scale + 0.5), tw), max(int(sh * scale + 0.5), th)
    resized = src.resize((nw, nh), Image.LANCZOS)
    src.close()
    left, top = (nw - tw) // 2, (nh - th) // 2
    base = resized.crop((left, top, left + tw, top + th))
    resized.close()
    if BG_DESAT > 0:                                    # unify colour across the set
        gray = base.convert("L").convert("RGB")
        blended = Image.blend(base, gray, BG_DESAT)
        base.close()
        gray.close()
        base = blended
    black = Image.new("RGB", (tw, th), (0, 0, 0))
    dark = Image.blend(base, black, BG_SCRIM)           # global darken
    base.close()
    if BG_EDGE_SCRIM > 0:                               # seat masthead (top) + footer (bottom)
        scrim = Image.new("L", (tw, th), 0)
        sd = ImageDraw.Draw(scrim)
        for y in range(th):
            t = y / th
            a = 0
            if t < 0.30:
                a = int(BG_EDGE_SCRIM * (1 - t / 0.30))
            elif t > 0.68:
                a = int(BG_EDGE_SCRIM * ((t - 0.68) / 0.32))
            if a:
                sd.line([(0, y), (tw, y)], fill=a)
        composited = Image.composite(black, dark, scrim)
        dark.close()
        scrim.close()
        dark = composited
    black.close()
    return dark


def _base_frame(b=None, bg=None):
    b = b or _brand()
    accent = b["accent"]
    if bg is not None:
        # picture-led: the darkened photo IS the background. Skip the ink gradient
        # and the accent glow (both fight a photograph); keep the corner ornaments
        # so brand identity survives on top of the image.
        img = bg.copy()
        d = ImageDraw.Draw(img)
    else:
        ink, lift = b["ink"], b["ink_lift"]
        img = Image.new("RGB", (FRAME_W, FRAME_H), ink)
        d = ImageDraw.Draw(img)
        for y in range(FRAME_H):                       # subtle vertical lift
            if y % 3 == 0:
                t = y / FRAME_H
                c = tuple(int(ink[i] + (lift[i] - ink[i]) * (1 - abs(t - 0.35) * 1.6)) for i in range(3))
                d.line([(0, y), (FRAME_W, y)], fill=c)
        _glow(img, FRAME_W // 2, int(FRAME_H * 0.34), int(FRAME_W * 0.62), accent, peak=26)
        d = ImageDraw.Draw(img)
    # corner ornaments in the brand accent
    m, L, wpx = 84, 150, 5
    for cx, cy, dx, dy in [(m, m, 1, 1), (FRAME_W - m, m, -1, 1),
                           (m, FRAME_H - m, 1, -1), (FRAME_W - m, FRAME_H - m, -1, -1)]:
        d.line([(cx, cy), (cx + dx * L, cy)], fill=accent, width=wpx)
        d.line([(cx, cy), (cx, cy + dy * L)], fill=accent, width=wpx)
    return img, d


def _masthead(d, text=None, b=None):
    b = b or _brand()
    _letterspaced(d, (0, 168), text or b["masthead"], _font(34, serif=False, bold=True),
                  b["accent"], tracking=9, anchor_center_w=FRAME_W)


def _dotted_divider(d, y, width=420, b=None):
    b = b or _brand()
    x0 = (FRAME_W - width) // 2
    for x in range(x0, x0 + width, 26):
        d.ellipse([x, y, x + 8, y + 8], fill=b["accent"])


def _chip(d, cy, label, b=None):
    f = _font(34, serif=False, bold=True)
    tw = d.textlength(label, font=f)
    pad_x, pad_y = 38, 20
    x0 = (FRAME_W - tw) / 2 - pad_x
    x1 = (FRAME_W + tw) / 2 + pad_x
    b = b or _brand()
    d.rounded_rectangle([x0, cy, x1, cy + f.size + 2 * pad_y], radius=14,
                        outline=b["accent"], width=4)
    d.text(((FRAME_W - tw) / 2, cy + pad_y), label, font=f, fill=b["accent"])


def _footer(d, text, b=None):
    b = b or _brand()
    f = _font(34, serif=False, bold=False)
    tw = d.textlength(text, font=f)
    d.text(((FRAME_W - tw) / 2, FRAME_H - 220), text, font=f, fill=b["muted"])


def render_title_frame(path, title, kicker, masthead=None, tagline=None, brand=None,
                       bg=None):
    b = _brand(brand)
    img, d = _base_frame(b, bg)
    _masthead(d, masthead, b)
    _chip(d, 560, kicker.upper(), b)
    f, lines, lh = _fit_serif(d, title, FRAME_W - 320, 760, start=128, floor=64)
    y = (FRAME_H - len(lines) * lh) // 2 - 40
    for line in lines:
        d.text(((FRAME_W - d.textlength(line, font=f)) / 2, y), line, font=f, fill=b["body"])
        y += lh
    _dotted_divider(d, y + 60, b=b)
    _footer(d, tagline or b["tagline"], b)
    small = img.resize((828, 1472), Image.LANCZOS)
    small.save(path, "PNG")
    small.close()
    img.close()


def _text_plate(img, top, bottom, strength=None):
    """Darken just the band the body text sits in, so the picture above it can
    stay bright. Feathered at both edges so there is no visible hard band."""
    if strength is None:
        strength = BG_TEXT_PLATE
    if strength <= 0 or bottom <= top:
        return
    w, h = img.size
    top = max(0, int(top)); bottom = min(h, int(bottom))
    feather = max(1, int((bottom - top) * 0.22))
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    for y in range(top, bottom):
        if y < top + feather:
            a = strength * (y - top) / feather
        elif y > bottom - feather:
            a = strength * (bottom - y) / feather
        else:
            a = strength
        md.line([(0, y), (w, y)], fill=int(a))
    black = Image.new("RGB", (w, h), (0, 0, 0))
    img.paste(Image.composite(black, img, mask), (0, 0))
    mask.close()
    black.close()


def render_scene_frame(path, text, idx, total, label=None, masthead=None, tagline=None,
                       brand=None, bg=None):
    b = _brand(brand)
    img, d = _base_frame(b, bg)
    _masthead(d, masthead, b)
    lab = (label or f"SCENE {idx}").upper()
    fl = _font(36, serif=False, bold=True)
    if bg is not None:
        # PICTURE MODE: the artwork is the point, so the words get out of its way.
        # Type is smaller, set wider, and seated in the lower third above the
        # progress dots, with a feathered plate behind it for legibility. The top
        # half of the illustration stays clear and bright.
        f, lines, lh = _fit_serif(d, text, FRAME_W - 170, 590,
                                  start=58, floor=34, bold=False, spacing=1.30)
        block_h = len(lines) * lh
        bottom = FRAME_H - 400                      # clear of the dots at FRAME_H-330
        y = bottom - block_h
        _text_plate(img, y - 120, bottom + 60)
        d = ImageDraw.Draw(img)                     # plate was pasted, refresh the draw
        _letterspaced(d, (0, y - 78), lab, fl, b["accent"], tracking=7,
                      anchor_center_w=FRAME_W)
    else:
        _letterspaced(d, (0, 520), lab, fl, b["accent"], tracking=7, anchor_center_w=FRAME_W)
        f, lines, lh = _fit_serif(d, text, FRAME_W - 300, 1000, start=92, floor=54,
                                  bold=False, spacing=1.42)
        y = (FRAME_H - len(lines) * lh) // 2
    for line in lines:
        d.text(((FRAME_W - d.textlength(line, font=f)) / 2, y), line, font=f, fill=b["body"])
        y += lh
    # progress dots
    r, gap = 9, 44
    x = (FRAME_W - (total - 1) * gap) / 2
    dy = FRAME_H - 330
    for i in range(total):
        fill = b["accent"] if i < idx else (70, 74, 82)
        d.ellipse([x + i * gap - r, dy - r, x + i * gap + r, dy + r], fill=fill)
    _footer(d, tagline or b["tagline"], b)
    small = img.resize((828, 1472), Image.LANCZOS)
    small.save(path, "PNG")
    small.close()
    img.close()


def render_cta_frame(path, title, cta, masthead=None, tagline=None, brand=None,
                     hashtag=None, bg=None):
    b = _brand(brand)
    img, d = _base_frame(b, bg)
    _masthead(d, masthead, b)
    ft = _font(46, serif=True, bold=True)
    d.text(((FRAME_W - d.textlength(title, font=ft)) / 2, 620), title, font=ft, fill=b["muted"])
    _dotted_divider(d, 740, b=b)
    f, lines, lh = _fit_serif(d, cta, FRAME_W - 320, 640, start=100, floor=58)
    y = (FRAME_H - len(lines) * lh) // 2
    for line in lines:
        d.text(((FRAME_W - d.textlength(line, font=f)) / 2, y), line, font=f, fill=b["body"])
        y += lh
    fh = _font(48, serif=False, bold=True)
    tag = (hashtag or "").strip() or b["hashtag"]
    d.text(((FRAME_W - d.textlength(tag, font=fh)) / 2, y + 90), tag, font=fh, fill=b["accent"])
    _footer(d, tagline or b["tagline"], b)
    small = img.resize((828, 1472), Image.LANCZOS)
    small.save(path, "PNG")
    small.close()
    img.close()


# ---------------------------------------------------------------- ffmpeg
def _ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        raise RuntimeError("ffmpeg not available: add imageio-ffmpeg to requirements.txt")


def _run(cmd, heartbeat=None):
    """Run ffmpeg. If a heartbeat callable is given, invoke it every ~15s while
    the process works, so a long encode on the shared 512MB box is never
    mistaken for a dead worker by the status watchdog."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    while True:
        try:
            _, err = proc.communicate(timeout=15)
            break
        except subprocess.TimeoutExpired:
            if heartbeat:
                try:
                    heartbeat()
                except Exception:                       # noqa: BLE001
                    pass
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + (err or "")[-800:])


def build_video(frames, bed, out_path, scene_secs, workdir, progress=None,
                clip_secs=None, narr_files=None, heartbeat=None):
    """Ken Burns per frame -> fade-through-black concat -> audio.
    clip_secs: optional per-clip durations (narration mode); narr_files: optional
    per-clip narration audio (None entries = silent under the bed)."""
    exe = _ffmpeg_exe()
    clips = []
    durs = clip_secs or [scene_secs] * len(frames)
    fade = 0.35                                        # fade-through-black page turn
    for i, frame in enumerate(frames):
        if progress:
            progress(f"encoding scene {i + 1}/{len(frames)}")
        d_i = durs[i]
        n_frames = max(int(d_i * FPS), FPS)
        clip = os.path.join(workdir, f"clip_{i:02d}.mp4")
        zoom = f"min(zoom+{0.10 / n_frames:.6f},1.10)"
        drift = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)+(on/{n})*40'".format(n=n_frames)
        vf = (
            f"zoompan=z='{zoom}':{drift}:d={n_frames}:s={OUT_W}x{OUT_H}:fps={FPS},"
            f"fade=t=in:st=0:d={fade},"
            f"fade=t=out:st={d_i - fade:.3f}:d={fade},"
            f"format=yuv420p"
        )
        _run([exe, "-y", "-threads", "1", "-loop", "1", "-i", frame, "-vf", vf,
              "-t", f"{d_i:.3f}", "-c:v", "libx264", "-profile:v", "high",
              "-preset", "ultrafast", "-crf", "21", "-an", clip],
             heartbeat=heartbeat)
        clips.append(clip)

    # join with the concat demuxer + stream copy: one clip in memory at a time,
    # no filtergraph, no re-encode — this was the OOM step in the xfade design.
    total = sum(durs)
    listfile = os.path.join(workdir, "concat.txt")
    with open(listfile, "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")
    silent = os.path.join(workdir, "video_only.mp4")
    if progress:
        progress("joining scenes")
    _run([exe, "-y", "-f", "concat", "-safe", "0", "-i", listfile,
          "-c", "copy", silent], heartbeat=heartbeat)

    if narr_files and any(narr_files):
        # narration track: each unit padded to its clip length, then concatenated
        if progress:
            progress("mixing narration")
        padded = []
        for i, nf in enumerate(narr_files):
            pw = os.path.join(workdir, f"narr_{i:02d}.wav")
            if nf:
                _run([exe, "-y", "-i", nf,
                      "-af", f"apad=whole_dur={durs[i]:.3f},atrim=0:{durs[i]:.3f}",
                      "-ar", "48000", "-ac", "2", pw])
            else:
                _run([exe, "-y", "-f", "lavfi",
                      "-i", f"anullsrc=r=48000:cl=stereo:d={durs[i]:.3f}", pw])
            padded.append(pw)
        nlist = os.path.join(workdir, "narr_concat.txt")
        with open(nlist, "w") as f:
            for p in padded:
                f.write(f"file '{p}'\n")
        narr_track = os.path.join(workdir, "narration.wav")
        _run([exe, "-y", "-f", "concat", "-safe", "0", "-i", nlist, "-c", "copy", narr_track])
        # mix: narration on top, bed ducked underneath, one final loudness pass
        af = (
            f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{total:.3f},volume={BED_DUCK}[bed];"
            f"[2:a]atrim=0:{total:.3f}[voice];"
            f"[voice][bed]amix=inputs=2:duration=first:normalize=0,"
            f"loudnorm=I=-14:TP=-1.5:LRA=11,"
            f"afade=t=in:st=0:d=0.6,afade=t=out:st={max(total - 2.0, 0):.3f}:d=2.0[aout]"
        )
        _run([exe, "-y", "-threads", "1", "-i", silent, "-i", bed, "-i", narr_track,
              "-filter_complex", af, "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
              "-c:a", "aac", "-b:a", "224k", "-ar", "48000", "-ac", "2",
              "-shortest", "-movflags", "+faststart", out_path], heartbeat=heartbeat)
        return total

    # bed-only (phase one behaviour, and the fallback when TTS is off or fails)
    af = (
        f"aloop=loop=-1:size=2e9,atrim=0:{total:.3f},"
        f"loudnorm=I=-14:TP=-1.5:LRA=11,"
        f"afade=t=in:st=0:d=1.0,afade=t=out:st={max(total - 2.0, 0):.3f}:d=2.0"
    )
    _run([exe, "-y", "-threads", "1", "-i", silent, "-i", bed, "-af", af,
          "-map", "0:v", "-map", "1:a", "-c:v", "copy",
          "-c:a", "aac", "-b:a", "224k", "-ar", "48000", "-ac", "2",
          "-shortest", "-movflags", "+faststart",
          out_path], heartbeat=heartbeat)
    return total


# ---------------------------------------------------------------- jobs
def _gc_jobs():
    now = time.time()
    with JOBS_LOCK:
        stale = [j for j, meta in JOBS.items() if now - meta["created"] > JOB_TTL]
        for j in stale:
            meta = JOBS.pop(j)
            for p in (meta.get("path"), _status_path(j)):
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass


def _render_job(job_id, payload, bed, scene_secs):
    workdir = tempfile.mkdtemp(prefix=f"story_{job_id}_")
    try:
        title = payload["title"].strip()
        # lane identity: a lane carries its own brand (colours, masthead, tagline,
        # hashtag) and may still override any single string. No brand -> trng, so
        # existing callers are untouched.
        brand_name = (payload.get("brand") or "").strip().lower() or DEFAULT_BRAND
        b = _brand(brand_name)
        kicker = (payload.get("kicker") or b["kicker"]).strip()
        cta = (payload.get("cta") or b["cta"]).strip()
        masthead = (payload.get("masthead") or "").strip() or None
        tagline = (payload.get("tagline") or "").strip() or None
        hashtag = (payload.get("hashtag") or "").strip() or None
        scenes = payload["scenes"]
        # picture-led background, two granularities that compose:
        #   bg_image            -> one photo for the whole episode (original behaviour)
        #   scenes[i].image     -> a photo for THAT beat, overriding the episode photo
        #   title_image / cta_image -> optional dedicated opening + closing pictures
        # Any of them absent or unreadable falls back to the next level down and
        # finally to the classic solid frame. Every failure is reported in status
        # (bg_image_error / scene_image_errors) and none of them fails a render.
        bg_ref = (payload.get("bg_image") or "").strip()
        bg = None
        bg_image_error = None
        if bg_ref:
            bg_path = bg_ref if (_is_url(bg_ref) or os.path.isabs(bg_ref)) \
                else os.path.join(BASE_DIR, bg_ref)
            bg = _load_bg(bg_path)
            if bg is None:
                bg_image_error = f"bg_image not loadable: {bg_ref}"

        scene_image_errors = []
        per_frame_used = 0

        def _frame_bg(ref, where):
            """Resolve one frame's own picture. Returns (image_or_None, is_own).
            is_own is True only when a dedicated picture loaded, so the caller
            knows whether it must close the image or leave the shared bg alone.
            One picture is held at a time: load, draw, release."""
            ref = (ref or "").strip() if isinstance(ref, str) else ""
            if not ref:
                return bg, False
            path = ref if (_is_url(ref) or os.path.isabs(ref)) \
                else os.path.join(BASE_DIR, ref)
            img = _load_bg(path)
            if img is None:
                scene_image_errors.append(f"{where}: not loadable: {ref}")
                return bg, False                        # soft fallback to the episode photo
            return img, True

        stamp = f"{time.time():.6f}".replace(".", "")   # microsecond-precision names
        frames = [os.path.join(workdir, f"f{stamp}_00_title.png")]
        t_bg, t_own = _frame_bg(payload.get("title_image"), "title_image")
        render_title_frame(frames[0], title, kicker, masthead, tagline, brand_name, bg=t_bg)
        if t_own:
            per_frame_used += 1
            t_bg.close()                                # released before the next one loads
        for i, s in enumerate(scenes, start=1):
            fp = os.path.join(workdir, f"f{stamp}_{i:02d}_scene.png")
            s_bg, s_own = _frame_bg(s.get("image"), f"scenes[{i - 1}].image")
            render_scene_frame(fp, s["text"].strip(), i, len(scenes), s.get("label"),
                               masthead, tagline, brand_name, bg=s_bg)
            if s_own:
                per_frame_used += 1
                s_bg.close()                            # one scene picture in memory at a time
            frames.append(fp)
        cta_fp = os.path.join(workdir, f"f{stamp}_{len(scenes) + 1:02d}_cta.png")
        c_bg, c_own = _frame_bg(payload.get("cta_image"), "cta_image")
        render_cta_frame(cta_fp, title, cta, masthead, tagline, brand_name, hashtag, bg=c_bg)
        if c_own:
            per_frame_used += 1
            c_bg.close()
        frames.append(cta_fp)

        if bg is not None:
            bg.close()                                  # release the shared photo before the encode
        pictured = (bool(bg_ref) and bg_image_error is None) or per_frame_used > 0
        import gc
        gc.collect()                                    # frame-stage intermediates go now
        out_path = os.path.join(JOB_DIR, f"{job_id}.mp4")
        beat = lambda step: _write_status(job_id, status="rendering",
                                          bed=os.path.basename(bed), step=step)
        hb = lambda: os.utime(_status_path(job_id))     # cheap mtime touch = heartbeat

        # narration (phase 2a): synth per unit; any failure -> bed-only fallback
        clip_secs = None
        narr_files = None
        long_scenes = []
        cfg = _tts_cfg(title, payload.get("voice"))
        want_narration = payload.get("narration", _tts_ready(cfg))
        narr_error = None
        if want_narration and _tts_ready(cfg):
            units = [f"{title}." if not title.endswith((".", "!", "?")) else title]
            units += [s["text"].strip() for s in scenes]
            units += [cta]
            nfiles, nsecs, adurs, ok, narr_error = [], [], [], True, None
            for i, text in enumerate(units):
                beat(f"narration {i + 1}/{len(units)}")
                nf = os.path.join(workdir, f"tts_{i:02d}.mp3")
                synth_ok, reason = _synth_narration(text, nf, cfg)
                if not synth_ok:
                    ok, narr_error = False, f"unit {i + 1}/{len(units)}: {reason}"
                    break
                d = _audio_duration(nf)
                if not d:
                    # graceful degrade: the TTS call already succeeded and nf holds real
                    # narration audio — only our duration MEASUREMENT failed, so estimate
                    # from text length rather than discarding the whole story's narration
                    d = max(1.2, len(text) * 0.075)
                nfiles.append(nf)
                adurs.append(d)
                # the clip is the narration plus breathing room. NEVER shorter than the
                # audio: build_video trims the voice to the clip, so a clamp here is a cut.
                nsecs.append(max(d + NARR_PAD, NARR_MIN))
            if ok:
                total_est = sum(nsecs)
                if total_est > MAX_TOTAL:               # tighten pads before giving up
                    squeeze = [max(a + NARR_PAD_MIN, NARR_MIN) for a in adurs]
                    if sum(squeeze) <= MAX_TOTAL:
                        nsecs = squeeze
                    else:
                        over = sum(squeeze) - MAX_TOTAL
                        raise RuntimeError(
                            f"narrated duration {sum(squeeze):.0f}s exceeds the {MAX_TOTAL}s Reel cap "
                            f"even at minimum pads: cut roughly {int(over * 2.5) + 1} words from the "
                            f"script, or reduce the scene count")
                long_scenes = [i + 1 for i, a in enumerate(adurs) if a + NARR_PAD > NARR_MAX]
                clip_secs, narr_files = nsecs, nfiles

        total = build_video(frames, bed, out_path, scene_secs, workdir, progress=beat,
                            clip_secs=clip_secs, narr_files=narr_files, heartbeat=hb)
        narr_err_final = narr_error if (want_narration and _tts_ready(cfg) and not narr_files) else None
        with JOBS_LOCK:
            JOBS[job_id].update(status="done", path=out_path, duration=round(total, 2),
                                narrated=bool(narr_files), voice=(cfg["voice"] if narr_files else None),
                                brand=brand_name, narration_error=narr_err_final,
                                long_scenes=(long_scenes if narr_files else []),
                                pictured=pictured, bg_image_error=bg_image_error,
                                scene_image_errors=scene_image_errors)
        _write_status(job_id, status="done", bed=os.path.basename(bed),
                      duration=round(total, 2), narrated=bool(narr_files),
                      voice=(cfg["voice"] if narr_files else None),
                      brand=brand_name, narration_error=narr_err_final,
                      long_scenes=(long_scenes if narr_files else []),
                      pictured=pictured, bg_image_error=bg_image_error,
                      scene_image_errors=scene_image_errors)
    except Exception as exc:                            # noqa: BLE001
        with JOBS_LOCK:
            JOBS[job_id].update(status="error", error=str(exc)[:800])
        _write_status(job_id, status="error", error=str(exc)[:800])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------- routes
@story_bp.route("/render/story/start", methods=["POST"])
def story_start():
    _gc_jobs()
    payload = request.get_json(silent=True) or {}
    errors, bed, scene_secs = validate_payload(payload)
    if errors:
        return jsonify({"status": "rejected", "errors": errors}), 422
    job_id = uuid.uuid4().hex[:16]
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "rendering", "created": time.time(), "path": None,
                        "bed": os.path.basename(bed)}
    _write_status(job_id, status="rendering", bed=os.path.basename(bed))
    threading.Thread(target=_render_job, args=(job_id, payload, bed, scene_secs),
                     daemon=True).start()
    return jsonify({"status": "accepted", "job_id": job_id,
                    "bed": os.path.basename(bed),
                    "status_url": f"/render/story/status/{job_id}"}), 202


@story_bp.route("/render/story/status/<job_id>", methods=["GET"])
def story_status(job_id):
    with JOBS_LOCK:
        meta = JOBS.get(job_id)
    if not meta:
        disk = _read_status(job_id)
        mp4 = os.path.join(JOB_DIR, f"{job_id}.mp4")
        if disk and disk.get("status") == "done" and os.path.exists(mp4):
            meta = {"status": "done", "path": mp4,
                    "duration": disk.get("duration"), "bed": disk.get("bed"),
                    "narrated": disk.get("narrated", False), "voice": disk.get("voice"),
                    "brand": disk.get("brand"),
                    "narration_error": disk.get("narration_error"),
                    "long_scenes": disk.get("long_scenes") or [],
                    "pictured": disk.get("pictured", False),
                    "bg_image_error": disk.get("bg_image_error"),
                    "scene_image_errors": disk.get("scene_image_errors") or []}
            with JOBS_LOCK:
                JOBS[job_id] = {**meta, "created": time.time()}
        elif disk and disk.get("status") == "error":
            meta = {"status": "error", "error": disk.get("error")}
        elif disk and disk.get("status") == "rendering":
            if disk.get("_age", 0) > HEARTBEAT_STALE:
                meta = {"status": "error",
                        "error": "render worker restarted mid-job (likely out of memory); job lost"}
            else:
                meta = {"status": "rendering"}
        else:
            return jsonify({"status": "unknown", "error": "job not found or expired"}), 404
    body = {"status": meta["status"]}
    if meta["status"] == "done":
        body["video_url"] = f"{request.url_root.rstrip('/')}/render/story/media/{job_id}.mp4"
        body["duration_seconds"] = meta.get("duration")
        body["bed"] = meta.get("bed")
        body["narrated"] = meta.get("narrated", False)
        body["voice"] = meta.get("voice")
        body["brand"] = meta.get("brand")
        body["pictured"] = meta.get("pictured", False)
        if meta.get("bg_image_error"):
            body["bg_image_error"] = meta["bg_image_error"]
        if meta.get("scene_image_errors"):
            body["scene_image_errors"] = meta["scene_image_errors"]
        if meta.get("narration_error"):
            body["narration_error"] = meta["narration_error"]
        if meta.get("long_scenes"):
            body["long_scenes"] = meta["long_scenes"]
            body["long_scene_note"] = (
                f"scene(s) run past {NARR_MAX:.0f}s of narration; the voice is intact but the "
                f"card holds a long time — consider splitting them")
    if meta["status"] == "error":
        body["error"] = meta.get("error")
    return jsonify(body)


def _join_job(job_id, parts):
    """Stitch finished parts into one film. Parts are job ids from this service,
    or http(s) links to mp4s. Copies streams rather than re-encoding, so a five
    minute film joins in seconds and loses no quality. Sources are fetched one at
    a time and released, so the box holds one part, not the whole film."""
    workdir = tempfile.mkdtemp(prefix="join_", dir=JOB_DIR)
    local = []
    try:
        for i, ref in enumerate(parts):
            if _is_url(ref):
                import requests
                dest = os.path.join(workdir, f"p{i:02d}.mp4")
                with requests.get(ref, stream=True, timeout=120) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as fh:
                        for chunk in resp.iter_content(1 << 20):
                            fh.write(chunk)
            else:                                       # a job id from this service
                with JOBS_LOCK:
                    meta = JOBS.get(ref)
                dest = (meta or {}).get("path") or os.path.join(JOB_DIR, f"{ref}.mp4")
                if not os.path.exists(dest):
                    raise RuntimeError(f"part not found or expired: {ref}")
            local.append(dest)

        listing = os.path.join(workdir, "parts.txt")
        with open(listing, "w", encoding="utf-8") as fh:
            for path in local:
                safe = path.replace("'", "'\\''")
                fh.write(f"file '{safe}'\n")

        out_path = os.path.join(JOB_DIR, f"{job_id}.mp4")
        _run([_ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", listing,
              "-c", "copy", "-movflags", "+faststart", out_path])
        total = _audio_duration(out_path) or 0.0
        with JOBS_LOCK:
            JOBS[job_id].update(status="done", path=out_path,
                                duration=round(total, 2), parts=len(local))
        _write_status(job_id, status="done", path=out_path,
                      duration=round(total, 2), parts=len(local))
    except Exception as exc:                            # noqa: BLE001
        with JOBS_LOCK:
            JOBS[job_id].update(status="error", error=str(exc)[:800])
        _write_status(job_id, status="error", error=str(exc)[:800])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@story_bp.route("/render/story/join", methods=["POST"])
def story_join():
    """Join finished parts into one film. Body: {"parts": [id or url, ...]}.
    Returns a job id that is polled and fetched exactly like a normal render, so
    a lane joins with the same wait, check and media steps it already uses."""
    payload = request.get_json(silent=True) or {}
    parts = payload.get("parts")
    if not isinstance(parts, list) or len(parts) < 2:
        return jsonify({"error": "parts must be a list of at least two job ids or mp4 urls"}), 422
    if len(parts) > 20:
        return jsonify({"error": "at most twenty parts per film"}), 422
    if not all(isinstance(x, str) and x.strip() for x in parts):
        return jsonify({"error": "every part must be a non empty job id or url"}), 422

    _gc_jobs()
    job_id = uuid.uuid4().hex[:16]
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "joining", "created": time.time(), "path": None,
                        "parts": len(parts)}
    _write_status(job_id, status="joining", parts=len(parts))
    threading.Thread(target=_join_job, args=(job_id, [x.strip() for x in parts]),
                     daemon=True).start()
    return jsonify({"id": job_id, "status": "joining", "parts": len(parts)}), 202


@story_bp.route("/render/story/media/<job_id>.mp4", methods=["GET"])
def story_media(job_id):
    with JOBS_LOCK:
        meta = JOBS.get(job_id)
    path = (meta or {}).get("path") or os.path.join(JOB_DIR, f"{job_id}.mp4")
    if not os.path.exists(path):
        return jsonify({"error": "video not ready or expired"}), 404
    return send_file(path, mimetype="video/mp4", conditional=True)


@story_bp.route("/render/story/health", methods=["GET"])
def story_health():
    problems = []
    try:
        _ffmpeg_exe()
    except Exception as exc:                            # noqa: BLE001
        problems.append(str(exc))
    beds = sorted(
        f for f in (os.listdir(AUDIO_DIR) if os.path.isdir(AUDIO_DIR) else [])
        if f.startswith("bed_") and f.endswith(".mp3")
    )
    if not beds:
        problems.append("no audio beds in audio/ (expected e.g. audio/bed_folktale.mp3)")
    cfg = _tts_cfg()
    narration = {"provider": cfg["provider"],
                 "ready": _tts_ready(cfg),
                 "voice_count": len(cfg["voice_pool"]),
                 "sample_voice": cfg["voice"] or "(default)"} if cfg["provider"] != "off" else {
                 "provider": "off"}
    return jsonify({
        "narration": narration,
        "brands": sorted(BRANDS),
        "status": "ok" if not problems else "degraded",
        "ffmpeg": "unavailable — check requirements.txt (imageio-ffmpeg)" if any("ffmpeg" in p for p in problems) else "bundled (imageio-ffmpeg)",
        "audio_beds": beds,
        "problems": problems,
    }), 200 if not problems else 503
