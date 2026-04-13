"""
Global Load Balancer for Executor Sessions
Feature 3: Global Load Balancing with Health Checks

Distributes sessions across multiple pools/regions with:
- Health-aware routing
- Session affinity (sticky sessions)
- Geographic load balancing
- Circuit breaker pattern
"""

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum
import aiohttp
import redis.asyncio as redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _redis_connection_kwargs() -> Dict[str, str | bool]:
    """Build optional redis-py TLS/auth kwargs from environment."""
    connection_kwargs: Dict[str, str | bool] = {}

    redis_password = os.environ.get("REDIS_PASSWORD")
    if redis_password:
        connection_kwargs["password"] = redis_password

    if os.environ.get("REDIS_TLS_ENABLED", "").lower() == "true":
        connection_kwargs["ssl"] = True
        connection_kwargs["ssl_cert_reqs"] = os.environ.get("REDIS_TLS_CERT_REQS", "required")

        ca_cert = os.environ.get("REDIS_TLS_CA_CERT_FILE")
        cert_file = os.environ.get("REDIS_TLS_CERT_FILE")
        key_file = os.environ.get("REDIS_TLS_KEY_FILE")

        if ca_cert:
            connection_kwargs["ssl_ca_certs"] = ca_cert
        if cert_file:
            connection_kwargs["ssl_certfile"] = cert_file
        if key_file:
            connection_kwargs["ssl_keyfile"] = key_file

    return connection_kwargs


class PoolStatus(Enum):
    """Status of a pool endpoint."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class PoolEndpoint:
    """Represents an executor pool endpoint."""
    name: str
    region: str
    url: str
    weight: int = 100
    priority: int = 1
    max_sessions: int = 100
    current_sessions: int = 0
    status: PoolStatus = PoolStatus.HEALTHY
    last_health_check: float = 0.0
    response_time_ms: float = 0.0
    error_rate: float = 0.0
    cpu_utilization: float = 0.0
    memory_utilization: float = 0.0
    queue_depth: int = 0
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "status": self.status.value
        }


@dataclass
class CircuitBreaker:
    """Circuit breaker for pool endpoints."""
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3
    
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    
    def record_success(self):
        """Record a successful request."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_max_calls:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                logger.info("Circuit breaker closed - pool recovered")
        else:
            self.failure_count = max(0, self.failure_count - 1)
    
    def record_failure(self):
        """Record a failed request."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker opened - pool still failing")
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
    
    def can_execute(self) -> bool:
        """Check if requests can be executed."""
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                logger.info("Circuit breaker half-open - testing pool recovery")
                return True
            return False
        else:  # HALF_OPEN
            return True


@dataclass
class SessionAffinity:
    """Session affinity/sticky session data."""
    session_id: str
    pool_name: str
    created_at: float
    ttl: int = 3600  # 1 hour
    
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl


class GlobalLoadBalancer:
    """
    Global load balancer for executor pools.
    
    Features:
    - Health-aware routing
    - Weighted least-connections
    - Session affinity
    - Geographic routing
    - Circuit breaker protection
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        health_check_interval: float = 10.0,
        enable_geo_routing: bool = False
    ):
        self.redis_url = redis_url
        self.health_check_interval = health_check_interval
        self.enable_geo_routing = enable_geo_routing
        
        self.pools: Dict[str, PoolEndpoint] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.session_affinities: Dict[str, SessionAffinity] = {}
        
        self.redis: Optional[redis.Redis] = None
        self.health_check_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Start the load balancer."""
        logger.info("Starting Global Load Balancer")
        
        self.redis = redis.from_url(
            self.redis_url,
            decode_responses=True,
            **_redis_connection_kwargs(),
        )
        self._running = True
        
        # Load pool configuration from Redis
        await self._load_pools()
        
        # Start health checks
        self.health_check_task = asyncio.create_task(self._health_check_loop())
        
        logger.info("Global Load Balancer started")
    
    async def stop(self):
        """Stop the load balancer."""
        logger.info("Stopping Global Load Balancer")
        
        self._running = False
        
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
        
        if self.redis:
            await self.redis.close()
        
        logger.info("Global Load Balancer stopped")
    
    async def _load_pools(self):
        """Load pool configuration from Redis."""
        try:
            pools_data = await self.redis.hgetall("executor:loadbalancer:pools")
            
            for pool_name, pool_json in pools_data.items():
                try:
                    pool_data = json.loads(pool_json)
                    pool = PoolEndpoint(**pool_data)
                    pool.status = PoolStatus(pool_data.get("status", "healthy"))
                    
                    self.pools[pool_name] = pool
                    if pool_name not in self.circuit_breakers:
                        self.circuit_breakers[pool_name] = CircuitBreaker()
                    
                    logger.info(f"Loaded pool: {pool_name} ({pool.region})")
                except Exception as e:
                    logger.error(f"Error loading pool {pool_name}: {e}")
            
            logger.info(f"Loaded {len(self.pools)} pools")
            
        except Exception as e:
            logger.error(f"Error loading pools: {e}")
    
    async def register_pool(
        self,
        name: str,
        region: str,
        url: str,
        weight: int = 100,
        priority: int = 1,
        max_sessions: int = 100
    ) -> bool:
        """
        Register a new pool endpoint.
        
        Args:
            name: Unique pool name
            region: Geographic region
            url: Pool URL (e.g., http://executor-pool-x.default.svc)
            weight: Load balancing weight (higher = more traffic)
            priority: Priority level (lower = higher priority)
            max_sessions: Maximum concurrent sessions
        
        Returns:
            True if registered successfully
        """
        try:
            pool = PoolEndpoint(
                name=name,
                region=region,
                url=url,
                weight=weight,
                priority=priority,
                max_sessions=max_sessions
            )
            
            self.pools[name] = pool
            self.circuit_breakers[name] = CircuitBreaker()
            
            # Persist to Redis
            await self.redis.hset(
                "executor:loadbalancer:pools",
                name,
                json.dumps(pool.to_dict())
            )
            
            logger.info(f"Registered pool: {name} in {region}")
            return True
            
        except Exception as e:
            logger.error(f"Error registering pool {name}: {e}")
            return False
    
    async def unregister_pool(self, name: str) -> bool:
        """Unregister a pool endpoint."""
        try:
            if name in self.pools:
                del self.pools[name]
            if name in self.circuit_breakers:
                del self.circuit_breakers[name]
            
            # Remove from Redis
            await self.redis.hdel("executor:loadbalancer:pools", name)
            
            logger.info(f"Unregistered pool: {name}")
            return True
            
        except Exception as e:
            logger.error(f"Error unregistering pool {name}: {e}")
            return False
    
    async def get_pool_for_session(
        self,
        session_id: str,
        preferred_region: Optional[str] = None
    ) -> Optional[PoolEndpoint]:
        """
        Select a pool for a new session.
        
        Selection criteria (in order):
        1. Session affinity (if exists)
        2. Healthy pools with capacity
        3. Circuit breaker state
        4. Weighted least-connections
        5. Geographic proximity (if enabled)
        
        Args:
            session_id: Unique session ID
            preferred_region: Preferred geographic region
        
        Returns:
            Selected pool or None if no pool available
        """
        # 1. Check session affinity
        affinity = await self._get_session_affinity(session_id)
        if affinity and not affinity.is_expired():
            pool = self.pools.get(affinity.pool_name)
            if pool and pool.status == PoolStatus.HEALTHY:
                logger.debug(f"Using session affinity for {session_id} -> {pool.name}")
                return pool
        
        # 2. Filter available pools
        available_pools = self._get_available_pools(preferred_region)
        
        if not available_pools:
            logger.warning("No available pools for session")
            return None
        
        # 3. Select pool using weighted least-connections
        selected_pool = self._select_weighted_pool(available_pools)
        
        if selected_pool:
            # Store session affinity
            await self._set_session_affinity(session_id, selected_pool.name)
            
            # Update session count
            selected_pool.current_sessions += 1
            await self._update_pool_metrics(selected_pool)
            
            logger.info(f"Selected pool {selected_pool.name} for session {session_id}")
        
        return selected_pool
    
    def _get_available_pools(
        self,
        preferred_region: Optional[str] = None
    ) -> List[PoolEndpoint]:
        """Get list of available pools."""
        available = []
        
        for name, pool in self.pools.items():
            # Check circuit breaker
            if not self.circuit_breakers[name].can_execute():
                continue
            
            # Check pool status
            if pool.status not in (PoolStatus.HEALTHY, PoolStatus.DEGRADED):
                continue
            
            # Check capacity
            if pool.current_sessions >= pool.max_sessions:
                continue
            
            # Check queue depth
            if pool.queue_depth > 50:
                continue
            
            available.append(pool)
        
        # Sort by priority and region
        if preferred_region and self.enable_geo_routing:
            available.sort(key=lambda p: (
                0 if p.region == preferred_region else 1,
                p.priority,
                p.current_sessions / p.max_sessions
            ))
        else:
            available.sort(key=lambda p: (p.priority, p.current_sessions / p.max_sessions))
        
        return available
    
    def _select_weighted_pool(self, pools: List[PoolEndpoint]) -> Optional[PoolEndpoint]:
        """Select a pool using weighted least-connections algorithm."""
        if not pools:
            return None
        
        # Calculate scores
        scores = []
        for pool in pools:
            # Score based on available capacity and weight
            utilization = pool.current_sessions / pool.max_sessions if pool.max_sessions > 0 else 1
            available_capacity = 1 - utilization
            
            # Factor in health status
            health_factor = 1.0
            if pool.status == PoolStatus.DEGRADED:
                health_factor = 0.7
            
            # Factor in response time
            response_factor = 1.0
            if pool.response_time_ms > 0:
                response_factor = 1000 / (pool.response_time_ms + 1000)
            
            score = available_capacity * pool.weight * health_factor * response_factor
            scores.append((pool, score))
        
        # Sort by score (highest first)
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Use weighted random selection from top 3
        top_pools = scores[:min(3, len(scores))]
        total_score = sum(s[1] for s in top_pools)
        
        if total_score == 0:
            return random.choice([p[0] for p in top_pools])
        
        r = random.uniform(0, total_score)
        cumulative = 0
        for pool, score in top_pools:
            cumulative += score
            if r <= cumulative:
                return pool
        
        return top_pools[-1][0]
    
    async def _get_session_affinity(self, session_id: str) -> Optional[SessionAffinity]:
        """Get session affinity from cache or Redis."""
        # Check local cache
        if session_id in self.session_affinities:
            affinity = self.session_affinities[session_id]
            if not affinity.is_expired():
                return affinity
            else:
                del self.session_affinities[session_id]
        
        # Check Redis
        try:
            affinity_data = await self.redis.hget(
                "executor:loadbalancer:affinities",
                session_id
            )
            if affinity_data:
                data = json.loads(affinity_data)
                affinity = SessionAffinity(**data)
                if not affinity.is_expired():
                    self.session_affinities[session_id] = affinity
                    return affinity
                else:
                    await self.redis.hdel("executor:loadbalancer:affinities", session_id)
        except Exception as e:
            logger.error(f"Error getting session affinity: {e}")
        
        return None
    
    async def _set_session_affinity(self, session_id: str, pool_name: str):
        """Set session affinity in cache and Redis."""
        affinity = SessionAffinity(
            session_id=session_id,
            pool_name=pool_name,
            created_at=time.time()
        )
        
        self.session_affinities[session_id] = affinity
        
        try:
            await self.redis.hset(
                "executor:loadbalancer:affinities",
                session_id,
                json.dumps(asdict(affinity))
            )
            await self.redis.expire("executor:loadbalancer:affinities", affinity.ttl)
        except Exception as e:
            logger.error(f"Error setting session affinity: {e}")
    
    async def release_session(self, session_id: str, pool_name: str):
        """Release a session from a pool."""
        if pool_name in self.pools:
            pool = self.pools[pool_name]
            pool.current_sessions = max(0, pool.current_sessions - 1)
            await self._update_pool_metrics(pool)
        
        # Clear session affinity
        if session_id in self.session_affinities:
            del self.session_affinities[session_id]
        
        try:
            await self.redis.hdel("executor:loadbalancer:affinities", session_id)
        except Exception as e:
            logger.error(f"Error clearing session affinity: {e}")
    
    async def _health_check_loop(self):
        """Background task for health checks."""
        while self._running:
            try:
                await self._run_health_checks()
                await asyncio.sleep(self.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
                await asyncio.sleep(self.health_check_interval)
    
    async def _run_health_checks(self):
        """Run health checks on all pools."""
        async with aiohttp.ClientSession() as session:
            tasks = [
                self._check_pool_health(session, pool)
                for pool in self.pools.values()
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _check_pool_health(self, http_session: aiohttp.ClientSession, pool: PoolEndpoint):
        """Check health of a single pool."""
        start_time = time.time()
        
        try:
            async with http_session.get(
                f"{pool.url}/health",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                response_time = (time.time() - start_time) * 1000
                
                if response.status == 200:
                    data = await response.json()
                    
                    # Update pool metrics
                    pool.response_time_ms = response_time
                    pool.last_health_check = time.time()
                    pool.queue_depth = data.get("queue_depth", 0)
                    pool.cpu_utilization = data.get("cpu_percent", 0)
                    pool.memory_utilization = data.get("memory_percent", 0)
                    
                    # Update status based on metrics
                    if pool.cpu_utilization > 90 or pool.memory_utilization > 90:
                        pool.status = PoolStatus.DEGRADED
                    else:
                        pool.status = PoolStatus.HEALTHY
                    
                    # Record success for circuit breaker
                    self.circuit_breakers[pool.name].record_success()
                    
                else:
                    pool.status = PoolStatus.UNHEALTHY
                    self.circuit_breakers[pool.name].record_failure()
                    
        except asyncio.TimeoutError:
            pool.response_time_ms = 5000
            pool.status = PoolStatus.DEGRADED
            self.circuit_breakers[pool.name].record_failure()
            logger.warning(f"Health check timeout for pool {pool.name}")
            
        except Exception as e:
            pool.status = PoolStatus.UNHEALTHY
            self.circuit_breakers[pool.name].record_failure()
            logger.error(f"Health check failed for pool {pool.name}: {e}")
        
        # Persist updated metrics
        await self._update_pool_metrics(pool)
    
    async def _update_pool_metrics(self, pool: PoolEndpoint):
        """Update pool metrics in Redis."""
        try:
            await self.redis.hset(
                "executor:loadbalancer:pools",
                pool.name,
                json.dumps(pool.to_dict())
            )
        except Exception as e:
            logger.error(f"Error updating pool metrics: {e}")
    
    async def get_pool_stats(self) -> Dict:
        """Get statistics for all pools."""
        stats = {
            "total_pools": len(self.pools),
            "healthy_pools": sum(1 for p in self.pools.values() if p.status == PoolStatus.HEALTHY),
            "degraded_pools": sum(1 for p in self.pools.values() if p.status == PoolStatus.DEGRADED),
            "unhealthy_pools": sum(1 for p in self.pools.values() if p.status == PoolStatus.UNHEALTHY),
            "total_sessions": sum(p.current_sessions for p in self.pools.values()),
            "total_capacity": sum(p.max_sessions for p in self.pools.values()),
            "pools": {name: pool.to_dict() for name, pool in self.pools.items()}
        }
        
        return stats


# Singleton instance
_load_balancer: Optional[GlobalLoadBalancer] = None


async def get_load_balancer() -> GlobalLoadBalancer:
    """Get or create global load balancer instance."""
    global _load_balancer
    if _load_balancer is None:
        _load_balancer = GlobalLoadBalancer()
        await _load_balancer.start()
    return _load_balancer


async def init_load_balancer(redis_url: str = "redis://localhost:6379"):
    """Initialize the global load balancer."""
    global _load_balancer
    _load_balancer = GlobalLoadBalancer(redis_url=redis_url)
    await _load_balancer.start()


async def close_load_balancer():
    """Close the global load balancer."""
    global _load_balancer
    if _load_balancer:
        await _load_balancer.stop()
        _load_balancer = None
