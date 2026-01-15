"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Spotify OAuth
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = ""
    
    # Gemini AI
    gemini_api_key: str = ""
    
    # Firebase
    firebase_credentials_path: str = ""  # Path to service account JSON
    firebase_project_id: str = ""
    encryption_key: str = ""  # Fernet key for token encryption
    
    # Subscription (free tier)
    subscription_duration_days: int = 365  # 1 year
    
    # AWS SES Email
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-south-1"  # Mumbai region
    ses_from_email: str = ""
    ses_from_name: str = "Spotify Organizer"
    
    # App Settings
    # NOTE: secret_key MUST be changed in production
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    secret_key: str = "development-secret-key-change-in-production"
    frontend_url: str = ""
    backend_url: str = ""
    
    def validate_production_secret(self) -> bool:
        """Validate that production is not using the default secret key."""
        if "development" in self.secret_key.lower():
            return False
        if len(self.secret_key) < 32:
            return False
        return True
    
    # Processing Limits
    max_liked_songs: int = 1000
    batch_size: int = 50
    
    # Rate Limiting (for FastAPI endpoints)
    rate_limit_requests: int = 10
    rate_limit_window: int = 60  # seconds
    
    # Spotify API Rate Limiting
    # Conservative limits to stay within Spotify's rolling 30-second window
    spotify_read_limit: int = 80      # READ requests per 30 seconds
    spotify_write_limit: int = 30     # WRITE requests per 30 seconds
    spotify_batch_limit: int = 20     # BATCH requests per 30 seconds
    
    # User Processing Concurrency
    max_concurrent_users: int = 5     # Max users processing simultaneously
    inter_user_delay: float = 5.0     # Seconds to wait between starting users
    
    # Job Queue Settings
    scan_stagger_seconds: float = 30  # Seconds between scheduled scan starts
    job_max_retries: int = 3          # Max retries for failed jobs
    job_stagger_delay: float = 30     # Delay between job executions
    
    # User Limits (Free tier - limited users)
    max_subscribers: int = 24         # Maximum active users allowed
    
    # Background Scheduler
    scan_hour_utc: int = 2  # Run daily scans at 2 AM UTC
    expiry_check_hour_utc: int = 10  # Run expiry checks at 10 AM UTC
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

