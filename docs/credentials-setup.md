# n8n Credentials Setup Guide

## Issue
After upgrading n8n to 2.9.1, the following credentials are missing and need to be recreated:

1. **Google Account** (for Gmail integration)
2. **Google Gemini API** (for AI processing)
3. **Slack API** (for notifications)

## Solution

### Prerequisites
- Access to n8n UI: https://n8n-s-app01.tmcast.net
- Google Cloud Console access (for OAuth)
- Google AI Studio access (for Gemini API key)
- Slack App access (for bot token)

---

## Step 1: Google OAuth2 Credential (Gmail)

### 1.1 In n8n:
1. Go to https://n8n-s-app01.tmcast.net/credentials
2. Click **"Add Credential"**
3. Search for **"Google OAuth2 API"**
4. Set Name: `Google account`

### 1.2 Copy the OAuth Redirect URL:
- The form will show a URL like:
  `https://n8n-s-app01.tmcast.net/rest/oauth2-credential/callback`
- Copy this URL

### 1.3 In Google Cloud Console:
1. Go to https://console.cloud.google.com/apis/credentials
2. Select your project
3. Click **"Create Credentials"** → **"OAuth client ID"**
4. Application type: **"Web application"**
5. Name: `n8n-gmail`
6. Authorized redirect URIs: Paste the URL from step 1.2
7. Click **"Create"**
8. Copy the **Client ID** and **Client Secret**

### 1.4 Back in n8n:
1. Paste the Client ID and Client Secret
2. Set Scope: `https://www.googleapis.com/auth/gmail.readonly`
3. Click **"Connect my account"**
4. Complete the Google authorization flow

---

## Step 2: Google Gemini API Credential

### 2.1 Get API Key:
1. Go to https://makersuite.google.com/app/apikey
2. Click **"Create API Key"**
3. Copy the key

### 2.2 In n8n:
1. Go to https://n8n-s-app01.tmcast.net/credentials
2. Click **"Add Credential"**
3. Search for **"Google PaLM API"** (or "Google Gemini API")
4. Set Name: `Google Gemini(PaLM) Api account`
5. Paste the API Key
6. Click **"Save"**

---

## Step 3: Slack API Credential

### 3.1 Get Bot Token:
1. Go to https://api.slack.com/apps
2. Select your app (or create one)
3. Go to **"OAuth & Permissions"**
4. Copy the **"Bot User OAuth Token"** (starts with `xoxb-`)

### 3.2 In n8n:
1. Go to https://n8n-s-app01.tmcast.net/credentials
2. Click **"Add Credential"**
3. Search for **"Slack API"**
4. Set Name: `Slack account`
5. Paste the Bot Token
6. Click **"Save"**

---

## Step 4: Verify

Test the credentials:

1. Open **brain_router_v1** workflow
2. Click on **"Call Gemini"** node
3. Select the credential from dropdown
4. Click **"Test Step"**

Or run the Gmail workflow and check if it processes emails successfully.

---

## Troubleshooting

### "Credentials could not be decrypted"
- The N8N_ENCRYPTION_KEY changed or is missing
- Check: `grep N8N_ENCRYPTION_KEY /opt/ai-orchestrator/.env`
- If different from backup, restore from: `/opt/ai-orchestrator/backups/n8n-upgrade-20260218-223409/`

### "Invalid credentials"
- Re-create the credential following the steps above
- Verify API keys/tokens are active and not expired

### OAuth redirect mismatch
- Ensure the exact URL from n8n is added to Google Cloud Console
- Include the full path: `/rest/oauth2-credential/callback`
