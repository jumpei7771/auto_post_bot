import requests
import json

# ✅ あなたの Notion Integration トークン
NOTION_TOKEN = "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"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ✅ Step 1: ワークスペース直下にページを作成
page_payload = {
    "parent": {
        "type": "workspace",
        "workspace": True
    },
    "properties": {
        "title": [
            {
                "type": "text",
                "text": {
                    "content": "X投稿管理ページ（API生成）"
                }
            }
        ]
    }
}

page_response = requests.post("https://api.notion.com/v1/pages", headers=headers, data=json.dumps(page_payload))

if page_response.status_code != 200:
    print(f"❌ ページ作成失敗: {page_response.status_code}")
    print(page_response.text)
    exit()

parent_page = page_response.json()
parent_page_id = parent_page["id"]
print(f"✅ ページ作成成功！Page ID: {parent_page_id}")

# ✅ Step 2: データベースをそのページ内に作成
db_payload = {
    "parent": {
        "type": "page_id",
        "page_id": parent_page_id
    },
    "title": [
        {
            "type": "text",
            "text": {
                "content": "X投稿管理データベース（API生成）"
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

db_response = requests.post("https://api.notion.com/v1/databases", headers=headers, data=json.dumps(db_payload))

if db_response.status_code == 200:
    print("✅ データベース作成成功！")
    print(json.dumps(db_response.json(), indent=2))
else:
    print(f"❌ データベース作成失敗: {db_response.status_code}")
    print(db_response.text)
