import os
import json
import urllib.request
import logging
import boto3
from datetime import datetime

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

def lambda_handler(event, context):
    """
    Lambda function to process S3 PUT events for link_check_data.json.
    Reads the JSON, performs dummy link checks, and logs the results.
    """
    logger.info(f"Received event: {json.dumps(event)}")

    # Extract S3 bucket and key from the event
    if 'Records' not in event or not event['Records']:
        logger.error("No records found in the event.")
        return {
            'statusCode': 400,
            'body': json.dumps('No S3 records found in the event.')
        }

    s3_record = event['Records'][0]['s3']
    bucket_name = s3_record['bucket']['name']
    object_key = urllib.parse.unquote_plus(s3_record['object']['key'], encoding='utf-8')

    logger.info(f"Processing file s3://{bucket_name}/{object_key}")

    try:
        # Get the object from S3
        s3_client = boto3.client('s3')
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        file_content = response['Body'].read().decode('utf-8')
        link_data = json.loads(file_content)

        logger.info(f"Successfully read link data: {link_data}")

        results = []
        # Dummy link checking logic
        for item in link_data.get('links', []):
            url = item.get('url')
            if url:
                try:
                    # This is a dummy check. In a real scenario, you'd use requests or similar.
                    # For simplicity, just checking if it's a valid URL format.
                    status = "SUCCESS" if url.startswith("http") else "INVALID_URL"
                    logger.info(f"Checking URL: {url} - Status: {status}")
                    results.append({"url": url, "status": status, "timestamp": datetime.now().isoformat()})
                except Exception as e:
                    logger.error(f"Error checking URL {url}: {e}")
                    results.append({"url": url, "status": "ERROR", "error_message": str(e), "timestamp": datetime.now().isoformat()})
            else:
                logger.warning("Skipping item with no URL.")

        logger.info(f"Link check results: {results}")

        

        # TODO: Send notification (e.g., Slack)
        # Example:
        # slack_webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
        # if slack_webhook_url:
        #     message = {"text": f"Link check completed for {object_key}. Results: {json.dumps(results)}"}
        #     req = urllib.request.Request(slack_webhook_url, data=json.dumps(message).encode('utf-8'), headers={'Content-Type': 'application/json'})
        #     urllib.request.urlopen(req)
        #     logger.info("Slack notification sent.")

        return {
            'statusCode': 200,
            'body': json.dumps('Link check process completed successfully!')
        }

    except Exception as e:
        logger.error(f"Error processing S3 object {object_key}: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error processing S3 object: {e}')
        }
