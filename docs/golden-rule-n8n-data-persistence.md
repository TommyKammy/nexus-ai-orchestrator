# n8n Data Persistence - Golden Rule

## The Golden Rule

PostgreSQL is the SOURCE OF TRUTH for n8n workflows, credentials, and execution history.

The /n8n directory contains ONLY:
- Configuration files (config)
- Event logs (n8nEventLog*.log)
- Exported workflow JSON files (manual exports)
- Custom nodes

NEVER assume workflows are in /n8n - they are in the database!

## Pre-Operation Checklist

Before ANY Update/Upgrade/Deployment:

1. Verify database has data:
   docker exec ai-postgres psql -U ai_user -d ai_memory -c "SELECT COUNT(*) FROM workflow_entity;"

2. Create backup:
   mkdir -p /opt/backups/$(date +%Y%m%d-%H%M%S)
   docker exec ai-postgres pg_dump -U ai_user -d ai_memory > /opt/backups/$(date +%Y%m%d-%H%M%S)/ai_memory.sql

3. Verify backup size (>100KB expected):
   ls -lh /opt/backups/$(date +%Y%m%d-%H%M%S)/ai_memory.sql

4. If backup <10KB, STOP and investigate!

## Emergency Recovery

Scenario: Accidentally Reset Database

Find latest backup:
LATEST_BACKUP=$(ls -t /opt/backups/*/ai_memory.sql 2>/dev/null | head -1)

Stop n8n:
cd /opt/ai-orchestrator
docker compose stop n8n

Restore database:
docker exec ai-postgres psql -U ai_user -d ai_memory -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker exec -i ai-postgres psql -U ai_user -d ai_memory < "$LATEST_BACKUP"

Restart n8n:
docker compose start n8n

## Common Mistakes to AVOID

- DON'T: Copy entire repo over existing installation
- DON'T: Use docker compose down -v (deletes volumes!)
- DON'T: Upgrade PostgreSQL without migration plan
- DON'T: Assume exported JSON files are backups

## Golden Rule Summary

Before touching ANYTHING related to n8n, verify the database has your workflows.
After touching ANYTHING, verify the database still has your workflows.
When in doubt, backup first.

PostgreSQL = Source of Truth
pg_dump = Your lifeline
Verification = Non-negotiable
