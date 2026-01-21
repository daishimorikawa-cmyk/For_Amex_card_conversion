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
        """
        if convert_from_bytes is None:
            raise ImportError("pdf2image is not installed.")

        try:
            images = convert_from_bytes(
                pdf_bytes,
                dpi=300,
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

    def get_crop_candidates(self, width: int, height: int) -> List[Dict[str, int]]:
        """
        Generate multiple crop boxes to try.
        Focus is on top crop variance to avoid cutting the first row or keeping PII.
        """
        candidates = []
        ratios = [0.10, 0.13, 0.16, 0.20]

        left = int(width * 0.05)
        right = int(width * 0.95)
        bottom = int(height * 0.92)

        for r in ratios:
            top = int(height * r)
            candidates.append({"left": left, "top": top, "right": right, "bottom": bottom, "ratio": r})

        return candidates

    def find_best_crop(self, image: Image.Image) -> Image.Image:
        """
        Try multiple crops, run quick OCR on each, and pick the one
        that captures the most 'Date' patterns (MM/DD) in the left column.
        Use that crop for the final LLM extraction.
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

            matches = re.findall(r"^\s*\d{1,2}/\d{1,2}", text, re.MULTILINE)
            score = len(matches)

            if score > max_score:
                max_score = score
                best_crop = attempt
            elif score == max_score:
                if best_crop and attempt["ratio"] < best_crop["ratio"]:
                    best_crop = attempt

        if best_crop is None or max_score == 0:
            top = int(h * 0.15)
            left = int(w * 0.05)
            right = int(w * 0.95)
            bottom = int(h * 0.90)
            return image.crop((left, top, right, bottom))

        final_img = image.crop((
            best_crop["left"], best_crop["top"],
            best_crop["right"], best_crop["bottom"]
        ))
        return final_img

    # ----------------------------
    # Period extraction
    # ----------------------------
    def extract_period(self, page1_image: Image.Image) -> Optional[Dict[str, datetime.date]]:
        """
        Extract statement period from Page 1 using Gemini Vision (Image-based).
        This is much more robust than OCR + Regex for varied formats.
        """
        # Crop header area (Top 40% should contain the period)
        w, h = page1_image.size
        header_crop = page1_image.crop((0, 0, w, int(h * 0.40)))

        # 1. Try Gemini Vision (Most Accurate)
        if self.model:
            prompt = """
            この画像はクレジットカード明細書のヘッダー部分です。
            「ご利用期間(Statement Period)」または「明細書作成対象期間」の日付範囲を探して抽出してください。
            
            レスポンスは以下のJSON形式のみを返してください:
            {
                "start_date": "YYYY/MM/DD",
                "end_date": "YYYY/MM/DD"
            }
            
            注意事項:
            - 日付は必ず西暦(YYYY)に変換してください。
            - 年の記載がない場合は、明細書の日付（作成日など）から推測して補完してください。近い過去の日付が正解の可能性が高いです。
            - 見つからない場合は null を入れてください。
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

        # 2. Legacy OCR Fallback (Original Logic)
        print("Falling back to OCR for period extraction...")
        img_oa = self.enhance_image_for_ocr(header_crop)
        text = pytesseract.image_to_string(img_oa, lang="jpn+eng")
        
        # Simple Regex Hunt as last resort
        dates = []
        # Find all YYYY/MM/DD or YYYY年MM月DD日
        matches = re.findall(r"20\d{2}[/\-年]\s?\d{1,2}[/\-月]\s?\d{1,2}", text)
        for m in matches:
            t = re.sub(r"[^\d]", "", m) # 20240101
            if len(t) == 8:
                try:
                    d = datetime.date(int(t[:4]), int(t[4:6]), int(t[6:8]))
                    dates.append(d)
                except:
                    pass
        
        dates = sorted(list(set(dates)))
        if len(dates) >= 2:
            # Assume earliest and latest in the header are the period (heuristic)
            return {"start": dates[0], "end": dates[-1]}
            
        return None

    # ----------------------------
    # Compatibility aliases
    # ----------------------------
    def extract_statement_period(self, page1_image: Image.Image) -> Optional[Dict[str, datetime.date]]:
        return self.extract_period(page1_image)

    # ----------------------------
    # LLM Transaction Extraction
    # ----------------------------
    def process_page_with_llm(self, image: Image.Image) -> str:
        """
        Extract transactions using Gemini LLM.
        """
        if not self.model:
            raise ValueError("Gemini API Key is missing.")

        # Prompt tailored for Japanese Amex Statement
        prompt = """
        この画像はクレジットカードの利用明細の一部です。
        以下の情報を抽出し、JSON形式のリストで返してください。
        
        抽出項目:
        - date: 利用日 (MM/DD形式)
        - description: ご利用店名・通信欄 (店舗名など)
        - amount: 金額 (数値のみ抽出、円マークは削除。「-」が末尾にある場合はマイナスとして扱う)
        
        ルール:
        - ヘッダー行や合計行（小計、合計など）は無視してください。
        - ページ番号や「---」のような区切り線も無視してください。
        - 1行に1つの明細があるとは限りません。レイアウトを解析してください。
        - 日付が読み取れない行は無視してください。
        
        出力JSON形式:
        [
          {"date": "12/01", "description": "セブンイレブン", "amount": 1000},
          {"date": "12/05", "description": "Amazon.co.jp", "amount": 5500}
        ]
        """
        
        try:
            response = self.model.generate_content(
                [prompt, image],
                generation_config={"response_mime_type": "application/json"}
            )
            return response.text
        except Exception as e:
            # Fallback or Log
            print(f"LLM Error: {e}")
            return "[]"

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
            
        final_list = []
        for item in data:
            raw_date = item.get("date", "")
            desc = item.get("description", "")
            amount_val = item.get("amount")
            
            # Skip empty records
            if not raw_date or not desc or amount_val is None:
                continue
                
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
