import requests
import json

# ✅ あなたの Notion Integration トークン
NOTION_TOKEN = "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"

# ✅ データベースを作成する Notion ページの ID
NOTION_PAGE_ID = "1f6eab4c6158808bbb33de86471907fe"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

payload = {
    "parent": {
        "type": "page_id",
        "page_id": NOTION_PAGE_ID
    },
    "title": [
        {
            "type": "text",
            "text": {
                "content": "X投稿管理（API生成）"
            }
        }
    ],
    "properties": {
        "名前": {
            "title": {}
        },
        "ステータス": {
            "select": {
                "options": [
                    {"name": "投稿待ち", "color": "green"},
                    {"name": "使用済み", "color": "red"}
                ]
            }
        },
        "回答（編集済み）": {
            "rich_text": {}
        },
        "動画": {
            "files": {}
        }
    }
}

url = "https://api.notion.com/v1/databases"

response = requests.post(url, headers=headers, data=json.dumps(payload))

if response.status_code == 200:
    print("✅ データベース作成成功！")
    print(json.dumps(response.json(), indent=2))
else:
    print(f"❌ 作成失敗: {response.status_code}")
    print(response.text)
