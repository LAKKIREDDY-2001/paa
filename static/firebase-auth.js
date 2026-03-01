// Firebase Authentication for Price Alert App
// Using Firebase SDK bundled via npm + esbuild

// Firebase configuration - using the config from firebase-init.js
// The actual initialization is done in firebase-entry.js bundle

// Auth reference - will be initialized from the bundle
let auth = null;

// Initialize Firebase Auth from bundle
function initFirebaseAuth() {
  // Check if Firebase is available from the bundle
  if (window.firebaseApp && window.firebaseAuth) {
    auth = window.firebaseAuth;
    console.log('Firebase Auth initialized from bundle');
    return auth;
  }
  
  // Fallback: use global firebase if available (from bundle)
  if (typeof firebase !== 'undefined' && firebase.auth) {
    if (!firebase.apps || firebase.apps.length === 0) {
      // If no apps initialized, try to initialize with config
      if (window.firebaseConfig) {
        firebase.initializeApp(window.firebaseConfig);
      }
    }
    auth = firebase.auth();
    console.log('Firebase Auth initialized from global firebase');
    return auth;
  }
  
  console.warn('Firebase Auth not available from bundle');
  return null;
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  // Small delay to ensure firebase-init.js and bundle have loaded
  setTimeout(() => {
    initFirebaseAuth();
  }, 100);
});

// ==================== AUTHENTICATION FUNCTIONS ====================

// Sign in with Google
async function signInWithGoogle() {
  if (!auth) {
    auth = initFirebaseAuth();
  }
  
  if (!auth) {
    throw new Error('Firebase Auth not initialized');
  }
  
  // Check if we have the auth functions from bundle
  if (window.firebaseAuthFunctions && window.firebaseAuthFunctions.signInWithGoogle) {
    return await window.firebaseAuthFunctions.signInWithGoogle();
  }
  
  throw new Error('Google sign-in not available');
}

// Sign in with email/password
async function signInWithEmail(email, password) {
  if (!auth) {
    auth = initFirebaseAuth();
  }
  
  if (!auth) {
    throw new Error('Firebase Auth not initialized');
  }
  
  if (window.firebaseAuthFunctions && window.firebaseAuthFunctions.signInWithEmail) {
    return await window.firebaseAuthFunctions.signInWithEmail(email, password);
  }
  
  throw new Error('Email sign-in not available');
}

// Sign up with email/password
async function signUpWithEmail(email, password, username) {
  if (!auth) {
    auth = initFirebaseAuth();
  }
  
  if (!auth) {
    throw new Error('Firebase Auth not initialized');
  }
  
  if (window.firebaseAuthFunctions && window.firebaseAuthFunctions.signUpWithEmail) {
    return await window.firebaseAuthFunctions.signUpWithEmail(email, password, username);
  }
  
  throw new Error('Email sign-up not available');
}

// Sign out
async function signOut() {
  if (!auth) {
    auth = initFirebaseAuth();
  }
  
  if (!auth) {
    throw new Error('Firebase Auth not initialized');
  }
  
  if (window.firebaseAuthFunctions && window.firebaseAuthFunctions.signOut) {
    return await window.firebaseAuthFunctions.signOut();
  }
  
  throw new Error('Sign out not available');
}

// Get current user
function getCurrentUser() {
  if (!auth) {
    auth = initFirebaseAuth();
  }
  return auth ? auth.currentUser : null;
}

// Get ID token for backend verification
async function getIdToken() {
  if (!auth) {
    auth = initFirebaseAuth();
  }
  
  if (!auth || !auth.currentUser) {
    return null;
  }
  
  return await auth.currentUser.getIdToken();
}

// Listen to auth state changes
function onAuthStateChanged(callback) {
  if (!auth) {
    auth = initFirebaseAuth();
  }
  
  if (auth) {
    auth.onAuthStateChanged(callback);
  }
}

// Check if user is authenticated
function isAuthenticated() {
  if (!auth) {
    auth = initFirebaseAuth();
  }
  return auth ? auth.currentUser !== null : false;
}

// Send password reset email
async function sendPasswordResetEmail(email) {
  if (!auth) {
    auth = initFirebaseAuth();
  }
  
  if (!auth) {
    throw new Error('Firebase Auth not initialized');
  }
  
  if (window.firebaseAuthFunctions && window.firebaseAuthFunctions.resetPassword) {
    return await window.firebaseAuthFunctions.resetPassword(email);
  }
  
  throw new Error('Password reset not available');
}

// Export for use in other modules
window.firebaseAuth = {
  signInWithGoogle,
  signInWithEmail,
  signUpWithEmail,
  signOut,
  getCurrentUser,
  getIdToken,
  onAuthStateChanged,
  isAuthenticated,
  sendPasswordResetEmail,
  initFirebaseAuth,
  getAuth: () => auth
};

console.log('Firebase auth module loaded');

