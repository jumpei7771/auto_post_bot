import subprocess
import argparse
import os
import sys

"""
このスクリプトは、Notionからの自動投稿処理全体を順次実行します。
1. promote_used_to_pending_minimum_batch.py: NotionDBの「使用済み」投稿を「投稿待ち」に移行。
2. post_tweet.py: NotionDBの「投稿待ち」からコンテンツを取得し、Twitterに投稿。
アカウント名とモードを引数として各サブスクリプトに渡します。
"""

# ==== スクリプトの場所を基準にしたパス設定 ====
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMOTE_SCRIPT_PATH = os.path.join(
    SCRIPT_DIR, "promote_used_to_pending_minimum_batch.py"
)
POST_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "post_tweet.py")
PYTHON_EXECUTABLE = sys.executable  # 現在のPythonインタプリタを使用

# ==== 引数受け取り ====
parser = argparse.ArgumentParser(
    description="Notionからの自動投稿処理（移行処理と投稿処理）を連続して実行します。"
)
parser.add_argument(
    "--account", default="default", help="使用するアカウント名 (accounts.jsonで定義)"
)
parser.add_argument(
    "--mode",
    choices=["question", "joboffer"],
    default="question",
    help="投稿モード（'question' または 'joboffer'）。Notionデータベースの選択に使用。",
)
args = parser.parse_args()

# ==== promote_used_to_pending_minimum_batch.py 実行 ====
print(
    f"🚀 Step1: 「使用済み」から「投稿待ち」への移行処理を開始 (アカウント: {args.account}, モード: {args.mode})"
)
try:
    subprocess.run(
        [
            PYTHON_EXECUTABLE,
            PROMOTE_SCRIPT_PATH,
            "--account",
            args.account,
            "--mode",
            args.mode,
        ],
        check=True,
    )
    print("✅ Step1: 移行処理 正常終了")
except FileNotFoundError:
    print(f"❌ Step1 エラー: スクリプト '{PROMOTE_SCRIPT_PATH}' が見つかりません。")
    sys.exit(1)
except subprocess.CalledProcessError as e:
    print(
        f"❌ Step1 エラー: 移行処理スクリプトがエラーコード {e.returncode} で終了しました。"
    )
    # サブスクリプトからの出力は既にコンソールに表示されているはずです
    sys.exit(1)


# ==== post_tweet.py 実行 ====
print(f"🚀 Step2: 投稿処理を開始 (アカウント: {args.account}, モード: {args.mode})")
try:
    subprocess.run(
        [
            PYTHON_EXECUTABLE,
            POST_SCRIPT_PATH,
            "--account",
            args.account,
            "--mode",
            args.mode,
        ],
        check=True,
    )
    print("✅ Step2: 投稿処理 正常終了")
except FileNotFoundError:
    print(f"❌ Step2 エラー: スクリプト '{POST_SCRIPT_PATH}' が見つかりません。")
    sys.exit(1)
except subprocess.CalledProcessError as e:
    print(
        f"❌ Step2 エラー: 投稿処理スクリプトがエラーコード {e.returncode} で終了しました。"
    )
    sys.exit(1)

print("🎉 全処理が正常に完了しました。")
