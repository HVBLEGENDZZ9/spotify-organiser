"""Background job scheduler service with improved rate limiting.

Handles:
- Daily scan jobs for all active subscribers (with staggered execution)
- Subscription expiry checks and reminder emails
- Token refresh before expiry
- Job queue management for scalable processing

Uses job queues and rate limiting to handle 1000+ concurrent users safely.
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import get_settings
from .firebase_service import get_firebase_service
from .email_service import get_email_service
from .spotify_service import SpotifyService
from .rate_limiter import get_user_processing_limiter
from .job_queue import get_job_queue, JobPriority

logger = logging.getLogger(__name__)


class SchedulerService:
    """Background job scheduler for periodic tasks with rate limiting support."""
    
    _instance: Optional['SchedulerService'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self.settings = get_settings()
        self.scheduler = AsyncIOScheduler()
        self.spotify_service = SpotifyService()
        self._processing_service = None  # Lazy-loaded to use global instance
        self.user_limiter = get_user_processing_limiter()
        self.job_queue = get_job_queue()
        self._initialized = True
        
        # Set up job handler
        self.job_queue.set_job_handler(self._execute_scan_job)
        
        logger.info("Scheduler service initialized with job queue support")
    
    @property
    def processing_service(self):
        """Get the shared processing service instance."""
        if self._processing_service is None:
            from .processing_service import get_processing_service
            self._processing_service = get_processing_service()
        return self._processing_service
    
    async def start(self):
        """Start the background scheduler and job queue worker."""
        if self.scheduler.running:
            logger.warning("Scheduler already running")
            return
        
        # Daily scan job - runs at configured hour UTC
        self.scheduler.add_job(
            self._run_daily_scans,
            CronTrigger(hour=self.settings.scan_hour_utc, minute=0),
            id='daily_scans',
            name='Daily Spotify Scans',
            replace_existing=True
        )
        
        # Expiry check job - runs at configured hour UTC
        self.scheduler.add_job(
            self._check_expiring_subscriptions,
            CronTrigger(hour=self.settings.expiry_check_hour_utc, minute=0),
            id='expiry_checks',
            name='Subscription Expiry Checks',
            replace_existing=True
        )
        
        # Expired subscription cleanup - runs daily at midnight UTC
        self.scheduler.add_job(
            self._cleanup_expired_subscriptions,
            CronTrigger(hour=0, minute=5),
            id='expired_cleanup',
            name='Expired Subscription Cleanup',
            replace_existing=True
        )
        
        # Start the scheduler
        self.scheduler.start()
        
        # Start the job queue worker
        await self.job_queue.start()
        
        logger.info(f"Scheduler started. Daily scans at {self.settings.scan_hour_utc}:00 UTC")
    
    def stop(self):
        """Stop the scheduler gracefully."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")
    
    # ============== Job Implementations ==============
    
    async def _run_daily_scans(self):
        """
        Run daily scans for all active subscribers using job queue.
        
        This job:
        1. Gets all users with active subscriptions
        2. Enqueues scan jobs with staggered timing (30s apart)
        3. Job queue handles concurrent execution with rate limiting
        4. Each job updates last scan time
        """
        logger.info("Starting daily scans job - enqueueing to job queue")
        firebase = get_firebase_service()
        
        try:
            active_users = await firebase.get_active_subscribers()
            logger.info(f"Found {len(active_users)} active subscribers to scan")
            
            # Get user IDs
            user_ids = [user.get('uid') for user in active_users if user.get('uid')]
            
            # Enqueue all jobs with staggered timing
            # 30 seconds between each job start time for 1000 users = ~8 hours spread
            stagger_seconds = self.settings.scan_stagger_seconds
            job_ids = await self.job_queue.enqueue_batch(
                user_ids=user_ids,
                job_type="daily_scan",
                stagger_seconds=stagger_seconds
            )
            
            logger.info(
                f"Daily scans enqueued: {len(job_ids)} jobs "
                f"(stagger: {stagger_seconds}s, total spread: {len(job_ids) * stagger_seconds / 3600:.1f}h)"
            )
            
        except Exception as e:
            logger.error(f"Daily scans job failed: {e}")
    
    async def _execute_scan_job(self, firebase_uid: str):
        """
        Execute a scan job for a single user with rate limiting.
        
        This is called by the job queue worker.
        """
        # Acquire user processing slot
        await self.user_limiter.acquire(firebase_uid)
        
        try:
            await self._scan_user(firebase_uid)
        finally:
            # Release the slot
            await self.user_limiter.release(firebase_uid)
    
    async def _scan_user(self, firebase_uid: str):
        """
        Run a scan for a single user.
        
        Args:
            firebase_uid: Firebase user ID
        """
        firebase = get_firebase_service()
        
        # Get Spotify tokens
        tokens = await firebase.get_spotify_tokens(firebase_uid)
        if not tokens:
            logger.warning(f"No Spotify tokens for user {firebase_uid[:8]}***, skipping")
            return
        
        access_token = tokens['access_token']
        refresh_token = tokens['refresh_token']
        expires_at = tokens.get('expires_at')
        
        # Check if token needs refresh
        if expires_at:
            now = datetime.now(timezone.utc)
            # Refresh if expires within 10 minutes
            if isinstance(expires_at, datetime) and expires_at <= now + timedelta(minutes=10):
                access_token = await self._refresh_spotify_token(firebase_uid, refresh_token)
                if not access_token:
                    logger.error(f"Token refresh failed for user {firebase_uid[:8]}***")
                    return
        
        # Log scan start
        log_id = await firebase.log_scan_start(firebase_uid)
        
        try:
            # Run the processing pipeline
            await self.processing_service.process(access_token, firebase_uid)
            
            # Get results from processing state
            state = self.processing_service.get_state(firebase_uid)
            
            # Log completion
            await firebase.log_scan_complete(
                log_id,
                songs_processed=state.processed_songs,
                playlists_updated=state.playlists_created
            )
            
            # Update user stats - schedule next scan for tomorrow
            next_scan = datetime.now(timezone.utc) + timedelta(days=1)
            await firebase.update_user_scan_stats(
                firebase_uid,
                songs_processed=state.processed_songs,
                next_scan_at=next_scan
            )
            
            logger.info(f"Scan completed for user {firebase_uid[:8]}***: {state.processed_songs} songs")
            
        except Exception as e:
            await firebase.log_scan_complete(log_id, 0, 0, error=str(e))
            raise
        finally:
            self.processing_service.clear_state(firebase_uid)
    
    async def _refresh_spotify_token(self, firebase_uid: str, refresh_token: str) -> Optional[str]:
        """
        Refresh Spotify access token.
        
        Returns:
            New access token or None if refresh failed
        """
        firebase = get_firebase_service()
        
        try:
            tokens = await self.spotify_service.refresh_token(refresh_token)
            
            access_token = tokens.get('access_token')
            expires_in = tokens.get('expires_in', 3600)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            
            await firebase.update_spotify_access_token(firebase_uid, access_token, expires_at)
            
            logger.info(f"Refreshed Spotify token for user {firebase_uid[:8]}***")
            return access_token
            
        except Exception as e:
            logger.error(f"Failed to refresh Spotify token: {e}")
            return None
    
    async def _check_expiring_subscriptions(self):
        """
        Check for expiring subscriptions and send reminder emails.
        
        Sends reminders at:
        - 10 days before expiry
        - 5 days before expiry
        - Day of expiry
        """
        logger.info("Starting expiry check job")
        firebase = get_firebase_service()
        email_service = get_email_service()
        
        reminder_days = [10, 5, 0]
        
        for days in reminder_days:
            try:
                users = await firebase.get_expiring_subscriptions(days)
                logger.info(f"Found {len(users)} subscriptions expiring in {days} days")
                
                for user in users:
                    uid = user.get('uid', '')[:8]
                    try:
                        await email_service.send_expiry_reminder(
                            to_email=user.get('email'),
                            user_name=user.get('display_name', 'there'),
                            days_remaining=days,
                            end_date=user.get('subscription_end_date')
                        )
                    except Exception as e:
                        logger.error(f"Failed to send reminder to user {uid}***: {e}")
                    
                    await asyncio.sleep(0.5)  # Rate limit emails
                    
            except Exception as e:
                logger.error(f"Error checking {days}-day expiry: {e}")
        
        logger.info("Expiry check job completed")
    
    async def _cleanup_expired_subscriptions(self):
        """
        Mark expired subscriptions as expired.
        
        This runs right after midnight to catch subscriptions
        that expired the previous day.
        """
        logger.info("Starting expired subscription cleanup")
        firebase = get_firebase_service()
        
        try:
            # Get subscriptions that expired yesterday or earlier
            expired_users = await firebase.get_expiring_subscriptions(-1)
            
            for user in expired_users:
                uid = user.get('uid')
                try:
                    await firebase.expire_subscription(uid)
                    logger.info(f"Marked subscription as expired for user {uid}")
                except Exception as e:
                    logger.error(f"Failed to expire subscription for {uid}: {e}")
            
            logger.info(f"Cleanup completed, processed {len(expired_users)} expired subscriptions")
            
        except Exception as e:
            logger.error(f"Expired subscription cleanup failed: {e}")
    
    # ============== Manual Triggers ==============
    
    async def trigger_user_scan(self, firebase_uid: str, immediate: bool = False) -> str:
        """
        Manually trigger a scan for a specific user.
        Used for first scan after subscription or manual refresh.
        
        Args:
            firebase_uid: User to scan
            immediate: If True, executes immediately instead of queuing
        
        Returns:
            Job ID if queued, or 'immediate' if executed directly
        """
        if immediate:
            # For first scans or urgent requests, run immediately with limits
            logger.info(f"Immediately executing scan for user {firebase_uid[:8]}***")
            await self._execute_scan_job(firebase_uid)
            return "immediate"
        else:
            # Queue with high priority for manual triggers
            logger.info(f"Enqueueing high-priority scan for user {firebase_uid[:8]}***")
            job_id = await self.job_queue.enqueue(
                user_id=firebase_uid,
                job_type="manual_scan",
                priority=JobPriority.HIGH,
                delay_seconds=0  # Start as soon as possible
            )
            return job_id
    
    def get_queue_stats(self) -> dict:
        """Get job queue statistics for monitoring."""
        return self.job_queue.get_queue_stats()
    
    async def close(self):
        """Cleanup resources."""
        self.stop()
        await self.job_queue.stop()
        await self.spotify_service.close()
        await self.processing_service.close()


def get_scheduler_service() -> SchedulerService:
    """Get scheduler service singleton."""
    return SchedulerService()

