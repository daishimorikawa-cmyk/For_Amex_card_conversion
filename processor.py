import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

import os
import re
import io
import json
import datetime
import pandas as pd
from PIL import Image

try:
    from pdf2image import convert_from_bytes
except ImportError:
    convert_from_bytes = None

import google.generativeai as genai


class AmexProcessor:
    def __init__(self, api_key: str | None):
        self.api_key = (api_key or "").strip()
        self.model = None

        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel("models/gemini-2.0-flash")# Cost-effective and fast

    def convert_pdf_to_images(self, pdf_bytes: bytes):
        """
        Convert PDF bytes to list of PIL Images using pdf2image + Poppler.
        """
        if convert_from_bytes is None:
            raise ImportError("pdf2image is not installed. Please install it with pip.")

        # 300dpi for better OCR
        try:
            images = convert_from_bytes(
                pdf_bytes,
                dpi=300,
                fmt="png",
                poppler_path=r"C:\poppler-25.12.0\Library\bin"
            )
            return images
        except Exception as e:
            raise Exception(
                f"PDF conversion failed: {str(e)}. "
                f"Please ensure Poppler is installed and poppler_path is correct."
            )

    def preprocess_image(self, image: Image.Image):
        """
        Crop the image to remove header/footer and keep the table area.
        Amex headers are usually at the top.
        """
        width, height = image.size

        # Crop parameters (Adjust based on trial)
        # Top 25% usually contains the header and personal info
        top_crop = int(height * 0.25)
        # Bottom 10% usually contains page numbers or footer
        bottom_crop = int(height * 0.90)

        # Side margins
        left_crop = int(width * 0.05)
        right_crop = int(width * 0.95)

        # Crop: (left, upper, right, lower)
        cropped_img = image.crop((left_crop, top_crop, right_crop, bottom_crop))
        return cropped_img

    def redact_pii(self, text: str) -> str:
        """
        Redact sensitive information using Regex
        """
        # Credit Card numbers (15-16 digits often with spaces)
        text = re.sub(r'\b(?:\d[\s-]*){13,16}\d\b', '****', text)
        # Phone numbers
        text = re.sub(r'0\d{1,4}-\d{1,4}-\d{3,4}', '****', text)
        # Email
        text = re.sub(r'[\w\.-]+@[\w\.-]+', '****', text)
        # Postal codes
        text = re.sub(r'〒?\d{3}-\d{4}', '****', text)

        return text

    def extract_period(self, page1_image: Image.Image):
        """
        Extract statement period from Page 1 (OCR -> Regex)
        Target: "YYYY年MM月DD日からYYYY年MM月DD日まで" (or similar)

        Returns:
          {
            "start": {"year":..., "month":..., "day":...},
            "end":   {"year":..., "month":..., "day":...}
          }
        or None if not found.
        """
        text = pytesseract.image_to_string(page1_image, lang='jpn+eng')

        # Match: 2024年12月21日から2025年1月20日まで
        m = re.search(
            r'(\d{4})年(\d{1,2})月(\d{1,2})日?\s*から\s*(\d{4})年(\d{1,2})月(\d{1,2})日?\s*まで',
            text
        )
        if m:
            return {
                "start": {"year": int(m.group(1)), "month": int(m.group(2)), "day": int(m.group(3))},
                "end":   {"year": int(m.group(4)), "month": int(m.group(5)), "day": int(m.group(6))},
            }

        # Some statements omit end year like "2024年12月21日から1月20日まで"
        m2 = re.search(
            r'(\d{4})年(\d{1,2})月(\d{1,2})日?\s*から\s*(\d{1,2})月(\d{1,2})日?\s*まで',
            text
        )
        if m2:
            start_year = int(m2.group(1))
            start_month = int(m2.group(2))
            end_month = int(m2.group(4))
            # If end month is smaller, it likely crosses year boundary
            end_year = start_year + (1 if end_month < start_month else 0)
            return {
                "start": {"year": start_year, "month": int(m2.group(2)), "day": int(m2.group(3))},
                "end":   {"year": end_year,   "month": int(m2.group(4)), "day": int(m2.group(5))},
            }

        return None

    def process_page_with_llm(self, text: str, year_hint: int):
        """
        Send sanitized OCR text to LLM to extract table.
        """
        if self.model is None:
            raise RuntimeError("Gemini API key is not set. Please provide Gemini API key in the UI.")

        prompt = f"""
You are a data extraction assistant.
Extract a transaction table from the following OCR text of a credit card statement.
The text might be messy and contains '****' for redacted numbers.

Target Columns:
1. Date (YYYY/MM/DD) - Use the year {year_hint} if year is missing. format: YYYY/MM/DD
2. Description - The payee name. Extract from text until the first digit of the amount appears. If no digit, leave empty.
3. Amount - The transaction amount (remove commas, currency symbols, convert to integer/number).

Rules:
- Output JSON format with key "transactions": [ {{ "date": "...", "description": "...", "amount": ... }} ]
- Ignore lines that are usually headers (like "Date Detail Amount").
- If description is empty or unintelligible, mark as "UNKNOWN".
- If amount is negative (refund), include the negative sign.
- Japanese characters are common.

OCR Text:
{text}
"""

        response = self.model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return response.text

    def parse_llm_response(self, response_text: str):
        try:
            cleaned = response_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(cleaned)
            return data.get("transactions", [])
        except Exception:
            return []
