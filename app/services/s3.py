import boto3
import os
import json
from PIL import Image
from botocore.exceptions import ClientError
from app.config import settings
from .enhanced_invoice_processing import process_invoice_image_enhanced


def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region
    )


def process_image(file_path: str, file_bytes: bytes = None, db_session=None, company_id: int = None) -> tuple:
    """
    Process the image: resize, compress, and extract invoice data.
    Returns (processed_image_path, invoice_processing_results).
    """
    try:
        # Read file bytes if not provided
        if file_bytes is None:
            with open(file_path, 'rb') as f:
                file_bytes = f.read()

        # Process invoice data using enhanced OCR and AI (with optional vendor lookup)
        invoice_results = process_invoice_image_enhanced(file_bytes, db_session, company_id)
        
        # Standard image processing (resize, compress)
        with Image.open(file_path) as img:
            # Convert RGBA to RGB if necessary
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            
            # Resize if too large (max 1920x1920)
            max_size = (1920, 1920)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Save processed image
            processed_path = file_path.replace('.', '_processed.')
            img.save(processed_path, 'JPEG', quality=85, optimize=True)
            
            return processed_path, invoice_results
            
    except Exception as e:
        # Return basic results even if invoice processing fails
        invoice_results = {
            "success": False,
            "error": str(e),
            "ocr_data": [],
            "structured_data": None,
            "total_words_extracted": 0
        }
        
        try:
            # Still try to do basic image processing
            with Image.open(file_path) as img:
                if img.mode == 'RGBA':
                    img = img.convert('RGB')
                max_size = (1920, 1920)
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
                processed_path = file_path.replace('.', '_processed.')
                img.save(processed_path, 'JPEG', quality=85, optimize=True)
                return processed_path, invoice_results
        except Exception as fallback_error:
            print(f"Fallback image processing also failed: {fallback_error}")
            pass
            
        raise Exception(f"Error processing image: {str(e)}")


def upload_to_s3(file_path: str, filename: str) -> tuple:
    """
    Upload file to S3 and return (s3_key, s3_url)
    """
    try:
        s3_client = get_s3_client()
        s3_key = f"processed-images/{filename}"
        
        s3_client.upload_file(
            file_path,
            settings.s3_bucket,
            s3_key,
            ExtraArgs={'ContentType': 'image/jpeg'}
        )
        
        # Store S3 key instead of direct URL
        # The actual URL will be generated as a pre-signed URL when needed
        s3_url = s3_key  # Store S3 key, not direct URL
        
        return s3_key, s3_url
        
    except ClientError as e:
        raise Exception(f"Error uploading to S3: {str(e)}")
    except Exception as e:
        raise Exception(f"Error uploading file: {str(e)}")


def generate_presigned_url(s3_key: str, expiration: int = 3600) -> str:
    """
    Generate a pre-signed URL for accessing S3 objects
    """
    try:
        s3_client = get_s3_client()
        response = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': settings.s3_bucket, 'Key': s3_key},
            ExpiresIn=expiration
        )
        return response
    except Exception as e:
        print(f"Error generating pre-signed URL: {str(e)}")
        return None


def download_file_from_s3(s3_key: str) -> bytes:
    """
    Download file from S3 and return as bytes
    """
    try:
        s3_client = get_s3_client()
        response = s3_client.get_object(Bucket=settings.s3_bucket, Key=s3_key)
        return response['Body'].read()
    except ClientError as e:
        print(f"Error downloading from S3: {str(e)}")
        return None
    except Exception as e:
        print(f"Error downloading file: {str(e)}")
        return None


def delete_from_s3(s3_key: str) -> bool:
    """
    Delete file from S3
    """
    try:
        s3_client = get_s3_client()
        s3_client.delete_object(Bucket=settings.s3_bucket, Key=s3_key)
        return True
    except Exception as e:
        print(f"Error deleting from S3: {str(e)}")
        return False