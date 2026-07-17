/**
 * Glanceboard Configuration — SELF-HOSTING TEMPLATE
 *
 * Instructions:
 *   1. Copy this file to config.js:  cp config.example.js config.js
 *   2. Fill in your Firebase project values below
 *
 * Get your Firebase config from:
 *   Firebase Console → Project Settings → Your Apps → Web app → Config
 */

// ─── Firebase Config ───────────────────────────────────────────
export const firebaseConfig = {
  apiKey: "YOUR_FIREBASE_API_KEY",
  authDomain: "YOUR_PROJECT.firebaseapp.com",
  projectId: "YOUR_PROJECT",
  storageBucket: "YOUR_PROJECT.firebasestorage.app",
  messagingSenderId: "YOUR_SENDER_ID",
  appId: "YOUR_APP_ID",
};

// ─── Firebase Functions Region ─────────────────────────────────
// Change this to the region where you deploy your Cloud Functions
export const FUNCTIONS_REGION = "us-central1";

// ─── Default Settings ──────────────────────────────────────────
export const DEFAULT_TIMEZONE = "America/New_York";
