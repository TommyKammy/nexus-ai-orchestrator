# Local Docker Compose Bootstrap

This guide provides a deterministic local startup flow for the full stack.

## Prerequisites

- Docker Engine with Compose plugin
- Linux/macOS shell environment
- `curl` (required for bootstrap health probes)
- Open ports `80`, `443`, `5432`, `6379`, `8088`, `8181`

## Bootstrap Command

From repository root:

```bash
bash scripts/bootstrap-local.sh
```

What it does:

1. Creates `.env` from `.env.example` if missing
2. Ensures runtime directories exist
3. Runs `docker compose up -d --build`
4. Waits for core services to become `running`/`healthy`
5. Executes health probes for Postgres, Redis, OPA, policy bundle server, and Caddy config

## Stop the Stack

```bash
docker compose down
```

## Troubleshooting

- Check container status:
  - `docker compose ps`
- Check logs:
  - `docker compose logs -f`
- Re-run bootstrap with extended timeout:
  - `TIMEOUT_SECONDS=420 bash scripts/bootstrap-local.sh`
