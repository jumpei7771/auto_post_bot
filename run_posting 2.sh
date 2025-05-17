#!/bin/bash

# スクリプトが存在するディレクトリに移動
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

# === アカウント指定（必須） ===
ACCOUNT_NAME=$1

# 引数チェック
if [ -z "$ACCOUNT_NAME" ]; then
    echo "エラー: アカウント名が指定されていません。"
    echo "使用法: $0 <アカウント名>"
    exit 1
fi

# カウントファイル（アカウント毎）
COUNTER_FILE="posting_counter_${ACCOUNT_NAME}.txt"
if [ ! -f "$COUNTER_FILE" ]; then
    touch "$COUNTER_FILE" 2>/dev/null || {
        echo "エラー: カウンターファイル '$COUNTER_FILE' の作成に失敗しました。"
        exit 1
    }
    echo 0 > "$COUNTER_FILE"
fi

# 現在のカウントを読み取り、不正な場合は0にフォールバック
count_raw=$(cat "$COUNTER_FILE")
if [[ "$count_raw" =~ ^[0-9]+$ ]]; then
    count=$count_raw
else
    echo "警告: カウンターファイル '$COUNTER_FILE' の内容が不正です。カウントを0にリセットします。"
    count=0
fi

# カウントアップして保存
count=$((count + 1))
echo "$count" > "$COUNTER_FILE"

# 3で割り切れるならjoboffer、そうでなければquestion
if [ $((count % 3)) -eq 0 ]; then
    mode="joboffer"
else
    mode="question"
fi

# === パス設定 ===
# ...existing code...
SCRIPT_PATH="$SCRIPT_DIR/run_full_posting.py"
# ...existing code...
python3 "$SCRIPT_PATH" --account "$ACCOUNT_NAME" --mode "$mode"
