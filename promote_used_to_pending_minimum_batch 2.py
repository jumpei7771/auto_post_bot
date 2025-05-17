import os
import json
import argparse
from notion_client import Client


def load_account_config(account_name):
    """
    指定されたアカウントの設定情報をJSONファイルから読み込む。
    Args:
        account_name (str): 読み込むアカウント名。
    Returns:
        dict or None: アカウントの設定情報。エラー時はNone。
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_filename = "accounts.json"
    config_path = os.path.join(base_dir, config_filename)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"エラー: 設定ファイルが見つかりません: {config_path}")
        return None
    except json.JSONDecodeError:
        print(f"エラー: 設定ファイルのJSON形式が正しくありません: {config_path}")
        return None

    if account_name not in config:
        print(f"エラー: アカウント '{account_name}' は設定に存在しません。")
        return None

    return config[account_name]


def count_pending_posts(notion_client, db_id):
    """
    指定されたNotionデータベース内の「投稿待ち」ステータスで条件を満たす投稿数をカウントする。
    Args:
        notion_client (notion_client.Client): Notion APIクライアント。
        db_id (str): 対象のNotionデータベースID。
    Returns:
        int: 条件を満たす投稿待ちの件数。エラー時は0。
    """
    try:
        # ページサイズを100にして、より多くの結果を一度に取得し、正確な件数を把握
        # ただし、Notion APIの最大ページサイズは100なので、100件を超える場合は複数回クエリが必要
        # ここでは、投稿待ちが極端に多くない前提で、最初の100件で判断する
        # (より正確には、has_more と next_cursor を使ったページネーションが必要)
        response = notion_client.databases.query(
            database_id=db_id,
            page_size=100,  # 投稿待ちの総数を把握するため、ある程度の数を取得
            filter={
                "and": [
                    {"property": "ステータス", "select": {"equals": "投稿待ち"}},
                    {"property": "動画", "files": {"is_not_empty": True}},
                    {
                        "property": "回答（編集済み）",
                        "rich_text": {"is_not_empty": True},
                    },
                ]
            },
        )
        return len(response.get("results", []))
    except Exception as e:
        print(f"❌ 投稿待ちの件数取得に失敗: {e}")
        return 0  # エラー時は0件として扱う


def promote_all_used_to_pending(notion_client, db_id):
    """
    指定されたNotionデータベース内の「使用済み」ステータスで条件を満たす全ての投稿を
    「投稿待ち」ステータスに更新する。
    Args:
        notion_client (notion_client.Client): Notion APIクライアント。
        db_id (str): 対象のNotionデータベースID。
    """
    promoted_count = 0
    has_more = True
    start_cursor = None

    print("🔍 「使用済み」で条件を満たす投稿を検索中...")
    while has_more:
        try:
            response = notion_client.databases.query(
                database_id=db_id,
                page_size=100,  # APIの最大値
                start_cursor=start_cursor,
                filter={
                    "and": [
                        {"property": "ステータス", "select": {"equals": "使用済み"}},
                        {"property": "動画", "files": {"is_not_empty": True}},
                        {
                            "property": "回答（編集済み）",
                            "rich_text": {"is_not_empty": True},
                        },
                    ]
                },
            )
        except Exception as e:
            print(f"❌ 使用済み投稿の取得中にエラーが発生しました: {e}")
            return  # エラーが発生したら処理を中断

        results = response.get("results", [])
        if not results and start_cursor is None:  # 最初のクエリで結果がなければ終了
            print("⚠️ 「使用済み」に移行対象の投稿は見つかりませんでした。")
            return

        for page in results:
            try:
                notion_client.pages.update(
                    page_id=page["id"],
                    properties={"ステータス": {"select": {"name": "投稿待ち"}}},
                )
                print(
                    f"✅ ステータス変更成功: ページID {page['id']} を「投稿待ち」にしました。"
                )
                promoted_count += 1
            except Exception as e:
                print(f"⚠️ ステータス変更失敗（ページID: {page['id']}）: {e}")

        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    if promoted_count > 0:
        print(
            f"🟢 移行完了: 合計 {promoted_count} 件の投稿を「使用済み」から「投稿待ち」に変更しました。"
        )
    elif start_cursor is None:  # 最初のクエリで結果がなく、ループにも入らなかった場合
        pass  # 上記の「見つかりませんでした」メッセージで対応済み
    else:  # ループはしたが、対象がなかった場合（通常は起こりにくい）
        print("ℹ️ 移行対象の「使用済み」投稿はありませんでした（ループ後確認）。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Notionの「使用済み」投稿を「投稿待ち」に移行するスクリプト。"
    )
    parser.add_argument(
        "--account",
        default="default",
        help="使用するアカウント名（accounts.jsonで定義）。省略時は 'default'。",
    )
    parser.add_argument(
        "--mode",
        choices=["question", "joboffer"],
        default="question",
        help="処理対象のNotionデータベースのモード（'question' または 'joboffer'）。省略時は 'question'。",
    )
    args = parser.parse_args()

    print(f"🚀 スクリプト開始: アカウント='{args.account}', モード='{args.mode}'")

    account_details = load_account_config(args.account)
    if not account_details:
        print("❌ アカウント設定の読み込みに失敗したため、処理を終了します。")
        exit(1)  # エラーコード 1 で終了

    NOTION_API_TOKEN = account_details.get("notion_token")
    DATABASE_IDS_CONFIG = account_details.get("database_ids", {})
    TARGET_DATABASE_ID = DATABASE_IDS_CONFIG.get(args.mode)

    if not NOTION_API_TOKEN:
        print("❌ Notion APIトークンが設定ファイルにありません。処理を終了します。")
        exit(1)
    if not TARGET_DATABASE_ID:
        print(
            f"❌ モード '{args.mode}' に対応するデータベースIDが設定ファイルにありません。処理を終了します。"
        )
        exit(1)

    notion_api_client = Client(auth=NOTION_API_TOKEN)

    current_pending_count = count_pending_posts(notion_api_client, TARGET_DATABASE_ID)
    print(f"ℹ️ 現在の「投稿待ち」件数: {current_pending_count}")

    MINIMUM_PENDING_THRESHOLD = 1  # 投稿待ちがこの件数未満なら移行を実行
    if current_pending_count < MINIMUM_PENDING_THRESHOLD:
        print(
            f"⚠️ 「投稿待ち」の件数が {MINIMUM_PENDING_THRESHOLD} 未満です。移行処理を開始します..."
        )
        promote_all_used_to_pending(notion_api_client, TARGET_DATABASE_ID)
    else:
        print(
            f"✅ 「投稿待ち」の件数が {MINIMUM_PENDING_THRESHOLD} 件以上あります。移行処理はスキップします。"
        )

    print("🏁 スクリプト処理終了。")
