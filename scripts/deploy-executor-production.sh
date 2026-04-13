#!/bin/bash
# deploy-executor-production.sh - Production deployment script
# Phase 3: Production Deployment

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi
    
    # Check Docker Compose
    if ! docker compose version &> /dev/null; then
        log_error "Docker Compose is not installed"
        exit 1
    fi

    # Check Sysbox runtime
    if ! docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q 'sysbox-runc'; then
        log_error "Docker runtime 'sysbox-runc' is not available on this host"
        log_error "Install Sysbox and configure Docker before deploying the executor"
        exit 1
    fi
    
    # Check if running as root or with sudo
    if [ "$EUID" -ne 0 ] && ! sudo -n true 2>/dev/null; then
        log_warn "Script may need sudo privileges for some operations"
    fi
    
    log_info "Prerequisites check passed"
}

# Build sandbox image
build_sandbox_image() {
    log_info "Building sandbox image..."
    
    cd "$PROJECT_DIR"
    
    if [ -f "executor/Dockerfile.sandbox" ]; then
        docker build -t executor-sandbox:latest \
            -f executor/Dockerfile.sandbox \
            executor/
        log_info "Sandbox image built successfully"
    else
        log_error "Dockerfile.sandbox not found"
        exit 1
    fi
}

# Deploy executor service
deploy_executor() {
    log_info "Deploying executor service..."
    
    cd "$PROJECT_DIR"
    
    # Create necessary directories
    mkdir -p logs/executor
    mkdir -p executor-cache
    
    # Deploy with docker compose
    docker compose \
        -f docker-compose.yml \
        -f docker-compose.executor.yml \
        up -d executor
    
    log_info "Executor service deployed"
}

# Wait for service to be ready
wait_for_service() {
    log_info "Waiting for executor service to be ready..."
    
    local max_attempts=30
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s http://localhost:8080/health >/dev/null 2>&1; then
            log_info "Executor service is ready"
            return 0
        fi
        
        log_info "Attempt $attempt/$max_attempts: Service not ready yet..."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    log_error "Service failed to start within expected time"
    return 1
}

# Run health checks
health_check() {
    log_info "Running health checks..."
    
    # Check Docker container
    if ! docker ps | grep -q "ai-executor-runtime"; then
        log_error "Executor container is not running"
        exit 1
    fi
    
    # Check API endpoint
    local response
    response=$(curl -s http://localhost:8080/health || echo "{}" )
    
    if echo "$response" | grep -q '"status":"healthy"'; then
        log_info "Health check passed"
    else
        log_warn "Health check returned unexpected response: $response"
    fi
}

# Setup monitoring
setup_monitoring() {
    log_info "Setting up monitoring..."
    
    # Create monitoring script
    cat > "$PROJECT_DIR/scripts/monitor-executor.sh" << 'EOF'
#!/bin/bash
# Executor monitoring script

LOG_FILE="/var/log/executor-monitor.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Check container health
if ! docker ps | grep -q "ai-executor-runtime"; then
    log "ERROR: Executor container is down"
    # Attempt restart
    cd /opt/ai-orchestrator
    docker compose -f docker-compose.yml -f docker-compose.executor.yml up -d executor
    log "INFO: Attempted container restart"
else
    # Get metrics
    metrics=$(curl -s http://localhost:8080/metrics || echo "{}")
    active_sessions=$(echo "$metrics" | grep -o '"active_sessions":[0-9]*' | cut -d: -f2)
    log "INFO: Active sessions: ${active_sessions:-unknown}"
fi
EOF

    chmod +x "$PROJECT_DIR/scripts/monitor-executor.sh"
    
    # Add cron job for monitoring
    (crontab -l 2>/dev/null || echo "") | grep -v "monitor-executor" || true
    (crontab -l 2>/dev/null || echo ""; echo "*/5 * * * * $PROJECT_DIR/scripts/monitor-executor.sh") | crontab -
    
    log_info "Monitoring setup complete"
}

# Setup log rotation
setup_log_rotation() {
    log_info "Setting up log rotation..."
    
    sudo tee /etc/logrotate.d/executor-monitor > /dev/null << EOF
/var/log/executor-monitor.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 root root
}
EOF

    log_info "Log rotation configured"
}

# Performance tuning
performance_tuning() {
    log_info "Applying performance tuning..."
    
    # Tune Docker daemon for better performance
    sudo mkdir -p /etc/docker
    
    if [ ! -f /etc/docker/daemon.json ]; then
        sudo tee /etc/docker/daemon.json > /dev/null << 'EOF'
{
  "storage-driver": "overlay2",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "max-concurrent-downloads": 10,
  "max-concurrent-uploads": 10,
  "experimental": false
}
EOF
        log_warn "Docker daemon config updated - restart Docker to apply"
    fi
    
    log_info "Performance tuning applied"
}

# Cleanup old resources
cleanup() {
    log_info "Cleaning up old resources..."
    
    # Remove dangling images
    docker image prune -f >/dev/null 2>&1 || true
    
    # Remove old executor containers (not in use)
    docker container prune -f >/dev/null 2>&1 || true
    
    # Clean up package cache if over 1GB
    CACHE_SIZE=$(du -sb executor-cache 2>/dev/null | cut -f1 || echo 0)
    if [ "$CACHE_SIZE" -gt 1073741824 ]; then
        log_warn "Package cache is over 1GB, consider cleaning"
    fi
    
    log_info "Cleanup complete"
}

# Backup current state
backup_state() {
    log_info "Creating backup..."
    
    BACKUP_DIR="$PROJECT_DIR/backups/executor-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    # Backup configuration
    cp -r "$PROJECT_DIR/executor" "$BACKUP_DIR/"
    cp "$PROJECT_DIR/docker-compose.executor.yml" "$BACKUP_DIR/"
    
    # Export current metrics
    curl -s http://localhost:8080/metrics > "$BACKUP_DIR/metrics.json" 2>/dev/null || true
    
    log_info "Backup created at $BACKUP_DIR"
}

# Rollback function
rollback() {
    log_error "Deployment failed, rolling back..."
    
    cd "$PROJECT_DIR"
    
    # Stop executor
    docker compose \
        -f docker-compose.yml \
        -f docker-compose.executor.yml \
        stop executor
    
    # Restore from backup if available
    LATEST_BACKUP=$(ls -td backups/executor-* 2>/dev/null | head -1)
    if [ -n "$LATEST_BACKUP" ]; then
        log_info "Restoring from backup: $LATEST_BACKUP"
        cp -r "$LATEST_BACKUP/executor" "$PROJECT_DIR/"
    fi
    
    # Restart with old version
    docker compose \
        -f docker-compose.yml \
        -f docker-compose.executor.yml \
        up -d executor
    
    log_info "Rollback complete"
}

# Main deployment function
main() {
    log_info "Starting executor production deployment..."
    
    # Parse arguments
    SKIP_BACKUP=false
    SKIP_HEALTH_CHECK=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --skip-backup)
                SKIP_BACKUP=true
                shift
                ;;
            --skip-health-check)
                SKIP_HEALTH_CHECK=true
                shift
                ;;
            --help)
                echo "Usage: $0 [OPTIONS]"
                echo "Options:"
                echo "  --skip-backup         Skip backup creation"
                echo "  --skip-health-check   Skip health checks"
                echo "  --help                Show this help message"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    # Run deployment steps
    check_prerequisites
    
    if [ "$SKIP_BACKUP" = false ]; then
        backup_state
    fi
    
    build_sandbox_image
    deploy_executor
    
    if [ "$SKIP_HEALTH_CHECK" = false ]; then
        if ! wait_for_service; then
            rollback
            exit 1
        fi
        health_check
    fi
    
    setup_monitoring
    setup_log_rotation
    performance_tuning
    cleanup
    
    log_info "========================================"
    log_info "Deployment completed successfully!"
    log_info "========================================"
    log_info "Executor API: http://localhost:8080"
    log_info "Health Check: http://localhost:8080/health"
    log_info "Metrics:      http://localhost:8080/metrics"
    log_info "========================================"
}

# Run main function
trap 'log_error "Deployment interrupted"; exit 1' INT TERM
main "$@"
