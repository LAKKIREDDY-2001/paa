// Firebase Initialization for Price Alert App
// Using Firebase SDK bundled via npm + esbuild

// Your web app's Firebase configuration (from task)
const firebaseConfig = {
  apiKey: "AIzaSyCNmtIZice9l2M-sk-lJ82m0BWYC2Ypl08",
  authDomain: "ai-price-alert.firebaseapp.com",
  projectId: "ai-price-alert",
  storageBucket: "ai-price-alert.firebasestorage.app",
  messagingSenderId: "150142041812",
  appId: "1:150142041812:web:c645b3d9d6f1fea4b6c541",
  measurementId: "G-0WZN54TWR0"
};

// reCAPTCHA v3 Site Key for Firebase App Check
const RECAPTCHA_SITE_KEY = "6Lfi-UUsAAAAALVa4-MIVKWmfy7P7wMR0jZRa9KY";

// Expose config globally for use in other scripts
window.firebaseConfig = firebaseConfig;
window.recaptchaSiteKey = RECAPTCHA_SITE_KEY;

console.log('Firebase config loaded from firebase-init.js');

