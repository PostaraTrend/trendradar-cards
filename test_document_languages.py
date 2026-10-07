import io
import unittest

from docx import Document
from docx.oxml.ns import qn
from flask import Flask
from pypdf import PdfReader

import resume_export as renderer

app = Flask(__name__)
app.register_blueprint(renderer.export_bp)
client = app.test_client()


class DocumentLanguages(unittest.TestCase):
    def test_language_survives_both_export_formats(self):
        cases = [
            ("en-CA", "Re: ", "Provided support to 12 residents."),
            ("fr-CA", "Objet : ", "Soutien auprès de 12 résidents."),
            ("es-419", "Asunto: ", "Apoyo a 12 residentes."),
        ]
        for language, subject, text in cases:
            for kind in ("resume", "cover"):
                for fmt in ("pdf", "docx"):
                    with self.subTest(language=language, kind=kind, format=fmt):
                        payload = {"document_language": language, "format": fmt,
                                   "seeker_name": "Alex Example",
                                   "posting": {"title": "Support Role"},
                                   "sections": [{"title": "Summary", "lines": [text]}],
                                   "body": [text]}
                        response = client.post("/export/" + kind, json=payload)
                        self.assertEqual(response.status_code, 200)
                        if fmt == "pdf":
                            pdf = PdfReader(io.BytesIO(response.data))
                            self.assertEqual(pdf.trailer["/Root"]["/Lang"], language)
                            output = "\n".join(page.extract_text() for page in pdf.pages)
                        else:
                            document = Document(io.BytesIO(response.data))
                            properties = document.styles["Normal"].element.rPr
                            self.assertEqual(properties.find(qn("w:lang")).get(qn("w:val")), language)
                            output = "\n".join(p.text for p in document.paragraphs)
                        self.assertIn(text, output)
                        self.assertNotIn("Verified by", output)
                        if kind == "cover":
                            self.assertIn(subject + "Support Role", output)
                            if language != "en-CA":
                                self.assertNotIn("Re: Support Role", output)

    def test_legacy_default_and_invalid_locale(self):
        for kind in ("resume", "cover"):
            body = {"sections": [{"title": "Summary", "lines": ["Example."]}],
                    "body": ["Example."], "posting": {"title": "Support Role"}}
            response = client.post("/export/" + kind, json=body)
            self.assertEqual(response.status_code, 200)
            pdf = PdfReader(io.BytesIO(response.data))
            self.assertEqual(pdf.trailer["/Root"]["/Lang"], "en-CA")
            for unsupported in ("de-DE", "<script>", None, ["fr-CA"]):
                self.assertEqual(client.post("/export/" + kind,
                                            json={**body, "document_language": unsupported}).status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
