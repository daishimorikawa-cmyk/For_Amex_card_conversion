# Streamlit Cloud デプロイ手順

このアプリをStreamlit Cloudで公開するための手順です。

## 1. 準備されたファイル
以下のファイルがデプロイのために自動生成・確認されました。
- `requirements.txt`: Pythonライブラリの依存関係定義（既存）
- `packages.txt`: システムライブラリの依存関係定義（Poppler, Tesseract, libgl1など）

※ Streamlit Cloudでは `Procfile` は不要です。

## 2. GitHubへのアップロード
まだGitHubにリポジトリがない場合は作成し、コードをプッシュしてください。

```bash
git add .
git commit -m "Prepare for Streamlit Cloud deployment"
git push
```

## 3. Streamlit Cloudでの設定

1. [Streamlit Cloud](https://streamlit.io/cloud) にログインし、"New app" をクリックします。
2. GitHubリポジトリ、ブランチ（通常は`main`または`master`）、およびメインファイルパス（`app.py`）を選択します。
3. **重要: Secretsの設定**
   Gemini APIキーを安全に設定するために、デプロイ画面の "Advanced settings" をクリックし、Functionsセクションにある "Secrets" 欄に以下のように入力してください。

   ```toml
   GOOGLE_API_KEY = "ここにあなたのGeminiAPIキーを貼り付け"
   ```

   ※ `.env` ファイルはセキュリティ上の理由からアップロードされないため、この設定が必須です。

4. "Deploy!" をクリックします。

## 4. 動作確認
デプロイが完了するとアプリが起動します。
Streamlit Cloudのサーバー上でライブラリ（Tesseractなど）のインストールが行われるため、初回の起動には数分かかる場合があります。

もしエラーが出る場合は、画面右下の "Manage app" からログを確認してください。
