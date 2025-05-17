# auto_post_bot - Notion 連携 Twitter 自動投稿システム

このプロジェクトは、Notion データベースに保存されたコンテンツ（テキストと動画）を元に、Twitter へ自動で投稿を行うための Python スクリプト群です。OpenAI API を利用して投稿文をリライトする機能や、複数の Twitter アカウントに対応する機能、macOS での定期実行設定機能も備えています。

---

## 🌟 主な機能

- **Notion 連携**: Notion データベースから投稿内容（テキスト、動画 URL）を取得します。
- **Twitter 自動投稿**: 取得した内容を Twitter に自動で投稿します（動画付きツイート、スレッド投稿対応）。
- **OpenAI によるリライト**: OpenAI API (GPT) を利用して、Notion 上のテキストを投稿用にリライトできます。
- **複数アカウント対応**: `accounts.json` に複数のアカウント情報を設定し、切り替えて使用できます。
- **Chrome プロファイル分離**: アカウントごとに Chrome のユーザープロファイルを分離し、ログイン状態を保持します。
- **投稿ステータス管理**: NotionDB 上の投稿ステータスを「投稿待ち」→「使用済み」のように自動更新します。
- **投稿予約・定期実行**:
  - `promote_used_to_pending_minimum_batch.py`: 「使用済み」の投稿を一定条件下で「投稿待ち」に戻し、投稿ネタ切れを防ぎます。
  - `run_posting.sh` と `generate_plist.py` (macOS): 指定したスケジュールで定期的に投稿処理を実行します。
- **Slack 通知**: 投稿の成功・失敗結果を Slack に通知します。
- **人間らしい振る舞い（試み）**: ランダムな User-Agent の使用や処理間のランダムな待機時間を挿入します。

---

## 📂 ディレクトリ構成

auto*post_not_blue/
├── .env # OpenAI API キーなどの環境変数を設定 (要作成)
├── accounts.json # Twitter アカウント情報、Notion 連携情報 (要作成)
├── post_tweet.py # Notion から取得した内容を Twitter に投稿するメインスクリプト
├── promote_used_to_pending_minimum_batch.py # 「使用済み」投稿を「投稿待ち」に戻すスクリプト
├── run_full_posting.py # ストック補充と投稿を連続実行するスクリプト
├── run_posting.sh # モード自動切り替え実行スクリプト (主に定期実行用)
├── generate_plist.py # macOS launchd 用 plist ファイル生成スクリプト
├── chrome_profiles/ # (初回実行時に自動生成) Chrome のユーザープロファイルが保存されるディレクトリ
├── style_prompts_questions.json # (任意) question モード用の OpenAI スタイルプロンプト
├── style_prompts_joboffers.json # (任意) joboffer モード用の OpenAI スタイルプロンプト
├── posting_counter*<アカウント名>.txt # run_posting.sh の実行回数カウンター (アカウント毎に生成)
└── requirements.txt # 必要な Python ライブラリ

---

## 🛠️ 必要なもの

- **Python 3.8 以上**: [Python 公式サイト](https://www.python.org/)
- **Google Chrome**: [Chrome 公式サイト](https://www.google.com/chrome/)
- **OpenAI API キー**: [OpenAI Platform](https://platform.openai.com/api-keys)
- **Notion API トークンとデータベース ID**: [Notion Developers](https://developers.notion.com/)
- **Slack Incoming Webhook URL** (任意): [Slack API](https://api.slack.com/messaging/webhooks)

---

## 🚀 セットアップ手順

1.  **リポジトリをクローン**

    ```bash
    git clone <リポジトリのURL>
    cd auto_post_not_blue
    ```

2.  **必要な Python ライブラリをインストール**
    プロジェクトルートに以下の内容で `requirements.txt` ファイルを作成してください。

    ```txt
    python-dotenv
    notion-client
    selenium
    openai
    requests
    pyperclip
    ```

    その後、ターミナルで以下を実行します。

    ```bash
    pip install -r requirements.txt
    ```

3.  **`.env` ファイルの作成と設定**
    プロジェクトルートに `.env` という名前のファイルを作成し、OpenAI API キーを設定します。

    ```properties
    OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    ```

    `sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` の部分を実際の API キーに置き換えてください。

4.  **`accounts.json` ファイルの作成と設定**
    プロジェクトルートに `accounts.json` という名前のファイルを作成し、以下のような形式で Twitter アカウント情報、Notion 連携情報を記述します。
    **このファイルは `.gitignore` に追加し、絶対に Git リポジトリにコミットしないでください。**

    ```json
    {
      "アカウント名1": {
        "email": "twitterアカウント1のメールアドレス",
        "username": "twitterアカウント1のユーザー名 (@なし)",
        "password": "twitterアカウント1のパスワード",
        "notion_token": "Notionインテグレーションのトークン",
        "database_ids": {
          "question": "質問用NotionデータベースID",
          "joboffer": "求人用NotionデータベースID"
        },
        "slack_webhook_url": "Slack通知用のWebhook URL (任意)"
      },
      "アカウント名2": {
        "email": "twitterアカウント2のメールアドレス"
        // ... 同様に設定 ...
      }
    }
    ```

    - `アカウント名1`, `アカウント名2`: スクリプト実行時に `--account` オプションで指定する名前です。自由に設定できます（例: `default`, `my_bot_alpha`など）。
    - `notion_token`: Notion のインテグレーションを作成し、発行された Internal Integration Token を設定します。
    - `database_ids`:
      - Notion で投稿内容を管理するデータベースを作成します。
      - データベースの URL `https://www.notion.so/your-workspace/DATABASE_ID?v=VIEW_ID` の `DATABASE_ID` の部分（32 文字の英数字）をコピーして設定します。
      - `question` と `joboffer` の 2 種類のデータベース ID を設定できます。同じ ID でも構いません。
      - **重要**: 設定した Notion インテグレーションに、これらのデータベースへの「フルアクセス」または「編集権限」を与えてください。
    - `slack_webhook_url`: 任意です。設定しない場合は Slack 通知機能は使用されません。

5.  **Notion データベースの準備**
    `accounts.json` で指定したデータベース ID に対応する Notion データベースには、以下のプロパティが必要です（プロパティ名はスクリプト内のものと一致させてください）。

    - `ステータス` (セレクトプロパティ): 値として「投稿待ち」「使用済み」が必要です。
    - `動画` (ファイルプロパティ): 投稿する動画ファイルをアップロードします。
    - `回答（編集済み）` (リッチテキストプロパティ): 投稿するメインのテキスト内容を記述します。

6.  **`style_prompts_*.json` ファイル (任意)**

    - `style_prompts_questions.json` と `style_prompts_joboffers.json` は、OpenAI で投稿文をリライトする際の指示（スタイルプロンプト）を定義するファイルです。
    - JSON 形式で、キーにアカウント名（`accounts.json` と同じもの）、値にプロンプト文字列を記述します。`"default"` キーを設定しておくと、アカウント固有のスタイルがない場合にそれが使用されます。
    - これらのファイルが存在しない、またはアカウントに対応するスタイルがない場合でも、基本的なリライト処理は行われます。
    - **例 (`style_prompts_questions.json`):**
      ```json
      {
        "default": "以下のテキストを、親しみやすく、簡潔で、絵文字を適度に含んだTwitter投稿文に変換してください。動画の内容に触れる形でお願いします。",
        "アカウント名1": "以下の内容について、専門家が初心者に語りかけるような丁寧な口調で、最大140字のツイート文案を作成してください。動画の内容を要約し、視聴を促す言葉を添えてください。"
      }
      ```

7.  **Chrome プロファイルの準備**
    - `chrome_profiles/` ディレクトリは、スクリプト初回実行時に Twitter アカウントごとに自動で作成されます。
    - ここには Chrome のセッション情報などが保存され、ログイン状態が維持されます。
    - **このディレクトリも `.gitignore` に追加し、コミットしないでください。**

---

## ▶️ 実行方法

スクリプトはプロジェクトルートディレクトリから実行してください。

### 1. 個別スクリプトの実行 (手動)

- **「使用済み」投稿を「投稿待ち」に戻す (投稿ストック補充)**

  ```bash
  python3 promote_used_to_pending_minimum_batch.py --account <アカウント名> --mode <question|joboffer>
  ```

  例: `python3 promote_used_to_pending_minimum_batch.py --account アカウント名1 --mode question`

  - NotionDB の「投稿待ち」が 1 件未満の場合、「使用済み」の中から条件を満たすものを「投稿待ち」に更新します。

- **Twitter へ投稿**
  ```bash
  python3 post_tweet.py --account <アカウント名> --mode <question|joboffer>
  ```
  例: `python3 post_tweet.py --account アカウント名1 --mode question`
  - NotionDB の「投稿待ち」から 1 件取得し、OpenAI でリライト後、Twitter に投稿します。
  - 成功すると NotionDB のステータスを「使用済み」に更新します。

### 2. 一括実行 (手動)

- **ストック補充と投稿を連続実行**
  ```bash
  python3 run_full_posting.py --account <アカウント名> --mode <question|joboffer>
  ```
  例: `python3 run_full_posting.py --account アカウント名1 --mode joboffer`
  - 内部で `promote_used_to_pending_minimum_batch.py` と `post_tweet.py` を順に実行します。

### 3. モード自動切り替え実行 (手動)

- **`run_posting.sh` を使用 (主に定期実行用だが手動も可)**
  このシェルスクリプトは、実行回数に応じて `--mode` (`question` / `joboffer`) を自動で切り替えて `run_full_posting.py` を呼び出します。
  まず、実行権限を付与します。
  ```bash
  chmod +x run_posting.sh
  ```
  実行方法:
  ```bash
  ./run_posting.sh <アカウント名>
  ```
  例: `./run_posting.sh アカウント名1`
  - 実行するたびに `posting_counter_<アカウント名>.txt` ファイルのカウントが 1 増えます。
  - カウントが 3 の倍数の時は `--mode joboffer`、それ以外は `--mode question` で実行されます。

### 4. 定期実行 (macOS - launchd)

`generate_plist.py` スクリプトを使用すると、macOS の `launchd` を使って定期的に投稿処理 (`run_posting.sh`経由) を実行するための設定ファイル (plist) を生成し、自動で登録します。

- **plist 生成と登録**

  ```bash
  python3 generate_plist.py
  ```

  - このスクリプトを実行すると、`accounts.json` に定義されている全てのアカウントに対して、個別の plist ファイルが `~/Library/LaunchAgents/` ディレクトリに生成・登録されます。
  - 各アカウントの投稿時間は、昼 12 時から翌朝 6 時までの間で、約 1 時間半おきに、アカウント間で均等に分散されるようにスケジュールされます。
  - 最初のアカウント (`accounts.json` の最初に定義されているアカウント) のみ、`RunAtLoad` が `true` に設定され、plist ロード直後（通常はログイン時やスクリプト実行時）にも一度実行されます。
  - **注意**:
    - `run_posting.sh` に実行権限 (`chmod +x run_posting.sh`) が必要です。
    - 環境変数 `PATH` の設定が重要です。`generate_plist.py` は `pyenv` のパスを自動で追加しようとしますが、環境によっては `run_posting.sh` 内で `python3` コマンドが見つからない場合があります。その場合は、`run_posting.sh` の `python3` をフルパス（例: `/usr/local/bin/python3` や `~/.pyenv/shims/python3`）に書き換えるか、plist 内の `EnvironmentVariables` の `PATH` を調整してください。
    - **Chrome がバックグラウンドで起動できる状態**である必要があります。macOS のセキュリティ設定や省電力設定により、GUI アプリケーションのバックグラウンド実行が制限される場合があります。
    - 定期実行を停止・変更したい場合は、再度 `generate_plist.py` を実行するか、`~/Library/LaunchAgents/` 内の該当する plist ファイルを直接編集・削除し、`launchctl unload <plistファイルパス>` および `launchctl load <plistファイルパス>` を実行してください。

- **ログの確認 (定期実行時)**
  `generate_plist.py` で設定した場合、各アカウントの実行ログは以下の場所に保存されます。
  - 標準出力: `~/Library/Logs/com.auto_post/<アカウント名>.out.log`
  - 標準エラー: `~/Library/Logs/com.auto_post/<アカウント名>.err.log`
    何か問題が発生した場合は、これらのログファイルを確認してください。

---

## ⚙️ 各スクリプトの詳細

- **`post_tweet.py`**:

  - Selenium を使用して Chrome を操作し、Twitter へのログイン、動画アップロード、テキスト投稿、リプライ（スレッド投稿）を行います。
  - OpenAI API を呼び出し、Notion から取得したテキストをリライトします。
  - 投稿成功後、Notion ページのステータスを「使用済み」に更新します。
  - エラー発生時や処理結果を Slack に通知します。

- **`promote_used_to_pending_minimum_batch.py`**:

  - 指定された Notion データベースの「投稿待ち」ステータスの投稿数をカウントします。
  - 「投稿待ち」が一定数（デフォルト 1 件）未満の場合、「使用済み」ステータスで条件（動画あり、編集済み回答あり）を満たす投稿を「投稿待ち」に更新します。

- **`run_full_posting.py`**:

  - `promote_used_to_pending_minimum_batch.py` を実行し、その後 `post_tweet.py` を実行するシンプルなラッパースクリプトです。引数を透過的に渡します。

- **`run_posting.sh`**:

  - 引数で指定されたアカウント名で `run_full_posting.py` を呼び出します。
  - 実行回数をカウントし、3 回に 1 回の割合で `--mode joboffer`、それ以外は `--mode question` を `run_full_posting.py` に渡します。

- **`generate_plist.py`**:
  - `accounts.json` を読み込み、定義されている各アカウントに対して macOS の `launchd` 用の `.plist` ファイルを生成します。
  - 生成された plist は、`run_posting.sh` を指定したスケジュールで実行するように設定されます。
  - 既存の同名 plist ファイルはアンロード・削除された後、新しい設定でロードされます。

---

## ⚠️ 注意事項

- **機密情報管理**:
  - `.env` ファイル (OpenAI API キー)
  - `accounts.json` ファイル (Twitter/Notion/Slack の認証情報)
  - `chrome_profiles/` ディレクトリ (Twitter のログインセッション)
    これらは機密情報を含みます。必ず `.gitignore` に追加し、Git リポジトリにコミットしないでください。(デフォルトの `.gitignore` にこれらを追加する設定を推奨します)
- **Twitter の利用規約**: 自動投稿は Twitter のルールに従って行う必要があります。過度な投稿やスパム行為とみなされる可能性のある利用は避けてください。このスクリプトの使用によって生じたいかなる問題についても、開発者は責任を負いません。
- **API の変更**: Twitter, Notion, OpenAI, Slack の API 仕様は変更される可能性があります。API の変更によりスクリプトが動作しなくなる場合があります。

---

## 🐛 トラブルシューティング

- **スクリプトが動かない**:
  - Python のバージョン、ライブラリのインストールを確認してください。
  - `.env` や `accounts.json` の設定内容（API キー、トークン、ID、ファイルパスなど）が正しいか確認してください。
  - Notion インテグレーションにデータベースへのアクセス権限が付与されているか確認してください。
  - ターミナルに表示されるエラーメッセージをよく読んでください。
- **定期実行が動かない (macOS)**:
  - `~/Library/Logs/com.auto_post/` 内のログファイルを確認してください。
  - `run_posting.sh` に実行権限が付与されているか確認してください (`ls -l run_posting.sh`)。
  - `launchctl list | grep com.auto_post` でジョブがロードされているか確認してください。
  - plist ファイル (`~/Library/LaunchAgents/com.auto_post.<アカウント名>.plist`) の内容、特に `ProgramArguments` のパスが正しいか確認してください。
  - macOS の「セキュリティとプライバシー」設定で、ターミナルや Python、Chrome による自動操作が許可されているか確認してください。
- **Chrome が起動しない/ログインできない**:
  - Chrome が最新版であるか確認してください。
  - `chrome_profiles/` ディレクトリを一度削除して、スクリプトに再生成させてみてください。
  - 手動で Chrome を起動し、該当アカウントで Twitter にログインできるか確認してください。

不明な点があれば、エラーメッセージと共に開発者に相談してください。

---

## License

This project is licensed under the MIT License.
