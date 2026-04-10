#!/bin/bash
# Safe Push Runbook for ai-orchestrator
# Usage: ./scripts/safe-push.sh [optional-commit-message]
#
# This script implements a safe push procedure that:
# 1. Prevents accidental .env commits
# 2. Runs secret scanning
# 3. Validates workflow exports
# 4. Creates a work log with evidence

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
WORKLOG_DIR="${WORKLOG_DIR:-${REPO_DIR}/worklog}"
WORKFLOW_DIR="n8n/workflows-v3"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[SAFE-PUSH]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Check if we're in the right directory
check_repo() {
    if [ ! -d "$REPO_DIR" ]; then
        error "Repository directory not found: $REPO_DIR"
    fi
    cd "$REPO_DIR"
    
    if [ ! -d ".git" ]; then
        error "Not a git repository"
    fi
    
    log "Working in: $(pwd)"
}

# Initialize work log
init_worklog() {
    TS=$(date -u +"%Y%m%d-%H%M%S")
    WORKLOG="$WORKLOG_DIR/WORKLOG-safe-push-$TS.md"
    
    mkdir -p "$WORKLOG_DIR"
    
    echo "# Work Log: Safe Push" > "$WORKLOG"
    echo "Timestamp (UTC): $(date -u)" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    echo "Repository: $(pwd)" >> "$WORKLOG"
    echo "Branch: $(git branch --show-current)" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    echo "WORKLOG=$WORKLOG"
}

# Step 1: Verify repo state
verify_repo_state() {
    log "Step 1: Verifying repository state..."
    
    echo "## Step 1: Repository State Verification" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    # Check git status
    echo "### Git status" >> "$WORKLOG"
    git status --short >> "$WORKLOG" 2>&1
    echo "" >> "$WORKLOG"
    
    # Verify .env is not tracked
    echo "### Checking .env tracking" >> "$WORKLOG"
    if git ls-files | grep -qE '(^|/).env$'; then
        error ".env file is tracked in git! Remove it immediately."
    else
        echo "OK: .env not tracked" >> "$WORKLOG"
        log ".env is not tracked ✓"
    fi
    
    # Check for secret-like files
    echo "" >> "$WORKLOG"
    echo "### Checking for secret-like files" >> "$WORKLOG"
    SECRET_FILES=$(git ls-files | grep -E '(^|/)(.env(..*)?|.*.pem|.*.key|id_rsa|service_account.*.json)$' || true)
    if [ -n "$SECRET_FILES" ]; then
        error "Secret-like files are tracked:\n$SECRET_FILES"
    else
        echo "OK: No secret-like files tracked" >> "$WORKLOG"
        log "No secret files tracked ✓"
    fi
}

# Step 2: Export workflows (manual step reminder)
verify_workflows() {
    log "Step 2: Verifying workflow exports..."
    
    echo "" >> "$WORKLOG"
    echo "## Step 2: Workflow Export Verification" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    if [ ! -d "$WORKFLOW_DIR" ]; then
        warn "Workflow directory not found: $WORKFLOW_DIR"
        echo "WARNING: Workflow directory not found" >> "$WORKLOG"
        return
    fi
    
    echo "### Exported workflow files:" >> "$WORKLOG"
    ls -lah "$WORKFLOW_DIR"/*.json >> "$WORKLOG" 2>&1 || echo "(no workflow files)" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    log "Found workflow files:"
    ls -1 "$WORKFLOW_DIR"/*.json 2>/dev/null | while read f; do
        log "  - $(basename $f)"
    done
}

# Step 3: Diff check
show_diff() {
    log "Step 3: Checking diffs..."
    
    echo "" >> "$WORKLOG"
    echo "## Step 3: Diff Review" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    echo "### Files changed:" >> "$WORKLOG"
    git diff --stat >> "$WORKLOG" 2>&1 || true
    echo "" >> "$WORKLOG"
    
    if git diff --quiet HEAD 2>/dev/null; then
        warn "No changes to commit"
        echo "No changes detected" >> "$WORKLOG"
        return 1
    fi
    
    # Check for suspicious patterns in diff
    SUSPICIOUS=$(git diff | grep -E '(password|secret|token|key).*[=:].*[A-Za-z0-9]{10,}' || true)
    if [ -n "$SUSPICIOUS" ]; then
        warn "Suspicious patterns in diff - review carefully:"
        echo "$SUSPICIOUS"
        echo "" >> "$WORKLOG"
        echo "WARNING: Suspicious patterns in diff:" >> "$WORKLOG"
        echo '```' >> "$WORKLOG"
        echo "$SUSPICIOUS" >> "$WORKLOG"
        echo '```' >> "$WORKLOG"
        echo "" >> "$WORKLOG"
    fi
    
    return 0
}

# Step 4: Secret scan
secret_scan() {
    log "Step 4: Running secret scan..."
    
    echo "" >> "$WORKLOG"
    echo "## Step 4: Secret Scan" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    local FOUND_SECRETS=false
    
    # Scan for common secret patterns
    echo "### Pattern scan:" >> "$WORKLOG"
    SCAN_RESULTS=$(grep -r --line-number --ignore-case \
        -E "(api[_-]?key|secret|token|password|PRIVATE KEY|BEGIN [A-Z ]*PRIVATE KEY|Bearer[[:space:]]+[A-Za-z0-9.*-]+)" \
        . \
        --exclude-dir=.git \
        --exclude-dir=node_modules \
        2>/dev/null | grep -v "example\|placeholder\|your-\|FILTERED\|dummy\|test" || true)
    
    if [ -n "$SCAN_RESULTS" ]; then
        warn "Potential secrets found - review required:"
        echo "$SCAN_RESULTS"
        echo '```' >> "$WORKLOG"
        echo "$SCAN_RESULTS" >> "$WORKLOG"
        echo '```' >> "$WORKLOG"
        FOUND_SECRETS=true
    else
        echo "OK: No obvious secrets found" >> "$WORKLOG"
        log "No obvious secrets found ✓"
    fi
    
    # Check n8n workflows for embedded credentials
    echo "" >> "$WORKLOG"
    echo "### n8n workflow credential check:" >> "$WORKLOG"
    if [ -d "$WORKFLOW_DIR" ]; then
        CRED_CHECK=$(grep -r --line-number --ignore-case \
            -E '"accessToken"|"refreshToken"|"clientSecret"|"privateKey"' \
            "$WORKFLOW_DIR" \
            2>/dev/null || true)
        
        if [ -n "$CRED_CHECK" ]; then
            warn "Embedded credentials found in workflows!"
            echo "$CRED_CHECK"
            echo '```' >> "$WORKLOG"
            echo "$CRED_CHECK" >> "$WORKLOG"
            echo '```' >> "$WORKLOG"
            FOUND_SECRETS=true
        else
            echo "OK: No embedded credentials" >> "$WORKLOG"
            log "No embedded credentials ✓"
        fi
    fi
    
    # Check .env file not staged
    echo "" >> "$WORKLOG"
    echo "### .env file check:" >> "$WORKLOG"
    if git diff --cached --name-only | grep -qE '^.env$'; then
        error ".env file is staged for commit! Aborting."
    else
        echo "OK: .env not staged" >> "$WORKLOG"
    fi
    
    if [ "$FOUND_SECRETS" = true ]; then
        warn "Secret scan completed with warnings. Review carefully before proceeding."
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log "Aborted by user"
            exit 1
        fi
    else
        log "Secret scan passed ✓"
    fi
}

# Step 5: Validation checks
run_validations() {
    log "Step 5: Running validations..."
    
    echo "" >> "$WORKLOG"
    echo "## Step 5: Validations" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    # Run any existing validation scripts
    if [ -f "scripts/validate_slack_workflows.py" ]; then
        log "Running validate_slack_workflows.py..."
        python3 scripts/validate_slack_workflows.py 2>&1 | tee -a "$WORKLOG" || warn "Validation script failed"
    fi
    
    if [ -f "scripts/ci/n8n_import_test.sh" ]; then
        log "Running n8n_import_test.sh..."
        bash scripts/ci/n8n_import_test.sh 2>&1 | tee -a "$WORKLOG" || warn "CI test failed"
    fi
    
    echo "Validations complete" >> "$WORKLOG"
}

# Step 6: Stage files
stage_files() {
    log "Step 6: Staging files..."
    
    echo "" >> "$WORKLOG"
    echo "## Step 6: Staging" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    # Check what files would be staged
    echo "### Files to stage:" >> "$WORKLOG"
    git status --short >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    log "Use explicit 'git add' for each file you want to commit."
    log "Example: git add n8n/workflows-v3/slack_chat_minimal_v1.json"
    log ""
    log "Current modified files:"
    git status --short
}

# Step 7: Commit
commit_changes() {
    log "Step 7: Committing..."
    
    echo "" >> "$WORKLOG"
    echo "## Step 7: Commit" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    # Check if anything is staged
    if git diff --cached --quiet; then
        warn "No files staged for commit"
        log "Use 'git add <file>' to stage files first"
        return 1
    fi
    
    # Show what will be committed
    echo "### Staged files:" >> "$WORKLOG"
    git diff --cached --stat >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    log "Staged files:"
    git diff --cached --stat
    
    # Commit with provided message or default
    COMMIT_MSG="${1:-"chore(n8n): update workflows $(date +%Y-%m-%d)"}"
    
    log "Committing with message: $COMMIT_MSG"
    git commit -m "$COMMIT_MSG" 2>&1 | tee -a "$WORKLOG"
    
    COMMIT_HASH=$(git rev-parse --short HEAD)
    echo "" >> "$WORKLOG"
    echo "Commit hash: $COMMIT_HASH" >> "$WORKLOG"
    log "Committed: $COMMIT_HASH ✓"
}

# Step 8: Push
push_changes() {
    log "Step 8: Pushing to origin..."
    
    echo "" >> "$WORKLOG"
    echo "## Step 8: Push" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    # Check if there are commits to push
    if git diff --quiet HEAD @{upstream} 2>/dev/null; then
        warn "No commits to push"
        return 0
    fi
    
    # Push
    git push origin "$(git branch --show-current)" 2>&1 | tee -a "$WORKLOG"
    log "Pushed successfully ✓"
}

# Step 9: Post-push verification
verify_push() {
    log "Step 9: Post-push verification..."
    
    echo "" >> "$WORKLOG"
    echo "## Step 9: Post-Push Verification" >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    # Verify working tree clean
    echo "### Git status:" >> "$WORKLOG"
    git status >> "$WORKLOG" 2>&1
    echo "" >> "$WORKLOG"
    
    # Show last commit
    echo "### Last commit:" >> "$WORKLOG"
    git log -1 --oneline >> "$WORKLOG"
    echo "" >> "$WORKLOG"
    
    # Verify remote
    echo "### Remote status:" >> "$WORKLOG"
    git log --oneline --decorate -3 >> "$WORKLOG"
    
    log "Post-push verification complete ✓"
}

# Main execution
main() {
    log "=== Safe Push Runbook ==="
    log "Starting safe push procedure..."
    
    # Initialize
    check_repo
    WORKLOG=$(init_worklog)
    export WORKLOG
    
    log "Work log: $WORKLOG"
    
    # Run all steps
    verify_repo_state
    verify_workflows
    
    if ! show_diff; then
        log "No changes to commit. Exiting."
        echo "" >> "$WORKLOG"
        echo "No changes to commit." >> "$WORKLOG"
        echo "SUCCESS: $WORKLOG" >> "$WORKLOG"
        exit 0
    fi
    
    secret_scan
    run_validations
    stage_files
    
    # Interactive staging
    log ""
    log "Ready to stage files."
    log "Common workflow files:"
    ls -1 n8n/workflows-v3/*.json 2>/dev/null | head -5
    log ""
    log "Stage your files manually:"
    log "  git add n8n/workflows-v3/slack_chat_minimal_v1.json"
    log "  git add n8n/workflows-v3/chat_router_v1.json"
    log ""
    log "Then run: git commit -m 'your message' && git push origin main"
    
    # Optional: auto-commit if files are staged
    if ! git diff --cached --quiet; then
        read -p "Files are staged. Commit now? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            commit_changes "${1:-}"
            push_changes
            verify_push
        fi
    fi
    
    # Finalize
    echo "" >> "$WORKLOG"
    echo "SUCCESS: $WORKLOG" >> "$WORKLOG"
    log "Work log saved: $WORKLOG"
    log "=== Safe Push Complete ==="
}

# Run main if executed directly
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
