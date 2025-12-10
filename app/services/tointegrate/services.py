import cv2
import pytesseract
import numpy as np
import logging
import os
from dotenv import load_dotenv

from PIL import Image # Pillow is often used with PyTesseract
import json # To store structured output
import subprocess
import google.generativeai as genai

load_dotenv()
# Set your API key
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY) 

TESSERACT_CONFIG = r'--oem 3 --psm 6'


def load_image(image_path: str):
    """
    Loads an image from the specified path.
    Handles potential errors during image loading.
    """
    if not os.path.exists(image_path):
        logging.error(f"Image not found at: {image_path}")
        raise FileNotFoundError(f"Image not found at: {image_path}")

    img = cv2.imread(image_path)
    if img is None:
        logging.error(f"Could not load image from: {image_path}. Check file format or corruption.")
        raise IOError(f"Could not load image from: {image_path}")

    return img

def preprocess_image_for_ocr(img: np.ndarray):
    """
    Applies a series of image preprocessing steps to enhance OCR accuracy.

    Args:
        img (np.ndarray): The input image (OpenCV format).

    Returns:
        np.ndarray: The preprocessed image.
    """
    img = cv2.imdecode(img, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    logging.info("Converted image to grayscale.")

    h, w = gray.shape
    if h < 500 or w < 500: # Example: if image is too small, upscale it
        scale_factor = 1.5
        gray = cv2.resize(gray, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
        logging.info(f"Rescaled image by factor {scale_factor}.")

    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    logging.info("Applied Otsu's thresholding.")

    return thresh

def perform_ocr_with_boxes(image: np.ndarray):
    """
    Performs OCR on the given image using PyTesseract and returns text
    along with its bounding box locations.

    Returns:
        list of dict: A list where each dictionary represents a detected word
                      and contains 'text', 'left', 'top', 'width', 'height'.
    """
    try:
        # Get bounding box data. 'image_to_data' returns a Pandas-like DataFrame structure.
        # output_type=Output.DICT makes it a dictionary of lists.
        # This includes word-level bounding box information.
        data = pytesseract.image_to_data(image, config=TESSERACT_CONFIG, output_type=pytesseract.Output.DICT)

        extracted_words_with_boxes = []
        n_boxes = len(data['text'])

        for i in range(n_boxes):
            text = data['text'][i]
            # Tesseract can return empty strings or low confidence results.
            # Filter out non-empty strings and potentially low-confidence ones.
            # Confidence is from 0 to 100. A threshold of 60-70 is often good.
            confidence = int(data['conf'][i])

            if text.strip() and confidence > 60: # Filter out empty strings and low confidence
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

        logging.info("OCR completed with bounding box information.")
        return extracted_words_with_boxes
    except pytesseract.TesseractNotFoundError:
        logging.error("Tesseract is not installed or not found in your PATH. Please install Tesseract OCR or specify the path to its executable.")
        return []
    except Exception as e:
        logging.error(f"An error occurred during OCR with boxes: {e}")
        return []

# def visualize_boxes(img: np.ndarray, boxes: list):
#     """
#     Draws bounding boxes and text on the original image for visualization.
#     """
#     img_copy = img.copy()
#     for box in boxes:
#         x, y, w, h = box['left'], box['top'], box['width'], box['height']
#         text = box['text']

#         # Draw rectangle
#         cv2.rectangle(img_copy, (x, y), (x + w, y + h), (0, 255, 0), 2) # Green rectangle

#         # Put text (optional, but good for debugging)
#         cv2.putText(img_copy, text, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1) # Red text above box

#     # Save or display the image (for development/debugging)
#     output_dir = "visualizations"
#     os.makedirs(output_dir, exist_ok=True)
#     base_name = os.path.basename(image_path)
#     name, ext = os.path.splitext(base_name)
#     output_path = os.path.join(output_dir, f"{name}_boxed{ext}")
#     cv2.imwrite(output_path, img_copy)
#     logging.info(f"Visualized image with boxes saved to: {output_path}")

#     # If running in an environment that supports imshow (e.g., local PC, not Colab without display setup)
#     # cv2.imshow("Image with Bounding Boxes", img_copy)
#     # cv2.waitKey(0)
#     # cv2.destroyAllWindows()

def process(img: str):

    try:
        # img = load_image(image_path)

        # Preprocess image
        processed_img = preprocess_image_for_ocr(img)

        # Perform OCR with bounding boxes
        extracted_data = perform_ocr_with_boxes(processed_img)

        collected_data = ""

        if extracted_data:
            # print("\n--- Extracted Text with Location ---")
            for item in extracted_data:
                # print(f"Text: '{item['text']}' | Left: {item['left']}, Top: {item['top']}, Width: {item['width']}, Height: {item['height']}, Confidence: {item['confidence']}")
                collected_data +=f"Text: '{item['text']}' | Left: {item['left']}, Top: {item['top']}, Width: {item['width']}, Height: {item['height']}, Confidence: {item['confidence']} \n"

            # # Optionally, save the structured data as JSON
            # output_dir = "extracted_data"
            # os.makedirs(output_dir, exist_ok=True)
            # base_name = os.path.basename(image_path)
            # name, ext = os.path.splitext(base_name)
            # json_output_path = os.path.join(output_dir, f"{name}_ocr_data.json")
            # with open(json_output_path, 'w', encoding='utf-8') as f:
            #     json.dump(extracted_data, f, ensure_ascii=False, indent=4)
            # logging.info(f"Extracted OCR data saved to: {json_output_path}")

            # Strategy 1: Simple List of Text and Coordinates
            llm_prompt_simple = "Here is a list of detected words from an invoice image, along with their bounding box coordinates (left, top, width, height):\n"
            for item in extracted_data:
                llm_prompt_simple += f"- '{item['text']}' at ({item['left']}, {item['top']}, {item['width']}, {item['height']})\n"
            llm_prompt_simple += "\nBased on this information, please extract the following details: Invoice Number, Date, Total Amount, Vendor Name, and Line Items (Description, Quantity, Unit Price, Discount, Total for each)."

            sorted_words = sorted(extracted_data, key=lambda k: (k['top'], k['left']))

            lines = []
            current_line_y_threshold = 10 # Pixels threshold to consider words on the same line
            if sorted_words:
                current_line = [sorted_words[0]]
                for i in range(1, len(sorted_words)):
                    # If the current word's top is close to the previous word's top, add to the current line
                    if abs(sorted_words[i]['top'] - current_line[-1]['top']) < current_line_y_threshold:
                        current_line.append(sorted_words[i])
                    else:
                        lines.append(current_line)
                        current_line = [sorted_words[i]]
                lines.append(current_line) # Add the last line

            llm_prompt_lines = "Here is the content of an invoice, organized by lines, with each word and its coordinates:\n"
            for line_idx, line in enumerate(lines):
                # Sort words within a line by their x-coordinate
                line_text = " ".join([word['text'] for word in sorted(line, key=lambda k: k['left'])])

                # You can also include line-level bounding boxes by calculating min/max x,y for the line
                min_x = min(word['left'] for word in line)
                min_y = min(word['top'] for word in line)
                max_x = max(word['left'] + word['width'] for word in line)
                max_y = max(word['top'] + word['height'] for word in line)

                llm_prompt_lines += f"Line {line_idx + 1} (bbox: {min_x},{min_y},{max_x-min_x},{max_y-min_y}): '{line_text}'\n"


        else:
        
            print("\n--- No text extracted or an error occurred. ---")

        return collected_data

    except (FileNotFoundError, IOError) as e:
        print(f"Error: {e}")
    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)


def master_func(np_arr):

    # img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    ocr_text = process(np_arr)


    # 2. Prompt for Ollama
    prompt = f"""
                You are given OCR extracted text from a sales invoice.
                Extract it into structured JSON with the below format. if calculations are not correct think and fix, OCR might not captured decimal points:

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
                {ocr_text}

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
            return json_response  # Return the dictionary
        

        except json.JSONDecodeError as e:
            # print(f"Could not parse response as JSON: {e}")
            # print("Raw response text:")
            # print(text_response)
            print(f"Could not parse response as JSON: {e}")
            print("Raw response text (the one that caused the error):")
            print(repr(text_response))

    else:
        print("Failed to get a valid response from the model.")


