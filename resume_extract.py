"""
Role Scout resume extraction endpoint (added Jul 2026, RS PL 001)
================================================================
POST /extract          -> raw docx or pdf bytes in, JSON text out
GET  /extract/health   -> dependency and version report
POST /extract/check    -> public readability check for the free resume
                          check page: facts only, never the text (added
                          Aug 2026, SOP-016 CP-016-02)

Purpose: the parse lane in n8n downloads a stored resume file from
Supabase storage and posts the raw bytes here. This module performs the
mechanical step only: bytes to plain text plus page facts. It never
interprets, never summarizes, never reorders. The transcription model in
the lane does the line and section work afterwards, per RS PL 001.

Detection is by magic bytes, not filename: PK.. means docx (zip
container), %PDF means pdf. Anything else returns 415.

Response shape on success:
  {ok: true, kind: "docx"|"pdf", pages: int, chars: int,
   scanned: bool, truncated: bool, text: "..."}
pages for a pdf is the true page count; for a docx it is an estimate
from character volume (about 1800 characters per page), minimum 1.
scanned is true when a pdf has pages but effectively no text layer
(under 40 characters per page on average). The lane turns scanned into
parse_failed with a plain message, per the approved design: OCR is
deferred, honesty over guessing.

House rules honoured: no import time downloads or raises (lazy imports,
missing dependencies reported by health, never fatal to the app), no
worker memory, stateless, single request in and out.

/extract/check is the one route the browser calls directly, from the
public free resume check page, so it answers OPTIONS preflights, sends
open CORS headers, caps the body at 20 MB, and rate limits by client
address (a small in memory counter per worker; it resets on deploy,
which is acceptable for abuse braking). It returns whether the file is
readable, the kind, page count, character count and scanned flag, and a
short preview of the first lines so the visitor sees Role Scout read the
right file. The full text is never returned on this route and nothing
is stored. /extract itself is unchanged and stays lane only.
"""

from flask import Blueprint, request, jsonify, Response
import time as _time
import threading as _threading

extract_bp = Blueprint("extract", __name__)

EXTRACT_VERSION = "1.1"
CHECK_MAX_BYTES = 20 * 1024 * 1024
CHECK_LIMIT_PER_HOUR = 12
CHECK_PREVIEW_CHARS = 600
_CHECK_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}
_check_hits = {}
_check_lock = _threading.Lock()


def _client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _check_rate_ok(ip):
    """Allows CHECK_LIMIT_PER_HOUR calls per address per rolling hour."""
    now = _time.time()
    with _check_lock:
        hits = [t for t in _check_hits.get(ip, []) if now - t < 3600]
        if len(hits) >= CHECK_LIMIT_PER_HOUR:
            _check_hits[ip] = hits
            return False
        hits.append(now)
        _check_hits[ip] = hits
        if len(_check_hits) > 5000:
            for k in [k for k, v in _check_hits.items() if not v or now - v[-1] > 3600]:
                _check_hits.pop(k, None)
        return True


def _with_check_cors(resp):
    for k, v in _CHECK_CORS.items():
        resp.headers[k] = v
    return resp


def _read_any(data):
    """Shared detection and extraction. Returns (kind, text, pages) or raises
    ValueError with a short reason the caller maps to a status."""
    if not data or len(data) < 8:
        raise ValueError("empty")
    if data[:4] == b"PK\x03\x04":
        kind = "docx"
    elif data[:5] == b"%PDF-":
        kind = "pdf"
    else:
        raise ValueError("type")
    if kind == "docx":
        if not _docx_available():
            raise ValueError("nodocx")
        text, pages = _extract_docx(data)
    else:
        if not _pdf_available():
            raise ValueError("nopdf")
        text, pages = _extract_pdf(data)
    return kind, text, pages
TEXT_CHAR_CAP = 250000
DOCX_CHARS_PER_PAGE = 1800
SCANNED_CHARS_PER_PAGE = 40


def _docx_available():
    try:
        import docx  # noqa: F401
        return True
    except Exception:
        return False


def _pdf_available():
    try:
        import pypdf  # noqa: F401
        return True
    except Exception:
        return False


def _extract_docx(data):
    """Paragraphs in document order, then table cells row by row.
    Verbatim text only. Empty paragraphs are dropped because they are
    layout, not content."""
    from io import BytesIO
    from docx import Document
    doc = Document(BytesIO(data))
    parts = []
    for para in doc.paragraphs:
        t = (para.text or "").strip()
        if t:
            parts.append(t)
    for table in doc.tables:
        for row in table.rows:
            cells = [(c.text or "").strip() for c in row.cells]
            cells = [c for c in cells if c]
            if cells:
                parts.append("  ".join(cells))
    text = "\n".join(parts)
    pages = max(1, (len(text) + DOCX_CHARS_PER_PAGE - 1) // DOCX_CHARS_PER_PAGE)
    return text, pages


def _extract_pdf(data):
    from io import BytesIO
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(data))
    pages = len(reader.pages)
    chunks = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            chunks.append("")
    text = "\n".join(chunks).strip()
    return text, pages


@extract_bp.get("/extract/health")
def extract_health():
    docx_ok = _docx_available()
    pdf_ok = _pdf_available()
    return jsonify({
        "ok": docx_ok and pdf_ok,
        "version": EXTRACT_VERSION,
        "docx": docx_ok,
        "pdf": pdf_ok,
        "text_char_cap": TEXT_CHAR_CAP,
        "check": {"max_bytes": CHECK_MAX_BYTES, "limit_per_hour": CHECK_LIMIT_PER_HOUR},
    })


@extract_bp.post("/extract")
def extract():
    data = request.get_data()
    if not data or len(data) < 8:
        return jsonify({"ok": False, "error": "file body required"}), 400

    if data[:4] == b"PK\x03\x04":
        kind = "docx"
    elif data[:5] == b"%PDF-":
        kind = "pdf"
    else:
        return jsonify({"ok": False,
                        "error": "unsupported file type, docx or pdf only"}), 415

    try:
        if kind == "docx":
            if not _docx_available():
                return jsonify({"ok": False,
                                "error": "docx support not installed"}), 503
            text, pages = _extract_docx(data)
        else:
            if not _pdf_available():
                return jsonify({"ok": False,
                                "error": "pdf support not installed"}), 503
            text, pages = _extract_pdf(data)
    except Exception as exc:  # unreadable or corrupt file
        return jsonify({"ok": False,
                        "error": "file could not be read: %s" % exc.__class__.__name__}), 422

    scanned = False
    if kind == "pdf" and pages > 0:
        scanned = (len(text) / pages) < SCANNED_CHARS_PER_PAGE

    truncated = len(text) > TEXT_CHAR_CAP
    if truncated:
        text = text[:TEXT_CHAR_CAP]

    return jsonify({
        "ok": True,
        "kind": kind,
        "pages": pages,
        "chars": len(text),
        "scanned": scanned,
        "truncated": truncated,
        "text": text,
    })


@extract_bp.route("/extract/check", methods=["POST", "OPTIONS"])
def extract_check():
    """Public readability check for the free resume check page.
    Facts only, never the text, nothing stored."""
    if request.method == "OPTIONS":
        return _with_check_cors(Response(status=204))
    ip = _client_ip()
    if not _check_rate_ok(ip):
        return _with_check_cors(jsonify({
            "ok": False, "readable": False,
            "message": "Too many checks from this connection. Please try again in an hour."}))\
            , 429
    length = request.content_length or 0
    if length > CHECK_MAX_BYTES:
        return _with_check_cors(jsonify({
            "ok": False, "readable": False,
            "message": "That file is larger than 20 MB. Please upload a smaller PDF or Word file."})), 413
    data = request.get_data()
    if data and len(data) > CHECK_MAX_BYTES:
        return _with_check_cors(jsonify({
            "ok": False, "readable": False,
            "message": "That file is larger than 20 MB. Please upload a smaller PDF or Word file."})), 413
    try:
        kind, text, pages = _read_any(data)
    except ValueError as exc:
        reason = str(exc)
        if reason == "type":
            msg = "This file type could not be read. Please upload a PDF or Word document."
            code = 415
        elif reason in ("nodocx", "nopdf"):
            msg = "The reader is unavailable at the moment. Please try again shortly."
            code = 503
        else:
            msg = "No file was received. Please choose a PDF or Word document."
            code = 400
        return _with_check_cors(jsonify({"ok": False, "readable": False, "message": msg})), code
    except Exception as exc:  # unreadable or corrupt file
        return _with_check_cors(jsonify({
            "ok": False, "readable": False,
            "message": "The file could not be opened. Please try uploading it again."})), 422

    scanned = False
    if kind == "pdf" and pages > 0:
        scanned = (len(text) / pages) < SCANNED_CHARS_PER_PAGE
    too_long = pages > 15
    readable = (len(text) > 0) and (not scanned) and (not too_long)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    preview = []
    used = 0
    for ln in lines:
        if used + len(ln) > CHECK_PREVIEW_CHARS:
            break
        preview.append(ln)
        used += len(ln)
    if scanned:
        message = ("This looks like a scanned image rather than a text document. "
                   "Role Scout cannot read the lines yet. Please upload the original file.")
    elif too_long:
        message = "This file is longer than fifteen pages. Please upload a shorter version."
    elif not lines:
        message = "The file opened but no text was found inside it."
    else:
        message = "Role Scout can read this file."
    return _with_check_cors(jsonify({
        "ok": True,
        "readable": readable,
        "kind": kind,
        "pages": pages,
        "chars": len(text),
        "lines": len(lines),
        "scanned": scanned,
        "too_long": too_long,
        "preview": preview,
        "message": message,
    }))
