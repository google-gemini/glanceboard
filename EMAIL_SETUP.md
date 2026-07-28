<!--
Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the Apache License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# 📧 Email Widget Setup Guide

The **Email** widget adds a daily email digest to your Glanceboard display — a short AI-summarised snapshot of your unread emails so you know at a glance if anything important has arrived.

> **This is entirely optional.** If you don't set it up, everything else works exactly the same. The email widget simply won't appear as available in the dashboard.

---

## What it does

- Reads the **subject lines and sender names** of your most recent unread emails (up to 5 by default)
- Uses **Gemini** to summarise them into a short, friendly digest (e.g., "3 new: School newsletter, Amazon delivery, Dentist reminder")
- Renders the digest onto your e-ink display as a widget, alongside your calendar, weather, etc.

## What it does NOT do

- ❌ Does **not** read email bodies — only subject lines and sender names
- ❌ Does **not** store any email content — it's fetched fresh each generation
- ❌ Does **not** send email data anywhere — summarisation happens locally via the Gemini API you already have configured
- ❌ Does **not** require any hosted infrastructure — everything runs on your own machine

---

## Prerequisites

- A working Glanceboard server (follow the main [README](README.md) first)
- A Google account with Gmail
- Access to the [Google Cloud Console](https://console.cloud.google.com/)

---

## Step 1: Install the email dependencies

The email widget requires a few additional Python packages. From the `server/` directory:

```bash
cd server
source venv/bin/activate
pip install -r requirements-email.txt
```

This installs:
- `google-auth-oauthlib` — Google OAuth 2.0 authentication
- `google-api-python-client` — Gmail API client
- `google-auth-httplib2` — HTTP transport for Google API calls

---

## Step 2: Enable the Gmail API

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Select the same project you use for your Gemini API key (or create a new one)
3. Go to **APIs & Services** → **Library**
4. Search for **Gmail API**
5. Click **Enable**

---

## Step 3: Create OAuth 2.0 credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **+ Create Credentials** → **OAuth 2.0 Client ID**
3. If prompted to configure the OAuth consent screen:
   - Choose **External** (unless you have Google Workspace and want Internal)
   - Fill in the required fields:
     - **App name**: `Glanceboard Email`
     - **User support email**: your email
     - **Developer contact email**: your email
   - Click **Save and Continue**
   - On the **Scopes** page, click **Add or Remove Scopes**
     - Search for `gmail.readonly` and select it
     - Click **Update** → **Save and Continue**
   - On the **Test users** page, click **+ Add Users**
     - Add your Gmail address
     - Click **Save and Continue**
   - Click **Back to Dashboard**
4. Now go back to **Credentials** → **+ Create Credentials** → **OAuth 2.0 Client ID**
   - **Application type**: Desktop application (recommended) or Web application
   - **Name**: `Glanceboard Email`
   - If using **Web application**:
     - **Authorized redirect URIs**: `http://localhost:8000/api/email/callback`
5. Click **Create**
6. Click **Download JSON** (the download icon ⬇️)
7. Save the file as `gmail_credentials.json` in your `server/data/` directory:

```
glanceboard/
└── server/
    └── data/
        └── gmail_credentials.json   ← put it here
```

> ⚠️ **Keep this file private.** It contains your OAuth client secret. It is already in `.gitignore` and will never be committed to the repository.

---

## Step 4: Authorise your Gmail account

1. Start your Glanceboard server as usual:
   ```bash
   cd server
   source venv/bin/activate
   python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
   ```

2. Open the Glanceboard dashboard at [http://localhost:8000](http://localhost:8000)

3. Go to the **Layout** page and drag the **📧 Email** widget onto your grid

4. Click the **⚙️** gear icon on the widget — the config panel will show a **Connect Gmail** button

5. Click **Connect Gmail** — a new browser tab will open with the Google OAuth consent screen

6. Sign in with your Google account and grant Glanceboard **read-only** access to your Gmail

7. You'll be redirected back and the widget will show ✅ **Gmail connected**

> The OAuth refresh token is stored in `server/data/gmail_token.json` (gitignored). You only need to do this once — the token refreshes automatically.

---

## Step 5: Configure the widget (optional)

In the widget config panel, you can adjust:

- **Max emails**: How many unread emails to include (default: 5)

---

## Privacy

- **Read-only access**: Glanceboard only requests `gmail.readonly` scope — it cannot send, delete, or modify your emails
- **Subject lines only**: Only the sender name and subject line are read — email bodies are never accessed
- **No storage**: Email data is fetched fresh each time an image is generated and is not persisted
- **Local processing**: The email summary is generated by calling the Gemini API (the same one you use for image generation) — no other services are involved
- **Your credentials**: The OAuth token is stored locally in `server/data/gmail_token.json` and is gitignored

---

## Disconnecting

To disconnect Gmail:
1. Click the **⚙️** gear icon on the Email widget
2. Click **Disconnect Gmail**

Or manually:
1. Delete `server/data/gmail_token.json`
2. Optionally delete `server/data/gmail_credentials.json`
3. Revoke access at [myaccount.google.com/permissions](https://myaccount.google.com/permissions)

---

## Troubleshooting

### "Email dependencies not installed"
```bash
cd server
source venv/bin/activate
pip install -r requirements-email.txt
```

### "Gmail credentials not found"
Make sure you downloaded the OAuth client JSON from Google Cloud Console and saved it as `server/data/gmail_credentials.json`.

### "Access blocked: This app's request is invalid" (Error 400)
- If using **Web application** type: make sure `http://localhost:8000/api/email/callback` is listed as an authorised redirect URI
- If using **Desktop application** type: this should work without redirect URI configuration

### "Access blocked: Glanceboard Email has not completed the Google verification process"
This is normal for apps in "Testing" mode. Click **Continue** (you may need to click "Advanced" first). Since you created the app yourself and added yourself as a test user, this is safe.

### "Token has been expired or revoked"
Delete `server/data/gmail_token.json` and re-authorise via the dashboard. This can happen if you revoke access from your Google account settings.

### "Quota exceeded"
The Gmail API has a generous free quota (250 quota units per second). Glanceboard makes very few calls (once per image generation). This should never be an issue for personal use.
