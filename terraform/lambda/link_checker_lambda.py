# -*- coding: utf-8 -*-
# 必要なライブラリをインポート
import os
import json
import urllib.parse
import logging
import time
import re
import boto3
import requests
import csv
import io
from bs4 import BeautifulSoup
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- グローバル設定 ---

# ロガーをセットアップ。ログレベルは環境変数 'LOG_LEVEL' から取得し、なければ 'INFO' を使用。
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# AWS S3 サービスクライアントを初期化
s3_client = boto3.client('s3')

# --- 定数定義 (マジックナンバーの排除) ---
# Meta refreshによるリダイレクトを追跡する最大回数
MAX_META_REFRESH_REDIRECTS = 5
# HTTPリクエストでリトライを行う対象のステータスコード
HTTP_RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
# ライブドアブログで記事ごとにチェックする際の待機秒数
PER_ARTICLE_WAIT_SECONDS = 1
# リンクチェック成功とみなすHTTPステータスコードの下限 (200 OKなど)
SUCCESS_STATUS_LOWER_BOUND = 200
# リンクチェック成功とみなすHTTPステータスコードの上限 (3xx リダイレクトを含む)
SUCCESS_STATUS_UPPER_BOUND = 400


# --- 環境変数からの設定読み込み ---
try:
    # 実行に必要な設定値を環境変数から取得します。
    S3_OUTPUT_BUCKET = os.environ['S3_OUTPUT_BUCKET']  # 結果を出力するS3バケット名
    REQUEST_TIMEOUT = int(os.environ['REQUEST_TIMEOUT'])  # HTTPリクエストのタイムアウト秒数
    MAX_RETRIES = int(os.environ['MAX_RETRIES'])  # HTTPリクエストの最大リトライ回数
    BACKOFF_FACTOR = float(os.environ['BACKOFF_FACTOR'])  # リトライ時の待機時間（指数関数的に増加）
    MAX_WORKERS = int(os.environ['MAX_WORKERS'])  # 並行処理を行う際のスレッド数
    CRAWL_WAIT_SECONDS = int(os.environ['CRAWL_WAIT_SECONDS'])  # ページ遷移時の待機秒数

    # S3_OUTPUT_BUCKETが空文字列でないことも確認します。
    if not S3_OUTPUT_BUCKET:
        # 空文字列の場合は設定不備とみなし、エラーを発生させます。
        raise ValueError("S3_OUTPUT_BUCKET is set but empty.")

# KeyError: 変数が存在しない場合, ValueError/TypeError: 型変換に失敗した場合
except (KeyError, ValueError, TypeError) as e:
    # 必須の環境変数が設定されていない、または値が不正な場合にエラーを記録して処理を中断します。
    logger.error(f"必須の環境変数が設定されていないか、値が不正です。エラー: {e}")
    # raise を実行することでLambda関数をエラーとして終了させます。
    raise

# --- 補助関数 ---

def requests_retry_session(retries=MAX_RETRIES, backoff_factor=BACKOFF_FACTOR, status_forcelist=HTTP_RETRY_STATUS_CODES, session=None):
    """
    リトライ機能付きのrequestsセッションを生成する関数。
    指定されたステータスコードを受け取った場合に、自動でリクエストを再試行する。
    """
    session = session or requests.Session()
    # リトライ戦略を設定
    retry = Retry(
        total=retries,  # 合計リトライ回数
        read=retries,   # Readエラーでのリトライ回数
        connect=retries, # Connectionエラーでのリトライ回数
        backoff_factor=backoff_factor, # リトライ間隔の計算係数
        status_forcelist=status_forcelist, # リトライ対象のHTTPステータスコード
        respect_retry_after_header=True # Retry-Afterヘッダーを尊重する
    )
    # セッションにリトライ設定を適用
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def get_html_content(url):
    """
    指定されたURLからHTMLコンテンツを取得する。
    リトライ機能付きセッションを使用し、取得に失敗した場合はNoneを返す。
    """
    try:
        session = requests_retry_session()
        # ブラウザからのアクセスを装うためのUser-Agentを設定
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = session.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
        response.raise_for_status()  # 200番台以外のステータスコードの場合に例外を発生させる
        response.encoding = response.apparent_encoding  # 文字化け防止のためエンコーディングを自動判別
        return response.text
    except requests.exceptions.RequestException as e:
        logger.error(f"URL取得エラー {url}: {e}")
        return None

def extract_ad_links(html_content, base_url):
    """
    HTMLコンテンツから「※一部、広告・宣伝が含まれます。」という文言の直後にあるリンクを抽出する。
    """
    if not html_content:
        return None
    soup = BeautifulSoup(html_content, 'html.parser')
    body = soup.body
    if not body:
        return None
    # 広告注釈のテキストを含む要素をすべて検索
    ad_notice_texts = body.find_all(string=re.compile(r"※一部、広告・宣伝が含まれます。"))
    if not ad_notice_texts:
        # 注釈が見つからなければNoneを返す
        return None
    
    links = set() # 重複を避けるためにセットを使用
    # 見つかった各注釈に対して処理を実行
    for notice_text in ad_notice_texts:
        # 注釈の次以降の要素を走査
        for next_element in notice_text.find_all_next():
            # aタグでhref属性を持つ最初の要素を見つける
            if next_element.name == 'a' and next_element.has_attr('href'):
                href = next_element['href']
                # javascript:で始まるURLは除外
                if href and not href.lower().startswith('javascript:'):
                    # 相対URLを絶対URLに変換
                    full_url = urllib.parse.urljoin(base_url, href)
                    # ページ内リンク（#）を除外
                    if full_url.split('#')[0] != base_url.split('#')[0]:
                        links.add(full_url)
                    break # 1つの注釈につき1つのリンクを抽出したらループを抜ける
    
    # URLのフラグメント（#以降）を除いたリンクのリストを返す
    return [link for link in links if not urllib.parse.urlparse(link).fragment]

def find_hatena_next_page_link(html_content, base_url):
    """はてなブログのページから「次のページ」へのリンクURLを抽出する。"""
    if not html_content: return None
    soup = BeautifulSoup(html_content, 'html.parser')
    # rel="next" 属性を持つaタグを探す
    next_link_tag = soup.find('a', rel='next', href=True)
    if next_link_tag:
        return urllib.parse.urljoin(base_url, next_link_tag['href'])
    return None

def extract_livedoor_article_links(html_content, base_url):
    """ライブドアブログの記事一覧ページから、各記事へのリンクURLを抽出する。"""
    links = set()
    if not html_content: return list(links)
    soup = BeautifulSoup(html_content, 'html.parser')
    # 記事要素を特定
    for article in soup.find_all('article', class_=re.compile(r'article')):
        # 記事タイトル内のリンクを探す
        title_link = article.select_one('h1.article-title a, h2.article-title a, a.article-title-link')
        if title_link and title_link.has_attr('href'):
            href = title_link['href']
            # 無効なリンクを除外
            if href and not href.startswith('#') and not href.lower().startswith('javascript:'):
                full_url = urllib.parse.urljoin(base_url, href)
                links.add(full_url.split('#')[0]) # URLのフラグメントを除いて追加
    return list(links)

def find_livedoor_next_page_link(html_content, base_url):
    """ライブドアブログのページから「次のページ」へのリンクURLを抽出する。"""
    if not html_content: return None
    soup = BeautifulSoup(html_content, 'html.parser')
    # 「次へ」や「»」などのテキストやクラス名を持つリンクを探す
    next_link_tag = soup.select_one('a.next, a.pager-next, a:-soup-contains("»"), a:-soup-contains("次へ")')
    if next_link_tag and next_link_tag.has_attr('href'):
        return urllib.parse.urljoin(base_url, next_link_tag['href'])
    return None

def check_link_status(url, ng_words=None):
    """
    指定されたURLのリンク状態を確認する。
    リダイレクトを追跡し、最終的なURLとステータスコードを返す。
    ページ内にNGワードが含まれているかもチェックする。
    """
    session = requests_retry_session()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8', 'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8'}
    current_url = url
    
    # Meta refreshによるリダイレクトを最大回数まで追跡
    for _ in range(MAX_META_REFRESH_REDIRECTS):
        try:
            response = session.get(current_url, timeout=REQUEST_TIMEOUT, headers=headers, allow_redirects=True)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            page_content = response.text
            soup = BeautifulSoup(page_content, 'html.parser')
            
            # Meta refreshタグを探す
            refresh_tag = soup.find('meta', attrs={'http-equiv': re.compile(r'refresh', re.I)})
            if refresh_tag and refresh_tag.get('content'):
                content_attr = refresh_tag['content'].lower()
                match = re.search(r'url=(.+)', content_attr)
                if match:
                    # リダイレクト先のURLを取得して次のループへ
                    next_url = match.group(1).strip().strip("'\"")
                    current_url = urllib.parse.urljoin(response.url, next_url)
                    continue
            
            # NGワードのチェック
            if ng_words:
                for word in ng_words:
                    if word in page_content:
                        return {"status_code": response.status_code, "final_url": response.url, "error_message": f"ページ内にNGワードが含まれています: '{word}'"}
            
            # 正常終了
            return {"status_code": response.status_code, "final_url": response.url, "error_message": None}
        
        except requests.exceptions.HTTPError as e:
            # HTTPエラー（4xx, 5xx系）
            return {"status_code": e.response.status_code if e.response else None, "final_url": e.response.url if e.response else current_url, "error_message": str(e)}
        except requests.exceptions.RequestException as e:
            # タイムアウトやDNSエラーなど
            return {"status_code": None, "final_url": current_url, "error_message": str(e)}
            
    # Meta refreshのリダイレクト回数上限を超えた場合
    return {"status_code": None, "final_url": current_url, "error_message": "Meta refresh redirect limit exceeded"}


# --- メイン処理 (Lambdaハンドラ) ---

def lambda_handler(event, context):
    """
    Lambda関数のエントリーポイント。
    S3イベントをトリガーに、指定されたブログのリンクチェックを実行する。
    """
    try:
        logger.info(f"イベント受信: {json.dumps(event)}")

        # 環境変数からNGワードリストを取得 (これはオプションなので .get() のまま)
        ng_words_str = os.environ.get('NG_WORDS', '')
        ng_words = [word.strip() for word in ng_words_str.split(',') if word.strip()]
        
        # --- 入力データの準備 ---
        # S3イベントからファイル情報を取得
        if 'Records' not in event or not event['Records']:
            return {'statusCode': 400, 'body': json.dumps({'message': 'S3レコードがイベントに見つかりません。'}, ensure_ascii=False)}
        s3_record = event['Records'][0]['s3']
        input_bucket_name = s3_record['bucket']['name']
        input_object_key = urllib.parse.unquote_plus(s3_record['object']['key'], encoding='utf-8')
        
        # S3から設定ファイル（JSON）を読み込み
        response = s3_client.get_object(Bucket=input_bucket_name, Key=input_object_key)
        input_data = json.loads(response['Body'].read().decode('utf-8'))
        
        # チェック対象のURLリストを取得
        target_urls = input_data.get('latest_target_url_list', [])
        
        # --- リンクチェックの実行 ---
        all_detailed_results = [] # 全てのチェック結果を格納するリスト
        current_errors = [] # 現在のエラーを格納するリスト
        
        # 各対象URLに対してループ処理
        for target_item in target_urls:
            blog_url = target_item.get('url')
            if not blog_url: continue # URLがなければスキップ
            
            # ブログの種類を判定
            is_hatena = "hatenablog.com" in blog_url or "hatenablog.jp" in blog_url
            is_livedoor = "livedoor.blog" in blog_url or "blog.jp" in blog_url

            # --- はてなブログの処理 ---
            if is_hatena:
                current_page_url = blog_url
                # 「次のページ」がなくなるまでページを巡回
                while current_page_url:
                    html_content = get_html_content(current_page_url)
                    if not html_content: break # ページ取得失敗
                    
                    extracted_links = extract_ad_links(html_content, current_page_url)
                    
                    if extracted_links is not None:
                        if not extracted_links:
                            error_reason = "対象の広告リンクが見つかりませんでした"
                            current_errors.append({"blog_url": blog_url, "page_url": current_page_url, "checked_link": current_page_url, "error_reason": error_reason})
                            all_detailed_results.append({"blog_url": blog_url, "page_url": current_page_url, "checked_link": current_page_url, "status": "ERROR", "status_code": None, "final_url": current_page_url, "error_message": error_reason, "timestamp": datetime.now().isoformat()})
                        
                        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                            future_to_link = {executor.submit(check_link_status, link, ng_words): link for link in extracted_links}
                            for future in as_completed(future_to_link):
                                link = future_to_link[future]
                                try:
                                    check_result = future.result()
                                    status = "OK"
                                    error_reason = None
                                    
                                    # エラー判定ロジック
                                    is_successful_status = check_result["status_code"] and SUCCESS_STATUS_LOWER_BOUND <= check_result["status_code"] < SUCCESS_STATUS_UPPER_BOUND
                                    if not is_successful_status or check_result["error_message"]:
                                        status = "ERROR"
                                        error_reason = check_result["error_message"] or f"ステータスコード: {check_result['status_code']}"
                                    
                                    # 特定のドメインやURLパターンをエラーとする追加のチェック
                                    if status == "OK":
                                        final_url = check_result["final_url"]
                                        parsed_final_url = urllib.parse.urlparse(final_url)
                                        parsed_blog_url = urllib.parse.urlparse(blog_url)
                                        if parsed_final_url.netloc == "jass-net.com":
                                            status = "ERROR"
                                            error_reason = "リンク先のドメインが 'jass-net.com' です"
                                        elif "hatena" in final_url and parsed_final_url.netloc != parsed_blog_url.netloc:
                                            status = "ERROR"
                                            error_reason = "リンク先のURLに 'hatena' が含まれています"
                                    
                                    detailed_result = {"blog_url": blog_url, "page_url": current_page_url, "checked_link": link, "status": status, "status_code": check_result["status_code"], "final_url": check_result["final_url"], "error_message": error_reason, "timestamp": datetime.now().isoformat()}
                                    all_detailed_results.append(detailed_result)
                                    if status == "ERROR":
                                        current_errors.append({"blog_url": blog_url, "page_url": current_page_url, "checked_link": link, "error_reason": error_reason})
                                
                                except Exception as exc:
                                    logger.error(f"リンクチェック中に例外が発生しました {link}: {exc}")
                                    all_detailed_results.append({"blog_url": blog_url, "page_url": current_page_url, "checked_link": link, "status": "ERROR", "status_code": None, "error_message": str(exc), "timestamp": datetime.now().isoformat()})
                                    current_errors.append({"blog_url": blog_url, "page_url": current_page_url, "checked_link": link, "error_reason": str(exc)})
                    
                    current_page_url = find_hatena_next_page_link(html_content, current_page_url)
                    if current_page_url: time.sleep(CRAWL_WAIT_SECONDS)

            # --- ライブドアブログの処理 ---
            elif is_livedoor:
                all_article_urls = set()
                current_list_page_url = blog_url
                while current_list_page_url:
                    list_page_html = get_html_content(current_list_page_url)
                    if not list_page_html: break
                    article_links_on_page = extract_livedoor_article_links(list_page_html, current_list_page_url)
                    all_article_urls.update(article_links_on_page)
                    current_list_page_url = find_livedoor_next_page_link(list_page_html, current_list_page_url)
                    if current_list_page_url: time.sleep(CRAWL_WAIT_SECONDS)
                
                for article_url in all_article_urls:
                    time.sleep(PER_ARTICLE_WAIT_SECONDS)
                    article_html = get_html_content(article_url)
                    if not article_html: continue
                    
                    extracted_links = extract_ad_links(article_html, article_url)
                    
                    if extracted_links is not None:
                        if not extracted_links:
                            error_reason = "対象の広告リンクが見つかりませんでした"
                            current_errors.append({"blog_url": blog_url, "page_url": article_url, "checked_link": article_url, "error_reason": error_reason})
                            all_detailed_results.append({"blog_url": blog_url, "page_url": article_url, "checked_link": article_url, "status": "ERROR", "status_code": None, "final_url": article_url, "error_message": error_reason, "timestamp": datetime.now().isoformat()})
                        
                        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                            future_to_link = {executor.submit(check_link_status, link, ng_words): link for link in extracted_links}
                            for future in as_completed(future_to_link):
                                link = future_to_link[future]
                                try:
                                    check_result = future.result()
                                    status = "OK"
                                    error_reason = None
                                    is_successful_status = check_result["status_code"] and SUCCESS_STATUS_LOWER_BOUND <= check_result["status_code"] < SUCCESS_STATUS_UPPER_BOUND
                                    if not is_successful_status or check_result["error_message"]:
                                        status = "ERROR"
                                        error_reason = check_result["error_message"] or f"ステータスコード: {check_result['status_code']}"
                                    if status == "OK":
                                        final_url = check_result["final_url"]
                                        parsed_final_url = urllib.parse.urlparse(final_url)
                                        parsed_blog_url = urllib.parse.urlparse(blog_url)
                                        if parsed_final_url.netloc == "jass-net.com":
                                            status = "ERROR"
                                            error_reason = "リンク先のドメインが 'jass-net.com' です"
                                        elif "hatena" in final_url and parsed_final_url.netloc != parsed_blog_url.netloc:
                                            status = "ERROR"
                                            error_reason = "リンク先のURLに 'hatena' が含まれています"
                                    detailed_result = {"blog_url": blog_url, "page_url": article_url, "checked_link": link, "status": status, "status_code": check_result["status_code"], "final_url": check_result["final_url"], "error_message": error_reason, "timestamp": datetime.now().isoformat()}
                                    all_detailed_results.append(detailed_result)
                                    if status == "ERROR":
                                        current_errors.append({"blog_url": blog_url, "page_url": article_url, "checked_link": link, "error_reason": error_reason})
                                except Exception as exc:
                                    logger.error(f"リンクチェック中に例外が発生しました {link}: {exc}")
                                    all_detailed_results.append({"blog_url": blog_url, "page_url": article_url, "checked_link": link, "status": "ERROR", "status_code": None, "error_message": str(exc), "timestamp": datetime.now().isoformat()})
                                    current_errors.append({"blog_url": blog_url, "page_url": article_url, "checked_link": link, "error_reason": str(exc)})
            else:
                logger.warning(f"サポート外のブログタイプです: {blog_url}")

        # --- 結果の出力 ---
        logger.info(f"詳細結果の合計: {len(all_detailed_results)}")
        logger.info(f"現在のエラー合計: {len(current_errors)}")

        if S3_OUTPUT_BUCKET:
            detailed_key = f"results/linkcheck_result.csv"
            
            if all_detailed_results:
                output = io.StringIO()
                headers = all_detailed_results[0].keys()
                writer = csv.DictWriter(output, fieldnames=headers)
                
                writer.writeheader()
                writer.writerows(all_detailed_results)
                
                csv_body = output.getvalue()
            else:
                csv_body = ""

            s3_client.put_object(
                Bucket=S3_OUTPUT_BUCKET, 
                Key=detailed_key, 
                Body=csv_body.encode('utf-8'),
                ContentType='text/csv'
            )
            logger.info(f"詳細結果を s3://{S3_OUTPUT_BUCKET}/{detailed_key} にアップロードしました")
        else:
            logger.error("S3_OUTPUT_BUCKET 環境変数が設定されていません。結果をアップロードできません。")
        
        return {'statusCode': 200, 'body': json.dumps({'message': 'リンクチェック処理が正常に完了しました！'}, ensure_ascii=False)}

    except Exception as e:
        logger.error(f"リンクチェック処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
        return {'statusCode': 500, 'body': json.dumps({'message': f'リンクチェック処理中にエラーが発生しました: {str(e)}'}, ensure_ascii=False)}