# Selected language verification October 7 2026

The renderer locale change is prepared in a draft branch and has not been deployed. TraceScout full selected language coverage is still undergoing implementation and integration verification. No production translation schema or feature activation was performed.

## Real test database checks

The existing tracescout-test project, ljtflqguenolyuobsvwj, received the exact db/0135_document_output_language.sql from TraceScout. Two additive translation tables were created. Production kdcxdirvtnfvpxyxvzpg was inspected read only and neither table exists there.

Twelve checks passed against real PostgreSQL: pending to ready increments row_version; stale compare and set touches zero rows; ready to reviewed increments row_version; reviewed text cannot change; identity cannot change; both tables enable RLS; authenticated clients have no insert, update or delete grants; anonymous clients cannot select; owner can select own row; another authenticated identity selects zero rows; English, French and Spanish versions store independently; language keys are distinct. Synthetic fixtures were rolled back. The security advisor returned no findings referring to either new table.

Actual production is_platform_owner and role_scout_has_complimentary_access definitions are STABLE SQL SELECT EXISTS checks. This resolves the prior uncertainty about whether these helpers mutate data.

## Real Auth and Data API checks

Two temporary synthetic accounts signed in using the test project's password grant. The owner received three rows, one for each language. The other signed in account received zero rows. Anonymous selection and authenticated direct updates were refused. Both sessions were signed out globally, each with HTTP 204. Accounts, postings, matches, source records and translation fixtures were removed. The cleanup query returned zero fixture accounts and zero translation rows. No emails were sent. This verifies Auth and Data API behavior, not full app browser acceptance testing.

## Current production renderer

The exact export payload shape used by buildTranslatedExport was tested with synthetic content against https://trendradar-cards.onrender.com/export/resume and /export/cover. All twelve combinations returned HTTP 200: English, French and Spanish, resume and cover letter, PDF and DOCX. Extracted content included the expected accented language text and unchanged synthetic name. All twelve short files were rendered and visually inspected with no clipping or broken accents.

The tests exposed the English Re: prefix in French and Spanish cover output. This branch changes it to Objet : and Asunto: using an allowlisted document_language. It also adds PDF catalog language and Word Normal style language metadata. English is the legacy default. Unsupported or malformed locale values return HTTP 422.

## Branch verification

Six unittest methods pass across test_document_languages and test_document_styles. The language test exercises twelve locale, document and format combinations. The original style suite covers three templates, matching Word margins, long covers and unchanged verification footer gating. Python compilation and git diff --check pass. Four changed French and Spanish cover PDF and DOCX samples were rendered and visually inspected after the change.

## Remaining release gates

Full app signed in translation request, guard, review and download flow; long multilingual document layouts; complete dynamic workspace and private note coverage; actual matching voice playback; coordinated stable application startup and deployment. Passing isolated Auth, database and renderer checks does not establish these gates. The current production renderer has not received this branch's locale fix.
