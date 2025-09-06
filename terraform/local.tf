locals {
  # ここに作成したいフォルダ名を追加・削除するだけでOK
  s3_folder_names = toset([
    "gas_url/",
    "lambda-layers/"
  ])
}