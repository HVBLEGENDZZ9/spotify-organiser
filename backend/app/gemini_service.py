"""Gemini AI service for language detection and artist genre classification using REST API.

This service handles:
1. Language detection for tracks
2. Genre classification for artists
"""

import json
import logging
from typing import List
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import get_settings
from .models import (
    Track, 
    LanguageDetectionResult, 
    BatchLanguageResult,
    ArtistGenreResult,
    BatchArtistGenreResult,
    GenreName
)

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# Valid genres for artist classification
VALID_GENRES = [genre.value for genre in GenreName]


class GeminiService:
    """Service for AI-powered language detection and artist genre classification using Gemini REST API."""
    
    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=60.0)
        self.api_key = self.settings.gemini_api_key
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    def _build_language_detection_prompt(self, tracks: List[Track]) -> str:
        """Build the language detection prompt for Gemini."""
        tracks_data = []
        for track in tracks:
            tracks_data.append({
                "id": track.id,
                "name": track.name,
                "artists": track.artists,
                "album": track.album
            })
        
        prompt = f"""You are a music language detection expert. Analyze each song and determine its PRIMARY language.

TRACK DATA:
{json.dumps(tracks_data, indent=2)}

INSTRUCTIONS:
1. Identify the primary language of vocals for each track
2. Common languages to detect: Hindi, English, Spanish, French, German, Italian, Portuguese, Japanese, Korean, Chinese, Arabic, Russian, Marathi, Bengali, Telugu, Tamil, Punjabi, Gujarati, Kannada, Malayalam
3. If the track appears to be instrumental (no vocals), mark it as "Instrumental"
4. Look for language hints in the track name, artist name, and album name
5. For Indian artists, identify specific regional languages rather than just labeling as "Indian"

RESPOND WITH ONLY A JSON ARRAY in this exact format:
[
  {{"track_id": "spotify_id_1", "language": "Hindi", "is_instrumental": false}},
  {{"track_id": "spotify_id_2", "language": "English", "is_instrumental": false}},
  {{"track_id": "spotify_id_3", "language": "Instrumental", "is_instrumental": true}}
]

IMPORTANT:
- Each track must have exactly one language
- Use proper language names (capitalize first letter)
- If unsure between Hindi and English, prefer the one that seems more likely based on artist/album names
- Mark as "Instrumental" if the track has no vocals"""
        
        return prompt
    
    def _build_artist_genre_prompt(self, artists: List[str]) -> str:
        """Build the artist genre classification prompt for Gemini."""
        prompt = f"""You are a music genre classification expert. Classify each artist into EXACTLY ONE of the following genres based on their primary musical style:

AVAILABLE GENRES (choose ONLY from this list):
1. Pop - Mainstream pop artists, catchy melodies, chart-toppers
2. Party - High energy party music, electronic dance music, club music artists
3. Hip-Hop - Rap artists, hip-hop producers, trap, grime
4. Rock - Rock bands, alternative rock, classic rock artists
5. Romantic - Romantic ballad singers, love song specialists
6. Indie - Independent artists, alternative music, non-mainstream
7. Bollywood Party - High-energy Bollywood/Hindi party music, item songs
8. Desi Indie - Indian indie artists, fusion, non-Bollywood Indian music
9. Instrumental - Instrumental artists, orchestras, producers of instrumental music
10. Bollywood Romantic - Romantic Bollywood/Hindi songs, melodious film music
11. Desi Hip-Hop - Indian hip-hop artists, desi rap, regional and Hindi rap
12. Soul - Soulful vocals, R&B-influenced artists, emotional and groove-based music
13. Jazz - Jazz artists, smooth jazz, fusion, classic and contemporary jazz

ARTISTS TO CLASSIFY:
{json.dumps(artists, indent=2)}

CLASSIFICATION RULES:
- Each artist gets EXACTLY one genre
- Indian hip-hop artists/rap artists → Desi Hip-Hop
- Bollywood singers known for party songs → Bollywood Party
- Bollywood singers known for romantic songs → Bollywood Romantic
- Indian indie/fusion artists → Desi Indie
- Western indie artists → Indie
- If unsure, use the most fitting genre based on artist name patterns
- Rappers and hip-hop artists → Hip-Hop
- DJ/Electronic artists/High energy party music → Party
- Rock artists → Rock
- Romantic, love and ballad singers → Romantic
- Soulful vocals → Soul
- Jazz artists → Jazz
- Pop artists → Mainstream pop artists, catchy melodies, chart-toppers
- Instrumental artists → Instrumental artists, orchestras, producers of instrumental music

RESPOND WITH ONLY A JSON ARRAY in this exact format:
[
  {{"artist_name": "Artist Name 1", "genre": "Pop"}},
  {{"artist_name": "Artist Name 2", "genre": "Hip-Hop"}},
  {{"artist_name": "Artist Name 3", "genre": "Bollywood Romantic"}}
]

IMPORTANT:
- The genre MUST be exactly one of the 13 genres listed above
- Spell the genre exactly as shown (case-sensitive)
- Every artist in the input list must appear in the output"""
        
        return prompt
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((httpx.HTTPError, Exception)),
        reraise=True
    )
    async def detect_languages(self, tracks: List[Track]) -> BatchLanguageResult:
        """Detect languages for a batch of tracks using Gemini AI."""
        if not self.api_key:
            logger.warning("Gemini API key not configured. Using fallback language detection.")
            return self._fallback_language_detection(tracks)
        
        try:
            prompt = self._build_language_detection_prompt(tracks)
            
            # Call Gemini REST API
            response = await self.client.post(
                f"{GEMINI_API_URL}?key={self.api_key}",
                json={
                    "contents": [{
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "temperature": 0.2,  # Lower temperature for more consistent results
                        "maxOutputTokens": 4096,
                    }
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                logger.error(f"Gemini API error: {response.status_code} - {response.text}")
                return self._fallback_language_detection(tracks)
            
            data = response.json()
            
            # Extract text from response
            response_text = ""
            if "candidates" in data and len(data["candidates"]) > 0:
                candidate = data["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    parts = candidate["content"]["parts"]
                    if len(parts) > 0 and "text" in parts[0]:
                        response_text = parts[0]["text"].strip()
            
            if not response_text:
                logger.error("Empty response from Gemini")
                return self._fallback_language_detection(tracks)
            
            # Extract JSON from response (handle markdown code blocks)
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]
            
            detections_data = json.loads(response_text.strip())
            
            detections = []
            failed_ids = []
            
            for item in detections_data:
                track_id = item.get("track_id")
                language = item.get("language", "English")
                is_instrumental = item.get("is_instrumental", False)
                
                if track_id:
                    # Normalize language name
                    language = language.strip().title()
                    
                    # Handle instrumental case
                    if is_instrumental or language.lower() == "instrumental":
                        language = "Instrumental"
                        is_instrumental = True
                    
                    detections.append(LanguageDetectionResult(
                        track_id=track_id,
                        language=language,
                        is_instrumental=is_instrumental
                    ))
                else:
                    logger.warning(f"Missing track_id in detection result: {item}")
            
            # Handle any tracks that weren't detected
            detected_ids = {d.track_id for d in detections}
            for track in tracks:
                if track.id not in detected_ids:
                    failed_ids.append(track.id)
                    logger.warning(f"No language detected for track {track.id}")
            
            logger.info(f"Language detection complete: {len(detections)} detected, {len(failed_ids)} failed")
            
            return BatchLanguageResult(
                detections=detections,
                failed_track_ids=failed_ids
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response: {e}")
            return self._fallback_language_detection(tracks)
        except Exception as e:
            logger.error(f"Gemini language detection error: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((httpx.HTTPError, Exception)),
        reraise=True
    )
    async def classify_artists(self, artists: List[str]) -> BatchArtistGenreResult:
        """Classify a batch of artists into genres using Gemini AI."""
        if not artists:
            return BatchArtistGenreResult(classifications=[], failed_artists=[])
        
        if not self.api_key:
            logger.warning("Gemini API key not configured. Using fallback artist classification.")
            return self._fallback_artist_classification(artists)
        
        try:
            prompt = self._build_artist_genre_prompt(artists)
            
            # Call Gemini REST API
            response = await self.client.post(
                f"{GEMINI_API_URL}?key={self.api_key}",
                json={
                    "contents": [{
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "temperature": 0.3,  # Slightly higher for genre nuance
                        "maxOutputTokens": 4096,
                    }
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                logger.error(f"Gemini API error: {response.status_code} - {response.text}")
                return self._fallback_artist_classification(artists)
            
            data = response.json()
            
            # Extract text from response
            response_text = ""
            if "candidates" in data and len(data["candidates"]) > 0:
                candidate = data["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    parts = candidate["content"]["parts"]
                    if len(parts) > 0 and "text" in parts[0]:
                        response_text = parts[0]["text"].strip()
            
            if not response_text:
                logger.error("Empty response from Gemini for artist classification")
                return self._fallback_artist_classification(artists)
            
            # Extract JSON from response (handle markdown code blocks)
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]
            
            classifications_data = json.loads(response_text.strip())
            
            classifications = []
            failed_artists = []
            classified_names = set()
            
            for item in classifications_data:
                artist_name = item.get("artist_name")
                genre = item.get("genre")
                
                if artist_name and genre:
                    # Validate genre is in our allowed list
                    if genre in VALID_GENRES:
                        classifications.append(ArtistGenreResult(
                            artist_name=artist_name,
                            genre=genre
                        ))
                        classified_names.add(artist_name.lower())
                    else:
                        # Map to closest valid genre or default to Pop
                        mapped_genre = self._map_to_valid_genre(genre)
                        classifications.append(ArtistGenreResult(
                            artist_name=artist_name,
                            genre=mapped_genre
                        ))
                        classified_names.add(artist_name.lower())
                        logger.warning(f"Invalid genre '{genre}' for artist '{artist_name}', mapped to '{mapped_genre}'")
            
            # Handle any artists that weren't classified
            for artist in artists:
                if artist.lower() not in classified_names:
                    failed_artists.append(artist)
                    logger.warning(f"No genre classification for artist: {artist}")
            
            logger.info(f"Artist classification complete: {len(classifications)} classified, {len(failed_artists)} failed")
            
            return BatchArtistGenreResult(
                classifications=classifications,
                failed_artists=failed_artists
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response for artist classification: {e}")
            return self._fallback_artist_classification(artists)
        except Exception as e:
            logger.error(f"Gemini artist classification error: {e}")
            raise
    
    def _map_to_valid_genre(self, genre: str) -> str:
        """Map an invalid genre to the closest valid genre."""
        genre_lower = genre.lower()
        
        # Common mappings
        mappings = {
            "pop": "Pop",
            "dance": "Dance",
            "edm": "Dance",
            "electronic": "Dance",
            "hip hop": "Hip-Hop",
            "hiphop": "Hip-Hop",
            "rap": "Hip-Hop",
            "rock": "Rock",
            "alternative": "Rock",
            "romantic": "Romantic",
            "love": "Romantic",
            "ballad": "Romantic",
            "indie": "Indie",
            "alternative indie": "Indie",
            "bollywood party": "Bollywood Party",
            "party": "Bollywood Party",
            "item song": "Bollywood Party",
            "desi indie": "Desi Indie",
            "indian indie": "Desi Indie",
            "fusion": "Desi Indie",
            "instrumental": "Instrumental",
            "classical": "Instrumental",
            "orchestra": "Instrumental",
            "bollywood romantic": "Bollywood Romantic",
            "bollywood": "Bollywood Romantic",
            "filmi": "Bollywood Romantic",
        }
        
        for key, value in mappings.items():
            if key in genre_lower:
                return value
        
        return "Pop"  # Default fallback
    
    def _fallback_language_detection(self, tracks: List[Track]) -> BatchLanguageResult:
        """
        Fallback language detection using simple heuristics.
        
        Note: This does not rely on audio features since they may not be
        available for apps registered after November 2024.
        """
        logger.info("Using fallback language detection")
        
        detections = []
        
        # Common Hindi artist name patterns
        hindi_indicators = [
            "arijit", "singh", "kumar", "shreya", "sunidhi", "neha", "kakkar",
            "atif", "badshah", "honey", "yo yo", "raftaar", "divine", "raja",
            "kishore", "lata", "asha", "mohammed", "rafi", "mukesh", "rahman",
            "gulzar", "javed", "akhtar", "amit", "trivedi", "vishal", "shekar",
            "pritam", "shankar", "ehsaan", "loy", "salim", "sulaiman", "sachin",
            "jigar", "tanishk", "bagchi", "nucleya", "ritviz", "prateek", "kuhad"
        ]
        
        # Regional language indicators
        marathi_indicators = ["marathi", "sairat", "ajay-atul"]
        bengali_indicators = ["bengali", "rabindra", "tagore", "bangla"]
        tamil_indicators = ["tamil", "ar rahman", "anirudh", "harris"]
        telugu_indicators = ["telugu", "thaman", "anirudh"]
        
        # Instrumental indicators (for detecting without audio features)
        instrumental_indicators = [
            "instrumental", "orchestr", "soundtrack", "score", "theme",
            "piano version", "acoustic version", "karaoke", "bgm",
            "background music", "symphony", "concerto", "opus"
        ]
        
        for track in tracks:
            # Combine name and artist info for detection
            combined_text = f"{track.name} {' '.join(track.artists)} {track.album}".lower()
            
            # Check for instrumental based on name patterns (since audio features may not be available)
            # Also check audio features if they exist (for older apps)
            is_instrumental = False
            if any(ind in combined_text for ind in instrumental_indicators):
                is_instrumental = True
            elif track.instrumentalness and track.instrumentalness > 0.8:
                is_instrumental = True
            
            if is_instrumental:
                detections.append(LanguageDetectionResult(
                    track_id=track.id,
                    language="Instrumental",
                    is_instrumental=True
                ))
                continue
            
            # Check regional languages first
            if any(ind in combined_text for ind in marathi_indicators):
                detections.append(LanguageDetectionResult(
                    track_id=track.id,
                    language="Marathi",
                    is_instrumental=False
                ))
            elif any(ind in combined_text for ind in bengali_indicators):
                detections.append(LanguageDetectionResult(
                    track_id=track.id,
                    language="Bengali",
                    is_instrumental=False
                ))
            elif any(ind in combined_text for ind in tamil_indicators):
                detections.append(LanguageDetectionResult(
                    track_id=track.id,
                    language="Tamil",
                    is_instrumental=False
                ))
            elif any(ind in combined_text for ind in telugu_indicators):
                detections.append(LanguageDetectionResult(
                    track_id=track.id,
                    language="Telugu",
                    is_instrumental=False
                ))
            elif any(ind in combined_text for ind in hindi_indicators):
                detections.append(LanguageDetectionResult(
                    track_id=track.id,
                    language="Hindi",
                    is_instrumental=False
                ))
            else:
                # Default to English
                detections.append(LanguageDetectionResult(
                    track_id=track.id,
                    language="English",
                    is_instrumental=False
                ))
        
        return BatchLanguageResult(
            detections=detections,
            failed_track_ids=[]
        )
    
    def _fallback_artist_classification(self, artists: List[str]) -> BatchArtistGenreResult:
        """Fallback artist classification using simple heuristics."""
        logger.info("Using fallback artist classification")
        
        classifications = []
        
        # Artist name patterns for genre detection
        bollywood_romantic_indicators = [
            "arijit", "atif", "shreya", "lata", "kishore", "kumar sanu",
            "mohammed rafi", "mukesh", "alka", "udit", "sonu", "kk",
            # added
            "armaan malik", "jubin nautiyal", "rahat fateh ali khan",
            "palak muchhal", "sunidhi", "asha bhosle", "talat mahmood"
        ]

        bollywood_party_indicators = [
            "badshah", "yo yo", "honey", "neha kakkar", "mika", "daler",
            "sukhbir", "benny dayal", "vishal dadlani",
            # added
            "ikka", "guru randhawa", "kanika kapoor",
            "aftab shivdasani",  # common party playback association
            "shalmali kholgade", "meet bros"
        ]

        hiphop_indicators = [
            "divine", "raftaar", "emiway", "mc stan", "prabh deep", "seedhe maut",
            "drake", "kendrick", "j cole", "eminem", "kanye", "jay z",
            # added
            "nas", "travis scott", "future", "lil wayne",
            "tyler the creator", "21 savage",
            "kr$na", "karma", "ikka", "brodha v"
        ]

        desi_indie_indicators = [
            "prateek kuhad", "ritviz", "nucleya", "anuv jain", "when chai met toast",
            "the local train", "ankur tewari", "shankar mahadevan",
            # added
            "jasleen royal", "zaeden", "asur",
            "amit trivedi", "papon", "raghu dixit",
            "the yellow diary", "sanjeeta bhattacharya"
        ]

        rock_indicators = [
            "coldplay", "imagine dragons", "linkin park", "green day",
            "foo fighters", "nirvana", "metallica", "ac/dc",
            # added
            "queen", "guns n roses", "red hot chili peppers",
            "arctic monkeys", "the rolling stones",
            "pink floyd", "led zeppelin"
        ]

        dance_indicators = [
            "marshmello", "avicii", "calvin harris", "david guetta",
            "tiesto", "kygo", "alan walker", "martin garrix",
            # added
            "zedd", "deadmau5", "afrojack", "steve aoki",
            "diplo", "major lazer", "hardwell"
        ]
        
        for artist in artists:
            artist_lower = artist.lower()
            
            if any(ind in artist_lower for ind in bollywood_party_indicators):
                genre = "Bollywood Party"
            elif any(ind in artist_lower for ind in hiphop_indicators):
                genre = "Hip-Hop"
            elif any(ind in artist_lower for ind in desi_indie_indicators):
                genre = "Desi Indie"
            elif any(ind in artist_lower for ind in rock_indicators):
                genre = "Rock"
            elif any(ind in artist_lower for ind in dance_indicators):
                genre = "Dance"
            elif any(ind in artist_lower for ind in bollywood_romantic_indicators):
                genre = "Bollywood Romantic"
            else:
                # Default to Pop for unknown artists
                genre = "Pop"
            
            classifications.append(ArtistGenreResult(
                artist_name=artist,
                genre=genre
            ))
        
        return BatchArtistGenreResult(
            classifications=classifications,
            failed_artists=[]
        )
