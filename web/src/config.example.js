/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

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
