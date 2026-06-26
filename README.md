# Trend Radar NG — Headline Card Render Service (flat layout)

All files sit at the top level (no subfolders). Renders an on-brand PNG news
card from a headline. One service serves all four lanes; only `category` changes.

## Deploy to Render
New -> Blueprint -> pick this repo (reads render.yaml). Plan = Starter (always-on).
Health: open `https://<app>.onrender.com/` -> should say `ok`.
Test:  `https://<app>.onrender.com/card?headline=Naira+firms&source=Nairametrics&category=ECONOMY`
