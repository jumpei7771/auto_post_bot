import os
import random
import platform
import time
import re
import datetime
import requests
import pyperclip
import unicodedata
import mimetypes
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import tweepy
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
import logging
from dateutil import parser as date_parser
import pytz
from utils.slack_notify import notify_slack
import json

# config_loader のインポートパス修正
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.append(project_root)
from config import config_loader # config ディレクトリ内の config_loader を直接指定

from utils.logger import setup_logger # utils.logger は相対パスで解決される想定
from utils.webdriver_utils import get_driver, quit_driver # WebDriverユーティリティ
from utils.twitter_login_selenium import login_to_twitter_with_selenium

# グローバルロガー設定 (main関数外でも使えるように)
# main関数内で設定されている logger を参照するか、ここで新たに設定するか検討。
# ここでは、スクリプトのトップレベルで設定し、各関数で利用できるようにする。
logger = setup_logger(log_dir_name='logs/auto_post_logs', logger_name='AutoPostBot_Global')

# TODO: このスクリプトは現在SeleniumベースのスクレイピングでXへの投稿を行っていますが、
# 将来的には X API v2 (User Context, Tweepyライブラリ利用) を使った方式に移行する予定です。
# 移行により、安定性の向上とメンテナンス性の改善を目指します。

# config_loaderを使用して設定を読み込む (古い形式、get_bot_config を使うべき)
# config = config_loader.load_config() # これは古い呼び出し方
# ↓ get_bot_config を使うように変更
BOT_NAME = "auto_post_bot" # ボット名を定義
config = config_loader.get_bot_config(BOT_NAME)

# 設定ファイルが見つからない、または読み込みに失敗した場合のフォールバック
if not config:
    logger.critical("CRITICAL: 設定ファイルの読み込みに失敗しました。デフォルト値での動作もできません。処理を中断します。")
    # エラーハンドリング： configがNoneの場合、後続の処理でエラーになるため、ここで終了するか、
    # ダミーのconfigを設定するなどの対策が必要。ここでは終了する。
    sys.exit(1) # プログラムを終了


# twitter_account セクションから情報を取得 (get_bot_configが解決してくれる)
# TWITTER_EMAIL = config.get("twitter_account", {}).get("email") # config['twitter_account'] に解決済み
# TWITTER_PASSWORD = config.get("twitter_account", {}).get("password")
# TWITTER_USERNAME = config.get("twitter_account", {}).get("username")
# ↓
TWITTER_EMAIL = config.get("twitter_account", {}).get("email")
TWITTER_PASSWORD = config.get("twitter_account", {}).get("password")
TWITTER_USERNAME = config.get("twitter_account", {}).get("username")


# posting セクションから情報を取得
posting_config = config.get("posting_settings", {}) # "posting" -> "posting_settings" に変更
char_limit_config = posting_config.get("char_limit", {})
CHAR_LIMIT = random.randint(
    char_limit_config.get("min", 135),
    char_limit_config.get("max", 150)
)
VIDEO_FILE_NAME = posting_config.get("video_download_filename", "temp_video.mp4")
USER_AGENTS = config.get("user_agents", []) # get_bot_configが解決してくれる
USE_TWITTER_API = config.get("posting_settings", {}).get("use_twitter_api", False) # API利用フラグ
logger.info(f"DEBUG: USE_TWITTER_API flag is set to: {USE_TWITTER_API} (Type: {type(USE_TWITTER_API)})") # DEBUG LOG


def simple_log(message):
    """簡易的なログ出力関数。loggerインスタンスを使用するように変更。"""
    logger.info(message)

def split_text(text, limit=CHAR_LIMIT):
    simple_log(f"🔍 テキストを {limit} 文字ごとに分割中...")
    return [text[i:i + limit] for i in range(0, len(text), limit)]

def convert_drive_url(url):
    """ Google Driveの共有URLを直接ダウンロード可能なURLに変換する """
    if not url or "drive.google.com" not in url:
        return url # Google DriveのURLでなければそのまま返す
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if match:
        file_id = match.group(1)
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        logger.info(f"Google Drive URLを変換: {url} -> {download_url}")
        return download_url
    else:
        logger.warning(f"Google Drive URLの形式が不正か、ファイルIDが見つかりません: {url}")
        return url # 変換失敗時は元のURLを返す (エラー処理は呼び出し元で行う想定)



def post_tweet(driver, text, media_path=None):
    driver.get("https://twitter.com/compose/post")
    time.sleep(3)

    try:
        # テキスト入力
        textarea = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div[aria-label="ポスト本文"]'))
        )
        textarea.click()
        ActionChains(driver).send_keys(text).perform()
        time.sleep(1)

        # メディアアップロード（任意）
        if media_path:
            file_input = driver.find_element(By.XPATH, '//input[@type="file"]')
            file_input.send_keys(media_path)
            time.sleep(3)

        # 投稿ボタンを明示的に待ってクリック
        post_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//button[@data-testid="tweetButton"]'))
        )
        post_button.click()
        time.sleep(2)

        return True

    except Exception as e:
        simple_log(f"❌ 投稿処理中にエラーが発生しました: {e}")
        return False



def get_twitter_conn_v1(twitter_api_config_param):
    logger.debug(f"get_twitter_conn_v1 called with twitter_api_config_param: {twitter_api_config_param}") # ★追加
    # bot_config から twitter_account セクションを取得する代わりに、渡された twitter_api_config_param を直接使用
    api_key = twitter_api_config_param.get("consumer_key") # settings.json に追加想定 -> twitter_api セクションのキーに変更
    api_secret_key = twitter_api_config_param.get("consumer_secret") # settings.json に追加想定 -> twitter_api セクションのキーに変更
    access_token = twitter_api_config_param.get("access_token") # settings.json に追加想定 -> twitter_api セクションのキーに変更
    access_token_secret = twitter_api_config_param.get("access_token_secret") # settings.json に追加想定 -> twitter_api セクションのキーに変更

    # ★追加: 各キーの値もデバッグ表示
    logger.debug(f"API Key for v1 auth: '{api_key}'")
    logger.debug(f"API Secret Key for v1 auth: '{api_secret_key}'")
    logger.debug(f"Access Token for v1 auth: '{access_token}'")
    logger.debug(f"Access Token Secret for v1 auth: '{access_token_secret}'")

    if not all([api_key, api_secret_key, access_token, access_token_secret]):
        logger.error("Twitter API (v1.1) の認証情報が不足しています。config.ymlのtwitter_apiセクションを確認してください。")
        return None

    auth = tweepy.OAuth1UserHandler(api_key, api_secret_key, access_token, access_token_secret)
    api = tweepy.API(auth=auth)
    if api.verify_credentials():
        logger.info("Twitter API v1.1 クライアントの認証に成功しました。")
        return api
    else:
        logger.error("Twitter API v1.1 クライアントの認証に失敗しました。")
        return None

def get_twitter_conn_v2(twitter_api_config_param):
    # bot_config から twitter_account セクションを取得する代わりに、渡された twitter_api_config_param を直接使用
    # v2の場合、Clientのコンストラクタはbearer_token, consumer_key, consumer_secret, access_token, access_token_secretを直接取る
    # tweepy.Client は引数名を正確に指定する必要がある。
    try:
        client = tweepy.Client(
            bearer_token=twitter_api_config_param.get("bearer_token"),
            consumer_key=twitter_api_config_param.get("consumer_key"),
            consumer_secret=twitter_api_config_param.get("consumer_secret"),
            access_token=twitter_api_config_param.get("access_token"),
            access_token_secret=twitter_api_config_param.get("access_token_secret")
        )
        # クライアントが実際に認証できるか簡単なテスト（例: me() エンドポイントを叩くなど）はここでは行わない
        # tweepy.Client のインスタンス化が成功すればOKとする
        # 実際にAPIを叩くのは post_tweet_with_api メソッド内
        logger.info("Twitter API v2 クライアントの準備ができました。")
        return client
    except Exception as e:
        logger.error(f"Twitter API v2 クライアントの作成に失敗: {e}", exc_info=True)
        return None

def fetch_posts_from_google_sheets(bot_config_param, logger_param, global_config=None):
    from config import config_loader  # 関数の先頭でインポート
    
    gs_config = bot_config_param.get("google_sheets_source", {})
    if not gs_config.get("enabled", False):
        logger_param.info("Google Sheetsからの投稿取得は無効化されています。")
        return []

    # sheet_nameはglobal_configから取得
    if global_config is None:
        global_config = config_loader.get_bot_config("auto_post_bot")
    sheet_name = global_config.get("sheet_name")
    worksheet_name = gs_config.get("worksheet_name")
    
    common_config = config_loader.get_common_config()
    key_file_path = common_config.get("file_paths", {}).get("google_key_file")

    if not sheet_name or not worksheet_name:
        logger_param.error("Google Sheetsのシート名またはワークシート名が設定されていません。")
        return []
    
    if not key_file_path:
        logger_param.error("Googleサービスアカウントキーのファイルパスがcommon設定内で見つかりません。")
        return []
    
    try:
        logger_param.info(f"'{sheet_name}' - '{worksheet_name}' から投稿ストックを取得中 (キーファイル: {key_file_path})...")
        posts = config_loader.load_records_from_sheet(sheet_name, worksheet_name, key_file_path)
        logger_param.info(f"{len(posts)} 件の投稿ストックを取得しました。")
        if posts:
            logger_param.debug(f"取得データサンプル（最初の1件）: {posts[0]}")
        return posts
    except Exception as e:
        logger_param.error(f"Google Sheetsからのデータ取得中にエラー: {e}", exc_info=True)
        return []

class AutoPoster:
    def __init__(self, config_path='config.yml', logger_param=None, profile_name_suffix=None):
        from config import config_loader
        BOT_NAME = "auto_post_bot"
        self.config = config_loader.get_bot_config(BOT_NAME)
        if isinstance(logger_param, logging.Logger):
            self.logger = logger_param
        else:
            self.logger = setup_logger('AutoPostBot_Global', logger_param)
        self.driver = None
        self.is_logged_in = False
        # account_idをprofile名に使う
        if profile_name_suffix is None:
            profile_name_suffix = "default"
        self.chrome_profile_dir = os.path.join(
            os.path.dirname(__file__),
            '.cache',
            f'chrome_profile_{profile_name_suffix}'
        )
        os.makedirs(self.chrome_profile_dir, exist_ok=True)

    def _initialize_webdriver(self):
        """WebDriverの初期化（Chromeプロファイルを固定）"""
        if self.driver is None:
            options = webdriver.ChromeOptions()
            options.add_argument(f'user-data-dir={self.chrome_profile_dir}')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(10)

    def _check_login_status(self):
        """現在のセッションが有効かチェック"""
        try:
            self.logger.info("[アクセスログ] _check_login_status: https://twitter.com/home にアクセスします")
            self.driver.get("https://twitter.com/home")
            time.sleep(2)
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='tweetTextarea_0']"))
            )
            self.is_logged_in = True
            return True
        except:
            self.is_logged_in = False
            return False

    def _ensure_logged_in(self):
        """ログイン状態を確認し、必要に応じてログイン"""
        self._initialize_webdriver()
        self.logger.info("[アクセスログ] _ensure_logged_in: ログイン状態チェックを実施")
        
        # ログイン状態チェックを1回だけ実行
        if not self._check_login_status():
            self.logger.info("[アクセスログ] _ensure_logged_in: セッションが無効なのでlogin_to_twitter_with_seleniumを呼び出します")
            return login_to_twitter_with_selenium(
                self.driver,
                self.config['twitter_account']['username'],
                self.config['twitter_account']['password'],
                self.config['twitter_account'].get('email'),
                self.logger
            )
        return True

    def post_tweet_with_selenium(self, content, media_path=None):
        try:
            self._initialize_webdriver()
            # ログイン状態チェックは1回だけ実行
            if not self._ensure_logged_in():
                self.logger.error("ログインに失敗しました。")
                return False

            # ここで再度 /home にアクセスせず、直接「ポストする」ボタンを探す
            self.logger.info("Seleniumを使用してツイートを投稿します...")
            try:
                # サイドバーの「ポストする」ボタンを最優先で探してクリック
                try:
                    post_btn = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, 'a[data-testid="SideNav_NewTweet_Button"]'))
                    )
                    self.logger.debug("サイドバーのポストするボタンをクリックします...")
                    post_btn.click()
                    time.sleep(2)
                except Exception as e:
                    self.logger.error(f"サイドバーのポストするボタンがクリックできませんでした: {e}")
                    # 失敗時にHTMLも保存
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    html_path = os.path.join(os.path.dirname(__file__), "error_screenshots", f"post_btn_error_{timestamp}.html")
                    os.makedirs(os.path.dirname(html_path), exist_ok=True)
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(self.driver.page_source)
                    self.logger.info(f"エラー時のHTMLを保存しました: {html_path}")
                    # 既存のフォールバック（直接URLアクセスなど）に進む
                    self.logger.info("[アクセスログ] post_tweet_with_selenium: https://twitter.com/compose/post にアクセスします（フォールバック）")
                    self.driver.get("https://twitter.com/compose/post")
                    time.sleep(3)
                # 投稿画面の読み込みを待機（複数のセレクタを試行）
                textarea_selectors = [
                    'div[data-testid="tweetTextarea_0"]',
                    'div[data-testid="tweetTextarea_1"]',
                    'div[role="textbox"]',
                    'div[aria-label="ポスト本文"]',
                    'div[aria-label="Post text"]',
                    'div[data-testid="tweetTextInput"]'  # 新しいセレクタを追加
                ]
                textarea = None
                for selector in textarea_selectors:
                    try:
                        textarea = WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        if textarea:
                            self.logger.debug(f"テキストエリアを見つけました: {selector}")
                            break
                    except:
                        continue
                if not textarea:
                    raise Exception("テキストエリアが見つかりませんでした")
                self.logger.debug("投稿画面に移動しました")
            except Exception as e:
                self.logger.error(f"投稿画面への移動中にエラーが発生しました: {e}")
                # 直接投稿URLにアクセスを試みる
                try:
                    self.logger.info("[アクセスログ] post_tweet_with_selenium: https://twitter.com/compose/post にアクセスします（直接URLアクセス）")
                    self.driver.get("https://twitter.com/compose/post")
                    time.sleep(3)
                    textarea = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="tweetTextarea_0"]'))
                    )
                except Exception as e2:
                    self.logger.error(f"直接URLでのアクセスも失敗しました: {e2}")
                    # 失敗時にHTMLも保存
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    html_path = os.path.join(os.path.dirname(__file__), "error_screenshots", f"post_url_error_{timestamp}.html")
                    os.makedirs(os.path.dirname(html_path), exist_ok=True)
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(self.driver.page_source)
                    self.logger.info(f"エラー時のHTMLを保存しました: {html_path}")
                    return False
            try:
                self.logger.debug("テキストを入力します...")
                textarea.click()
                ActionChains(self.driver).send_keys_to_element(textarea, content).perform()
                time.sleep(2)  # テキスト入力後の待機を追加
                if media_path:
                    self.logger.info(f"メディアをアップロードします: {media_path}")
                    file_input = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, '//input[@data-testid="fileInput"]'))
                    )
                    abs_media_path = os.path.abspath(media_path)  # 絶対パスに変換
                    file_input.send_keys(abs_media_path)
                    WebDriverWait(self.driver, 30).until(
                        EC.presence_of_element_located((By.XPATH, '//div[@data-testid="attachments"]//img[@alt="画像プレビュー"]|//div[@data-testid="attachments"]//video'))
                    )
                    self.logger.info("メディアのアップロードが完了したようです。")
                    time.sleep(2)  # メディアアップロード後の待機を追加
                self.logger.debug("投稿ボタンを探しています...")
                # 投稿ボタンの活性化を待機
                post_button = None
                max_retries = 5
                retry_count = 0
                while retry_count < max_retries:
                    try:
                        post_button = WebDriverWait(self.driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, '//button[@data-testid="tweetButton"]'))
                        )
                        if post_button and post_button.is_enabled():
                            self.logger.debug("投稿ボタンが活性化しました")
                            break
                    except:
                        retry_count += 1
                        self.logger.debug(f"投稿ボタンの活性化待機中... ({retry_count}/{max_retries})")
                        time.sleep(2)
                        continue
                if not post_button or not post_button.is_enabled():
                    raise Exception("投稿ボタンが活性化しませんでした")
                self.logger.debug("投稿ボタンをクリックします...")
                # JSクリックのフォールバック
                self.driver.execute_script("arguments[0].click();", post_button)
                time.sleep(3)
                current_url = self.driver.current_url
                if "/home" in current_url or "twitter.com/home" in current_url:
                    self.logger.info("投稿後、/homeへの遷移を検知しました（JSクリック）。投稿成功とみなします。")
                    return True
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'ポストを送信しました') or contains(text(), '投稿しました') or contains(text(), 'ツイートを投稿しました') or contains(text(), 'Your post was sent') or contains(text(), 'Your Tweet was sent')]"))
                    )
                    self.logger.info("ツイート投稿が成功したポップアップを検知しました（JSクリック）。")
                    return True
                except Exception:
                    pass
                self.logger.error("投稿後、/home遷移もポップアップ検知もできませんでした（JSクリック）。投稿失敗とみなします。")
                return False
            except TimeoutException as te:
                self.logger.error(f"投稿処理中にタイムアウトが発生しました: {te}")
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = os.path.join(os.path.dirname(__file__), "error_screenshots", f"post_timeout_{timestamp}.png")
                os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"エラー時のスクリーンショットを保存しました: {screenshot_path}")
                return False
            except Exception as e:
                self.logger.error(f"投稿処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = os.path.join(os.path.dirname(__file__), "error_screenshots", f"post_error_{timestamp}.png")
                os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"エラー時のスクリーンショットを保存しました: {screenshot_path}")
                return False
        except Exception as e:
            self.logger.error(f"投稿処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
            return False

    def download_media(self, url, filename_base):
        self.logger.info(f"メディアをダウンロードします: {url}")
        mime_type = None
        actual_filename = filename_base
        try:
            response = requests.get(url, stream=True, timeout=20)
            response.raise_for_status()
            mime_type = response.headers.get('content-type')
            self.logger.info(f"検出されたMIMEタイプ: {mime_type}")

            # MIMEタイプが動画または画像か確認
            if not mime_type or not (mime_type.startswith('video/') or mime_type.startswith('image/')):
                self.logger.error(f"無効なメディアタイプが検出されました: {mime_type} (URL: {url})。動画または画像ではありません。ダウンロードを中止します。")
                return None, None # 無効なタイプなので失敗として扱う

            # MIMEタイプから拡張子を推測
            ext = mimetypes.guess_extension(mime_type) if mime_type else None
            if not ext:
                # フォールバック: URLから拡張子を試みる (限定的)
                self.logger.warning(f"MIMEタイプから拡張子を推測できませんでした ({mime_type})。URLから試みます。")
                original_filename_from_url, original_ext_from_url = os.path.splitext(url.split('/')[-1].split('?')[0])
                if original_ext_from_url:
                    ext = original_ext_from_url
                else: # それでもダメならデフォルトの拡張子（画像と仮定）
                    self.logger.warning("URLからも拡張子を特定できませんでした。デフォルトで .jpg を使用します。")
                    ext = '.jpg'
            
            actual_filename = f"{filename_base}{ext}"

            with open(actual_filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            self.logger.info(f"メディアのダウンロードが完了しました: {actual_filename}")
            return actual_filename, mime_type
        except requests.exceptions.RequestException as e:
            self.logger.error(f"メディアのダウンロードに失敗しました ({url}): {e}")
            return None, None
        except Exception as e:
            self.logger.error(f"メディアのダウンロード中に予期せぬエラー ({url}): {e}", exc_info=True)
            return None, None

    def cleanup(self):
        if self.driver:
            self.logger.info("WebDriverを終了します。")
            quit_driver(self.driver)
            self.driver = None

    def post_tweet_with_api(self, text, media_path=None):
        self.logger.info("APIを使用してツイートを投稿します...")
        if not self.api_v1 or not self.api_v2_client:
            self.logger.error("APIクライアントが初期化されていません。API投稿をスキップします。")
            return False

        media_id_str = None
        media_ids_list = []

        try:
            if media_path:
                self.logger.info(f"API経由でメディアをアップロードします: {media_path}")
                # media_upload はファイルタイプを自動判別してくれるはず
                # 動画の場合は media_category='tweet_video' が必要になる場合がある
                # シンプルな画像アップロードをまず試す
                try:
                    media = self.api_v1.media_upload(filename=media_path)
                    media_id_str = media.media_id_string
                    media_ids_list.append(media_id_str)
                    self.logger.info(f"メディアのアップロード成功。Media ID: {media_id_str}")
                except tweepy.TweepyException as e_media:
                    self.logger.error(f"APIでのメディアアップロード中にエラー: {e_media}", exc_info=True)
                    # メディアアップロード失敗時はテキストのみで投稿するか、全体を失敗とするか
                    # ここでは一旦、投稿全体を失敗とする
                    return False
            
            # ツイート投稿 (API v2)
            if media_ids_list:
                response = self.api_v2_client.create_tweet(text=text, media_ids=media_ids_list)
            else:
                response = self.api_v2_client.create_tweet(text=text)
            
            if response.data and response.data.get("id"):
                tweet_id = response.data.get("id")
                self.logger.info(f"API経由でのツイート投稿成功。Tweet ID: {tweet_id}")
                # tweepy.Response オブジェクトの構造を確認。 response.data['id'] が一般的
                # https://docs.tweepy.org/en/stable/v2_models.html#tweet
                return True
            else:
                self.logger.error(f"API経由でのツイート投稿に失敗しました。レスポンス: {response.errors if response.errors else response}")
                return False

        except tweepy.TweepyException as e_tweet:
            self.logger.error(f"APIでのツイート投稿処理中にエラー: {e_tweet}", exc_info=True)
            # エラーレスポンスの詳細を取得 (e_tweet.api_codes, e_tweet.api_errorsなど)
            if hasattr(e_tweet, 'response') and e_tweet.response is not None:
                 self.logger.error(f"APIエラーレスポンス Status: {e_tweet.response.status_code}, Content: {e_tweet.response.text}")
            return False
        except Exception as e:
            self.logger.error(f"API投稿中に予期せぬエラー: {e}", exc_info=True)
            return False

def post_single_tweet(bot_config_param, post_data, logger_param, global_config=None):
    """単一の投稿データに基づいてツイートを試みる。SeleniumまたはAPI v2を使用。"""
    from config import config_loader  # 関数の先頭でインポート
    
    logger_param.info(f"DEBUG: post_single_tweet called. Global USE_TWITTER_API is: {USE_TWITTER_API}")

    text_to_post = post_data.get("本文")
    media_url_original = post_data.get("画像/動画URL")
    post_id_for_log = post_data.get("ID", None)
    
    # 追加: アカウント名（username）を取得
    username = bot_config_param.get("username", "unknown")
    
    log_identifier = post_data.get("log_identifier", f"投稿 (本文抜粋: {text_to_post[:20]}...)")
    if post_id_for_log:
        log_identifier = f"投稿ID '{post_id_for_log}'"

    if not text_to_post:
        logger_param.warning(f"{log_identifier}: 本文が空のためスキップします。")
        return False

    logger_param.info(f"--- {log_identifier} の処理開始 ---")
    logger_param.info(f"本文: {text_to_post[:50]}...")
    logger_param.info(f"元メディアURL: {media_url_original or 'なし'}")

    # 行インデックス取得処理を追加
    gs_config = bot_config_param.get("google_sheets_source", {})
    if global_config is None:
        from config import config_loader
        global_config = config_loader.get_bot_config("auto_post_bot")
    sheet_name = global_config.get("sheet_name")
    worksheet_name = gs_config.get("worksheet_name")
    common_config = config_loader.get_common_config()
    key_file_path = common_config.get("file_paths", {}).get("google_key_file")
    column_settings = gs_config.get("columns", [])  # column_settingsを取得
    
    gspread_client = None
    gspread_sheet_obj = None
    row_index_to_update = None
    
    if key_file_path and sheet_name and worksheet_name:
        try:
            actual_key_file_path = os.path.join(config_loader.CONFIG_DIR, key_file_path) if not os.path.isabs(key_file_path) else key_file_path
            creds = ServiceAccountCredentials.from_json_keyfile_name(actual_key_file_path, config_loader.GOOGLE_API_SCOPE)
            gspread_client = gspread.authorize(creds)
            gspread_sheet_obj = gspread_client.open(sheet_name).worksheet(worksheet_name)
            
            # ヘッダー行を取得
            sheet_header = gspread_sheet_obj.row_values(1)
            logger_param.info(f"[DEBUG] スプレッドシート1行目: {sheet_header}")
            print(f"[print] スプレッドシート1行目: {sheet_header}")
            
            # ID列の名前を取得
            id_column_name = "ID"
            if post_id_for_log:
                row_index_to_update = config_loader.find_row_index_by_id(gspread_sheet_obj, id_column_name, str(post_id_for_log))
                logger_param.info(f"[DEBUG] row_index_to_update: {row_index_to_update}")
                print(f"[print] row_index_to_update: {row_index_to_update}")
        except Exception as e:
            logger_param.error(f"gspreadクライアントの初期化または行インデックス取得に失敗: {e}", exc_info=True)

    media_url_for_download = convert_drive_url(media_url_original) if media_url_original else None
    if media_url_original and not media_url_for_download:
        logger_param.warning(f"{log_identifier}: メディアURLの変換に失敗したか、Google Drive URLではありませんでした。元のURLで試行します: {media_url_original}")
        media_url_for_download = media_url_original
    elif media_url_for_download:
        logger_param.info(f"変換後メディアURL: {media_url_for_download}")

    success = False
    media_path_local = None
    account_id = bot_config_param.get("account_id", "default")
    poster = AutoPoster(config_path='config.yml', logger_param=logger_param, profile_name_suffix=account_id) 

    try:
        if media_url_for_download:
            temp_file_base = f"temp_media_{post_id_for_log or datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            media_path_local, downloaded_mime_type = poster.download_media(media_url_for_download, temp_file_base)
            if not media_path_local:
                logger_param.error(f"{log_identifier}: メディアのダウンロードに失敗しました。メディアなしで投稿を試みます。")
        if USE_TWITTER_API:
            if poster.api_v1 and poster.api_v2_client:
                success = poster.post_tweet_with_api(text_to_post, media_path_local) 
            else:
                logger_param.error(f"{log_identifier}: APIクライアントの初期化に失敗しているため、API投稿を実行できません。")
                success = False 
        else:
            if not poster._ensure_logged_in():
                logger_param.error(f"{log_identifier}: Seleniumでのログインに失敗しました。")
                success = False
            else:
                success = poster.post_tweet_with_selenium(text_to_post, media_path_local)
    except Exception as e:
        logger_param.error(f"{log_identifier}: 投稿処理中に予期せぬエラー: {e}", exc_info=True)
        success = False
    finally:
        if not USE_TWITTER_API:
            poster.cleanup()
        if media_path_local and os.path.exists(media_path_local):
            try:
                os.remove(media_path_local)
                logger_param.info(f"一時メディアファイルを削除しました: {media_path_local}")
            except OSError as e_remove:
                logger_param.warning(f"一時メディアファイルの削除に失敗: {e_remove}")

    slack_webhook_url = load_slack_webhook_url()
    if success:
        logger.info(f"✅ {log_identifier}: 投稿成功")
        if slack_webhook_url:
            notify_slack(f"✅ [{username}] {log_identifier}: 投稿成功", slack_webhook_url)
        # 最終投稿日時カラムを現在時刻で更新
        if row_index_to_update:
            try:
                now_str = datetime.datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M:%S')
                last_post_col = "最終投稿日時"  # 最終投稿日時カラム名を定義
                logger.info(f"[DEBUG] column_settings: {column_settings}")
                logger.info(f"[DEBUG] sheet_header: {sheet_header if gspread_sheet_obj else None}")
                print(f"[print] column_settings: {column_settings}")
                print(f"[print] sheet_header: {sheet_header if gspread_sheet_obj else None}")
                col_index = column_settings.index(last_post_col)+1
                logger.info(f"[DEBUG] 最終投稿日時カラムのindex: {col_index}")
                print(f"[print] 最終投稿日時カラムのindex: {col_index}")
                gspread_sheet_obj.update_cell(row_index_to_update, col_index, now_str)
                logger.info(f"[最終投稿日時] {row_index_to_update}行目を{now_str}で更新しました。")
            except Exception as e:
                logger.error(f"[最終投稿日時] 更新中にエラー: {e}")
                print(f"[print] [最終投稿日時] 更新中にエラー: {e}")
        # 投稿済み回数カラムの更新
        try:
            logger.info("[DEBUG] 投稿済み回数カラムの更新処理に入ります")
            print("[print] 投稿済み回数カラムの更新処理に入ります")
            post_count_col_name = "投稿済み回数"
            post_count_col_index = column_settings.index(post_count_col_name) + 1
            logger.info(f"[DEBUG] 投稿済み回数カラムのindex: {post_count_col_index}")
            print(f"[print] 投稿済み回数カラムのindex: {post_count_col_index}")
            current_val = gspread_sheet_obj.cell(row_index_to_update, post_count_col_index).value
            logger.info(f"[DEBUG] 現在の投稿済み回数の値: {current_val}")
            print(f"[print] 現在の投稿済み回数の値: {current_val}")
            try:
                current_count = int(current_val) if current_val else 0
                new_count = current_count + 1
                logger.info(f"[DEBUG] カウントを更新します。current_count: {current_count} -> new_count: {new_count}")
                print(f"[print] カウントを更新します。current_count: {current_count} -> new_count: {new_count}")
                gspread_sheet_obj.update_cell(row_index_to_update, post_count_col_index, str(new_count))
                logger.info(f"[投稿済み回数] カウントアップ完了。new_count: {new_count}")
                print(f"[print] [投稿済み回数] カウントアップ完了。new_count: {new_count}")
            except ValueError:
                logger.error(f"[投稿済み回数] 現在の値 '{current_val}' を数値に変換できません。")
                print(f"[print] [投稿済み回数] 現在の値 '{current_val}' を数値に変換できません。")
        except Exception as e:
            logger.error(f"[投稿済み回数] 更新処理のtryブロック外で例外: {e}")
            print(f"[print] [投稿済み回数] 更新処理のtryブロック外で例外: {e}")
            logger.error(f"[投稿済み回数] 更新中にエラー: {e}")
            print(f"[print] [投稿済み回数] 更新中にエラー: {e}")
    else:
        logger_param.error(f"❌ {log_identifier}: 投稿失敗")
        if slack_webhook_url:
            notify_slack(f"❌ [{username}] {log_identifier}: 投稿失敗", slack_webhook_url)
    return success

def parse_dt(dt_str):
    if not dt_str:
        return datetime.datetime(1970, 1, 1, tzinfo=pytz.UTC)
    try:
        dt = date_parser.parse(dt_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=pytz.UTC)
        return dt
    except Exception:
        return datetime.datetime(1970, 1, 1, tzinfo=pytz.UTC)

def load_slack_webhook_url():
    # config_loaderでconfig.ymlからslack_webhook_urlを取得
    from config import config_loader
    config = config_loader.get_bot_config("auto_post_bot")
    # トップレベルまたはslackセクションどちらでも対応
    if "slack_webhook_url" in config:
        return config["slack_webhook_url"]
    slack_config = config.get("slack", {})
    return slack_config.get("webhook_url")

def main():
    global logger
    logger.info("===== Auto Post Bot 開始 =====")

    if not config:
        logger.critical("設定が読み込まれていないため、処理を終了します。")
        return

    sheet_name = config.get("sheet_name")
    twitter_accounts = config.get("twitter_accounts", [])
    global_columns = config.get("columns")

    for account in twitter_accounts:
        # columns補完処理
        gs_config = account.get("google_sheets_source", {})
        if "columns" not in gs_config or not gs_config["columns"]:
            gs_config["columns"] = global_columns
        account["google_sheets_source"] = gs_config
        # デバッグログを追加
        logger.info(f"[DEBUG] アカウント設定全体: {account}")
        
        worksheet_name = gs_config.get("worksheet_name")
        key_file_path = config_loader.get_common_config().get("file_paths", {}).get("google_key_file")
        column_settings = gs_config.get("columns", [])

        # sheet_nameはグローバルから取得するため、アカウントごとの必須チェックから除外
        if not all([worksheet_name, key_file_path, column_settings]):
            logger.error(f"アカウント {account.get('username')} の設定が不足しています。スキップします。")
            logger.error(f"[DEBUG] アカウント設定内容: {account}")
            logger.error(f"[DEBUG] worksheet_name: {worksheet_name}")
            logger.error(f"[DEBUG] key_file_path: {key_file_path}")
            logger.error(f"[DEBUG] column_settings: {column_settings}")
            continue

        posts_to_process = fetch_posts_from_google_sheets(account, logger, global_config=config)
        logger.info(f"[{account.get('username')}] fetch_posts_from_google_sheetsで取得した件数: {len(posts_to_process)}")
        if not posts_to_process:
            logger.info(f"[{account.get('username')}] 投稿データが0件でした。スキップします。")
            continue

        last_post_col = "最終投稿日時"
        # 本文が空でない投稿のみ抽出
        posts_with_body = [p for p in posts_to_process if p.get("本文") and str(p.get("本文")).strip()]
        posts_sorted = sorted(posts_with_body, key=lambda x: parse_dt(x.get(last_post_col)))
        target_post = posts_sorted[0] if posts_sorted else None

        if not target_post:
            logger.info(f"[{account.get('username')}] 投稿対象がありません。スキップします。")
            continue

        success = post_single_tweet(account, target_post, logger, global_config=config)

    logger.info("===== Auto Post Bot 終了 =====")

if __name__ == "__main__":
    main()
