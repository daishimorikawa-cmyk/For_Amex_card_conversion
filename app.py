import streamlit as st
import os
import pandas as pd
import importlib.util
import time
import json
from processor import AmexProcessor
import pytesseract

# ページ設定
st.set_page_config(layout="wide", page_title="Amex明細変換ツール")

st.title("💳 Amex利用明細 PDF変換ツール")
st.markdown("""
PDFをアップロードして、経費精算用CSV/TSVを作成します。
**セキュリティ厳守**: 個人情報はローカルでマスキングされ、AIには渡されません。
""")

# サイドバー設定
with st.sidebar:
    st.header("設定")
    env_api_key = os.getenv("GEMINI_API_KEY", "")
    api_key_input = st.text_input("Gemini API Key", value=env_api_key, type="password")
    
    st.markdown("---")
    st.markdown("### 依存ツール状態")
    
    # Check Poppler
    # 簡易チェック: pdf2imageがインポートできるか
    is_poppler_ok = importlib.util.find_spec("pdf2image") is not None
    st.write(f"Poppler (pdf2image): {'✅ OK' if is_poppler_ok else '❌ Missing'}")
    
    # Check Tesseract
    # 簡易チェック: pytesseractが実行できるか（パスが通っているか）
    try:
        tesseract_version = pytesseract.get_tesseract_version()
        st.write(f"Tesseract: ✅ v{tesseract_version}")
    except Exception:
        st.write("Tesseract: ❌ Missing (or not in PATH)")
        st.warning("Tesseractをインストールし、PATHに通してください。")

if not api_key_input:
    st.warning("左のサイドバーでGemini API Keyを設定してください。")
    st.stop()

# プロセッサ初期化
processor = AmexProcessor(api_key_input)

# ファイルアップロード
uploaded_file = st.file_uploader("Amex明細PDFをアップロード", type=["pdf"])

if uploaded_file is not None:
    if st.button("変換開始"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            # 1. 画像化
            status_text.text("PDFを画像に変換中...")
            pdf_bytes = uploaded_file.read()
            images = processor.convert_pdf_to_images(pdf_bytes)
            
            if len(images) < 2:
                st.error("ページ数が不足しています（2ページ以上必要です）。")
                st.stop()
                
            total_pages = len(images)
            st.info(f"全 {total_pages} ページを読み込みました。")
            
            # 2. 期間抽出 (Page 1)
            status_text.text("1ページ目から期間を抽出中...")
            period_info = None
            try:
                period_info = processor.extract_period(images[0])
            except Exception as e:
                st.warning(f"期間抽出に失敗しました (手動補完が必要になる可能性があります): {e}")
            
            current_year = period_info['year'] if period_info else 2024
            st.write(f"明細対象年（推定）: {current_year}年")
            
            # 3. 各ページ処理
            all_transactions = []
            
            # Page 1 is skipped for transactions
            for i, img in enumerate(images[1:], start=2):
                status_text.text(f"Processing page {i}/{total_pages}...")
                progress = (i / total_pages)
                progress_bar.progress(progress)
                
                # Preprocess (Crop)
                cropped = processor.preprocess_image(img)
                
                # OCR & Masking
                # 日本語OCRを含めるため lang='jpn+eng'。インストールされていない場合は eng のみになるかも
                ocr_text = pytesseract.image_to_string(cropped, lang='jpn+eng')
                masked_text = processor.redact_pii(ocr_text)
                
                # Check empty
                if len(masked_text.strip()) < 50:
                    st.write(f"Page {i}: 文字数が少ないためスキップしました。")
                    continue
                
                # LLM Extraction
                llm_response = processor.process_page_with_llm(masked_text, current_year)
                transactions = processor.parse_llm_response(llm_response)
                
                if transactions:
                    st.write(f"Page {i}: {len(transactions)} 件抽出")
                    all_transactions.extend(transactions)
                else:
                    st.warning(f"Page {i}: データ抽出できませんでした。")
                    with st.expander(f"Page {i} OCR Raw Data"):
                        st.text(masked_text)

            progress_bar.progress(1.0)
            status_text.text("完了！")
            
            if not all_transactions:
                st.error("有効な明細データが見つかりませんでした。")
            else:
                # 4. DataFrame化 & 出力
                df = pd.DataFrame(all_transactions)
                
                # カラム整理
                desired_columns = ["date", "payee", "empty", "amount"]
                # LLMの出力をマッピング
                df["payee"] = df.get("description", "")
                df["empty"] = "" # 空欄固定
                df["date"] = df.get("date", "")
                df["amount"] = df.get("amount", 0)
                
                final_df = df[["date", "payee", "empty", "amount"]]
                
                st.subheader("抽出結果プレビュー")
                st.dataframe(final_df)
                
                # TSV (Clipboard copy friendly)
                tsv = final_df.to_csv(sep="\t", index=False, header=False)
                st.text_area("TSV出力 (コピー用)", tsv, height=200)
                
                # CSV Download
                csv = final_df.to_csv(index=False, header=False).encode('utf-8')
                st.download_button(
                    label="CSVをダウンロード (UTF-8)",
                    data=csv,
                    file_name="amex_statement.csv",
                    mime="text/csv",
                )

        except Exception as e:
            st.error(f"エラーが発生しました: {str(e)}")
            st.error("Popplerの設定やTesseractのインストールを確認してください。")

