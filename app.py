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
st.set_page_config(
    layout="wide",
    page_title="Amex明細変換ツール",
    page_icon="💳",
    initial_sidebar_state="expanded"
)

# カスタムCSS
st.markdown("""
<style>
    /* メインコンテナ */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }

    /* ヘッダースタイル */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        box-shadow: 0 10px 40px rgba(102, 126, 234, 0.3);
    }

    .main-header h1 {
        color: white;
        font-size: 2.2rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.5px;
    }

    .main-header p {
        color: rgba(255, 255, 255, 0.9);
        font-size: 1rem;
        margin-top: 0.5rem;
        margin-bottom: 0;
    }

    /* カードスタイル */
    .custom-card {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
        border: 1px solid rgba(0, 0, 0, 0.05);
        margin-bottom: 1.5rem;
    }

    .custom-card h3 {
        color: #1a1a2e;
        font-size: 1.1rem;
        font-weight: 600;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    /* アップロードエリア */
    .upload-area {
        background: linear-gradient(135deg, #f5f7fa 0%, #e4e8eb 100%);
        border: 2px dashed #667eea;
        border-radius: 16px;
        padding: 3rem 2rem;
        text-align: center;
        transition: all 0.3s ease;
    }

    .upload-area:hover {
        border-color: #764ba2;
        background: linear-gradient(135deg, #f0f2f5 0%, #dde1e4 100%);
    }

    /* ボタンスタイル */
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        font-size: 1rem;
        font-weight: 600;
        border-radius: 10px;
        cursor: pointer;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        width: 100%;
    }

    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
    }

    /* プログレスバー */
    .stProgress > div > div > div {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }

    /* サイドバー */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    }

    section[data-testid="stSidebar"] .stMarkdown {
        color: rgba(255, 255, 255, 0.85);
    }

    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: white !important;
    }

    section[data-testid="stSidebar"] .stTextInput label {
        color: rgba(255, 255, 255, 0.7) !important;
    }

    /* ステータスバッジ */
    .status-badge {
        display: inline-flex;
        align-items: center;
        padding: 0.35rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 500;
        gap: 0.4rem;
    }

    .status-success {
        background: rgba(16, 185, 129, 0.15);
        color: #059669;
    }

    .status-warning {
        background: rgba(245, 158, 11, 0.15);
        color: #d97706;
    }

    .status-error {
        background: rgba(239, 68, 68, 0.15);
        color: #dc2626;
    }

    /* データフレーム */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
    }

    /* 結果カード */
    .result-card {
        background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
        border-radius: 12px;
        padding: 1.5rem;
        border-left: 4px solid #667eea;
        margin: 1rem 0;
    }

    /* アニメーション */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .animate-fade-in {
        animation: fadeIn 0.5s ease-out;
    }

    /* 統計カード */
    .stat-card {
        background: white;
        border-radius: 12px;
        padding: 1.25rem;
        text-align: center;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
        border: 1px solid rgba(0, 0, 0, 0.05);
    }

    .stat-value {
        font-size: 2rem;
        font-weight: 700;
        color: #667eea;
    }

    .stat-label {
        font-size: 0.85rem;
        color: #64748b;
        margin-top: 0.25rem;
    }
</style>
""", unsafe_allow_html=True)

# ヘッダー
st.markdown("""
<div class="main-header">
    <h1>💳 Amex利用明細 PDF変換ツール</h1>
    <p>PDFをアップロードして、経費精算用CSV/TSVを簡単に作成</p>
</div>
""", unsafe_allow_html=True)

# サイドバー設定
with st.sidebar:
    st.markdown("## ⚙️ 設定")
    st.markdown("---")

    # API Key Handling (Secure)
    env_api_key = os.getenv("GEMINI_API_KEY")
    if env_api_key:
        st.success("✅ API Key 設定済み")
        api_key_input = env_api_key
    else:
        st.markdown("### 🔑 API Key")
        api_key_input = st.text_input("Gemini API Key", type="password", label_visibility="collapsed")

    st.markdown("---")
    st.markdown("### 📁 ツールパス")

    # Defaults based on OS
    if os.name == 'nt':
        default_tesseract = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        default_poppler = os.getenv("POPPLER_PATH", r"C:\poppler-25.12.0\Library\bin")
    else:
        default_tesseract = os.getenv("TESSERACT_CMD", "")
        default_poppler = os.getenv("POPPLER_PATH", "")

    tesseract_cmd = st.text_input("Tesseract", value=default_tesseract)
    poppler_path = st.text_input("Poppler", value=default_poppler)

    st.markdown("---")
    st.markdown("### 📊 ステータス")

    # Check Poppler
    is_poppler_ok = os.path.exists(poppler_path) or (importlib.util.find_spec("pdf2image") is not None)
    if os.path.exists(poppler_path) or poppler_path == "":
        st.markdown("✅ Poppler: OK")
    else:
        st.markdown("⚠️ Poppler: パス確認")

    # Check Tesseract
    try:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        tesseract_version = pytesseract.get_tesseract_version()
        st.markdown(f"✅ Tesseract: v{tesseract_version}")
    except Exception:
        st.markdown("❌ Tesseract: エラー")

# API Key チェック
if not api_key_input:
    st.markdown("""
    <div class="custom-card" style="text-align: center; padding: 3rem;">
        <h3>🔐 API Keyを設定してください</h3>
        <p style="color: #64748b;">左のサイドバーでGemini API Keyを入力してください</p>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# プロセッサ初期化
processor = AmexProcessor(api_key_input, tesseract_cmd, poppler_path)

# メインコンテンツ
st.markdown("""
<div class="custom-card">
    <h3>📄 PDFアップロード</h3>
</div>
""", unsafe_allow_html=True)

# ファイルアップロード
uploaded_file = st.file_uploader(
    "Amex明細PDFをドラッグ＆ドロップ、またはクリックして選択",
    type=["pdf"],
    label_visibility="collapsed"
)

if uploaded_file is not None:
    # ファイル情報表示
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">📎</div>
            <div class="stat-label">{uploaded_file.name}</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        file_size = len(uploaded_file.getvalue()) / 1024
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{file_size:.1f}</div>
            <div class="stat-label">KB</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">PDF</div>
            <div class="stat-label">形式</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🚀 変換を開始する", use_container_width=True):
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            # 1. 画像化
            status_text.markdown("**🔄 PDFを画像に変換中...**")
            pdf_bytes = uploaded_file.getvalue()
            images = processor.convert_pdf_to_images(pdf_bytes)

            if len(images) < 2:
                st.error("⚠️ ページ数が不足しています（2ページ以上必要です）。")
                st.stop()

            total_pages = len(images)

            # 2. 期間抽出 (Page 1)
            status_text.markdown("**📅 1ページ目から期間を抽出中...**")
            period_info = None
            try:
                period_info = processor.extract_period(images[0])
            except Exception as e:
                st.warning(f"期間抽出エラー: {e}")

            if period_info:
                s = period_info['start']
                e_date = period_info['end']
                st.markdown(f"""
                <div class="result-card">
                    <strong>📅 明細対象期間</strong><br>
                    <span style="font-size: 1.2rem; color: #667eea;">{s.strftime('%Y/%m/%d')} 〜 {e_date.strftime('%Y/%m/%d')}</span>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.warning("⚠️ 期間の自動抽出に失敗しました。年補完は行われません。")

            # 3. 各ページ処理
            all_transactions = []

            for i, img in enumerate(images[1:], start=2):
                status_text.markdown(f"**📖 ページ {i}/{total_pages} を処理中...**")
                progress = (i / total_pages)
                progress_bar.progress(progress)

                best_crop_img = processor.find_best_crop(img)
                llm_response = processor.process_page_with_llm(best_crop_img)

                transactions = processor.parse_llm_response(
                    llm_response,
                    period_info['start'] if period_info else None,
                    period_info['end'] if period_info else None
                )

                if transactions:
                    all_transactions.extend(transactions)

            progress_bar.progress(1.0)
            status_text.markdown("**✅ 処理完了！**")

            if not all_transactions:
                st.error("有効な明細データが見つかりませんでした。")
            else:
                # 4. DataFrame化 & 出力
                df = pd.DataFrame(all_transactions)

                try:
                    df['date_obj'] = pd.to_datetime(df['date'], errors='coerce')
                    df = df.sort_values('date_obj').drop(columns=['date_obj'])
                except:
                    pass

                final_cols = ["date", "description", "amount"]
                for c in final_cols:
                    if c not in df.columns:
                        df[c] = ""

                final_df = df[final_cols]

                # 統計表示
                st.markdown("<br>", unsafe_allow_html=True)
                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    st.markdown(f"""
                    <div class="stat-card">
                        <div class="stat-value">{len(final_df)}</div>
                        <div class="stat-label">取引件数</div>
                    </div>
                    """, unsafe_allow_html=True)

                with col2:
                    st.markdown(f"""
                    <div class="stat-card">
                        <div class="stat-value">{total_pages}</div>
                        <div class="stat-label">ページ数</div>
                    </div>
                    """, unsafe_allow_html=True)

                with col3:
                    try:
                        total_amount = sum(int(str(a).replace(',', '').replace('-', '')) for a in final_df['amount'] if str(a).strip())
                        st.markdown(f"""
                        <div class="stat-card">
                            <div class="stat-value">¥{total_amount:,}</div>
                            <div class="stat-label">合計金額</div>
                        </div>
                        """, unsafe_allow_html=True)
                    except:
                        st.markdown(f"""
                        <div class="stat-card">
                            <div class="stat-value">-</div>
                            <div class="stat-label">合計金額</div>
                        </div>
                        """, unsafe_allow_html=True)

                with col4:
                    empty_count = len(final_df[final_df['description'] == ""])
                    st.markdown(f"""
                    <div class="stat-card">
                        <div class="stat-value">{empty_count}</div>
                        <div class="stat-label">空欄件数</div>
                    </div>
                    """, unsafe_allow_html=True)

                if empty_count > 0:
                    st.warning(f"⚠️ {empty_count} 件の明細で「支払相手先」が空欄です。")

                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("### 📋 抽出結果")
                st.dataframe(final_df, use_container_width=True, hide_index=True)

                # ダウンロードボタン
                st.markdown("<br>", unsafe_allow_html=True)
                col1, col2 = st.columns(2)

                with col1:
                    csv = final_df.to_csv(index=False, header=False).encode('utf-8-sig')
                    st.download_button(
                        label="📥 CSVダウンロード",
                        data=csv,
                        file_name="amex_statement.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

                with col2:
                    tsv = final_df.to_csv(sep="\t", index=False, header=False)
                    st.download_button(
                        label="📥 TSVダウンロード",
                        data=tsv.encode('utf-8'),
                        file_name="amex_statement.tsv",
                        mime="text/tab-separated-values",
                        use_container_width=True
                    )

                # TSVプレビュー（折りたたみ）
                with st.expander("📄 TSVプレビュー"):
                    st.code(tsv, language=None)

        except Exception as e:
            st.error(f"❌ エラーが発生しました: {str(e)}")
            st.info("💡 PopplerやTesseractの設定を確認してください。")

# フッター
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown("""
<div style="text-align: center; color: #94a3b8; font-size: 0.85rem; padding: 2rem 0;">
    <p>🔒 セキュリティ厳守: 個人情報はローカルで処理され、安全に管理されます</p>
</div>
""", unsafe_allow_html=True)
