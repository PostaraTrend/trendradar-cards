"""
Role Scout resume export (added Jul 2026, verification link build)
==================================================================
POST /export/resume        -> renders a verified tailored resume as a
                              downloadable PDF or Word document (binary)
GET  /export/resume/health -> reports pdf, docx and qr renderer availability

Contract (JSON body):
{
  "format": "pdf" | "docx",
  "template": "classic" | "compact" | "plain",   optional, default classic
  "seeker_name": "Full Name",
  "contact_lines": ["optional strings under the name"],
  "posting": {"title": "...", "employer": "...", "location": "..."},
  "sections": [{"title": "SUMMARY", "lines": ["...", "..."]}],
  "verified_at": "2026-07-28",       optional
  "attested_version": 2,             optional
  "verify_url": "https://.../verify/abc123"   optional
}

sections is the only required content field. When verified_at and
attested_version are both present, a single quiet verification footer
line renders at the end of the document; when either is absent the
document renders with no footer, so the caller controls inclusion.

When the footer renders AND verify_url is present, a small QR code
linking to that URL renders directly beneath the footer line, captioned
"Scan before you call. Confirm this resume was not altered from the
candidate's verified source." The caption names the moment a recruiter
is actually in (right before deciding whether to call the candidate)
rather than only describing the mechanism, so the code is more likely to
get used. The QR is intentionally gated behind the same verified_at and
attested_version facts as the footer text, not on verify_url alone, so a
document can never carry a scannable link to a verification page without
the printed sentence that explains what the scan confirms. If the qr
rendering dependency is unavailable, or code generation fails for any
reason, the document still renders in full with the footer text alone;
QR is additive and never blocks export.

Output is deliberately ATS shaped: one column, standard fonts, plain
uppercase section headings, no tables, no graphics other than the
optional verification QR described above. Three templates share that
shape and differ only in type size, spacing and colour: classic (the
original), compact (tighter, for long resumes that should fit two pages),
and plain (Times, black only, the most conservative parse). The content
arrives already verified by the tailor lane, so this module renders
mechanically and applies no content gates.

CORS: the Role Scout app in the browser calls this route directly, so
the blueprint answers OPTIONS preflights and sends open CORS headers on
its responses. The route holds no secrets and writes nothing.

Lazy imports per the resume_extract pattern: a missing dependency
degrades to a 503 on this route instead of breaking the app at import
(pdf, docx), or degrades to a silently omitted QR (qr, additive only).
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
    "Access-Control-Expose-Headers": "Content-Disposition",
    "Access-Control-Max-Age": "86400",
}


# Template parameters. Every template is one column with plain uppercase
# section headings and no tables, so all three parse the same way; they differ
# in type size, spacing and colour only. pdf_font is the reportlab base font
# name, docx_font the Word font name.
_TEMPLATES = {
    "classic": {
        "pdf_font": "Helvetica", "docx_font": "Calibri",
        "name": 18, "contact": 9.5, "section": 11.5, "heading": 10.5, "body": 10,
        "footer": 8, "section_before": 13, "section_after": 4, "heading_before": 8,
        "body_after": 2, "leading_ratio": 1.4, "section_color": "#1F2A44",
        "margin_x": 0.9, "margin_y": 0.7,
    },
    "compact": {
        "pdf_font": "Helvetica", "docx_font": "Calibri",
        "name": 16, "contact": 9, "section": 10.5, "heading": 10, "body": 9.5,
        "footer": 7.5, "section_before": 9, "section_after": 2, "heading_before": 5,
        "body_after": 1, "leading_ratio": 1.3, "section_color": "#1F2A44",
        "margin_x": 0.75, "margin_y": 0.6,
    },
    "plain": {
        "pdf_font": "Times-Roman", "docx_font": "Times New Roman",
        "name": 16, "contact": 10, "section": 11, "heading": 11, "body": 10.5,
        "footer": 8, "section_before": 12, "section_after": 3, "heading_before": 7,
        "body_after": 2, "leading_ratio": 1.35, "section_color": "#000000",
        "margin_x": 1.0, "margin_y": 0.8,
    },
}

# The line printed beneath the verification QR on both export formats. It
# names the moment the recruiter is in (right before deciding whether to
# call the candidate) so the code is more likely to get scanned, not just
# noticed.
_QR_CAPTION = ("Scan before you call. Confirm this resume was not altered "
               "from the candidate's verified source.")


def _template(payload):
    return _TEMPLATES.get(payload.get("template") or "classic", _TEMPLATES["classic"])


def _pdf_bold(base):
    """Maps a reportlab base font to its bold face."""
    return "Times-Bold" if base == "Times-Roman" else "Helvetica-Bold"


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


def _qr_ready():
    try:
        import qrcode  # noqa: F401
        return True
    except Exception:
        return False


def _generate_qr_png(url):
    """Builds a small QR code PNG in memory for the given URL.

    Returns a BytesIO positioned at 0, or None on any failure (missing
    dependency, bad url, encoding error). QR is additive, so a failure
    here must never break the surrounding document render.
    """
    if not url:
        return None
    try:
        import qrcode
        img = qrcode.make(url, box_size=6, border=2)
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception:
        return None


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
        # The internal OTHER category is a catch all, never a real heading.
        # Blank it so those lines render with no section label to the employer.
        if title.upper() == "OTHER":
            title = ""
        out_lines = []
        for x in (sec.get("lines") or []):
            if isinstance(x, dict):
                txt = str(x.get("text") or "").strip()
                is_heading = bool(x.get("heading"))
            else:
                txt = str(x).strip()
                is_heading = False
            if not txt:
                continue
            stripped = _re.sub(r"^[\u2022\u2023\u25E6\u2043\-\*]\s+", "", txt)
            out_lines.append({"text": stripped, "heading": is_heading})
        # promote an employer line: a non heading line directly above a role or date
        # heading that is not a full sentence, so employers render as sub headings not bullets
        orig_flags = [ln["heading"] for ln in out_lines]
        for _i in range(len(out_lines) - 1):
            if not orig_flags[_i] and orig_flags[_i + 1]:
                _t = out_lines[_i]["text"].rstrip()
                if _t and _t[-1] not in ".!?":
                    out_lines[_i]["heading"] = True
        if out_lines:
            clean_sections.append({"title": title, "lines": out_lines})
    if not clean_sections:
        return None, _err("sections contained no usable lines", 422)

    posting = data.get("posting") if isinstance(data.get("posting"), dict) else {}
    payload = {
        "format": str(data.get("format") or "pdf").strip().lower(),
        "template": str(data.get("template") or "classic").strip().lower(),
        "seeker_name": str(data.get("seeker_name") or "").strip(),
        "contact_lines": [str(x).strip() for x in (data.get("contact_lines") or [])
                          if str(x).strip()],
        "posting_title": str(posting.get("title") or "").strip(),
        "posting_employer": str(posting.get("employer") or "").strip(),
        "posting_location": str(posting.get("location") or "").strip(),
        "sections": clean_sections,
        "verified_at": str(data.get("verified_at") or "").strip(),
        "attested_version": data.get("attested_version"),
        "verify_url": str(data.get("verify_url") or "").strip(),
    }
    if payload["format"] not in ("pdf", "docx"):
        return None, _err("format must be pdf or docx", 422)
    if payload["template"] not in _TEMPLATES:
        return None, _err("template must be classic, compact or plain", 422)
    return payload, None


_FOOTER_TEMPLATE = ("Verified by TraceScout against Version {v} of the attested "
                    "source resume on {d}. Every line traces to attested content. "
                    "Nothing was invented.")


def _footer_line(payload):
    """Returns the verification footer, or None when either fact is absent."""
    v = payload.get("attested_version")
    d = payload.get("verified_at")
    if v in (None, "") or not d:
        return None
    return _FOOTER_TEMPLATE.format(v=v, d=d)


def _render_pdf(payload):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Image, Spacer
    from xml.sax.saxutils import escape

    t = _template(payload)
    base, bold = t["pdf_font"], _pdf_bold(t["pdf_font"])
    lr = t["leading_ratio"]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=t["margin_x"] * inch, rightMargin=t["margin_x"] * inch,
                            topMargin=t["margin_y"] * inch, bottomMargin=t["margin_y"] * inch,
                            title=payload["seeker_name"] or "Resume")
    name_style = ParagraphStyle("name", fontName=bold, fontSize=t["name"],
                                leading=round(t["name"] * 1.2), alignment=TA_LEFT, spaceAfter=2)
    contact_style = ParagraphStyle("contact", fontName=base, fontSize=t["contact"],
                                   leading=round(t["contact"] * lr), spaceAfter=1)
    section_style = ParagraphStyle("section", fontName=bold,
                                   fontSize=t["section"], leading=round(t["section"] * 1.3),
                                   spaceBefore=t["section_before"],
                                   spaceAfter=t["section_after"], textColor=t["section_color"])
    heading_style = ParagraphStyle("subhead", fontName=bold,
                                   fontSize=t["heading"], leading=round(t["heading"] * lr),
                                   spaceBefore=t["heading_before"], spaceAfter=1)
    bullet_style = ParagraphStyle("bullet", fontName=base, fontSize=t["body"],
                                  leading=round(t["body"] * lr), leftIndent=14, bulletIndent=2,
                                  spaceAfter=t["body_after"])
    footer_style = ParagraphStyle("footer", fontName=base, fontSize=t["footer"],
                                  leading=round(t["footer"] * lr), textColor="#000000" if payload.get("template") == "plain" else "#555555",
                                  spaceBefore=14)
    qr_caption_style = ParagraphStyle("qrcaption", fontName=base, fontSize=t["footer"],
                                      leading=round(t["footer"] * lr), textColor="#000000" if payload.get("template") == "plain" else "#555555",
                                      alignment=TA_CENTER, spaceBefore=3)

    story = []
    if payload["seeker_name"]:
        story.append(Paragraph(escape(payload["seeker_name"]), name_style))
    for line in payload["contact_lines"]:
        story.append(Paragraph(escape(line), contact_style))
    for sec in payload["sections"]:
        if sec["title"]:
            story.append(Paragraph(escape(sec["title"].upper()), section_style))
        for item in sec["lines"]:
            if item["heading"]:
                story.append(Paragraph(escape(item["text"]), heading_style))
            else:
                story.append(Paragraph(escape(item["text"]), bullet_style,
                                       bulletText=u"\u2022"))
    footer = _footer_line(payload)
    if footer:
        story.append(Paragraph(escape(footer), footer_style))
        qr_buf = _generate_qr_png(payload.get("verify_url")) if _qr_ready() else None
        if qr_buf is not None:
            qr_size = 0.85 * inch
            qr_img = Image(qr_buf, width=qr_size, height=qr_size)
            qr_img.hAlign = "CENTER"
            story.append(Spacer(1, 6))
            story.append(qr_img)
            story.append(Paragraph(escape(_QR_CAPTION), qr_caption_style))
    doc.build(story)
    buf.seek(0)
    return buf


def _apply_docx_layout(document, template):
    from docx.shared import Inches, Pt

    for section in document.sections:
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.left_margin = section.right_margin = Inches(template["margin_x"])
        section.top_margin = section.bottom_margin = Inches(template["margin_y"])
    for name in ("Normal", "List Bullet"):
        style = document.styles[name]
        style.font.name = template["docx_font"]
        style.font.size = Pt(template["body"])
        style.paragraph_format.line_spacing = template["leading_ratio"]
        style.paragraph_format.space_after = Pt(template["body_after"])


def _render_docx(payload):
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    t = _template(payload)
    d = Document()
    _apply_docx_layout(d, t)
    sec_rgb = RGBColor(int(t["section_color"][1:3], 16), int(t["section_color"][3:5], 16),
                       int(t["section_color"][5:7], 16))

    def _run(par, text, size, bold=False, color=None):
        r = par.add_run(text)
        r.font.name = t["docx_font"]
        r.font.size = Pt(size)
        r.bold = bold
        if color is not None:
            r.font.color.rgb = color
        return r

    if payload["seeker_name"]:
        p = d.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.2
        p.paragraph_format.keep_with_next = True
        _run(p, payload["seeker_name"], t["name"], bold=True)
    for line in payload["contact_lines"]:
        p = d.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.keep_with_next = True
        _run(p, line, t["contact"])
    for sec in payload["sections"]:
        if sec["title"]:
            p = d.add_paragraph()
            p.paragraph_format.space_before = Pt(t["section_before"])
            p.paragraph_format.space_after = Pt(t["section_after"])
            p.paragraph_format.keep_with_next = True
            _run(p, sec["title"].upper(), t["section"], bold=True, color=sec_rgb)
        for item in sec["lines"]:
            if item["heading"]:
                p = d.add_paragraph()
                p.paragraph_format.space_before = Pt(t["heading_before"])
                p.paragraph_format.space_after = Pt(1)
                p.paragraph_format.keep_with_next = True
                _run(p, item["text"], t["heading"], bold=True)
            else:
                _run(d.add_paragraph(style="List Bullet"), item["text"], t["body"])
    footer = _footer_line(payload)
    if footer:
        _run(d.add_paragraph(), footer, t["footer"], color=RGBColor(0, 0, 0) if payload.get("template") == "plain" else RGBColor(0x55, 0x55, 0x55))
        qr_buf = _generate_qr_png(payload.get("verify_url")) if _qr_ready() else None
        if qr_buf is not None:
            qr_par = d.add_paragraph()
            qr_par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            qr_par.add_run().add_picture(qr_buf, width=Inches(0.85))
            caption_par = d.add_paragraph()
            caption_par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _run(caption_par, _QR_CAPTION, t["footer"], color=RGBColor(0, 0, 0) if payload.get("template") == "plain" else RGBColor(0x55, 0x55, 0x55))
    buf = BytesIO()
    d.save(buf)
    buf.seek(0)
    return buf


@export_bp.route("/export/resume/health", methods=["GET"])
def export_health():
    body = {"ok": True, "pdf": _pdf_ready(), "docx": _docx_ready(), "qr": _qr_ready(),
            "templates": sorted(_TEMPLATES.keys()), "version": "v1.5"}
    return Response(_json.dumps(body), mimetype="application/json")


@export_bp.route("/export/resume", methods=["POST", "OPTIONS"])
def export_resume():
    if request.method == "OPTIONS":
        return Response(status=204)
    payload, err = _read_payload(request)
    if err is not None:
        return err
    fmt = payload["format"]
    if fmt == "pdf":
        if not _pdf_ready():
            return _err("pdf renderer unavailable on this deploy", 503)
        buf = _render_pdf(payload)
        ext, mime = "pdf", "application/pdf"
    else:
        if not _docx_ready():
            return _err("docx renderer unavailable on this deploy", 503)
        buf = _render_docx(payload)
        ext, mime = "docx", ("application/vnd.openxmlformats-officedocument"
                             ".wordprocessingml.document")
    fname = _safe_name(payload["seeker_name"], payload["posting_title"])
    return send_file(buf, mimetype=mime, as_attachment=True,
                     download_name="{0}.{1}".format(fname, ext))


# ---------------------------------------------------------------------------
# Role Scout cover letter export (added Aug 2026, cover letter build)
# ---------------------------------------------------------------------------
# POST /export/cover        -> renders a verified cover letter as a
#                              downloadable PDF or Word document (binary)
# GET  /export/cover/health -> reports pdf and docx renderer availability
#
# Contract (JSON body):
# {
#   "format": "pdf" | "docx",
#   "template": "classic" | "compact" | "plain", optional, default classic
#   "seeker_name": "Full Name",
#   "contact_lines": ["email", "phone", "city"],   verified contact block
#   "posting": {"title": "...", "employer": "...", "location": "..."},
#   "body": ["Dear Hiring Manager,", "sentence", "sentence", "closing"],
#   "date": "August 19, 2026",     optional
#   "recipient": true,             optional, default true
#   "verified_at": "2026-08-19",   optional
#   "attested_version": 2          optional
# }
#
# body is the only required content field and arrives as the verified
# sentence list the cover letter lane wrote. The contact header is passed
# in from the same verified contact block the resume export uses, so it is
# exact and never model written. As with the resume, the verification
# footer renders only when verified_at and attested_version are both
# present, so the caller controls inclusion. Same blueprint, so the CORS
# handling, the readiness checks, and app.py registration are all reused.
# The cover letter export does not carry the QR code; that stays scoped
# to the resume export where the verification claim is strongest.

_COVER_FOOTER_TEMPLATE = ("Verified by TraceScout against Version {v} of the "
                          "attested source resume on {d}. Every claim traces to "
                          "attested content. Nothing was invented.")


def _cover_footer_line(payload):
    """Returns the cover letter verification footer, or None when a fact is absent."""
    v = payload.get("attested_version")
    d = payload.get("verified_at")
    if v in (None, "") or not d:
        return None
    return _COVER_FOOTER_TEMPLATE.format(v=v, d=d)


def _letter_paragraphs(body):
    """Greeting on its own line, the middle as one flowing paragraph, closing on its own line."""
    if len(body) >= 3:
        return [body[0], " ".join(body[1:-1]), body[-1]]
    return list(body)


def _read_cover_payload(req):
    data = req.get_json(silent=True)
    if not isinstance(data, dict):
        raw = req.get_data(as_text=True) or ""
        try:
            data = _json.loads(raw)
        except Exception:
            data = None
    if not isinstance(data, dict):
        return None, _err("JSON body required", 400)

    body = data.get("body")
    if not isinstance(body, list) or not body:
        return None, _err("body is required and must be a non empty list of sentences", 422)
    body_lines = [str(x).strip() for x in body if str(x).strip()]
    if not body_lines:
        return None, _err("body contained no usable sentences", 422)

    posting = data.get("posting") if isinstance(data.get("posting"), dict) else {}
    payload = {
        "format": str(data.get("format") or "pdf").strip().lower(),
        "template": str(data.get("template") or "classic").strip().lower(),
        "seeker_name": str(data.get("seeker_name") or "").strip(),
        "contact_lines": [str(x).strip() for x in (data.get("contact_lines") or [])
                          if str(x).strip()],
        "posting_title": str(posting.get("title") or "").strip(),
        "posting_employer": str(posting.get("employer") or "").strip(),
        "posting_location": str(posting.get("location") or "").strip(),
        "body": body_lines,
        "date": str(data.get("date") or "").strip(),
        "recipient": bool(data.get("recipient", True)),
        "verified_at": str(data.get("verified_at") or "").strip(),
        "attested_version": data.get("attested_version"),
    }
    if payload["format"] not in ("pdf", "docx"):
        return None, _err("format must be pdf or docx", 422)
    if payload["template"] not in _TEMPLATES:
        return None, _err("template must be classic, compact or plain", 422)
    return payload, None


def _render_cover_pdf(payload):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from xml.sax.saxutils import escape

    t = _template(payload)
    base, bold = t["pdf_font"], _pdf_bold(t["pdf_font"])
    lr = t["leading_ratio"]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=t["margin_x"] * inch, rightMargin=t["margin_x"] * inch,
                            topMargin=t["margin_y"] * inch, bottomMargin=t["margin_y"] * inch,
                            title=payload["seeker_name"] or "Cover Letter")
    name_style = ParagraphStyle("cname", fontName=bold, fontSize=t["name"],
                                leading=round(t["name"] * 1.2), alignment=TA_LEFT, spaceAfter=2)
    contact_style = ParagraphStyle("ccontact", fontName=base, fontSize=t["contact"],
                                   leading=round(t["contact"] * lr), spaceAfter=1)
    meta_style = ParagraphStyle("cmeta", fontName=base, fontSize=t["body"],
                                leading=round(t["body"] * lr))
    body_style = ParagraphStyle("cbody", fontName=base, fontSize=t["body"],
                                leading=round(t["body"] * lr), spaceAfter=t["heading_before"])
    sig_style = ParagraphStyle("csig", fontName=base, fontSize=t["body"],
                               leading=round(t["body"] * lr))
    footer_style = ParagraphStyle("cfooter", fontName=base, fontSize=t["footer"],
                                  leading=round(t["footer"] * lr), textColor="#000000" if payload.get("template") == "plain" else "#555555", spaceBefore=16)

    story = []
    if payload["seeker_name"]:
        story.append(Paragraph(escape(payload["seeker_name"]), name_style))
    for line in payload["contact_lines"]:
        story.append(Paragraph(escape(line), contact_style))
    story.append(Spacer(1, 10))
    if payload["date"]:
        story.append(Paragraph(escape(payload["date"]), meta_style))
        story.append(Spacer(1, 8))
    if payload["recipient"]:
        if payload["posting_title"]:
            story.append(Paragraph(escape("Re: " + payload["posting_title"]), meta_style))
        recip_line = ", ".join(b for b in [payload["posting_employer"],
                                           payload["posting_location"]] if b)
        if recip_line:
            story.append(Paragraph(escape(recip_line), meta_style))
        story.append(Spacer(1, 10))
    for para in _letter_paragraphs(payload["body"]):
        story.append(Paragraph(escape(para), body_style))
    if payload["seeker_name"]:
        story.append(Spacer(1, 6))
        story.append(Paragraph(escape(payload["seeker_name"]), sig_style))
    footer = _cover_footer_line(payload)
    if footer:
        story.append(Paragraph(escape(footer), footer_style))
    doc.build(story)
    buf.seek(0)
    return buf


def _render_cover_docx(payload):
    from docx import Document
    from docx.shared import Pt, RGBColor

    t = _template(payload)
    d = Document()
    _apply_docx_layout(d, t)
    if payload["seeker_name"]:
        p = d.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.2
        p.paragraph_format.keep_with_next = True
        run = p.add_run(payload["seeker_name"])
        run.bold = True
        run.font.size = Pt(t["name"])
    for line in payload["contact_lines"]:
        p = d.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.keep_with_next = True
        p.add_run(line).font.size = Pt(t["contact"])
    if payload["date"]:
        d.add_paragraph()
        p = d.add_paragraph()
        p.add_run(payload["date"]).font.size = Pt(t["body"])
    if payload["recipient"]:
        if payload["posting_title"]:
            p = d.add_paragraph()
            p.add_run("Re: " + payload["posting_title"]).font.size = Pt(t["body"])
        recip_line = ", ".join(b for b in [payload["posting_employer"],
                                           payload["posting_location"]] if b)
        if recip_line:
            p = d.add_paragraph()
            p.add_run(recip_line).font.size = Pt(t["body"])
    d.add_paragraph()
    for para in _letter_paragraphs(payload["body"]):
        p = d.add_paragraph()
        p.paragraph_format.space_after = Pt(t["heading_before"])
        p.add_run(para).font.size = Pt(t["body"])
    if payload["seeker_name"]:
        d.add_paragraph()
        p = d.add_paragraph()
        p.add_run(payload["seeker_name"]).font.size = Pt(t["body"])
    footer = _cover_footer_line(payload)
    if footer:
        p = d.add_paragraph()
        p.paragraph_format.space_before = Pt(16)
        run = p.add_run(footer)
        run.font.size = Pt(t["footer"])
        run.font.color.rgb = RGBColor(0, 0, 0) if payload.get("template") == "plain" else RGBColor(0x55, 0x55, 0x55)
    buf = BytesIO()
    d.save(buf)
    buf.seek(0)
    return buf


@export_bp.route("/export/cover/health", methods=["GET"])
def export_cover_health():
    body = {"ok": True, "pdf": _pdf_ready(), "docx": _docx_ready(),
            "version": "v1.1", "kind": "cover", "templates": sorted(_TEMPLATES.keys())}
    return Response(_json.dumps(body), mimetype="application/json")


@export_bp.route("/export/cover", methods=["POST", "OPTIONS"])
def export_cover():
    if request.method == "OPTIONS":
        return Response(status=204)
    payload, err = _read_cover_payload(request)
    if err is not None:
        return err
    fmt = payload["format"]
    if fmt == "pdf":
        if not _pdf_ready():
            return _err("pdf renderer unavailable on this deploy", 503)
        buf = _render_cover_pdf(payload)
        ext, mime = "pdf", "application/pdf"
    else:
        if not _docx_ready():
            return _err("docx renderer unavailable on this deploy", 503)
        buf = _render_cover_docx(payload)
        ext, mime = "docx", ("application/vnd.openxmlformats-officedocument"
                             ".wordprocessingml.document")
    fname = _safe_name(payload["seeker_name"], "Cover Letter", payload["posting_title"])
    return send_file(buf, mimetype=mime, as_attachment=True,
                     download_name="{0}.{1}".format(fname, ext))
