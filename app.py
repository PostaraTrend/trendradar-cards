{
  "nodes": [
    {
      "parameters": {
        "method": "POST",
        "url": "https://trendradar-cards.onrender.com/host",
        "sendBody": true,
        "contentType": "binaryData",
        "inputDataFieldName": "data",
        "options": {}
      },
      "name": "Host Card for IG",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [
        0,
        0
      ],
      "id": "a1b2c3d4-0001-4000-8000-000000000001"
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
              "value": "REPLACE_WITH_CAPTION_EXPRESSION"
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
        220,
        0
      ],
      "id": "a1b2c3d4-0002-4000-8000-000000000002"
    },
    {
      "parameters": {
        "amount": 15
      },
      "name": "Wait for Container",
      "type": "n8n-nodes-base.wait",
      "typeVersion": 1.1,
      "position": [
        440,
        0
      ],
      "id": "a1b2c3d4-0003-4000-8000-000000000003"
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
        660,
        0
      ],
      "id": "a1b2c3d4-0004-4000-8000-000000000004"
    }
  ],
  "connections": {
    "Host Card for IG": {
      "main": [
        [
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
    }
  },
  "pinData": {},
  "meta": {
    "instanceId": "paste-block"
  }
}
