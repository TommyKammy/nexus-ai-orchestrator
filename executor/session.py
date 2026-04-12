"""
Session Manager for CodeSandbox
Phase 2: Enhanced Execution Management

Provides session lifecycle management with TTL, concurrent execution,
and resource pooling for sandbox containers.
"""

import logging
import os
import threading
import time
import uuid
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from urllib.parse import urlsplit

from executor.sandbox import CodeSandbox

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_AUTO_STATE_STORE = object()


class RedisSessionStateStore:
    """Persists session metadata and TTL state in Redis."""

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "executor:session:",
        connect_timeout: float = 0.5,
        socket_timeout: float = 0.5,
    ):
        import redis  # Imported lazily to avoid hard dependency when disabled

        self._client = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=connect_timeout,
            socket_timeout=socket_timeout,
        )
        self._key_prefix = key_prefix

    def _key(self, session_id: str) -> str:
        return f"{self._key_prefix}{session_id}"

    def ping(self) -> None:
        self._client.ping()

    def save(self, session_id: str, payload: Dict[str, Any], ttl: int) -> None:
        expires_in = max(1, int(ttl))
        self._client.set(self._key(session_id), json.dumps(payload), ex=expires_in)

    def delete(self, session_id: str) -> None:
        self._client.delete(self._key(session_id))


@dataclass
class Session:
    """Represents a sandbox session."""
    id: str
    sandbox: CodeSandbox
    template: str
    created_at: float
    last_used: float
    ttl: int  # Time to live in seconds
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    use_count: int = 0
    
    @property
    def age(self) -> float:
        """Get session age in seconds."""
        return time.time() - self.created_at
    
    @property
    def idle_time(self) -> float:
        """Get idle time in seconds."""
        return time.time() - self.last_used
    
    @property
    def is_expired(self) -> bool:
        """Check if session has exceeded TTL."""
        return self.idle_time > self.ttl
    
    def touch(self):
        """Update last used timestamp."""
        self.last_used = time.time()
        self.use_count += 1


class SessionManager:
    """
    Manages sandbox sessions with TTL and concurrent execution support.
    
    Features:
    - Session pooling and reuse
    - Automatic cleanup of expired sessions
    - Concurrent session limit
    - Session metadata and tracking
    - Background cleanup thread
    """
    
    def __init__(
        self,
        default_ttl: int = 300,  # 5 minutes
        max_sessions: int = 10,
        cleanup_interval: int = 60,  # 1 minute
        enable_cleanup_thread: bool = True,
        state_store: Any = _AUTO_STATE_STORE,
    ):
        """
        Initialize session manager.
        
        Args:
            default_ttl: Default session TTL in seconds
            max_sessions: Maximum concurrent sessions
            cleanup_interval: Cleanup thread interval in seconds
            enable_cleanup_thread: Whether to enable background cleanup
        """
        self.default_ttl = default_ttl
        self.max_sessions = max_sessions
        self.cleanup_interval = cleanup_interval
        
        self.sessions: Dict[str, Session] = {}
        self._lock = threading.RLock()
        self._creation_lock = threading.Lock()  # Separate lock for creation coordination
        self._session_semaphore = threading.Semaphore(max_sessions)  # Limit concurrent creations
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_cleanup = threading.Event()
        
        # Metrics
        self.metrics = {
            "sessions_created": 0,
            "sessions_reused": 0,
            "sessions_destroyed": 0,
            "sessions_expired": 0,
            "errors": 0
        }
        if state_store is _AUTO_STATE_STORE:
            self._state_store = self._create_state_store_from_env()
        else:
            self._state_store = state_store
        
        if enable_cleanup_thread:
            self._start_cleanup_thread()

    def _create_state_store_from_env(self) -> Optional[RedisSessionStateStore]:
        redis_url = os.environ.get("SESSION_STATE_REDIS_URL", "").strip()
        if not redis_url:
            return None

        key_prefix = os.environ.get("SESSION_STATE_REDIS_PREFIX", "executor:session:")
        connect_timeout_ms = int(os.environ.get("SESSION_STATE_REDIS_CONNECT_TIMEOUT_MS", "500"))
        socket_timeout_ms = int(os.environ.get("SESSION_STATE_REDIS_SOCKET_TIMEOUT_MS", "500"))
        try:
            store = RedisSessionStateStore(
                redis_url,
                key_prefix=key_prefix,
                connect_timeout=max(1, connect_timeout_ms) / 1000.0,
                socket_timeout=max(1, socket_timeout_ms) / 1000.0,
            )
            store.ping()
            logger.info("Redis session state enabled: %s", self._sanitize_redis_target(redis_url))
            return store
        except Exception as exc:
            logger.error("Failed to initialize Redis session state store: %s", exc)
            self.metrics["errors"] += 1
            return None

    def _sanitize_redis_target(self, redis_url: str) -> str:
        parsed = urlsplit(redis_url)
        host = parsed.hostname or "unknown"
        port = f":{parsed.port}" if parsed.port else ""
        db_path = parsed.path or ""
        scheme = parsed.scheme or "redis"
        return f"{scheme}://{host}{port}{db_path}"

    def _session_state_payload(self, session: Session) -> Dict[str, Any]:
        return {
            "id": session.id,
            "template": session.template,
            "created_at": session.created_at,
            "last_used": session.last_used,
            "ttl": session.ttl,
            "metadata": session.metadata,
            "is_active": session.is_active,
            "use_count": session.use_count,
        }

    def _save_session_state(self, session_id: str, payload: Dict[str, Any], ttl: int):
        if not self._state_store:
            return
        try:
            self._state_store.save(session_id, payload, ttl)
        except Exception as exc:
            logger.warning("Failed to persist session state for %s: %s", session_id, exc)
            self.metrics["errors"] += 1

    def _delete_session_state(self, session_id: str):
        if not self._state_store:
            return
        try:
            self._state_store.delete(session_id)
        except Exception as exc:
            logger.warning("Failed to delete session state for %s: %s", session_id, exc)
            self.metrics["errors"] += 1
    
    def create_session(
        self,
        template: str = "default",
        ttl: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **sandbox_kwargs
    ) -> str:
        """
        Create a new sandbox session.
        
        Args:
            template: Environment template name
            ttl: Session TTL (uses default if not specified)
            metadata: Additional session metadata
            **sandbox_kwargs: Additional arguments for CodeSandbox
        
        Returns:
            Session ID
        
        Raises:
            RuntimeError: If maximum session limit reached
        """
        ttl = ttl or self.default_ttl
        expired_state_ids: List[str] = []
        
        # Phase 1: Acquire semaphore slot to prevent race conditions
        # This ensures we never exceed max_sessions even with concurrent creation
        if not self._session_semaphore.acquire(blocking=False):
            # Try to cleanup expired sessions first
            with self._lock:
                expired_state_ids = self._cleanup_expired()
            for expired_session_id in expired_state_ids:
                self._delete_session_state(expired_session_id)
            
            # Try again after cleanup
            if not self._session_semaphore.acquire(blocking=False):
                raise RuntimeError(
                    f"Maximum session limit reached ({self.max_sessions}). "
                    "Destroy existing sessions or increase limit."
                )
        
        sandbox = None
        try:
            persist_session_id: Optional[str] = None
            persist_payload: Optional[Dict[str, Any]] = None
            persist_ttl: Optional[int] = None

            # Phase 2: Create sandbox OUTSIDE the lock to avoid blocking other operations
            sandbox = CodeSandbox(**sandbox_kwargs)
            sandbox.create()
            
            # Phase 3: Register session with lock
            with self._lock:
                session_id = str(uuid.uuid4())[:12]
                session = Session(
                    id=session_id,
                    sandbox=sandbox,
                    template=template,
                    created_at=time.time(),
                    last_used=time.time(),
                    ttl=ttl,
                    metadata=metadata or {}
                )
                
                self.sessions[session_id] = session
                self.metrics["sessions_created"] += 1
                persist_session_id = session_id
                persist_payload = self._session_state_payload(session)
                persist_ttl = session.ttl
                
                logger.info(f"Session created: {session_id} (template: {template})")
            if persist_session_id and persist_payload is not None and persist_ttl is not None:
                self._save_session_state(persist_session_id, persist_payload, persist_ttl)
            return session_id
                
        except Exception as e:
            # Release semaphore slot if creation failed
            self._session_semaphore.release()
            self.metrics["errors"] += 1
            logger.error(f"Failed to create session: {e}")
            # Cleanup sandbox if it was created
            if sandbox:
                try:
                    sandbox.destroy()
                except:
                    pass
            raise
    
    def peek_session(self, session_id: str) -> Optional[Session]:
        """
        Read session state without mutating TTL or usage counters.

        Args:
            session_id: Session identifier

        Returns:
            Session object or None if not found, inactive, or expired
        """
        with self._lock:
            session = self.sessions.get(session_id)

            if not session:
                return None

            if not session.is_active:
                logger.warning(f"Session {session_id} is inactive")
                return None

            if session.is_expired:
                logger.info(f"Session {session_id} expired during read-only lookup")
                return None

            return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Get existing session by ID.
        
        Args:
            session_id: Session identifier
        
        Returns:
            Session object or None if not found/expired
        """
        session_to_return: Optional[Session] = None
        session_to_delete_state: Optional[str] = None
        persist_payload: Optional[Dict[str, Any]] = None
        persist_ttl: Optional[int] = None

        with self._lock:
            session = self.sessions.get(session_id)

            if not session:
                return None

            if not session.is_active:
                logger.warning(f"Session {session_id} is inactive")
                return None

            if session.is_expired:
                logger.info(f"Session {session_id} expired, destroying")
                _, should_delete_state = self._destroy_session_unlocked(session_id)
                if should_delete_state:
                    session_to_delete_state = session_id
            else:
                session.touch()
                self.metrics["sessions_reused"] += 1
                persist_payload = self._session_state_payload(session)
                persist_ttl = session.ttl
                session_to_return = session

        if session_to_delete_state:
            self._delete_session_state(session_to_delete_state)
            return None

        if not session_to_return:
            return None

        if persist_payload is not None and persist_ttl is not None:
            self._save_session_state(session_to_return.id, persist_payload, persist_ttl)
            
        return session_to_return
    
    def execute_in_session(
        self,
        session_id: str,
        code: str,
        language: str = "python",
        files: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Execute code in an existing session.
        
        Args:
            session_id: Session identifier
            code: Code to execute
            language: Programming language
            files: Files to upload
        
        Returns:
            Execution result
        """
        session = self.get_session(session_id)
        
        if not session:
            return {
                "status": "error",
                "error": f"Session {session_id} not found or expired",
                "exit_code": -1
            }
        
        try:
            result = session.sandbox.run_code(code, language, files)
            return result
        except Exception as e:
            logger.error(f"Execution error in session {session_id}: {e}")
            return {
                "status": "error",
                "error": str(e),
                "exit_code": -1
            }
    
    def destroy_session(self, session_id: str) -> bool:
        """
        Destroy a session and cleanup resources.
        
        Args:
            session_id: Session identifier
        
        Returns:
            True if destroyed successfully
        """
        should_delete_state = False
        with self._lock:
            destroyed, should_delete_state = self._destroy_session_unlocked(session_id)

        if should_delete_state:
            self._delete_session_state(session_id)

        return destroyed
    
    def _destroy_session_unlocked(self, session_id: str) -> tuple[bool, bool]:
        """Internal method to destroy session (must hold lock)."""
        session = self.sessions.get(session_id)
        
        if not session:
            return False, False
        
        try:
            session.is_active = False
            session.sandbox.destroy()
            del self.sessions[session_id]
            self.metrics["sessions_destroyed"] += 1
            
            # Release semaphore slot to allow new session creation
            try:
                self._session_semaphore.release()
            except ValueError:
                # Semaphore already at max value, ignore
                pass
            
            logger.info(f"Session destroyed: {session_id}")
            return True, True
            
        except Exception as e:
            logger.error(f"Error destroying session {session_id}: {e}")
            self.metrics["errors"] += 1
            return False, False
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        List all active sessions.
        
        Returns:
            List of session info dictionaries
        """
        with self._lock:
            return [
                {
                    "id": s.id,
                    "template": s.template,
                    "age": round(s.age, 2),
                    "idle_time": round(s.idle_time, 2),
                    "ttl": s.ttl,
                    "is_expired": s.is_expired,
                    "use_count": s.use_count,
                    "metadata": s.metadata
                }
                for s in self.sessions.values()
                if s.is_active
            ]
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get session manager metrics."""
        with self._lock:
            return {
                **self.metrics,
                "active_sessions": len(self.sessions),
                "max_sessions": self.max_sessions,
                "default_ttl": self.default_ttl
            }
    
    def _cleanup_expired(self) -> List[str]:
        """Clean up expired sessions."""
        expired_ids = [
            sid for sid, session in self.sessions.items()
            if session.is_expired
        ]
        expired_state_ids: List[str] = []
        
        for sid in expired_ids:
            destroyed, should_delete_state = self._destroy_session_unlocked(sid)
            if destroyed:
                self.metrics["sessions_expired"] += 1
            if should_delete_state:
                expired_state_ids.append(sid)
        
        if expired_ids:
            logger.info(f"Cleaned up {len(expired_ids)} expired sessions")
        return expired_state_ids
    
    def _start_cleanup_thread(self):
        """Start background cleanup thread."""
        def cleanup_loop():
            while not self._stop_cleanup.wait(self.cleanup_interval):
                try:
                    expired_state_ids: List[str] = []
                    with self._lock:
                        expired_state_ids = self._cleanup_expired()
                    for expired_session_id in expired_state_ids:
                        self._delete_session_state(expired_session_id)
                except Exception as e:
                    logger.error(f"Cleanup thread error: {e}")
        
        self._cleanup_thread = threading.Thread(
            target=cleanup_loop,
            name="SessionCleanup",
            daemon=True
        )
        self._cleanup_thread.start()
        logger.info("Session cleanup thread started")
    
    def stop(self):
        """Stop session manager and cleanup all resources."""
        logger.info("Stopping session manager")
        
        # Signal cleanup thread to stop
        self._stop_cleanup.set()
        
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
        
        # Destroy all sessions
        with self._lock:
            session_ids = list(self.sessions.keys())
            for sid in session_ids:
                self._destroy_session_unlocked(sid)
        
        logger.info("Session manager stopped")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()


class SessionPool:
    """
    Pre-warmed pool of sandbox sessions for faster execution.
    
    Useful for high-throughput scenarios where session creation
    overhead needs to be minimized.
    """
    
    def __init__(
        self,
        manager: SessionManager,
        template: str = "default",
        min_size: int = 2,
        max_size: int = 5,
        **sandbox_kwargs
    ):
        """
        Initialize session pool.
        
        Args:
            manager: SessionManager instance
            template: Template name for pooled sessions
            min_size: Minimum number of pre-warmed sessions
            max_size: Maximum pool size
            **sandbox_kwargs: Additional sandbox configuration
        """
        self.manager = manager
        self.template = template
        self.min_size = min_size
        self.max_size = max_size
        self.sandbox_kwargs = sandbox_kwargs
        
        self._pool: List[str] = []
        self._lock = threading.RLock()
        
        # Pre-warm pool
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Create initial pool of sessions."""
        for _ in range(self.min_size):
            try:
                sid = self.manager.create_session(
                    template=self.template,
                    **self.sandbox_kwargs
                )
                self._pool.append(sid)
            except Exception as e:
                logger.error(f"Failed to initialize pool session: {e}")
    
    def acquire(self) -> Optional[str]:
        """
        Acquire a session from the pool.
        
        Returns:
            Session ID or None if pool exhausted
        """
        with self._lock:
            # Try to get from pool
            while self._pool:
                sid = self._pool.pop(0)
                session = self.manager.get_session(sid)
                if session:
                    return sid
            
            # Pool empty, create new if under max_size
            if len(self._pool) < self.max_size:
                try:
                    return self.manager.create_session(
                        template=self.template,
                        **self.sandbox_kwargs
                    )
                except Exception as e:
                    logger.error(f"Failed to create session: {e}")
            
            return None
    
    def release(self, session_id: str, destroy: bool = False):
        """
        Return a session to the pool or destroy it.
        
        Args:
            session_id: Session to release
            destroy: If True, destroy instead of returning to pool
        """
        if destroy:
            self.manager.destroy_session(session_id)
            return
        
        with self._lock:
            session = self.manager.get_session(session_id)
            if session and len(self._pool) < self.max_size:
                self._pool.append(session_id)
            else:
                self.manager.destroy_session(session_id)
    
    def __enter__(self) -> Optional[str]:
        """Context manager entry - acquire session."""
        return self.acquire()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - release session."""
        # Note: Session ID must be stored externally for this to work
        pass
