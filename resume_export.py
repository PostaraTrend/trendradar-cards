"""
Role Scout resume export (added Jul 2026, verification link build)
==================================================================
POST /export/resume        -> renders a verified tailored resume as a
                              downloadable PDF or Word document (binary)
GET  /export/resume/health -> reports pdf and docx renderer availability

Contract (JSON body):
{
  "format": "pdf" | "docx",
  "seeker_name": "Full Name",
  "contact_lines": ["optional strings under the name"],
  "posting": {"title": "...", "employer": "...", "location": "..."},
  "sections": [{"title": "SUMMARY", "lines": ["...", "..."]}],
  "verified_at": "2026-07-28",       optional
  "attested_version": 2              optional
}

sections is the only required content field. When verified_at and
attested_version are both present, a single quiet verification footer
line renders at the end of the document; when either is absent the
document renders with no footer, so the caller controls inclusion.

Output is deliberately ATS shaped: one column, standard fonts, plain
uppercase section headings, no tables, no graphics. The content arrives
already verified by the tailor lane, so this module renders mechanically
and applies no content gates.

CORS: the Role Scout app in the browser calls this route directly, so
the blueprint answers OPTIONS preflights and sends open CORS headers on
its responses. The route holds no secrets and writes nothing.

Lazy imports per the resume_extract pattern: a missing dependency
degrades to a 503 on this route instead of breaking the app at import.
Stateless, no worker memory.
"""

from flask import Blueprint, request, Response, send_file
from io import BytesIO
import json as _json
import re as _re

export_bp = Blueprint("resume_export", __name__)

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


@export_bp.after_request
def _add_cors(resp):
    for k, v in _CORS_HEADERS.items():
        resp.headers[k] = v
    return resp


def _pdf_ready():
    try:
        import reportlab  # noqa: F401
        return True
    except Exception:
        return False


def _docx_ready():
    try:
        import docx  # noqa: F401
        return True
    except Exception:
        return False


def _err(msg, status):
    return Response(_json.dumps({"error": msg}), status=status,
                    mimetype="application/json")


def _safe_name(*parts):
    """Builds a filesystem safe download name from name and posting parts."""
    joined = "_".join(p for p in parts if p)
    cleaned = _re.sub(r"[^A-Za-z0-9]+", "_", joined).strip("_")
    return cleaned or "Tailored_Resume"


def _read_payload(req):
    data = req.get_json(silent=True)
    if not isinstance(data, dict):
        raw = req.get_data(as_text=True) or ""
        try:
            data = _json.loads(raw)
        except Exception:
            data = None
    if not isinstance(data, dict):
        return None, _err("JSON body required", 400)

    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        return None, _err("sections is required and must be a non empty list", 422)
    clean_sections = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        title = str(sec.get("title") or "").strip()
        lines = [str(x).strip() for x in (sec.get("lines") or []) if str(x).strip()]
        if lines:
            clean_sections.append({"title": title, "lines": lines})
    if not clean_sections:
        return None, _err("sections contained no usable lines", 422)

    posting = data.get("posting") if isinstance(data.get("posting"), dict) else {}
    payload = {
        "format": str(data.get("format") or "pdf").strip().lower(),
        "seeker_name": str(data.get("seeker_name") or "").strip(),
        "contact_lines": [str(x).strip() for x in (data.get("contact_lines") or [])
                          if str(x).strip()],
        "posting_title": str(posting.get("title") or "").strip(),
        "posting_employer": str(posting.get("employer") or "").strip(),
        "sections": clean_sections,
        "verified_at": str(data.get("verified_at") or "").strip(),
        "attested_version": data.get("attested_version"),
    }
    if payload["format"] not in ("pdf", "docx"):
        return None,
