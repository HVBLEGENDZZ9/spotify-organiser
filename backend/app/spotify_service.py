"""Spotify Web API integration service with global rate limiting.

This service handles all interactions with the Spotify Web API including:
- OAuth authentication flow
- Fetching user library and playlists
- Audio features retrieval
- Playlist creation and population

Rate limiting is handled globally to prevent hitting Spotify's API limits
when processing many users concurrently.
"""

import httpx
from typing import Optional, List, Dict, Any
from urllib.parse import urlencode
import logging
import asyncio

from .config import get_settings
from .models import Track
from .rate_limiter import (
    get_spotify_rate_limiter,
    EndpointType
)

logger = logging.getLogger(__name__)

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"


class SpotifyService:
    """Service for interacting with Spotify Web API with global rate limiting."""
    
    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=30.0)
        self.rate_limiter = get_spotify_rate_limiter()
        
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    def generate_auth_url(self, state: str) -> str:
        """Generate Spotify OAuth authorization URL."""
        params = {
            "client_id": self.settings.spotify_client_id,
            "response_type": "code",
            "redirect_uri": self.settings.spotify_redirect_uri,
            "scope": "user-library-read playlist-modify-public playlist-modify-private",
            "state": state,
            "show_dialog": "true"
        }
        return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"
    
    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.spotify_redirect_uri,
            "client_id": self.settings.spotify_client_id,
            "client_secret": self.settings.spotify_client_secret,
        }
        
        response = await self.client.post(
            SPOTIFY_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code != 200:
            logger.error(f"Token exchange failed: {response.text}")
            raise Exception(f"Failed to exchange code: {response.status_code}")
        
        return response.json()
    
    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh the access token."""
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.settings.spotify_client_id,
            "client_secret": self.settings.spotify_client_secret,
        }
        
        response = await self.client.post(
            SPOTIFY_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code != 200:
            logger.error(f"Token refresh failed: {response.text}")
            raise Exception(f"Failed to refresh token: {response.status_code}")
        
        return response.json()
    
    async def get_current_user(self, access_token: str) -> Dict[str, Any]:
        """Get current user's profile."""
        response = await self.client.get(
            f"{SPOTIFY_API_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to get user profile: {response.status_code}")
        
        return response.json()
    
    async def _handle_rate_limit(self, response: httpx.Response) -> int:
        """Handle rate limiting and return retry-after seconds."""
        # Report to global rate limiter for adaptive throttling
        recommended_wait = await self.rate_limiter.report_429()
        
        # Use the higher of Spotify's Retry-After or our recommended wait
        retry_after = max(
            int(response.headers.get("Retry-After", 1)),
            recommended_wait
        )
        logger.warning(f"Rate limited. Retry after {retry_after} seconds")
        return retry_after
    
    async def get_liked_songs(
        self, 
        access_token: str, 
        limit: int = 50, 
        offset: int = 0
    ) -> Dict[str, Any]:
        """Fetch user's liked songs with pagination and rate limiting."""
        max_retries = 3
        
        for attempt in range(max_retries):
            # Acquire rate limit token before making request
            await self.rate_limiter.acquire(EndpointType.READ)
            
            response = await self.client.get(
                f"{SPOTIFY_API_BASE}/me/tracks",
                params={"limit": limit, "offset": offset},
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if response.status_code == 429:
                retry_after = await self._handle_rate_limit(response)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_after)
                    continue
                raise Exception(f"Rate limited. Retry after {retry_after} seconds")
            
            if response.status_code != 200:
                raise Exception(f"Failed to fetch liked songs: {response.status_code}")
            
            # Report success for adaptive rate limiting
            await self.rate_limiter.report_success()
            return response.json()
        
        raise Exception("Max retries exceeded for fetching liked songs")
    
    async def fetch_all_liked_songs(
        self, 
        access_token: str, 
        max_songs: int = 1000,
        since_timestamp: Optional[str] = None
    ) -> List[Track]:
        """
        Fetch liked songs up to max_songs limit.
        
        Args:
            access_token: Spotify access token
            max_songs: Maximum songs to fetch
            since_timestamp: If provided, only fetch songs added after this ISO timestamp.
                           Stops fetching when we hit older songs.
        
        Returns:
            List of Track objects (newest first if since_timestamp is used)
        """
        tracks = []
        offset = 0
        batch_size = 50
        reached_old_songs = False
        
        while offset < max_songs and not reached_old_songs:
            result = await self.get_liked_songs(
                access_token, 
                limit=batch_size, 
                offset=offset
            )
            
            items = result.get("items", [])
            if not items:
                break
            
            for item in items:
                if len(tracks) >= max_songs:
                    break
                
                # Get the added_at timestamp
                added_at = item.get("added_at")
                
                # If we have a since_timestamp, check if this track is older
                if since_timestamp and added_at:
                    if added_at <= since_timestamp:
                        # This song and all subsequent ones are old, stop fetching
                        reached_old_songs = True
                        logger.info(f"Reached songs from previous scan at {added_at}")
                        break
                    
                track_data = item.get("track", {})
                if not track_data or not track_data.get("id"):
                    continue
                
                # Extract release year from album
                release_date = track_data.get("album", {}).get("release_date", "")
                release_year = None
                if release_date:
                    try:
                        release_year = int(release_date[:4])
                    except (ValueError, IndexError):
                        pass
                
                track = Track(
                    id=track_data["id"],
                    name=track_data.get("name", "Unknown"),
                    artists=[a.get("name", "") for a in track_data.get("artists", [])],
                    album=track_data.get("album", {}).get("name", "Unknown"),
                    release_year=release_year,
                    duration_ms=track_data.get("duration_ms", 0),
                    popularity=track_data.get("popularity", 0),
                    added_at=added_at
                )
                tracks.append(track)
            
            offset += batch_size
            
            if len(items) < batch_size:
                break
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)
        
        if since_timestamp:
            logger.info(f"Fetched {len(tracks)} NEW liked songs (since {since_timestamp})")
        else:
            logger.info(f"Fetched {len(tracks)} liked songs (full scan)")
        return tracks
    
    async def get_audio_features(
        self, 
        access_token: str, 
        track_ids: List[str]
    ) -> Dict[str, Dict[str, float]]:
        """
        Get all audio features for multiple tracks.
        Returns all features needed for genre classification.
        """
        if not track_ids:
            return {}
        
        # Spotify allows max 100 tracks per request
        features = {}
        max_retries = 3
        
        for i in range(0, len(track_ids), 100):
            batch_ids = track_ids[i:i+100]
            
            for attempt in range(max_retries):
                # Acquire rate limit token for batch operations
                await self.rate_limiter.acquire(EndpointType.BATCH)
                
                response = await self.client.get(
                    f"{SPOTIFY_API_BASE}/audio-features",
                    params={"ids": ",".join(batch_ids)},
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                
                if response.status_code == 429:
                    retry_after = await self._handle_rate_limit(response)
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_after)
                        continue
                    logger.error(f"Rate limited while fetching audio features")
                    break
                
                if response.status_code == 200:
                    data = response.json()
                    for feature in data.get("audio_features", []):
                        if feature and feature.get("id"):
                            # Extract ALL features needed for classification
                            features[feature["id"]] = {
                                "danceability": feature.get("danceability"),
                                "energy": feature.get("energy"),
                                "tempo": feature.get("tempo"),
                                "loudness": feature.get("loudness"),
                                "speechiness": feature.get("speechiness"),
                                "acousticness": feature.get("acousticness"),
                                "instrumentalness": feature.get("instrumentalness"),
                                "valence": feature.get("valence"),
                                "key": feature.get("key"),
                                "mode": feature.get("mode"),
                                "time_signature": feature.get("time_signature"),
                                "liveness": feature.get("liveness"),
                            }
                    break
                else:
                    logger.warning(f"Failed to fetch audio features: {response.status_code}")
                    break
            
            # Small delay between batches
            await asyncio.sleep(0.1)
        
        logger.info(f"Fetched audio features for {len(features)} tracks")
        return features
    
    async def get_user_playlists(self, access_token: str) -> List[Dict[str, Any]]:
        """Get all playlists owned by the current user with rate limiting."""
        playlists = []
        offset = 0
        
        while True:
            # Acquire rate limit token
            await self.rate_limiter.acquire(EndpointType.READ)
            
            response = await self.client.get(
                f"{SPOTIFY_API_BASE}/me/playlists",
                params={"limit": 50, "offset": offset},
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch playlists: {response.status_code} - {response.text}")
                break
            
            data = response.json()
            items = data.get("items", [])
            playlists.extend(items)
            
            logger.debug(f"Fetched {len(items)} playlists (offset={offset}, total so far={len(playlists)})")
            
            if len(items) < 50:
                break
            offset += 50
            
            await asyncio.sleep(0.1)
        
        logger.info(f"Total playlists fetched: {len(playlists)}")
        return playlists

    
    async def find_playlist_by_name(
        self, 
        access_token: str, 
        user_id: str,
        name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Find an existing playlist by exact name match.
        Only returns playlists owned by the current user.
        
        Args:
            access_token: Spotify access token
            user_id: The current user's Spotify ID
            name: Exact playlist name to search for
        
        Returns:
            Playlist dict if found, None otherwise
        """
        playlists = await self.get_user_playlists(access_token)
        
        for playlist in playlists:
            # Check if playlist name matches and user owns it
            if playlist.get("name") == name:
                owner = playlist.get("owner", {})
                if owner.get("id") == user_id:
                    logger.info(f"Found existing playlist: {name} ({playlist.get('id')})")
                    return playlist
        
        return None
    
    async def get_or_create_playlist(
        self, 
        access_token: str, 
        user_id: str,
        name: str, 
        description: str = "",
        public: bool = False
    ) -> Dict[str, Any]:
        """
        Get an existing playlist by name or create a new one if it doesn't exist.
        This allows songs to accumulate across multiple runs.
        
        Args:
            access_token: Spotify access token
            user_id: The current user's Spotify ID
            name: Playlist name
            description: Playlist description (only used when creating new)
            public: Whether the playlist should be public (only used when creating new)
        
        Returns:
            Playlist dict (either existing or newly created)
        """
        # First, try to find an existing playlist with this name
        existing_playlist = await self.find_playlist_by_name(access_token, user_id, name)
        
        if existing_playlist:
            logger.info(f"Reusing existing playlist: {name}")
            return existing_playlist
        
        # No existing playlist found, create a new one
        logger.info(f"Creating new playlist: {name}")
        return await self.create_playlist(access_token, user_id, name, description, public)
    
    async def create_playlist(
        self, 
        access_token: str, 
        user_id: str,
        name: str, 
        description: str = "",
        public: bool = False
    ) -> Dict[str, Any]:
        """Create a new playlist with rate limiting."""
        max_retries = 3
        
        for attempt in range(max_retries):
            # Acquire rate limit token for write operation
            await self.rate_limiter.acquire(EndpointType.WRITE)
            
            response = await self.client.post(
                f"{SPOTIFY_API_BASE}/users/{user_id}/playlists",
                json={
                    "name": name,
                    "description": description,
                    "public": public
                },
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code == 429:
                retry_after = await self._handle_rate_limit(response)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_after)
                    continue
                raise Exception(f"Rate limited while creating playlist")
            
            if response.status_code not in (200, 201):
                raise Exception(f"Failed to create playlist: {response.status_code}")
            
            return response.json()
        
        raise Exception("Max retries exceeded for creating playlist")
    
    async def add_tracks_to_playlist(
        self, 
        access_token: str, 
        playlist_id: str, 
        track_uris: List[str]
    ) -> bool:
        """Add tracks to a playlist with rate limiting. Max 100 tracks per request."""
        max_retries = 3
        
        for i in range(0, len(track_uris), 100):
            batch_uris = track_uris[i:i+100]
            
            for attempt in range(max_retries):
                # Acquire rate limit token for write operation
                await self.rate_limiter.acquire(EndpointType.WRITE)
                
                response = await self.client.post(
                    f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
                    json={"uris": batch_uris},
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    }
                )
                
                if response.status_code == 429:
                    retry_after = await self._handle_rate_limit(response)
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_after)
                        continue
                    logger.error(f"Rate limited while adding tracks")
                    return False
                
                if response.status_code not in (200, 201):
                    logger.error(f"Failed to add tracks: {response.text}")
                    return False
                
                break
            
            # Small delay between batches
            await asyncio.sleep(0.1)
        
        return True
    
    async def get_playlist_track_count(
        self, 
        access_token: str, 
        playlist_id: str
    ) -> int:
        """Get the number of tracks in a playlist."""
        response = await self.client.get(
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}",
            params={"fields": "tracks.total"},
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("tracks", {}).get("total", 0)
        
        return 0
    
    async def delete_playlist(self, access_token: str, playlist_id: str) -> bool:
        """Unfollow (delete) a playlist."""
        response = await self.client.delete(
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/followers",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        return response.status_code == 200
