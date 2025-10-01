/**
 * @fileoverview プロジェクト全体の設定を管理する共通ファイルです。
 */

// =============================================================================
// --- コード内で管理する定数 (UIや固定ファイル名など変更頻度が低いもの) ---
// =============================================================================

// --- 事前処理用 ---
const S3_URL_FILE_KEY = 'urls_list.json';
const SHEET_NAME_SUMMARY = '前回URLチェック件数';
const SHEET_NAME_TARGET = 'ブログ一覧';
const SHEET_NAME_MANUAL = 'ブログ一覧_手動';
const SUMMARY_CELL = 'A1';

// --- 事後処理用 ---
const SHEET_NAME_TODAY = 'リンクチェック結果_当日';
const SHEET_NAME_YESTERDAY = 'リンクチェック結果_前日';
const ADD_COLOR = '#E0FFE0';
const CHANGE_COLOR = '#FFFFE0';
const DELETE_COLOR = '#FFE0E0';
const S3_RESULT_FILE_KEY = 'linkcheck_result.csv';
const S3_FLAG_FILE_KEY = 'lambda_completion_status.json';
const RESULT_SHEET_COLUMN_COUNT = 8;


// =============================================================================
// --- スクリプトプロパティから読み込む設定 ---
// =============================================================================

/**
 * プロジェクト全体で使用する設定をスクリプトプロパティから読み込みます。
 * @returns {object} スクリプトプロパティから取得した設定オブジェクト
 */
function getScriptConfiguration_() {
  const properties = PropertiesService.getScriptProperties();

  return {
    // スプレッドシート関連
    SPREADSHEET_ID_WORK: properties.getProperty('SPREADSHEET_ID_WORK'),   // 事前・事後処理で共通の作業用ID
    SPREADSHEET_ID_SOURCE: properties.getProperty('SPREADSHEET_ID_SOURCE'), // 事前処理で使う原本ID

    // S3関連
    S3_BUCKET_NAME: properties.getProperty('S3_BUCKET_NAME'),

    // 通知関連
    EMAIL_ADDRESSES: properties.getProperty('EMAIL_ADDRESSES'),

    // AWS認証情報
    S3_BUCKET_REGION: properties.getProperty('S3_BUCKET_REGION'),
    AWS_ACCESS_KEY_ID: properties.getProperty('AWS_ACCESS_KEY_ID'),
    AWS_SECRET_ACCESS_KEY: properties.getProperty('AWS_SECRET_ACCESS_KEY')
  };
}

/**
 * プロジェクト全体で利用するグローバルな設定オブジェクト
 */
const CONFIG = getScriptConfiguration_();