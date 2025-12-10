import cv2
import pytesseract
import numpy as np
import logging
import os
import json
from PIL import Image
import google.generativeai as genai
from typing import Optional, Dict, Any

from app.config import settings

# Configure Google AI if API key is provided
if settings.google_api_key:
    genai.configure(api_key=settings.google_api_key)

TESSERACT_CONFIG = r'--oem 3 --psm 6'

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def preprocess_image_for_ocr(file_bytes: bytes) -> np.ndarray:
    """
    Applies image preprocessing steps to enhance OCR accuracy.
    
    Args:
        file_bytes: Raw file bytes
        
    Returns:
        np.ndarray: The preprocessed image.
    """
    try:
        # Convert bytes to numpy array
        np_arr = np.frombuffer(file_bytes, np.uint8)
        
        # Decode image
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image")
            
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        logger.info("Converted image to grayscale.")

        # Resize if image is too small
        h, w = gray.shape
        if h < 500 or w < 500:
            scale_factor = 1.5
            gray = cv2.resize(gray, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
            logger.info(f"Rescaled image by factor {scale_factor}.")

        # Apply Otsu's thresholding
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        logger.info("Applied Otsu's thresholding.")

        return thresh
    except Exception as e:
        logger.error(f"Error preprocessing image: {e}")
        raise


def perform_ocr_with_boxes(image: np.ndarray) -> list:
    """
    Performs OCR on the given image using PyTesseract and returns text
    along with bounding box locations.
    
    Returns:
        list of dict: A list of detected words with bounding box info.
    """
    try:
        data = pytesseract.image_to_data(image, config=TESSERACT_CONFIG, output_type=pytesseract.Output.DICT)

        extracted_words_with_boxes = []
        n_boxes = len(data['text'])

        for i in range(n_boxes):
            text = data['text'][i]
            confidence = int(data['conf'][i])

            if text.strip() and confidence > 60:  # Filter out empty strings and low confidence
                x = data['left'][i]
                y = data['top'][i]
                w = data['width'][i]
                h = data['height'][i]

                extracted_words_with_boxes.append({
                    'text': text,
                    'left': x,
                    'top': y,
                    'width': w,
                    'height': h,
                    'confidence': confidence
                })

        logger.info("OCR completed with bounding box information.")
        return extracted_words_with_boxes
        
    except pytesseract.TesseractNotFoundError:
        logger.error("Tesseract is not installed or not found in your PATH.")
        return []
    except Exception as e:
        logger.error(f"An error occurred during OCR with boxes: {e}")
        return []


def extract_structured_data_with_ai(ocr_data: list) -> Optional[Dict[str, Any]]:
    """
    Uses Google Gemini AI to extract structured invoice data from OCR results.
    
    Args:
        ocr_data: List of OCR results with bounding boxes
        
    Returns:
        Dict with structured invoice data or None if processing fails
    """
    if not settings.google_api_key:
        logger.warning("Google API key not configured, skipping AI processing")
        return None
        
    if not ocr_data:
        logger.warning("No OCR data provided")
        return None
        
    try:
        # Build OCR text string
        collected_data = ""
        for item in ocr_data:
            collected_data += f"Text: '{item['text']}' | Left: {item['left']}, Top: {item['top']}, Width: {item['width']}, Height: {item['height']}, Confidence: {item['confidence']} \n"

        # Create prompt for AI
        prompt = f"""
        You are given OCR extracted text from a sales invoice.
        Extract it into structured JSON with the below format. If calculations are not correct think and fix, OCR might not captured decimal points:

        {{
            "company_registration_number": "", 
            "company_capital": "", 
            "vat_number": "", 
            "invoice_number": "",
            "invoice_date": "", 
            "customer_address": "",
            "customer_telephone": "",
            "customer_financial_registration_number": "",
            "salesman": "",
            "delivery_address": "",
            "company_address": "",
            "currency": "",
            "items": [
                {{
                    "description": "", 
                    "quantity": 0, 
                    "unit_price": 0,
                    "discount": 0,
                    "net_amount": 0, 
                    "vat_rate": 0, 
                    "vat_amount": 0,
                    "total": 0, 
                    "calculation_check": false
                }}
            ], 
            "totals": {{
                "gross_total": 0, 
                "net_before_vat": 0, 
                "vat_amount": 0,
                "net_after_vat": 0,
                "calculation_check": false
            }}
        }}

        Also include "calculation_check" boolean fields inside each item and totals:
        - item.calculation_check is true if quantity × unit_price == net_amount AND net_amount × vat_rate == vat_amount AND net_amount + vat_amount == total
        - totals.calculation_check is true if sum of net_amounts == gross_total AND gross_total + totals.vat_amount == totals.net_after_vat

        OCR TEXT:
        {collected_data}

        Return only valid JSON.
        """

        # Call the Gemini Pro model
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)

        # Check for a valid response
        if response and response.candidates and response.candidates[0].content.parts:
            text_response = response.candidates[0].content.parts[0].text
            
            # Try to parse the text as JSON
            try:
                # Remove the markdown code fences and surrounding quotes/whitespace
                cleaned_response = text_response.strip().removeprefix('```json\n').removesuffix('\n```')
                json_response = json.loads(cleaned_response)
                return json_response
                
            except json.JSONDecodeError as e:
                logger.error(f"Could not parse AI response as JSON: {e}")
                logger.debug(f"Raw response text: {repr(text_response)}")
                return None
        else:
            logger.error("Failed to get a valid response from the AI model.")
            return None
            
    except Exception as e:
        logger.error(f"Error in AI processing: {e}")
        return None


def process_invoice_image(file_bytes: bytes) -> Dict[str, Any]:
    """
    Main function to process an invoice image and extract structured data.
    
    Args:
        file_bytes: Raw file bytes of the invoice image
        
    Returns:
        Dict with processing results including OCR data and structured extraction
    """
    try:
        # Preprocess image
        processed_img = preprocess_image_for_ocr(file_bytes)
        
        # Perform OCR
        extracted_data = perform_ocr_with_boxes(processed_img)
        
        # Extract structured data using AI
        structured_data = None
        if extracted_data:
            structured_data = extract_structured_data_with_ai(extracted_data)
        
        return {
            "success": True,
            "ocr_data": extracted_data,
            "structured_data": structured_data,
            "total_words_extracted": len(extracted_data) if extracted_data else 0
        }
        
    except Exception as e:
        logger.error(f"Error processing invoice image: {e}")
        return {
            "success": False,
            "error": str(e),
            "ocr_data": [],
            "structured_data": None,
            "total_words_extracted": 0
        }