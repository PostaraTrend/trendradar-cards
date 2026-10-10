import unittest
from io import BytesIO
from zipfile import ZipFile
from flask import Flask
from pypdf import PdfReader
import resume_export

class LanguageExports(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(resume_export.export_bp)
        self.client = app.test_client()

    def test_languages_formats_and_templates(self):
        for language, subject in (("en-CA", "Re: "), ("fr-CA", "Objet : "), ("es-419", "Asunto: ")):
            for template in ("classic", "compact", "plain"):
                for kind in ("resume", "cover"):
                    for fmt in ("pdf", "docx"):
                        payload = {"format": fmt, "template": template, "document_language": language,
                                   "seeker_name": "Jordan Example", "posting": {"title": "Support"},
                                   "sections": [{"title": "Formation", "lines": [{"text": "Diplôme", "heading": True}, "Expérience vérifiée."]}],
                                   "body": ["Bonjour,", "Expérience vérifiée.", "Merci."]}
                        response = self.client.post("/export/" + kind, json=payload)
                        self.assertEqual(response.status_code, 200)
                        if fmt == "pdf":
                            pdf = PdfReader(BytesIO(response.data))
                            self.assertEqual(str(pdf.trailer["/Root"]["/Lang"]), language)
                            text = "".join(p.extract_text() for p in pdf.pages)
                            self.assertIn("Jordan Example", text)
                            if kind == "cover": self.assertIn(subject + "Support", text)
                        else:
                            with ZipFile(BytesIO(response.data)) as z:
                                styles = z.read("word/styles.xml").decode()
                                document = z.read("word/document.xml").decode()
                                self.assertIn('w:val="' + language + '"', styles)
                                self.assertIn(language, z.read("docProps/core.xml").decode())
                                if kind == "resume":
                                    self.assertIn('w:val="Heading1"', document)
                                    self.assertIn('w:val="Heading2"', document)
                                else: self.assertIn(subject + "Support", document)

    def test_invalid_language_is_rejected(self):
        for kind in ("resume", "cover"):
            for language in ("de", "", None, 123):
                r = self.client.post("/export/" + kind, json={"document_language": language,
                    "sections": [{"title": "Summary", "lines": ["Text"]}], "body": ["Text"]})
                self.assertEqual(r.status_code, 422)

    def test_legacy_default(self):
        r = self.client.post("/export/resume", json={"sections": [{"title": "Summary", "lines": ["Text"]}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(str(PdfReader(BytesIO(r.data)).trailer["/Root"]["/Lang"]), "en-CA")

if __name__ == "__main__":
    unittest.main()
