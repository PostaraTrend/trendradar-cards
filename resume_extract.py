"""
Role Scout resume extraction endpoint (added Jul 2026, RS PL 001)
================================================================
POST /extract          -> raw docx or pdf bytes in, JSON text out
GET  /extract/health   -> dependency and version report
POST /extract/check    -> public readability check for the free resume
                          check page: facts only, never the text (added
                          Aug 2026, SOP-016 CP-016-02)

v1.2 (Aug 27 2026, SOP-016 CP-016-08): LinkedIn data export ZIPs are read
too. A ZIP that holds word/document.xml is a Word file as before; a ZIP
that holds Profile.csv or Positions.csv is a LinkedIn export and is turned
into resume shaped text (CONTACT, SUMMARY, EXPERIENCE, EDUCATION, SKILLS,
CERTIFICATIONS, OTHER) so the parse lane transcribes it unchanged. Birth
date, maiden name and street address are never carried over. kind is
"linkedin" on both routes.

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

EXTRACT_VERSION = "1.2"
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


def _zip_kind(data):
    """A PK archive is either a Word file or a LinkedIn data export."""
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n.replace("\\", "/").split("/")[-1].lower() for n in zf.namelist()]
            full = [n.lower() for n in zf.namelist()]
    except Exception:
        return "docx"  # let the docx reader report the corruption
    if any(n.endswith("word/document.xml") for n in full):
        return "docx"
    if "profile.csv" in names or "positions.csv" in names:
        return "linkedin"
    return "unknown"


def _li_rows(zf, wanted):
    """Rows of one CSV inside the export, matched by file name, as dicts with
    lower case keys. Missing file or unreadable content gives an empty list."""
    import csv
    import io
    for name in zf.namelist():
        if name.replace("\\", "/").split("/")[-1].lower() == wanted.lower():
            try:
                raw = zf.read(name).decode("utf-8-sig", errors="replace")
            except Exception:
                return []
            lines = raw.splitlines()
            # Connections.csv starts with a Notes: paragraph and a blank
            # line before the header; drop that preamble only.
            if lines and lines[0].strip().lower().startswith("notes:"):
                while lines and lines[0].strip():
                    lines.pop(0)
                while lines and not lines[0].strip():
                    lines.pop(0)
            reader = csv.DictReader(io.StringIO("\n".join(lines)))
            out = []
            for row in reader:
                if not row:
                    continue
                out.append({(k or "").strip().lower(): (v or "").strip() for k, v in row.items()})
            return out
    return []


def _li_span(a, b, ongoing="Present"):
    """(start to end). ongoing is the word used when there is no end date;
    pass an empty string for things that simply have a date, like a
    certificate, so it reads (Mar 2022) rather than (Mar 2022 to Present)."""
    a = (a or "").strip()
    b = (b or "").strip()
    if not a and not b:
        return ""
    if not b:
        return "(%s)" % a if not ongoing else "(%s to %s)" % (a, ongoing)
    return "(%s to %s)" % (a or "Unknown", b)


def _extract_linkedin(data):
    """LinkedIn data export ZIP to resume shaped text, one fact per line,
    under the section names the parse lane already uses."""
    import io
    import zipfile
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        prof = _li_rows(zf, "Profile.csv")
        p = prof[0] if prof else {}
        out.append("CONTACT")
        name = ("%s %s" % (p.get("first name", ""), p.get("last name", ""))).strip()
        if name:
            out.append(name)
        if p.get("headline"):
            out.append(p["headline"])
        if p.get("geo location"):
            out.append(p["geo location"])
        emails = _li_rows(zf, "Email Addresses.csv")
        primary = [e for e in emails if e.get("primary", "").lower() == "yes"] or emails
        if primary and primary[0].get("email address"):
            out.append(primary[0]["email address"])
        phones = _li_rows(zf, "PhoneNumbers.csv")
        if phones and phones[0].get("number"):
            out.append(phones[0]["number"])
        for w in (p.get("websites") or "").split(","):
            w = w.strip().strip("[]")
            if w:
                out.append(w.split(":", 1)[-1].strip() if w.upper().startswith(("OTHER:", "PERSONAL:", "COMPANY:", "BLOG:", "PORTFOLIO:", "RSS:")) else w)
        if p.get("summary"):
            out.append("")
            out.append("SUMMARY")
            for ln in p["summary"].splitlines():
                if ln.strip():
                    out.append(ln.strip())
        positions = _li_rows(zf, "Positions.csv")
        if positions:
            out.append("")
            out.append("EXPERIENCE")
            for r in positions:
                head = ", ".join(x for x in (r.get("title"), r.get("company name"), r.get("location")) if x)
                span = _li_span(r.get("started on"), r.get("finished on"))
                out.append((head + " " + span).strip())
                for ln in (r.get("description") or "").splitlines():
                    if ln.strip():
                        out.append(ln.strip())
        edu = _li_rows(zf, "Education.csv")
        if edu:
            out.append("")
            out.append("EDUCATION")
            for r in edu:
                head = ", ".join(x for x in (r.get("degree name"), r.get("school name")) if x)
                span = _li_span(r.get("start date"), r.get("end date"))
                out.append((head + " " + span).strip())
                for key in ("notes", "activities"):
                    for ln in (r.get(key) or "").splitlines():
                        if ln.strip():
                            out.append(ln.strip())
        skills = [r.get("name") for r in _li_rows(zf, "Skills.csv") if r.get("name")]
        if skills:
            out.append("")
            out.append("SKILLS")
            for i in range(0, len(skills), 8):
                out.append(", ".join(skills[i:i + 8]))
        certs = _li_rows(zf, "Certifications.csv")
        if certs:
            out.append("")
            out.append("CERTIFICATIONS")
            for r in certs:
                head = ", ".join(x for x in (r.get("name"), r.get("authority")) if x)
                span = _li_span(r.get("started on"), r.get("finished on"), ongoing="")
                out.append((head + " " + span).strip())
        other = []
        for r in _li_rows(zf, "Projects.csv"):
            head = "Project: " + ", ".join(x for x in (r.get("title"),) if x)
            other.append((head + " " + _li_span(r.get("started on"), r.get("finished on"))).strip())
            for ln in (r.get("description") or "").splitlines():
                if ln.strip():
                    other.append(ln.strip())
        for r in _li_rows(zf, "Volunteering.csv"):
            head = "Volunteering: " + ", ".join(x for x in (r.get("role"), r.get("company name"), r.get("cause")) if x)
            other.append((head + " " + _li_span(r.get("started on"), r.get("finished on"))).strip())
            for ln in (r.get("description") or "").splitlines():
                if ln.strip():
                    other.append(ln.strip())
        langs = [", ".join(x for x in (r.get("name"), r.get("proficiency")) if x) for r in _li_rows(zf, "Languages.csv") if r.get("name")]
        if langs:
            other.append("Languages: " + "; ".join(langs))
        for r in _li_rows(zf, "Honors.csv"):
            if r.get("title"):
                other.append("Honour: " + r["title"] + (" " + _li_span(r.get("issued on"), "") if r.get("issued on") else ""))
        for r in _li_rows(zf, "Publications.csv"):
            if r.get("name"):
                other.append("Publication: " + r["name"] + ((", " + r["publisher"]) if r.get("publisher") else ""))
        if other:
            out.append("")
            out.append("OTHER")
            out.extend(other)
    text = "\n".join(out)
    pages = max(1, (len(text) + DOCX_CHARS_PER_PAGE - 1) // DOCX_CHARS_PER_PAGE)
    return text, pages


def _read_any(data):
    """Shared detection and extraction. Returns (kind, text, pages) or raises
    ValueError with a short reason the caller maps to a status."""
    if not data or len(data) < 8:
        raise ValueError("empty")
    if data[:4] == b"PK\x03\x04":
        kind = _zip_kind(data)
        if kind == "unknown":
            raise ValueError("type")
    elif data[:5] == b"%PDF-":
        kind = "pdf"
    else:
        raise ValueError("type")
    if kind == "docx":
        if not _docx_available():
            raise ValueError("nodocx")
        text, pages = _extract_docx(data)
    elif kind == "linkedin":
        text, pages = _extract_linkedin(data)
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

    try:
        kind, text, pages = _read_any(data)
    except ValueError as exc:
        reason = str(exc)
        if reason == "type":
            return jsonify({"ok": False,
                            "error": "unsupported file type, docx, pdf or LinkedIn export zip only"}), 415
        if reason == "nodocx":
            return jsonify({"ok": False, "error": "docx support not installed"}), 503
        if reason == "nopdf":
            return jsonify({"ok": False, "error": "pdf support not installed"}), 503
        return jsonify({"ok": False, "error": "file body required"}), 400
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
            msg = "This file type could not be read. Please upload a PDF, a Word document, or your LinkedIn data export ZIP."
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
    if kind == "linkedin" and len(lines) < 3:
        readable = False
        message = ("The LinkedIn export opened but held almost no profile content. "
                   "Please request the full data archive from LinkedIn and upload that ZIP.")
    elif scanned:
        message = ("This looks like a scanned image rather than a text document. "
                   "Role Scout cannot read the lines yet. Please upload the original file.")
    elif too_long:
        message = "This file is longer than fifteen pages. Please upload a shorter version."
    elif not lines:
        message = "The file opened but no text was found inside it."
    elif kind == "linkedin":
        message = "Role Scout can read this LinkedIn export."
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
