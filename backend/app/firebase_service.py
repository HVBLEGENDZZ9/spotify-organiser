"""Firebase Admin SDK integration service.

Handles:
- Firebase Admin SDK initialization
- User authentication via Firebase ID tokens
- Firestore database operations for user data
- Secure token encryption/decryption for Spotify tokens
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from functools import lru_cache

import firebase_admin
from firebase_admin import credentials, auth, firestore
from cryptography.fernet import Fernet

from .config import get_settings

logger = logging.getLogger(__name__)


class FirebaseService:
    """Service for Firebase Authentication and Firestore operations."""
    
    _instance: Optional['FirebaseService'] = None
    _initialized: bool = False
    
    def __new__(cls):
        """Singleton pattern to ensure only one Firebase app instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if FirebaseService._initialized:
            return
            
        self.settings = get_settings()
        self._init_firebase()
        self._init_encryption()
        FirebaseService._initialized = True
    
    def _init_firebase(self):
        """Initialize Firebase Admin SDK."""
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(self.settings.firebase_credentials_path)
                firebase_admin.initialize_app(cred, {
                    'projectId': self.settings.firebase_project_id
                })
                logger.info("Firebase Admin SDK initialized successfully")
            
            self.db = firestore.client()
            self.users_collection = self.db.collection('users')
            self.scan_logs_collection = self.db.collection('scan_logs')
            self.artist_genres_collection = self.db.collection('artist_genres')
            
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            raise
    
    def _init_encryption(self):
        """Initialize Fernet encryption for token storage."""
        try:
            if self.settings.encryption_key:
                self.fernet = Fernet(self.settings.encryption_key.encode())
            else:
                # Generate a key for development (should be set in production)
                logger.warning("No encryption key set, generating temporary key")
                self.fernet = Fernet(Fernet.generate_key())
        except Exception as e:
            logger.error(f"Failed to initialize encryption: {e}")
            raise
    
    def _encrypt(self, data: str) -> str:
        """Encrypt sensitive data."""
        return self.fernet.encrypt(data.encode()).decode()
    
    def _decrypt(self, encrypted_data: str) -> str:
        """Decrypt sensitive data."""
        return self.fernet.decrypt(encrypted_data.encode()).decode()
    
    # ============== Authentication ==============
    
    async def verify_id_token(self, id_token: str) -> Dict[str, Any]:
        """
        Verify a Firebase ID token and return the decoded claims.
        
        Args:
            id_token: The Firebase ID token from the client
            
        Returns:
            Decoded token claims including uid, email, etc.
            
        Raises:
            ValueError: If token is invalid or expired
        """
        try:
            decoded_token = auth.verify_id_token(id_token)
            logger.info(f"Verified token for user: {decoded_token.get('uid')}")
            return decoded_token
        except auth.InvalidIdTokenError as e:
            logger.warning(f"Invalid ID token: {e}")
            raise ValueError("Invalid authentication token")
        except auth.ExpiredIdTokenError as e:
            logger.warning(f"Expired ID token: {e}")
            raise ValueError("Authentication token has expired")
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            raise ValueError("Authentication failed")
    
    # ============== User Management ==============
    
    async def get_or_create_user(self, firebase_uid: str, email: str, display_name: str = "") -> Dict[str, Any]:
        """
        Get an existing user or create a new one.
        
        Args:
            firebase_uid: Firebase user ID
            email: User's email address
            display_name: User's display name
            
        Returns:
            User document data
        """
        user_ref = self.users_collection.document(firebase_uid)
        user_doc = user_ref.get()
        
        if user_doc.exists:
            logger.info(f"Found existing user: {firebase_uid[:8]}***")
            return user_doc.to_dict()
        
        # Create new user
        now = datetime.now(timezone.utc)
        user_data = {
            'email': email,
            'display_name': display_name or email.split('@')[0],
            'created_at': now,
            
            # Spotify linkage (not linked yet)
            'spotify_user_id': None,
            'spotify_access_token': None,
            'spotify_refresh_token': None,
            'spotify_token_expires_at': None,
            'spotify_linked_at': None,
            
            # Subscription (none yet)
            'subscription_status': 'none',
            'subscription_start_date': None,
            'subscription_end_date': None,
            
            # Processing stats
            'last_scan_at': None,
            'last_scan_songs_processed': 0,
            'next_scan_at': None,
            'total_songs_organized': 0,
            
            # Incremental scanning - timestamp of last fetch
            'last_liked_songs_fetch_at': None
        }
        
        user_ref.set(user_data)
        logger.info(f"Created new user: {firebase_uid[:8]}***")
        
        return user_data
    
    async def get_user(self, firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get user by Firebase UID."""
        user_doc = self.users_collection.document(firebase_uid).get()
        if user_doc.exists:
            return user_doc.to_dict()
        return None
    
    async def update_user(self, firebase_uid: str, updates: Dict[str, Any]) -> bool:
        """Update user document fields."""
        try:
            self.users_collection.document(firebase_uid).update(updates)
            logger.info(f"Updated user {firebase_uid[:8]}***: {list(updates.keys())}")
            return True
        except Exception as e:
            logger.error(f"Failed to update user {firebase_uid}: {e}")
            return False
    
    # ============== Spotify Token Management ==============
    
    async def save_spotify_tokens(
        self, 
        firebase_uid: str, 
        spotify_user_id: str,
        access_token: str, 
        refresh_token: str,
        expires_at: datetime
    ) -> bool:
        """
        Save Spotify tokens for a user (encrypted).
        
        Args:
            firebase_uid: Firebase user ID
            spotify_user_id: Spotify user ID
            access_token: Spotify access token
            refresh_token: Spotify refresh token
            expires_at: Token expiration time
        """
        try:
            updates = {
                'spotify_user_id': spotify_user_id,
                'spotify_access_token': self._encrypt(access_token),
                'spotify_refresh_token': self._encrypt(refresh_token),
                'spotify_token_expires_at': expires_at,
                'spotify_linked_at': datetime.now(timezone.utc)
            }
            
            return await self.update_user(firebase_uid, updates)
        except Exception as e:
            logger.error(f"Failed to save Spotify tokens: {e}")
            return False
    
    async def get_spotify_tokens(self, firebase_uid: str) -> Optional[Dict[str, Any]]:
        """
        Get decrypted Spotify tokens for a user.
        
        Returns:
            Dict with access_token, refresh_token, expires_at, spotify_user_id
            or None if not linked
        """
        user = await self.get_user(firebase_uid)
        if not user or not user.get('spotify_access_token'):
            return None
        
        try:
            return {
                'spotify_user_id': user.get('spotify_user_id'),
                'access_token': self._decrypt(user['spotify_access_token']),
                'refresh_token': self._decrypt(user['spotify_refresh_token']),
                'expires_at': user.get('spotify_token_expires_at')
            }
        except Exception as e:
            logger.error(f"Failed to decrypt Spotify tokens: {e}")
            return None
    
    async def update_spotify_access_token(
        self, 
        firebase_uid: str, 
        access_token: str,
        expires_at: datetime
    ) -> bool:
        """Update only the access token (after refresh)."""
        try:
            updates = {
                'spotify_access_token': self._encrypt(access_token),
                'spotify_token_expires_at': expires_at
            }
            return await self.update_user(firebase_uid, updates)
        except Exception as e:
            logger.error(f"Failed to update access token: {e}")
            return False
    
    # ============== Subscription Management ==============
    
    async def activate_free_account(
        self, 
        firebase_uid: str,
        duration_days: int = 365
    ) -> bool:
        """
        Activate a free account (no payment required).
        
        Args:
            firebase_uid: Firebase user ID
            duration_days: Subscription duration
        """
        now = datetime.now(timezone.utc)
        end_date = datetime.fromtimestamp(
            now.timestamp() + (duration_days * 24 * 60 * 60),
            tz=timezone.utc
        )
        
        updates = {
            'subscription_status': 'active',
            'subscription_start_date': now,
            'subscription_end_date': end_date,
            # Schedule first scan
            'next_scan_at': now
        }
        
        success = await self.update_user(firebase_uid, updates)
        
        if success:
            logger.info(f"Activated free account for user {firebase_uid[:8]}***")
        
        return success
    
    async def expire_subscription(self, firebase_uid: str) -> bool:
        """Mark a subscription as expired."""
        updates = {
            'subscription_status': 'expired',
            'next_scan_at': None
        }
        return await self.update_user(firebase_uid, updates)
    
    async def get_active_subscribers(self) -> List[Dict[str, Any]]:
        """Get all users with active subscriptions."""
        query = self.users_collection.where('subscription_status', '==', 'active')
        docs = query.stream()
        
        users = []
        for doc in docs:
            user_data = doc.to_dict()
            user_data['uid'] = doc.id
            users.append(user_data)
        
        logger.info(f"Found {len(users)} active subscribers")
        return users
    
    async def get_expiring_subscriptions(self, days_until_expiry: int) -> List[Dict[str, Any]]:
        """Get users whose subscriptions expire within the specified days."""
        now = datetime.now(timezone.utc)
        target_date = datetime.fromtimestamp(
            now.timestamp() + (days_until_expiry * 24 * 60 * 60),
            tz=timezone.utc
        )
        
        # Get subscriptions expiring on the target date (within that day)
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        query = (
            self.users_collection
            .where('subscription_status', '==', 'active')
            .where('subscription_end_date', '>=', start_of_day)
            .where('subscription_end_date', '<=', end_of_day)
        )
        
        docs = query.stream()
        
        users = []
        for doc in docs:
            user_data = doc.to_dict()
            user_data['uid'] = doc.id
            users.append(user_data)
        
        return users
    
    async def get_active_subscriber_count(self) -> int:
        """Get the count of currently active subscribers."""
        query = self.users_collection.where('subscription_status', '==', 'active')
        docs = list(query.stream())
        count = len(docs)
        logger.info(f"Active subscriber count: {count}")
        return count
    
    async def log_interest_click(self, firebase_uid: str, email: str) -> bool:
        """
        Log when a user clicks subscribe after limit is reached.
        
        This helps track interest for V2 marketing and planning.
        """
        try:
            interest_collection = self.db.collection('interested_users')
            
            # Check if already logged
            existing = interest_collection.where('firebase_uid', '==', firebase_uid).limit(1).stream()
            if list(existing):
                logger.info(f"Interest already logged for user {firebase_uid}")
                return True
            
            interest_data = {
                'firebase_uid': firebase_uid,
                'email': email,
                'clicked_at': datetime.now(timezone.utc),
                'notified': False  # For future V2 notification
            }
            
            interest_collection.add(interest_data)
            logger.info(f"Logged interest for user (ID: {firebase_uid[:8]}***)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to log interest: {e}")
            return False
    
    # ============== Scan Logging ==============
    
    async def log_scan_start(self, firebase_uid: str) -> str:
        """Log the start of a scan and return the log ID."""
        now = datetime.now(timezone.utc)
        log_data = {
            'user_id': firebase_uid,
            'started_at': now,
            'completed_at': None,
            'status': 'running',
            'songs_processed': 0,
            'playlists_updated': 0,
            'error': None
        }
        
        doc_ref = self.scan_logs_collection.add(log_data)
        return doc_ref[1].id
    
    async def log_scan_complete(
        self, 
        log_id: str, 
        songs_processed: int, 
        playlists_updated: int,
        error: Optional[str] = None
    ):
        """Log scan completion."""
        status = 'failed' if error else 'completed'
        
        self.scan_logs_collection.document(log_id).update({
            'completed_at': datetime.now(timezone.utc),
            'status': status,
            'songs_processed': songs_processed,
            'playlists_updated': playlists_updated,
            'error': error
        })
    
    async def update_user_scan_stats(
        self, 
        firebase_uid: str, 
        songs_processed: int,
        next_scan_at: datetime
    ):
        """Update user's scan statistics after a successful scan."""
        user = await self.get_user(firebase_uid)
        total = (user.get('total_songs_organized', 0) if user else 0) + songs_processed
        
        updates = {
            'last_scan_at': datetime.now(timezone.utc),
            'last_scan_songs_processed': songs_processed,
            'next_scan_at': next_scan_at,
            'total_songs_organized': total
        }
        
        await self.update_user(firebase_uid, updates)
    
    # ============== Account Management ==============
    
    async def delete_user_account(self, firebase_uid: str) -> bool:
        """
        Delete user account and all associated data.
        
        Args:
            firebase_uid: Firebase user ID
            
        Returns:
            True if successful
        """
        try:
            # Delete user document
            self.users_collection.document(firebase_uid).delete()
            
            # Delete scan logs
            scan_logs = self.scan_logs_collection.where('user_id', '==', firebase_uid).stream()
            for log in scan_logs:
                log.reference.delete()
            
            # Delete from interested users if present
            interest_docs = self.db.collection('interested_users').where('firebase_uid', '==', firebase_uid).stream()
            for doc in interest_docs:
                doc.reference.delete()
            
            logger.info(f"Deleted account for user {firebase_uid[:8]}***")
            return True
        except Exception as e:
            logger.error(f"Failed to delete account: {e}")
            return False
    
    # ============== Incremental Scanning ==============
    
    async def get_last_fetch_timestamp(self, firebase_uid: str) -> Optional[str]:
        """
        Get the timestamp of when liked songs were last fetched for a user.
        
        Returns:
            ISO timestamp string or None if this is the first scan
        """
        user = await self.get_user(firebase_uid)
        if not user:
            return None
        
        timestamp = user.get('last_liked_songs_fetch_at')
        if timestamp and hasattr(timestamp, 'isoformat'):
            return timestamp.isoformat()
        return timestamp
    
    async def update_fetch_timestamp(self, firebase_uid: str, timestamp: str) -> bool:
        """
        Update the timestamp of when liked songs were fetched.
        
        Args:
            firebase_uid: User ID
            timestamp: ISO timestamp string
            
        Returns:
            True if successful
        """
        return await self.update_user(firebase_uid, {
            'last_liked_songs_fetch_at': timestamp
        })
    
    # ============== Artist Genre Cache ==============
    
    async def get_cached_artist_genres(self, artist_names: List[str]) -> Dict[str, str]:
        """
        Get cached genres for a list of artists.
        
        Args:
            artist_names: List of artist names to look up
            
        Returns:
            Dict mapping artist name to genre (only for found artists)
        """
        if not artist_names:
            return {}
        
        cached_genres = {}
        
        # Firestore 'in' queries are limited to 30 items
        batch_size = 30
        
        for i in range(0, len(artist_names), batch_size):
            batch_names = artist_names[i:i + batch_size]
            
            try:
                # Query for artists in this batch
                query = self.artist_genres_collection.where('name', 'in', batch_names)
                docs = list(query.stream())
                
                for doc in docs:
                    data = doc.to_dict()
                    artist_name = data.get('name')
                    genre = data.get('genre')
                    if artist_name and genre:
                        cached_genres[artist_name] = genre
                        
            except Exception as e:
                logger.warning(f"Failed to fetch cached genres batch: {e}")
        
        logger.info(f"Found {len(cached_genres)}/{len(artist_names)} artists in cache")
        return cached_genres
    
    async def save_artist_genres(self, artist_genres: Dict[str, str]) -> int:
        """
        Save artist genre classifications to the global cache.
        
        Args:
            artist_genres: Dict mapping artist name to genre
            
        Returns:
            Number of artists saved
        """
        if not artist_genres:
            return 0
        
        saved_count = 0
        now = datetime.now(timezone.utc)
        
        # Use batched writes for efficiency
        batch = self.db.batch()
        batch_count = 0
        max_batch_size = 500  # Firestore batch limit
        
        for artist_name, genre in artist_genres.items():
            # Use a normalized version of artist name as document ID
            doc_id = artist_name.lower().replace('/', '_').replace('\\', '_')[:100]
            doc_ref = self.artist_genres_collection.document(doc_id)
            
            batch.set(doc_ref, {
                'name': artist_name,
                'genre': genre,
                'created_at': now,
                'updated_at': now
            }, merge=True)
            
            batch_count += 1
            saved_count += 1
            
            # Commit batch if we hit the limit
            if batch_count >= max_batch_size:
                batch.commit()
                batch = self.db.batch()
                batch_count = 0
        
        # Commit any remaining writes
        if batch_count > 0:
            batch.commit()
        
        logger.info(f"Saved {saved_count} artist genres to cache")
        return saved_count


@lru_cache
def get_firebase_service() -> FirebaseService:
    """Get cached Firebase service instance."""
    return FirebaseService()

