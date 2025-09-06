#!/bin/bash
set -e

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

# Terraformに渡すJSONを出力（絶対パスで渡すのが最も確実）
jq -n --arg path "$OUTPUT_PATH" '{"output_path": $path}'
