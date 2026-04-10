#!/bin/bash
# Credential setup helper for n8n

echo "=== n8n Credential Setup Helper ==="
echo ""
echo "Credentials need to be recreated in n8n UI."
echo "URL: https://n8n-s-app01.tmcast.net/credentials"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd /opt/ai-orchestrator 2>/dev/null || cd "$REPO_DIR" || {
    echo "Error: unable to locate repository directory" >&2
    exit 1
}

echo "=== Required Credentials ==="
echo ""

echo "1. GOOGLE OAUTH2 (for Gmail)"
echo "   - Name: Google account"
echo "   - Type: Google OAuth2 API"
echo "   - Scopes: https://www.googleapis.com/auth/gmail.readonly"
echo "   - Redirect URL: https://n8n-s-app01.tmcast.net/rest/oauth2-credential/callback"
echo ""

echo "2. GOOGLE GEMINI API"
echo "   - Name: Google Gemini(PaLM) Api account"
echo "   - Type: Google PaLM API"
echo "   - API Key: [Get from https://makersuite.google.com/app/apikey]"
echo ""

echo "3. SLACK API"
echo "   - Name: Slack account"
echo "   - Type: Slack API"
echo "   - Access Token: [Get from https://api.slack.com/apps -> OAuth & Permissions]"
echo ""

echo "4. POSTGRES (already exists)"
echo "   - Name: Postgres account"
echo "   - Status: ✅ OK"
echo ""

echo "=== Current Environment Variables ==="
if [ -f .env ]; then
    echo ""
    echo "BRAIN_PROVIDER: $(grep "^BRAIN_PROVIDER=" .env | cut -d= -f2)"
    echo "BRAIN_MODEL: $(grep "^BRAIN_MODEL=" .env | cut -d= -f2)"
    echo ""
    
    # Check for API keys
    if grep -q "^GEMINI_API_KEY=" .env 2>/dev/null; then
        echo "GEMINI_API_KEY: [Set in .env]"
    else
        echo "⚠️  GEMINI_API_KEY: Not set in .env"
    fi
    
    if grep -q "^OPENAI_API_KEY=" .env 2>/dev/null; then
        VAL=$(grep "^OPENAI_API_KEY=" .env | cut -d= -f2)
        if [ -n "$VAL" ]; then
            echo "OPENAI_API_KEY: [Set in .env]"
        else
            echo "⚠️  OPENAI_API_KEY: Empty in .env"
        fi
    fi
fi

echo ""
echo "=== Step-by-Step Instructions ==="
echo ""
echo "1. Open https://n8n-s-app01.tmcast.net/credentials"
echo ""
echo "2. Click 'Add Credential' and create each one:"
echo ""
echo "   GOOGLE ACCOUNT:"
echo "   - Type: 'Google OAuth2 API'"
echo "   - Name: 'Google account'"
echo "   - Copy the OAuth Redirect URL from the form"
echo "   - Add this URL to your Google Cloud Console -> Credentials -> OAuth 2.0 Client"
echo "   - Enter Client ID and Secret"
echo "   - Click 'Connect my account' and authorize"
echo ""
echo "   GEMINI API:"
echo "   - Type: 'Google PaLM API' (or 'Google Gemini API')"
echo "   - Name: 'Google Gemini(PaLM) Api account'"
echo "   - API Key: Get from https://makersuite.google.com/app/apikey"
echo ""
echo "   SLACK API:"
echo "   - Type: 'Slack API'"
echo "   - Name: 'Slack account'"
echo "   - Access Token: Bot token from Slack app (xoxb-...)"
echo ""
echo "3. Test workflows after all credentials are created"
echo ""
