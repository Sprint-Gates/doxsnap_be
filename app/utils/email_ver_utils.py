import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from secrets import token_urlsafe
from typing import Optional

# Configuration (replace with your own SMTP/email server)
SMTP_HOST = "smtp.example.com"
SMTP_PORT = 587
SMTP_USER = "your-email@example.com"
SMTP_PASSWORD = "your-email-password"
FROM_EMAIL = "no-reply@example.com"
FRONTEND_URL = "https://your-frontend.com"  # used for verification link

def generate_verification_token(length: int = 32) -> str:
    """
    Generate a secure random URL-safe token for email verification.
    """
    return token_urlsafe(length)


def send_verification_email(to_email: str, token: str, subject: Optional[str] = None):
    """
    Send an email containing the verification link to the user.
    """
    if subject is None:
        subject = "Verify your email address"

    # Build the verification link
    verification_link = f"{FRONTEND_URL}/verify-email?token={token}"

    # Create the email
    msg = MIMEMultipart()
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject

    body = f"""
    Hi,

    Thank you for signing up! Please verify your email by clicking the link below:

    {verification_link}

    This link will expire in 24 hours.

    If you did not sign up, please ignore this email.

    Best regards,
    Your App Team
    """
    msg.attach(MIMEText(body, "plain"))

    # Send the email
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()  # secure the connection
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
    except Exception as e:
        # Log the error
        print(f"Failed to send verification email to {to_email}: {e}")
        # You could also raise an exception here if desired
