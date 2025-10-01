# ブログリンクチェッカー (Blog Link Checker)

指定されたブログ記事内のリンク切れを自動でチェックするシステムです。  
Google Apps Script (GAS) と AWSサービスを連携させ、インフラはTerraformで管理します。

詳細な要件や設計については、`/docs` フォルダ内の[要件定義書](./docs/【ブログリンクチェッカー】要件定義書.md)および[基本設計書](./docs/【ブログリンクチェッカー】基本設計書.md)を参照してください。

## 処理フロー概要

1.  **[GAS]** Googleスプレッドシートからチェック対象のURLリストを取得し、S3にアップロードします。
2.  **[AWS]** S3へのアップロードをトリガーにLambda関数が起動し、URLをクロールしてリンクをチェックします。
3.  **[AWS]** Lambdaはチェック結果をCSVファイルとしてS3に出力します。
4.  **[GAS]** 結果ファイルをS3からダウンロードし、前回結果との差分をスプレッドシートに反映・整形します。
5.  **[GAS]** 処理結果（差分情報など）を管理者にメールで通知します。

## ディレクトリ構成

```
.
├── docs/         # 要件定義書、基本設計書、構成図
├── gas/          # Google Apps Scriptのソースコード
└── terraform/    # Terraformのソースコード
    ├── lambda/   # Lambda関数のソースコード (Python)
    └── *.tf      # AWSリソース定義ファイル
```

## セットアップとデプロイ

### 1. AWSインフラ (Terraform Cloud)

本システムのAWSリソースはTerraform Cloudを利用して管理・デプロイされます。

1.  **リソースの変更:**
    `terraform/` ディレクトリ内の `.tf` ファイルを修正します。

2.  **デプロイ:**
    変更をGitリポジトリのmainブランチにプッシュすると、連携されたTerraform Cloudのワークスペースで自動的に`plan`と`apply`が実行されます。

    ローカルでの動作確認は、Terraform CloudのCLIワークスペース連携設定に従ってください。
    ```bash
    # 初期化とTerraform Cloudへのログイン
    terraform init
    terraform login

    # デプロイ計画の確認
    terraform plan
    ```
    `apply`はTerraform Cloud上で実行されます。

### 2. Lambda関数

Lambda関数（Python）のコードは `terraform/lambda/` にあります。  
デプロイは上記の `terraform apply` に含まれており、Terraformが依存ライブラリと共にソースコードをzip化してアップロードします。

### 3. Google Apps Script (GAS)

`gas/` ディレクトリ内のスクリプトをGoogleスプレッドシートに紐づくGASプロジェクトにコピー＆ペーストして設定します。

1.  **スクリプトプロパティの設定**
    基本設計書に従い、以下の情報をGASのスクリプトプロパティに設定します。
    *   AWSの認証情報 (Access Key, Secret Key)
    *   各種スプレッドシートID
    *   通知先メールアドレス など

2.  **トリガーの設定**
    以下の2つの関数に対して、時間ベースのトリガーを設定します。
    *   `pre_url_s3upload.gs` 内の関数（例: `main`）: Lambda処理の前に実行（日次）
    *   `post_result_s3download.gs` 内の関数（例: `main`）: Lambda処理が十分に完了する時間を見越して実行（日次）

## 使い方

1.  GASで設定した「原本スプレッドシート」に、チェックしたいブログのURLを記載します。
2.  設定したトリガーに従ってシステムが自動で実行されます。
3.  処理が完了すると、GASで設定した通知先メールアドレスに結果サマリーが送信されます。
4.  詳細は「作業用スプレッドシート」で確認できます。新規エラーや修正済みリンクは色付けでハイライトされます。
