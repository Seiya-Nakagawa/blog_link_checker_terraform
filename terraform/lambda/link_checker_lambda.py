# -*- coding: utf-8 -*-
import os
import json
import urllib.parse
import logging
import time  # サーバー負荷軽減のためのtimeモジュールをインポート
import boto3
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

# ロギング設定
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# AWSサービスクライアントの初期化
s3_client = boto3.client('s3')
sns_client = boto3.client('sns')

# 環境変数から設定値を取得
S3_OUTPUT_BUCKET = os.environ.get('S3_OUTPUT_BUCKET')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')

# 環境変数を堅牢に型変換して取得
try:
    REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', 10))
    MAX_RETRIES = int(os.environ.get('MAX_RETRIES', 3))
    BACKOFF_FACTOR = float(os.environ.get('BACKOFF_FACTOR', 0.5))
    MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 10))
    CRAWL_WAIT_SECONDS = int(os.environ.get('CRAWL_WAIT_SECONDS', 2))
except (ValueError, TypeError) as e:
    logger.warning(f"環境変数の値が無効です。デフォルト値を使用します。エラー: {e}")
    REQUEST_TIMEOUT = 10
    MAX_RETRIES = 3
    BACKOFF_FACTOR = 0.5
    MAX_WORKERS = 10
    CRAWL_WAIT_SECONDS = 2

def requests_retry_session(retries=MAX_RETRIES, backoff_factor=BACKOFF_FACTOR, status_forcelist=(500, 502, 503, 504), session=None):
    """リトライ機能付きのrequestsセッションをセットアップする"""
    session = session or requests.Session()
    retry = Retry(
        total=retries, read=retries, connect=retries,
        backoff_factor=backoff_factor, status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def get_html_content(url):
    """指定されたURLからHTMLコンテンツを取得する"""
    try:
        session = requests_retry_session()
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = session.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        return response.text
    except requests.exceptions.RequestException as e:
        logger.error(f"URL取得エラー {url}: {e}")
        return None

# --- ここから元のロジックで必要だった関数を再定義 ---

def extract_hatena_ad_links(html_content, base_url):
    """はてなブログのHTMLから、指定された条件の広告リンクのみを抽出する"""
    links = set()
    if not html_content:
        return list(links)
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # ページ内の全ての「(※一部、広告・宣伝が含まれます。)」を探す
    for p_tag in soup.find_all('p'):
        if p_tag.get_text(strip=True) == "(※一部、広告・宣伝が含まれます。)":
            # その直後にあるpタグを探す
            next_p = p_tag.find_next_sibling('p')
            if next_p:
                a_tag = next_p.find('a', href=True)
                if a_tag:
                    href = a_tag['href']
                    full_url = urllib.parse.urljoin(base_url, href)
                    links.add(full_url)
    
    return list(links)

def find_next_page_link(html_content, base_url):
    """はてなブログのHTMLから「次のページ」のリンクURLを取得する"""
    if not html_content:
        return None
        
    soup = BeautifulSoup(html_content, 'html.parser')
    next_link_tag = soup.find('a', rel='next', href=True)
    
    if next_link_tag:
        next_page_url = urllib.parse.urljoin(base_url, next_link_tag['href'])
        logger.info(f"次のページのリンクが見つかりました: {next_page_url}")
        return next_page_url
    else:
        logger.info("次のページのリンクは見つかりませんでした。クロールを終了します。")
        return None
        
# --- ここまでが再定義した関数 ---

def extract_links(html_content, base_url):
    """HTMLコンテンツから全てのhrefリンクを抽出する（汎用・ライブドアブログ用）"""
    links = set()
    if not html_content:
        return list(links)
    soup = BeautifulSoup(html_content, 'html.parser')
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        if not href or href.startswith('#') or href.lower().startswith('javascript:'):
            continue
        full_url = urllib.parse.urljoin(base_url, href)
        links.add(full_url)
    return list(links)

def extract_article_links_for_livedoor(html_content, base_url):
    """ライブドアブログのトップページから記事ページへのリンクのみを抽出する"""
    article_links = set()
    if not html_content:
        return list(article_links)
    soup = BeautifulSoup(html_content, 'html.parser')
    for a_tag in soup.find_all('a', href=lambda href: href and 'archives/' in href):
        href = a_tag['href']
        full_url = urllib.parse.urljoin(base_url, href)
        article_links.add(full_url)
    return list(article_links)

def check_link_status(url):
    """単一のリンクのステータスを確認する"""
    try:
        session = requests_retry_session()
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = session.head(url, timeout=REQUEST_TIMEOUT, headers=headers, allow_redirects=True)

        status_code = response.status_code
        final_url = response.url
        error_message = None
        status = "OK"

        if not (200 <= status_code < 400):
            status = "ERROR"
            error_message = f"ステータスコード: {status_code}"
        else:
            # ステータスがOKの場合でも、特定の条件でエラーとする
            parsed_url = urllib.parse.urlparse(final_url)
            if parsed_url.netloc == "jass-net.com":
                status = "ERROR"
                error_message = "リンク先のドメインが 'jass-net.com' です"
            elif "hatena" in final_url:
                status = "ERROR"
                error_message = "リンク先のURLに 'hatena' が含まれています"

        # HTTPErrorを明示的に発生させる
        response.raise_for_status()

        return {"status": status, "status_code": status_code, "final_url": final_url, "error_message": error_message}
    except requests.exceptions.HTTPError as e:
        # ステータスコードが4xx, 5xxの場合
        error_msg = str(e) if "error_message" not in locals() else error_message
        return {"status": "ERROR", "status_code": e.response.status_code if e.response else None, "final_url": e.response.url if e.response else url, "error_message": error_msg}
    except requests.exceptions.RequestException as e:
        # タイムアウトや接続エラーなど
        return {"status": "ERROR", "status_code": None, "final_url": url, "error_message": str(e)}

def publish_sns_notification(subject, message):
    """SNSトピックにメッセージを公開する"""
    if not SNS_TOPIC_ARN:
        logger.warning("SNS_TOPIC_ARNが設定されていません。SNS通知をスキップします。")
        return
    try:
        sns_client.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=message)
        logger.info(f"SNS通知を送信しました: Subject='{subject}'")
    except Exception as e:
        logger.error(f"SNS通知の公開エラー: {e}")

def process_page_links(page_url, blog_url, all_detailed_results, current_errors):
    """指定された1ページの汎用的なリンクチェック処理を行う（汎用・ライブドアブログ用）"""
    logger.info(f"記事ページをチェック中: {page_url}")
    html_content = get_html_content(page_url)
    if not html_content:
        error_reason = "記事ページのコンテンツ取得に失敗しました"
        all_detailed_results.append({"blog_url": blog_url, "page_url": page_url, "checked_link": page_url, "status": "ERROR", "status_code": None, "final_url": page_url, "error_message": error_reason, "timestamp": datetime.now().isoformat()})
        current_errors.append({"blog_url": blog_url, "page_url": page_url, "checked_link": page_url, "error_reason": error_reason})
        return

    extracted_links = extract_links(html_content, page_url)
    logger.info(f"{page_url} から {len(extracted_links)} 個のリンクを抽出しました")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_link = {executor.submit(check_link_status, link): link for link in extracted_links}
        for future in as_completed(future_to_link):
            link = future_to_link[future]
            try:
                check_result = future.result()
                detailed_result = {"blog_url": blog_url, "page_url": page_url, "checked_link": link, "status": check_result["status"], "status_code": check_result["status_code"], "final_url": check_result["final_url"], "error_message": check_result["error_message"], "timestamp": datetime.now().isoformat()}
                all_detailed_results.append(detailed_result)
                if check_result["status"] == "ERROR":
                    current_errors.append({"blog_url": blog_url, "page_url": page_url, "checked_link": link, "error_reason": check_result["error_message"] or f"ステータスコード: {check_result['status_code']}"})
            except Exception as exc:
                logger.error(f"リンクチェック中に例外が発生しました {link}: {exc}")
                all_detailed_results.append({"blog_url": blog_url, "page_url": page_url, "checked_link": link, "status": "ERROR", "status_code": None, "final_url": link, "error_message": str(exc), "timestamp": datetime.now().isoformat()})
                current_errors.append({"blog_url": blog_url, "page_url": page_url, "checked_link": link, "error_reason": str(exc)})


def lambda_handler(event, context):
    """Lambda関数のメインハンドラ"""
    logger.info(f"イベント受信: {json.dumps(event)}")

    if 'Records' not in event or not event['Records']:
        logger.error("イベントにレコードが見つかりません。")
        return {'statusCode': 400, 'body': json.dumps('S3レコードがイベントに見つかりません。')}

    s3_record = event['Records'][0]['s3']
    input_bucket_name = s3_record['bucket']['name']
    input_object_key = urllib.parse.unquote_plus(s3_record['object']['key'], encoding='utf-8')

    logger.info(f"入力ファイルを処理中: s3://{input_bucket_name}/{input_object_key}")

    try:
        response = s3_client.get_object(Bucket=input_bucket_name, Key=input_object_key)
        input_data = json.loads(response['Body'].read().decode('utf-8'))
        target_urls = input_data.get('latest_target_url_list', [])
        previous_error_details = input_data.get('previous_error_details', [])

        logger.info(f"入力データを正常に読み込みました。対象URL数: {len(target_urls)}")
        logger.info(f"前回のエラー詳細数: {len(previous_error_details)}")

        all_detailed_results = []
        current_errors = []

        for target_item in target_urls:
            blog_url = target_item.get('url')
            if not blog_url:
                logger.warning(f"URLがないためターゲット項目をスキップします: {target_item}")
                continue
            
            is_livedoor = "livedoor.blog" in blog_url or "blog.jp" in blog_url
            is_hatena = "hatenablog.com" in blog_url or "hatenablog.jp" in blog_url

            if is_hatena:
                logger.info(f"はてなブログを処理中: {blog_url}")
                current_page_url = blog_url
                
                # --- ここをwhileループに戻し、ページネーションをたどる ---
                while current_page_url:
                    logger.info(f"ページをクロール中: {current_page_url}")
                    html_content = get_html_content(current_page_url)
                    
                    if not html_content:
                        logger.warning(f"ページのコンテンツ取得に失敗したため、このURLでのクロールを終了します: {current_page_url}")
                        # ページ取得失敗時はエラーとして記録せず、次のブログの処理に移る
                        break 
                    
                    # ページ内の指定広告リンクをすべて抽出
                    extracted_links = extract_hatena_ad_links(html_content, current_page_url)
                    logger.info(f"{current_page_url} から {len(extracted_links)} 個の対象広告リンクを抽出しました")

                    # 抽出したリンクのステータスを並列でチェック
                    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                        future_to_link = {executor.submit(check_link_status, link): link for link in extracted_links}
                        for future in as_completed(future_to_link):
                            link = future_to_link[future]
                            try:
                                check_result = future.result()
                                
                                detailed_result = {
                                    "blog_url": blog_url, 
                                    "page_url": current_page_url, 
                                    "checked_link": link, 
                                    "status": check_result["status"], 
                                    "status_code": check_result["status_code"], 
                                    "final_url": check_result["final_url"], 
                                    "error_message": check_result["error_message"], 
                                    "timestamp": datetime.now().isoformat()
                                }
                                all_detailed_results.append(detailed_result)
                                
                                if check_result["status"] == "ERROR":
                                    current_errors.append({
                                        "blog_url": blog_url, 
                                        "page_url": current_page_url, 
                                        "checked_link": link, 
                                        "error_reason": check_result["error_message"] or f"ステータスコード: {check_result['status_code']}"
                                    })
                            except Exception as exc:
                                logger.error(f"リンクチェック中に例外が発生しました {link}: {exc}")
                                all_detailed_results.append({"blog_url": blog_url, "page_url": current_page_url, "checked_link": link, "status": "ERROR", "status_code": None, "final_url": link, "error_message": str(exc), "timestamp": datetime.now().isoformat()})
                                current_errors.append({"blog_url": blog_url, "page_url": current_page_url, "checked_link": link, "error_reason": str(exc)})
                    
                    # 次のページのURLを取得
                    current_page_url = find_next_page_link(html_content, current_page_url)

                    # 次のページがある場合は、サーバー負荷軽減のために待機
                    if current_page_url:
                        logger.info(f"次のページへアクセスする前に{CRAWL_WAIT_SECONDS}秒待機します...")
                        time.sleep(CRAWL_WAIT_SECONDS)

            elif is_livedoor:
                logger.info(f"ライブドアブログを処理中: {blog_url}")
                top_page_content = get_html_content(blog_url)
                if top_page_content:
                    article_urls = extract_article_links_for_livedoor(top_page_content, blog_url)
                    logger.info(f"{blog_url} から {len(article_urls)} 件の記事URLを抽出しました。")
                    if not article_urls:
                        logger.warning(f"記事URLが見つかりませんでした。トップページのリンクをチェックします。")
                        process_page_links(blog_url, blog_url, all_detailed_results, current_errors)
                    else:
                        for article_url in article_urls:
                            process_page_links(article_url, blog_url, all_detailed_results, current_errors)
                else:
                    error_reason = "ブログトップページのコンテンツ取得に失敗しました"
                    all_detailed_results.append({"blog_url": blog_url, "checked_link": blog_url, "status": "ERROR", "status_code": None, "error_message": error_reason, "timestamp": datetime.now().isoformat()})
                    current_errors.append({"blog_url": blog_url, "checked_link": blog_url, "error_reason": error_reason})
            
            else:
                logger.info(f"汎用ページとして処理中: {blog_url}")
                process_page_links(blog_url, blog_url, all_detailed_results, current_errors)

        logger.info(f"詳細結果の合計: {len(all_detailed_results)}")
        logger.info(f"現在のエラー合計: {len(current_errors)}")

        previous_error_set = {(e.get('page_url', e['blog_url']), e['checked_link']) for e in previous_error_details}
        current_error_set = {(e.get('page_url', e['blog_url']), e['checked_link']) for e in current_errors}
        new_errors = [e for e in current_errors if (e.get('page_url', e['blog_url']), e['checked_link']) not in previous_error_set]
        fixed_links = [e for e in previous_error_details if (e.get('page_url', e['blog_url']), e['checked_link']) not in current_error_set]

        logger.info(f"新規エラー検出数: {len(new_errors)}")
        logger.info(f"修正済みリンク検出数: {len(fixed_links)}")

        timestamp = datetime.now().isoformat()
        output_data = {"all_detailed_logs": all_detailed_results, "new_errors": new_errors, "fixed_links": fixed_links}

        if S3_OUTPUT_BUCKET:
            now = datetime.now()
            output_key_prefix = now.strftime("%Y-%m-%d")
            timestamp_str = now.strftime("%Y%m%dT%H%M%S")
            detailed_key = f"results/{output_key_prefix}/detailed_logs_{timestamp_str}.json"
            
            s3_client.put_object(Bucket=S3_OUTPUT_BUCKET, Key=detailed_key, Body=json.dumps(output_data, indent=2, ensure_ascii=False))
            logger.info(f"詳細結果を s3://{S3_OUTPUT_BUCKET}/{detailed_key} にアップロードしました")
        else:
            logger.error("S3_OUTPUT_BUCKET 環境変数が設定されていません。結果をアップロードできません。")

        sns_subject = "リンクチェック完了通知"
        if not new_errors and not fixed_links:
            sns_message = "リンクチェックが完了しました。前回からの変更はありません。"
        else:
            sns_message = "リンクチェックが完了しました。結果に変更がありました。\n\n"
            if new_errors:
                sns_message += "■ 新規エラー:\n"
                for err in new_errors:
                    sns_message += f"- 記事ページ: {err.get('page_url', err['blog_url'])}\n  対象リンク: {err['checked_link']}\n  エラー理由: {err['error_reason']}\n"
                sns_message += "\n"
            if fixed_links:
                sns_message += "■ 修正済みリンク:\n"
                for fixed in fixed_links:
                    sns_message += f"- 記事ページ: {fixed.get('page_url', fixed['blog_url'])}\n  対象リンク: {fixed['checked_link']}\n"
        
        publish_sns_notification(sns_subject, sns_message)

        return {'statusCode': 200, 'body': json.dumps('リンクチェック処理が正常に完了しました！')}

    except Exception as e:
        logger.error(f"リンクチェック処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
        publish_sns_notification("リンクチェック処理エラー", f"リンクチェック処理中に予期せぬエラーが発生しました: {e}")
        return {'statusCode': 500, 'body': json.dumps(f'リンクチェック処理中にエラーが発生しました: {e}')}