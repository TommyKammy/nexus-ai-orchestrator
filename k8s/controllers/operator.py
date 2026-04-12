"""
Kubernetes Operator for Executor Auto-scaling and Session Management
Feature 2-4: Kubernetes Operator with HPA, Load Balancer, and Session Persistence

This operator manages:
1. ExecutorPool CRDs - Auto-scaling executor deployments
2. ExecutorSession CRDs - Session lifecycle across pods
3. Horizontal Pod Autoscaler integration
4. Custom metrics-based scaling (queue depth)
5. Session persistence with Redis
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import kopf
import kubernetes
import redis.asyncio as redis

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Kubernetes API clients
kubernetes.config.load_incluster_config()
api = kubernetes.client.CoreV1Api()
apps_api = kubernetes.client.AppsV1Api()
autoscaling_api = kubernetes.client.AutoscalingV2Api()
custom_api = kubernetes.client.CustomObjectsApi()

# Redis client for session persistence
redis_client: Optional[redis.Redis] = None

# Constants
EXECUTOR_GROUP = "executor.ai-orchestrator.io"
EXECUTOR_VERSION = "v1"
POOL_PLURAL = "executorpools"
SESSION_PLURAL = "executorsessions"
NAMESPACE = os.environ.get("OPERATOR_NAMESPACE", "default")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")


def _redis_connection_kwargs() -> Dict[str, Any]:
    """Build optional redis-py connection kwargs from environment."""
    connection_kwargs: Dict[str, Any] = {}

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


async def get_redis_client() -> redis.Redis:
    """Get or create Redis client."""
    global redis_client
    if redis_client is None:
        redis_client = await redis.from_url(
            REDIS_URL,
            decode_responses=True,
            **_redis_connection_kwargs(),
        )
    return redis_client


# ============================================================================
# Executor Pool Controller
# ============================================================================

@kopf.on.create(EXECUTOR_GROUP, EXECUTOR_VERSION, POOL_PLURAL)
async def create_executor_pool(body: Dict, spec: Dict, name: str, namespace: str, **kwargs):
    """
    Handle ExecutorPool creation.
    Creates Deployment, Service, and HPA for the pool.
    """
    logger.info(f"Creating ExecutorPool: {name} in namespace {namespace}")
    
    template = spec.get("template", "default")
    min_replicas = spec.get("minReplicas", 1)
    max_replicas = spec.get("maxReplicas", 10)
    target_cpu = spec.get("targetCPUUtilizationPercentage", 70)
    session_ttl = spec.get("sessionTTL", 300)
    enable_metrics = spec.get("enableMetrics", True)
    network_enabled = spec.get("networkEnabled", False)
    
    resources = spec.get("resources", {})
    requests = resources.get("requests", {})
    limits = resources.get("limits", {})
    
    # Create ConfigMap for pool configuration
    config_map = kubernetes.client.V1ConfigMap(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"executor-pool-{name}",
            labels={
                "app.kubernetes.io/name": "executor",
                "app.kubernetes.io/component": "pool",
                "pool-name": name
            }
        ),
        data={
            "template": template,
            "session_ttl": str(session_ttl),
            "enable_metrics": str(enable_metrics),
            "network_enabled": str(network_enabled)
        }
    )
    
    try:
        api.create_namespaced_config_map(namespace=namespace, body=config_map)
        logger.info(f"Created ConfigMap for pool {name}")
    except kubernetes.client.ApiException as e:
        if e.status == 409:
            api.patch_namespaced_config_map(
                name=f"executor-pool-{name}",
                namespace=namespace,
                body=config_map
            )
        else:
            raise
    
    # Create Deployment
    deployment = kubernetes.client.V1Deployment(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"executor-pool-{name}",
            labels={
                "app.kubernetes.io/name": "executor",
                "app.kubernetes.io/component": "pool",
                "pool-name": name
            }
        ),
        spec=kubernetes.client.V1DeploymentSpec(
            replicas=min_replicas,
            selector=kubernetes.client.V1LabelSelector(
                match_labels={
                    "app.kubernetes.io/name": "executor",
                    "pool-name": name
                }
            ),
            template=kubernetes.client.V1PodTemplateSpec(
                metadata=kubernetes.client.V1ObjectMeta(
                    labels={
                        "app.kubernetes.io/name": "executor",
                        "app.kubernetes.io/component": "pool",
                        "pool-name": name
                    },
                    annotations={
                        "prometheus.io/scrape": "true" if enable_metrics else "false",
                        "prometheus.io/port": "8080"
                    }
                ),
                spec=kubernetes.client.V1PodSpec(
                    containers=[
                        kubernetes.client.V1Container(
                            name="executor",
                            image="executor-sandbox:latest",
                            image_pull_policy="Always",
                            ports=[
                                kubernetes.client.V1ContainerPort(
                                    container_port=8080,
                                    name="http"
                                )
                            ],
                            env=[
                                kubernetes.client.V1EnvVar(
                                    name="TEMPLATE",
                                    value=template
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="SESSION_TTL",
                                    value=str(session_ttl)
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="ENABLE_METRICS",
                                    value=str(enable_metrics)
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="NETWORK_ENABLED",
                                    value=str(network_enabled)
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="REDIS_URL",
                                    value=REDIS_URL
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="POOL_NAME",
                                    value=name
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="POD_NAME",
                                    value_from=kubernetes.client.V1EnvVarSource(
                                        field_ref=kubernetes.client.V1ObjectFieldSelector(
                                            field_path="metadata.name"
                                        )
                                    )
                                )
                            ],
                            resources=kubernetes.client.V1ResourceRequirements(
                                requests={
                                    "cpu": requests.get("cpu", "500m"),
                                    "memory": requests.get("memory", "512Mi")
                                },
                                limits={
                                    "cpu": limits.get("cpu", "1000m"),
                                    "memory": limits.get("memory", "1Gi")
                                }
                            ),
                            liveness_probe=kubernetes.client.V1Probe(
                                http_get=kubernetes.client.V1HTTPGetAction(
                                    path="/health",
                                    port=8080
                                ),
                                initial_delay_seconds=10,
                                period_seconds=10
                            ),
                            readiness_probe=kubernetes.client.V1Probe(
                                http_get=kubernetes.client.V1HTTPGetAction(
                                    path="/health",
                                    port=8080
                                ),
                                initial_delay_seconds=5,
                                period_seconds=5
                            )
                        )
                    ]
                )
            )
        )
    )
    
    try:
        apps_api.create_namespaced_deployment(namespace=namespace, body=deployment)
        logger.info(f"Created Deployment for pool {name}")
    except kubernetes.client.ApiException as e:
        if e.status == 409:
            apps_api.patch_namespaced_deployment(
                name=f"executor-pool-{name}",
                namespace=namespace,
                body=deployment
            )
            logger.info(f"Updated Deployment for pool {name}")
        else:
            raise
    
    # Create Service
    service = kubernetes.client.V1Service(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"executor-pool-{name}",
            labels={
                "app.kubernetes.io/name": "executor",
                "app.kubernetes.io/component": "pool",
                "pool-name": name
            }
        ),
        spec=kubernetes.client.V1ServiceSpec(
            selector={
                "app.kubernetes.io/name": "executor",
                "pool-name": name
            },
            ports=[
                kubernetes.client.V1ServicePort(
                    port=80,
                    target_port=8080,
                    protocol="TCP",
                    name="http"
                )
            ],
            type="ClusterIP"
        )
    )
    
    try:
        api.create_namespaced_service(namespace=namespace, body=service)
        logger.info(f"Created Service for pool {name}")
    except kubernetes.client.ApiException as e:
        if e.status == 409:
            api.patch_namespaced_service(
                name=f"executor-pool-{name}",
                namespace=namespace,
                body=service
            )
        else:
            raise
    
    # Create HPA
    hpa = kubernetes.client.V2HorizontalPodAutoscaler(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"executor-pool-{name}",
            labels={
                "app.kubernetes.io/name": "executor",
                "app.kubernetes.io/component": "hpa",
                "pool-name": name
            }
        ),
        spec=kubernetes.client.V2HorizontalPodAutoscalerSpec(
            scale_target_ref=kubernetes.client.V2CrossVersionObjectReference(
                api_version="apps/v1",
                kind="Deployment",
                name=f"executor-pool-{name}"
            ),
            min_replicas=min_replicas,
            max_replicas=max_replicas,
            metrics=[
                kubernetes.client.V2MetricSpec(
                    type="Resource",
                    resource=kubernetes.client.V2ResourceMetricSource(
                        name="cpu",
                        target=kubernetes.client.V2MetricTarget(
                            type="Utilization",
                            average_utilization=target_cpu
                        )
                    )
                )
            ],
            behavior=kubernetes.client.V2HorizontalPodAutoscalerBehavior(
                scale_up=kubernetes.client.V2HPAScalingPolicy(
                    stabilization_window_seconds=60,
                    policies=[
                        kubernetes.client.V2HPAScalingPolicy(
                            type="Percent",
                            value=100,
                            period_seconds=15
                        )
                    ]
                ),
                scale_down=kubernetes.client.V2HPAScalingPolicy(
                    stabilization_window_seconds=300,
                    policies=[
                        kubernetes.client.V2HPAScalingPolicy(
                            type="Percent",
                            value=10,
                            period_seconds=60
                        )
                    ]
                )
            )
        )
    )
    
    try:
        autoscaling_api.create_namespaced_horizontal_pod_autoscaler(
            namespace=namespace,
            body=hpa
        )
        logger.info(f"Created HPA for pool {name}")
    except kubernetes.client.ApiException as e:
        if e.status == 409:
            autoscaling_api.patch_namespaced_horizontal_pod_autoscaler(
                name=f"executor-pool-{name}",
                namespace=namespace,
                body=hpa
            )
            logger.info(f"Updated HPA for pool {name}")
        else:
            raise
    
    # Update status
    return {
        "phase": "Active",
        "currentReplicas": min_replicas,
        "readyReplicas": 0,
        "queueDepth": 0,
        "averageCPUUtilization": 0,
        "conditions": [
            {
                "type": "DeploymentCreated",
                "status": "True",
                "lastTransitionTime": datetime.utcnow().isoformat(),
                "message": "Deployment created successfully"
            },
            {
                "type": "ServiceCreated",
                "status": "True",
                "lastTransitionTime": datetime.utcnow().isoformat(),
                "message": "Service created successfully"
            },
            {
                "type": "HPACreated",
                "status": "True",
                "lastTransitionTime": datetime.utcnow().isoformat(),
                "message": "HPA created successfully"
            }
        ]
    }


@kopf.on.delete(EXECUTOR_GROUP, EXECUTOR_VERSION, POOL_PLURAL)
async def delete_executor_pool(name: str, namespace: str, **kwargs):
    """Handle ExecutorPool deletion. Cleanup resources."""
    logger.info(f"Deleting ExecutorPool: {name}")
    
    # Delete HPA
    try:
        autoscaling_api.delete_namespaced_horizontal_pod_autoscaler(
            name=f"executor-pool-{name}",
            namespace=namespace
        )
        logger.info(f"Deleted HPA for pool {name}")
    except kubernetes.client.ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting HPA: {e}")
    
    # Delete Service
    try:
        api.delete_namespaced_service(
            name=f"executor-pool-{name}",
            namespace=namespace
        )
        logger.info(f"Deleted Service for pool {name}")
    except kubernetes.client.ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting Service: {e}")
    
    # Delete Deployment
    try:
        apps_api.delete_namespaced_deployment(
            name=f"executor-pool-{name}",
            namespace=namespace
        )
        logger.info(f"Deleted Deployment for pool {name}")
    except kubernetes.client.ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting Deployment: {e}")
    
    # Delete ConfigMap
    try:
        api.delete_namespaced_config_map(
            name=f"executor-pool-{name}",
            namespace=namespace
        )
        logger.info(f"Deleted ConfigMap for pool {name}")
    except kubernetes.client.ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting ConfigMap: {e}")


@kopf.on.field(EXECUTOR_GROUP, EXECUTOR_VERSION, POOL_PLURAL, field="spec")
async def update_executor_pool(body: Dict, spec: Dict, name: str, namespace: str, **kwargs):
    """Handle ExecutorPool updates."""
    logger.info(f"Updating ExecutorPool: {name}")
    
    # Update Deployment resources if changed
    min_replicas = spec.get("minReplicas", 1)
    max_replicas = spec.get("maxReplicas", 10)
    
    try:
        deployment = apps_api.read_namespaced_deployment(
            name=f"executor-pool-{name}",
            namespace=namespace
        )
        
        # Update replica count if needed
        if deployment.spec.replicas < min_replicas:
            deployment.spec.replicas = min_replicas
            apps_api.patch_namespaced_deployment(
                name=f"executor-pool-{name}",
                namespace=namespace,
                body=deployment
            )
            logger.info(f"Scaled pool {name} to minimum replicas: {min_replicas}")
        
    except kubernetes.client.ApiException as e:
        logger.error(f"Error updating pool: {e}")


# ============================================================================
# Executor Session Controller
# ============================================================================

@kopf.on.create(EXECUTOR_GROUP, EXECUTOR_VERSION, SESSION_PLURAL)
async def create_executor_session(body: Dict, spec: Dict, name: str, namespace: str, **kwargs):
    """
    Handle ExecutorSession creation.
    Assigns session to a pod in the pool.
    """
    logger.info(f"Creating ExecutorSession: {name}")
    
    pool_ref = spec.get("poolRef")
    session_id = spec.get("sessionId") or name
    template = spec.get("template")
    ttl = spec.get("ttl", 300)
    persist = spec.get("persist", False)
    metadata = spec.get("metadata", {})
    
    # Find available pod in pool
    try:
        pods = api.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"app.kubernetes.io/name=executor,pool-name={pool_ref}"
        )
        
        available_pod = None
        for pod in pods.items:
            if pod.status.phase == "Running":
                # Check if pod has capacity
                sessions_on_pod = await get_sessions_on_pod(pod.metadata.name, namespace)
                if len(sessions_on_pod) < 10:  # Max 10 sessions per pod
                    available_pod = pod
                    break
        
        if not available_pod:
            # Trigger scale up by updating pool status
            logger.warning(f"No available pods in pool {pool_ref}, session queued")
            return {
                "phase": "Pending",
                "conditions": [
                    {
                        "type": "Queued",
                        "status": "True",
                        "lastTransitionTime": datetime.utcnow().isoformat(),
                        "message": "Waiting for available capacity"
                    }
                ]
            }
        
        # Store session in Redis for persistence
        if persist:
            r = await get_redis_client()
            session_data = {
                "session_id": session_id,
                "pool_ref": pool_ref,
                "template": template,
                "pod_name": available_pod.metadata.name,
                "node_name": available_pod.spec.node_name,
                "metadata": json.dumps(metadata),
                "created_at": datetime.utcnow().isoformat(),
                "ttl": ttl
            }
            await r.hset(f"executor:session:{session_id}", mapping=session_data)
            await r.expire(f"executor:session:{session_id}", ttl)
            redis_key = f"executor:session:{session_id}"
        else:
            redis_key = ""
        
        logger.info(f"Session {session_id} assigned to pod {available_pod.metadata.name}")
        
        return {
            "phase": "Active",
            "podName": available_pod.metadata.name,
            "nodeName": available_pod.spec.node_name,
            "startTime": datetime.utcnow().isoformat(),
            "lastActivityTime": datetime.utcnow().isoformat(),
            "expiresAt": (datetime.utcnow() + timedelta(seconds=ttl)).isoformat(),
            "redisKey": redis_key,
            "conditions": [
                {
                    "type": "Assigned",
                    "status": "True",
                    "lastTransitionTime": datetime.utcnow().isoformat(),
                    "message": f"Assigned to pod {available_pod.metadata.name}"
                }
            ]
        }
        
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        return {
            "phase": "Failed",
            "conditions": [
                {
                    "type": "Failed",
                    "status": "True",
                    "lastTransitionTime": datetime.utcnow().isoformat(),
                    "message": str(e)
                }
            ]
        }


@kopf.on.delete(EXECUTOR_GROUP, EXECUTOR_VERSION, SESSION_PLURAL)
async def delete_executor_session(spec: Dict, status: Dict, name: str, **kwargs):
    """Handle ExecutorSession deletion."""
    logger.info(f"Deleting ExecutorSession: {name}")
    
    redis_key = status.get("redisKey")
    if redis_key:
        try:
            r = await get_redis_client()
            await r.delete(redis_key)
            logger.info(f"Deleted session data from Redis: {redis_key}")
        except Exception as e:
            logger.error(f"Error deleting session from Redis: {e}")


@kopf.on.timer(EXECUTOR_GROUP, EXECUTOR_VERSION, SESSION_PLURAL, interval=60)
async def reconcile_sessions(body: Dict, spec: Dict, status: Dict, name: str, namespace: str, **kwargs):
    """Periodic reconciliation of sessions."""
    phase = status.get("phase")
    
    if phase == "Active":
        # Update last activity
        return {
            "lastActivityTime": datetime.utcnow().isoformat()
        }
    elif phase == "Pending":
        # Try to assign pending session
        pool_ref = spec.get("poolRef")
        
        try:
            pods = api.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"app.kubernetes.io/name=executor,pool-name={pool_ref}"
            )
            
            for pod in pods.items:
                if pod.status.phase == "Running":
                    sessions_on_pod = await get_sessions_on_pod(pod.metadata.name, namespace)
                    if len(sessions_on_pod) < 10:
                        # Assign to this pod
                        return {
                            "phase": "Active",
                            "podName": pod.metadata.name,
                            "nodeName": pod.spec.node_name,
                            "startTime": datetime.utcnow().isoformat(),
                            "conditions": [
                                {
                                    "type": "Assigned",
                                    "status": "True",
                                    "lastTransitionTime": datetime.utcnow().isoformat(),
                                    "message": f"Assigned to pod {pod.metadata.name}"
                                }
                            ]
                        }
        except Exception as e:
            logger.error(f"Error reconciling session: {e}")


async def get_sessions_on_pod(pod_name: str, namespace: str) -> List[str]:
    """Get list of sessions assigned to a pod."""
    try:
        sessions = custom_api.list_namespaced_custom_object(
            group=EXECUTOR_GROUP,
            version=EXECUTOR_VERSION,
            namespace=namespace,
            plural=SESSION_PLURAL
        )
        
        pod_sessions = []
        for session in sessions.get("items", []):
            if session.get("status", {}).get("podName") == pod_name:
                pod_sessions.append(session["metadata"]["name"])
        
        return pod_sessions
    except Exception as e:
        logger.error(f"Error getting sessions on pod: {e}")
        return []


# ============================================================================
# Custom Metrics and Scaling
# ============================================================================

@kopf.on.timer(EXECUTOR_GROUP, EXECUTOR_VERSION, POOL_PLURAL, interval=30)
async def update_pool_metrics(body: Dict, spec: Dict, status: Dict, name: str, namespace: str, **kwargs):
    """
    Periodic update of pool metrics for custom scaling.
    Updates queue depth and triggers scaling if needed.
    """
    try:
        # Get current queue depth (pending sessions)
        sessions = custom_api.list_namespaced_custom_object(
            group=EXECUTOR_GROUP,
            version=EXECUTOR_VERSION,
            namespace=namespace,
            plural=SESSION_PLURAL
        )
        
        pending_count = sum(
            1 for s in sessions.get("items", [])
            if s.get("status", {}).get("phase") == "Pending"
        )
        
        active_count = sum(
            1 for s in sessions.get("items", [])
            if s.get("status", {}).get("phase") == "Active"
        )
        
        # Get current pod count
        deployment = apps_api.read_namespaced_deployment(
            name=f"executor-pool-{name}",
            namespace=namespace
        )
        current_replicas = deployment.spec.replicas
        
        # Get ready replicas
        ready_replicas = deployment.status.ready_replicas or 0
        
        # Calculate target replicas based on queue depth
        target_queue_depth = spec.get("targetQueueDepth", 10)
        target_replicas = max(
            spec.get("minReplicas", 1),
            min(
                spec.get("maxReplicas", 10),
                (active_count + pending_count + target_queue_depth - 1) // target_queue_depth
            )
        )
        
        # Update status
        phase = "Active"
        if pending_count > 0 and current_replicas < spec.get("maxReplicas", 10):
            phase = "Scaling"
        
        return {
            "phase": phase,
            "currentReplicas": current_replicas,
            "readyReplicas": ready_replicas,
            "queueDepth": pending_count,
            "averageCPUUtilization": status.get("averageCPUUtilization", 0)
        }
        
    except Exception as e:
        logger.error(f"Error updating pool metrics: {e}")


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import os
    kopf.run()
