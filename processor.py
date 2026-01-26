import os
import re
import json
import datetime
from typing import List, Dict, Optional, Any

import pytesseract
from PIL import Image, ImageOps, ImageEnhance
import google.generativeai as genai

try:
    from pdf2image import convert_from_bytes
except ImportError:
    convert_from_bytes = None


class AmexProcessor:
    def __init__(self, api_key: str | None, tesseract_cmd: str = None, poppler_path: str = None):
        self.api_key = (api_key or "").strip()
        self.model = None

        # Configure Tesseract
        self.tesseract_cmd = tesseract_cmd
        if self.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

        # Configure Poppler (pdf2image uses this to find pdfinfo/pdftoppm)
        self.poppler_path = poppler_path

        # Configure Gemini
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel("models/gemini-2.0-flash")

    def convert_pdf_to_images(self, pdf_bytes: bytes) -> List[Image.Image]:
        """
        Convert PDF bytes to list of PIL Images using pdf2image.
        Higher DPI (400) for better text recognition.
        """
        if convert_from_bytes is None:
            raise ImportError("pdf2image is not installed.")

        try:
            images = convert_from_bytes(
                pdf_bytes,
                dpi=400,  # Increased from 300 for better quality
                fmt="png",
                poppler_path=self.poppler_path
            )
            return images
        except Exception as e:
            raise Exception(f"PDF conversion failed: {e}. Check Poppler path.")

    def enhance_image_for_ocr(self, image: Image.Image) -> Image.Image:
        """
        Grayscale -> Contrast -> Threshold to improve OCR accuracy.
        """
        img = ImageOps.grayscale(image)

        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)

        # Binarize (may be a bit aggressive for some headers; kept as-is)
        img = img.point(lambda x: 0 if x < 140 else 255, "1")
        return img

    def enhance_image_for_llm(self, image: Image.Image) -> Image.Image:
        """
        Enhance image for LLM processing (without binarization).
        Keeps color information but improves contrast and sharpness.
        """
        from PIL import ImageFilter

        # Enhance contrast (moderate)
        enhancer = ImageEnhance.Contrast(image)
        img = enhancer.enhance(1.3)

        # Enhance sharpness
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(1.5)

        # Enhance brightness slightly
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.05)

        return img

    def get_crop_candidates(self, width: int, height: int) -> List[Dict[str, int]]:
        """
        Generate multiple crop boxes to try.
        Focus is on top crop variance to avoid cutting the first row or keeping PII.
        More conservative margins to ensure all data is captured.
        """
        candidates = []
        # More conservative top ratios to avoid cutting off first transaction
        ratios = [0.08, 0.10, 0.12, 0.15]

        # Slightly more conservative margins on sides
        left = int(width * 0.03)
        right = int(width * 0.97)
        # More bottom area to capture all data
        bottom = int(height * 0.95)

        for r in ratios:
            top = int(height * r)
            candidates.append({"left": left, "top": top, "right": right, "bottom": bottom, "ratio": r})

        return candidates

    def find_best_crop(self, image: Image.Image) -> Image.Image:
        """
        Try multiple crops, run quick OCR on each, and pick the one
        that captures the most 'Date' patterns (MM/DD) in the left column.
        Use that crop for the final LLM extraction.
        Returns an enhanced image for better LLM recognition.
        """
        w, h = image.size
        candidates = self.get_crop_candidates(w, h)

        best_crop = None
        max_score = -1

        check_img = self.enhance_image_for_ocr(image)

        for attempt in candidates:
            c_img = check_img.crop((
                attempt["left"], attempt["top"],
                attempt["right"], attempt["bottom"]
            ))

            try:
                text = pytesseract.image_to_string(c_img, lang="eng", config="--psm 6")
            except Exception:
                text = ""

            # Count date patterns (MM/DD format)
            matches = re.findall(r"^\s*\d{1,2}/\d{1,2}", text, re.MULTILINE)
            score = len(matches)

            if score > max_score:
                max_score = score
                best_crop = attempt
            elif score == max_score:
                # Prefer smaller top crop (more content preserved)
                if best_crop and attempt["ratio"] < best_crop["ratio"]:
                    best_crop = attempt

        # Fallback with more conservative crop if no dates found
        if best_crop is None or max_score == 0:
            top = int(h * 0.10)  # More conservative default
            left = int(w * 0.03)
            right = int(w * 0.97)
            bottom = int(h * 0.95)
            cropped = image.crop((left, top, right, bottom))
        else:
            cropped = image.crop((
                best_crop["left"], best_crop["top"],
                best_crop["right"], best_crop["bottom"]
            ))

        # Apply LLM-optimized enhancement (improves contrast without binarization)
        final_img = self.enhance_image_for_llm(cropped)
        return final_img

    # ----------------------------
    # Period extraction
    # ----------------------------
    def extract_period(self, page1_image: Image.Image) -> Optional[Dict[str, datetime.date]]:
        """
        Extract statement period from Page 1 using Gemini Vision (Image-based).
        This is much more robust than OCR + Regex for varied formats.
        """
        # Crop header area (Expanded to Top 50% to ensure we catch the date)
        w, h = page1_image.size
        header_crop = page1_image.crop((0, 0, w, int(h * 0.50)))

        # 1. Try Gemini Vision (Most Accurate)
        if self.model:
            prompt = """
            この画像はクレジットカード明細書の1ページ目（ヘッダー部分）です。
            「ご利用期間(Statement Period)」または「明細書作成対象期間」の日付範囲を探して抽出してください。
            
            レスポンスは以下のJSON形式のみを返してください:
            {
                "start_date": "YYYY/MM/DD",
                "end_date": "YYYY/MM/DD"
            }
            
            注意事項:
            - 日付は必ず西暦(YYYY)に変換してください。 (例: 24/01/01 -> 2024/01/01)
            - 期間が見つからない場合、単一に記載されている「作成日」「請求日」などの日付があれば、それを end_date とし、start_date はその1ヶ月前を推測して入れてください。
            - 形式が特定できない場合は null を入れてください。
            """
            try:
                response = self.model.generate_content(
                    [prompt, header_crop],
                    generation_config={"response_mime_type": "application/json"}
                )
                cleaned = response.text.replace("```json", "").replace("```", "").strip()
                data = json.loads(cleaned)
                
                s_str = data.get("start_date")
                e_str = data.get("end_date")
                
                if s_str and e_str:
                    try:
                        s_date = datetime.datetime.strptime(s_str, "%Y/%m/%d").date()
                        e_date = datetime.datetime.strptime(e_str, "%Y/%m/%d").date()
                        return {"start": s_date, "end": e_date}
                    except ValueError:
                        pass
            except Exception as e:
                print(f"Gemini Vision Extraction Failed: {e}")
                # Fallthrough to legacy OCR method if LLM fails

        # 2. Legacy OCR Fallback (Original Logic + Enhanced Regex)
        print("Falling back to OCR for period extraction...")
        img_oa = self.enhance_image_for_ocr(header_crop)
        text = pytesseract.image_to_string(img_oa, lang="jpn+eng")
        
        dates = []
        # Support: 2024/01/01, 2024-01-01, 2024年1月1日, 2024.01.01, 24/01/01
        patterns = [
            r"(20\d{2})[/\-年.]\s?(\d{1,2})[/\-月.]\s?(\d{1,2})",  # 2024/01/01
            r"(\d{2})[/\-.]\s?(\d{1,2})[/\-.]\s?(\d{1,2})"         # 24/01/01
        ]
        
        for pat in patterns:
            matches = re.findall(pat, text)
            for m in matches:
                try:
                    y_str, m_str, d_str = m
                    
                    # Year correction for 2-digit year
                    if len(y_str) == 2:
                        y_val = 2000 + int(y_str)
                    else:
                        y_val = int(y_str)
                        
                    d_obj = datetime.date(y_val, int(m_str), int(d_str))
                    dates.append(d_obj)
                except:
                    pass
        
        dates = sorted(list(set(dates)))
        
        # Heuristic: If we found dates, assume the period is the range encompassed
        if len(dates) >= 2:
            return {"start": dates[0], "end": dates[-1]}
        elif len(dates) == 1:
            # If only one date found, assume it's the statement date (end)
            end = dates[0]
            start = end - datetime.timedelta(days=30) # Rough guess
            return {"start": start, "end": end}
            
        return None

    # ----------------------------
    # Compatibility aliases
    # ----------------------------
    def extract_statement_period(self, page1_image: Image.Image) -> Optional[Dict[str, datetime.date]]:
        return self.extract_period(page1_image)

    # ----------------------------
    # LLM Transaction Extraction
    # ----------------------------
    def process_page_with_llm(self, image: Image.Image, use_crop: bool = False) -> str:
        """
        Extract transactions using Gemini LLM.
        Args:
            image: PIL Image to process
            use_crop: If True, apply cropping. If False, use full image (recommended)
        """
        if not self.model:
            raise ValueError("Gemini API Key is missing.")

        # Optionally apply enhancement without aggressive cropping
        if use_crop:
            processed_img = self.find_best_crop(image)
        else:
            # Just enhance the full image for better readability
            processed_img = self.enhance_image_for_llm(image)

        # Improved prompt for Japanese Amex Statement
        prompt = """
あなたはクレジットカード明細の読み取りエキスパートです。
この画像はアメリカン・エキスプレス（Amex）のクレジットカード利用明細です。

画像内のすべての取引明細（利用履歴）を抽出してください。

## 抽出項目:
1. date: 利用日（MM/DD形式、例: 6/25, 7/03）
2. description: ご利用店名・ご利用先（店舗名、サービス名）
3. amount: 金額（数字のみ）

## 重要ルール:
- 明細表の各行から「日付」「店舗名」「金額」を抽出
- 日付形式: 「6/25」「7/03」「12/15」など
- 金額が「1,234-」のように末尾にマイナス記号がある場合は、マイナス値（返金）
- ヘッダー行（ご利用日、ご利用店名など）は除外
- 合計行、小計行は除外
- 「ご請求金額」「お支払い金額」などの合計は除外

## 出力形式（JSON配列）:
[
  {"date": "6/25", "description": "AMAZON.CO.JP", "amount": 1500},
  {"date": "7/03", "description": "東京電力EP", "amount": 8500}
]

画像に取引明細が見つからない場合は空配列 [] を返してください。
"""

        try:
            response = self.model.generate_content(
                [prompt, processed_img],
                generation_config={"response_mime_type": "application/json"}
            )
            return response.text
        except Exception as e:
            print(f"LLM Error: {e}")
            return "[]"

    def process_full_page_with_llm(self, image: Image.Image) -> str:
        """
        Process full page without cropping - recommended for better accuracy.
        """
        return self.process_page_with_llm(image, use_crop=False)

    def parse_llm_response(self, response_text: str, start_date: Optional[datetime.date] = None, end_date: Optional[datetime.date] = None) -> List[Dict[str, Any]]:
        """
        Parse JSON from LLM and apply date correction (Year calculation).
        """
        try:
            cleaned = response_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(cleaned)
        except Exception as e:
            print(f"JSON Parse Error: {e}")
            return []

        # Ensure data is a list
        if not isinstance(data, list):
            print(f"Unexpected data format: {type(data)}")
            return []

        final_list = []
        for item in data:
            if not isinstance(item, dict):
                continue

            raw_date = str(item.get("date", "")).strip()
            desc = str(item.get("description", "")).strip()
            amount_val = item.get("amount")

            # Skip records without date or amount (description can be empty but logged)
            if not raw_date or amount_val is None:
                continue

            # If description is empty, use placeholder but still include the record
            if not desc:
                desc = ""  # Will be logged as empty in app.py
                
            # Clean Amount
            clean_amount = str(amount_val).replace(",", "").replace("¥", "").strip()
            # Handle trailing '-' for refunds (Amex style: "100-") -> "-100"
            if clean_amount.endswith("-"):
                 clean_amount = "-" + clean_amount[:-1]
            
            # Date Year Logic
            final_date = raw_date # Default fallback
            
            if start_date and end_date:
                # Try to parse MM/DD
                m = re.match(r"(\d{1,2})/(\d{1,2})", raw_date)
                if m:
                    mm = int(m.group(1))
                    dd = int(m.group(2))
                    
                    # Determine year based on period
                    # Logic: Try both years (start_date.year and end_date.year)
                    # Pick the one that makes the date fall within or closest to period
                    
                    years_to_try = {start_date.year, end_date.year}
                    candidates = []
                    for y in years_to_try:
                        try:
                            d_obj = datetime.date(y, mm, dd)
                            candidates.append(d_obj)
                        except ValueError:
                            pass # Invalid date
                    
                    best_cand = None
                    
                    # 1. Check if ANY candidate is strictly within period
                    in_range = [c for c in candidates if start_date <= c <= end_date]
                    if in_range:
                        best_cand = in_range[0]
                    else:
                        # 2. If none, pick closest
                        if candidates:
                            def dist_to_period(d, s, e):
                                if s <= d <= e: return 0
                                return min(abs((d - s).days), abs((d - e).days))
                            
                            best_cand = min(candidates, key=lambda x: dist_to_period(x, start_date, end_date))
                    
                    if best_cand:
                        final_date = best_cand.strftime("%Y/%m/%d")
            
            final_list.append({
                "date": final_date,
                "description": desc,
                "amount": clean_amount
            })
            
        return final_list
