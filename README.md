# Spotify Liked Songs Organizer

A smart, AI-powered application that automatically organizes your Spotify "Liked Songs" into genre/mood-based playlists.

## Features

- **Automated Organization**: Scans your "Liked Songs" and sorts them into playlists like *SPO-Pop*, *SPO-Hip-Hop*, *SPO-Bollywood-Romantic*, etc.
- **AI-Powered Classification**: Uses **Google Gemini 2.0 Flash** to intelligently detect languages and genres, handling nuances better than static rules.
- **Smart Rate Limiting**: Built-in sliding window rate limiter to respect Spotify's API limits and prevent 429 errors.
- **Subscription Model**: Simple "Free Tier" system (limited to 24 users) with Firebase Auth.
- **Secure Architecture**: OAuth 2.0 with state verification, secure token storage, and strict CORS policies.

## Tech Stack

- **Backend**: Python (FastAPI), Google Gemini AI, Spotify Web API
- **Frontend**: React, Tailwind CSS, Vite
- **Database**: Firebase Firestore (User data, Auth state)
- **Deployment**: Vercel (Frontend), Render/Railway (Backend - recommended)

## Service Structure

- `spotify_service.py`: Handles all Spotify API interactions with retry logic.
- `gemini_service.py`: Interfaces with Google Gemini for intelligent classification.
- `rate_limiter.py`: Custom sliding window rate limiter implementation.
- `scheduler_service.py`: Manages background jobs for daily playlist updates.

## Getting Started

### Backend Setup

1.  Clone the repository.
2.  Navigate to `backend/`.
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Set up environment variables (`.env`):
    ```env
    SPOTIFY_CLIENT_ID=your_id
    SPOTIFY_CLIENT_SECRET=your_secret
    SPOTIFY_REDIRECT_URI=http://localhost:8000/auth/spotify/callback
    GEMINI_API_KEY=your_key
    FRONTEND_URL=http://localhost:5173
    ```
5.  Run the server:
    ```bash
    uvicorn app.main:app --reload
    ```

### Frontend Setup

1.  Navigate to `frontend/`.
2.  Install dependencies:
    ```bash
    npm install
    ```
3.  Start the dev server:
    ```bash
    npm run dev
    ```

## Security

- **OAuth State**: Validated server-side with TTL to prevent CSRF.
- **Input Validation**: Pydantic models ensure data integrity.
- **Error Handling**: Graceful degradation and user-friendly error messages.
