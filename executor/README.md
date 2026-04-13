# Executor Sandbox - Complete Documentation

## Overview

The AI Orchestrator Executor provides **E2B-style** secure sandbox execution for AI-generated code. It supports dynamic container creation, session management, rich output visualization, and comprehensive security controls.

## Features

### Phase 1: Core Infrastructure ✅
- Dynamic Docker container sandboxing
- Resource limits (CPU, memory, timeout)
- Network isolation
- Read-only filesystem with tmpfs
- File upload/download

### Phase 2: Enhanced Management ✅
- Session lifecycle management with TTL
- Pre-configured environment templates
- Secure filesystem operations
- Package caching
- HTTP API for integration

### Phase 3: Visualization & Production ✅
- Rich code interpreter output
- Matplotlib/Plotly chart support
- Artifact extraction and handling
- Production deployment scripts
- Advanced monitoring

## Quick Start

### 1. Start the Executor Service

```bash
# Required: executor API auth
export EXECUTOR_API_KEY="change-me"

# Optional: explicit browser origins and request-body cap
export EXECUTOR_ALLOWED_ORIGINS="https://console.example.com"
export EXECUTOR_MAX_REQUEST_BODY_BYTES=1048576

# Start with Sysbox-backed executor
docker compose -f docker-compose.yml -f docker-compose.executor.yml up -d executor

# Wait for service to be ready
curl http://localhost:8080/health
```

### 2. Execute Code

```bash
# Direct execution
curl -X POST http://localhost:8080/execute \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -H "X-Authenticated-Tenant-Id: t1" \
  -d '{
    "scope": "user:123",
    "code": "print('Hello, Sandbox!')",
    "template": "default"
  }'
```

Notes:
- `EXECUTOR_API_KEY` is required at startup. The API refuses to boot without it.
- Browser access requires explicit `EXECUTOR_ALLOWED_ORIGINS`; the server no longer sends wildcard CORS headers.
- Executor POST endpoints only accept JSON-object request bodies and reject oversized bodies with `413`.

### 3. Python SDK Example

```python
from executor.sandbox import CodeSandbox
from executor.session import SessionManager
from executor.interpreter import CodeInterpreter

# Direct execution
with CodeSandbox(template="python-data") as sandbox:
    interpreter = CodeInterpreter(sandbox)
    result = interpreter.run("""
import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 10, 100)
plt.plot(x, np.sin(x))
plt.show()
    """)
    
    print(result.stdout)
    for artifact in result.artifacts:
        print(f"Artifact: {artifact.name} ({artifact.type})")

# Session-based execution
with SessionManager() as manager:
    session_id = manager.create_session(template="python-ml")
    result = manager.execute_in_session(
        session_id,
        "import torch; print(torch.__version__)"
    )
```

## API Reference

### Endpoints

#### GET /health
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "service": "executor-api",
  "version": "2.0.0"
}
```

#### GET /templates
List available environment templates.

**Response:**
```json
{
  "status": "success",
  "templates": [
    {
      "name": "python-data",
      "description": "Python data science environment",
      "memory_limit": "1g",
      "package_count": 7
    }
  ]
}
```

#### POST /execute
Execute code in a new sandbox.

**Request:**
```json
{
  "scope": "user:123",
  "code": "print('Hello')",
  "language": "python",
  "template": "python-data",
  "files": {"data.csv": "name,value\nAlice,100"}
}
```

**Response:**
```json
{
  "status": "success",
  "exit_code": 0,
  "stdout": "Hello",
  "stderr": "",
  "execution_time": 1.23,
  "artifacts": [
    {
      "type": "image/png",
      "name": "plot_0",
      "content": "base64encoded..."
    }
  ]
}
```

**Request requirements:**
- Include `X-API-Key` on executor requests.
- Include `X-Authenticated-Tenant-Id` on protected executor requests. The executor derives tenant context from this authenticated ingress header.
- Send `Content-Type: application/json`.
- Request body must be a JSON object.
- Body size is capped by `EXECUTOR_MAX_REQUEST_BODY_BYTES` and returns `413` when exceeded.
- These same POST requirements apply to `/execute`, `/session/create`, `/session/execute`, and `/session/destroy`.
- If a request body still includes `tenant_id`, it must exactly match `X-Authenticated-Tenant-Id` or the request is rejected with `403`.

#### POST /session/create
Create a persistent session.

**curl example:**
```bash
curl -X POST http://localhost:8080/session/create \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -H "X-Authenticated-Tenant-Id: t1" \
  -d '{
    "scope": "user:123",
    "template": "python-ml",
    "ttl": 300
  }'
```

**Request:**
```json
{
  "scope": "user:123",
  "template": "python-ml",
  "ttl": 300
}
```

**Response:**
```json
{
  "status": "success",
  "session_id": "abc123def456",
  "template": "python-ml",
  "ttl": 300
}
```

#### POST /session/execute
Execute code in an existing session.

**curl example:**
```bash
curl -X POST http://localhost:8080/session/execute \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -H "X-Authenticated-Tenant-Id: t1" \
  -d '{
    "session_id": "abc123def456",
    "code": "print('\''In session'\'')",
    "language": "python"
  }'
```

**Request:**
```json
{
  "session_id": "abc123def456",
  "code": "print('In session')",
  "language": "python"
}
```

#### POST /session/destroy
Destroy a session.

**curl example:**
```bash
curl -X POST http://localhost:8080/session/destroy \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -H "X-Authenticated-Tenant-Id: t1" \
  -d '{
    "session_id": "abc123def456"
  }'
```

**Request:**
```json
{
  "session_id": "abc123def456"
}
```

#### GET /metrics
Get session manager metrics.

**Response:**
```json
{
  "status": "success",
  "metrics": {
    "sessions_created": 10,
    "sessions_reused": 25,
    "active_sessions": 3,
    "max_sessions": 10
  }
}
```

## Templates

### Built-in Templates

| Template | Description | Packages | Memory |
|----------|-------------|----------|--------|
| `default` | Basic Python | Core only | 512m |
| `python-data` | Data Science | pandas, numpy, matplotlib, seaborn | 1g |
| `python-ml` | Machine Learning | torch, transformers, sklearn | 2g |
| `python-nlp` | NLP | nltk, spacy, textblob | 1g |
| `python-web` | Web Scraping | requests, selenium, scrapy | 512m |
| `node-basic` | Node.js | Node 18 base | 512m |
| `minimal` | Minimal Resources | No extras | 256m |

### Custom Templates

```python
from executor.templates import SandboxTemplate, template_manager

# Create custom template
template = SandboxTemplate(
    name="custom-ml",
    description="Custom ML environment",
    base_image="executor-sandbox:latest",
    packages=["tensorflow", "keras", "pillow"],
    memory_limit="4g",
    cpu_quota=400000,
    timeout=300
)

# Register
template_manager.register_template(template, persist=True)
```

## Security

### Container Isolation
- Each execution runs in a fresh Docker container
- Containers are destroyed after execution
- No access to host filesystem
- Network disabled by default

### Resource Limits
- Memory: Configurable (default 512m)
- CPU: Configurable (default 1 core)
- Timeout: Configurable (default 30s)
- File size: 10MB per file, 100MB total

### Path Security
- Path traversal prevention (`../` blocked)
- Absolute paths blocked
- Dangerous extensions blocked (`.exe`, `.sh`, etc.)
- Filename character validation

### Read-Only Filesystem
- Root filesystem is read-only
- Writable areas via tmpfs:
  - `/tmp` (100MB)
  - `/workspace` (50MB)

## Production Deployment

### Prerequisites
- Docker 20.10+
- Docker Compose 2.0+
- Linux host with the `sysbox-runc` Docker runtime installed
- Minimum 4GB RAM, 2 CPU cores

Install and configure Sysbox on the host before deploying the executor stack. The executor compose path now expects Docker to expose the `sysbox-runc` runtime and no longer relies on `privileged: true`.

### Deployment Script

```bash
# Deploy to production
./scripts/deploy-executor-production.sh

# Options
./scripts/deploy-executor-production.sh --skip-backup
./scripts/deploy-executor-production.sh --skip-health-check
```

### Monitoring

The deployment script sets up:
- Health check cron job (every 5 minutes)
- Log rotation (daily, 7 days retention)
- Metrics collection
- Automatic restart on failure

### Performance Tuning

```bash
# Tune Docker daemon
sudo tee /etc/docker/daemon.json > /dev/null <<EOF
{
  "storage-driver": "overlay2",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF

sudo systemctl restart docker
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
docker logs ai-executor-runtime

# Verify executor container
docker ps | grep executor

# Check port availability
sudo netstat -tlnp | grep 8080
```

### Execution Timeout

```bash
# Increase timeout
curl -X POST http://localhost:8080/execute \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -H "X-Authenticated-Tenant-Id: t1" \
  -d '{
    "scope": "test",
    "code": "...",
    "timeout": 120
  }'

# Requests over EXECUTOR_MAX_REQUEST_BODY_BYTES return 413 before execution starts.
```

### Out of Memory

```bash
# Use larger template
curl -X POST http://localhost:8080/execute \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -H "X-Authenticated-Tenant-Id: t1" \
  -d '{
    "scope": "test",
    "code": "...",
    "template": "python-ml"
  }'

# Or create custom session with more memory
```

## Examples

See `executor/examples/` directory for:
- `visualization_examples.py` - Matplotlib and data analysis examples
- `session_examples.py` - Session management examples
- `file_operations.py` - File upload/download examples

## Architecture

```
n8n Workflow
    │
    ▼ HTTP API
Executor API Server
    │
    ├── Session Manager (TTL, pooling)
    ├── Template Manager (environments)
    └── Filesystem Manager (secure I/O)
    │
    ▼ Docker
CodeSandbox (per execution)
    │
    ▼ Isolated Container
User Code Execution
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes
4. Add tests
5. Submit PR

## License

MIT License - See LICENSE file

## Support

For issues and questions:
- GitHub Issues: https://github.com/TommyKammy/ai-orchestrator/issues
- Documentation: See docs/ directory
