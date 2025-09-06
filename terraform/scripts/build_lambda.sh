#!/bin/bash
set -e

# -------------------------------------------------------------------
# 【重要】Terraform Cloud環境に必要なツールを管理者権限でインストールする
# -------------------------------------------------------------------
# apt-getコマンドには管理者権限が必要なため、先頭に"sudo"を追加します。
echo "Updating package lists and installing zip..."
sudo apt-get update > /dev/null
sudo apt-get install -y zip > /dev/null
echo "Installation complete."
# -------------------------------------------------------------------

# スクリプトが置かれているディレクトリ('scripts')を基準にする
SCRIPT_DIR=$(dirname "$0")
# プロジェクトのルートディレクトリは、スクリプトの場所から一つ上の階層
PROJECT_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)

# 各パスをプロジェクトルートからの相対パスとして定義
SOURCE_DIR="${PROJECT_ROOT}/lambda"
BUILD_DIR="${PROJECT_ROOT}/build"
OUTPUT_PATH="${BUILD_DIR}/lambda_package.zip"

# 以前のビルド結果をクリーンアップ
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/pkg"

# ライブラリを一時ディレクトリ(pkg)にインストール
pip install -r "${SOURCE_DIR}/requirements.txt" -t "${BUILD_DIR}/pkg" > /dev/null

# Lambda関数コードを一時ディレクトリにコピー
cp "${SOURCE_DIR}/link_checker_lambda.py" "${BUILD_DIR}/pkg/"

# 一時ディレクトリの中身をZIP化
(cd "${BUILD_DIR}/pkg" && zip -r "${OUTPUT_PATH}" .)

# Terraformに渡すJSONを出力
jq -n --arg path "$OUTPUT_PATH" '{"output_path": $path}'