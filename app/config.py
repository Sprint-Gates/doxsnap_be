from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    # Database Configuration - matching your .env file
    database_url: Optional[str] = None
    db_username: Optional[str] = None
    db_password: Optional[str] = None
    db_host: str = "localhost"
    db_port: str = "5432"
    db_name: Optional[str] = None

    # Authentication
    secret_key: str = "your-secret-key-here"
    algorithm: str = "HS256"
    access_token_expire_minutes: Optional[int] = 30

    @field_validator('algorithm', mode='before')
    @classmethod
    def parse_algorithm(cls, v):
        if v is None or v == '':
            return "HS256"
        return v

    @field_validator('access_token_expire_minutes', mode='before')
    @classmethod
    def parse_token_expire(cls, v):
        if v is None or v == '':
            return 30
        return int(v)
    
    # Google AI Configuration
    google_api_key: Optional[str] = None
    
    # AWS S3 Configuration - matching your .env file
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "eu-central-1"  # Updated to match your .env
    s3_bucket: str = "doxsnap"  # Updated to match your .env
    
    # Email Configuration
    smtp_server: str = "smtp.office365.com"
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    company_support_email: str = "noreply@arabiaesim.com"
    
    @property
    def database_connection_url(self) -> str:
        """Build database URL from individual components or use direct URL"""
        # Prioritize PostgreSQL if individual components are available
        if all([self.db_username, self.db_password, self.db_host, self.db_port, self.db_name]):
            return f"postgresql://{self.db_username}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        elif self.database_url:
            return self.database_url
        else:
            return "sqlite:///./app.db"  # Fallback to SQLite
    
    class Config:
        env_file = ".env"


settings = Settings()