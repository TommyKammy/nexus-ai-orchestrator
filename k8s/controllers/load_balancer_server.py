"""
Load Balancer HTTP Server
FastAPI-based API for the global load balancer
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel

from load_balancer import GlobalLoadBalancer, get_load_balancer, init_load_balancer, close_load_balancer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Pydantic models
class PoolRegistration(BaseModel):
    name: str
    region: str
    url: str
    weight: int = 100
    priority: int = 1
    max_sessions: int = 100


class SessionRequest(BaseModel):
    session_id: str
    preferred_region: Optional[str] = None


class PoolResponse(BaseModel):
    name: str
    region: str
    url: str
    status: str
    current_sessions: int
    max_sessions: int


class StatsResponse(BaseModel):
    total_pools: int
    healthy_pools: int
    degraded_pools: int
    unhealthy_pools: int
    total_sessions: int
    total_capacity: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    # Startup
    logger.info("Starting Load Balancer Server")
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379")
    await init_load_balancer(redis_url)
    yield
    # Shutdown
    logger.info("Shutting down Load Balancer Server")
    await close_load_balancer()


app = FastAPI(
    title="Executor Global Load Balancer",
    description="Global load balancing for executor pools with health checks",
    version="1.0.0",
    lifespan=lifespan
)


async def get_lb() -> GlobalLoadBalancer:
    """Dependency to get load balancer instance."""
    return await get_load_balancer()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "load-balancer"}


@app.post("/pools/register", response_model=PoolResponse)
async def register_pool(
    pool: PoolRegistration,
    lb: GlobalLoadBalancer = Depends(get_lb)
):
    """Register a new pool endpoint."""
    success = await lb.register_pool(
        name=pool.name,
        region=pool.region,
        url=pool.url,
        weight=pool.weight,
        priority=pool.priority,
        max_sessions=pool.max_sessions
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to register pool")
    
    return PoolResponse(
        name=pool.name,
        region=pool.region,
        url=pool.url,
        status="healthy",
        current_sessions=0,
        max_sessions=pool.max_sessions
    )


@app.delete("/pools/{pool_name}")
async def unregister_pool(
    pool_name: str,
    lb: GlobalLoadBalancer = Depends(get_lb)
):
    """Unregister a pool endpoint."""
    success = await lb.unregister_pool(pool_name)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to unregister pool")
    
    return {"message": f"Pool {pool_name} unregistered"}


@app.post("/sessions/assign", response_model=PoolResponse)
async def assign_session(
    request: SessionRequest,
    lb: GlobalLoadBalancer = Depends(get_lb)
):
    """Assign a session to a pool."""
    pool = await lb.get_pool_for_session(
        session_id=request.session_id,
        preferred_region=request.preferred_region
    )
    
    if not pool:
        raise HTTPException(status_code=503, detail="No available pools")
    
    return PoolResponse(
        name=pool.name,
        region=pool.region,
        url=pool.url,
        status=pool.status.value,
        current_sessions=pool.current_sessions,
        max_sessions=pool.max_sessions
    )


@app.post("/sessions/{session_id}/release")
async def release_session(
    session_id: str,
    pool_name: str,
    lb: GlobalLoadBalancer = Depends(get_lb)
):
    """Release a session from a pool."""
    await lb.release_session(session_id, pool_name)
    return {"message": f"Session {session_id} released from {pool_name}"}


@app.get("/pools", response_model=list[PoolResponse])
async def list_pools(lb: GlobalLoadBalancer = Depends(get_lb)):
    """List all registered pools."""
    pools = []
    for name, pool in lb.pools.items():
        pools.append(PoolResponse(
            name=pool.name,
            region=pool.region,
            url=pool.url,
            status=pool.status.value,
            current_sessions=pool.current_sessions,
            max_sessions=pool.max_sessions
        ))
    return pools


@app.get("/stats", response_model=StatsResponse)
async def get_stats(lb: GlobalLoadBalancer = Depends(get_lb)):
    """Get load balancer statistics."""
    stats = await lb.get_pool_stats()
    return StatsResponse(
        total_pools=stats["total_pools"],
        healthy_pools=stats["healthy_pools"],
        degraded_pools=stats["degraded_pools"],
        unhealthy_pools=stats["unhealthy_pools"],
        total_sessions=stats["total_sessions"],
        total_capacity=stats["total_capacity"]
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
