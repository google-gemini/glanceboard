# Self-Hosting Guide

Run your own instance of Glanceboard. This guide covers deploying to Firebase (the easiest path), but the backend is just Python Flask endpoints and the frontend is a static Vite SPA — you could adapt it to run locally, on a VPS, or any cloud platform you prefer.

---

## Prerequisites

- A Google account
- [Node.js](https://nodejs.org/) 18+ installed
- [Python 3.11+](https://www.python.org/) installed
- A credit card (Firebase Blaze plan is pay-as-you-go; the free tier covers most usage)

---

## Step 1: Create a Firebase Project

1. Go to [console.firebase.google.com](https://console.firebase.google.com/)
2. Click **Add Project** → Name it (e.g., `my-glanceboard`)
3. Disable Google Analytics (optional, not needed)
4. Click **Create Project**

### Upgrade to Blaze Plan
Cloud Functions require the Blaze (pay-as-you-go) plan. Don't worry — there's a generous free tier:
1. In the Firebase console, click ⚙️ → **Usage and billing** → **Details & settings**
2. Click **Upgrade** → **Blaze**
3. Add a payment method

### Enable Services
1. **Authentication** → Get Started → Enable **Google** sign-in provider → Save
2. **Firestore Database** → Create Database → Start in production mode → Select your region
3. **Storage** → Get Started → Start in production mode
4. **Functions** → Get Started (will be set up via CLI)

---

## Step 2: Get Your Firebase Config

1. In the Firebase console, click ⚙️ → **Project Settings**
2. Scroll to **Your apps** → Click **Web** (</>) → Register app
3. Copy the `firebaseConfig` object — you'll need these values

---

## Step 3: Set Up Google Calendar OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your Firebase project
3. Go to **APIs & Services** → **Credentials**
4. Click **Create Credentials** → **OAuth 2.0 Client ID**
   - Application type: **Web application**
   - Name: `Glanceboard Calendar`
   - Authorized JavaScript origins: `http://localhost:5173` (dev) + your production domain
   - Authorized redirect URIs: Same as origins
5. Copy the **Client ID** and **Client Secret**

### Enable the Calendar API
1. Go to **APIs & Services** → **Library**
2. Search for **Google Calendar API** → **Enable**

### Store Secrets in Firebase
```bash
# Install Firebase CLI
npm install -g firebase-tools

# Login
firebase login

# Set your project
firebase use your-project-id

# Store secrets
firebase functions:secrets:set GOOGLE_CLIENT_ID
# Paste your OAuth Client ID

firebase functions:secrets:set GOOGLE_CLIENT_SECRET
# Paste your OAuth Client Secret
```

---

## Step 4: Clone and Configure

```bash
# Clone the repo
git clone https://github.com/botti/glanceboard.git
cd glanceboard

# Copy the config template
cp web/src/config.example.js web/src/config.js
```

Edit `web/src/config.js` with your Firebase config values:
```javascript
export const firebaseConfig = {
  apiKey: "YOUR_FIREBASE_API_KEY",
  authDomain: "YOUR_PROJECT.firebaseapp.com",
  projectId: "YOUR_PROJECT",
  storageBucket: "YOUR_PROJECT.firebasestorage.app",
  messagingSenderId: "YOUR_SENDER_ID",
  appId: "YOUR_APP_ID",
};

export const GOOGLE_CLIENT_ID = "YOUR_OAUTH_CLIENT_ID.apps.googleusercontent.com";
export const FUNCTIONS_REGION = "us-central1"; // or your preferred region
export const DEPLOYMENT_MODE = "selfhost";
```

---

## Step 5: Deploy

```bash
# Install web dependencies
cd web && npm install && cd ..

# Build the frontend
cd web && npm run build && cd ..

# Deploy everything to Firebase
firebase deploy
```

This deploys:
- **Hosting** → Your dashboard at `your-project.web.app`
- **Functions** → Cloud Functions (Python)
- **Firestore Rules** → Security rules
- **Storage Rules** → Storage security rules

---

## Step 6: Set Up Your PhotoPainter Display

See the full [Firmware & Display Setup Guide](firmware/README.md) for detailed instructions.

**Quick version:**
1. Flash the community firmware via the [Web Flasher](https://aitjcize.github.io/esp32-photoframe/#flash) in Chrome
2. Connect the PhotoPainter to your home WiFi via its setup hotspot (`PhotoFrame-XXXX`)
3. Open the device's web interface → **Auto Rotate** → set **Rotation Mode** to `url`
4. Paste your Display Image URL from the Glanceboard dashboard (**Settings → Copy URL**)
5. Set interval to 300 seconds, disable deep sleep, enable auto rotate
6. Generate your first image from the dashboard → the display will fetch and show it!

> 💡 **Using a Raspberry Pi instead?** See the [Legacy Pi Setup Guide](pi/LEGACY_PI_SETUP.md).

---

## Cost Estimates

With the Firebase free tier and Google AI Studio:

| Service | Free Tier | Typical Monthly Cost |
|---------|-----------|---------------------|
| Firebase Auth | 10K users free | $0 |
| Firestore | 50K reads/day free | $0 |
| Firebase Storage | 5GB free | $0 |
| Cloud Functions | 2M invocations free | $0 |
| Firebase Hosting | 10GB free | $0 |
| **Google AI Studio** | Varies | **~$1-3** (2 images/day) |

**Total estimated cost: ~$1-3/month** (just the AI image generation API).

---

## Updating

```bash
git pull origin main
cd web && npm run build && cd ..
firebase deploy
```

---

## Troubleshooting

### "Permission denied" errors
- Make sure Firestore and Storage rules are deployed: `firebase deploy --only firestore,storage`

### Cloud Functions failing
- Check the region matches your config: `FUNCTIONS_REGION` in `config.js`
- Check secrets are set: `firebase functions:secrets:access GOOGLE_CLIENT_ID`

### Calendar not connecting
- Verify your OAuth Client ID matches in both `config.js` and Firebase secrets
- Check that the Calendar API is enabled in Google Cloud Console
- Verify your authorized origins include your domain

### Pi display not updating
- Check the display URL is correct in `~/.glanceboard.conf`
- Generate an image first from the dashboard
- Check Pi logs: `journalctl -u eink-display -f`
