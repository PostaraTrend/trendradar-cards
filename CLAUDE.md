# CLAUDE.md

This file gives Claude Code standing context for working in this repository.

## About this repo

This is PostaraTrend/trendradar-cards, the Flask render service behind Trend Radar Nigeria (TRNG), PostaraTrend's automated Nigerian news and culture publishing platform, deployed on Render. One service renders on brand PNG headline cards for four TRNG lanes, distinguished only by a category query parameter (see the many card.py files: civic_card, health_card, gist_card, wahala_card, scam_card, and others). It also holds story_video.py, the shared narrated story video renderer used by the Heritage Story Reel and serial lanes (see the memory file story-renderer.md for the API contract), and resume_export.py plus resume_extract.py, which back parts of the Role Scout (TraceScout) resume parsing and export pipeline. In short, this one Render service is shared infrastructure across TRNG and TraceScout, not a single purpose repo.

## Standing rules for this project (set by the founder, Celestine Oamen)

These apply across every PostaraTrend, TRNG, and CRLK repository, not only this one.

### Drafted content (copy, captions, SOPs, docs, code comments meant for people)
- No contractions anywhere. Expand them (do not write "don't", write "do not").
- No dashes as punctuation, including em dashes, en dashes, or a hyphen used as a pause. Use a comma, a colon, or split into two sentences instead.

### Delivery format
- When a file needs changing, hand over the COMPLETE updated file, never a diff or edit instructions. Verify it (lint, compile, or the equivalent for the language) before delivering, and be ready to show proof of that check.
- When a change spans several files or steps, hand them over ONE at a time, in order, naming the environment each one goes into (for example Supabase SQL editor, n8n, Lovable, GitHub, Render), and wait for confirmation before presenting the next one.
- Any image generation prompt must include the intended save as filename inside the prompt block itself.
- Pasteable content (prompts, captions, hook messages, agent instructions) should be easy to copy in one block.

### Engineering practice
- Cost optimization is a mandatory design factor for any new build: model tier choice, polling versus event triggers, execution quota impact. State the trade offs rather than silently picking the cheapest option.
- QA the INTEGRATED system, not pieces in isolation. When a fix spans two components, test them together against the exact payload before delivering either. Walk the runtime data flow through every branch, including empty results. SQL handed over must be exact and runnable, with no placeholders, checked against the real schema first. Never assert a cause without log or execution evidence; say plainly what is unknown and what single artifact would settle it.
- Every deliverable gets a due diligence pass before handover, plus an explicit blind spot list: state in a line what was checked and what was not, and name the gaps that are visible but cannot be fixed from where the work stands, so they are on the table rather than found in production.
- Explain the why behind an instruction or step in plain language, at the point of the instruction, not only if asked.

### n8n workflows specifically
- Every workflow shipped or modified needs a "What This Lane Does" sticky note describing the lane and its flow, and a notesInFlow annotation on every node describing that node's function. The no dashes rule applies to these annotations too.

### Incident handling
- When an issue (bug, outage, incident) is resolved: write a root cause analysis, commit it as a new incident entry (plus a matching README row) to the private repo PostaraTrend/rolescout-incidents and its Google Drive mirror ("Role Scout Incident Knowledge Base" folder), and call the Role Scout Incident Notify webhook (https://postaratrend.app.n8n.cloud/webhook/role-scout-incident-notify, POST body: title, date, area, summary, corrective, preventive, github_url) so the founder and Chinwe both receive an executive summary email automatically, without being asked each time.

### Tools already in use across this stack
- Lovable project rolescout-postaratrend (display name Tracescout) hosts the TraceScout app, live at tracescout.ca.
- Supabase projects: role-scout (id kdcxdirvtnfvpxyxvzpg) for TraceScout, postaratrend-prod (id hdzaqnpgrtcncjmyhyca) for the wider platform.
- n8n instance at postaratrend.app.n8n.cloud runs ingestion, matching, tailoring, publishing, and digest lanes.
- Render hosts postaratrend.ca and the card render services described below, auto-deploying on push to each repo's main branch.

### Tone toward the founder
- When asking him questions or laying out a plan, keep it collaborative rather than directive: present options and trade offs rather than instructions. This governs tone only. It does not apply to drafted content meant for an audience, and it does not mean withholding honest concerns or disagreement.
