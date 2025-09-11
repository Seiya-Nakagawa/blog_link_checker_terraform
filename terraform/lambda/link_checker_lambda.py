# -*- coding: utf-8 -*-
import os
import json
import urllib.parse
import logging
import time
import re
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
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
try:
    S3_OUTPUT_BUCKET = os.environ.get('S3_OUTPUT_BUCKET')
    REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', '15'))
    MAX_RETRIES = int(os.environ.get('MAX_RETRIES', '3'))
    BACKOFF_FACTOR = float(os.environ.get('BACKOFF_FACTOR', '2'))
    MAX_WORKERS = int(os.environ.get('MAX_WORKERS', '10'))
    CRAWL_WAIT_SECONDS = int(os.environ.get('CRAWL_WAIT_SECONDS', '5'))
    GAS_WEBAPP_URL = os.environ.get('GAS_WEBAPP_URL')
except (ValueError, TypeError) as e:
    logger.error(f"環境変数が設定されていません。エラー: {e}")
    raise

def requests_retry_session(retries=MAX_RETRIES, backoff_factor=BACKOFF_FACTOR, status_forcelist=(429, 500, 502, 503, 504), session=None):
    session = session or requests.Session()
    retry = Retry(total=retries, read=retries, connect=retries, backoff_factor=backoff_factor, status_forcelist=status_forcelist, respect_retry_after_header=True)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def get_html_content(url):
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

def extract_ad_links(html_content, base_url):
    if not html_content:
        return None
    soup = BeautifulSoup(html_content, 'html.parser')
    body = soup.body
    if not body:
        return None
    ad_notice_texts = body.find_all(string=re.compile(r"※一部、広告・宣伝が含まれます。"))
    if not ad_notice_texts:
        return None
    links = set()
    for notice_text in ad_notice_texts:
        for next_element in notice_text.find_all_next():
            if next_element.name == 'a' and next_element.has_attr('href'):
                href = next_element['href']
                if href and not href.lower().startswith('javascript:'):
                    full_url = urllib.parse.urljoin(base_url, href)
                    if full_url.split('#')[0] != base_url.split('#')[0]:
                        links.add(full_url)
                    break
    return [link for link in links if not urllib.parse.urlparse(link).fragment]

def find_hatena_next_page_link(html_content, base_url):
    if not html_content: return None
    soup = BeautifulSoup(html_content, 'html.parser')
    next_link_tag = soup.find('a', rel='next', href=True)
    if next_link_tag:
        return urllib.parse.urljoin(base_url, next_link_tag['href'])
    return None

def extract_livedoor_article_links(html_content, base_url):
    links = set()
    if not html_content: return list(links)
    soup = BeautifulSoup(html_content, 'html.parser')
    for article in soup.find_all('article', class_=re.compile(r'article')):
        title_link = article.select_one('h1.article-title a, h2.article-title a, a.article-title-link')
        if title_link and title_link.has_attr('href'):
            href = title_link['href']
            if href and not href.startswith('#') and not href.lower().startswith('javascript:'):
                full_url = urllib.parse.urljoin(base_url, href)
                links.add(full_url.split('#')[0])
    return list(links)

def find_livedoor_next_page_link(html_content, base_url):
    if not html_content: return None
    soup = BeautifulSoup(html_content, 'html.parser')
    next_link_tag = soup.select_one('a.next, a.pager-next, a:-soup-contains("»"), a:-soup-contains("次へ")')
    if next_link_tag and next_link_tag.has_attr('href'):
        return urllib.parse.urljoin(base_url, next_link_tag['href'])
    return None

def check_link_status(url, ng_words=None):
    session = requests_retry_session()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8', 'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8'}
    current_url = url
    for i in range(5):
        try:
            response = session.get(current_url, timeout=REQUEST_TIMEOUT, headers=headers, allow_redirects=True)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            page_content = response.text
            soup = BeautifulSoup(page_content, 'html.parser')
            refresh_tag = soup.find('meta', attrs={'http-equiv': re.compile(r'refresh', re.I)})
            if refresh_tag and refresh_tag.get('content'):
                content_attr = refresh_tag['content'].lower()
                match = re.search(r'url=(.+)', content_attr)
                if match:
                    next_url = match.group(1).strip().strip("'\"")
                    current_url = urllib.parse.urljoin(response.url, next_url)
                    continue
            if ng_words:
                for word in ng_words:
                    if word in page_content:
                        return {"status_code": response.status_code, "final_url": response.url, "error_message": f"ページ内にNGワードが含まれています: '{word}'"}
            return {"status_code": response.status_code, "final_url": response.url, "error_message": None}
        except requests.exceptions.HTTPError as e:
            return {"status_code": e.response.status_code if e.response else None, "final_url": e.response.url if e.response else current_url, "error_message": str(e)}
        except requests.exceptions.RequestException as e:
            return {"status_code": None, "final_url": current_url, "error_message": str(e)}
    return {"status_code": None, "final_url": current_url, "error_message": "Meta refresh redirect limit exceeded"}

def publish_sns_notification(subject, message):
    if not SNS_TOPIC_ARN: return
    try:
        sns_client.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=message)
    except Exception as e:
        logger.error(f"SNS通知の公開エラー: {e}")

def execute_gas_webapp(s3_key):
    if not GAS_WEBAPP_URL:
        logger.info("GAS_WEBAPP_URLが設定されていないため、GASの実行をスキップします。")
        return
    try:
        payload = {'s3_key': s3_key}
        headers = {'Content-Type': 'application/json'}
        response = requests.post(GAS_WEBAPP_URL, data=json.dumps(payload), headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        logger.info(f"GASウェブアプリを正常に実行しました。ステータスコード: {response.status_code}")
        logger.debug(f"GASからの応答: {response.text}")
    except requests.exceptions.RequestException as e:
        logger.error(f"GASウェブアプリの実行に失敗しました: {e}")

def lambda_handler(event, context):
    try:
        logger.info(f"イベント受信: {json.dumps(event)}")
        ng_words_str = os.environ.get('NG_WORDS', '')
        ng_words = [word.strip() for word in ng_words_str.split(',') if word.strip()]
        if 'Records' not in event or not event['Records']:
            return {'statusCode': 400, 'body': json.dumps({'message': 'S3レコードがイベントに見つかりません。'}, ensure_ascii=False)}
        s3_record = event['Records'][0]['s3']
        input_bucket_name = s3_record['bucket']['name']
        input_object_key = urllib.parse.unquote_plus(s3_record['object']['key'], encoding='utf-8')
        response = s3_client.get_object(Bucket=input_bucket_name, Key=input_object_key)
        input_data = json.loads(response['Body'].read().decode('utf-8'))
        target_urls = input_data.get('latest_target_url_list', [])
        previous_error_details = input_data.get('previous_error_details', [])
        all_detailed_results = []
        current_errors = []
        
        for target_item in target_urls:
            blog_url = target_item.get('url')
            if not blog_url: continue
            
            is_hatena = "hatenablog.com" in blog_url or "hatenablog.jp" in blog_url
            is_livedoor = "livedoor.blog" in blog_url or "blog.jp" in blog_url

            if is_hatena:
                logger.info(f"はてなブログを処理中: {blog_url}")
                current_page_url = blog_url
                while current_page_url:
                    logger.info(f"ページをクロール中: {current_page_url}")
                    html_content = get_html_content(current_page_url)
                    if not html_content: break
                    extracted_links = extract_ad_links(html_content, current_page_url)
                    if extracted_links is None:
                        logger.info(f"{current_page_url} には広告注釈が見つからないため、スキップします。")
                    else:
                        logger.info(f"{current_page_url} から {len(extracted_links)} 個の対象広告リンクを抽出しました")
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
                                    if not (check_result["status_code"] and 200 <= check_result["status_code"] < 400) or check_result["error_message"]:
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

            elif is_livedoor:
                logger.info(f"ライブドアブログを処理中: {blog_url}")
                all_article_urls = set()
                current_list_page_url = blog_url
                while current_list_page_url:
                    logger.info(f"記事一覧ページをクロール中: {current_list_page_url}")
                    list_page_html = get_html_content(current_list_page_url)
                    if not list_page_html: break
                    article_links_on_page = extract_livedoor_article_links(list_page_html, current_list_page_url)
                    all_article_urls.update(article_links_on_page)
                    current_list_page_url = find_livedoor_next_page_link(list_page_html, current_list_page_url)
                    if current_list_page_url: time.sleep(CRAWL_WAIT_SECONDS)
                
                logger.info(f"合計 {len(all_article_urls)} 件の記事URLを抽出しました。")
                for article_url in all_article_urls:
                    time.sleep(1)
                    logger.info(f"記事ページをチェック中: {article_url}")
                    article_html = get_html_content(article_url)
                    if not article_html: continue
                    extracted_links = extract_ad_links(article_html, article_url)
                    if extracted_links is None:
                        logger.info(f"{article_url} には広告注釈が見つからないため、スキップします。")
                    else:
                        logger.info(f"{article_url} から {len(extracted_links)} 個の対象広告リンクを抽出しました")
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
                                    if not (check_result["status_code"] and 200 <= check_result["status_code"] < 400) or check_result["error_message"]:
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

        logger.info(f"詳細結果の合計: {len(all_detailed_results)}")
        logger.info(f"現在のエラー合計: {len(current_errors)}")
        previous_error_set = {(e.get('page_url', e['blog_url']), e['checked_link']) for e in previous_error_details}
        current_error_set = {(e.get('page_url', e['blog_url']), e['checked_link']) for e in current_errors}
        new_errors = [e for e in current_errors if (e.get('page_url', e['blog_url']), e['checked_link']) not in previous_error_set]
        fixed_links = [e for e in previous_error_details if (e.get('page_url', e['blog_url']), e['checked_link']) not in current_error_set]
        logger.info(f"新規エラー検出数: {len(new_errors)}")
        logger.info(f"修正済みリンク検出数: {len(fixed_links)}")
        timestamp = datetime.now().isoformat()
        output_summary = { "total_links_checked": len(all_detailed_results), "total_errors": len(current_errors), "new_errors_count": len(new_errors), "fixed_links_count": len(fixed_links), "timestamp": timestamp }
        output_data = { "summary": output_summary, "all_detailed_logs": all_detailed_results, "errors": current_errors, "fixed_links": fixed_links }
        
        if S3_OUTPUT_BUCKET:
            now = datetime.now()
            timestamp_str = now.strftime("%Y%m%dT%H%M%S")
            detailed_key = f"results/linkcheck_result.json"
            s3_client.put_object(Bucket=S3_OUTPUT_BUCKET, Key=detailed_key, Body=json.dumps(output_data, indent=2, ensure_ascii=False))
            logger.info(f"詳細結果を s3://{S3_OUTPUT_BUCKET}/{detailed_key} にアップロードしました")
            
            execute_gas_webapp(detailed_key)
            
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
        
        return {'statusCode': 200, 'body': json.dumps({'message': 'リンクチェック処理が正常に完了しました！'}, ensure_ascii=False)}
    except Exception as e:
        logger.error(f"リンクチェック処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
        publish_sns_notification("リンクチェック処理エラー", f"リンクチェック処理中に予期せぬエラーが発生しました: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps({'message': f'リンクチェック処理中にエラーが発生しました: {str(e)}'}, ensure_ascii=False)}