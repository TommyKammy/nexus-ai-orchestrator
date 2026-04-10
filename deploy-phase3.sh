#!/bin/bash
# Production Optimization Deployment Script
# Phase 3 - PCA, Monitoring, Maintenance

set -e

echo "========================================"
echo "AI Orchestrator - Phase 3 Deployment"
echo "Date: $(date)"
echo "========================================"
echo ""

# Configuration
RUNTIME_DIR="/opt/ai-orchestrator"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SOURCE_DIR:-$SCRIPT_DIR}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Step 1: Checking prerequisites...${NC}"

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    echo -e "${YELLOW}Note: Some operations may require sudo${NC}"
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker not found${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker available${NC}"

# Check containers
echo ""
echo -e "${YELLOW}Step 2: Checking container status...${NC}"
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "ai-" || true

echo ""
echo -e "${YELLOW}Step 3: Generating PCA model...${NC}"
echo "This step requires Python with numpy and scikit-learn"
echo ""

if [ -d "$RUNTIME_DIR/tools" ]; then
    cd "$RUNTIME_DIR/tools"
    
    # Check if pip is available
    if command -v pip3 &> /dev/null; then
        echo "Installing dependencies..."
        pip3 install -r requirements.txt --quiet || {
            echo -e "${YELLOW}Warning: Could not install dependencies${NC}"
            echo "You may need to install manually:"
            echo "  pip3 install numpy scikit-learn psycopg2-binary"
        }
        
        echo "Generating PCA model from database..."
        python3 pca_reduce.py fit \
            --source db \
            --samples 5000 \
            --output pca_model.pkl \
            --components 1536 || {
            echo -e "${YELLOW}Warning: Could not generate PCA model${NC}"
            echo "Using truncation method as fallback"
        }
        
        if [ -f "pca_model.pkl" ]; then
            echo -e "${GREEN}✓ PCA model generated: $(ls -lh pca_model.pkl | awk '{print $5}')${NC}"
            
            # Export to JSON for JavaScript usage
            python3 export_pca_to_json.py \
                --input pca_model.pkl \
                --output pca_model.json || true
        else
            echo -e "${YELLOW}⚠ PCA model not generated - will use truncation${NC}"
        fi
    else
        echo -e "${YELLOW}⚠ pip3 not available - skipping PCA generation${NC}"
        echo "Install Python dependencies manually to enable PCA"
    fi
else
    echo -e "${RED}Error: Runtime directory not found at $RUNTIME_DIR${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 4: Updating docker-compose.yml...${NC}"

# Backup current compose file
cp "$RUNTIME_DIR/docker-compose.yml" "$RUNTIME_DIR/docker-compose.yml.bak.$(date +%Y%m%d_%H%M%S)"

# Copy updated compose file
cp "$SOURCE_DIR/docker-compose.yml" "$RUNTIME_DIR/docker-compose.yml"

echo -e "${GREEN}✓ Docker compose updated${NC}"

echo ""
echo -e "${YELLOW}Step 5: Restarting services...${NC}"

cd "$RUNTIME_DIR"

# Restart n8n to pick up PCA model mount
docker compose restart n8n || {
    echo -e "${RED}Error: Failed to restart n8n${NC}"
    exit 1
}

echo -e "${GREEN}✓ n8n restarted${NC}"

echo ""
echo -e "${YELLOW}Step 6: Setting up monitoring cron jobs...${NC}"

# Create cron entries
CRON_HOURLY="0 * * * * docker exec ai-postgres psql -U ai_user -d ai_memory -f /workspace/monitor_pgvector.sql >> /var/log/pgvector_monitor.log 2>&1"
CRON_WEEKLY="0 3 * * 0 docker exec ai-postgres psql -U ai_user -d ai_memory -c \"VACUUM ANALYZE memory_vectors;\" >> /var/log/pgvector_maintenance.log 2>&1"

# Add to crontab if not already present
(crontab -l 2>/dev/null | grep -v "pgvector_monitor\|pgvector_maintenance"; \
 echo "$CRON_HOURLY"; \
 echo "$CRON_WEEKLY") | crontab -

echo -e "${GREEN}✓ Cron jobs configured:${NC}"
echo "  - Hourly monitoring: pgvector health checks"
echo "  - Weekly maintenance: VACUUM ANALYZE"

echo ""
echo -e "${YELLOW}Step 7: Verifying deployment...${NC}"

# Check n8n is running
if docker ps | grep -q "ai-n8n"; then
    echo -e "${GREEN}✓ n8n container running${NC}"
else
    echo -e "${RED}✗ n8n container not running${NC}"
fi

# Check Postgres
if docker exec ai-postgres pg_isready -U ai_user &>/dev/null; then
    echo -e "${GREEN}✓ PostgreSQL ready${NC}"
else
    echo -e "${RED}✗ PostgreSQL not ready${NC}"
fi

# Check if PCA model is mounted
if docker exec ai-n8n ls /workspace/pca_model.pkl &>/dev/null; then
    echo -e "${GREEN}✓ PCA model mounted in n8n${NC}"
else
    echo -e "${YELLOW}⚠ PCA model not mounted (optional)${NC}"
fi

echo ""
echo -e "${YELLOW}Step 8: Copying updated workflows...${NC}"

# Copy workflows
mkdir -p "$RUNTIME_DIR/n8n/workflows-v3"
cp "$SOURCE_DIR/n8n/workflows/01_memory_ingest.json" "$RUNTIME_DIR/n8n/workflows-v3/"
cp "$SOURCE_DIR/n8n/workflows/02_vector_search.json" "$RUNTIME_DIR/n8n/workflows-v3/"

echo -e "${GREEN}✓ Workflows copied${NC}"

echo ""
echo "========================================"
echo -e "${GREEN}Phase 3 Deployment Complete!${NC}"
echo "========================================"
echo ""
echo "Next Steps:"
echo "  1. Import updated workflows into n8n UI"
echo "  2. Test PCA reduction (if model generated)"
echo "  3. Check monitoring logs: tail -f /var/log/pgvector_monitor.log"
echo "  4. Verify cron jobs: crontab -l"
echo ""
echo "Manual Actions Required:"
echo "  - Import workflows via n8n UI at https://n8n-s-app01.tmcast.net"
echo "  - Activate new workflows and deactivate old ones"
echo "  - Test end-to-end with sample requests"
echo ""
echo "Monitoring:"
echo "  - Hourly health checks: /var/log/pgvector_monitor.log"
echo "  - Weekly maintenance: /var/log/pgvector_maintenance.log"
echo ""
