"""Main FastAPI application for free Spotify Organizer.

Authentication Flow:
1. User signs in with Google (Firebase Auth)
2. User's account is auto-activated (up to 24 users)
3. User links Spotify account
4. Background scheduler runs daily scans
"""

import secrets
import logging
import asyncio
from typing import Optional
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel

from .config import get_settings
from .models import StatusResponse
from .spotify_service import SpotifyService
from .processing_service import ProcessingService, get_processing_service, set_processing_service
from .firebase_service import get_firebase_service
from .email_service import get_email_service
from .scheduler_service import get_scheduler_service, SchedulerService
from .rate_limiter import get_spotify_rate_limiter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
)
logger = logging.getLogger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Services (initialized in lifespan)
spotify_service: Optional[SpotifyService] = None
processing_service: Optional[ProcessingService] = None
scheduler_service: Optional[SchedulerService] = None

# Temporary state storage for OAuth flow
state_storage: dict = {}


# ============== Request/Response Models ==============

class GoogleAuthRequest(BaseModel):
    """Request to verify Google/Firebase ID token."""
    id_token: str


class GoogleAuthResponse(BaseModel):
    """Response after Google auth verification."""
    user_id: str
    email: str
    display_name: str
    subscription_status: str
    spotify_linked: bool


class SpotifyLinkRequest(BaseModel):
    """Request to initiate Spotify linking."""
    pass  # Firebase token comes from header


class SubscriptionStatusResponse(BaseModel):
    """Response with subscription details."""
    status: str
    start_date: Optional[str]
    end_date: Optional[str]
    spotify_linked: bool
    last_scan_at: Optional[str]
    total_songs_organized: int


# ============== Lifespan ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global spotify_service, processing_service, scheduler_service
    
    spotify_service = SpotifyService()
    processing_service = ProcessingService()
    set_processing_service(processing_service)  # Set as global singleton
    scheduler_service = get_scheduler_service()
    
    # Start background scheduler and job queue (now async)
    await scheduler_service.start()
    
    logger.info("Application started with scheduler and job queue")
    yield
    
    # Cleanup
    await spotify_service.close()
    await processing_service.close()
    await scheduler_service.close()
    logger.info("Application shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title="Spotify Organizer API",
        description="AI-powered Spotify Liked Songs organizer with subscription support",
        version="2.0.0",
        lifespan=lifespan
    )
    
    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_custom_handler)
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url, "http://localhost:5173", "http://127.0.0.1:5173", "https://spotify-organiser.web.app", "https://spotify-organiser.firebaseapp.com"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    return app


def rate_limit_custom_handler(request: Request, exc: RateLimitExceeded):
    """
    Custom handler for rate limit exceeded errors.
    Returns a clean JSON response with retry_after estimate.
    """
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": "You are doing that too fast. Please try again later.",
            "retry_after": 60  # Default 60s cooldown
        }
    )


app = create_app()


# ============== Dependencies ==============

def get_spotify() -> SpotifyService:
    """Dependency to get Spotify service."""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Service not initialized")
    return spotify_service


def get_processing() -> ProcessingService:
    """Dependency to get Processing service (singleton)."""
    return get_processing_service()


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """
    Dependency to verify Firebase token and get current user.
    
    Expects: Authorization: Bearer <firebase_id_token>
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    token = authorization[7:]  # Remove "Bearer "
    
    firebase = get_firebase_service()
    
    try:
        decoded = await firebase.verify_id_token(token)
        user = await firebase.get_or_create_user(
            firebase_uid=decoded['uid'],
            email=decoded.get('email', ''),
            display_name=decoded.get('name', '')
        )
        user['uid'] = decoded['uid']
        return user
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


async def require_subscription(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency that requires an active subscription."""
    if current_user.get('subscription_status') != 'active':
        raise HTTPException(status_code=403, detail="Active subscription required")
    return current_user


# ============== Auth Endpoints ==============

@app.post("/auth/google", response_model=GoogleAuthResponse)
@limiter.limit("20/minute")
async def auth_google(request: Request, body: GoogleAuthRequest):
    """
    Verify Google/Firebase ID token and create/get user.
    
    This is the first step - user signs in with Google on the frontend,
    gets a Firebase ID token, and sends it here for verification.
    """
    firebase = get_firebase_service()
    email_service = get_email_service()
    
    try:
        decoded = await firebase.verify_id_token(body.id_token)
        
        # Get or create user
        user = await firebase.get_or_create_user(
            firebase_uid=decoded['uid'],
            email=decoded.get('email', ''),
            display_name=decoded.get('name', '')
        )
        
        # Send welcome email for new users
        if not user.get('subscription_status') or user.get('subscription_status') == 'none':
            await email_service.send_welcome_email(
                to_email=decoded.get('email', ''),
                user_name=decoded.get('name', 'there')
            )
        
        return GoogleAuthResponse(
            user_id=decoded['uid'],
            email=decoded.get('email', ''),
            display_name=decoded.get('name', ''),
            subscription_status=user.get('subscription_status', 'none'),
            spotify_linked=bool(user.get('spotify_user_id'))
        )
        
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


# ============== Spotify Linking Endpoints ==============

@app.get("/auth/spotify/login")
@limiter.limit("10/minute")
async def spotify_login(
    request: Request, 
    current_user: dict = Depends(get_current_user),
    spotify: SpotifyService = Depends(get_spotify)
):
    """
    Initiate Spotify OAuth flow.
    
    User must be authenticated with Firebase first.
    """
    # Generate secure state with user ID
    state = f"{current_user['uid']}:{secrets.token_urlsafe(32)}"
    state_storage[state] = {
        'uid': current_user['uid'],
        'created_at': datetime.now(timezone.utc)
    }
    
    auth_url = spotify.generate_auth_url(state)
    
    logger.info(f"Spotify OAuth initiated for user {current_user['uid'][:8]}***")
    
    return {"auth_url": auth_url}


@app.get("/auth/spotify/callback")
async def spotify_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    spotify: SpotifyService = Depends(get_spotify)
):
    """Handle Spotify OAuth callback after user authorizes."""
    settings = get_settings()
    
    if error:
        logger.error(f"Spotify OAuth error: {error}")
        return RedirectResponse(
            url=f"{settings.frontend_url}?spotify_error={error}"
        )
    
    if not code or not state:
        logger.error("Missing code or state in Spotify callback")
        return RedirectResponse(
            url=f"{settings.frontend_url}?spotify_error=missing_params"
        )
    
    # Validate state
    if state not in state_storage:
        logger.error(f"Invalid state in Spotify callback")
        return RedirectResponse(
            url=f"{settings.frontend_url}?spotify_error=invalid_state"
        )
    
    state_data = state_storage.pop(state)
    firebase_uid = state_data['uid']
    
    try:
        # Exchange code for tokens
        tokens = await spotify.exchange_code(code)
        
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)
        
        # Get Spotify user info
        user_info = await spotify.get_current_user(access_token)
        spotify_user_id = user_info.get("id")
        
        # Calculate token expiry
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        # Save tokens to Firebase
        firebase = get_firebase_service()
        await firebase.save_spotify_tokens(
            firebase_uid=firebase_uid,
            spotify_user_id=spotify_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at
        )
        
        logger.info(f"Spotify linked for user {firebase_uid[:8]}***")
        
        # Check if user has active subscription - trigger first scan
        user = await firebase.get_user(firebase_uid)
        if user and user.get('subscription_status') == 'active':
            # Trigger first full scan in background
            scheduler = get_scheduler_service()
            asyncio.create_task(scheduler.trigger_user_scan(firebase_uid))
        
        return RedirectResponse(
            url=f"{settings.frontend_url}?spotify_linked=true"
        )
        
    except Exception as e:
        logger.error(f"Spotify token exchange failed: {e}")
        return RedirectResponse(
            url=f"{settings.frontend_url}?spotify_error=auth_failed"
        )

# ============== Account Activation Endpoints ==============

@app.post("/auth/activate")
@limiter.limit("10/minute")
async def activate_account(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """
    Activate a free account for the user.
    
    Limited to first 24 users. Can be called after Google sign-in.
    """
    settings = get_settings()
    firebase = get_firebase_service()
    email_service = get_email_service()
    
    # Check if already active
    if current_user.get('subscription_status') == 'active':
        return {"status": "already_active", "message": "Account already activated"}
    
    # Check if user limit reached
    current_count = await firebase.get_active_subscriber_count()
    if current_count >= settings.max_subscribers:
        raise HTTPException(
            status_code=403, 
            detail="Maximum user limit reached"
        )
    
    # Activate free account
    success = await firebase.activate_free_account(
        firebase_uid=current_user['uid'],
        duration_days=settings.subscription_duration_days
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to activate account")
    
    # Get updated user data
    user = await firebase.get_user(current_user['uid'])
    
    # Send activation email
    await email_service.send_subscription_confirmation(
        to_email=current_user.get('email', ''),
        user_name=current_user.get('display_name', 'there'),
        amount=0,  # Free
        end_date=user.get('subscription_end_date')
    )
    
    # Trigger first scan if Spotify is already linked
    if user.get('spotify_user_id'):
        scheduler = get_scheduler_service()
        background_tasks.add_task(scheduler.trigger_user_scan, current_user['uid'])
    
    logger.info(f"Free account activated for user {current_user['uid'][:8]}***")
    
    return {"status": "activated", "message": "Account activated successfully"}


# ============== User Account Management ==============

@app.delete("/user/account")
@limiter.limit("5/minute")
async def delete_account(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete user account and all associated data.
    
    This action is irreversible.
    """
    firebase = get_firebase_service()
    
    success = await firebase.delete_user_account(firebase_uid=current_user['uid'])
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete account")
    
    logger.info(f"Account deleted for user {current_user['uid'][:8]}***")
    
    return {"status": "deleted", "message": "Account deleted successfully"}


# ============== Subscription Endpoints ==============

@app.get("/subscription/status", response_model=SubscriptionStatusResponse)
async def get_subscription_status(current_user: dict = Depends(get_current_user)):
    """Get current user's subscription status."""
    
    def format_date(dt):
        if isinstance(dt, datetime):
            return dt.isoformat()
        return None
    
    return SubscriptionStatusResponse(
        status=current_user.get('subscription_status', 'none'),
        start_date=format_date(current_user.get('subscription_start_date')),
        end_date=format_date(current_user.get('subscription_end_date')),
        spotify_linked=bool(current_user.get('spotify_user_id')),
        last_scan_at=format_date(current_user.get('last_scan_at')),
        total_songs_organized=current_user.get('total_songs_organized', 0)
    )


class SubscriptionLimitResponse(BaseModel):
    """Response with subscription limit information."""
    max_users: int
    current_users: int
    limit_reached: bool


@app.get("/subscription/limit", response_model=SubscriptionLimitResponse)
async def get_subscription_limit():
    """
    Check if subscription limit has been reached.
    
    This is public (no auth required) so the frontend can check before login.
    Returns default values if Firebase is unavailable.
    """
    settings = get_settings()
    
    try:
        firebase = get_firebase_service()
        current_count = await firebase.get_active_subscriber_count()
        limit_reached = current_count >= settings.max_subscribers
        
        return SubscriptionLimitResponse(
            max_users=settings.max_subscribers,
            current_users=current_count,
            limit_reached=limit_reached
        )
    except Exception as e:
        logger.error(f"Failed to check user limit: {e}")
        # Return defaults if Firebase is unavailable - don't block users
        return SubscriptionLimitResponse(
            max_users=settings.max_subscribers,
            current_users=0,
            limit_reached=False
        )


@app.post("/subscription/interest")
@limiter.limit("10/minute")
async def log_subscription_interest(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Log interest when a user clicks subscribe after limit is reached.
    
    This helps track potential users for V2 release marketing.
    """
    firebase = get_firebase_service()
    
    await firebase.log_interest_click(
        firebase_uid=current_user['uid'],
        email=current_user.get('email', '')
    )
    
    return {
        "status": "logged",
        "message": "Thanks for your interest! We'll notify you when V2 is available."
    }


# ============== Processing Endpoints ==============

@app.post("/process/trigger")
@limiter.limit("3/hour")
async def trigger_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_subscription)
):
    """
    Manually trigger a scan. Requires active subscription.
    
    Limited to 3 times per hour to prevent abuse.
    """
    if not current_user.get('spotify_user_id'):
        raise HTTPException(status_code=400, detail="Spotify account not linked")
    
    scheduler = get_scheduler_service()
    background_tasks.add_task(scheduler.trigger_user_scan, current_user['uid'])
    
    logger.info(f"Manual scan triggered for user {current_user['uid'][:8]}***")
    
    return {"status": "started", "message": "Scan started in background"}


@app.get("/process/status", response_model=StatusResponse)
@limiter.limit("60/minute")
async def get_process_status(
    request: Request,
    current_user: dict = Depends(require_subscription),
    processing: ProcessingService = Depends(get_processing)
):
    """Get current processing status for the user."""
    state = processing.get_state(current_user['uid'])
    return state.to_response()


# ============== Health & Info ==============

@app.get("/health")
@limiter.limit("60/minute")
async def health_check(request: Request):
    """Health check endpoint with system metrics."""
    rate_limiter = get_spotify_rate_limiter()
    scheduler = get_scheduler_service()
    
    return {
        "status": "healthy",
        "version": "2.0.0",
        "rate_limiter": rate_limiter.get_stats(),
        "job_queue": scheduler.get_queue_stats()
    }


# Metrics endpoints - Protected or removed for production
# Uncomment and add auth dependency if needed for internal monitoring
# @app.get("/metrics/rate-limiter")
# async def get_rate_limiter_metrics(current_user: dict = Depends(get_current_user)):
#     """Get detailed rate limiter metrics for monitoring."""
#     if current_user.get('email') not in ["admin@example.com"]: # Replace with admin check
#          raise HTTPException(status_code=403)
#     rate_limiter = get_spotify_rate_limiter()
#     return rate_limiter.get_stats()

# @app.get("/metrics/jobs")
# async def get_job_queue_metrics(current_user: dict = Depends(get_current_user)):
#     """Get job queue metrics for monitoring."""
#      if current_user.get('email') not in ["admin@example.com"]:
#          raise HTTPException(status_code=403)
#     scheduler = get_scheduler_service()
#     return scheduler.get_queue_stats()


@app.get("/")
async def root():
    """Root endpoint with API info."""
    settings = get_settings()
    return {
        "app": "Spotify Organizer API",
        "version": "2.1.0",
        "docs": "/docs",
        "pricing": "FREE (limited to 24 users)",
        "max_users": settings.max_subscribers,
        "features": [
            "Free for all users",
            "AI-powered genre classification",
            "Daily automatic organization",
            "Multi-language support"
        ]
    }

