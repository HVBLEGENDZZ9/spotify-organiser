"""Job queue for managing background processing tasks.

This module provides a simple but effective job queue for managing
user processing tasks. It supports:
- Priority-based scheduling
- Staggered execution to avoid API rate limits
- Job status tracking
- Retry on failure

For production at larger scale, consider migrating to Celery + Redis.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Callable, Any
from enum import Enum
from dataclasses import dataclass, field
from heapq import heappush, heappop
import uuid

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Status of a queued job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority(Enum):
    """Priority levels for jobs."""
    HIGH = 0      # Manual triggers, first scans
    NORMAL = 1    # Scheduled daily scans
    LOW = 2       # Retry jobs


@dataclass(order=True)
class Job:
    """Represents a queued job."""
    scheduled_time: datetime = field(compare=True)
    priority: int = field(compare=True)
    job_id: str = field(compare=False, default_factory=lambda: str(uuid.uuid4()))
    user_id: str = field(compare=False, default="")
    job_type: str = field(compare=False, default="scan")
    status: JobStatus = field(compare=False, default=JobStatus.PENDING)
    created_at: datetime = field(compare=False, default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = field(compare=False, default=None)
    completed_at: Optional[datetime] = field(compare=False, default=None)
    error: Optional[str] = field(compare=False, default=None)
    retry_count: int = field(compare=False, default=0)
    max_retries: int = field(compare=False, default=3)


class JobQueue:
    """
    A priority-based job queue for background processing.
    
    Features:
    - Priority scheduling (high priority jobs run first)
    - Staggered execution (configurable delay between jobs)
    - Automatic retry on failure
    - Job status tracking
    """
    
    _instance: Optional['JobQueue'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        # Priority queue (min-heap based on scheduled_time and priority)
        self._queue: List[Job] = []
        
        # Job lookup by ID
        self._jobs: Dict[str, Job] = {}
        
        # User to job mapping (one active job per user)
        self._user_jobs: Dict[str, str] = {}
        
        # Queue processing settings
        self.stagger_delay = 30.0  # seconds between starting jobs
        self.max_concurrent_jobs = 5
        
        # Locks
        self._queue_lock = asyncio.Lock()
        
        # Worker task
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Job handler
        self._job_handler: Optional[Callable] = None
        
        self._initialized = True
        logger.info("Job queue initialized")
    
    def set_job_handler(self, handler: Callable[[str], Any]) -> None:
        """
        Set the function that processes jobs.
        
        Args:
            handler: Async function that takes user_id and processes the job
        """
        self._job_handler = handler
    
    async def start(self) -> None:
        """Start the job queue worker."""
        if self._running:
            return
        
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Job queue worker started")
    
    async def stop(self) -> None:
        """Stop the job queue worker."""
        self._running = False
        
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Job queue worker stopped")
    
    async def enqueue(
        self,
        user_id: str,
        job_type: str = "scan",
        priority: JobPriority = JobPriority.NORMAL,
        delay_seconds: float = 0
    ) -> str:
        """
        Add a job to the queue.
        
        Args:
            user_id: User to process
            job_type: Type of job (e.g., "scan", "first_scan")
            priority: Job priority level
            delay_seconds: Delay before job can run
        
        Returns:
            Job ID
        """
        async with self._queue_lock:
            # Check if user already has a pending/running job
            if user_id in self._user_jobs:
                existing_job_id = self._user_jobs[user_id]
                existing_job = self._jobs.get(existing_job_id)
                
                if existing_job and existing_job.status in [JobStatus.PENDING, JobStatus.RUNNING]:
                    logger.warning(f"User {user_id} already has an active job: {existing_job_id}")
                    return existing_job_id
            
            # Create new job
            scheduled_time = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            
            job = Job(
                scheduled_time=scheduled_time,
                priority=priority.value,
                user_id=user_id,
                job_type=job_type
            )
            
            # Add to queue and tracking
            heappush(self._queue, job)
            self._jobs[job.job_id] = job
            self._user_jobs[user_id] = job.job_id
            
            logger.info(
                f"Enqueued job {job.job_id} for user {user_id} "
                f"(type: {job_type}, priority: {priority.name}, delay: {delay_seconds}s)"
            )
            
            return job.job_id
    
    async def enqueue_batch(
        self,
        user_ids: List[str],
        job_type: str = "scan",
        stagger_seconds: float = 30
    ) -> List[str]:
        """
        Enqueue jobs for multiple users with staggered scheduling.
        
        Args:
            user_ids: List of user IDs to process
            job_type: Type of job
            stagger_seconds: Delay between each job's scheduled time
        
        Returns:
            List of job IDs
        """
        job_ids = []
        
        for i, user_id in enumerate(user_ids):
            delay = i * stagger_seconds
            job_id = await self.enqueue(
                user_id=user_id,
                job_type=job_type,
                priority=JobPriority.NORMAL,
                delay_seconds=delay
            )
            job_ids.append(job_id)
        
        logger.info(f"Enqueued {len(job_ids)} jobs with {stagger_seconds}s stagger")
        return job_ids
    
    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get the status of a specific job."""
        job = self._jobs.get(job_id)
        if not job:
            return None
        
        return {
            "job_id": job.job_id,
            "user_id": job.user_id,
            "job_type": job.job_type,
            "status": job.status.value,
            "priority": job.priority,
            "scheduled_time": job.scheduled_time.isoformat(),
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error": job.error,
            "retry_count": job.retry_count
        }
    
    def get_queue_stats(self) -> Dict:
        """Get overall queue statistics."""
        status_counts = {status.value: 0 for status in JobStatus}
        
        for job in self._jobs.values():
            status_counts[job.status.value] += 1
        
        return {
            "total_jobs": len(self._jobs),
            "queue_length": len(self._queue),
            "status_counts": status_counts,
            "running": self._running
        }
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending job."""
        async with self._queue_lock:
            job = self._jobs.get(job_id)
            
            if not job:
                return False
            
            if job.status == JobStatus.PENDING:
                job.status = JobStatus.CANCELLED
                logger.info(f"Cancelled job {job_id}")
                return True
            
            return False
    
    async def _worker_loop(self) -> None:
        """Main worker loop that processes jobs."""
        semaphore = asyncio.Semaphore(self.max_concurrent_jobs)
        
        while self._running:
            try:
                # Get next job
                job = await self._get_next_job()
                
                if job:
                    # Process with concurrency limit
                    asyncio.create_task(self._process_job_with_limit(job, semaphore))
                else:
                    # No jobs ready, wait a bit
                    await asyncio.sleep(1)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(5)
    
    async def _get_next_job(self) -> Optional[Job]:
        """Get the next job that's ready to run."""
        async with self._queue_lock:
            now = datetime.now(timezone.utc)
            
            while self._queue:
                # Peek at the top job
                job = self._queue[0]
                
                # Skip cancelled or completed jobs
                if job.status in [JobStatus.CANCELLED, JobStatus.COMPLETED, JobStatus.FAILED]:
                    heappop(self._queue)
                    continue
                
                # Check if job is ready (scheduled time has passed)
                if job.scheduled_time <= now:
                    heappop(self._queue)
                    return job
                else:
                    # Job not ready yet
                    break
            
            return None
    
    async def _process_job_with_limit(self, job: Job, semaphore: asyncio.Semaphore) -> None:
        """Process a job with concurrency limiting."""
        async with semaphore:
            await self._process_job(job)
            await asyncio.sleep(self.stagger_delay)
    
    async def _process_job(self, job: Job) -> None:
        """Process a single job."""
        if not self._job_handler:
            logger.error("No job handler set")
            job.status = JobStatus.FAILED
            job.error = "No job handler configured"
            return
        
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        
        logger.info(f"Processing job {job.job_id} for user {job.user_id}")
        
        try:
            await self._job_handler(job.user_id)
            
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            
            logger.info(
                f"Job {job.job_id} completed successfully "
                f"(duration: {(job.completed_at - job.started_at).total_seconds():.1f}s)"
            )
            
        except Exception as e:
            logger.error(f"Job {job.job_id} failed: {e}")
            
            job.retry_count += 1
            
            if job.retry_count < job.max_retries:
                # Re-queue with exponential backoff
                job.status = JobStatus.PENDING
                job.scheduled_time = datetime.now(timezone.utc) + timedelta(
                    seconds=60 * (2 ** job.retry_count)  # 2, 4, 8 minutes
                )
                job.error = str(e)
                
                async with self._queue_lock:
                    heappush(self._queue, job)
                
                logger.info(
                    f"Job {job.job_id} re-queued for retry "
                    f"(attempt {job.retry_count}/{job.max_retries})"
                )
            else:
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now(timezone.utc)
                job.error = str(e)
                
                logger.error(f"Job {job.job_id} failed after {job.max_retries} retries")
        
        finally:
            # Clean up user mapping for completed/failed jobs
            if job.status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                async with self._queue_lock:
                    if self._user_jobs.get(job.user_id) == job.job_id:
                        del self._user_jobs[job.user_id]


def get_job_queue() -> JobQueue:
    """Get the singleton job queue instance."""
    return JobQueue()
