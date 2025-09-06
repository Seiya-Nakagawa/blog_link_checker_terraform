import os
import json
import urllib.parse
import logging
import boto3
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# AWS Clients
s3_client = boto3.client('s3')
sns_client = boto3.client('sns')

# Environment Variables
S3_OUTPUT_BUCKET = os.environ.get('S3_OUTPUT_BUCKET')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')

# Environment Variables with robust type conversion
try:
    REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', 10)) # seconds
    MAX_RETRIES = int(os.environ.get('MAX_RETRIES', 3))
    BACKOFF_FACTOR = float(os.environ.get('BACKOFF_FACTOR', 0.5))
    MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 10)) # Concurrency for link checking
except (ValueError, TypeError) as e:
    logger.warning(f"Invalid environment variable value, using defaults. Error: {e}")
    REQUEST_TIMEOUT = 10
    MAX_RETRIES = 3
    BACKOFF_FACTOR = 0.5
    MAX_WORKERS = 10

def requests_retry_session(retries=MAX_RETRIES, backoff_factor=BACKOFF_FACTOR, status_forcelist=(500, 502, 503, 504), session=None):
    """Setup requests session with retries."""
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def get_html_content(url):
    """Fetches HTML content from a given URL."""
    try:
        session = requests_retry_session()
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = session.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        return response.text
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching {url}: {e}")
        return None

def extract_links(html_content, base_url):
    """Extracts all href links from HTML content."""
    links = set()
    if not html_content:
        return links

    soup = BeautifulSoup(html_content, 'html.parser')
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        # Ignore empty, anchor, and javascript links
        if not href or href.startswith('#') or href.lower().startswith('javascript:'):
            continue
        full_url = urllib.parse.urljoin(base_url, href)
        links.add(full_url)
    return list(links)

def check_link_status(url):
    """Checks the status of a single link."""
    try:
        session = requests_retry_session()
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = session.head(url, timeout=REQUEST_TIMEOUT, headers=headers, allow_redirects=True)
        response.raise_for_status()
        return {
            "status_code": response.status_code,
            "redirected_url": response.url if response.url != url else None,
            "error_message": None
        }
    except requests.exceptions.HTTPError as e:
        return {
            "status_code": e.response.status_code if e.response is not None else None,
            "redirected_url": e.response.url if e.response is not None and e.response.url != url else None,
            "error_message": str(e)
        }
    except requests.exceptions.RequestException as e:
        return {
            "status_code": None,
            "redirected_url": None,
            "error_message": str(e)
        }

def publish_sns_notification(subject, message):
    """Publishes a message to an SNS topic."""
    if not SNS_TOPIC_ARN:
        logger.warning("SNS_TOPIC_ARN is not set. Skipping SNS notification.")
        return

    try:
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=message
        )
        logger.info(f"SNS notification sent: Subject='{subject}'")
    except Exception as e:
        logger.error(f"Error publishing SNS notification: {e}")

def lambda_handler(event, context):
    """
    Lambda function to process S3 PUT events for link_check_data.json.
    Performs comprehensive link checks, compares results, and sends notifications.
    """
    logger.info(f"Received event: {json.dumps(event)}")

    if 'Records' not in event or not event['Records']:
        logger.error("No records found in the event.")
        return {'statusCode': 400, 'body': json.dumps('No S3 records found in the event.')}

    s3_record = event['Records'][0]['s3']
    input_bucket_name = s3_record['bucket']['name']
    input_object_key = urllib.parse.unquote_plus(s3_record['object']['key'], encoding='utf-8')

    logger.info(f"Processing input file s3://{input_bucket_name}/{input_object_key}")

    try:
        # 1. Get the input file from S3
        response = s3_client.get_object(Bucket=input_bucket_name, Key=input_object_key)
        input_data = json.loads(response['Body'].read().decode('utf-8'))
        target_urls = input_data.get('latest_target_url_list', [])
        previous_error_details = input_data.get('previous_error_details', [])

        logger.info(f"Successfully read input data. Target URLs count: {len(target_urls)}")
        logger.info(f"Previous error details count: {len(previous_error_details)}")

        all_detailed_results = []
        current_errors = []

        # 2. Perform link checks
        for target_item in target_urls:
            blog_url = target_item.get('url')
            if not blog_url:
                logger.warning(f"Skipping target item with no URL: {target_item}")
                continue

            logger.info(f"Checking blog URL: {blog_url}")
            html_content = get_html_content(blog_url)
            if not html_content:
                error_reason = "Failed to fetch blog content"
                all_detailed_results.append({
                    "blog_url": blog_url, "checked_link": blog_url, "status": "ERROR",
                    "status_code": None, "error_message": error_reason, "timestamp": datetime.now().isoformat()
                })
                current_errors.append({"blog_url": blog_url, "checked_link": blog_url, "error_reason": error_reason})
                continue

            extracted_links = extract_links(html_content, blog_url)
            logger.info(f"Extracted {len(extracted_links)} links from {blog_url}")

            # Execute link checks in parallel for performance
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_link = {executor.submit(check_link_status, link): link for link in extracted_links}
                for future in as_completed(future_to_link):
                    link = future_to_link[future]
                    try:
                        check_result = future.result()
                        status = "OK" if check_result["status_code"] and 200 <= check_result["status_code"] < 400 else "ERROR"
                        detailed_result = {
                            "blog_url": blog_url, "checked_link": link, "status": status,
                            "status_code": check_result["status_code"], "redirected_url": check_result["redirected_url"],
                            "error_message": check_result["error_message"], "timestamp": datetime.now().isoformat()
                        }
                        all_detailed_results.append(detailed_result)
                        if status == "ERROR":
                            current_errors.append({
                                "blog_url": blog_url, "checked_link": link,
                                "error_reason": check_result["error_message"] or f"Status Code: {check_result['status_code']}"
                            })
                    except Exception as exc:
                        logger.error(f"An exception occurred while checking link {link}: {exc}")
                        all_detailed_results.append({
                            "blog_url": blog_url, "checked_link": link, "status": "ERROR",
                            "status_code": None, "error_message": str(exc), "timestamp": datetime.now().isoformat()
                        })
                        current_errors.append({"blog_url": blog_url, "checked_link": link, "error_reason": str(exc)})

        logger.info(f"Total detailed results: {len(all_detailed_results)}")
        logger.info(f"Total current errors: {len(current_errors)}")

        # 3. Compare results and detect changes
        previous_error_set = {(e['blog_url'], e['checked_link']) for e in previous_error_details}
        current_error_set = {(e['blog_url'], e['checked_link']) for e in current_errors}
        new_errors = [e for e in current_errors if (e['blog_url'], e['checked_link']) not in previous_error_set]
        fixed_links = [e for e in previous_error_details if (e['blog_url'], e['checked_link']) not in current_error_set]

        logger.info(f"New errors detected: {len(new_errors)}")
        logger.info(f"Fixed links detected: {len(fixed_links)}")

        # 4. Prepare output files
        timestamp = datetime.now().isoformat()
        output_summary = {
            "total_links_checked": len(all_detailed_results), "total_errors": len(current_errors),
            "new_errors_count": len(new_errors), "fixed_links_count": len(fixed_links), "timestamp": timestamp
        }
        output_data = {
            "summary": output_summary, "all_detailed_logs": all_detailed_results,
            "current_error_details": current_errors, "new_errors": new_errors, "fixed_links": fixed_links
        }

        # 5. Upload results to S3
        if S3_OUTPUT_BUCKET:
            now = datetime.now()
            output_key_prefix = now.strftime("%Y-%m-%d")
            timestamp_str = now.strftime("%Y%m%dT%H%M%S")
            summary_key = f"results/{output_key_prefix}/summary_{timestamp_str}.json"
            detailed_key = f"results/{output_key_prefix}/detailed_logs_{timestamp_str}.json"
            
            s3_client.put_object(Bucket=S3_OUTPUT_BUCKET, Key=summary_key, Body=json.dumps(output_summary, indent=2, ensure_ascii=False))
            logger.info(f"Uploaded summary to s3://{S3_OUTPUT_BUCKET}/{summary_key}")
            
            s3_client.put_object(Bucket=S3_OUTPUT_BUCKET, Key=detailed_key, Body=json.dumps(output_data, indent=2, ensure_ascii=False))
            logger.info(f"Uploaded detailed results to s3://{S3_OUTPUT_BUCKET}/{detailed_key}")
        else:
            logger.error("S3_OUTPUT_BUCKET environment variable is not set. Cannot upload results.")

        # 6. Send SNS Notification
        sns_subject = "リンクチェック完了通知"
        if not new_errors and not fixed_links:
            sns_message = "リンクチェックが完了しました。前回からの変更はありません。"
        else:
            sns_message = "リンクチェックが完了しました。結果に変更がありました。\n\n"
            if new_errors:
                sns_message += "■ 新規エラー:\n"
                for err in new_errors:
                    sns_message += f"- リンク元: {err['blog_url']}\n  対象リンク: {err['checked_link']}\n  エラー理由: {err['error_reason']}\n"
                sns_message += "\n"
            if fixed_links:
                sns_message += "■ 修正済みリンク:\n"
                for fixed in fixed_links:
                    sns_message += f"- リンク元: {fixed['blog_url']}\n  対象リンク: {fixed['checked_link']}\n"

        publish_sns_notification(sns_subject, sns_message)

        return {'statusCode': 200, 'body': json.dumps('Link check process completed successfully!')}

    except Exception as e:
        logger.error(f"Error during link check process: {e}", exc_info=True)
        publish_sns_notification("リンクチェック処理エラー", f"リンクチェック処理中に予期せぬエラーが発生しました: {e}")
        return {'statusCode': 500, 'body': json.dumps(f'Error during link check process: {e}')}