import requests

# ✅ Integration トークン（新ワークスペース用）
NOTION_TOKEN = "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"

# ✅ ターゲットページのID
NOTION_PAGE_ID = "1f7422325cdd804e8d2cfe4bb5efa849"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

url = f"https://api.notion.com/v1/pages/{NOTION_PAGE_ID}"

response = requests.get(url, headers=headers)

if response.status_code == 200:
    print("✅ 200 OK！NotionがIntegrationを認識しました！")
else:
    print(f"❌ 接続失敗: {response.status_code}")
    print(response.text)
