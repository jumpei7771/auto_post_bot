import os
import re
import time
import json
import random
import datetime
import argparse
import platform
import requests
import pyperclip
import unicodedata
import sys
from openai import OpenAI
from dotenv import load_dotenv
from notion_client import Client
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# from selenium.webdriver.chrome.options import Options # 重複インポート
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchWindowException,
    TimeoutException,
    NoSuchElementException,
)

# === Notion & Twitter定数 ===
CHAR_LIMIT = random.randint(135, 150)
VIDEO_FILE_NAME = "notion_video.mp4"

# ランダムに選ばれるUser-Agentリスト
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


def log(message):
    """
    現在時刻と共にメッセージをコンソールに出力する。
    Args:
        message (str): 出力するメッセージ。
    """
    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}")


def is_effectively_empty(text):
    """
    テキストが実質的に空かどうか（空白や制御文字のみでないか）を判定する。
    Args:
        text (str): 判定対象のテキスト。
    Returns:
        bool: 実質的に空であればTrue、そうでなければFalse。
    """
    stripped = text.strip()
    if not stripped:
        return True
    for c in stripped:
        if unicodedata.category(c)[0] not in ["C", "Z"]:  # Control / Separator
            return False
    return True


def load_config(account_name, path="accounts.json"):
    """
    指定されたアカウントの設定情報をJSONファイルから読み込む。
    Args:
        account_name (str): 読み込むアカウント名。
        path (str, optional): 設定ファイルのパス。デフォルトは "accounts.json"。
    Returns:
        dict: アカウントの設定情報。
    Raises:
        FileNotFoundError: 設定ファイルが見つからない場合。
        ValueError: 指定されたアカウント名が設定ファイルに存在しない場合。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} が見つかりません")

    with open(path, "r", encoding="utf-8") as f:
        accounts = json.load(f)

    if account_name not in accounts:
        raise ValueError(f"指定されたアカウント '{account_name}' は存在しません")

    return accounts[account_name]


def send_slack_notify(message: str) -> bool:
    """
    Slackにメッセージを通知する。
    Args:
        message (str): Slackに送信するメッセージ。
    Returns:
        bool: 通知が成功した場合はTrue、失敗した場合はFalse。
    """
    payload = {"text": message}
    try:
        res = requests.post(SLACK_WEBHOOK_URL, json=payload)
        res.raise_for_status()
        log("✅ Slack通知送信成功")
        return True
    except Exception as e:
        log(f"❌ Slack通知に失敗: {e}")
        return False


def get_valid_page():
    """
    Notionデータベースから「投稿待ち」ステータスで条件を満たす最初のページを取得する。
    条件: ステータスが「投稿待ち」、動画ファイルが存在、回答（編集済み）が空でない。
    Returns:
        tuple: (content, page_id, video_url)
               content (str): 投稿するテキスト内容。
               page_id (str): NotionページのID。
               video_url (str): 添付動画のURL。
               対象が見つからない場合やエラー時は (None, None, None) を返す。
    """
    log("🔍 投稿待ちの投稿を取得中...")
    try:
        results = notion.databases.query(
            database_id=DATABASE_ID,
            page_size=100,  # 十分な数を取得
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
            sorts=[
                {"timestamp": "created_time", "direction": "ascending"}
            ],  # 古いものから
        ).get("results")
    except Exception as e:
        log(f"❌ 投稿待ちの取得に失敗しました: {e}")
        send_slack_notify(f"❌ 投稿待ちの取得に失敗: {e}")
        return None, None, None

    if not results:
        log("❌ 投稿待ちに投稿対象が見つかりませんでした → 終了")
        send_slack_notify("❌ 投稿待ちに投稿対象が見つかりませんでした")
        return None, None, None

    page = results[0]  # 最初の1件を取得
    log(f"✅ 投稿対象を取得 → ページID: {page['id']}")
    content = "".join(
        block["text"]["content"]
        for block in page["properties"]["回答（編集済み）"]["rich_text"]
    )
    page_id = page["id"]
    video_url = page["properties"]["動画"]["files"][0]["file"]["url"]
    return content, page_id, video_url


def get_driver():
    """
    Selenium WebDriver (Chrome) のインスタンスを生成して返す。
    User-Agentのランダム選択、プロファイルディレクトリの設定などを行う。
    Returns:
        selenium.webdriver.chrome.webdriver.WebDriver: WebDriverインスタンス。
    """
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--start-maximized")

    user_agent = random.choice(USER_AGENTS)
    options.add_argument(f"user-agent={user_agent}")
    log(f"🎯 選ばれたUser-Agent: {user_agent}")

    profile_dir = os.path.join(os.getcwd(), "chrome_profiles", TWITTER_USERNAME)
    os.makedirs(profile_dir, exist_ok=True)
    options.add_argument(f"--user-data-dir={profile_dir}")

    driver = webdriver.Chrome(options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def login(driver):
    """
    Twitterにログインする。既にログイン済みの場合はスキップする。
    Args:
        driver (selenium.webdriver.chrome.webdriver.WebDriver): WebDriverインスタンス。
    """
    driver.get("https://twitter.com/home")
    time.sleep(random.uniform(2.5, 3.5))

    if "ログイン" not in driver.title and "/login" not in driver.current_url:
        log("✅ 既にログイン状態 → ログイン処理スキップ")
        driver.get("https://twitter.com/compose/post")  # 投稿画面へ
        return

    log("🔐 ログイン処理を開始（セッション未保持のため）")
    driver.get("https://twitter.com/i/flow/login")

    # メールアドレス入力
    email_input = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.NAME, "text"))
    )
    email_input.send_keys(TWITTER_EMAIL)
    email_input.send_keys(Keys.ENTER)
    time.sleep(random.uniform(2.0, 3.0))

    # ユーザー名入力（必要な場合）
    try:
        username_input = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.NAME, "text"))
        )
        username_input.send_keys(TWITTER_USERNAME)
        username_input.send_keys(Keys.ENTER)
        time.sleep(random.uniform(2.0, 3.0))
    except Exception:
        log("👤 ユーザー名入力スキップ")

    # パスワード入力
    password_input = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.NAME, "password"))
    )
    password_input.send_keys(TWITTER_PASSWORD)
    password_input.send_keys(Keys.ENTER)
    time.sleep(random.uniform(6.0, 7.0))  # ログイン完了待ち

    log("✅ ログイン成功 → 投稿画面に移動")
    driver.get("https://twitter.com/compose/post")


def split_text(text, limit=CHAR_LIMIT):
    """
    指定された文字数制限に基づいてテキストを分割する。
    Args:
        text (str): 分割対象のテキスト。
        limit (int, optional): 1チャンクあたりの最大文字数。デフォルトはCHAR_LIMIT。
    Returns:
        list: 分割されたテキストのリスト。
    """
    log(f"🔍 テキストを {limit} 文字ごとに分割中...")
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def paste_and_send(driver, selector, content):
    """
    指定されたCSSセレクタの要素にコンテンツをペーストし、投稿を試みる。
    投稿ボタンのクリックとキーボードショートカットを試行し、成功判定を行う。
    Args:
        driver (selenium.webdriver.chrome.webdriver.WebDriver): WebDriverインスタンス。
        selector (str): テキスト入力エリアのCSSセレクタ。
        content (str): 投稿するテキスト内容。
    Returns:
        bool: 投稿に成功した場合はTrue、失敗した場合はFalse。
    """
    try:
        area = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
        log(f"📋 テキストエリア ({selector}) が見つかりました。")

        pyperclip.copy(content)
        log("📋 クリップボードにコンテンツをコピーしました。")

        ActionChains(driver).move_to_element(area).click().perform()
        time.sleep(random.uniform(0.5, 1.0))

        keys_modifier = Keys.COMMAND if platform.system() == "Darwin" else Keys.CONTROL
        ActionChains(driver).key_down(keys_modifier).send_keys("v").key_up(
            keys_modifier
        ).perform()
        log("📋 クリップボードからテキストをペーストしました。")
        time.sleep(random.uniform(1.5, 2.5))

    except Exception as e_paste:
        log(f"❌ テキストエリアへのペースト処理中にエラー: {e_paste}")
        return False

    max_retries = 3
    for attempt in range(max_retries):
        log(f"📤 送信試行 {attempt + 1}/{max_retries}...")
        send_action_successful = False

        primary_send_button_css = 'button[data-testid="tweetButton"]'
        try:
            log(
                f"🔍 送信ボタン ({primary_send_button_css}) をCSSセレクタで探しています..."
            )
            send_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, primary_send_button_css))
            )
            log(f"✅ 送信ボタン ({primary_send_button_css}) がクリック可能です。")
            time.sleep(random.uniform(0.5, 1.2))
            driver.execute_script("arguments[0].scrollIntoView(true);", send_button)
            time.sleep(0.3)
            driver.execute_script("arguments[0].click();", send_button)
            log(f"📩 送信ボタン ({primary_send_button_css}) をクリックしました。")
            send_action_successful = True
        except Exception as e_button_click:
            log(
                f"⚠️ CSSセレクタ ({primary_send_button_css}) で送信ボタンのクリックに失敗 (試行 {attempt + 1}): {str(e_button_click).splitlines()[0]}"
            )

        if not send_action_successful:
            log(
                "↳ プライマリ送信ボタンの処理に失敗したため、フォールバックとしてキーボードショートカット (⌘/Ctrl + Enter) を試みます。"
            )
            try:
                text_area_for_keys = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                ActionChains(driver).move_to_element(
                    text_area_for_keys
                ).click().perform()
                time.sleep(random.uniform(0.3, 0.7))
                ActionChains(driver).key_down(keys_modifier).send_keys(
                    Keys.ENTER
                ).key_up(keys_modifier).perform()
                log("📩 キーボードショートカット (⌘/Ctrl + Enter) を送信しました。")
                send_action_successful = True
            except Exception as e_keys_send:
                log(
                    f"❌ キーボードショートカットの送信にも失敗しました (試行 {attempt + 1}): {str(e_keys_send).splitlines()[0]}"
                )

        if not send_action_successful:
            log(f"❌ 送信アクションの実行に失敗しました (試行 {attempt + 1})。")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(3.0, 4.5))
                continue
            else:
                log(
                    f"❌ {max_retries}回試行しましたが、送信アクションを実行できませんでした。"
                )
                return False

        log("⏳ 投稿処理の反映を待っています...")
        time.sleep(random.uniform(5.0, 7.5))

        try:
            text_area_check = WebDriverWait(driver, 7).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            current_text_area_content = text_area_check.get_attribute(
                "textContent"
            ).strip()
            log(
                f"💬 テキストエリア内容確認: '{current_text_area_content[:100].replace(chr(10), '↵')}'"
            )
            if not current_text_area_content:
                log("✅ テキストエリアが空になりました。投稿成功と判定します。")
                return True
            else:
                log(f"⚠️ テキストエリアにまだ文字が残っています (試行 {attempt + 1})。")
        except Exception as e_text_check:
            log(f"⚠️ テキストエリアの内容確認中にエラーが発生しました: {e_text_check}")

        if attempt < max_retries - 1:
            log("🔄 次の送信試行の準備をします...")
            time.sleep(random.uniform(2.5, 4.0))
        else:
            log(
                f"❌ 最大リトライ回数 ({max_retries}回) に達しましたが、テキストエリアに文字が残っています。"
            )

    log(f"❌ 投稿失敗: {max_retries}回の試行後も投稿を完了できませんでした。")
    return False


def download_video(url):
    """
    指定されたURLから動画をダウンロードし、ローカルに保存する。
    Args:
        url (str): ダウンロードする動画のURL。
    Returns:
        str or None: 保存された動画ファイルの絶対パス。ダウンロード失敗時はNone。
    """
    try:
        res = requests.get(url)
        res.raise_for_status()  # HTTPエラーチェック
        with open(VIDEO_FILE_NAME, "wb") as f:
            f.write(res.content)
        return os.path.abspath(VIDEO_FILE_NAME)
    except Exception as e:
        log(f"❌ 動画のダウンロードに失敗: {e}")
        send_slack_notify(f"❌ 動画のダウンロードに失敗: {e}")
        return None


def post_tweet(driver, content, media_path=None, single_post_mode=False):
    """
    Twitterにツイートを投稿する。メディア添付、単一投稿モードに対応。
    投稿後、成功した場合はツイートのURLを返す。
    Args:
        driver (selenium.webdriver.chrome.webdriver.WebDriver): WebDriverインスタンス。
        content (str): 投稿するテキスト内容。
        media_path (str, optional): 添付するメディアファイルのパス。デフォルトはNone。
        single_post_mode (bool, optional): 単一投稿モードか否か。Trueの場合、URL取得をスキップ。デフォルトはFalse。
    Returns:
        str or None: 投稿成功時はツイートURL、単一投稿成功時は "SUCCESS_SINGLE_POST"。失敗時はNone。
    """
    try:
        if media_path:
            # メディアファイルをアップロード
            upload_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, '//input[@type="file"]'))
            )
            upload_input.send_keys(media_path)
            time.sleep(random.uniform(3.0, 3.5))  # アップロード完了待ち

        # paste_and_send関数を呼び出して投稿処理
        if not paste_and_send(
            driver,
            'div[data-testid="tweetTextarea_0"][role="textbox"][aria-label="ポスト本文"]',
            content,
        ):
            log("❌ paste_and_send での投稿に失敗しました。")
            return None  # paste_and_sendがFalseを返したら投稿失敗

        if single_post_mode:
            log("✅ 1投稿のみのためプロフ遷移スキップ → 投稿成功と判定")
            return "SUCCESS_SINGLE_POST"

        # 投稿後にプロフィールへ移動し、最新のツイートURLを取得
        time.sleep(random.uniform(2.0, 2.5))
        profile_url = f"https://twitter.com/{TWITTER_USERNAME}"
        driver.get(profile_url)
        time.sleep(random.uniform(3.0, 4.0))  # プロフィールページ読み込み待ち

        # 最新のツイートのリンク要素を取得
        # より確実に自分のツイートを取得するために、ユーザー名を含むXPathを検討することもできる
        latest_tweet_link_elements = driver.find_elements(
            By.XPATH,
            f'//article[@data-testid="tweet" and .//span[contains(text(), "@{TWITTER_USERNAME}")]]//a[contains(@href, "/status/")]',
        )
        if not latest_tweet_link_elements:
            log("❌ プロフィールページで最新のツイートリンクが見つかりませんでした。")
            return None

        # 複数のリンクが見つかる可能性があるので、最もそれらしいもの（通常は最初のもの）を選ぶ
        # さらに、投稿内容と照合するロジックを追加するとより堅牢になる
        tweet_url = None
        for link_element in latest_tweet_link_elements:
            href = link_element.get_attribute("href")
            if href and f"/{TWITTER_USERNAME}/status/" in href:
                # time要素を持つリンクを優先する (より投稿に近い要素である可能性)
                try:
                    link_element.find_element(By.XPATH, ".//time")
                    tweet_url = href
                    log(f"  ツイートURL候補 (time要素あり): {tweet_url}")
                    break  # time要素を持つものが見つかればそれを採用
                except NoSuchElementException:
                    if (
                        not tweet_url
                    ):  # まだURLが設定されていなければ、最初の候補として保持
                        tweet_url = href
                        log(f"  ツイートURL候補 (time要素なし): {tweet_url}")

        if not tweet_url:
            log("❌ 適切なツイートURLの特定に失敗しました。")
            return None

        # URLの正規化 (ユーザー名部分を強制的に正しいものに)
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(tweet_url)
        path_parts = parsed.path.strip("/").split("/")
        if (
            len(path_parts) >= 3 and path_parts[1] == "status"
        ):  # [username, "status", tweet_id]
            new_path = f"/{TWITTER_USERNAME}/status/{path_parts[2]}"
            tweet_url = urlunparse(parsed._replace(path=new_path))
            log(f"  正規化されたツイートURL: {tweet_url}")
        else:
            log(f"⚠️ ツイートURLのパス構造が予期しない形式です: {parsed.path}")
            # この場合でも元のtweet_urlをそのまま使うか、エラーとするか検討

        if not tweet_url or "/status/" not in tweet_url:  # 再度チェック
            log("❌ 正しい投稿URLの取得に失敗しました (正規化後)。")
            return None

        log(f"✅ 投稿完了 → 自身の最新投稿URLを取得: {tweet_url}")
        return tweet_url
    except Exception as e:
        log(f"❌ 投稿またはURL取得で例外発生: {e}")
        # driver.save_screenshot(f"error_post_tweet_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        return None
    finally:
        if media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
                log(f"🗑️ # 投稿用に一時保存された動画を削除: {media_path}")
            except Exception as e:
                log(f"⚠️ # 投稿用に一時保存された動画を削除に失敗しました: {e}")


def close_premium_popup(driver):
    """
    Twitterのプレミアム加入を促すポップアップをEscキーで閉じる試みを行う。
    Args:
        driver (selenium.webdriver.chrome.webdriver.WebDriver): WebDriverインスタンス。
    """
    try:
        log("⚠️ Escキー送信（待機なし）")
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    except Exception as e:
        log(f"❌ Escキー送信に失敗: {e}")


def remove_non_bmp(text):
    """
    テキストからBMP（基本多言語面）以外の文字を除去する。
    Args:
        text (str): 対象のテキスト。
    Returns:
        str: BMP外の文字が除去されたテキスト。
    """
    return "".join(c for c in text if c <= "\uffff")


def remove_emojis(text):
    """
    テキストから絵文字を除去する。
    Args:
        text (str): 対象のテキスト。
    Returns:
        str: 絵文字が除去されたテキスト。
    """
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"
        "\U0001f300-\U0001f5ff"
        "\U0001f680-\U0001f6ff"
        "\U0001f1e0-\U0001f1ff"
        "\U00002700-\U000027bf"
        "\U0001f900-\U0001f9ff"
        "\U00002600-\U000026ff"
        "\u200d"
        "\u2640-\u2642"
        "\ufe0f"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub(r"", text)


def strip_invisible(text):
    """
    テキストから非表示文字（制御文字など）を除去する。
    Args:
        text (str): 対象のテキスト。
    Returns:
        str: 非表示文字が除去されたテキスト。
    """
    return "".join(
        c
        for c in text
        if c.isprintable() and not unicodedata.category(c).startswith("C")
    )


def check_driver_window(driver, operation_name=""):
    """
    WebDriverのウィンドウハンドルが存在するか確認する。
    ウィンドウが閉じている可能性がある場合にFalseを返す。
    Args:
        driver (selenium.webdriver.chrome.webdriver.WebDriver): WebDriverインスタンス。
        operation_name (str, optional): 操作名（ログ出力用）。デフォルトは空文字。
    Returns:
        bool: ウィンドウハンドルが存在すればTrue、そうでなければFalse。
    """
    try:
        handles = driver.window_handles
        if not handles:
            log(
                f"❌ {operation_name}: ウィンドウハンドルが空です。ウィンドウが閉じている可能性があります。"
            )
            return False
        return True
    except NoSuchWindowException:
        log(
            f"❌ {operation_name}: ウィンドウハンドルの確認中に NoSuchWindowException が発生しました。"
        )
        return False
    except Exception as e:
        log(
            f"❌ {operation_name}: ウィンドウハンドルの確認中に予期せぬエラー: {type(e).__name__} - {e}"
        )
        return False


def reply_to_tweet(driver, tweet_url, reply_content, is_last_reply=False):
    """
    指定されたツイートURLに対してリプライを投稿する。
    Args:
        driver (selenium.webdriver.chrome.webdriver.WebDriver): WebDriverインスタンス。
        tweet_url (str): リプライ対象のツイートURL。
        reply_content (str): リプライするテキスト内容。
        is_last_reply (bool, optional): これがスレッドの最後のリプライか否か。デフォルトはFalse。
    Returns:
        str or None: 投稿成功時は新しいリプライのURL、または "SUCCESS_LAST_REPLY"。失敗時はNone。
    """
    log(
        f"💬 リプライを開始します: {tweet_url} へ「{reply_content[:30]}...」 (最後のリプライ: {is_last_reply})"
    )
    try:
        if not check_driver_window(driver, "reply_to_tweet開始時"):
            return None

        log(f"🔁 リプライ対象URLへアクセス: {tweet_url}")
        driver.get(tweet_url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located(
                (By.XPATH, '//article[@data-testid="tweet"]')
            )
        )
        log("✅ リプライ対象のツイートページ読み込み完了。")
        time.sleep(random.uniform(1.5, 2.5))

        if not check_driver_window(driver, "リプライ入力エリア検索前"):
            return None

        reply_area_selector = 'div[data-testid="tweetTextarea_0"][role="textbox"]'

        try:
            reply_area = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, reply_area_selector))
            )
            log(f"📋 リプライ入力エリア ({reply_area_selector}) が見つかりました。")
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
                reply_area,
            )
            time.sleep(0.5)
            ActionChains(driver).move_to_element(reply_area).click().perform()
            time.sleep(random.uniform(0.5, 1.0))
        except NoSuchWindowException as e_focus_nw:
            log(
                f"❌ リプライ入力エリアのフォーカス中にウィンドウが閉じました: {type(e_focus_nw).__name__} - {e_focus_nw}"
            )
            return None
        except Exception as e_focus:
            log(
                f"❌ リプライ入力エリアのフォーカスに失敗: {type(e_focus).__name__} - {e_focus}"
            )
            return None

        if not check_driver_window(driver, "リプライペースト前"):
            return None

        pyperclip.copy(reply_content)
        keys_modifier = Keys.COMMAND if platform.system() == "Darwin" else Keys.CONTROL
        ActionChains(driver).key_down(keys_modifier).send_keys("v").key_up(
            keys_modifier
        ).perform()
        log("📋 クリップボードからリプライ内容をペーストしました。")
        time.sleep(random.uniform(1.0, 1.5))

        max_retries_reply = 2
        send_action_successful = False

        for attempt in range(max_retries_reply):
            log(f"📤 リプライ送信試行 {attempt + 1}/{max_retries_reply}...")
            if not check_driver_window(
                driver, f"リプライ送信試行 {attempt + 1} 開始時"
            ):
                return None

            reply_button_inline_xpath = '//div[@data-testid="inline_reply_offscreen"]//button[@data-testid="tweetButtonInline"]'
            reply_specific_button_xpath = '//div[@data-testid="inline_reply_offscreen"]//button[@data-testid="tweetButton"]'
            reply_send_button_xpath_primary = (
                '(//button[@data-testid="tweetButton"])[1]'
            )
            reply_send_button_xpath_dialog = (
                '//div[@role="dialog"]//button[@data-testid="tweetButton"]'
            )
            selectors_to_try = [
                (By.XPATH, reply_button_inline_xpath, "XPath (Reply Inline Button)"),
                (
                    By.XPATH,
                    reply_specific_button_xpath,
                    "XPath (Reply Screen Specific)",
                ),
                (By.XPATH, reply_send_button_xpath_dialog, "XPath (Dialog)"),
                (By.XPATH, reply_send_button_xpath_primary, "XPath (Primary)"),
                (
                    By.CSS_SELECTOR,
                    'button[data-testid="tweetButton"]',
                    "CSS Selector (General tweetButton)",
                ),
                (
                    By.CSS_SELECTOR,
                    'button[data-testid="tweetButtonInline"]',
                    "CSS Selector (General tweetButtonInline)",
                ),
            ]

            for by_type, selector_value, selector_name in selectors_to_try:
                if send_action_successful:
                    break
                if not check_driver_window(driver, f"セレクタ {selector_name} 試行前"):
                    return None
                the_button_element = None
                try:
                    log(
                        f"🔍 リプライ送信ボタン ({selector_value}) を{selector_name}で探しています..."
                    )
                    presence_wait_duration = 10
                    the_button_element = WebDriverWait(
                        driver, presence_wait_duration
                    ).until(EC.presence_of_element_located((by_type, selector_value)))
                    log(f"  ✅ 要素 ({selector_name}) がDOMに存在します。")

                    if not the_button_element.is_displayed():
                        log(
                            f"  ⚠️ 要素 ({selector_name}) はDOMに存在しますが、表示されていません。スキップします。"
                        )
                        continue
                    if not the_button_element.is_enabled():
                        log(
                            f"  ⚠️ 要素 ({selector_name}) は表示されていますが、有効ではありません (is_enabled()=False)。スキップします。"
                        )
                        continue
                    log(f"  ℹ️ 要素 ({selector_name}) の状態: 表示=True, 有効=True")

                    driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                        the_button_element,
                    )
                    log(f"  📜 要素 ({selector_name}) を中央にスクロールしました。")
                    time.sleep(random.uniform(0.5, 1.0))

                    clickable_wait_duration = 5
                    WebDriverWait(driver, clickable_wait_duration).until(
                        EC.element_to_be_clickable(the_button_element)
                    )
                    log(
                        f"✅ リプライ送信ボタン ({selector_name} - {selector_value}) がクリック可能です。"
                    )
                    if not the_button_element.is_enabled():
                        log(
                            f"  ⚠️ クリック直前でボタンが無効化されました ({selector_name})。スキップします。"
                        )
                        continue
                    driver.execute_script("arguments[0].click();", the_button_element)
                    log(
                        f"📩 リプライ送信ボタン ({selector_name} - {selector_value}) をJavaScriptでクリックしました。"
                    )
                    send_action_successful = True
                    break
                except TimeoutException as e_timeout:
                    log(
                        f"⚠️ {selector_name} ({selector_value}) でタイムアウト (試行 {attempt + 1}): {str(e_timeout).splitlines()[0]}"
                    )
                    if the_button_element:
                        try:
                            log(
                                f"  ℹ️ タイムアウト時の要素状態: 表示={the_button_element.is_displayed()}, 有効={the_button_element.is_enabled()}, 位置={the_button_element.location}, サイズ={the_button_element.size}, テキスト='{the_button_element.text[:30]}'"
                            )
                        except Exception as e_state:
                            log(f"  ℹ️ タイムアウト時の要素状態取得失敗: {e_state}")
                    else:
                        log(
                            f"  ℹ️ 要素 ({selector_name}) がDOM内で見つからなかったか、存在確認の段階でタイムアウトしました。"
                        )
                except NoSuchWindowException as e_btn_click_nw:
                    log(
                        f"⚠️ {selector_name} ({selector_value}) でボタン操作中にウィンドウが閉じました (試行 {attempt + 1}): {type(e_btn_click_nw).__name__} - {e_btn_click_nw}"
                    )
                    return None
                except Exception as e_button_click:
                    log(
                        f"⚠️ {selector_name} ({selector_value}) でリプライ送信ボタンの処理中に予期せぬエラー (試行 {attempt + 1}): {type(e_button_click).__name__} - {str(e_button_click).splitlines()[0]}"
                    )

            if send_action_successful:
                break
            if not send_action_successful and attempt < max_retries_reply:
                log(
                    f"↳ ボタンクリックに失敗したため (試行 {attempt + 1})、フォールバックとしてキーボードショートカット (⌘/Ctrl + Enter) を試みます。"
                )
                try:
                    active_reply_area = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, reply_area_selector)
                        )
                    )
                    ActionChains(driver).move_to_element(
                        active_reply_area
                    ).click().perform()
                    time.sleep(random.uniform(0.3, 0.7))
                    ActionChains(driver).key_down(keys_modifier).send_keys(
                        Keys.ENTER
                    ).key_up(keys_modifier).perform()
                    log(
                        "📩 キーボードショートカット (⌘/Ctrl + Enter) を送信しました (リプライ)。"
                    )
                    send_action_successful = True
                    break
                except NoSuchWindowException as e_keys_nw:
                    log(
                        f"❌ キーボードショートカット送信中にウィンドウが閉じました (リプライ試行 {attempt + 1}): {type(e_keys_nw).__name__} - {e_keys_nw}"
                    )
                    return None
                except Exception as e_keys_send:
                    log(
                        f"❌ キーボードショートカットの送信にも失敗しました (リプライ試行 {attempt + 1}): {type(e_keys_send).__name__} - {str(e_keys_send).splitlines()[0]}"
                    )
            if send_action_successful:
                break
            if attempt < max_retries_reply - 1:
                log(f"リトライ待機中 (試行 {attempt + 1} 失敗)...")
                time.sleep(random.uniform(2.5, 4.0))

        if not send_action_successful:
            log(
                f"❌ {max_retries_reply}回試行しましたが、リプライの送信アクションを実行できませんでした。"
            )
            return None

        log("⏳ リプライ送信後のUI反映を待っています...")
        time.sleep(random.uniform(4.0, 5.5))

        reply_successful_based_on_area = False
        try:
            WebDriverWait(driver, 10).until_not(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, f'{reply_area_selector}[aria-busy="true"]')
                )
            )
            log("✅ リプライエリアのaria-busy状態が解除されました。")
            for check_count in range(3):
                if not check_driver_window(
                    driver, f"リプライエリア内容確認 {check_count+1}回目"
                ):
                    return None
                reply_area_check = driver.find_element(
                    By.CSS_SELECTOR, reply_area_selector
                )
                current_reply_area_content = reply_area_check.get_attribute(
                    "textContent"
                ).strip()
                if not current_reply_area_content:
                    log(
                        "✅ リプライ入力エリアが空になりました。リプライ成功と判定します。"
                    )
                    reply_successful_based_on_area = True
                    break
                log(
                    f"⚠️ リプライ入力エリアに文字が残っています ({check_count+1}/3): '{current_reply_area_content[:70].replace(chr(10), '↵')}'"
                )
                if check_count < 2:
                    time.sleep(1.5)
        except (NoSuchElementException, TimeoutException) as e_area_check:
            log(
                f"✅ リプライ入力エリアが見つからないかタイムアウトしました ({type(e_area_check).__name__})。リプライ成功と見なします (エリアが消えた可能性)。"
            )
            reply_successful_based_on_area = True
        except Exception as e_text_check_unexpected:
            log(
                f"⚠️ リプライ入力エリアの確認中に予期せぬエラー: {type(e_text_check_unexpected).__name__} - {e_text_check_unexpected}"
            )

        if not reply_successful_based_on_area:
            log(
                "❌ リプライ入力エリアのクリア確認で最終的に失敗しました。リプライ失敗とみなします。"
            )
            return None

        close_premium_popup(driver)

        if is_last_reply:
            log("✅ 最後のリプライ投稿成功。URL取得はスキップします。")
            return "SUCCESS_LAST_REPLY"

        log("⏳ 新しいリプライURLの取得を試みます (現在のページから)...")
        new_reply_url = None
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(random.uniform(2.0, 2.5))

            if not check_driver_window(driver, "リプライURL取得のための記事検索前"):
                return None

            articles = driver.find_elements(By.XPATH, '//article[@data-testid="tweet"]')
            log(f"📦 現在のページで検出された投稿記事数: {len(articles)}")

            if articles:
                normalized_reply_content_for_comp = strip_invisible(
                    remove_emojis(
                        unicodedata.normalize(
                            "NFKC", remove_non_bmp(reply_content.strip())
                        )[:20]
                    )
                ).replace(" ", "")
                found_matching_article = False
                for article in reversed(articles):
                    if not check_driver_window(driver, "記事ループでのURL取得試行中"):
                        return None
                    article_text_raw = article.text
                    preview_comp = strip_invisible(
                        remove_emojis(
                            unicodedata.normalize(
                                "NFKC", remove_non_bmp(article_text_raw)
                            )
                        )
                    ).replace(" ", "")
                    user_name_in_article_xpath = f".//div[@data-testid='User-Name']//span[contains(text(), '@{TWITTER_USERNAME}')]"

                    if normalized_reply_content_for_comp in preview_comp:
                        try:
                            article.find_element(By.XPATH, user_name_in_article_xpath)
                            log(
                                f"✅ 内容が一致する可能性のある記事を発見。記事テキスト抜粋: {article_text_raw.strip().replace(chr(10), '↵')[:70]}..."
                            )
                            url_element = None
                            try:
                                url_element = article.find_element(
                                    By.XPATH,
                                    './/a[contains(@href, "/status/") and .//time]',
                                )
                            except NoSuchElementException:
                                log(
                                    "  ⓘ time要素を持つstatusリンクは見つかりませんでした。"
                                )
                            if not url_element:
                                try:
                                    url_element = article.find_element(
                                        By.XPATH, './/a[contains(@href, "/status/")]'
                                    )
                                except NoSuchElementException:
                                    log(
                                        "  ⚠️ 一般的なstatusリンクも見つかりませんでした。この記事からはURLを取得できません。"
                                    )
                                    continue
                            potential_url = url_element.get_attribute("href")
                            if (
                                TWITTER_USERNAME in potential_url
                                and "/status/" in potential_url
                            ):
                                new_reply_url = potential_url
                                log(f"🌐 URL取得成功 (内容一致): {new_reply_url}")
                                found_matching_article = True
                                break
                        except NoSuchElementException:
                            log(
                                f"  ⓘ 内容スニペットは一致したが、ユーザー名またはリンク特定できず。"
                            )
                            continue
                        except Exception as e_link_extract:
                            log(f"  ⚠️ 記事からのリンク抽出中にエラー: {e_link_extract}")
                            continue
                if not found_matching_article and articles:
                    log(
                        "⚠️ 内容一致でのURL特定に失敗。old_reply_to_tweet.py のように最新記事からの取得を試みます。"
                    )
                    last_article = articles[-1]
                    try:
                        preview_last = (
                            last_article.text.strip()
                            .replace("\n", " ")
                            .replace("  ", " ")
                        )
                        normalized_preview_last = remove_emojis(
                            unicodedata.normalize("NFKC", remove_non_bmp(preview_last))
                        )
                        chunk_comp_last = normalized_reply_content_for_comp[:15]
                        if chunk_comp_last in strip_invisible(
                            normalized_preview_last.replace(" ", "")
                        ):
                            log(
                                "✅ 最新記事の内容が投稿チャンクと部分一致（フォールバック）。"
                            )
                            url_element = None
                            try:
                                url_element = last_article.find_element(
                                    By.XPATH,
                                    './/a[contains(@href, "/status/") and .//time]',
                                )
                            except NoSuchElementException:
                                log(
                                    "  ⓘ (フォールバック) time要素を持つstatusリンクは見つかりませんでした。"
                                )
                            if not url_element:
                                try:
                                    url_element = last_article.find_element(
                                        By.XPATH, './/a[contains(@href, "/status/")]'
                                    )
                                except NoSuchElementException:
                                    log(
                                        "  ⚠️ (フォールバック) 一般的なstatusリンクも見つかりませんでした。"
                                    )
                            if url_element:
                                new_reply_url = url_element.get_attribute("href")
                                log(
                                    f"🌐 URL取得成功 (フォールバック - 最新記事): {new_reply_url}"
                                )
                        else:
                            log(
                                f"❌ 最新記事の内容も投稿チャンクと一致しませんでした。プレビュー: {preview_last[:50]}..., チャンク比較用: {chunk_comp_last}"
                            )
                    except Exception as e_fallback:
                        log(
                            f"⚠️ 最新記事からのURL取得(フォールバック)に失敗: {e_fallback}"
                        )
            else:
                log("⚠️ 現在のページにツイート記事が見つかりませんでした。URL取得不可。")
        except NoSuchWindowException as e_get_url_nw:
            log(
                f"⚠️ リプライURL取得中にウィンドウが閉じました: {type(e_get_url_nw).__name__} - {e_get_url_nw}"
            )
            return None
        except Exception as e_get_url:
            log(
                f"⚠️ 新しく投稿されたリプライのURL取得処理でエラー: {type(e_get_url).__name__} - {e_get_url}"
            )

        if not check_driver_window(driver, "リプライ処理完了前"):
            return None

        if new_reply_url:
            log(f"✅ リプライ送信処理完了。次のリプライ対象URL: {new_reply_url}")
            return new_reply_url
        else:
            log(
                f"❌ 新しいリプライURLが取得できませんでした。リプライ失敗とみなし None を返します。"
            )
            return None
    except NoSuchWindowException as e_main_nw:
        log(
            f"❌ リプライ処理の主要部分でウィンドウが閉じました: {type(e_main_nw).__name__} - {e_main_nw}"
        )
        return None
    except Exception as e:
        log(f"❌ リプライ処理中に予期せぬエラー: {type(e).__name__} - {e}")
        send_slack_notify(
            f"❌ リプライ処理中にエラーが発生しました: {tweet_url} - {type(e).__name__} - {e}"
        )
        return None


def post_to_twitter(driver, chunks, video_url):
    """
    一連のテキストチャンクと動画URLを受け取り、Twitterにスレッド形式で投稿する。
    最初のチャンクには動画を添付する。
    Args:
        driver (selenium.webdriver.chrome.webdriver.WebDriver): WebDriverインスタンス。
        chunks (list): 投稿するテキストチャンクのリスト。
        video_url (str): 添付する動画のURL。
    Returns:
        bool: 全ての投稿が成功した場合はTrue、途中で失敗した場合はFalse。
    """
    media_path = download_video(video_url)
    if not media_path:
        log("❌ 動画のダウンロードに失敗したため投稿中止")
        return False

    single_post_mode = len(chunks) == 1
    tweet_outcome = post_tweet(
        driver, chunks[0], media_path, single_post_mode=single_post_mode
    )

    if single_post_mode:
        if tweet_outcome == "SUCCESS_SINGLE_POST":
            log("✅ 本投稿(単一モード)成功")
            return True
        else:
            log(f"❌ 本投稿(単一モード)に失敗。post_tweet結果: {tweet_outcome}")
            return False
    else:  # スレッド投稿の場合
        if not tweet_outcome or "/status/" not in tweet_outcome:
            log(
                f"❌ 本投稿(多段の初回)に失敗またはURL取得失敗 (結果: {tweet_outcome}) → リプライ投稿を中止"
            )
            return False

        current_url = tweet_outcome
        log(f"✅ 本投稿(多段の初回)成功。最初の投稿URL: {current_url}")

        # chunks[0] は最初の投稿で使ったので、リプライは chunks[1:] から
        reply_chunks = chunks[1:]
        num_reply_chunks = len(reply_chunks)

        for i, chunk_content in enumerate(reply_chunks):
            reply_number = i + 2  # 2段目から始まる
            is_this_the_last_reply_in_thread = i == num_reply_chunks - 1

            if is_effectively_empty(chunk_content):
                log(f"⚠️ {reply_number}段目の内容が実質空のためスキップ")
                continue

            log(f"📎 {reply_number}段目リプライ投稿中（対象: {current_url})...")
            reply_result = reply_to_tweet(
                driver,
                current_url,
                chunk_content,
                is_last_reply=is_this_the_last_reply_in_thread,
            )

            if not reply_result:
                log(
                    f"❌ {reply_number}段目のリプライ投稿またはそのURL取得に失敗 → スレッド投稿を中断します"
                )
                send_slack_notify(
                    f"❌ {reply_number}段目のリプライ投稿/URL取得失敗: {TWITTER_USERNAME} - 対象URL: {current_url}"
                )
                return False

            if reply_result == "SUCCESS_LAST_REPLY":
                log(f"✅ {reply_number}段目(最終リプライ)成功。")
                break  # これが最後のチャンクだったので、スレッド投稿完了
            elif "/status/" in reply_result:
                current_url = reply_result
                log(
                    f"✅ {reply_number}段目リプライ成功。次のリプライは {current_url} に対して行われます。"
                )
                time.sleep(random.uniform(1.0, 2.0))  # 次のリプライまでの待機
            else:  # 予期しない戻り値
                log(
                    f"❌ {reply_number}段目のリプライで予期しない結果 ({reply_result}) → スレッド投稿を中断します"
                )
                return False

    log("✅ 全てのスレッド投稿が完了しました。")
    return True


def mark_as_posted(page_id):
    """
    指定されたNotionページのステータスを「使用済み」に更新する。
    Args:
        page_id (str): 更新するNotionページのID。
    """
    try:
        notion.pages.update(
            page_id=page_id, properties={"ステータス": {"select": {"name": "使用済み"}}}
        )
        log(f"✅ 投稿完了 → Notion ステータス更新（{page_id}）")
    except Exception as e:
        log(f"❌ Notion ステータス更新失敗: {e}")
        send_slack_notify(f"❌ Notion ステータス更新失敗: {e}")


def load_style_prompt(account="default", path="style_prompts.json"):
    """
    指定されたアカウントまたはデフォルトのスタイルプロンプトをJSONファイルから読み込む。
    Args:
        account (str, optional): アカウント名。デフォルトは "default"。
        path (str, optional): スタイルプロンプトファイルのパス。デフォルトは "style_prompts.json"。
    Returns:
        str: スタイルプロンプト。
    Raises:
        FileNotFoundError: スタイルプロンプトファイルが見つからない場合。
        KeyError: 指定アカウントもdefaultもスタイル定義が存在しない場合。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Style prompt ファイルが見つかりません: {path}")

    with open(path, "r", encoding="utf-8") as f:
        styles = json.load(f)

    if account in styles:
        return styles[account]
    elif "default" in styles:
        log(
            f"⚠️ アカウント '{account}' 用のスタイルが見つかりません。defaultを使用します。"
        )
        return styles["default"]
    else:
        raise KeyError(
            f"スタイル定義が存在しません（アカウント: {account}, defaultもなし）"
        )


# --- メイン処理 ---
# CLI引数パーサーの設定
parser = argparse.ArgumentParser(description="Twitter自動投稿スクリプト")
parser.add_argument(
    "--account", default="default", help="使用するアカウント名 (accounts.jsonで定義)"
)
parser.add_argument(
    "--mode",
    choices=["question", "joboffer"],
    default="question",
    help="投稿モード（'question' または 'joboffer'）。Notionデータベースの選択に使用。",
)

if "pytest" not in sys.modules:
    args = parser.parse_args()
else:
    # pytest実行時はデフォルト値で動作させる
    args = argparse.Namespace(account="default", mode="question")

load_dotenv()  # .envファイルから環境変数を読み込む

if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("❌ OPENAI_API_KEY が .env に定義されていません")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))  # OpenAIクライアント初期化

config = load_config(args.account)  # アカウント設定読み込み

# グローバル変数として設定値を展開
TWITTER_EMAIL = config["email"]
TWITTER_USERNAME = config["username"]
TWITTER_PASSWORD = config["password"]
NOTION_TOKEN = config["notion_token"]
DATABASE_ID = config["database_ids"][args.mode]  # モードに応じたDB IDを使用
SLACK_WEBHOOK_URL = config["slack_webhook_url"]

if __name__ == "__main__":
    if "pytest" in sys.modules:
        log("⚠️ pytest 実行中のため、メインスクリプトをスキップします")
    else:
        page_id_for_finally = None  # finallyブロックで使うためのpage_id
        driver_instance = None  # finallyブロックで使うためのdriver
        try:
            notion = Client(auth=NOTION_TOKEN)  # Notionクライアント初期化
            driver_instance = get_driver()  # WebDriver取得

            login(driver_instance)  # Twitterログイン

            content, page_id_for_finally, video_url = get_valid_page()  # 投稿対象取得
            if not content or not video_url:
                log("❌ 投稿対象がありません → 処理終了")
                # exit() # スクリプト終了
            else:
                log("📄 元の投稿内容:")
                log(content)

                # スタイルプロンプトの読み込み (GPT書き換え用だが現在はコメントアウトされている)
                # account_name = args.account
                # if args.mode == "joboffer":
                #     style_prompt = load_style_prompt(
                #         account_name, path="style_prompts_joboffers.json"
                #     )
                # else:
                #     style_prompt = load_style_prompt(
                #         account_name, path="style_prompts_questions.json"
                #     )
                # content_modified = rewrite_with_gpt(content, style_prompt) # GPT書き換え処理 (現在未使用)
                # log("📝 GPTによる書き換え後の投稿内容:")
                # log(content_modified)
                # chunks = split_text(content_modified) # 書き換え後の内容を分割

                chunks = split_text(content)  # 現在は元の内容を分割

                # Twitterへ投稿実行
                success = post_to_twitter(driver_instance, chunks, video_url)
                if success:
                    send_slack_notify(
                        f"✅ 投稿成功: {TWITTER_USERNAME} のツイートが完了しました"
                    )
                else:
                    send_slack_notify(
                        f"❌ 投稿失敗: {TWITTER_USERNAME} のツイートに失敗しました"
                    )

        except Exception as e:
            log(f"❌ 全体で例外発生: {e}")
            send_slack_notify(f"❌ 致命的なエラーが発生: {e}")
        finally:
            # 処理の最後に必ず実行されるブロック
            if page_id_for_finally:  # page_idが取得されていればNotionステータス更新
                mark_as_posted(page_id_for_finally)
            if driver_instance:  # driverが初期化されていれば閉じる
                driver_instance.quit()
            log("🏁 スクリプト処理終了")
