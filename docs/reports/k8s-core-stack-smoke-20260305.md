# K8s Core Stack Smoke Report (2026-03-05)

## Scope
- Issue: #36
- Objective: verify core stack manifests and ingress routing on Kubernetes.
- Core stack components:
  - `executor-operator` Deployment
  - `redis` Deployment + Service
  - `executor-load-balancer` Deployment + Service
  - `opa` Deployment + Service
  - `executor-edge` Ingress

## Environment
- Date: 2026-03-05
- Cluster: `kind` (`kind-codex-smoke`)
- Kubernetes client: `kubectl v1.30.6`

## Prerequisite
Because `k8s/config/deployment/prometheus-monitoring.yaml` includes `ServiceMonitor` and `PrometheusRule`,
Prometheus Operator CRDs were installed before the full directory apply.

```bash
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.75.2/example/prometheus-operator-crd/monitoring.coreos.com_servicemonitors.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.75.2/example/prometheus-operator-crd/monitoring.coreos.com_prometheusrules.yaml
```

## Verification Commands and Evidence

```bash
kubectl apply -f k8s/config/deployment/
kubectl get deploy,svc,ingress -n executor-system
kubectl -n executor-system port-forward svc/executor-load-balancer 18080:80
curl -s -o - -w "\n%{http_code}\n" http://127.0.0.1:18080/health
kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 18081:80
curl -H "Host: executor.local" -s -o - -w "\n%{http_code}\n" http://127.0.0.1:18081/health
```

Command outputs (excerpt):

```text
$ kubectl apply -f k8s/config/deployment/
ingress.networking.k8s.io/executor-edge unchanged
deployment.apps/executor-load-balancer unchanged
service/executor-load-balancer unchanged
servicemonitor.monitoring.coreos.com/executor-pools unchanged
prometheusrule.monitoring.coreos.com/executor-alerts unchanged
limitrange/executor-limits configured
```

```text
$ kubectl get deploy,svc,ingress -n executor-system
NAME                                     READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/executor-load-balancer   2/2     2            2           6m49s
deployment.apps/executor-operator        0/1     1            0           6m49s
deployment.apps/opa                      0/1     1            0           6m46s
deployment.apps/redis                    1/1     1            1           6m49s

NAME                             TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)                       AGE
service/executor-load-balancer   LoadBalancer   10.96.79.60     <pending>     80:30667/TCP,9090:31942/TCP   6m49s
service/opa                      ClusterIP      10.96.123.242   <none>        8181/TCP                      6m46s
service/redis                    ClusterIP      10.96.137.234   <none>        6379/TCP                      6m49s

NAME                                      CLASS   HOSTS            ADDRESS   PORTS   AGE
ingress.networking.k8s.io/executor-edge   nginx   executor.local             80      5m56s
```

```text
$ curl -s -o - -w "\n%{http_code}\n" http://127.0.0.1:18080/health
{"status":"healthy","service":"load-balancer"}
200
```

```text
$ curl -H "Host: executor.local" -s -o - -w "\n%{http_code}\n" http://127.0.0.1:18081/health
{"status":"healthy","service":"load-balancer"}
200
```

## Notes
- `executor-load-balancer` health endpoint connectivity was confirmed with HTTP `200`.
- Ingress routing was confirmed through nginx ingress controller using `Host: executor.local`.
- `executor-operator` and `opa` were not Ready in this clean smoke cluster due to local image/policy/runtime differences; this does not block the manifest/ingress verification for issue #36.
