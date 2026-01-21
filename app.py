import streamlit as st
import os
import pandas as pd
import importlib.util
import time
import json
import datetime
from processor import AmexProcessor
import pytesseract
from dotenv import load_dotenv

load_dotenv()

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
    st.markdown("### 依存ツールパス設定")
    
    # Defaults
    default_tesseract = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    default_poppler = os.getenv("POPPLER_PATH", r"C:\poppler-25.12.0\Library\bin")
    
    tesseract_cmd = st.text_input("Tesseract Path", value=default_tesseract)
    poppler_path = st.text_input("Poppler Bin Path", value=default_poppler)
    
    st.markdown("---")
    st.markdown("### 依存ツール状態")
    
    # Check Poppler (mock check by ensuring path exists or fallback to import check)
    is_poppler_ok = os.path.exists(poppler_path) or (importlib.util.find_spec("pdf2image") is not None)
    st.write(f"Poppler Path: {'✅ Found' if os.path.exists(poppler_path) else '⚠️ Not Found (Check Path)'}")
    
    # Check Tesseract
    try:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        tesseract_version = pytesseract.get_tesseract_version()
        st.write(f"Tesseract: ✅ v{tesseract_version}")
    except Exception:
        st.write("Tesseract: ❌ Error")
        st.error("Tesseractのパスを確認してください。")

if not api_key_input:
    st.warning("左のサイドバーでGemini API Keyを設定してください。")
    st.stop()

# プロセッサ初期化
processor = AmexProcessor(api_key_input, tesseract_cmd, poppler_path)

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
                st.warning(f"期間抽出エラー: {e}")
            
            if period_info:
                s = period_info['start']
                e_date = period_info['end']
                st.success(f"📅 明細対象期間: {s.strftime('%Y/%m/%d')} 〜 {e_date.strftime('%Y/%m/%d')}")
            else:
                st.warning("⚠️ 期間の自動抽出に失敗しました。年補完は行われません（OCRの日付そのままとなります）。必要に応じて手動でCSVを修正してください。")
                # period_info remains None, logic downstream must handle this.
            
            # 3. 各ページ処理
            all_transactions = []
            
            # Page 1 is skipped for transactions
            for i, img in enumerate(images[1:], start=2):
                status_text.text(f"Processing page {i}/{total_pages}...")
                progress = (i / total_pages)
                progress_bar.progress(progress)
                
                # Find Best Crop (Optical analysis)
                # "1/17 Amazon" 対策: 最適なクロップ率を自動判定
                best_crop_img = processor.find_best_crop(img)
                
                # LLM Extraction (Image -> JSON)
                # 日本語Garbage対策: 画像を直接Geminiに渡して構造化抽出
                llm_response = processor.process_page_with_llm(best_crop_img)
                
                transactions = processor.parse_llm_response(
                    llm_response, 
                    period_info['start'] if period_info else None, 
                    period_info['end'] if period_info else None
                )
                
                if transactions:
                    st.write(f"Page {i}: {len(transactions)} 件抽出")
                    all_transactions.extend(transactions)
                else:
                    st.warning(f"Page {i}: データ抽出なし (空ページまたは読み取り不能)")
                    # Debug: Show crop used
                    # st.image(best_crop_img, caption=f"Page {i} Crop Used", width=300)

            progress_bar.progress(1.0)
            status_text.text("完了！")
            
            if not all_transactions:
                st.error("有効な明細データが見つかりませんでした。")
            else:
                # 4. DataFrame化 & 出力
                df = pd.DataFrame(all_transactions)
                
                # 必須仕様: 3列 (Date, Description, Amount)
                # 空欄 Description は parse_llm_response で "" になっている
                
                # Sort by date just in case
                try:
                    df['date_obj'] = pd.to_datetime(df['date'], errors='coerce')
                    df = df.sort_values('date_obj').drop(columns=['date_obj'])
                except:
                    pass

                final_cols = ["date", "description", "amount"]
                # Ensure columns exist
                for c in final_cols:
                    if c not in df.columns:
                        df[c] = ""
                        
                final_df = df[final_cols]
                
                # Check for empty descriptions (Logging requirement)
                empty_count = len(final_df[final_df['description'] == ""])
                if empty_count > 0:
                    st.warning(f"⚠️ {empty_count} 件の明細で「支払相手先」が空欄、または認識できませんでした。")

                st.subheader("抽出結果プレビュー")
                st.dataframe(final_df)
                
                # TSV Output (Headerなし)
                tsv = final_df.to_csv(sep="\t", index=False, header=False)
                st.text_area("TSV出力 (コピー用)", tsv, height=200)
                
                # CSV Download (Headerなし, UTF-8 BOM付き for Excel)
                csv = final_df.to_csv(index=False, header=False).encode('utf-8-sig')
                st.download_button(
                    label="CSVをダウンロード (Excel対応/UTF-8 BOM)",
                    data=csv,
                    file_name="amex_statement.csv",
                    mime="text/csv",
                )

        except Exception as e:
            st.error(f"エラーが発生しました: {str(e)}")
            st.error("PopplerやTesseractの設定が正しいか確認してください。")

