# Amex PDF Converter

アメックスの利用明細PDFからデータを抽出し、経費精算用ファイル(TSV/CSV)を作成するツールです。

## インストールと実行方法

### 1. 前提条件 (外部ツールのインストール)
このツールはPDFの画像化とOCRを行うため、以下のツールが必要です。

1. **Poppler** (PDF -> 画像)
   - [Poppler for Windows](https://github.com/oschwartz10612/poppler-windows/releases/) などからダウンロード
   - 解凍後、`bin` フォルダへのパスを環境変数 `PATH` に追加してください。

2. **Tesseract-OCR** (画像 -> テキスト)
   - [Tesseract installer](https://github.com/UB-Mannheim/tesseract/wiki) をダウンロードしてインストール
   - インストール時に **「Japanese script」「Japanese」言語データ** を必ず選択してください。
   - インストール先（例: `C:\Program Files\Tesseract-OCR`）をPATHに追加するか、コード内のパス設定を確認してください。

### 2. Python環境のセットアップ

```bash
# 仮想環境の作成（推奨）
python -m venv venv
.\venv\Scripts\activate

# ライブラリのインストール
pip install -r requirements.txt
```

### 3. アプリケーションの起動

以下のコマンドでWebインターフェースが立ち上がります。

```bash
streamlit run app.py
```
または、付属の `start.bat` をダブルクリックしてください。

## 使い方
1. ブラウザが開いたら、サイドバーに **Gemini API Key** を入力します。
2. PDFファイルをアップロードします。
3. 「変換開始」をクリックします。
4. 処理が完了すると、画面にTSVが表示され、CSVをダウンロードできます。

## ファイル構成
- `app.py`: メインアプリケーション
- `processor.py`: データ処理ロジック (OCR, 画像処理, LLM)
- `requirements.txt`: 依存ライブラリ一覧
