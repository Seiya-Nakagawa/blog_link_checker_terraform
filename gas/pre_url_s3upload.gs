/**
 * @fileoverview 事前処理を担当するスクリプトです。
 * スプレッドシートからURLリストを取得し、S3にアップロードします。
 */

// =============================================================================
// --- メイン処理 ---
// =============================================================================

/**
 * AWS Lambdaでのリンクチェックに必要な事前処理を実行するメイン関数です。
 */
function mainPreProcess() {
  const CONFIG = getScriptConfiguration_();

  try {
    // 設定値のチェック
    if (!CONFIG.SPREADSHEET_ID_WORK || !CONFIG.SPREADSHEET_ID_SOURCE || !CONFIG.S3_BUCKET_NAME) {
      throw new Error('スクリプトプロパティに必要な設定が不足しています。(SPREADSHEET_ID_WORK, SPREADSHEET_ID_SOURCE, S3_BUCKET_NAME)');
    }

    // 前回実行結果の取得（URL件数のみ）
    const previousUrlCount = getPreviousUrlCount_();

    // チェック対象リストの更新と取得
    const rawTargetUrls = getLatestTargetUrls_();

    // URL件数の比較と通知
    const currentUrlCount = rawTargetUrls.length;
    Logger.log(`URL件数の比較: 前回=${previousUrlCount}件, 今回=${currentUrlCount}件`);
    if (currentUrlCount !== previousUrlCount) {
      Logger.log(`URL件数に変動がありました。差分: ${currentUrlCount - previousUrlCount}件`);
      sendDifferenceReport_(previousUrlCount, currentUrlCount);
    } else {
      Logger.log('URL件数に変動はありませんでした。');
    }

    // 作業用スプレッドシートの実行サマリーシートを更新
    updateSummarySheet_(currentUrlCount);

    // Lambdaが期待する形式にデータを変換
    const autoUrlList = rawTargetUrls
      .filter(item => item.source === 'auto')
      .map(item => ({ "url": item.row[2] }));

    const manualUrlList = rawTargetUrls
      .filter(item => item.source === 'manual')
      .map(item => ({
        "spreadsheet_link": item.row[0],
        "blog_article_url": item.row[1],
        "affiliate_link": item.row[2]
      }));

    Logger.log(`自動取得URL件数: ${autoUrlList.length}, 手動設定URL件数: ${manualUrlList.length}`);

    // S3へのデータアップロード
    const uploadData = {
      auto_url_list: autoUrlList,
      manual_url_list: manualUrlList,
    };
    uploadToS3_(S3_URL_FILE_KEY, uploadData);

    Logger.log('事前処理が正常に完了しました。ファイル名: %s', S3_URL_FILE_KEY);

  } catch (e) {
    Logger.log('事前処理中にエラーが発生しました: %s', e.message);
    sendErrorNotification_(e);
    throw e;
  }
}


// =============================================================================
// --- ヘルパー関数 ---
// =============================================================================

/**
 * スクリプトプロパティから設定値を取得します。
 * @returns {object} 設定値のオブジェクト
 * @private
 */
function getScriptConfiguration_() {
  const properties = PropertiesService.getScriptProperties();
  return {
    SPREADSHEET_ID_WORK: properties.getProperty('SPREADSHEET_ID_WORK'),
    SPREADSHEET_ID_SOURCE: properties.getProperty('SPREADSHEET_ID_SOURCE'),
    S3_BUCKET_NAME: properties.getProperty('S3_BUCKET_NAME'),
    EMAIL_ADDRESSES: properties.getProperty('EMAIL_ADDRESSES'),
    AWS_ACCESS_KEY_ID: properties.getProperty('AWS_ACCESS_KEY_ID'),
    AWS_SECRET_ACCESS_KEY: properties.getProperty('AWS_SECRET_ACCESS_KEY')
  };
}

/**
 * 作業用スプレッドシートから前回実行時のURL総数を取得します。
 * @returns {number} 前回総リンク数
 * @private
 */
function getPreviousUrlCount_() {
  const CONFIG = getScriptConfiguration_();
  const ss = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID_WORK);
  const summarySheet = ss.getSheetByName(SHEET_NAME_SUMMARY);
  const linkCount = summarySheet ? summarySheet.getRange('A1').getValue() : 0;

  Logger.log('前回実行時の総リンク数を取得しました: %s件', linkCount);

  return Number(linkCount) || 0;
}

/**
 * 最新のチェック対象URLリストを取得します。
 * 1. コピー元の「ブログ一覧」をコピー先の「ブログ一覧」に上書きコピーします。
 * 2. 作業用スプレッドシートの「ブログ一覧」と「ブログ一覧_手動」からURLを読み込みます。
 * @returns {Array<object>} チェック対象URLの配列
 * @private
 */
function getLatestTargetUrls_() {
  const CONFIG = getScriptConfiguration_();
  const sourceSs = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID_SOURCE);
  const workSs = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID_WORK);

  // 「ブログ一覧」シートをコピー元からコピー先へ上書きコピー
  const sourceSheet = sourceSs.getSheetByName(SHEET_NAME_TARGET);
  if (!sourceSheet) {
    throw new Error(`コピー元スプレッドシートに '${SHEET_NAME_TARGET}' シートが見つかりません。`);
  }
  
  const sourceData = sourceSheet.getLastRow() > 0 ? sourceSheet.getDataRange().getValues() : [];
  
  let workSheetTarget = workSs.getSheetByName(SHEET_NAME_TARGET);
  if (!workSheetTarget) {
    workSheetTarget = workSs.insertSheet(SHEET_NAME_TARGET);
  }
  
  workSheetTarget.clear();
  if (sourceData.length > 0) {
    workSheetTarget.getRange(1, 1, sourceData.length, sourceData[0].length).setValues(sourceData);
    Logger.log(`'${SHEET_NAME_TARGET}' シートをコピー元からコピー先に上書きコピーしました。総行数: ${sourceData.length}`);
  } else {
    Logger.log(`コピー元の'${SHEET_NAME_TARGET}'シートにデータがありませんでした。コピー先のシートはクリアされました。`);
  }

  // S3アップロード用のデータを【作業用スプレッドシート】から読み込む
  const autoBodyData = sourceData.length > 1 ? sourceData.slice(1) : [];
  Logger.log(`作業用の'${SHEET_NAME_TARGET}'からヘッダーを除き ${autoBodyData.length} 件のデータを取得しました。`);

  const manualSheet = workSs.getSheetByName(SHEET_NAME_MANUAL);
  let manualBodyData = [];
  if (manualSheet) {
    if (manualSheet.getLastRow() > 1) {
      manualBodyData = manualSheet.getRange(2, 1, manualSheet.getLastRow() - 1, manualSheet.getLastColumn()).getValues();
    }
    Logger.log(`作業用の'${SHEET_NAME_MANUAL}'から ${manualBodyData.length} 件のデータを取得しました。`);
  } else {
    Logger.log(`作業用スプレッドシートに '${SHEET_NAME_MANUAL}' シートが見つかりませんでした。`);
  }

  // データを結合し、戻り値を生成
  const autoUrls = autoBodyData.map(row => ({ row: row, source: 'auto' }));
  const manualUrls = manualBodyData.map(row => ({ row: row, source: 'manual' }));

  const combinedUrls = autoUrls.concat(manualUrls);
  
  const targetUrls = combinedUrls.filter(item => item.row[2] && String(item.row[2]).trim() !== '');
  Logger.log('チェック対象のURLを抽出しました。総URL数: %s', targetUrls.length);

  return targetUrls;
}


/**
 * 作業用スプレッドシートのサマリーシートを更新します。
 * @param {number} currentUrlCount - 今回のURL件数
 * @private
 */
function updateSummarySheet_(currentUrlCount) {
  const CONFIG = getScriptConfiguration_();
  const ss = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID_WORK);
  const summarySheet = ss.getSheetByName(SHEET_NAME_SUMMARY);
  if (summarySheet) {
    summarySheet.getRange('A1').setValue(currentUrlCount);
    Logger.log(`実行サマリーシートのA1セルを現在のURL件数(${currentUrlCount}件)で更新しました。`);
  } else {
    Logger.log(`警告: '${SHEET_NAME_SUMMARY}' シートが見つかりませんでした。A1セルの更新をスキップします。`);
  }
}

/**
 * データをJSON形式でS3にアップロードします。
 * @param {string} fileName - S3にアップロードするファイル名
 * @param {object} data - アップロードするデータ
 * @private
 */
function uploadToS3_(fileName, data) {
  const CONFIG = getScriptConfiguration_();
  const s3 = S3.getInstance(
    CONFIG.AWS_ACCESS_KEY_ID,
    CONFIG.AWS_SECRET_ACCESS_KEY
  );

  const blob = Utilities.newBlob(JSON.stringify(data, null, 2), 'application/json', fileName);
  const response = s3.putObject(CONFIG.S3_BUCKET_NAME, fileName, blob, { log: true });

  Logger.log('S3へのアップロードが完了しました。レスポンス: %s', response);
}

/**
 * URL件数の差分をメールで通知します。
 * @param {number} previousUrlCount - 前回のURL件数
 * @param {number} currentUrlCount - 今回のURL件数
 * @private
 */
function sendDifferenceReport_(previousUrlCount, currentUrlCount) {
  const CONFIG = getScriptConfiguration_();
  const recipients = CONFIG.EMAIL_ADDRESSES ? CONFIG.EMAIL_ADDRESSES : Session.getActiveUser().getEmail();
  const subject = 'ブログURL件数変動のお知らせ';
  const body = `ブログのURL件数に変動がありました。

- 前回の件数: ${previousUrlCount}件
- 今回の件数: ${currentUrlCount}件
- 差分: ${currentUrlCount - previousUrlCount}件

スプレッドシートをご確認ください。`;

  MailApp.sendEmail(recipients, subject, body);
  Logger.log('件数変動の通知メールを送信しました。宛先: %s', recipients);
}

/**
 * 実行時エラーをメールで通知します。
 * @param {Error} error - 発生したエラーオブジェクト
 * @private
 */
function sendErrorNotification_(error) {
  const CONFIG = getScriptConfiguration_();
  try {
    const recipients = CONFIG.EMAIL_ADDRESSES ? CONFIG.EMAIL_ADDRESSES : Session.getActiveUser().getEmail();
    const subject = '【エラー】ブログリンクチェッカー事前処理でエラーが発生しました';
    const body = `Google Apps Scriptの実行中にエラーが発生しました。

エラーメッセージ:
${error.message}

スタックトレース:
${error.stack}

ログをご確認ください。`;

    MailApp.sendEmail(recipients, subject, body);
    Logger.log('エラー通知メールを送信しました。');
  } catch (e) {
    Logger.log('エラー通知メールの送信自体に失敗しました: %s', e.message);
  }
}