# Spotify Liked Songs Housekeeping – AI‑Driven Playlist Organizer

## 1. Overview
This document describes the end‑to‑end design of a web application that organizes a user's **Spotify Liked Songs** into curated genre‑based playlists using AI (Gemini). The app focuses on **simplicity, security, scalability, and premium UX**.

The system consists of:
- **Frontend**: A minimal, luxurious React web UI
- **Backend**: FastAPI service handling Spotify OAuth, playlist management, AI classification, batching, retries, and cleanup

The app is **stateless for users**, does **not store personal data**, and operates only during an active session.

---

## 2. Goals & Non‑Goals

### Goals
- Clean up Spotify Liked Songs into **exactly one playlist per song**
- Use **AI‑assisted classification** with strict genre rules
- Support up to **1000 liked songs** per run
- Provide **safe, secure, abuse‑resistant** infrastructure
- Deliver a **premium, refined, responsive UI**

### Non‑Goals
- No long‑term user data storage
- No social, sharing, or collaboration features
- No playlist re‑runs without re‑authorization

---

## 3. User Experience Flow

1. User opens the web app
2. Sees a luxury landing page with:
   - "Authorize and Begin" CTA
   - Trust card: *"We do not collect any data"* and *"Made out of love for Tana"*
3. User authorizes Spotify via OAuth
4. Backend fetches liked songs (up to 1000)
5. Songs are processed in batches using Gemini
6. Playlists are created / populated
7. Empty playlists are deleted
8. UI displays: **"House Keeping done!"**
9. User is redirected to home page

---

## 4. Playlist Taxonomy & Classification Rules

### Global Rule
- **Each song must belong to exactly ONE playlist**
- Classification priority: **Language → Era → Mood → Genre**

### Playlists

**English (Strict)**
- Pre 1980: English songs released before 1980
- Pre 2000: English songs released between 1980–1999

**Bollywood (Hindi Film Music)**
- Bollywood (pre 1980)
- Bollywood (pre 2000)
- Upbeat Bollywood
- Slow Bollywood
- Romantic Bollywood

**Hip Hop**
- OldHipHop (80s–early 2000s, global)
- DesiHipHop (Indian hip hop)

**Electronic**
- EDMs

**Indie**
- DesiIndies
- GlobalIndies

**Utility / Mood**
- Instrumentals
- PartySongs

**Regional (Strict Language Based)**
- Marathi
- Bengali
- Telugu
- Tamil

---

## 5. System Architecture

### High‑Level Architecture

```
[ React + Tailwind ]
        |
        v
[ FastAPI Backend ]
        |
 ┌──────┼────────┐
 |      |        |
 v      v        v
Spotify OAuth  Gemini API  Logging / Rate Limiter
```

---

## 6. Backend Design

### Tech Stack
- FastAPI
- Pydantic
- Spotify Web API
- OAuth2 Authorization Code Flow
- Gemini API
- Redis (rate limiting & retries – optional but recommended)
- Python logging + structured logs

---

### Backend Responsibilities

1. OAuth token exchange & refresh
2. Fetch liked songs (pagination)
3. Enforce max 1000 songs
4. Batch processing (50 songs per batch)
5. AI classification
6. Playlist creation & population
7. Empty playlist cleanup
8. Error handling & retries
9. Abuse protection

---

### API Endpoints

```http
GET  /auth/login
GET  /auth/callback
POST /process/start
GET  /process/status
```

---

### OAuth Flow

- Uses Spotify Authorization Code Flow
- Scopes:
  - user-library-read
  - playlist-modify-public
  - playlist-modify-private

Tokens are:
- Stored **in memory only** (or encrypted short‑lived cache)
- Never persisted to DB

---

## 7. Batch Processing Strategy

- Spotify liked songs fetched in pages of 50
- Processing pipeline:

```
Fetch Songs → Normalize Metadata → Batch (50) → AI Classify → Apply Playlists
```

- If liked songs > 1000:
  - Only first 1000 processed
  - User notified

---

## 8. AI (Gemini) Integration

### Prompt Strategy

Each batch is sent with:
- Track name
- Artist
- Album
- Release year
- Spotify audio features (energy, tempo, valence, etc.)

### Gemini Output Schema

```json
{
  "track_id": "spotify_id",
  "playlist": "Pre 1980"
}
```

### Safeguards
- Strict enum validation using Pydantic
- Rejects unknown playlists
- Fallback classification (rule‑based) if Gemini fails

---

## 9. Retry & Rate Limit Handling

### Gemini API
- Exponential backoff (max retries: 5)
- Circuit breaker when quota exhausted
- Frontend displays:

> **"Too much traffic. Please try again shortly."**

### Spotify API
- Retry on 429 using `Retry‑After` header

---

## 10. Playlist Management Logic

### Playlist Creation
- If playlist with same name exists:
  - Reuse existing playlist (songs accumulate)
- If playlist doesn't exist:
  - Create new playlist with simple name (genre or language)

### Cleanup
- After population:
  - Fetch created playlists
  - Delete playlists with 0 tracks

---

## 11. Frontend Design

### Tech Stack
- React
- Tailwind CSS
- Vite
- Framer Motion (optional for subtle animations)

### UI Principles
- Minimal
- Premium
- Dark, elegant palette
- Soft gradients
- Responsive (mobile‑first)

### Pages

**Landing Page**
- Centered hero text
- CTA button: "Authorize and Begin"
- Trust card

**Status Overlay**
- Loading spinner
- Progress text

---

## 12. Security & Abuse Protection

- OAuth state validation
- CSRF protection
- Rate limiting per IP
- Request size limits
- No user data persistence
- HTTPS only

---

## 13. Logging & Observability

### Logging
- Structured JSON logs
- Log levels: INFO / WARNING / ERROR
- Correlation ID per request

### Metrics
- Songs processed
- AI latency
- Error rates

---

## 14. Error Handling Strategy

- User‑friendly messages on frontend
- Detailed stack traces only in logs
- Graceful failure per batch
- Partial success allowed

---

## 15. Future Enhancements (Optional)

- User‑defined genres
- Dry‑run mode
- Re‑processing specific playlists
- Background jobs with Celery

---

## 16. Summary

This design ensures:
- Clean separation of concerns
- AI‑assisted yet deterministic outcomes
- High security and privacy
- Premium user experience
- Maintainable, scalable codebase

**Outcome:** A safe, elegant, AI‑powered housekeeping tool for Spotify music lovers.
