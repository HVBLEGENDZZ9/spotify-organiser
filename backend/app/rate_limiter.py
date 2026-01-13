"""Global rate limiter for Spotify API calls.

This module provides rate limiting to prevent hitting Spotify's API limits
when processing many users concurrently. Spotify uses a rolling 30-second
window for rate calculations.

Features:
- Global rate limiting across all users
- Sliding window algorithm
- Configurable limits per endpoint type
- Automatic backoff on 429 responses
"""

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Dict
from enum import Enum

logger = logging.getLogger(__name__)


class EndpointType(Enum):
    """Types of Spotify API endpoints with different rate limit priorities."""
    READ = "read"           # GET requests (higher limit)
    WRITE = "write"         # POST/PUT/DELETE requests (lower limit)
    BATCH = "batch"         # Batch operations like audio features


class SpotifyRateLimiter:
    """
    Global rate limiter for Spotify API calls using sliding window algorithm.
    
    Implements a token bucket / sliding window approach to ensure we stay
    within Spotify's rate limits across all concurrent operations.
    """
    
    _instance: Optional['SpotifyRateLimiter'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        # Configuration - conservative limits to stay safe
        # Spotify doesn't publish exact limits, so we use conservative values
        self.window_seconds = 30
        
        # Separate limits for different operation types
        self.limits: Dict[EndpointType, int] = {
            EndpointType.READ: 80,    # 80 read requests per 30 seconds
            EndpointType.WRITE: 30,   # 30 write requests per 30 seconds
            EndpointType.BATCH: 20,   # 20 batch requests per 30 seconds
        }
        
        # Track call times per endpoint type
        self.call_times: Dict[EndpointType, deque] = {
            endpoint_type: deque() for endpoint_type in EndpointType
        }
        
        # Lock for thread safety
        self._locks: Dict[EndpointType, asyncio.Lock] = {
            endpoint_type: asyncio.Lock() for endpoint_type in EndpointType
        }
        
        # Global lock for cross-type operations
        self._global_lock = asyncio.Lock()
        
        # Track 429 responses for adaptive limiting
        self._consecutive_429s = 0
        self._backoff_multiplier = 1.0
        
        self._initialized = True
        logger.info("Spotify rate limiter initialized")
    
    async def acquire(self, endpoint_type: EndpointType = EndpointType.READ) -> None:
        """
        Acquire permission to make an API call.
        
        This method will block if we're at the rate limit until a slot
        becomes available.
        
        Args:
            endpoint_type: Type of endpoint being called
        """
        async with self._locks[endpoint_type]:
            now = datetime.now(timezone.utc)
            call_times = self.call_times[endpoint_type]
            limit = int(self.limits[endpoint_type] / self._backoff_multiplier)
            
            # Remove calls outside the window
            cutoff = now.timestamp() - self.window_seconds
            while call_times and call_times[0] < cutoff:
                call_times.popleft()
            
            # If at limit, wait for oldest call to expire
            if len(call_times) >= limit:
                oldest = call_times[0]
                wait_time = (oldest + self.window_seconds) - now.timestamp()
                
                if wait_time > 0:
                    logger.debug(
                        f"Rate limit reached for {endpoint_type.value}. "
                        f"Waiting {wait_time:.2f}s"
                    )
                    await asyncio.sleep(wait_time + 0.1)
                    
                    # Re-clean after waiting
                    now = datetime.now(timezone.utc)
                    cutoff = now.timestamp() - self.window_seconds
                    while call_times and call_times[0] < cutoff:
                        call_times.popleft()
            
            # Record this call
            call_times.append(now.timestamp())
    
    async def report_429(self) -> int:
        """
        Report a 429 response from Spotify.
        
        Increases backoff multiplier to slow down requests.
        
        Returns:
            Recommended wait time in seconds
        """
        async with self._global_lock:
            self._consecutive_429s += 1
            self._backoff_multiplier = min(4.0, 1.0 + (self._consecutive_429s * 0.5))
            
            wait_time = min(60, 5 * self._consecutive_429s)
            
            logger.warning(
                f"Spotify 429 received. Consecutive: {self._consecutive_429s}, "
                f"Backoff multiplier: {self._backoff_multiplier}, "
                f"Wait: {wait_time}s"
            )
            
            return wait_time
    
    async def report_success(self) -> None:
        """Report a successful API call to gradually reduce backoff."""
        if self._consecutive_429s > 0:
            async with self._global_lock:
                self._consecutive_429s = max(0, self._consecutive_429s - 1)
                if self._consecutive_429s == 0:
                    self._backoff_multiplier = 1.0
    
    def get_stats(self) -> Dict:
        """Get current rate limiter statistics."""
        return {
            "window_seconds": self.window_seconds,
            "backoff_multiplier": self._backoff_multiplier,
            "consecutive_429s": self._consecutive_429s,
            "current_usage": {
                endpoint_type.value: len(calls)
                for endpoint_type, calls in self.call_times.items()
            },
            "limits": {
                endpoint_type.value: int(limit / self._backoff_multiplier)
                for endpoint_type, limit in self.limits.items()
            }
        }


class UserProcessingLimiter:
    """
    Limits the number of users that can be processed concurrently.
    
    This ensures we don't overwhelm Spotify's API by processing too many
    users at the same time.
    """
    
    _instance: Optional['UserProcessingLimiter'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        # Maximum concurrent user processing
        self.max_concurrent_users = 5
        self._semaphore = asyncio.Semaphore(self.max_concurrent_users)
        
        # Delay between starting each user's processing
        self.inter_user_delay = 5.0  # seconds
        
        # Track active processing
        self._active_users: set = set()
        self._lock = asyncio.Lock()
        
        self._initialized = True
        logger.info(f"User processing limiter initialized (max concurrent: {self.max_concurrent_users})")
    
    async def acquire(self, user_id: str) -> None:
        """
        Acquire a slot to process a user.
        
        Args:
            user_id: Unique identifier for the user
        """
        await self._semaphore.acquire()
        
        async with self._lock:
            self._active_users.add(user_id)
            logger.info(f"Started processing user {user_id}. Active: {len(self._active_users)}")
    
    async def release(self, user_id: str) -> None:
        """
        Release the processing slot for a user.
        
        Args:
            user_id: Unique identifier for the user
        """
        async with self._lock:
            self._active_users.discard(user_id)
            logger.info(f"Finished processing user {user_id}. Active: {len(self._active_users)}")
        
        self._semaphore.release()
        
        # Add delay before next user can start
        await asyncio.sleep(self.inter_user_delay)
    
    def get_active_count(self) -> int:
        """Get the number of currently active user processing jobs."""
        return len(self._active_users)
    
    def is_processing(self, user_id: str) -> bool:
        """Check if a specific user is currently being processed."""
        return user_id in self._active_users


def get_spotify_rate_limiter() -> SpotifyRateLimiter:
    """Get the singleton Spotify rate limiter instance."""
    return SpotifyRateLimiter()


def get_user_processing_limiter() -> UserProcessingLimiter:
    """Get the singleton user processing limiter instance."""
    return UserProcessingLimiter()
