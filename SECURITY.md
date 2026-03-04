# Security Documentation

This document describes the security features of the Executor system and provides guidance on secure deployment.

## Table of Contents

1. [Security Features](#security-features)
2. [Docker-in-Docker (DinD) Security](#docker-in-docker-dind-security)
3. [API Authentication](#api-authentication)
4. [Production Deployment](#production-deployment)
5. [Security Best Practices](#security-best-practices)
6. [Threat Model and Checklist v1](#threat-model-and-checklist-v1)
7. [Reporting Security Issues](#reporting-security-issues)

---

## Security Features

### Container Isolation

The Executor uses Docker containers with comprehensive security options:

- **Read-only root filesystem**: Containers cannot modify their root filesystem
- **No new privileges**: Prevents privilege escalation via `setuid` binaries
- **Capability dropping**: All Linux capabilities are dropped by default
- **User isolation**: Containers run as non-root `sandbox` user (UID 1000)
- **Resource limits**: CPU, memory, and disk quotas enforced
- **Network isolation**: Containers have no network access by default (optional)
- **tmpfs with noexec**: Temporary directories mounted with `noexec` flag

### Path Traversal Protection

All file operations are validated through `SecurePathValidator`:

- Null byte detection
- Path traversal prevention (`../`)
- Absolute path rejection
- Base directory confinement
- Dangerous extension blocking

### Session Management

- **Race condition protection**: Semaphore-based limiting prevents exceeding `max_sessions`
- **TTL enforcement**: Automatic cleanup of expired sessions
- **Resource tracking**: Metrics and limits on concurrent executions

---

## Docker-in-Docker (DinD) Security

### Current Implementation

The Executor currently uses **privileged Docker-in-Docker** for sandbox creation:

```yaml
privileged: true  # Required for Docker-in-Docker
```

**Security Implications:**
- Container has full access to host devices
- Can modify host kernel parameters
- Bypasses most container isolation
- Potential for container escape

### Mitigations in Place

1. **Resource limits**: CPU (2 cores) and memory (2GB) constraints
2. **Localhost binding**: API only accessible via `127.0.0.1:8080`
3. **Read-only mounts**: Executor code mounted read-only
4. **Health checks**: Container health monitoring

### Recommended Alternatives

#### Option 1: Rootless Podman (Recommended)

Podman supports rootless containers and doesn't require a daemon:

```python
# executor/sandbox.py modifications
import podman

client = podman.PodmanClient()
container = client.containers.run(
    image="executor-sandbox:latest",
    detach=True,
    # No privileged mode needed
)
```

**Benefits:**
- No daemon required
- Rootless by default
- Compatible with Docker CLI
- Better security isolation

**Setup:**
```bash
# Install Podman
sudo apt-get install podman

# Enable rootless mode
podman system migrate

# Test
podman run --rm hello-world
```

#### Option 2: Sysbox Runtime

Sysbox is a container runtime that enables secure DinD without privileged mode:

```yaml
# docker-compose.executor.yml
runtime: sysbox-runc  # Instead of privileged: true
```

**Benefits:**
- Stronger isolation than privileged containers
- Supports Docker, Kubernetes, and systemd
- No code changes required

**Setup:**
```bash
# Install Sysbox
wget https://downloads.nestybox.com/sysbox/releases/latest/sysbox-latest.deb
sudo dpkg -i sysbox-latest.deb

# Configure Docker to use Sysbox
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json > /dev/null <<EOF
{
  "runtimes": {
    "sysbox-runc": {
      "path": "/usr/bin/sysbox-runc"
    }
  }
}
EOF
sudo systemctl restart docker
```

#### Option 3: Kaniko for Image Building

If you only need image building (not full Docker):

```yaml
# Use Kaniko for building images without DinD
executor:
  image: gcr.io/kaniko-project/executor:latest
```

#### Option 4: Docker Socket Mounting (Not Recommended)

Mount host Docker socket (less secure than DinD):

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

**⚠️ Warning**: This provides full host Docker access from container.

### Migration Guide

To migrate from privileged DinD to Sysbox:

1. Install Sysbox runtime (see above)
2. Update `docker-compose.executor.yml`:

```yaml
services:
  executor:
    image: docker:25.0-dind
    runtime: sysbox-runc  # Add this line
    # Remove: privileged: true
    # ... rest of config
```

3. Test thoroughly before production deployment
4. Monitor for compatibility issues

---

## API Authentication

### Optional API Key Authentication

Enable API key authentication by setting the environment variable:

```bash
export EXECUTOR_API_KEY="your-secure-api-key-here"
python executor/api_server.py
```

### Using API Keys

Include the API key in request headers:

```bash
curl -X POST http://localhost:8080/execute \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secure-api-key-here" \
  -d '{
    "tenant_id": "tenant-123",
    "scope": "test",
    "code": "print(\"Hello World\")"
  }'
```

### Production Mode

Enable production mode for sanitized error messages:

```bash
export EXECUTOR_PRODUCTION=true
python executor/api_server.py
```

**Effects:**
- Error messages sanitized (no internal details leaked)
- Security headers added to responses
- Sensitive information filtered from logs

---

## Production Deployment

### Kubernetes Security

1. **Apply Network Policies**:
```bash
kubectl apply -f k8s/config/deployment/network-policies.yaml
```

2. **Apply Resource Quotas**:
```bash
kubectl apply -f k8s/config/deployment/resource-quotas.yaml
```

3. **Enable Pod Security Standards**:
```bash
kubectl label namespace executor-system \
  pod-security.kubernetes.io/enforce=restricted
```

### Docker Compose Security

1. **Use non-root user**:
```yaml
services:
  executor:
    user: "1000:1000"
```

2. **Drop capabilities**:
```yaml
services:
  executor:
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - SETGID
      - SETUID
```

3. **Read-only filesystem**:
```yaml
services:
  executor:
    read_only: true
    tmpfs:
      - /tmp
      - /var/tmp
```

---

## Security Best Practices

### 1. Keep Images Updated

Regularly update base images and dependencies:

```bash
# Rebuild sandbox image with latest updates
docker build --no-cache -t executor-sandbox:latest \
  -f executor/Dockerfile.sandbox executor/
```

### 2. Use Specific Image Tags

Avoid `latest` tag in production:

```yaml
# Bad
image: executor-sandbox:latest

# Good
image: executor-sandbox:v1.2.3
```

### 3. Enable Audit Logging

```python
# executor/api_server.py - already enabled
logger.info(f"Execution: tenant={tenant_id}, scope={scope}, size={len(code)}")
```

### 4. Enable Policy Enforcement (OPA)

Set policy controls with environment variables:

```bash
export OPA_URL="http://opa:8181"
export POLICY_MODE="enforce"     # shadow or enforce
export POLICY_TIMEOUT_MS="800"
export POLICY_FAIL_MODE="closed" # open or closed
```

- `shadow`: evaluate + log decisions only
- `enforce`: block `deny` and `requires_approval`
- `closed`: deny requests if OPA is unavailable
- `open`: allow requests if OPA is unavailable (temporary rollout mode)

### 5. Monitor Resource Usage

Set up alerts for:
- High CPU/memory usage
- Failed authentication attempts
- Unusual error rates
- Session limit exhaustion

### 6. Regular Security Audits

Run security scanning tools:

```bash
# Trivy scanner for images
trivy image executor-sandbox:latest

# Docker Bench for Security
docker run -it --net host --pid host --userns host \
  --cap-add audit_control \
  -e DOCKER_CONTENT_TRUST=$DOCKER_CONTENT_TRUST \
  -v /var/lib:/var/lib \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /usr/lib/systemd:/usr/lib/systemd \
  -v /etc:/etc --label docker_bench_security \
  docker/docker-bench-security
```

---

## Threat Model and Checklist v1

See `docs/security-threat-model-v1.md` for:

- scoped threat actors and trust boundaries
- concrete threat scenario matrix
- PR/deployment/operations security checklist
- open risks and follow-up actions

---

## Reporting Security Issues

If you discover a security vulnerability:

1. **DO NOT** create a public GitHub issue
2. Email security concerns to: security@your-organization.com
3. Include detailed description and reproduction steps
4. Allow reasonable time for response before public disclosure

### Security Checklist

Before production deployment:

- [ ] API key authentication enabled
- [ ] Production mode enabled
- [ ] Network policies applied (K8s)
- [ ] Resource quotas set (K8s)
- [ ] Security contexts configured
- [ ] DinD alternative evaluated
- [ ] Container images scanned
- [ ] Log aggregation configured
- [ ] Monitoring/alerting set up
- [ ] Backup/disaster recovery tested

---

## Compliance

### CIS Docker Benchmark

Key items addressed:
- 4.1 - Container runs as non-root user ✅
- 4.6 - Container health check ✅
- 5.1 - Linux kernel capabilities ✅
- 5.2 - No new privileges ✅
- 5.3 - Container filesystem read-only ✅
- 5.4 - Container with SELinux/AppArmor ✅ (via Docker security options)
- 5.25 - Resource limits ✅
- 5.28 - PIDs cgroup limit ✅ (via container configuration)

### GDPR Considerations

- Session data automatically expires (TTL)
- No persistent storage of user code
- Audit logs for compliance tracking

---

**Last Updated:** 2026-02-20  
**Security Audit Version:** 2.0
