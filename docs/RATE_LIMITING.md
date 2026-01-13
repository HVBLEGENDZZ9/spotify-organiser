# Spotify API Rate Limiting & Scalability Guide

This document explains the rate limiting and scalability improvements implemented in the Spotify Organizer application to support 1000+ concurrent users.

## Overview

Spotify's API has strict rate limits calculated on a rolling 30-second window. When deploying at scale, you must implement proper rate limiting to avoid 429 (Too Many Requests) errors.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│  │   Endpoint  │───▶│  Job Queue  │───▶│  User       │          │
│  │   Rate      │    │  (Staggered │    │  Processing │          │
│  │   Limiter   │    │   Execution)│    │  Limiter    │          │
│  └─────────────┘    └─────────────┘    └─────────────┘          │
│                                               │                   │
│                                               ▼                   │
│                          ┌─────────────────────────────┐         │
│                          │    Spotify Rate Limiter     │         │
│                          │  (Global, Sliding Window)   │         │
│                          └─────────────────────────────┘         │
│                                       │                           │
│                                       ▼                           │
│                          ┌─────────────────────────────┐         │
│                          │      Spotify Web API        │         │
│                          └─────────────────────────────┘         │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Global Spotify Rate Limiter (`rate_limiter.py`)

The `SpotifyRateLimiter` class implements a sliding window algorithm to enforce rate limits across ALL concurrent users.

**Features:**
- Separate limits for READ, WRITE, and BATCH operations
- Adaptive backoff on 429 responses
- Thread-safe with asyncio locks
- Configurable via environment variables

**Default Limits (per 30 seconds):**
- READ operations: 80 requests
- WRITE operations: 30 requests
- BATCH operations: 20 requests

**Usage:**
```python
from app.rate_limiter import get_spotify_rate_limiter, EndpointType

rate_limiter = get_spotify_rate_limiter()

# Before making a Spotify API call
await rate_limiter.acquire(EndpointType.READ)

# After a successful call
await rate_limiter.report_success()

# After a 429 error
wait_time = await rate_limiter.report_429()
```

### 2. User Processing Limiter (`rate_limiter.py`)

The `UserProcessingLimiter` class controls how many users can be processed simultaneously.

**Configuration:**
- `MAX_CONCURRENT_USERS`: Maximum simultaneous processing (default: 5)
- `INTER_USER_DELAY`: Seconds between starting new users (default: 5)

### 3. Job Queue (`job_queue.py`)

The `JobQueue` class provides priority-based scheduling with staggered execution.

**Features:**
- Priority levels: HIGH (manual triggers), NORMAL (daily scans), LOW (retries)
- Staggered scheduling (e.g., 30 seconds between jobs)
- Automatic retry with exponential backoff
- Job status tracking

**For 1000 users with 30s stagger = ~8.3 hours to process all**

### 4. Updated Scheduler Service (`scheduler_service.py`)

The scheduler now uses the job queue for daily scans:

```python
# Old approach (sequential, can't scale)
for user in users:
    await self._scan_user(user)
    await asyncio.sleep(2)

# New approach (staggered, scalable)
await self.job_queue.enqueue_batch(
    user_ids=user_ids,
    stagger_seconds=30
)
```

## Configuration

Add these to your `.env` file:

```bash
# Spotify API Rate Limiting
SPOTIFY_READ_LIMIT=80
SPOTIFY_WRITE_LIMIT=30
SPOTIFY_BATCH_LIMIT=20

# User Processing Concurrency
MAX_CONCURRENT_USERS=5
INTER_USER_DELAY=5.0

# Job Queue Settings
SCAN_STAGGER_SECONDS=30
JOB_MAX_RETRIES=3
JOB_STAGGER_DELAY=30
```

## Monitoring

New endpoints are available for monitoring:

### Health Check with Metrics
```
GET /health
```

Returns:
```json
{
  "status": "healthy",
  "version": "2.0.0",
  "rate_limiter": {
    "window_seconds": 30,
    "backoff_multiplier": 1.0,
    "consecutive_429s": 0,
    "current_usage": {"read": 0, "write": 0, "batch": 0},
    "limits": {"read": 80, "write": 30, "batch": 20}
  },
  "job_queue": {
    "total_jobs": 0,
    "queue_length": 0,
    "status_counts": {...},
    "running": true
  }
}
```

### Rate Limiter Metrics
```
GET /metrics/rate-limiter
```

### Job Queue Metrics
```
GET /metrics/jobs
```

## Spotify Developer Requirements

### Development Mode (Default)
- Only 25 users allowed
- Must be manually added to allowlist
- Lower rate limits

### Extended Quota Mode (Required for Scale)
To deploy with 1000+ users, you MUST apply for Extended Quota Mode.

**Requirements (as of May 2025):**
- Registered business entity
- Live, public-facing application
- Minimum 250,000 active monthly users
- Clear revenue generation
- Application via company email

### API Access Changes (November 2024)
New apps registered after November 27, 2024 do **NOT** have access to:
- `/v1/audio-features`
- `/v1/audio-analysis`
- `/v1/recommendations`
- 30-second preview URLs

**Impact on this app:** The fallback language detection has been updated to not rely on audio features.

## Scaling Recommendations

### For 100-500 Users
- Default settings should work
- Increase `MAX_CONCURRENT_USERS` to 10

### For 500-1000 Users
- Increase stagger to 60 seconds
- Consider running scans over 24 hours
- Apply for Extended Quota Mode

### For 1000+ Users
- MUST have Extended Quota Mode
- Consider multiple scan windows (not just 2 AM UTC)
- Add Redis for distributed rate limiting
- Consider Celery for job queue
- Monitor via `/health` endpoint

## Error Handling

### 429 (Rate Limited)
1. Global rate limiter increases backoff multiplier
2. All future requests are slowed down
3. After successful requests, backoff gradually reduces

### Job Failures
1. Failed jobs are re-queued with exponential backoff
2. Default: 3 retries (2, 4, 8 minutes delay)
3. After max retries, job is marked as failed

## Testing

To test rate limiting locally:

```bash
# Check health and metrics
curl http://localhost:8000/health

# Check rate limiter specifically
curl http://localhost:8000/metrics/rate-limiter

# Check job queue
curl http://localhost:8000/metrics/jobs
```

## Future Improvements

For even larger scale (10,000+ users), consider:

1. **Redis-backed Rate Limiting**: Distribute rate limit state across instances
2. **Celery + Redis**: Replace in-memory job queue with Celery
3. **Horizontal Scaling**: Multiple API instances behind load balancer
4. **Database Queuing**: Persist job queue to survive restarts
5. **Webhooks**: Use Spotify webhooks if they become available
