"""Pydantic models for request/response validation."""

from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class GenreName(str, Enum):
    """
    Strict enum of the 10 genres for classification.
    Used for Hindi, English, and Instrumental songs.
    """
    
    POP = "Pop"
    PARTY = "Party"
    HIPHOP = "Hip-Hop"
    ROCK = "Rock"
    ROMANTIC = "Romantic"
    INDIE = "Indie"
    BOLLYWOOD_PARTY = "Bollywood Party"
    DESI_INDIE = "Desi Indie"
    INSTRUMENTAL = "Instrumental"
    BOLLYWOOD_ROMANTIC = "Bollywood Romantic"
    DESI_HIP_HOP = "Desi Hip-Hop"
    SOUL = "Soul"
    JAZZ = "Jazz"


class Track(BaseModel):
    """Spotify track information."""
    
    id: str
    name: str
    artists: List[str]
    album: str
    release_year: Optional[int] = None
    duration_ms: int = 0
    popularity: int = 0
    added_at: Optional[str] = None  # ISO timestamp when song was liked
    
    # Audio features (kept for potential future use)
    energy: Optional[float] = None
    tempo: Optional[float] = None
    valence: Optional[float] = None
    danceability: Optional[float] = None
    loudness: Optional[float] = None
    speechiness: Optional[float] = None
    acousticness: Optional[float] = None
    instrumentalness: Optional[float] = None
    
    # Language detection result
    detected_language: Optional[str] = None


class TrackClassification(BaseModel):
    """Classification result for a track."""
    
    track_id: str
    playlist: str  # Can be a genre name or language name


class LanguageDetectionResult(BaseModel):
    """Result of language detection for a track."""
    
    track_id: str
    language: str  # e.g., "Hindi", "English", "Spanish", "French", etc.
    is_instrumental: bool = False


class BatchLanguageResult(BaseModel):
    """Result of language detection for a batch of tracks."""
    
    detections: List[LanguageDetectionResult]
    failed_track_ids: List[str] = []


class ArtistGenreResult(BaseModel):
    """Result of genre classification for an artist."""
    
    artist_name: str
    genre: str


class BatchArtistGenreResult(BaseModel):
    """Result of genre classification for a batch of artists."""
    
    classifications: List[ArtistGenreResult]
    failed_artists: List[str] = []


class BatchClassificationResult(BaseModel):
    """Result of classifying a batch of tracks."""
    
    classifications: List[TrackClassification]
    failed_track_ids: List[str] = []


class ProcessingStatus(str, Enum):
    """Status of the processing pipeline."""
    
    IDLE = "idle"
    FETCHING_SONGS = "fetching_songs"
    DETECTING_LANGUAGES = "detecting_languages"
    BUILDING_ARTIST_MAP = "building_artist_map"
    CLASSIFYING_ARTISTS = "classifying_artists"
    CREATING_PLAYLISTS = "creating_playlists"
    POPULATING_PLAYLISTS = "populating_playlists"
    CLEANING_UP = "cleaning_up"
    COMPLETED = "completed"
    ERROR = "error"


class StatusResponse(BaseModel):
    """Response for /process/status endpoint."""
    
    status: ProcessingStatus
    progress: float = 0.0  # 0.0 to 1.0
    message: str = ""
    total_songs: int = 0
    processed_songs: int = 0
    playlists_created: int = 0
    error: Optional[str] = None


class AuthResponse(BaseModel):
    """Response for successful authentication."""
    
    success: bool
    message: str
    redirect_url: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response."""
    
    error: str
    detail: str
