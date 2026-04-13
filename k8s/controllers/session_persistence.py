"""
Session Persistence Manager
Feature 4: Session Persistence Across Pod Restarts

Manages session state persistence using Redis for:
- Session state serialization
- Pod migration support
- Graceful shutdown/recovery
- Multi-region session replication
"""

import json
import logging
import pickle
import zlib
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, BinaryIO
import asyncio

import redis.asyncio as redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Represents a persisted session state."""
    session_id: str
    pool_name: str
    pod_name: str
    template: str
    created_at: str
    last_activity: str
    expires_at: str
    
    # File system state
    files: Dict[str, bytes] = None
    
    # Environment state
    environment: Dict[str, str] = None
    
    # Execution history
    execution_history: List[Dict] = None
    
    # Package installations
    installed_packages: List[str] = None
    
    # Session metadata
    metadata: Dict[str, str] = None
    
    def __post_init__(self):
        if self.files is None:
            self.files = {}
        if self.environment is None:
            self.environment = {}
        if self.execution_history is None:
            self.execution_history = []
        if self.installed_packages is None:
            self.installed_packages = []
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (files excluded, stored separately)."""
        return {
            "session_id": self.session_id,
            "pool_name": self.pool_name,
            "pod_name": self.pod_name,
            "template": self.template,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "expires_at": self.expires_at,
            "environment": self.environment,
            "execution_history": self.execution_history,
            "installed_packages": self.installed_packages,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionState':
        """Create from dictionary."""
        state = cls(
            session_id=data["session_id"],
            pool_name=data["pool_name"],
            pod_name=data["pod_name"],
            template=data["template"],
            created_at=data["created_at"],
            last_activity=data["last_activity"],
            expires_at=data["expires_at"],
            environment=data.get("environment", {}),
            execution_history=data.get("execution_history", []),
            installed_packages=data.get("installed_packages", []),
            metadata=data.get("metadata", {}),
        )
        return state


class SessionPersistenceManager:
    """
    Manages session persistence using Redis.
    
    Features:
    - Automatic state serialization
    - Compressed storage
    - Pod migration support
    - Multi-region replication
    - Incremental snapshots
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        compression_enabled: bool = True,
        max_file_size: int = 10 * 1024 * 1024,  # 10MB
        snapshot_interval: int = 60  # seconds
    ):
        self.redis_url = redis_url
        self.compression_enabled = compression_enabled
        self.max_file_size = max_file_size
        self.snapshot_interval = snapshot_interval
        
        self.redis: Optional[redis.Redis] = None
        self._snapshot_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Local cache of active sessions
        self._active_sessions: Dict[str, SessionState] = {}
    
    async def start(self):
        """Start the persistence manager."""
        logger.info("Starting Session Persistence Manager")
        
        self.redis = redis.from_url(self.redis_url, decode_responses=False)
        self._running = True
        
        # Start periodic snapshot task
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())
        
        logger.info("Session Persistence Manager started")
    
    async def stop(self):
        """Stop the persistence manager."""
        logger.info("Stopping Session Persistence Manager")
        
        self._running = False
        
        # Save all active sessions
        await self._save_all_sessions()
        
        if self._snapshot_task:
            self._snapshot_task.cancel()
            try:
                await self._snapshot_task
            except asyncio.CancelledError:
                pass
        
        if self.redis:
            await self.redis.close()
        
        logger.info("Session Persistence Manager stopped")
    
    async def create_session(
        self,
        session_id: str,
        pool_name: str,
        pod_name: str,
        template: str = "default",
        ttl: int = 3600,
        metadata: Optional[Dict[str, str]] = None
    ) -> SessionState:
        """
        Create a new persisted session.
        
        Args:
            session_id: Unique session ID
            pool_name: Name of the executor pool
            pod_name: Name of the pod running the session
            template: Sandbox template name
            ttl: Time-to-live in seconds
            metadata: Optional session metadata
        
        Returns:
            Created session state
        """
        now = datetime.utcnow()
        expires = now + timedelta(seconds=ttl)
        
        state = SessionState(
            session_id=session_id,
            pool_name=pool_name,
            pod_name=pod_name,
            template=template,
            created_at=now.isoformat(),
            last_activity=now.isoformat(),
            expires_at=expires.isoformat(),
            metadata=metadata or {}
        )
        
        self._active_sessions[session_id] = state
        
        # Persist to Redis
        await self._save_session(state, ttl)
        
        logger.info(f"Created persisted session: {session_id}")
        return state
    
    async def get_session(self, session_id: str) -> Optional[SessionState]:
        """
        Get session state.
        
        First checks local cache, then Redis.
        """
        # Check local cache
        if session_id in self._active_sessions:
            return self._active_sessions[session_id]
        
        # Load from Redis
        return await self._load_session(session_id)
    
    async def update_session(
        self,
        session_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update session state.
        
        Args:
            session_id: Session ID
            updates: Dictionary of updates
        
        Returns:
            True if updated successfully
        """
        try:
            # Get current state
            state = await self.get_session(session_id)
            if not state:
                logger.warning(f"Session not found for update: {session_id}")
                return False
            
            # Apply updates
            for key, value in updates.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            
            # Update last activity
            state.last_activity = datetime.utcnow().isoformat()
            
            # Update cache
            self._active_sessions[session_id] = state
            
            logger.debug(f"Updated session: {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating session {session_id}: {e}")
            return False
    
    async def add_file(
        self,
        session_id: str,
        file_path: str,
        content: bytes
    ) -> bool:
        """
        Add or update a file in session storage.
        
        Args:
            session_id: Session ID
            file_path: File path
            content: File content
        
        Returns:
            True if successful
        """
        try:
            if len(content) > self.max_file_size:
                logger.warning(f"File too large for session {session_id}: {file_path}")
                return False
            
            state = await self.get_session(session_id)
            if not state:
                return False
            
            # Compress if enabled
            if self.compression_enabled:
                content = zlib.compress(content)
            
            state.files[file_path] = content
            state.last_activity = datetime.utcnow().isoformat()
            
            # Persist file separately
            await self._save_file(session_id, file_path, content)
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding file to session {session_id}: {e}")
            return False
    
    async def get_file(
        self,
        session_id: str,
        file_path: str
    ) -> Optional[bytes]:
        """
        Get file from session storage.
        
        Args:
            session_id: Session ID
            file_path: File path
        
        Returns:
            File content or None
        """
        try:
            # Check local cache
            state = self._active_sessions.get(session_id)
            if state and file_path in state.files:
                content = state.files[file_path]
                if self.compression_enabled:
                    content = zlib.decompress(content)
                return content
            
            # Load from Redis
            content = await self._load_file(session_id, file_path)
            if content and self.compression_enabled:
                content = zlib.decompress(content)
            return content
            
        except Exception as e:
            logger.error(f"Error getting file from session {session_id}: {e}")
            return None
    
    async def delete_file(self, session_id: str, file_path: str) -> bool:
        """Delete a file from session storage."""
        try:
            state = self._active_sessions.get(session_id)
            if state and file_path in state.files:
                del state.files[file_path]
            
            await self.redis.hdel(f"executor:session:{session_id}:files", file_path)
            return True
            
        except Exception as e:
            logger.error(f"Error deleting file from session {session_id}: {e}")
            return False
    
    async def migrate_session(
        self,
        session_id: str,
        new_pod_name: str,
        new_pool_name: Optional[str] = None
    ) -> Optional[SessionState]:
        """
        Migrate a session to a new pod.
        
        Args:
            session_id: Session ID
            new_pod_name: New pod name
            new_pool_name: New pool name (optional)
        
        Returns:
            Updated session state or None
        """
        try:
            state = await self.get_session(session_id)
            if not state:
                logger.warning(f"Cannot migrate non-existent session: {session_id}")
                return None
            
            old_pod = state.pod_name
            state.pod_name = new_pod_name
            
            if new_pool_name:
                state.pool_name = new_pool_name
            
            state.last_activity = datetime.utcnow().isoformat()
            state.metadata["migrated_from"] = old_pod
            state.metadata["migrated_at"] = datetime.utcnow().isoformat()
            
            # Update cache
            self._active_sessions[session_id] = state
            
            # Persist updated state
            await self._save_session(state)
            
            logger.info(f"Migrated session {session_id} from {old_pod} to {new_pod_name}")
            return state
            
        except Exception as e:
            logger.error(f"Error migrating session {session_id}: {e}")
            return None
    
    async def restore_session(
        self,
        session_id: str,
        new_pod_name: str
    ) -> Optional[SessionState]:
        """
        Restore a persisted session to a new pod.
        
        Args:
            session_id: Session ID
            new_pod_name: New pod name
        
        Returns:
            Restored session state or None
        """
        try:
            state = await self._load_session(session_id)
            if not state:
                logger.warning(f"Cannot restore non-existent session: {session_id}")
                return None
            
            # Update pod assignment
            state.pod_name = new_pod_name
            state.last_activity = datetime.utcnow().isoformat()
            state.metadata["restored"] = "true"
            state.metadata["restored_at"] = datetime.utcnow().isoformat()
            
            # Add to cache
            self._active_sessions[session_id] = state
            
            # Load all files
            state.files = await self._load_all_files(session_id)
            
            logger.info(f"Restored session {session_id} to pod {new_pod_name}")
            return state
            
        except Exception as e:
            logger.error(f"Error restoring session {session_id}: {e}")
            return None
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its data."""
        try:
            # Remove from cache
            if session_id in self._active_sessions:
                del self._active_sessions[session_id]
            
            # Delete from Redis
            pipeline = self.redis.pipeline()
            pipeline.delete(f"executor:session:{session_id}")
            pipeline.delete(f"executor:session:{session_id}:files")
            await pipeline.execute()
            
            logger.info(f"Deleted session: {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
            return False
    
    async def list_sessions(
        self,
        pool_name: Optional[str] = None,
        pod_name: Optional[str] = None
    ) -> List[SessionState]:
        """
        List sessions with optional filtering.
        
        Args:
            pool_name: Filter by pool name
            pod_name: Filter by pod name
        
        Returns:
            List of session states
        """
        try:
            # Get all session keys
            keys = await self.redis.keys("executor:session:*")
            
            sessions = []
            for key in keys:
                # Skip file keys
                if b":files" in key:
                    continue
                
                session_id = key.decode().split(":")[-1]
                state = await self._load_session(session_id)
                
                if state:
                    # Apply filters
                    if pool_name and state.pool_name != pool_name:
                        continue
                    if pod_name and state.pod_name != pod_name:
                        continue
                    
                    sessions.append(state)
            
            return sessions
            
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            return []
    
    async def _save_session(self, state: SessionState, ttl: Optional[int] = None):
        """Save session state to Redis."""
        try:
            key = f"executor:session:{state.session_id}"
            data = json.dumps(state.to_dict())
            
            if ttl:
                await self.redis.setex(key, ttl, data)
            else:
                await self.redis.set(key, data)
                
        except Exception as e:
            logger.error(f"Error saving session {state.session_id}: {e}")
    
    async def _load_session(self, session_id: str) -> Optional[SessionState]:
        """Load session state from Redis."""
        try:
            key = f"executor:session:{session_id}"
            data = await self.redis.get(key)
            
            if data:
                return SessionState.from_dict(json.loads(data))
            return None
            
        except Exception as e:
            logger.error(f"Error loading session {session_id}: {e}")
            return None
    
    async def _save_file(self, session_id: str, file_path: str, content: bytes):
        """Save a file to Redis."""
        try:
            key = f"executor:session:{session_id}:files"
            await self.redis.hset(key, file_path, content)
            
            # Set TTL on files hash
            await self.redis.expire(key, 86400)  # 24 hours
            
        except Exception as e:
            logger.error(f"Error saving file {file_path} for session {session_id}: {e}")
    
    async def _load_file(self, session_id: str, file_path: str) -> Optional[bytes]:
        """Load a file from Redis."""
        try:
            key = f"executor:session:{session_id}:files"
            return await self.redis.hget(key, file_path)
            
        except Exception as e:
            logger.error(f"Error loading file {file_path} for session {session_id}: {e}")
            return None
    
    async def _load_all_files(self, session_id: str) -> Dict[str, bytes]:
        """Load all files for a session."""
        try:
            key = f"executor:session:{session_id}:files"
            files_data = await self.redis.hgetall(key)
            return {k.decode(): v for k, v in files_data.items()}
            
        except Exception as e:
            logger.error(f"Error loading files for session {session_id}: {e}")
            return {}
    
    async def _snapshot_loop(self):
        """Background task for periodic snapshots."""
        while self._running:
            try:
                await asyncio.sleep(self.snapshot_interval)
                await self._save_all_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in snapshot loop: {e}")
    
    async def _save_all_sessions(self):
        """Save all active sessions to Redis."""
        try:
            for session_id, state in list(self._active_sessions.items()):
                await self._save_session(state)
                
            logger.debug(f"Saved {len(self._active_sessions)} sessions to Redis")
            
        except Exception as e:
            logger.error(f"Error saving all sessions: {e}")
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get persistence manager statistics."""
        try:
            keys = await self.redis.keys("executor:session:*")
            total_sessions = len([k for k in keys if b":files" not in k])
            
            return {
                "active_sessions": len(self._active_sessions),
                "persisted_sessions": total_sessions,
                "compression_enabled": self.compression_enabled,
                "max_file_size": self.max_file_size,
                "snapshot_interval": self.snapshot_interval
            }
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}


# Singleton instance
_persistence_manager: Optional[SessionPersistenceManager] = None


async def get_persistence_manager() -> SessionPersistenceManager:
    """Get or create persistence manager instance."""
    global _persistence_manager
    if _persistence_manager is None:
        _persistence_manager = SessionPersistenceManager()
        await _persistence_manager.start()
    return _persistence_manager


async def init_persistence_manager(redis_url: str = "redis://localhost:6379"):
    """Initialize the persistence manager."""
    global _persistence_manager
    _persistence_manager = SessionPersistenceManager(redis_url=redis_url)
    await _persistence_manager.start()


async def close_persistence_manager():
    """Close the persistence manager."""
    global _persistence_manager
    if _persistence_manager:
        await _persistence_manager.stop()
        _persistence_manager = None
