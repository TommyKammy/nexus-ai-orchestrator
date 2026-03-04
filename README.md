# AI Orchestrator Infrastructure

Secure AI orchestration system with isolated code execution sandbox, Kubernetes auto-scaling, workflow automation, and semantic memory.

## Overview

This system provides a complete infrastructure for AI-powered applications with:
- **Isolated Code Execution**: Docker-based sandbox for secure code execution (95% E2B parity)
- **Kubernetes Auto-scaling**: HPA, global load balancing, and session persistence
- **Workflow Automation**: n8n with custom workflows for memory, audit, and execution
- **Semantic Memory**: PostgreSQL + pgvector for persistent AI memory
- **Multi-language Support**: Python, Node.js, R, Go, Rust, Java, C++, and more

## Architecture

```
                    Internet / Clients
                            ↓
                    Caddy (HTTPS, Auth)
                            ↓
                  n8n (Webhooks/Orchestration)
                  ├──────────────┬──────────────┬──────────────┐
                  ↓              ↓              ↓              ↓
         PostgreSQL+pgvector   Redis          OPA PDP    Executor API (internal)
      (memory + audit_events) (cache)   (policy decision)         ↓
                                                           Executor Load Balancer
                                                                    ↓
                                                              Executor Pools
                                                         (K8s/Standalone Sandboxes)
                                                                    ↓
                                                               Redis (state)

  Note: External traffic is terminated at Caddy and routed to n8n.
  Executor endpoints are internal-only and invoked by workflows/services.
```

Architecture decision records (ADRs) are tracked under `docs/adr/`.
See the ADR index at `docs/adr/README.md` for the full list.

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| **n8n** | Workflow automation | Node.js, Docker |
| **PostgreSQL** | Persistent memory with pgvector | PostgreSQL 18 |
| **Redis** | Short-term cache & session state | Redis 8.6 |
| **OPA** | Central policy decision point | Open Policy Agent |
| **Executor** | Isolated code execution | Docker/Kubernetes |
| **Caddy** | Reverse proxy with HTTPS | Caddy 2 |

## Executor Sandbox System

### Features

- **12 Language Templates**: Python (data science, ML, NLP), Node.js, R, Go, Rust, Java, C++
- **Visualization Support**: Matplotlib and Plotly chart extraction
- **Session Management**: TTL-based sessions with pooling
- **Security**: Read-only filesystem, no-new-privileges, capability dropping, network isolation
- **Auto-scaling**: Kubernetes HPA with custom metrics
- **Global Load Balancing**: Circuit breaker, health checks, session affinity

### Security Features

- **Container Isolation**: Docker with security hardening
- **Path Traversal Protection**: Comprehensive validation
- **Resource Limits**: CPU, memory, disk quotas enforced
- **Network Isolation**: Disabled by default, opt-in only
- **API Authentication**: Optional API key validation
- **Audit Logging**: Complete execution history

## Quick Start

### Docker Compose (Single Node)

\`\`\`bash
# Clone repository
git clone <repository-url>
cd ai-orchestrator

# Configure environment
cp .env.example .env
# Edit .env with your secrets

# Option A: local bootstrap in current repository
bash scripts/bootstrap-local.sh
\`\`\`

Or, for server deployment to `/opt/ai-orchestrator`:

\`\`\`bash
# Option B: deployment flow (includes Caddy + policy-ui validation)
./deploy.sh
\`\`\`

`./deploy.sh` validates:
- Caddy config syntax in container
- `policy-ui` direct endpoint on `policy-bundle-server`
- `policy-ui` route through Caddy

Tip:
- Do not run local bootstrap and deploy flow simultaneously on the same host; both use identical container names and host ports.
- Set `N8N_HOST` in `.env` before deploy to validate external route (`https://<N8N_HOST>/policy-ui/`).
- See local bootstrap guide: `docs/local-compose-bootstrap.md`

### n8n Japanese Locale Overlay (CE)

Use the optional compose overlay to build/apply a Japanese locale pack for n8n UI:

\`\`\`bash
docker compose -f docker-compose.yml -f docker-compose.n8n-ja.yml up -d --build n8n
\`\`\`

Notes:
- The locale pack is in `n8n/locales/ja.partial.json` (partial translation + English fallback)
- `N8N_DEFAULT_LOCALE=ja` is applied via the overlay
- You can keep running standard CE without this overlay if desired

### Policy Registry Publish (CE)

Week2 adds no-restart policy publish flow for OPA:

- n8n workflow `07_policy_registry_publish` writes published rules to DB and calls `POST /registry/publish` on `policy-bundle-server`
- `policy-bundle-server` persists runtime registry to `policy/runtime/policy_registry.json`
- OPA keeps polling bundle (`min_delay_seconds: 10`) and picks up updates without OPA restart
- Lightweight UI is available at `/policy-ui/` (served by `policy-bundle-server`)

Related docs:
- `docs/policy-registry-operations.md`
- `docs/policy-registry-rollback.md`
- `docs/policy-registry-e2e-checklist.md`
- `docs/policy-registry-e2e-evidence-20260222.md`
- `docs/policy-registry-troubleshooting.md`
- `docs/postgres-data-layout-migration.md`
- `docs/host-quick-flow.md`

### Kubernetes (Production)

\`\`\`bash
# Apply CRDs
kubectl apply -f k8s/config/crd/executor-crd.yaml

# Deploy operator and infrastructure
kubectl apply -f k8s/config/deployment/operator-deployment.yaml
kubectl apply -f k8s/config/deployment/opa-deployment.yaml
kubectl apply -f k8s/config/deployment/network-policies.yaml
kubectl apply -f k8s/config/deployment/resource-quotas.yaml

# Create executor pool
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
  sessionTTL: 300
EOF
\`\`\`

## API Usage

### Direct Execution

\`\`\`bash
curl -X POST http://localhost:8080/execute \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: \$EXECUTOR_API_KEY" \\
  -d '{
    "tenant_id": "t1",
    "scope": "analysis",
    "code": "import pandas as pd; print(pd.__version__)",
    "template": "python-data"
  }'
\`\`\`

### Session-based Execution

\`\`\`bash
# Create session
curl -X POST http://localhost:8080/session/create \\
  -H "Content-Type: application/json" \\
  -d '{
    "tenant_id": "t1",
    "scope": "project-1",
    "template": "python-data",
    "ttl": 600
  }'

# Execute in session
curl -X POST http://localhost:8080/session/execute \\
  -H "Content-Type: application/json" \\
  -d '{
    "session_id": "<session-id>",
    "code": "import matplotlib.pyplot as plt; plt.plot([1,2,3]); plt.show()"
  }'

# Destroy session
curl -X POST http://localhost:8080/session/destroy \\
  -H "Content-Type: application/json" \\
  -d '{"session_id": "<session-id>"}'
\`\`\`

### Metrics (Policy/Executor)

```bash
# JSON metrics
curl http://localhost:8080/metrics

# Prometheus format
curl http://localhost:8080/metrics/prometheus
```

## Available Templates

| Template | Description | Packages | Network |
|----------|-------------|----------|---------|
| \`default\` | Basic Python | - | No |
| \`python-data\` | Data Science | pandas, numpy, matplotlib, seaborn, scipy, scikit-learn | No |
| \`python-ml\` | Machine Learning | torch, transformers, datasets, accelerate | No |
| \`python-nlp\` | NLP | nltk, spacy, textblob, gensim | No |
| \`python-web\` | Web Scraping | requests, beautifulsoup4, selenium, scrapy | Yes |
| \`node-basic\` | Node.js | npm available | No |
| \`r-stats\` | R Statistics | ggplot2, dplyr, tidyr, readr | No |
| \`go-basic\` | Go | Go toolchain | No |
| \`rust-basic\` | Rust | Cargo toolchain | No |
| \`java-basic\` | Java | JDK 21 | No |
| \`cpp-basic\` | C++ | GCC 13, cmake | No |
| \`minimal\` | Minimal Python | None | No |

## Security

### Security Audit Results

**Overall Rating: GOOD** ✅

- **0 Critical** vulnerabilities found
- **0 High** severity issues
- Comprehensive security documentation in [SECURITY.md](SECURITY.md)
- Threat model and checklist in [docs/security-threat-model-v1.md](docs/security-threat-model-v1.md)
- Full audit report in [docs/reports/security-audit-report.md](docs/reports/security-audit-report.md)

### Key Security Features

1. **Container Isolation**
   - Read-only root filesystem
   - No-new-privileges flag
   - All capabilities dropped
   - Non-root user execution

2. **Input Validation**
   - Path traversal prevention
   - File size limits (10MB/file, 100MB total)
   - Timeout enforcement
   - Code execution limits

3. **Kubernetes Security**
   - Network policies (default-deny)
   - Security contexts (non-root, read-only)
   - Resource quotas and limits
   - RBAC with least privilege

4. **API Security**
   - Optional API key authentication
   - Security headers (CSP, HSTS, X-Frame-Options)
   - Error message sanitization in production
   - CORS support

See [SECURITY.md](SECURITY.md) for detailed security documentation.

## Repository Structure

\`\`\`
.
├── docker-compose.yml           # Docker Compose configuration
├── docker-compose.executor.yml  # Executor-specific compose
├── k8s/                        # Kubernetes manifests
│   ├── config/
│   │   ├── crd/               # Custom Resource Definitions
│   │   └── deployment/        # Deployment manifests
│   ├── controllers/           # Operator controllers
│   └── README.md              # K8s deployment guide
├── executor/                   # Executor sandbox system
│   ├── sandbox.py             # Core sandbox implementation
│   ├── api_server.py          # HTTP API server
│   ├── session.py             # Session management
│   ├── filesystem.py          # Secure file operations
│   ├── interpreter.py         # Code interpreter with visualization
│   ├── templates.py           # Environment templates
│   └── README.md              # Executor documentation
├── n8n/
│   └── workflows/             # n8n workflow definitions
├── docs/
│   ├── adr/                   # architecture decision records
│   ├── reports/               # implementation and verification reports
│   └── ...                    # operations and troubleshooting docs
├── scripts/                   # Utility scripts
├── SECURITY.md                # Security documentation
└── README.md                  # This file
\`\`\`

## Environment Configuration

Required environment variables:

\`\`\`bash
# Database
POSTGRES_PASSWORD=your_secure_password
POSTGRES_IMAGE=pgvector/pgvector:pg18
POSTGRES_PGDATA=/var/lib/postgresql/data
REDIS_IMAGE=redis:8.6-alpine

# n8n
N8N_ENCRYPTION_KEY=your_64_char_hex_key
N8N_BASIC_AUTH_PASSWORD=your_admin_password
N8N_WEBHOOK_API_KEY=your_64_char_hex_key

# Executor (optional)
EXECUTOR_API_KEY=your_api_key_for_production
EXECUTOR_PRODUCTION=true  # Enable production security features
OPA_URL=http://opa:8181
POLICY_MODE=shadow        # shadow or enforce
POLICY_TIMEOUT_MS=800
POLICY_FAIL_MODE=open     # open or closed

# LLM Providers (optional)
KIMI_API_KEY=your_kimi_key
OPENAI_API_KEY=your_openai_key
\`\`\`

`N8N_WEBHOOK_API_KEY` is enforced by Caddy for webhook routes by default:
- missing/invalid key returns `401 Unauthorized`
- `/webhook/slack-command` is explicitly exempt and protected separately via `X-Internal-Auth`

## PostgreSQL 18 Upgrade

This repository now defaults to `pgvector/pgvector:pg18`.

If you already have PostgreSQL 16 data under `./postgres`, run the upgrade script:

```bash
export POSTGRES_PASSWORD=your_secure_password
./scripts/upgrade-postgres-16-to-18.sh --yes
```

What the script does:
- stops write-path services
- creates a logical backup under `backups/postgres-upgrade/<timestamp>/`
- preserves old PG16 data directory
- starts PostgreSQL 18 and restores data
- restarts the full stack and validates extension presence

Rollback is documented in the script output and uses the preserved PG16 data directory.

## Redis 8.6 Upgrade

This repository now defaults to `redis:8.6-alpine`.

If you are upgrading from Redis 7 with existing data, run:

```bash
./scripts/upgrade-redis-7-to-8.sh --yes
```

The script performs a consistent backup (`SAVE` + `docker cp /data`) before switching and verifies that Redis 8 is running.

## Development

### Testing Executor

\`\`\`bash
# Test sandbox creation
echo '{"type":"ping","message":"test"}' | docker exec -i ai-executor python /workspace/executor_api.py

# Test via API
curl http://localhost:8080/health
\`\`\`

### Kubernetes Development

\`\`\`bash
# Build operator image
docker build -t executor-operator:latest -f k8s/config/deployment/Dockerfile.operator .

# Build load balancer image
docker build -t executor-load-balancer:latest -f k8s/config/deployment/Dockerfile.loadbalancer .

# Port forward for testing
kubectl port-forward -n executor-system svc/executor-load-balancer 8080:80
\`\`\`

### Database Access

\`\`\`bash
docker exec -it ai-postgres psql -U ai_user -d ai_memory
\`\`\`

### View Logs

\`\`\`bash
# Docker Compose
docker compose logs -f [service-name]

# Kubernetes
kubectl logs -n executor-system -l app.kubernetes.io/component=operator -f
\`\`\`

## CI/CD

GitHub Actions workflows:

- **Workflow Validation**: Validates n8n workflow JSON files
- **Import Testing**: Tests n8n workflow imports
- **Security Scanning**: Automated security checks

Run locally:

\`\`\`bash
# Validate workflows
python3 scripts/validate_workflow_schema.py n8n/workflows n8n/workflows-v3
python3 scripts/validate_slack_workflows.py

# Test imports
bash scripts/ci/n8n_import_test.sh

# One-command compose core journey (ingest -> search -> execute)
pnpm e2e:compose-core

# The command imports run-scoped CI-safe copies of core workflows
# and validates successful executions plus DB side effects.
\`\`\`

## Known Issues

### Slack Signature Verification

n8n 2.7.4 blocks the \`crypto\` module in Code nodes. Temporary workaround:

\`\`\`yaml
environment:
  SLACK_SIG_VERIFY_ENABLED: "false"  # Only for debugging
\`\`\`

See [Security Notice](#security-notice) for details.

## Roadmap

- [x] Phase 1: Core sandbox infrastructure
- [x] Phase 2: Enhanced management (sessions, filesystem, templates)
- [x] Phase 3: Visualization and production deployment
- [x] Phase 4: Kubernetes auto-scaling, load balancing, session persistence
- [ ] Phase 5: GPU support for ML workloads
- [ ] Phase 6: Multi-region federation

## Contributing

Contribution workflow and merge requirements are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

1. Review [SECURITY.md](SECURITY.md) before contributing
2. Ensure no secrets are committed (use \`.env.example\` as template)
3. Run a quick secret scan before PR:
   \`grep -r "CHANGE_ME\\|password\\|secret" . --include="*.yml" --include="*.yaml" --include="*.py" --include="*.ts" --include="*.js"\`
4. Test deployment locally before submitting PR
5. Follow conventional commits style

## License

MIT License

## Support

- Documentation: See \`README.md\` files in each component directory
- Security: See [SECURITY.md](SECURITY.md)
- Issues: Create GitHub issue with detailed description
