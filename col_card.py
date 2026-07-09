{
  "name": "TRNG — Shine Your Eye (Scam Alert) v1.1",
  "nodes": [
    {
      "parameters": {
        "rule": {
          "interval": [
            {
              "field": "cronExpression",
              "expression": "0 6-20/2 * * *"
            }
          ]
        }
      },
      "name": "Every 2 Hours (Daytime)",
      "type": "n8n-nodes-base.scheduleTrigger",
      "typeVersion": 1.2,
      "position": [
        -1600,
        0
      ],
      "notes": "Runs 7am–9pm WAT every 2 hours. One alert max per run; daily cap enforced via Scam_Config."
    },
    {
      "parameters": {
        "url": "https://punchng.com/feed/",
        "options": {}
      },
      "name": "RSS — Punch",
      "type": "n8n-nodes-base.rssFeedRead",
      "typeVersion": 1.1,
      "position": [
        -1380,
        -160
      ],
      "onError": "continueRegularOutput"
    },
    {
      "parameters": {
        "url": "https://www.premiumtimesng.com/feed",
        "options": {}
      },
      "name": "RSS — Premium Times",
      "type": "n8n-nodes-base.rssFeedRead",
      "typeVersion": 1.1,
      "position": [
        -1380,
        0
      ],
      "onError": "continueRegularOutput"
    },
    {
      "parameters": {
        "url": "https://www.vanguardngr.com/feed/",
        "options": {}
      },
      "name": "RSS — Vanguard",
      "type": "n8n-nodes-base.rssFeedRead",
      "typeVersion": 1.1,
      "position": [
        -1380,
        160
      ],
      "onError": "continueRegularOutput"
    },
    {
      "parameters": {
        "mode": "append",
        "numberInputs": 3
      },
      "name": "Merge Feeds",
      "type": "n8n-nodes-base.merge",
      "typeVersion": 3,
      "position": [
        -1160,
        0
      ]
    },
    {
      "parameters": {
        "operation": "read",
        "documentId": {
          "__rl": true,
          "mode": "list",
          "value": "REPLACE_WITH_OPS_WORKBOOK_ID"
        },
        "sheetName": {
          "__rl": true,
          "mode": "name",
          "value": "Scam_Config"
        },
        "options": {}
      },
      "name": "Read Scam Config",
      "type": "n8n-nodes-base.googleSheets",
      "typeVersion": 4.5,
      "position": [
        -940,
        -120
      ],
      "notes": "Scam_Config tab: enabled (TRUE/FALSE) | max_per_day. Your kill switch for this lane."
    },
    {
      "parameters": {
        "operation": "read",
        "documentId": {
          "__rl": true,
          "mode": "list",
          "value": "REPLACE_WITH_OPS_WORKBOOK_ID"
        },
        "sheetName": {
          "__rl": true,
          "mode": "name",
          "value": "Scam_Log"
        },
        "options": {}
      },
      "name": "Read Scam Log",
      "type": "n8n-nodes-base.googleSheets",
      "typeVersion": 4.5,
      "position": [
        -940,
        120
      ],
      "notes": "Dedup memory: every classified article lands here (published AND rejected) so nothing is reprocessed."
    },
    {
      "parameters": {
        "jsCode": "// ---- Keyword filter + dedup + config gate; emits at most ONE candidate ----\nconst config = $('Read Scam Config').first().json;\nconst enabled = String(config.enabled).toUpperCase() === 'TRUE';\nif (!enabled) return [];\n\nconst maxPerDay = parseInt(config.max_per_day) || 3;\nconst logRows = $('Read Scam Log').all().map(i => i.json);\n\n// daily cap (Lagos date)\nconst todayLagos = new Date().toLocaleDateString('en-CA', { timeZone: 'Africa/Lagos' });\nconst publishedToday = logRows.filter(r =>\n  r.decision === 'published' &&\n  String(r.timestamp || '').length &&\n  new Date(r.timestamp).toLocaleDateString('en-CA', { timeZone: 'Africa/Lagos' }) === todayLagos\n).length;\nif (publishedToday >= maxPerDay) return [];\n\nconst KEYWORDS = ['ponzi','scam','fraud','fraudster','defraud','dupe','duped','419',\n  'yahoo boy','investment scheme','wonder bank','fake job','job racket','recruitment scam',\n  'fake recruitment','fake alert','pos fraud','phishing','impersonat','forex scheme',\n  'crypto scheme','efcc arrest','efcc warn','sec warn','cbn warn','fccpc warn','money doubling'];\n\nconst normUrl = (u) => String(u || '').toLowerCase()\n  .replace(/^https?:\\/\\/(www\\.)?/, '').replace(/[?#].*$/, '').replace(/\\/+$/, '');\nconst tokens = (t) => new Set(String(t || '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ')\n  .split(/\\s+/).filter(w => w.length > 3));\nconst similarity = (a, b) => {\n  const A = tokens(a), B = tokens(b);\n  if (!A.size || !B.size) return 0;\n  let inter = 0; for (const w of A) if (B.has(w)) inter++;\n  return inter / Math.min(A.size, B.size);\n};\n\nconst seenUrls = new Set(logRows.map(r => normUrl(r.url_norm)));\nconst seenHeadlines = logRows.map(r => r.headline || '');\n\nconst items = $('Merge Feeds').all().map(i => i.json);\nconst candidates = [];\nfor (const it of items) {\n  const title = it.title || '';\n  const content = (it.contentSnippet || it.content || '').slice(0, 1500);\n  const hay = (title + ' ' + content).toLowerCase();\n  if (!KEYWORDS.some(k => hay.includes(k))) continue;\n  const un = normUrl(it.link);\n  if (!un || seenUrls.has(un)) continue;\n  if (seenHeadlines.some(h => similarity(h, title) >= 0.7)) continue;\n  candidates.push({\n    title, content, link: it.link, url_norm: un,\n    source: (it.creator || it.link || '').includes('punch') ? 'Punch' :\n            String(it.link || '').includes('premiumtimes') ? 'Premium Times' :\n            String(it.link || '').includes('vanguard') ? 'Vanguard' : 'News report',\n    pubDate: it.pubDate || it.isoDate || ''\n  });\n}\nif (!candidates.length) return [];\ncandidates.sort((a, b) => new Date(b.pubDate) - new Date(a.pubDate));\nreturn [{ json: candidates[0] }];  // one alert per run keeps quality high"
      },
      "name": "Filter & Dedup",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [
        -720,
        0
      ]
    },
    {
      "parameters": {
        "conditions": {
          "options": {
            "caseSensitive": true,
            "typeValidation": "loose"
          },
          "conditions": [
            {
              "leftValue": "={{ $json.url_norm }}",
              "rightValue": "",
              "operator": {
                "type": "string",
                "operation": "notEmpty",
                "singleValue": true
              }
            }
          ],
          "combinator": "and"
        },
        "options": {}
      },
      "name": "Has Candidate?",
      "type": "n8n-nodes-base.if",
      "typeVersion": 2.2,
      "position": [
        -500,
        0
      ]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "https://api.anthropic.com/v1/messages",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            {
              "name": "anthropic-version",
              "value": "2023-06-01"
            },
            {
              "name": "content-type",
              "value": "application/json"
            }
          ]
        },
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ model: 'claude-sonnet-4-6', max_tokens: 1000, system: \"You are the editorial classifier for Trend Radar NG's 'Shine Your Eye' scam-alert lane (Nigerian Facebook/Instagram audience). Given one news article, decide if it should become a scam-alert card.\\n\\nPUBLISH only if the article describes an active or recent scam, fraud scheme, or fraud method that ordinary Nigerians could still fall victim to (Ponzi/investment schemes, fake jobs, fake recruitment, POS/bank fraud tricks, phishing, money doubling). Do NOT publish for: court updates on old cases with no ongoing public risk, opinion pieces, politics-framed corruption stories, or foreign scams with no Nigerian exposure.\\n\\nNAMING RULE (strict): include a named company/scheme/person ONLY if the article reports on-record action or warning by an official body (EFCC, SEC Nigeria, CBN, Nigeria Police, FCCPC, NNPC) or is the outlet's own on-record reporting of such action. Otherwise describe the scheme generically without names.\\n\\nRespond with ONLY a JSON object, no markdown fences, no preamble:\\n{\\\"publishable\\\": bool, \\\"confidence\\\": 0.0-1.0, \\\"alert_type\\\": \\\"PONZI ALERT\\\"|\\\"JOB SCAM\\\"|\\\"FRAUD TRICK\\\"|\\\"FAKE RECRUITMENT\\\"|\\\"SCAM ALERT\\\", \\\"headline\\\": \\\"one clear sentence, max 14 words\\\", \\\"facts\\\": [\\\"up to 3 short factual bullets from the article\\\"], \\\"protection\\\": [\\\"exactly 2 practical protection tips\\\"], \\\"source_name\\\": \\\"agency and/or outlet, e.g. EFCC / Punch\\\", \\\"reason\\\": \\\"one line explaining the decision\\\"}\\n\\nLight Nigerian Pidgin flavor is welcome in protection tips. Facts must stay strictly faithful to the article \\u2014 no invented details, no invented amounts.\", messages: [{ role: 'user', content: 'ARTICLE TITLE: ' + $json.title + '\\n\\nOUTLET: ' + $json.source + '\\n\\nURL: ' + $json.link + '\\n\\nCONTENT: ' + $json.content }] }) }}",
        "options": {}
      },
      "name": "Claude — Classify Alert",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [
        -280,
        -60
      ],
      "notes": "Create an n8n Header Auth credential named e.g. 'Anthropic API' with header x-api-key = your key (billed to admin@postaratrend.ca Anthropic account). Sonnet chosen deliberately: the naming/defamation gate needs judgment, not just extraction."
    },
    {
      "parameters": {
        "jsCode": "// ---- Parse Claude JSON, apply publish gate, build render payload + caption ----\nconst resp = $('Claude \\u2014 Classify Alert').first().json;\nconst cand = $('Filter & Dedup').first().json;\n\nlet text = '';\nif (Array.isArray(resp.content)) text = resp.content.filter(b => b.type === 'text').map(b => b.text).join('\\n');\ntext = text.replace(/```json|```/g, '').trim();\n\nlet verdict;\ntry { verdict = JSON.parse(text); }\ncatch (e) { verdict = { publishable: false, confidence: 0, reason: 'classifier returned unparseable output' }; }\n\nconst publish = verdict.publishable === true && (verdict.confidence || 0) >= 0.8\n  && verdict.headline && (verdict.facts || []).length >= 1 && (verdict.protection || []).length >= 1;\n\nconst payload = {\n  alert_type: verdict.alert_type || 'SCAM ALERT',\n  headline: verdict.headline || '',\n  facts: (verdict.facts || []).slice(0, 3),\n  protection: (verdict.protection || []).slice(0, 2),\n  source_name: verdict.source_name || cand.source,\n  date_label: new Date().toLocaleDateString('en-NG', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Africa/Lagos' })\n};\n\nconst hooks = {\n  'PONZI ALERT': '\\ud83d\\udea8 PONZI ALERT \\u2014 shine your eye before you invest!',\n  'JOB SCAM': '\\ud83d\\udea8 JOB SCAM ALERT \\u2014 no let them use your hustle catch you!',\n  'FRAUD TRICK': '\\ud83d\\udea8 NEW FRAUD TRICK DEY GO ROUND \\u2014 read this one well!',\n  'FAKE RECRUITMENT': '\\ud83d\\udea8 FAKE RECRUITMENT ALERT \\u2014 no pay anybody for form!',\n  'SCAM ALERT': '\\ud83d\\udea8 SCAM ALERT \\u2014 shine your eye!'\n};\nconst lines = [hooks[payload.alert_type] || hooks['SCAM ALERT'], '', payload.headline, ''];\nfor (const f of payload.facts) lines.push('\\u26a0\\ufe0f ' + f);\nlines.push('');\nfor (const p of payload.protection) lines.push('\\u2705 ' + p);\nlines.push('');\nlines.push('Source: ' + payload.source_name);\nlines.push('');\nlines.push('Tag person wey need to see this \\ud83d\\udc47 Share am make your people no fall victim.');\nlines.push('');\nlines.push('#TrendRadarNG #ShineYourEye #ScamAlert #NigeriaNews #EFCC #StaySafe');\n\nreturn [{ json: {\n  publish,\n  payload,\n  caption: lines.join('\\n'),\n  url_norm: cand.url_norm,\n  headline_log: verdict.headline || cand.title,\n  alert_type: payload.alert_type,\n  reason: verdict.reason || ''\n} }];"
      },
      "name": "Parse & Gate",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [
        -60,
        -60
      ]
    },
    {
      "parameters": {
        "conditions": {
          "options": {
            "caseSensitive": true,
            "typeValidation": "loose"
          },
          "conditions": [
            {
              "leftValue": "={{ $json.publish }}",
              "rightValue": true,
              "operator": {
                "type": "boolean",
                "operation": "true",
                "singleValue": true
              }
            }
          ],
          "combinator": "and"
        },
        "options": {}
      },
      "name": "Publishable?",
      "type": "n8n-nodes-base.if",
      "typeVersion": 2.2,
      "position": [
        160,
        -60
      ]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "https://trendradar-cards.onrender.com/scam/render",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($json.payload) }}",
        "options": {}
      },
      "name": "Render Alert Card",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [
        380,
        -160
      ]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "https://graph.facebook.com/v21.0/REPLACE_PAGE_ID/photos",
        "sendQuery": true,
        "queryParameters": {
          "parameters": [
            {
              "name": "url",
              "value": "={{ $json.image_url }}"
            },
            {
              "name": "caption",
              "value": "={{ $('Parse & Gate').first().json.caption }}"
            },
            {
              "name": "access_token",
              "value": "REPLACE_WITH_PAGE_ACCESS_TOKEN"
            }
          ]
        },
        "options": {}
      },
      "name": "Facebook — Publish Alert",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [
        600,
        -260
      ]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "https://graph.facebook.com/v21.0/REPLACE_IG_USER_ID/media",
        "sendQuery": true,
        "queryParameters": {
          "parameters": [
            {
              "name": "image_url",
              "value": "={{ $json.image_url_jpg }}"
            },
            {
              "name": "caption",
              "value": "={{ $('Parse & Gate').first().json.caption }}"
            },
            {
              "name": "access_token",
              "value": "REPLACE_WITH_PAGE_ACCESS_TOKEN"
            }
          ]
        },
        "options": {}
      },
      "name": "IG — Create Media Container",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [
        600,
        -60
      ]
    },
    {
      "parameters": {
        "amount": 15
      },
      "name": "Wait for Container",
      "type": "n8n-nodes-base.wait",
      "typeVersion": 1.1,
      "position": [
        820,
        -60
      ]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "https://graph.facebook.com/v21.0/REPLACE_IG_USER_ID/media_publish",
        "sendQuery": true,
        "queryParameters": {
          "parameters": [
            {
              "name": "creation_id",
              "value": "={{ $('IG — Create Media Container').first().json.id }}"
            },
            {
              "name": "access_token",
              "value": "REPLACE_WITH_PAGE_ACCESS_TOKEN"
            }
          ]
        },
        "options": {}
      },
      "name": "IG — Publish",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [
        1040,
        -60
      ]
    },
    {
      "parameters": {
        "operation": "append",
        "documentId": {
          "__rl": true,
          "mode": "list",
          "value": "REPLACE_WITH_OPS_WORKBOOK_ID"
        },
        "sheetName": {
          "__rl": true,
          "mode": "name",
          "value": "Scam_Log"
        },
        "options": {},
        "columns": {
          "mappingMode": "defineBelow",
          "value": {
            "timestamp": "={{ new Date().toISOString() }}",
            "url_norm": "={{ $('Parse & Gate').first().json.url_norm }}",
            "headline": "={{ $('Parse & Gate').first().json.headline_log }}",
            "alert_type": "={{ $('Parse & Gate').first().json.alert_type }}",
            "decision": "published",
            "reason": "={{ $('Parse & Gate').first().json.reason }}",
            "fb_post_id": "={{ $('Facebook — Publish Alert').first().json.post_id || $('Facebook — Publish Alert').first().json.id }}",
            "ig_media_id": "={{ $('IG — Publish').first().json.id }}"
          }
        }
      },
      "name": "Log Published",
      "type": "n8n-nodes-base.googleSheets",
      "typeVersion": 4.5,
      "position": [
        1260,
        -60
      ]
    },
    {
      "parameters": {
        "operation": "append",
        "documentId": {
          "__rl": true,
          "mode": "list",
          "value": "REPLACE_WITH_OPS_WORKBOOK_ID"
        },
        "sheetName": {
          "__rl": true,
          "mode": "name",
          "value": "Scam_Log"
        },
        "options": {},
        "columns": {
          "mappingMode": "defineBelow",
          "value": {
            "timestamp": "={{ new Date().toISOString() }}",
            "url_norm": "={{ $json.url_norm }}",
            "headline": "={{ $json.headline_log }}",
            "alert_type": "={{ $json.alert_type }}",
            "decision": "rejected",
            "reason": "={{ $json.reason }}",
            "fb_post_id": "",
            "ig_media_id": ""
          }
        }
      },
      "name": "Log Rejected",
      "type": "n8n-nodes-base.googleSheets",
      "typeVersion": 4.5,
      "position": [
        380,
        80
      ],
      "notes": "Rejected articles are logged too, so the same story is never re-classified (saves API cost and keeps dedup airtight)."
    }
  ],
  "connections": {
    "Every 2 Hours (Daytime)": {
      "main": [
        [
          {
            "node": "RSS — Punch",
            "type": "main",
            "index": 0
          },
          {
            "node": "RSS — Premium Times",
            "type": "main",
            "index": 0
          },
          {
            "node": "RSS — Vanguard",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "RSS — Punch": {
      "main": [
        [
          {
            "node": "Merge Feeds",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "RSS — Premium Times": {
      "main": [
        [
          {
            "node": "Merge Feeds",
            "type": "main",
            "index": 1
          }
        ]
      ]
    },
    "RSS — Vanguard": {
      "main": [
        [
          {
            "node": "Merge Feeds",
            "type": "main",
            "index": 2
          }
        ]
      ]
    },
    "Merge Feeds": {
      "main": [
        [
          {
            "node": "Read Scam Config",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Read Scam Config": {
      "main": [
        [
          {
            "node": "Read Scam Log",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Read Scam Log": {
      "main": [
        [
          {
            "node": "Filter & Dedup",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Filter & Dedup": {
      "main": [
        [
          {
            "node": "Has Candidate?",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Has Candidate?": {
      "main": [
        [
          {
            "node": "Claude — Classify Alert",
            "type": "main",
            "index": 0
          }
        ],
        []
      ]
    },
    "Claude — Classify Alert": {
      "main": [
        [
          {
            "node": "Parse & Gate",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Parse & Gate": {
      "main": [
        [
          {
            "node": "Publishable?",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Publishable?": {
      "main": [
        [
          {
            "node": "Render Alert Card",
            "type": "main",
            "index": 0
          }
        ],
        [
          {
            "node": "Log Rejected",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Render Alert Card": {
      "main": [
        [
          {
            "node": "Facebook — Publish Alert",
            "type": "main",
            "index": 0
          },
          {
            "node": "IG — Create Media Container",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "IG — Create Media Container": {
      "main": [
        [
          {
            "node": "Wait for Container",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Wait for Container": {
      "main": [
        [
          {
            "node": "IG — Publish",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "IG — Publish": {
      "main": [
        [
          {
            "node": "Log Published",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  },
  "settings": {
    "executionOrder": "v1",
    "timezone": "Africa/Lagos"
  }
}
