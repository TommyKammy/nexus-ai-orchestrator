# Host Quick Flow (Shortest Commands)

This is the shortest host-side operation flow for the current deployment model.

## 0) Move to host repository

```bash
cd /opt/ai-orchestrator
```

## 1) Update + deploy + validation (one command)

```bash
./deploy-updates.sh
```

What this includes:
- Git fetch/rebase to latest `origin/main`
- Service rebuild/recreate via `./deploy.sh`
- Caddy config validation
- `policy-ui` direct/proxy route validation

## 2) Verify service status

```bash
docker compose ps
```

## 3) Open UI

```text
https://<N8N_HOST>/policy-ui/
```

## 4) If PostgreSQL layout mismatch occurs

```bash
./scripts/migrate-postgres-data-layout.sh
./deploy-updates.sh
```

## 5) Logs (only when needed)

```bash
docker compose logs -f caddy policy-bundle-server n8n opa
```

---

## Optional: Force clean gateway refresh only

```bash
docker compose up -d --build --force-recreate caddy policy-bundle-server
```
