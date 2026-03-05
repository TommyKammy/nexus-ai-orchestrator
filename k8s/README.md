# Executor Kubernetes Features - Deployment Guide

This directory contains the Kubernetes implementation for Executor Features 2-4:
- **Feature 2**: Auto-scaling with Kubernetes
- **Feature 3**: Global Load Balancer
- **Feature 4**: Session Persistence

## Architecture Overview

```
                    Internet / Clients
                            ↓
                    Caddy (HTTPS, Auth)
                            ↓
                  n8n (Webhooks/Orchestration)
                            ↓
                 Internal Executor API / LB Service
                            ↓
┌────────────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │             executor-system Namespace                         │  │
│  │                                                              │  │
│  │  OPA (PDP)   Redis (state/cache)   Operator (CRD control)    │  │
│  │      │                │                    │                  │  │
│  │      └────────────────┴────────────────────┘                  │  │
│  │                           ↓                                   │  │
│  │               Executor Load Balancer (2 replicas)             │  │
│  │                           ↓                                   │  │
│  │                   Executor Pools (HPA-managed)                │  │
│  │                [python-data] [python-ml] ...                 │  │
│  │                                                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘

Note: production external traffic is terminated at Caddy and routed to n8n.
`executor-edge` Ingress is an optional Kubernetes edge path for cluster-native routing/tests.
Executor services are internal and invoked by workflows/services in the default production flow.
```

## Core Stack (Issue #36 Scope)

The Kubernetes core stack in this repository is defined as:
- `executor-operator` Deployment (operator control plane)
- `redis` Deployment + Service (session/cache state)
- `executor-load-balancer` Deployment + Service (internal execution entrypoint)
- `opa` Deployment + Service (policy decision point)
- `executor-edge` Ingress (edge routing to `executor-load-balancer`)

## Quick Start

### 1. Prerequisites

- Kubernetes cluster (v1.25+)
- kubectl configured
- Docker registry access
- Prometheus Operator (optional, for monitoring)
- Ingress controller that provides class `nginx` (for `executor-edge` Ingress)
- DNS/hosts mapping for `executor.local`, or explicit `Host: executor.local` header for ingress verification

If you apply the entire `k8s/config/deployment/` directory, install Prometheus Operator CRDs
(`ServiceMonitor` and `PrometheusRule`) first.

### 2. Deploy CRDs

```bash
kubectl apply -f k8s/config/crd/executor-crd.yaml
```

### 3. Build and Push Images

```bash
# Update the build script with your registry
export REGISTRY=your-registry.com/executor

# Build images
bash k8s/config/deployment/build-images.sh
```

### 4. Deploy Operator and Infrastructure

```bash
kubectl apply -f k8s/config/deployment/operator-deployment.yaml
kubectl apply -f k8s/config/deployment/opa-deployment.yaml
kubectl apply -f k8s/config/deployment/network-policies.yaml
kubectl apply -f k8s/config/deployment/ingress.yaml
```

### 5. Create Executor Pools

```bash
# Create a pool for data science workloads
kubectl apply -f - <<EOF
apiVersion: executor.ai-orchestrator.io/v1
kind: ExecutorPool
metadata:
  name: python-data-pool
  namespace: executor-system
spec:
  template: python-data
  minReplicas: 2
  maxReplicas: 20
  targetCPUUtilizationPercentage: 70
  targetQueueDepth: 10
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 1000m
      memory: 1Gi
  sessionTTL: 300
  enableMetrics: true
EOF
```

### 6. Verify Deployment

```bash
# Check operator
kubectl get pods -n executor-system

# Check pools
kubectl get executorpools -n executor-system

# Check HPA
kubectl get hpa -n executor-system

# Check services
kubectl get svc -n executor-system

# Check core stack resources
kubectl get deploy,svc,ingress -n executor-system

# Verify ingress routing (example with port-forward)
kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 18081:80
curl -H "Host: executor.local" http://127.0.0.1:18081/health
```

## Custom Resources

### ExecutorPool

Defines a pool of executor pods with auto-scaling configuration.

```yaml
apiVersion: executor.ai-orchestrator.io/v1
kind: ExecutorPool
metadata:
  name: my-pool
spec:
  template: python-data          # Sandbox template
  minReplicas: 2                 # Minimum pods
  maxReplicas: 20                # Maximum pods
  targetCPUUtilizationPercentage: 70
  targetQueueDepth: 10           # Scale based on queue
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 1000m
      memory: 1Gi
  sessionTTL: 300               # Session timeout
  enableMetrics: true           # Prometheus metrics
  networkEnabled: false         # Network access
```

### ExecutorSession

Represents a user session assigned to a pod.

```yaml
apiVersion: executor.ai-orchestrator.io/v1
kind: ExecutorSession
metadata:
  name: session-123
spec:
  poolRef: python-data-pool
  sessionId: session-123
  template: python-data
  ttl: 600
  persist: true                 # Persist across restarts
  metadata:
    user: "user@example.com"
    project: "data-analysis"
```

## Load Balancer API

The load balancer provides the following endpoints:

### Register a Pool

```bash
POST /pools/register
{
  "name": "us-east-pool",
  "region": "us-east",
  "url": "http://executor-pool-us-east.default.svc",
  "weight": 100,
  "priority": 1,
  "max_sessions": 100
}
```

### Assign Session

```bash
POST /sessions/assign
{
  "session_id": "session-456",
  "preferred_region": "us-east"
}
```

Response:
```json
{
  "name": "us-east-pool",
  "region": "us-east",
  "url": "http://executor-pool-us-east.default.svc",
  "status": "healthy",
  "current_sessions": 15,
  "max_sessions": 100
}
```

### Get Statistics

```bash
GET /stats
```

## Session Persistence

Sessions are automatically persisted to Redis when:
- Pod is about to be terminated (preStop hook)
- Session is marked with `persist: true`
- Periodic snapshot (every 60 seconds)

Sessions can be restored to a new pod during:
- Pod migration
- Pool scaling
- Rolling updates

## Monitoring

### Prometheus Metrics

The following metrics are exported:

- `executor_queue_depth` - Current queue depth per pool
- `executor_cpu_utilization` - CPU utilization per pool
- `executor_memory_utilization` - Memory utilization per pool
- `executor_session_count` - Active sessions per pool
- `executor_session_migration_total` - Session migration count
- `executor_load_balancer_requests_total` - LB request count

### Grafana Dashboard

Import the dashboard from `monitoring/grafana-dashboard.json`

### Alerts

The following alerts are configured:

- `ExecutorPoolDown` - Pool is not responding
- `ExecutorHighQueueDepth` - Queue depth > 50
- `ExecutorHighCPUUtilization` - CPU > 90%
- `ExecutorSessionMigrationFailed` - Migration failures

## Scaling Behavior

### Scale Up

- Trigger: CPU > 70% OR Queue depth > 10 per pod
- Speed: 100% increase every 15 seconds
- Stabilization: 60 seconds

### Scale Down

- Trigger: CPU < 30% AND Queue depth < 5 per pod
- Speed: 10% decrease every 60 seconds
- Stabilization: 300 seconds (5 minutes)

### Circuit Breaker

- Opens after: 5 consecutive failures
- Recovery timeout: 30 seconds
- Test requests: 3 successful to close

## Troubleshooting

### Check Operator Logs

```bash
kubectl logs -n executor-system deployment/executor-operator -f
```

### Check Load Balancer

```bash
kubectl logs -n executor-system deployment/executor-load-balancer -f
```

### Check Pool Status

```bash
kubectl describe executorpools python-data-pool -n executor-system
```

### Redis Connection Issues

```bash
kubectl exec -it -n executor-system deployment/redis -- redis-cli ping
```

### Session Migration Debugging

```bash
# Check session in Redis
kubectl exec -it -n executor-system deployment/redis -- redis-cli hgetall executor:session:SESSION_ID

# Check session files
kubectl exec -it -n executor-system deployment/redis -- redis-cli hkeys executor:session:SESSION_ID:files
```

## Cleanup

```bash
# Delete all pools
kubectl delete executorpools --all -n executor-system

# Delete all sessions
kubectl delete executorsessions --all -n executor-system

# Delete operator
kubectl delete -f k8s/config/deployment/operator-deployment.yaml

# Delete CRDs
kubectl delete -f k8s/config/crd/executor-crd.yaml
```

## Advanced Configuration

### Multi-Region Setup

1. Deploy operator in each region
2. Configure load balancer with region awareness
3. Use geographic routing

### Custom Metrics Scaling

Enable custom metrics scaling with Prometheus Adapter:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: executor-pool-custom
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: executor-pool-python-data
  metrics:
    - type: Pods
      pods:
        metric:
          name: executor_queue_depth
        target:
          type: AverageValue
          averageValue: "10"
```

### Node Affinity

Add node affinity to pool spec:

```yaml
spec:
  template:
    spec:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: node-type
                    operator: In
                    values:
                      - compute-optimized
```

## Performance Tuning

### Redis Optimization

- Use Redis Cluster for high availability
- Enable Redis persistence (AOF)
- Configure appropriate maxmemory policy

### Load Balancer Optimization

- Increase replicas for high availability
- Adjust health check intervals
- Tune circuit breaker thresholds

### Operator Optimization

- Adjust reconciliation intervals
- Configure rate limits
- Enable leader election for HA
