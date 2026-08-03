#!/usr/bin/env python3
"""
generate_frames.py  —  batch image generator for TRNG/PostaraTrend serials.

Reads serials/<slug>/frames.json (config + one prompt per episode), generates each
frame through the Leonardo Production API, and writes it to
assets/serial/<slug>/epNN.jpg so a GitHub Action can commit it.

Design notes:
- Cost first: num_images defaults to 1, alchemy and ultra default off, so each
  frame runs on the cheapest tier that still looks right. A serial of 15 frames
  costs pennies of the API credit.
- Idempotent: a frame whose file already exists is skipped, unless --force is
  passed. So a re-run only fills what is missing, and never double spends.
- Consistency: every frame uses the same modelId, styleUUID, size and grade words,
  which is what keeps the set looking like one series. Set modelId and styleUUID
  from Leonardo Get API Code on a frame you like for an exact match.
- Never fails the whole batch on one frame: a frame that errors is logged and
  skipped, and its episode number is reported at the end so it can be re-run.

Env:
  LEONARDO_API_KEY   required, the Production API key (a GitHub Actions secret)

Usage:
  python tools/generate_frames.py --serial blood-money [--force] [--only 3,7]
"""

import argparse
import json
import os
import sys
import time

import requests

API_BASE = "https://cloud.leonardo.ai/api/rest/v1"
POLL_INTERVAL = 5          # seconds between status checks
POLL_TIMEOUT = 180         # give up on a single frame after this long
HTTP_TIMEOUT = 60


def _headers(key):
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {key}",
    }


def start_generation(session, key, cfg, prompt, negative_prompt):
    """POST one generation. Returns the generationId."""
    body = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "modelId": cfg["modelId"],
        "width": int(cfg.get("width", 832)),
        "height": int(cfg.get("height", 1472)),
        "num_images": int(cfg.get("num_images", 1)),
        "alchemy": bool(cfg.get("alchemy", False)),
        "ultra": bool(cfg.get("ultra", False)),
    }
    if cfg.get("contrast") is not None:
        body["contrast"] = cfg["contrast"]
    if cfg.get("styleUUID"):
        body["styleUUID"] = cfg["styleUUID"]
    r = session.post(f"{API_BASE}/generations", headers=_headers(key),
                     json=body, timeout=HTTP_TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(
            f"generate failed http {r.status_code}: {(r.text or '')[:300]} "
            f"(if this mentions the model, set config.modelId from Leonardo Get API Code)")
    data = r.json()
    job = data.get("sdGenerationJob") or {}
    gen_id = job.get("generationId")
    if not gen_id:
        raise RuntimeError(f"no generationId in response: {json.dumps(data)[:300]}")
    return gen_id, job.get("apiCreditCost")


def wait_for_image(session, key, gen_id):
    """Poll one generation until COMPLETE. Returns the first image URL."""
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        r = session.get(f"{API_BASE}/generations/{gen_id}", headers=_headers(key),
                        timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            raise RuntimeError(f"poll failed http {r.status_code}: {(r.text or '')[:200]}")
        gen = (r.json() or {}).get("generations_by_pk") or {}
        status = str(gen.get("status") or "").upper()
        if status == "COMPLETE":
            images = gen.get("generated_images") or []
            if not images or not images[0].get("url"):
                raise RuntimeError("generation complete but no image url returned")
            return images[0]["url"]
        if status == "FAILED":
            raise RuntimeError("generation reported FAILED")
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"timed out after {POLL_TIMEOUT}s waiting for the image")


def download(session, url, dest_path):
    r = session.get(url, timeout=HTTP_TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"download failed http {r.status_code}")
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(r.content)
    return len(r.content)


def run(serial, force=False, only=None, session=None, key=None, repo_root="."):
    session = session or requests.Session()
    key = key or os.environ.get("LEONARDO_API_KEY", "").strip()
    if not key:
        print("ERROR: LEONARDO_API_KEY is not set", file=sys.stderr)
        return 2

    spec_path = os.path.join(repo_root, "serials", serial, "frames.json")
    with open(spec_path) as f:
        spec = json.load(f)
    cfg = spec["config"]
    frames = spec["frames"]
    out_dir = os.path.join(repo_root, "assets", "serial", serial)

    made, skipped, failed = [], [], []
    for fr in frames:
        n = fr["episode_no"]
        if only and n not in only:
            continue
        dest = os.path.join(out_dir, fr["filename"])
        if os.path.exists(dest) and not force:
            print(f"ep{n:02d}: exists, skipping (use --force to regenerate)")
            skipped.append(n)
            continue
        try:
            print(f"ep{n:02d}: generating...")
            gen_id, cost = start_generation(session, key, cfg, fr["prompt"],
                                            fr.get("negative_prompt", ""))
            url = wait_for_image(session, key, gen_id)
            size = download(session, url, dest)
            print(f"ep{n:02d}: saved {fr['filename']} ({size} bytes, credit {cost})")
            made.append(n)
        except Exception as exc:                              # noqa: BLE001
            print(f"ep{n:02d}: FAILED, {exc}", file=sys.stderr)
            failed.append(n)

    print(f"\nDone. made={made} skipped={skipped} failed={failed}")
    return 1 if failed else 0


def _parse_only(s):
    if not s:
        return None
    return {int(x) for x in str(s).replace(" ", "").split(",") if x}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default="blood-money")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    sys.exit(run(a.serial, force=a.force, only=_parse_only(a.only)))
