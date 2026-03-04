#!/usr/bin/env bash
set -euo pipefail

docker compose --env-file .env.example -f docker-compose.yml config -q
docker compose --env-file .env.example -f docker-compose.executor.yml config -q
docker compose --env-file .env.example -f docker-compose.yml -f docker-compose.n8n-ja.yml config -q
