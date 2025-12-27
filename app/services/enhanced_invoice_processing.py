import cv2
import pytesseract
import numpy as np
import logging
import os
import json
from PIL import Image
import google.generativeai as genai
from typing import Optional, Dict, Any, List
import re

from app.config import settings

# Configure Google AI if API key is provided
if settings.google_api_key:
    genai.configure(api_key=settings.google_api_key)

TESSERACT_CONFIG = r'--oem 3 --psm 6'

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def preprocess_image_for_ocr_enhanced(file_bytes: bytes) -> List[np.ndarray]:
    """
    Enhanced preprocessing with multiple techniques for better OCR.
    Returns multiple processed versions of the image.
    """
    try:
        # Convert bytes to numpy array
        np_arr = np.frombuffer(file_bytes, np.uint8)
        
        # Decode image
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image")
            
        processed_images = []
        
        # 1. Standard grayscale with Otsu thresholding
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        
        # Resize if needed
        if h < 500 or w < 500:
            scale_factor = 1.5
            gray = cv2.resize(gray, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
            
        _, thresh1 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        processed_images.append(thresh1)
        
        # 2. Adaptive threshold
        adaptive_thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        processed_images.append(adaptive_thresh)
        
        # 3. Morphological operations to clean up
        kernel = np.ones((1, 1), np.uint8)
        morph = cv2.morphologyEx(thresh1, cv2.MORPH_CLOSE, kernel)
        processed_images.append(morph)
        
        # 4. Denoising
        denoised = cv2.fastNlMeansDenoising(gray)
        _, thresh_denoised = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        processed_images.append(thresh_denoised)
        
        logger.info(f"Created {len(processed_images)} enhanced preprocessed images")
        return processed_images
        
    except Exception as e:
        logger.error(f"Error in enhanced preprocessing: {e}")
        raise


def perform_enhanced_ocr(images: List[np.ndarray]) -> Dict[str, Any]:
    """
    Performs OCR on multiple processed images and combines results.
    """
    try:
        all_words = []
        confidence_scores = []
        
        for i, image in enumerate(images):
            try:
                # Get word-level data
                data = pytesseract.image_to_data(image, config=TESSERACT_CONFIG, output_type=pytesseract.Output.DICT)
                
                words_from_image = []
                n_boxes = len(data['text'])
                
                for j in range(n_boxes):
                    text = data['text'][j]
                    confidence = int(data['conf'][j])
                    
                    if text.strip() and confidence > 30:  # Lower threshold for more data
                        word_info = {
                            'text': text,
                            'left': data['left'][j],
                            'top': data['top'][j],
                            'width': data['width'][j],
                            'height': data['height'][j],
                            'confidence': confidence,
                            'preprocessing_method': i
                        }
                        words_from_image.append(word_info)
                        confidence_scores.append(confidence)
                
                all_words.extend(words_from_image)
                logger.info(f"Preprocessing method {i}: extracted {len(words_from_image)} words")
                
            except Exception as e:
                logger.warning(f"OCR failed for preprocessing method {i}: {e}")
                continue
        
        # Remove duplicates based on position and text similarity
        unique_words = remove_duplicate_words(all_words)
        
        # Sort by position (top to bottom, left to right)
        sorted_words = sorted(unique_words, key=lambda k: (k['top'], k['left']))
        
        # Group into lines
        lines = group_words_into_lines(sorted_words)
        
        # Extract potential patterns
        patterns = extract_patterns_from_text(sorted_words)
        
        avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
        
        return {
            'words': sorted_words,
            'lines': lines,
            'patterns': patterns,
            'total_words': len(sorted_words),
            'average_confidence': avg_confidence,
            'unique_preprocessing_methods': len(set(w['preprocessing_method'] for w in sorted_words))
        }
        
    except Exception as e:
        logger.error(f"Enhanced OCR failed: {e}")
        return {
            'words': [],
            'lines': [],
            'patterns': {},
            'total_words': 0,
            'average_confidence': 0,
            'unique_preprocessing_methods': 0
        }


def remove_duplicate_words(words: List[Dict]) -> List[Dict]:
    """Remove duplicate words based on position and text similarity."""
    unique_words = []
    position_threshold = 15  # pixels
    
    for word in words:
        is_duplicate = False
        for existing in unique_words:
            # Check if words are in similar positions
            pos_diff = abs(word['left'] - existing['left']) + abs(word['top'] - existing['top'])
            text_similarity = word['text'].lower() == existing['text'].lower()
            
            if pos_diff < position_threshold and text_similarity:
                # Keep the word with higher confidence
                if word['confidence'] > existing['confidence']:
                    unique_words.remove(existing)
                    unique_words.append(word)
                is_duplicate = True
                break
        
        if not is_duplicate:
            unique_words.append(word)
    
    return unique_words


def group_words_into_lines(words: List[Dict]) -> List[Dict]:
    """Group words into lines based on vertical position."""
    if not words:
        return []
    
    lines = []
    current_line_threshold = 15  # pixels
    
    current_line = [words[0]]
    
    for i in range(1, len(words)):
        # If the current word's top is close to the previous word's top, add to current line
        if abs(words[i]['top'] - current_line[-1]['top']) < current_line_threshold:
            current_line.append(words[i])
        else:
            # Sort words in current line by left position
            current_line.sort(key=lambda x: x['left'])
            line_text = ' '.join([word['text'] for word in current_line])
            
            # Calculate line bounding box
            min_x = min(word['left'] for word in current_line)
            min_y = min(word['top'] for word in current_line)
            max_x = max(word['left'] + word['width'] for word in current_line)
            max_y = max(word['top'] + word['height'] for word in current_line)
            
            lines.append({
                'text': line_text,
                'words': current_line.copy(),
                'bbox': {'x': min_x, 'y': min_y, 'width': max_x - min_x, 'height': max_y - min_y},
                'avg_confidence': sum(w['confidence'] for w in current_line) / len(current_line)
            })
            
            current_line = [words[i]]
    
    # Don't forget the last line
    if current_line:
        current_line.sort(key=lambda x: x['left'])
        line_text = ' '.join([word['text'] for word in current_line])
        min_x = min(word['left'] for word in current_line)
        min_y = min(word['top'] for word in current_line)
        max_x = max(word['left'] + word['width'] for word in current_line)
        max_y = max(word['top'] + word['height'] for word in current_line)
        
        lines.append({
            'text': line_text,
            'words': current_line.copy(),
            'bbox': {'x': min_x, 'y': min_y, 'width': max_x - min_x, 'height': max_y - min_y},
            'avg_confidence': sum(w['confidence'] for w in current_line) / len(current_line)
        })
    
    return lines


def extract_patterns_from_text(words: List[Dict]) -> Dict[str, List]:
    """Extract common invoice patterns from OCR text."""
    all_text = ' '.join([word['text'] for word in words])
    patterns = {}
    
    # Date patterns
    date_patterns = [
        r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',  # DD/MM/YYYY or MM/DD/YYYY
        r'\d{2,4}[/-]\d{1,2}[/-]\d{1,2}',  # YYYY/MM/DD
        r'\d{1,2}\s+\w+\s+\d{2,4}',        # DD Month YYYY
        r'\w+\s+\d{1,2},?\s+\d{2,4}'       # Month DD, YYYY
    ]
    
    dates = []
    for pattern in date_patterns:
        dates.extend(re.findall(pattern, all_text))
    patterns['dates'] = list(set(dates))
    
    # Number patterns (potential amounts, quantities)
    number_patterns = [
        r'\d+[.,]\d{2}',          # Decimal numbers
        r'\d{1,3}(?:[.,]\d{3})*[.,]\d{2}',  # Formatted currency
        r'\d+(?:\.\d+)?%',        # Percentages
        r'\d+[.,]\d+',            # General decimals
    ]
    
    numbers = []
    for pattern in number_patterns:
        numbers.extend(re.findall(pattern, all_text))
    patterns['numbers'] = list(set(numbers))
    
    # Phone patterns
    phone_patterns = [
        r'[\+]?[1-9]?[0-9]{7,15}',          # International format
        r'\(\d{3}\)\s*\d{3}[-.\s]?\d{4}',   # (XXX) XXX-XXXX
        r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',   # XXX-XXX-XXXX
    ]
    
    phones = []
    for pattern in phone_patterns:
        phones.extend(re.findall(pattern, all_text))
    patterns['phones'] = list(set(phones))
    
    # Email patterns
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    patterns['emails'] = list(set(re.findall(email_pattern, all_text)))
    
    # VAT/Tax ID patterns
    vat_patterns = [
        r'[A-Z]{2}\d{8,12}',      # EU VAT format
        r'\d{9,15}',              # General tax numbers
        r'[A-Z]{2,4}\d{6,12}',    # Mixed format
    ]
    
    vat_numbers = []
    for pattern in vat_patterns:
        matches = re.findall(pattern, all_text)
        # Filter out numbers that are too generic
        filtered_matches = [m for m in matches if len(m) >= 8]
        vat_numbers.extend(filtered_matches)
    patterns['vat_numbers'] = list(set(vat_numbers))
    
    return patterns


def extract_with_vision_ai(file_bytes: bytes, ocr_data: Dict = None) -> Optional[Dict[str, Any]]:
    """
    Extract invoice data using Gemini's vision capabilities directly on the image.
    This provides much better accuracy than OCR-based extraction.
    """
    if not settings.google_api_key:
        logger.warning("Google API key not configured, skipping AI processing")
        return None

    try:
        import base64
        from PIL import Image
        import io

        # Prepare the image for Gemini Vision
        # Convert bytes to PIL Image to ensure proper format
        img = Image.open(io.BytesIO(file_bytes))

        # Ensure image is in RGB mode (Gemini works best with RGB)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Resize if image is too large (Gemini has limits)
        max_dimension = 4096
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        # Convert to bytes for Gemini
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG', quality=95)
        img_byte_arr = img_byte_arr.getvalue()

        # Create the prompt for vision-based extraction
        prompt = get_invoice_extraction_prompt()

        # Configure the model for vision
        generation_config = {
            "temperature": 0.1,
            "top_p": 0.8,
            "top_k": 40,
            "max_output_tokens": 8000,
        }

        model = genai.GenerativeModel(
            'gemini-2.0-flash',
            generation_config=generation_config
        )

        # Send image directly to Gemini Vision
        response = model.generate_content([
            prompt,
            {"mime_type": "image/png", "data": img_byte_arr}
        ])

        if response and response.candidates and response.candidates[0].content.parts:
            text_response = response.candidates[0].content.parts[0].text

            try:
                # Enhanced JSON cleaning
                cleaned_response = text_response.strip()

                # Remove various markdown patterns
                patterns_to_remove = [
                    (r'```json\s*', ''),
                    (r'\s*```', ''),
                    (r'^[^{]*', ''),
                    (r'}[^}]*$', '}')
                ]

                for pattern, replacement in patterns_to_remove:
                    cleaned_response = re.sub(pattern, replacement, cleaned_response, flags=re.DOTALL)

                json_response = json.loads(cleaned_response)

                # Add processing metadata
                json_response['processing_metadata'] = {
                    'extraction_method': 'vision_ai',
                    'model': 'gemini-2.0-flash',
                    'image_size': f"{img.width}x{img.height}",
                    'ocr_words_extracted': ocr_data.get('total_words', 0) if ocr_data else 0,
                    'ocr_confidence': ocr_data.get('average_confidence', 0) if ocr_data else 0
                }

                # Run post-extraction validation
                json_response = validate_line_item_calculations(json_response)

                logger.info("Vision AI extraction successful")
                return json_response

            except json.JSONDecodeError as e:
                logger.error(f"Vision AI JSON parsing failed: {e}")
                logger.debug(f"Response: {repr(cleaned_response[:500])}")
                return None
        else:
            logger.error("No valid response from Vision AI")
            return None

    except Exception as e:
        logger.error(f"Vision AI extraction failed: {e}")
        return None


def get_invoice_extraction_prompt() -> str:
    """Returns the comprehensive prompt for invoice extraction."""
    return """You are an advanced invoice processing AI with vision capabilities. Analyze this invoice image directly and extract ALL information.

============================================================
CRITICAL: ANALYZE THE IMAGE DIRECTLY
============================================================

Look at the invoice image and extract:
1. All text, numbers, dates, and amounts you can see
2. The table structure and line items
3. Headers, footers, and any logos/company information
4. Payment details, terms, and notes

============================================================
CRITICAL: LINE ITEM EXTRACTION IS YOUR TOP PRIORITY
============================================================

BEFORE extracting any other data, you MUST:
1. Identify the invoice total/grand total amount from the document
2. Find EVERY SINGLE line item in the invoice - look for rows containing:
   - Product descriptions/names
   - Quantities (numbers like 1, 2, 5, 10, etc.)
   - Unit prices
   - Line totals/amounts
3. Calculate the SUM of all line item totals you found
4. Compare this sum to the invoice grand total
5. If the sum doesn't match the total (within reasonable tolerance):
   - You are MISSING line items! Go back and search more carefully
   - Look for items that might be on separate lines
   - Check for subtotals that might actually be line items
   - Look for service charges, fees, or additional items

LINE ITEM DETECTION TIPS:
- Line items often appear in a table format
- Look for patterns: description followed by numbers (qty, price, total)
- Watch for items like "Shipping", "Handling", "Service Fee", "Delivery"
- Items might be numbered (1., 2., 3.) or have item codes
- The number of line items should account for the invoice total

CRITICAL - DISCOUNT COLUMN DETECTION:
Many invoices have a DISCOUNT column that you MUST check for carefully:
- Look for column headers like: "Discount", "Disc", "Disc%", "Disc Amt", "Remise", "Rabatt", "Descuento"
- Discount can appear as a PERCENTAGE (e.g., 10%, 5.5%, -10%) or as an AMOUNT (e.g., -50.00, 10.00)
- Discount columns often appear BETWEEN unit price and line total columns
- If the line total doesn't equal quantity × unit_price, there's likely a discount!
- Formula check: If total_line_amount < (quantity × unit_price), calculate the difference as discount
- Some invoices show discount as negative numbers, others as positive - extract the absolute value
- Per-line discounts may be different from each other - check EACH line item individually
- Also look for overall/global discounts that apply to the entire invoice

============================================================

Extract into this comprehensive JSON structure. Fill ALL fields you can identify, use null for missing data:

{
    "document_info": {
        "document_type": "",
        "invoice_number": "",
        "purchase_order_number": "",
        "reference_number": "",
        "invoice_date": "",
        "due_date": "",
        "delivery_date": "",
        "payment_terms": ""
    },
    "supplier": {
        "company_name": "",
        "company_address": "",
        "postal_code": "",
        "city": "",
        "country": "",
        "phone": "",
        "fax": "",
        "email": "",
        "website": "",
        "vat_number": "",
        "tax_id": "",
        "registration_number": "",
        "bank_account": "",
        "iban": "",
        "swift": ""
    },
    "customer": {
        "company_name": "",
        "contact_person": "",
        "address": "",
        "postal_code": "",
        "city": "",
        "country": "",
        "phone": "",
        "email": "",
        "customer_id": "",
        "vat_number": "",
        "delivery_address": ""
    },
    "financial_details": {
        "currency": "",
        "exchange_rate": 0,
        "payment_method": "",
        "bank_details": "",
        "subtotal": 0,
        "total_before_tax": 0,
        "total_tax_amount": 0,
        "total_discount": 0,
        "total_after_tax": 0,
        "amount_paid": 0,
        "amount_due": 0,
        "rounding_amount": 0
    },
    "tax_breakdown": [
        {
            "tax_type": "",
            "tax_rate": 0,
            "taxable_amount": 0,
            "tax_amount": 0
        }
    ],
    "line_items": [
        {
            "line_number": 0,
            "item_code": "",
            "description": "",
            "unit": "",
            "quantity": 0,
            "unit_price": 0,
            "discount_percent": 0,
            "discount_amount": 0,
            "amount_before_discount": 0,
            "net_amount": 0,
            "tax_rate": 0,
            "tax_amount": 0,
            "gross_amount": 0,
            "total_line_amount": 0
        }
    ],
    "additional_charges": [
        {
            "charge_type": "",
            "description": "",
            "amount": 0
        }
    ],
    "notes_and_comments": {
        "invoice_notes": "",
        "payment_instructions": "",
        "terms_and_conditions": "",
        "additional_info": ""
    },
    "document_metadata": {
        "pages": 1,
        "language": "",
        "processing_quality": ""
    },
    "validation": {
        "line_item_checks": {
            "all_quantities_valid": false,
            "all_unit_prices_valid": false,
            "all_net_amounts_correct": false,
            "all_tax_amounts_correct": false,
            "all_totals_correct": false,
            "line_items_complete": false,
            "line_item_errors": []
        },
        "completeness_check": {
            "line_items_sum": 0,
            "document_total": 0,
            "difference": 0,
            "difference_percent": 0,
            "potentially_missing_items": false,
            "estimated_missing_amount": 0,
            "completeness_notes": ""
        },
        "financial_checks": {
            "subtotal_matches_line_items": false,
            "tax_total_matches_line_items": false,
            "grand_total_matches_line_items": false,
            "discount_total_matches_line_items": false,
            "total_before_tax_correct": false,
            "total_after_tax_correct": false,
            "amount_due_correct": false,
            "financial_errors": []
        },
        "calculations_correct": false,
        "confidence_score": 0,
        "validation_summary": ""
    }
}

IMPORTANT EXTRACTION INSTRUCTIONS:
1. Extract EVERY piece of information you can see in the image
2. For amounts, handle different decimal separators (. and ,) - European invoices often use comma as decimal separator
3. Handle multiple languages common in European invoices
4. Extract tax rates even if written as percentages (e.g., "19%" or "19")
5. Pay special attention to table structures for line items
6. Look for any discount columns between price and total

CRITICAL LINE ITEM VALIDATION:
For EACH line item:
1. amount_before_discount = quantity × unit_price
2. If discount exists: discount_amount = the discount value (as positive number)
3. net_amount = amount_before_discount - discount_amount
4. tax_amount = net_amount × (tax_rate / 100)
5. total_line_amount = net_amount + tax_amount

COMPLETENESS CHECK:
- Calculate line_items_sum = sum of all line item total_line_amounts
- Compare to document_total (total_after_tax)
- If difference > 2%, set potentially_missing_items = true

Return ONLY valid JSON with no additional text or formatting."""


def extract_enhanced_structured_data_with_ai(ocr_data: Dict, patterns: Dict) -> Optional[Dict[str, Any]]:
    """
    Fallback: Enhanced AI extraction using OCR text (used when vision fails).
    """
    if not settings.google_api_key:
        logger.warning("Google API key not configured, skipping AI processing")
        return None

    if not ocr_data.get('words'):
        logger.warning("No OCR data provided")
        return None

    try:
        # Build comprehensive text representation
        lines_text = "\n".join([f"Line {i+1}: {line['text']}" for i, line in enumerate(ocr_data['lines'])])
        words_with_positions = "\n".join([
            f"'{word['text']}' at position ({word['left']}, {word['top']}) confidence: {word['confidence']}%"
            for word in ocr_data['words'][:100]  # Limit to avoid token limits
        ])

        patterns_text = "\n".join([f"{key}: {', '.join(values[:5])}" for key, values in patterns.items() if values])

        # Enhanced prompt with more fields and better instructions
        prompt = f"""
        You are an advanced invoice processing AI. Your PRIMARY TASK is to extract ALL line items and ALL information from this invoice OCR data.

        OCR LINES:
        {lines_text}

        DETECTED PATTERNS:
        {patterns_text}

        ============================================================
        CRITICAL: LINE ITEM EXTRACTION IS YOUR TOP PRIORITY
        ============================================================

        BEFORE extracting any other data, you MUST:
        1. Identify the invoice total/grand total amount from the document
        2. Find EVERY SINGLE line item in the invoice - look for rows containing:
           - Product descriptions/names
           - Quantities (numbers like 1, 2, 5, 10, etc.)
           - Unit prices
           - Line totals/amounts
        3. Calculate the SUM of all line item totals you found
        4. Compare this sum to the invoice grand total
        5. If the sum doesn't match the total (within reasonable tolerance):
           - You are MISSING line items! Go back and search more carefully
           - Look for items that might be on separate lines
           - Check for subtotals that might actually be line items
           - Look for service charges, fees, or additional items
           - Re-examine any text near amounts that might be additional items

        LINE ITEM DETECTION TIPS:
        - Line items often appear in a table format but may span multiple OCR lines
        - Look for patterns: description followed by numbers (qty, price, total)
        - Some items may have long descriptions split across lines
        - Watch for items like "Shipping", "Handling", "Service Fee", "Delivery" - these are line items too
        - Items might be numbered (1., 2., 3.) or have item codes
        - The number of line items should account for the invoice total

        CRITICAL - DISCOUNT COLUMN DETECTION:
        Many invoices have a DISCOUNT column that you MUST check for carefully:
        - Look for column headers like: "Discount", "Disc", "Disc%", "Disc Amt", "Remise", "Rabatt", "Descuento"
        - Discount can appear as a PERCENTAGE (e.g., 10%, 5.5%, -10%) or as an AMOUNT (e.g., -50.00, 10.00)
        - Discount columns often appear BETWEEN unit price and line total columns
        - If the line total doesn't equal quantity × unit_price, there's likely a discount!
        - Formula check: If total_line_amount < (quantity × unit_price), calculate the difference as discount
        - Some invoices show discount as negative numbers, others as positive - extract the absolute value
        - Per-line discounts may be different from each other - check EACH line item individually
        - Also look for overall/global discounts that apply to the entire invoice (in financial_details.total_discount)

        DO NOT PROCEED until you are confident you have found ALL line items.
        If the sum of your line items is significantly less than the invoice total,
        you have missed items - keep searching!

        ============================================================

        Extract into this comprehensive JSON structure. Fill ALL fields you can identify, use null for missing data:

        {{
            "document_info": {{
                "document_type": "",
                "invoice_number": "",
                "purchase_order_number": "",
                "reference_number": "",
                "invoice_date": "",
                "due_date": "",
                "delivery_date": "",
                "payment_terms": ""
            }},
            "supplier": {{
                "company_name": "",
                "company_address": "",
                "postal_code": "",
                "city": "",
                "country": "",
                "phone": "",
                "fax": "",
                "email": "",
                "website": "",
                "vat_number": "",
                "tax_id": "",
                "registration_number": "",
                "bank_account": "",
                "iban": "",
                "swift": ""
            }},
            "customer": {{
                "company_name": "",
                "contact_person": "",
                "address": "",
                "postal_code": "",
                "city": "",
                "country": "",
                "phone": "",
                "email": "",
                "customer_id": "",
                "vat_number": "",
                "delivery_address": ""
            }},
            "financial_details": {{
                "currency": "",
                "exchange_rate": 0,
                "payment_method": "",
                "bank_details": "",
                "subtotal": 0,
                "total_before_tax": 0,
                "total_tax_amount": 0,
                "total_discount": 0,
                "total_after_tax": 0,
                "amount_paid": 0,
                "amount_due": 0,
                "rounding_amount": 0
            }},
            "tax_breakdown": [
                {{
                    "tax_type": "",
                    "tax_rate": 0,
                    "taxable_amount": 0,
                    "tax_amount": 0
                }}
            ],
            "line_items": [
                {{
                    "line_number": 0,
                    "item_code": "",
                    "description": "",
                    "unit": "",
                    "quantity": 0,
                    "unit_price": 0,
                    "discount_percent": 0,
                    "discount_amount": 0,
                    "amount_before_discount": 0,
                    "net_amount": 0,
                    "tax_rate": 0,
                    "tax_amount": 0,
                    "gross_amount": 0,
                    "total_line_amount": 0
                }}
            ],
            "additional_charges": [
                {{
                    "charge_type": "",
                    "description": "",
                    "amount": 0
                }}
            ],
            "notes_and_comments": {{
                "invoice_notes": "",
                "payment_instructions": "",
                "terms_and_conditions": "",
                "additional_info": ""
            }},
            "document_metadata": {{
                "pages": 1,
                "language": "",
                "ocr_confidence": {ocr_data.get('average_confidence', 0)},
                "total_words_extracted": {ocr_data.get('total_words', 0)},
                "processing_quality": ""
            }},
            "validation": {{
                "line_item_checks": {{
                    "all_quantities_valid": false,
                    "all_unit_prices_valid": false,
                    "all_net_amounts_correct": false,
                    "all_tax_amounts_correct": false,
                    "all_totals_correct": false,
                    "line_items_complete": false,
                    "line_item_errors": []
                }},
                "completeness_check": {{
                    "line_items_sum": 0,
                    "document_total": 0,
                    "difference": 0,
                    "difference_percent": 0,
                    "potentially_missing_items": false,
                    "estimated_missing_amount": 0,
                    "completeness_notes": ""
                }},
                "financial_checks": {{
                    "subtotal_matches_line_items": false,
                    "tax_total_matches_line_items": false,
                    "grand_total_matches_line_items": false,
                    "discount_total_matches_line_items": false,
                    "total_before_tax_correct": false,
                    "total_after_tax_correct": false,
                    "amount_due_correct": false,
                    "financial_errors": []
                }},
                "data_quality": {{
                    "required_fields_present": false,
                    "data_consistency_check": false,
                    "currency_consistent": false,
                    "dates_valid": false
                }},
                "calculations_correct": false,
                "confidence_score": 0,
                "validation_summary": ""
            }}
        }}

        IMPORTANT EXTRACTION INSTRUCTIONS:
        1. Extract EVERY piece of information you can identify
        2. For amounts, handle different decimal separators (. and ,) - European invoices often use comma as decimal separator
        3. Handle multiple languages common in European invoices
        4. Extract tax rates even if written as percentages (e.g., "19%" or "19")
        5. Identify line items even if table structure is unclear
        6. Use context clues to identify field relationships

        CRITICAL LINE ITEM VALIDATION - YOU MUST PERFORM THESE CHECKS:
        For EACH line item, verify these calculations:
        1. amount_before_discount = quantity × unit_price (ALWAYS calculate this first)
        2. If invoice shows a discount column or discount is apparent:
           - discount_amount = the discount value from the invoice (as positive number)
           - discount_percent = (discount_amount / amount_before_discount) × 100
           - OR if percentage is given: discount_amount = amount_before_discount × (discount_percent / 100)
        3. net_amount = amount_before_discount - discount_amount (this is the discounted subtotal)
        4. tax_amount = net_amount × (tax_rate / 100)
        5. total_line_amount = net_amount + tax_amount
        6. gross_amount should equal total_line_amount

        DISCOUNT DETECTION VALIDATION:
        - If total_line_amount (from invoice) is LESS than amount_before_discount, there IS a discount
        - Calculate: implicit_discount = amount_before_discount - (total_line_amount - tax_amount)
        - If implicit_discount > 0, set discount_amount = implicit_discount
        - ALWAYS check each line item individually for discounts - they may vary per item

        If a calculation doesn't match what's on the invoice:
        - Use the values from the invoice document (OCR extracted values)
        - Record the discrepancy in line_item_errors array
        - Set the corresponding check to false

        CRITICAL FINANCIAL SUMMARY VALIDATION:
        Verify these totals against line items:
        1. subtotal = SUM of all line item net_amounts (before discounts and taxes)
        2. total_discount = SUM of all line item discount_amounts
        3. total_before_tax = subtotal - total_discount
        4. total_tax_amount = SUM of all line item tax_amounts
        5. total_after_tax = total_before_tax + total_tax_amount
        6. amount_due = total_after_tax - amount_paid

        Record any discrepancies in financial_errors array.

        CRITICAL COMPLETENESS CHECK (MUST FILL):
        In the "completeness_check" section, you MUST:
        1. Set "line_items_sum" = the actual sum of all line item total_line_amounts you extracted
        2. Set "document_total" = the total_after_tax from the invoice document
        3. Set "difference" = document_total - line_items_sum
        4. Set "difference_percent" = (difference / document_total) * 100 if document_total > 0
        5. If difference_percent > 2% (tolerance):
           - Set "potentially_missing_items" = true
           - Set "estimated_missing_amount" = the difference
           - Set "completeness_notes" = explain what might be missing (e.g., "Missing approximately X amount - check for additional line items, fees, or charges")
           - Set "line_items_complete" in line_item_checks = false
        6. If difference_percent <= 2%:
           - Set "potentially_missing_items" = false
           - Set "line_items_complete" in line_item_checks = true
           - Set "completeness_notes" = "All line items captured - totals match within tolerance"

        CONFIDENCE SCORING GUIDELINES:
        - Start at 100 points
        - Deduct 5 points for each missing required field (invoice_number, invoice_date, supplier name, total)
        - Deduct 3 points for each line item calculation error
        - Deduct 5 points for each financial summary mismatch
        - Deduct 10 points if OCR confidence is below 70%
        - Deduct 2 points for each missing optional field
        - Minimum score is 0, maximum is 100

        In validation_summary, provide a brief explanation of any issues found.

        Return ONLY valid JSON with no additional text or formatting.
        """

        # Call the Gemini Pro model with enhanced configuration
        generation_config = {
            "temperature": 0.1,  # Lower temperature for more consistent extraction
            "top_p": 0.8,
            "top_k": 40,
            "max_output_tokens": 4000,
        }
        
        model = genai.GenerativeModel(
            'gemini-2.0-flash',
            generation_config=generation_config
        )
        
        response = model.generate_content(prompt)
        
        if response and response.candidates and response.candidates[0].content.parts:
            text_response = response.candidates[0].content.parts[0].text
            
            try:
                # Enhanced JSON cleaning
                cleaned_response = text_response.strip()
                
                # Remove various markdown patterns
                patterns_to_remove = [
                    (r'```json\s*', ''),
                    (r'\s*```', ''),
                    (r'^[^{]*', ''),  # Remove text before first {
                    (r'}[^}]*$', '}')  # Remove text after last }
                ]
                
                for pattern, replacement in patterns_to_remove:
                    cleaned_response = re.sub(pattern, replacement, cleaned_response, flags=re.DOTALL)
                
                json_response = json.loads(cleaned_response)
                
                # Add processing metadata
                json_response['processing_metadata'] = {
                    'extraction_method': 'enhanced_ai',
                    'ocr_methods_used': ocr_data.get('unique_preprocessing_methods', 1),
                    'patterns_detected': len([k for k, v in patterns.items() if v]),
                    'total_ocr_words': ocr_data.get('total_words', 0),
                    'average_ocr_confidence': ocr_data.get('average_confidence', 0)
                }

                # Run post-extraction validation to verify line item calculations
                json_response = validate_line_item_calculations(json_response)

                return json_response
                
            except json.JSONDecodeError as e:
                logger.error(f"Enhanced JSON parsing failed: {e}")
                logger.debug(f"Cleaned response: {repr(cleaned_response[:500])}")
                return None
                
        else:
            logger.error("No valid response from enhanced AI model")
            return None
            
    except Exception as e:
        logger.error(f"Enhanced AI processing error: {e}")
        return None


def validate_line_item_calculations(structured_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-extraction validation of line item calculations.
    Performs independent verification of all computations.
    Returns updated structured_data with validation results.
    """
    if not structured_data:
        return structured_data

    TOLERANCE = 0.01  # Allow small floating point differences

    line_items = structured_data.get('line_items', [])
    financial_details = structured_data.get('financial_details', {})

    # Initialize validation structure if not present
    if 'validation' not in structured_data:
        structured_data['validation'] = {}

    validation = structured_data['validation']

    # Initialize line item checks
    line_item_checks = validation.get('line_item_checks', {})
    line_item_errors = []

    all_quantities_valid = True
    all_unit_prices_valid = True
    all_net_amounts_correct = True
    all_tax_amounts_correct = True
    all_totals_correct = True

    # Calculated sums for financial validation
    calc_subtotal = 0
    calc_total_discount = 0
    calc_total_tax = 0
    calc_grand_total = 0

    for idx, item in enumerate(line_items):
        line_num = item.get('line_number', idx + 1)
        quantity = float(item.get('quantity', 0) or 0)
        unit_price = float(item.get('unit_price', 0) or 0)
        discount_amount = float(item.get('discount_amount', 0) or 0)
        discount_percent = float(item.get('discount_percent', 0) or 0)
        amount_before_discount = float(item.get('amount_before_discount', 0) or 0)
        net_amount = float(item.get('net_amount', 0) or 0)
        tax_rate = float(item.get('tax_rate', 0) or 0)
        tax_amount = float(item.get('tax_amount', 0) or 0)
        total_line_amount = float(item.get('total_line_amount', 0) or 0)
        gross_amount = float(item.get('gross_amount', 0) or 0)

        # Validate quantity
        if quantity <= 0 and unit_price > 0:
            all_quantities_valid = False
            line_item_errors.append(f"Line {line_num}: Invalid quantity ({quantity})")

        # Validate unit price
        if unit_price < 0:
            all_unit_prices_valid = False
            line_item_errors.append(f"Line {line_num}: Invalid unit price ({unit_price})")

        # Calculate expected amount before discount: quantity × unit_price
        expected_before_discount = quantity * unit_price

        # Use amount_before_discount if provided, otherwise use calculated value
        if amount_before_discount == 0:
            amount_before_discount = expected_before_discount

        # Validate amount_before_discount
        if abs(expected_before_discount - amount_before_discount) > TOLERANCE and expected_before_discount > 0:
            line_item_errors.append(
                f"Line {line_num}: amount_before_discount mismatch. Expected {expected_before_discount:.2f} (qty × price), got {amount_before_discount:.2f}"
            )

        # Calculate discount if percentage is given but amount is not
        if discount_percent > 0 and discount_amount == 0:
            discount_amount = amount_before_discount * (discount_percent / 100)

        # Detect implicit discount: if total_line_amount is less than expected
        if discount_amount == 0 and total_line_amount > 0:
            expected_total_no_discount = amount_before_discount + (amount_before_discount * tax_rate / 100) if tax_rate > 0 else amount_before_discount
            if expected_total_no_discount > total_line_amount + TOLERANCE:
                # There's an implicit discount
                implicit_discount = amount_before_discount - (total_line_amount - tax_amount)
                if implicit_discount > TOLERANCE:
                    discount_amount = implicit_discount
                    line_item_errors.append(
                        f"Line {line_num}: Detected implicit discount of {implicit_discount:.2f} (not explicitly shown in invoice)"
                    )

        # Amount after discount (net_amount should equal this)
        expected_net = amount_before_discount - discount_amount

        # Validate net_amount
        if abs(expected_net - net_amount) > TOLERANCE and expected_net > 0 and net_amount > 0:
            all_net_amounts_correct = False
            line_item_errors.append(
                f"Line {line_num}: net_amount mismatch. Expected {expected_net:.2f} (before_discount - discount), got {net_amount:.2f}"
            )

        # Use the calculated net if not provided
        amount_after_discount = net_amount if net_amount > 0 else expected_net

        # Calculate expected tax amount
        if tax_rate > 0:
            expected_tax = amount_after_discount * (tax_rate / 100)
            if abs(expected_tax - tax_amount) > TOLERANCE:
                all_tax_amounts_correct = False
                line_item_errors.append(
                    f"Line {line_num}: tax_amount mismatch. Expected {expected_tax:.2f}, got {tax_amount:.2f}"
                )

        # Calculate expected total line amount
        expected_total = amount_after_discount + tax_amount
        if abs(expected_total - total_line_amount) > TOLERANCE and expected_total > 0:
            all_totals_correct = False
            line_item_errors.append(
                f"Line {line_num}: total_line_amount mismatch. Expected {expected_total:.2f}, got {total_line_amount:.2f}"
            )

        # Check gross_amount equals total_line_amount
        if gross_amount > 0 and abs(gross_amount - total_line_amount) > TOLERANCE:
            line_item_errors.append(
                f"Line {line_num}: gross_amount ({gross_amount:.2f}) doesn't match total_line_amount ({total_line_amount:.2f})"
            )

        # Accumulate for financial validation
        # subtotal should be sum of amounts before discount
        calc_subtotal += amount_before_discount if amount_before_discount > 0 else (net_amount + discount_amount)
        calc_total_discount += discount_amount
        calc_total_tax += tax_amount
        calc_grand_total += total_line_amount if total_line_amount > 0 else (amount_after_discount + tax_amount)

    # Update line item checks
    line_item_checks['all_quantities_valid'] = all_quantities_valid
    line_item_checks['all_unit_prices_valid'] = all_unit_prices_valid
    line_item_checks['all_net_amounts_correct'] = all_net_amounts_correct
    line_item_checks['all_tax_amounts_correct'] = all_tax_amounts_correct
    line_item_checks['all_totals_correct'] = all_totals_correct
    line_item_checks['line_item_errors'] = line_item_errors
    validation['line_item_checks'] = line_item_checks

    # Financial summary validation
    financial_checks = validation.get('financial_checks', {})
    financial_errors = []

    subtotal = float(financial_details.get('subtotal', 0) or 0)
    total_discount = float(financial_details.get('total_discount', 0) or 0)
    total_before_tax = float(financial_details.get('total_before_tax', 0) or 0)
    total_tax_amount = float(financial_details.get('total_tax_amount', 0) or 0)
    total_after_tax = float(financial_details.get('total_after_tax', 0) or 0)
    amount_paid = float(financial_details.get('amount_paid', 0) or 0)
    amount_due = float(financial_details.get('amount_due', 0) or 0)

    # Check subtotal matches sum of line items
    subtotal_matches = abs(calc_subtotal - subtotal) <= TOLERANCE or subtotal == 0
    if not subtotal_matches and calc_subtotal > 0:
        financial_errors.append(
            f"Subtotal mismatch: Document shows {subtotal:.2f}, line items sum to {calc_subtotal:.2f}"
        )
    financial_checks['subtotal_matches_line_items'] = subtotal_matches

    # Check tax total matches sum of line items
    tax_matches = abs(calc_total_tax - total_tax_amount) <= TOLERANCE or total_tax_amount == 0
    if not tax_matches and calc_total_tax > 0:
        financial_errors.append(
            f"Tax total mismatch: Document shows {total_tax_amount:.2f}, line items sum to {calc_total_tax:.2f}"
        )
    financial_checks['tax_total_matches_line_items'] = tax_matches

    # Check discount total matches sum of line items
    discount_matches = abs(calc_total_discount - total_discount) <= TOLERANCE or total_discount == 0
    if not discount_matches and calc_total_discount > 0:
        financial_errors.append(
            f"Discount total mismatch: Document shows {total_discount:.2f}, line items sum to {calc_total_discount:.2f}"
        )
    financial_checks['discount_total_matches_line_items'] = discount_matches

    # Check grand total matches sum of line items
    grand_total_matches = abs(calc_grand_total - total_after_tax) <= TOLERANCE or total_after_tax == 0
    if not grand_total_matches and calc_grand_total > 0:
        financial_errors.append(
            f"Grand total mismatch: Document shows {total_after_tax:.2f}, line items sum to {calc_grand_total:.2f}"
        )
    financial_checks['grand_total_matches_line_items'] = grand_total_matches

    # Check total_before_tax = subtotal - total_discount
    expected_before_tax = subtotal - total_discount
    before_tax_correct = abs(expected_before_tax - total_before_tax) <= TOLERANCE or total_before_tax == 0
    if not before_tax_correct and total_before_tax > 0:
        financial_errors.append(
            f"Total before tax error: Expected {expected_before_tax:.2f} (subtotal - discount), got {total_before_tax:.2f}"
        )
    financial_checks['total_before_tax_correct'] = before_tax_correct

    # Check total_after_tax = total_before_tax + total_tax_amount
    expected_after_tax = (total_before_tax if total_before_tax > 0 else subtotal) + total_tax_amount
    after_tax_correct = abs(expected_after_tax - total_after_tax) <= TOLERANCE or total_after_tax == 0
    if not after_tax_correct and total_after_tax > 0:
        financial_errors.append(
            f"Total after tax error: Expected {expected_after_tax:.2f}, got {total_after_tax:.2f}"
        )
    financial_checks['total_after_tax_correct'] = after_tax_correct

    # Check amount_due = total_after_tax - amount_paid
    expected_due = total_after_tax - amount_paid
    due_correct = abs(expected_due - amount_due) <= TOLERANCE or amount_due == 0
    if not due_correct and amount_due > 0:
        financial_errors.append(
            f"Amount due error: Expected {expected_due:.2f}, got {amount_due:.2f}"
        )
    financial_checks['amount_due_correct'] = due_correct

    financial_checks['financial_errors'] = financial_errors
    validation['financial_checks'] = financial_checks

    # ============================================================
    # COMPLETENESS CHECK - Detect potential missing line items
    # ============================================================
    COMPLETENESS_TOLERANCE_PERCENT = 2.0  # Allow 2% difference

    completeness_check = validation.get('completeness_check', {})

    # Calculate sum of line item totals
    line_items_sum = calc_grand_total
    document_total = total_after_tax

    # If total_after_tax is 0, try to use subtotal or amount_due
    if document_total == 0:
        document_total = subtotal if subtotal > 0 else amount_due

    difference = document_total - line_items_sum
    difference_percent = (abs(difference) / document_total * 100) if document_total > 0 else 0

    potentially_missing = difference_percent > COMPLETENESS_TOLERANCE_PERCENT and difference > 0

    completeness_check['line_items_sum'] = round(line_items_sum, 2)
    completeness_check['document_total'] = round(document_total, 2)
    completeness_check['difference'] = round(difference, 2)
    completeness_check['difference_percent'] = round(difference_percent, 2)
    completeness_check['potentially_missing_items'] = potentially_missing
    completeness_check['estimated_missing_amount'] = round(difference, 2) if potentially_missing else 0

    if potentially_missing:
        completeness_check['completeness_notes'] = (
            f"WARNING: Line items sum ({line_items_sum:.2f}) is {difference_percent:.1f}% less than "
            f"document total ({document_total:.2f}). Missing approximately {difference:.2f}. "
            f"Check for additional line items, fees, shipping, or service charges that may have been missed."
        )
        line_item_checks['line_items_complete'] = False
        # Add to financial errors for visibility
        financial_errors.append(
            f"POTENTIAL MISSING ITEMS: Line items total {line_items_sum:.2f} but document total is {document_total:.2f} "
            f"(difference: {difference:.2f}, {difference_percent:.1f}%)"
        )
        financial_checks['financial_errors'] = financial_errors
    elif difference_percent <= COMPLETENESS_TOLERANCE_PERCENT:
        completeness_check['completeness_notes'] = "All line items captured - totals match within tolerance."
        line_item_checks['line_items_complete'] = True
    else:
        # Line items sum is higher than document total (possible extra items or calculation error)
        completeness_check['completeness_notes'] = (
            f"Note: Line items sum ({line_items_sum:.2f}) exceeds document total ({document_total:.2f}) "
            f"by {abs(difference):.2f}. This may indicate duplicate items or calculation discrepancies."
        )
        line_item_checks['line_items_complete'] = True  # Not missing items, but might have extras

    validation['completeness_check'] = completeness_check
    validation['line_item_checks'] = line_item_checks

    # Overall calculations correct (including completeness)
    all_line_items_correct = (
        all_quantities_valid and all_unit_prices_valid and
        all_net_amounts_correct and all_tax_amounts_correct and
        all_totals_correct and line_item_checks.get('line_items_complete', False)
    )
    all_financials_correct = (
        subtotal_matches and tax_matches and discount_matches and
        grand_total_matches and before_tax_correct and after_tax_correct
    )
    validation['calculations_correct'] = all_line_items_correct and all_financials_correct

    # Recalculate confidence score based on validation
    base_confidence = float(validation.get('confidence_score', 80))

    # Deduct points for errors
    error_count = len(line_item_errors) + len(financial_errors)
    penalty = error_count * 3  # 3 points per error

    # Additional penalty for missing items
    if potentially_missing:
        penalty += 15  # Significant penalty for potentially missing items

    adjusted_confidence = max(0, min(100, base_confidence - penalty))
    validation['confidence_score'] = adjusted_confidence

    # Generate comprehensive validation summary
    total_errors = len(line_item_errors) + len(financial_errors)
    summary_parts = []

    if potentially_missing:
        summary_parts.append(
            f"⚠️ POTENTIAL MISSING LINE ITEMS: Document total is {document_total:.2f} but "
            f"extracted line items only sum to {line_items_sum:.2f} (missing ~{difference:.2f})"
        )

    if total_errors > 0:
        summary_parts.append(
            f"Found {total_errors} calculation issue(s): "
            f"{len(line_item_errors)} in line items, {len(financial_errors)} in financial totals."
        )

    if not summary_parts:
        validation['validation_summary'] = "All calculations verified successfully. All line items captured."
    else:
        validation['validation_summary'] = " | ".join(summary_parts)

    structured_data['validation'] = validation

    logger.info(f"Post-extraction validation complete. Errors: {total_errors}, Missing items: {potentially_missing}")

    return structured_data


def generate_address_number(db_session, company_id: int) -> str:
    """Generate sequential address number for the company."""
    from app.models import AddressBook
    from sqlalchemy import func

    # Get the max address_number for this company
    max_num = db_session.query(func.max(AddressBook.address_number)).filter(
        AddressBook.company_id == company_id
    ).scalar()

    if max_num:
        try:
            next_num = int(max_num) + 1
        except ValueError:
            next_num = 1
    else:
        next_num = 1

    return str(next_num).zfill(8)  # 8-digit format like "00000001"


def lookup_vendor_in_database(supplier_name: str, db_session=None, supplier_data: Dict = None, company_id: int = None) -> Dict[str, Any]:
    """
    Enhanced vendor lookup using Address Book (search_type='V').
    Matches on: company name (alpha_name), tax number (tax_id), registration number, email, phone.
    If no vendor is found and company_id is provided, auto-creates an Address Book entry.
    Returns vendor info if found or created.

    Args:
        supplier_name: The extracted supplier company name
        db_session: Database session
        supplier_data: Full supplier data dict from OCR extraction (optional)
        company_id: The company ID to filter vendors and auto-create if needed
    """
    if not db_session:
        return {"found": False, "vendor": None, "suggestions": [], "extracted_name": supplier_name, "match_method": None}

    try:
        from sqlalchemy import or_, func
        from app.models import AddressBook, BusinessUnit

        # Extract additional attributes from supplier_data for multi-attribute matching
        extracted_tax_number = None
        extracted_registration_number = None
        extracted_email = None
        extracted_phone = None
        extracted_address = None
        extracted_city = None
        extracted_country = None

        if supplier_data:
            extracted_tax_number = supplier_data.get("vat_number") or supplier_data.get("tax_id")
            extracted_registration_number = supplier_data.get("registration_number")
            extracted_email = supplier_data.get("email")
            extracted_phone = supplier_data.get("phone")
            extracted_address = supplier_data.get("company_address")
            extracted_city = supplier_data.get("city")
            extracted_country = supplier_data.get("country")

        vendor = None
        match_method = None

        # Build base query filtered by company and search_type='V' (Vendor)
        def get_vendor_query():
            query = db_session.query(AddressBook).filter(
                AddressBook.is_active == True,
                AddressBook.search_type == 'V'
            )
            if company_id:
                query = query.filter(AddressBook.company_id == company_id)
            return query

        # Priority 1: Match by Tax Number (VAT number) - most reliable identifier
        if extracted_tax_number and extracted_tax_number.strip():
            normalized_tax = extracted_tax_number.strip().upper().replace(" ", "").replace("-", "")
            vendors = get_vendor_query().all()
            for v in vendors:
                if v.tax_id:
                    db_tax = v.tax_id.strip().upper().replace(" ", "").replace("-", "")
                    if db_tax == normalized_tax:
                        vendor = v
                        match_method = "tax_number"
                        logger.info(f"Vendor matched by tax number: {extracted_tax_number}")
                        break

        # Priority 2: Match by Registration Number
        if not vendor and extracted_registration_number and extracted_registration_number.strip():
            normalized_reg = extracted_registration_number.strip().upper().replace(" ", "").replace("-", "")
            vendors = get_vendor_query().all()
            for v in vendors:
                if v.registration_number:
                    db_reg = v.registration_number.strip().upper().replace(" ", "").replace("-", "")
                    if db_reg == normalized_reg:
                        vendor = v
                        match_method = "registration_number"
                        logger.info(f"Vendor matched by registration number: {extracted_registration_number}")
                        break

        # Priority 3: Match by Email
        if not vendor and extracted_email and extracted_email.strip():
            query = get_vendor_query().filter(
                func.lower(AddressBook.email) == extracted_email.strip().lower()
            )
            vendor = query.first()
            if vendor:
                match_method = "email"
                logger.info(f"Vendor matched by email: {extracted_email}")

        # Priority 4: Match by Company Name (exact match, case-insensitive)
        if not vendor and supplier_name and supplier_name.strip():
            query = get_vendor_query().filter(
                AddressBook.alpha_name.ilike(supplier_name.strip())
            )
            vendor = query.first()
            if vendor:
                match_method = "company_name_exact"
                logger.info(f"Vendor matched by exact company name: {supplier_name}")

        # Priority 5: Match by Phone Number (normalized)
        if not vendor and extracted_phone and extracted_phone.strip():
            # Normalize phone: keep only digits
            normalized_phone = ''.join(filter(str.isdigit, extracted_phone))
            if len(normalized_phone) >= 7:  # Minimum reasonable phone length
                vendors = get_vendor_query().all()
                for v in vendors:
                    if v.phone_primary:
                        db_phone = ''.join(filter(str.isdigit, v.phone_primary))
                        # Match last 7+ digits (handles country code differences)
                        if len(db_phone) >= 7 and (db_phone[-7:] == normalized_phone[-7:] or db_phone == normalized_phone):
                            vendor = v
                            match_method = "phone"
                            logger.info(f"Vendor matched by phone: {extracted_phone}")
                            break

        # If no vendor found and we have company_id and supplier name, auto-create Address Book entry
        if not vendor and company_id and supplier_name and supplier_name.strip():
            try:
                # Generate address number
                address_number = generate_address_number(db_session, company_id)

                # Create Business Unit for the vendor
                bu = BusinessUnit(
                    company_id=company_id,
                    code=f"V{address_number}",
                    name=supplier_name.strip()[:100],
                    description=f"Auto-created for vendor: {supplier_name.strip()}"
                )
                db_session.add(bu)
                db_session.flush()

                # Create Address Book entry with search_type='V'
                new_vendor = AddressBook(
                    company_id=company_id,
                    address_number=address_number,
                    search_type='V',  # Vendor type
                    alpha_name=supplier_name.strip()[:100],
                    mailing_name=supplier_name.strip()[:100],
                    email=extracted_email.strip()[:255] if extracted_email else None,
                    phone_primary=extracted_phone.strip()[:30] if extracted_phone else None,  # Truncate to DB limit
                    address_line_1=extracted_address.strip()[:200] if extracted_address else None,
                    city=extracted_city.strip()[:100] if extracted_city else None,
                    country=extracted_country.strip()[:50] if extracted_country else None,
                    tax_id=extracted_tax_number.strip()[:50] if extracted_tax_number else None,
                    registration_number=extracted_registration_number.strip()[:50] if extracted_registration_number else None,
                    business_unit_id=bu.id,
                    is_active=True
                )
                db_session.add(new_vendor)
                db_session.flush()  # Get the ID without committing

                vendor = new_vendor
                match_method = "auto_created"
                logger.info(f"Auto-created vendor '{supplier_name}' in Address Book (ID: {vendor.id}) for company {company_id}")
            except Exception as create_error:
                logger.error(f"Failed to auto-create vendor in Address Book: {create_error}")
                # Continue without vendor creation

        if vendor:
            return {
                "found": True,
                "vendor": {
                    "id": vendor.id,
                    "address_book_id": vendor.id,
                    "address_number": vendor.address_number,
                    "name": vendor.alpha_name,
                    "display_name": vendor.alpha_name,
                    "email": vendor.email,
                    "phone": vendor.phone_primary,
                    "address": " ".join(filter(None, [vendor.address_line_1, vendor.city, vendor.country])),
                    "tax_number": vendor.tax_id,
                    "registration_number": vendor.registration_number
                },
                "suggestions": [],
                "extracted_name": supplier_name,
                "match_method": match_method
            }

        # No exact match found - try partial match for suggestions
        suggestions = []
        if supplier_name and supplier_name.strip():
            search_term = f"%{supplier_name.strip()}%"
            query = get_vendor_query().filter(
                AddressBook.alpha_name.ilike(search_term)
            ).limit(5)
            similar_vendors = query.all()

            suggestions = [
                {
                    "id": v.id,
                    "address_book_id": v.id,
                    "address_number": v.address_number,
                    "name": v.alpha_name,
                    "display_name": v.alpha_name
                }
                for v in similar_vendors
            ]

        return {
            "found": False,
            "vendor": None,
            "suggestions": suggestions,
            "extracted_name": supplier_name,
            "match_method": None
        }

    except Exception as e:
        logger.error(f"Vendor lookup failed: {e}")
        return {"found": False, "vendor": None, "suggestions": [], "extracted_name": supplier_name, "match_method": None}


def apply_vendor_data_to_invoice(structured_data: Dict[str, Any], vendor_data: Dict) -> Dict[str, Any]:
    """
    Apply accurate vendor data from Address Book to the invoice's supplier section.
    This replaces potentially inaccurate OCR-extracted data with verified vendor information.

    Args:
        structured_data: The invoice structured data
        vendor_data: The matched vendor data from Address Book

    Returns:
        Updated structured_data with vendor information applied
    """
    if not structured_data or not vendor_data:
        return structured_data

    if "supplier" not in structured_data:
        structured_data["supplier"] = {}

    supplier = structured_data["supplier"]

    # Apply Address Book vendor data - takes precedence over OCR data
    supplier["address_book_id"] = vendor_data.get("address_book_id") or vendor_data.get("id")
    supplier["vendor_matched"] = True

    # Only overwrite if vendor has the data (preserve OCR data if vendor data is empty)
    if vendor_data.get("display_name"):
        supplier["company_name"] = vendor_data["display_name"]

    if vendor_data.get("email"):
        supplier["email"] = vendor_data["email"]

    if vendor_data.get("phone"):
        supplier["phone"] = vendor_data["phone"]

    if vendor_data.get("address"):
        supplier["company_address"] = vendor_data["address"]

    if vendor_data.get("tax_number"):
        supplier["vat_number"] = vendor_data["tax_number"]
        supplier["tax_id"] = vendor_data["tax_number"]

    if vendor_data.get("registration_number"):
        supplier["registration_number"] = vendor_data["registration_number"]

    logger.info(f"Applied Address Book vendor data (ID: {vendor_data.get('id')}) to invoice supplier section")
    return structured_data


def process_invoice_image_enhanced(file_bytes: bytes, db_session=None, company_id: int = None) -> Dict[str, Any]:
    """
    Enhanced main function to process invoice images with comprehensive data extraction.
    Uses Vision AI as primary extraction method for better accuracy.
    Optionally checks vendor database if db_session is provided.
    If company_id is provided and vendor not found, auto-creates the vendor.
    """
    try:
        # First, try Vision AI extraction (most accurate method)
        # This sends the image directly to Gemini for analysis
        logger.info("Attempting Vision AI extraction (primary method)...")
        structured_data = extract_with_vision_ai(file_bytes)

        # Also run OCR for metadata and as fallback data source
        processed_images = preprocess_image_for_ocr_enhanced(file_bytes)
        ocr_results = perform_enhanced_ocr(processed_images)

        # If Vision AI failed, fall back to OCR-based extraction
        if not structured_data:
            logger.warning("Vision AI extraction failed, falling back to OCR-based extraction...")
            if ocr_results['words']:
                structured_data = extract_enhanced_structured_data_with_ai(
                    ocr_results,
                    ocr_results['patterns']
                )

        # Update metadata with OCR stats if we have them
        if structured_data and ocr_results:
            if 'processing_metadata' not in structured_data:
                structured_data['processing_metadata'] = {}
            structured_data['processing_metadata']['ocr_words_extracted'] = ocr_results.get('total_words', 0)
            structured_data['processing_metadata']['ocr_confidence'] = ocr_results.get('average_confidence', 0)

        # Vendor lookup if structured data contains supplier info
        # Use multi-attribute matching for better accuracy
        # If no vendor found and company_id provided, auto-create vendor
        vendor_lookup = {"found": False, "vendor": None, "suggestions": [], "extracted_name": None}
        if structured_data and structured_data.get("supplier"):
            supplier_data = structured_data["supplier"]
            supplier_name = supplier_data.get("company_name")
            if supplier_name or supplier_data:
                # Pass full supplier data for multi-attribute matching and company_id for auto-creation
                vendor_lookup = lookup_vendor_in_database(
                    supplier_name,
                    db_session,
                    supplier_data=supplier_data,
                    company_id=company_id
                )

                # If vendor found or created, apply accurate vendor data to the invoice
                # This replaces potentially inaccurate OCR data with verified database info
                if vendor_lookup.get("found") and vendor_lookup.get("vendor"):
                    structured_data = apply_vendor_data_to_invoice(
                        structured_data,
                        vendor_lookup["vendor"]
                    )
                    logger.info(f"Vendor matched via {vendor_lookup.get('match_method', 'unknown')} - applied vendor data to invoice")

        return {
            "success": True,
            "ocr_data": ocr_results,
            "structured_data": structured_data,
            "total_words_extracted": ocr_results['total_words'],
            "average_confidence": ocr_results['average_confidence'],
            "vendor_lookup": vendor_lookup,
            "enhancement_features": {
                "vision_ai_used": structured_data.get('processing_metadata', {}).get('extraction_method') == 'vision_ai' if structured_data else False,
                "multiple_preprocessing": len(processed_images),
                "pattern_recognition": len(ocr_results['patterns']),
                "line_detection": len(ocr_results['lines']),
                "duplicate_removal": True,
                "comprehensive_fields": True
            }
        }

    except Exception as e:
        logger.error(f"Enhanced invoice processing failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "ocr_data": {"words": [], "lines": [], "patterns": {}},
            "structured_data": None,
            "total_words_extracted": 0,
            "average_confidence": 0,
            "vendor_lookup": {"found": False, "vendor": None, "suggestions": [], "extracted_name": None},
            "enhancement_features": {}
        }