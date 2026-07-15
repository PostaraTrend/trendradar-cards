"""
TRNG Story Video Renderer — /render/story
Animated storytelling Reels (1080x1920 MP4, H.264 + AAC) for Trend Radar Nigeria.

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
    texts = [title, p.get("kicker", ""), p.get("cta", "")]
    for i, s in enumerate(scenes if isinstance(scenes, list) else []):
        t = (s.get("text") or "").strip() if isinstance(s, dict) else ""
        if not t:
            errors.append(f"scenes[{i}].text is required")
        texts.append(t)
    hits = sorted({h for t in texts for h in find_contractions(t)})
    if hits:
        errors.append("contractions not allowed: " + ", ".join(hits))
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
    total = n_clips * secs - (n_clips - 1) * XFADE
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


def _base_frame():
    img = Image.new("RGB", (FRAME_W, FRAME_H), INK)
    d = ImageDraw.Draw(img)
    for y in range(FRAME_H):                       # subtle vertical lift
        if y % 3 == 0:
            t = y / FRAME_H
            c = tuple(int(INK[i] + (INK_LIFT[i] - INK[i]) * (1 - abs(t - 0.35) * 1.6)) for i in range(3))
            d.line([(0, y), (FRAME_W, y)], fill=c)
    _glow(img, FRAME_W // 2, int(FRAME_H * 0.34), int(FRAME_W * 0.62), GOLD, peak=26)
    d = ImageDraw.Draw(img)
    # gold corner ornaments
    m, L, wpx = 84, 150, 5
    for cx, cy, dx, dy in [(m, m, 1, 1), (FRAME_W - m, m, -1, 1),
                           (m, FRAME_H - m, 1, -1), (FRAME_W - m, FRAME_H - m, -1, -1)]:
        d.line([(cx, cy), (cx + dx * L, cy)], fill=GOLD, width=wpx)
        d.line([(cx, cy), (cx, cy + dy * L)], fill=GOLD, width=wpx)
    return img, d


def _masthead(d):
    _letterspaced(d, (0, 168), MASTHEAD, _font(34, serif=False, bold=True),
                  GOLD, tracking=9, anchor_center_w=FRAME_W)


def _dotted_divider(d, y, width=420):
    x0 = (FRAME_W - width) // 2
    for x in range(x0, x0 + width, 26):
        d.ellipse([x, y, x + 8, y + 8], fill=GOLD)


def _chip(d, cy, label):
    f = _font(34, serif=False, bold=True)
    tw = d.textlength(label, font=f)
    pad_x, pad_y = 38, 20
    x0 = (FRAME_W - tw) / 2 - pad_x
    x1 = (FRAME_W + tw) / 2 + pad_x
    d.rounded_rectangle([x0, cy, x1, cy + f.size + 2 * pad_y], radius=14,
                        outline=GOLD, width=4)
    d.text(((FRAME_W - tw) / 2, cy + pad_y), label, font=f, fill=GOLD)


def _footer(d, text):
    f = _font(34, serif=False, bold=False)
    tw = d.textlength(text, font=f)
    d.text(((FRAME_W - tw) / 2, FRAME_H - 220), text, font=f, fill=GREY)


def render_title_frame(path, title, kicker):
    img, d = _base_frame()
    _masthead(d)
    _chip(d, 560, kicker.upper())
    f, lines, lh = _fit_serif(d, title, FRAME_W - 320, 760, start=128, floor=64)
    y = (FRAME_H - len(lines) * lh) // 2 - 40
    for line in lines:
        d.text(((FRAME_W - d.textlength(line, font=f)) / 2, y), line, font=f, fill=CREAM)
        y += lh
    _dotted_divider(d, y + 60)
    _footer(d, TAGLINE)
    img.save(path, "PNG")


def render_scene_frame(path, text, idx, total, label=None):
    img, d = _base_frame()
    _masthead(d)
    lab = (label or f"SCENE {idx}").upper()
    fl = _font(36, serif=False, bold=True)
    _letterspaced(d, (0, 520), lab, fl, GOLD, tracking=7, anchor_center_w=FRAME_W)
    f, lines, lh = _fit_serif(d, text, FRAME_W - 300, 1000, start=92, floor=54, bold=False, spacing=1.42)
    y = (FRAME_H - len(lines) * lh) // 2
    for line in lines:
        d.text(((FRAME_W - d.textlength(line, font=f)) / 2, y), line, font=f, fill=CREAM)
        y += lh
    # progress dots
    r, gap = 9, 44
    x = (FRAME_W - (total - 1) * gap) / 2
    dy = FRAME_H - 330
    for i in range(total):
        fill = GOLD if i < idx else (70, 74, 82)
        d.ellipse([x + i * gap - r, dy - r, x + i * gap + r, dy + r], fill=fill)
    _footer(d, TAGLINE)
    img.save(path, "PNG")


def render_cta_frame(path, title, cta):
    img, d = _base_frame()
    _masthead(d)
    ft = _font(46, serif=True, bold=True)
    d.text(((FRAME_W - d.textlength(title, font=ft)) / 2, 620), title, font=ft, fill=GREY)
    _dotted_divider(d, 740)
    f, lines, lh = _fit_serif(d, cta, FRAME_W - 320, 640, start=100, floor=58)
    y = (FRAME_H - len(lines) * lh) // 2
    for line in lines:
        d.text(((FRAME_W - d.textlength(line, font=f)) / 2, y), line, font=f, fill=CREAM)
        y += lh
    fh = _font(48, serif=False, bold=True)
    tag = "#TrendRadarNG"
    d.text(((FRAME_W - d.textlength(tag, font=fh)) / 2, y + 90), tag, font=fh, fill=GOLD)
    _footer(d, TAGLINE)
    img.save(path, "PNG")


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


def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + (res.stderr or "")[-800:])


def build_video(frames, bed, out_path, scene_secs, workdir, progress=None):
    """Ken Burns per frame -> chained crossfades -> normalized audio bed."""
    exe = _ffmpeg_exe()
    clips = []
    n_frames = int(scene_secs * FPS)
    for i, frame in enumerate(frames):
        clip = os.path.join(workdir, f"clip_{i:02d}.mp4")
        zoom = f"min(zoom+{0.10 / n_frames:.6f},1.10)"
        drift = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)+(on/{n})*40'".format(n=n_frames)
        vf = (
            f"zoompan=z='{zoom}':{drift}:d={n_frames}:s={OUT_W}x{OUT_H}:fps={FPS},"
            f"format=yuv420p"
        )
        _run([exe, "-y", "-threads", "1", "-loop", "1", "-i", frame, "-vf", vf,
              "-t", f"{scene_secs}", "-c:v", "libx264", "-preset", "veryfast",
              "-crf", "20", "-an", clip])
        if progress:
            progress(f"scene {i + 1}/{len(frames)}")
        clips.append(clip)

    # chain crossfades
    inputs = []
    for c in clips:
        inputs += ["-i", c]
    parts, prev, elapsed = [], "0:v", scene_secs
    for i in range(1, len(clips)):
        label = f"v{i}"
        offset = elapsed - XFADE
        parts.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}[{label}]")
        prev = label
        elapsed = offset + scene_secs
    total = elapsed
    silent = os.path.join(workdir, "video_only.mp4")
    if progress:
        progress("joining scenes")
    _run([exe, "-y", "-threads", "1", *inputs,
          "-filter_complex", ";".join(parts) + f";[{prev}]format=yuv420p[vout]",
          "-map", "[vout]", "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast",
          "-crf", "20", "-r", str(FPS), silent])

    # audio: loop if short, loudness normalize to -14 LUFS, fade in/out, single AAC encode
    af = (
        f"aloop=loop=-1:size=2e9,atrim=0:{total:.3f},"
        f"loudnorm=I=-14:TP=-1.5:LRA=11,"
        f"afade=t=in:st=0:d=1.0,afade=t=out:st={max(total - 2.0, 0):.3f}:d=2.0"
    )
    _run([exe, "-y", "-i", silent, "-i", bed, "-af", af,
          "-map", "0:v", "-map", "1:a", "-c:v", "copy",
          "-c:a", "aac", "-b:a", "224k", "-ar", "48000", "-ac", "2",
          "-shortest", "-movflags", "+faststart",
          out_path])
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
        kicker = (payload.get("kicker") or "NIGERIAN FOLKTALE").strip()
        cta = (payload.get("cta") or "Follow Trend Radar NG for more stories.").strip()
        scenes = payload["scenes"]
        stamp = f"{time.time():.6f}".replace(".", "")   # microsecond-precision names
        frames = [os.path.join(workdir, f"f{stamp}_00_title.png")]
        render_title_frame(frames[0], title, kicker)
        for i, s in enumerate(scenes, start=1):
            fp = os.path.join(workdir, f"f{stamp}_{i:02d}_scene.png")
            render_scene_frame(fp, s["text"].strip(), i, len(scenes), s.get("label"))
            frames.append(fp)
        cta_fp = os.path.join(workdir, f"f{stamp}_{len(scenes) + 1:02d}_cta.png")
        render_cta_frame(cta_fp, title, cta)
        frames.append(cta_fp)

        out_path = os.path.join(JOB_DIR, f"{job_id}.mp4")
        beat = lambda step: _write_status(job_id, status="rendering",
                                          bed=os.path.basename(bed), step=step)
        total = build_video(frames, bed, out_path, scene_secs, workdir, progress=beat)
        with JOBS_LOCK:
            JOBS[job_id].update(status="done", path=out_path, duration=round(total, 2))
        _write_status(job_id, status="done", bed=os.path.basename(bed),
                      duration=round(total, 2))
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
                    "duration": disk.get("duration"), "bed": disk.get("bed")}
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
    if meta["status"] == "error":
        body["error"] = meta.get("error")
    return jsonify(body)


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
    return jsonify({
        "status": "ok" if not problems else "degraded",
        "ffmpeg": "unavailable — check requirements.txt (imageio-ffmpeg)" if any("ffmpeg" in p for p in problems) else "bundled (imageio-ffmpeg)",
        "audio_beds": beds,
        "problems": problems,
    }), 200 if not problems else 503
