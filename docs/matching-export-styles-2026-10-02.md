# Matching resume and cover letter export styles

Released October 1, 2026 in America/Edmonton. Verification occurred October 2, 2026 UTC.

## Behavior

The tailored resume and cover letter download controls share Classic, Compact and Plain layout choices. The browser remembers the choice separately for each signed in user. It applies on both export pages and synchronizes across tabs. Missing, invalid or inaccessible storage falls back to Classic. A full localStorage clear removes all stored preferences.

Both PDF exports share font family, name and contact sizing, margins and body sizing for each layout. Both Word exports share the corresponding Word font, page size, margins and base paragraph spacing. Letter paragraphs and resume bullet sections retain their distinct document structures. Plain uses Times and black text. No one page or ATS acceptance guarantee is made.

The formatter renders the supplied content mechanically. Existing authorization, source version metadata, verification footer conditions and resume QR conditions remain in their existing paths.

## Release references

* Lovable project: 0725d412-f8b0-4dca-8c67-304339aa5222
* App source head: 48ccdd39960ca7a1bb5f79da9117e2f85fbd9918
* App prior source head: 1c1e9cb3408e25ea02dc2c223e54808023bc8b9c
* Publish request: 86379733-297e-4781-aa68-5385bf2880c6
* Public application: https://tracescout.app
* Renderer implementation commit: 32578833261461570be151d0d1b68cf055f2ad34
* Regression test commit: 65948700031f209576b9c977f47acdb92c4adea2
* Renderer prior head: a06721e4445b79c35e9275da155eac258e46f0b5
* Resume renderer health version: v1.5
* Cover renderer health version: v1.1

## Verification

The app build and type check passed. Four focused preference tests passed after the final logic changes. The earlier full suite reported 1011 passes, zero failures and four skips. The subsequent inspection identified three database runtime tests and one conditional closed sales test as the skipped cases. No database runtime verification is claimed for this feature.

Four renderer test groups passed, covering all twelve combinations of two document types, three layouts and two formats; font and margin alignment; default compatibility; invalid layout refusal; verification footer gates; and a cover letter with one hundred numbered responsibilities preserving every sentence across multiple pages.

All six sample PDFs and all six Word documents were rendered and visually inspected. Synthetic fixtures used Alex Example and an example.test email address.

Live HTTP checks downloaded all twelve document combinations successfully from the production renderer and checked their text and fonts. An invalid cover layout returned 422. Four additional production checks confirmed the resume verification footer and QR gates in PDF and Word with and without complete verification metadata.

The public application returned HTTP 200. Its entry bundle referenced the new shared preference bundle. Both published route bundles imported that bundle and included the template payload property:
* matches._id.cover-BI1rS-ys.js
* matches._id.tailored-BfBKc8Xd.js
* use-export-template-C8hX9TUZ.js

The renderer source was read back from GitHub and exactly matched the submitted replacement.

## Limitations

No signed in preview session was available. Actual menu clicks, navigation and cross tab synchronization through authenticated application pages were not tested. Unit tests cover storage behavior, while live renderer tests cover file outputs. Browser choice persistence is local to that browser and is not synchronized across devices.

## Reproduce renderer checks

Install the existing Flask, reportlab and python-docx dependencies plus PyMuPDF for text inspection. Run:

```sh
python -m unittest test_document_styles -v
```

The tests use a temporary output folder by default. Set TS_STYLE_SAMPLE_DIR to retain synthetic samples for visual inspection.

## Rollback

Use a forward change restoring the app export controls and helper files from the prior app source head, then publish. The old cover formatter ignores the optional template property, so it remains compatible while the app is restored.

Restore resume_export.py from the renderer prior head in a new commit on main. Preserve later unrelated changes and do not reset branch history. The renderer deploys automatically from main.
