"""Playlist processing service that orchestrates the entire workflow.

Classification Logic (updated):
1. Detect language for all songs using Gemini
2. Non-Hindi, Non-English, Non-Instrumental songs → {Language} playlists
3. For Hindi, English, and Instrumental songs:
   a. Build artist → songs map
   b. Classify each artist into one of the defined genres using Gemini
   c. Assign songs to playlists based on artist genre

Playlists are named simply by genre or language (e.g., "Pop", "Hindi", "Spanish").
Existing playlists with matching names are reused, allowing songs to accumulate.

Optimizations:
- Incremental scanning: Only fetch new songs since last scan
- Artist genre caching: Cached in Firebase, only call Gemini for new artists
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from collections import defaultdict

from .models import (
    Track, 
    ProcessingStatus, 
    StatusResponse
)
from .spotify_service import SpotifyService
from .gemini_service import GeminiService
from .firebase_service import get_firebase_service
from .config import get_settings

logger = logging.getLogger(__name__)

# Languages that get classified by artist genre into the 10 genres
CLASSIFIABLE_LANGUAGES = {"hindi", "english", "instrumental"}


class ProcessingState:
    """Holds the state of the current processing session."""
    
    def __init__(self):
        self.status: ProcessingStatus = ProcessingStatus.IDLE
        self.progress: float = 0.0
        self.message: str = ""
        self.total_songs: int = 0
        self.processed_songs: int = 0
        self.playlists_created: int = 0
        self.error: Optional[str] = None
        self.created_playlist_ids: List[str] = []
    
    def to_response(self) -> StatusResponse:
        return StatusResponse(
            status=self.status,
            progress=self.progress,
            message=self.message,
            total_songs=self.total_songs,
            processed_songs=self.processed_songs,
            playlists_created=self.playlists_created,
            error=self.error
        )


class ProcessingService:
    """Service that handles the complete processing pipeline."""
    
    def __init__(self):
        self.settings = get_settings()
        self.spotify = SpotifyService()
        self.gemini = GeminiService()
        
        # In-memory state per session (keyed by user_id)
        self.sessions: Dict[str, ProcessingState] = {}
    
    def get_state(self, user_id: str) -> ProcessingState:
        """Get or create processing state for a user."""
        if user_id not in self.sessions:
            self.sessions[user_id] = ProcessingState()
        return self.sessions[user_id]
    
    def clear_state(self, user_id: str):
        """Clear the processing state for a user."""
        if user_id in self.sessions:
            del self.sessions[user_id]
    
    async def process(self, access_token: str, user_id: str):
        """
        Main processing pipeline with incremental scanning.
        
        1. Check if first scan or incremental
        2. Fetch liked songs (only new ones if incremental)
        3. Detect languages using Gemini
        4. Route non-Hindi/English/Instrumental to {Language} playlists
        5. For Hindi/English/Instrumental songs:
           a. Build artist → songs map
           b. Check cached artist genres, only call Gemini for new artists
           c. Assign songs to genre playlists based on artist genre
        6. Create and populate playlists
        """
        state = self.get_state(user_id)
        firebase = get_firebase_service()
        
        try:
            # ============================================================
            # Step 1: Fetch liked songs (incremental if not first scan)
            # ============================================================
            state.status = ProcessingStatus.FETCHING_SONGS
            state.message = "Checking for new songs..."
            state.progress = 0.02
            
            # Get last fetch timestamp
            last_fetch_timestamp = await firebase.get_last_fetch_timestamp(user_id)
            is_first_scan = last_fetch_timestamp is None
            
            if is_first_scan:
                state.message = "First scan - fetching all liked songs..."
                logger.info(f"First scan for user {user_id[:8]}***")
            else:
                state.message = "Fetching new liked songs..."
                logger.info(f"Incremental scan for user {user_id[:8]}*** (since {last_fetch_timestamp})")
            
            state.progress = 0.05
            
            # Record the timestamp NOW (before fetch) so we don't miss songs
            current_fetch_timestamp = datetime.now(timezone.utc).isoformat()
            
            # Fetch songs (incremental if we have a previous timestamp)
            tracks = await self.spotify.fetch_all_liked_songs(
                access_token, 
                max_songs=self.settings.max_liked_songs,
                since_timestamp=last_fetch_timestamp  # None for first scan = fetch all
            )
            
            # Save the new fetch timestamp
            await firebase.update_fetch_timestamp(user_id, current_fetch_timestamp)
            
            state.total_songs = len(tracks)
            
            if is_first_scan:
                logger.info(f"First scan: fetched {len(tracks)} total tracks for user {user_id[:8]}***")
            else:
                logger.info(f"Incremental scan: fetched {len(tracks)} NEW tracks for user {user_id[:8]}***")
            
            if not tracks:
                state.status = ProcessingStatus.COMPLETED
                if is_first_scan:
                    state.message = "No liked songs found."
                else:
                    state.message = "No new songs to organize!"
                state.progress = 1.0
                return
            
            # ============================================================
            # Step 2: Language Detection using Gemini
            # ============================================================
            state.status = ProcessingStatus.DETECTING_LANGUAGES
            state.message = "Detecting song languages..."
            state.progress = 0.10
            
            # Categorize tracks by language detection
            language_based_tracks: Dict[str, List[Track]] = defaultdict(list)  # Other languages
            classifiable_tracks: List[Track] = []  # Hindi, English, Instrumental
            
            # Process in batches for language detection
            batch_size = self.settings.batch_size
            total_batches = (len(tracks) + batch_size - 1) // batch_size
            
            for i in range(0, len(tracks), batch_size):
                batch = tracks[i:i + batch_size]
                current_batch = i // batch_size + 1
                
                state.message = f"Detecting languages ({current_batch}/{total_batches})..."
                state.progress = 0.10 + (0.15 * current_batch / total_batches)
                
                try:
                    result = await self.gemini.detect_languages(batch)
                    
                    # Create a lookup for quick access
                    detection_map = {d.track_id: d for d in result.detections}
                    
                    for track in batch:
                        detection = detection_map.get(track.id)
                        
                        if detection:
                            language = detection.language.lower()
                            track.detected_language = detection.language
                            
                            # Check if instrumental or classifiable language
                            if detection.is_instrumental:
                                track.detected_language = "Instrumental"
                                classifiable_tracks.append(track)
                            elif language in CLASSIFIABLE_LANGUAGES:
                                classifiable_tracks.append(track)
                            else:
                                # Other languages → {Language} playlist
                                language_based_tracks[detection.language].append(track)
                        else:
                            # Fallback: assume English if detection failed
                            track.detected_language = "English"
                            classifiable_tracks.append(track)
                    
                except Exception as e:
                    logger.error(f"Language detection batch failed: {e}")
                    # Fallback: treat all as English (classifiable)
                    for track in batch:
                        track.detected_language = "English"
                        classifiable_tracks.append(track)
                
                # Small delay to avoid rate limits
                await asyncio.sleep(0.3)
            
            logger.info(
                f"Language detection complete: "
                f"{len(classifiable_tracks)} Hindi/English/Instrumental, "
                f"{sum(len(t) for t in language_based_tracks.values())} Other languages"
            )
            
            # ============================================================
            # Step 3: Build Artist → Songs Map
            # ============================================================
            state.status = ProcessingStatus.BUILDING_ARTIST_MAP
            state.message = "Building artist map..."
            state.progress = 0.30
            
            # artist_name -> list of track objects
            artist_songs_map: Dict[str, List[Track]] = defaultdict(list)
            
            for track in classifiable_tracks:
                for artist in track.artists:
                    # Normalize artist name for consistency
                    artist_normalized = artist.strip()
                    if artist_normalized:
                        artist_songs_map[artist_normalized].append(track)
            
            all_artists = list(artist_songs_map.keys())
            logger.info(f"Built artist map with {len(all_artists)} unique artists")
            
            # ============================================================
            # Step 4: Classify Artists by Genre (with caching)
            # ============================================================
            state.status = ProcessingStatus.CLASSIFYING_ARTISTS
            state.message = "Classifying artists by genre..."
            state.progress = 0.35
            
            # artist_name -> genre
            artist_genre_map: Dict[str, str] = {}
            
            # First, check the cache for known artists
            state.message = "Checking artist genre cache..."
            cached_genres = await firebase.get_cached_artist_genres(all_artists)
            
            # Add cached genres to our map
            artist_genre_map.update(cached_genres)
            
            # Find artists we need to classify with Gemini
            uncached_artists = [a for a in all_artists if a not in cached_genres]
            
            if uncached_artists:
                logger.info(f"Cache hit: {len(cached_genres)}, need to classify: {len(uncached_artists)}")
                
                # New genres to save to cache after processing
                new_artist_genres: Dict[str, str] = {}
                
                # Process uncached artists in batches
                artist_batch_size = 30
                total_artist_batches = (len(uncached_artists) + artist_batch_size - 1) // artist_batch_size
                
                for i in range(0, len(uncached_artists), artist_batch_size):
                    artist_batch = uncached_artists[i:i + artist_batch_size]
                    current_batch = i // artist_batch_size + 1
                    
                    state.message = f"Classifying new artists ({current_batch}/{total_artist_batches})..."
                    state.progress = 0.35 + (0.20 * current_batch / total_artist_batches)
                    
                    try:
                        result = await self.gemini.classify_artists(artist_batch)
                        
                        for classification in result.classifications:
                            artist_genre_map[classification.artist_name] = classification.genre
                            new_artist_genres[classification.artist_name] = classification.genre
                        
                        # Handle failed artists - default to Pop
                        for failed_artist in result.failed_artists:
                            artist_genre_map[failed_artist] = "Pop"
                            new_artist_genres[failed_artist] = "Pop"
                            logger.warning(f"Artist '{failed_artist}' defaulted to Pop")
                        
                    except Exception as e:
                        logger.error(f"Artist classification batch failed: {e}")
                        # Fallback: assign Pop to all artists in this batch
                        for artist in artist_batch:
                            if artist not in artist_genre_map:
                                artist_genre_map[artist] = "Pop"
                                new_artist_genres[artist] = "Pop"
                    
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.5)
                
                # Save new classifications to cache
                if new_artist_genres:
                    await firebase.save_artist_genres(new_artist_genres)
                    logger.info(f"Saved {len(new_artist_genres)} new artist genres to cache")
            else:
                logger.info(f"All {len(all_artists)} artists found in cache - no Gemini calls needed!")
                state.progress = 0.55
            
            logger.info(f"Classified {len(artist_genre_map)} artists into genres")
            
            # ============================================================
            # Step 5: Assign Songs to Playlists
            # ============================================================
            state.message = "Organizing songs into playlists..."
            state.progress = 0.58
            
            # Final playlist assignments: playlist_name -> list of track_ids
            playlist_assignments: Dict[str, Set[str]] = defaultdict(set)
            
            # 5a. Add language-based tracks (non Hindi/English/Instrumental)
            for language, tracks_list in language_based_tracks.items():
                # Use language name as playlist name
                playlist_name = language.title()
                for track in tracks_list:
                    playlist_assignments[playlist_name].add(track.id)
                logger.info(f"Assigned {len(tracks_list)} tracks to language: {playlist_name}")
            
            # 5b. Assign classifiable tracks based on artist genre
            for track in classifiable_tracks:
                # For tracks with multiple artists, we add to all artist genres
                # But if genres match, it's only added once (using set)
                assigned_genres = set()
                
                for artist in track.artists:
                    artist_normalized = artist.strip()
                    if artist_normalized in artist_genre_map:
                        genre = artist_genre_map[artist_normalized]
                        assigned_genres.add(genre)
                
                # If no genres found (shouldn't happen), default to Pop
                if not assigned_genres:
                    assigned_genres.add("Pop")
                
                # Add track to each assigned genre playlist
                for genre in assigned_genres:
                    playlist_assignments[genre].add(track.id)
            
            # Convert sets to lists
            playlist_assignments_final: Dict[str, List[str]] = {
                name: list(ids) for name, ids in playlist_assignments.items() if ids
            }
            
            state.processed_songs = len(tracks)
            
            # Log genre distribution
            for playlist_name, track_ids in playlist_assignments_final.items():
                logger.info(f"Playlist '{playlist_name}': {len(track_ids)} tracks")
            
            # ============================================================
            # Step 6: Create/Reuse playlists
            # ============================================================
            state.status = ProcessingStatus.CREATING_PLAYLISTS
            state.message = "Checking existing playlists..."
            state.progress = 0.60
            # Get user info for playlist creation
            user_info = await self.spotify.get_current_user(access_token)
            spotify_user_id = user_info.get("id")
            logger.debug(f"Current user's Spotify ID: {spotify_user_id}")
            
            # OPTIMIZATION: Fetch all user playlists ONCE to avoid repeated searches
            # This prevents creating duplicates if the playlist already exists
            all_user_playlists = await self.spotify.get_user_playlists(access_token)
            logger.debug(f"Total playlists in user's library: {len(all_user_playlists)}")
            
            # Debug: Log all playlists with their owners
            for p in all_user_playlists:  # First 10 for debugging
                owner_id = p.get('owner', {}).get('id', 'UNKNOWN')
                logger.debug(f"  Playlist: '{p.get('name')}' | Owner: {owner_id} | Match: {owner_id == spotify_user_id}")

            # Map existing playlists by name (only if owned by current user)
            # Use lowercase keys for case-insensitive matching
            existing_playlists_map = {
                p['name'].lower(): p for p in all_user_playlists 
                if p.get('owner', {}).get('id') == spotify_user_id
            }
            logger.info(f"Loaded {len(existing_playlists_map)} OWNED playlists for user (out of {len(all_user_playlists)} total)")
            
            # Debug: Log all existing playlist names for troubleshooting
            if existing_playlists_map:
                logger.debug(f"Existing playlist names (lowercase): {list(existing_playlists_map.keys())}")
            
            # Debug: Log target playlist names we're looking for
            logger.debug(f"Target playlist names: {list(playlist_assignments_final.keys())}")
            
            playlist_mapping: Dict[str, str] = {}  # playlist name -> playlist id
            total_playlists = len(playlist_assignments_final)
            created_count = 0
            
            state.message = "Preparing playlists..."

            for playlist_name in playlist_assignments_final.keys():
                try:
                    # Check if playlist already exists in our pre-fetched map (case-insensitive)
                    playlist_name_lower = playlist_name.lower()
                    if playlist_name_lower in existing_playlists_map:
                        playlist = existing_playlists_map[playlist_name_lower]
                        logger.info(f"Reusing existing playlist: {playlist.get('name')} ({playlist.get('id')})")
                    else:
                        # Create new playlist
                        logger.info(f"Creating new playlist: {playlist_name}")
                        playlist = await self.spotify.create_playlist(
                            access_token,
                            spotify_user_id,
                            playlist_name,
                            description=f"Auto-organized by Spotify Housekeeping",
                            public=True, 
                        )
                        # Add to map so we don't create it again if referenced twice (unlikely but safe)
                        existing_playlists_map[playlist_name_lower] = playlist
                        
                    playlist_id = playlist.get("id")
                    playlist_mapping[playlist_name] = playlist_id
                    
                    if playlist_id not in state.created_playlist_ids:
                        state.created_playlist_ids.append(playlist_id)
                        state.playlists_created += 1
                    
                    created_count += 1
                    state.progress = 0.60 + (0.15 * created_count / max(total_playlists, 1))
                    state.message = f"Preparing playlist: {playlist_name}"
                    
                except Exception as e:
                    logger.error(f"Failed to get/create playlist {playlist_name}: {e}")
                
                # Small delay between operations
                await asyncio.sleep(0.1)
            
            # ============================================================
            # Step 7: Populate playlists
            # ============================================================
            state.status = ProcessingStatus.POPULATING_PLAYLISTS
            state.message = "Adding songs to playlists..."
            state.progress = 0.75
            
            playlists_populated = 0
            
            for playlist_name, playlist_id in playlist_mapping.items():
                track_ids = playlist_assignments_final[playlist_name]
                track_uris = [f"spotify:track:{tid}" for tid in track_ids]
                
                try:
                    await self.spotify.add_tracks_to_playlist(
                        access_token,
                        playlist_id,
                        track_uris
                    )
                    
                    playlists_populated += 1
                    state.progress = 0.75 + (0.15 * playlists_populated / max(len(playlist_mapping), 1))
                    state.message = f"Added {len(track_ids)} songs to {playlist_name}..."
                    
                    logger.info(f"Added {len(track_ids)} tracks to {playlist_name}")
                    
                except Exception as e:
                    logger.error(f"Failed to populate playlist {playlist_name}: {e}")
            
            # ============================================================
            # Step 8: Cleanup empty playlists
            # ============================================================
            state.status = ProcessingStatus.CLEANING_UP
            state.message = "Cleaning up empty playlists..."
            state.progress = 0.92
            
            for playlist_id in state.created_playlist_ids:
                try:
                    count = await self.spotify.get_playlist_track_count(access_token, playlist_id)
                    if count == 0:
                        await self.spotify.delete_playlist(access_token, playlist_id)
                        state.playlists_created -= 1
                        logger.info(f"Deleted empty playlist: {playlist_id}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup playlist {playlist_id}: {e}")
            
            # ============================================================
            # Complete!
            # ============================================================
            state.status = ProcessingStatus.COMPLETED
            state.message = "Housekeeping done!"
            state.progress = 1.0
            
            logger.info(
                f"Processing completed for user {user_id}. "
                f"Processed {state.processed_songs} songs into {state.playlists_created} playlists."
            )
            
        except Exception as e:
            logger.error(f"Processing failed for user {user_id}: {e}")
            state.status = ProcessingStatus.ERROR
            state.error = str(e)
            state.message = "An error occurred during processing."
            raise
    
    async def close(self):
        """Cleanup resources."""
        await self.spotify.close()
        await self.gemini.close()


# Singleton instance
_processing_service_instance: Optional[ProcessingService] = None


def get_processing_service() -> ProcessingService:
    """Get or create singleton ProcessingService instance."""
    global _processing_service_instance
    if _processing_service_instance is None:
        _processing_service_instance = ProcessingService()
    return _processing_service_instance


def set_processing_service(instance: ProcessingService):
    """Set the global ProcessingService instance (used during app startup)."""
    global _processing_service_instance
    _processing_service_instance = instance
