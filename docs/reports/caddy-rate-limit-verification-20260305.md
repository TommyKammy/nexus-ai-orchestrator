# Caddy Rate-Limit Verification (2026-03-05)

## Scope
- Issue: #31 Security headers and rate limiting in Caddy
- Target behavior:
  - `/webhook/*` is rate-limited to `30 requests/minute` per source IP
  - exceed limit returns `429 Too Many Requests`
  - `/webhook/slack-command` is exempt from this rate limit

## Configuration Evidence
- [`Caddyfile`](../../Caddyfile)
  - `@webhook_rate_limited` matcher on `/webhook/*`
  - explicit exclusion: `not path /webhook/slack-command /webhook/slack-command/*`
  - `events 30`, `window 1m`, `key {remote_host}`
  - `respond @webhook_rate_limited 429`
- [`docker/caddy/Dockerfile`](../../docker/caddy/Dockerfile)
  - pinned Caddy version (`2.8.4`)
  - pinned module (`github.com/mholt/caddy-ratelimit@v0.1.0`)

## CI Verification
Executed in this PR:
- `pnpm -r --if-present lint`
- `pnpm -r --if-present typecheck`
- `pnpm -r --if-present test`
- `pnpm -r --if-present build`
- `pnpm e2e`

The lint stage includes `scripts/ci/caddy_security_headers_rate_limit_check.sh`, which validates:
- required security headers
- rate-limit matcher and threshold/window/key settings
- explicit Slack-command exclusion
- pinned Caddy and ratelimit module configuration

## Manual Reproduction Command
```bash
for i in $(seq 1 35); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -H "X-API-Key: ${N8N_WEBHOOK_API_KEY}" \
    https://n8n-s-app01.tmcast.net/webhook/<your-test-webhook-path>
done | sort | uniq -c
```

Expected:
- initial requests return normal webhook status
- once threshold is crossed in the 1-minute window, responses include `429`
