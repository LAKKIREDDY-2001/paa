// Auth JavaScript - Handles Signup, Login, and Password Reset

// CRITICAL: Override window.open to prevent about:blank
const originalWindowOpen = window.open;
window.open = function(url, target, features) {
    console.log('window.open called:', url, target);
    // Prevent about:blank
    if (!url || url === '' || url === 'about:blank' || url === 'null' || url === 'undefined') {
        console.error('Blocked window.open with invalid URL:', url);
        return null;
    }
    return originalWindowOpen.call(window, url, target, features);
};

// Also override location.href assignments
const originalLocationHref = Object.getOwnPropertyDescriptor(window.Location.prototype, 'href');
if (originalLocationHref) {
    const originalSet = originalLocationHref.set;
    Object.defineProperty(window.Location.prototype, 'href', {
        set: function(value) {
            console.log('Setting location.href:', value);
            if (value && value !== 'about:blank') {
                originalSet.call(this, value);
            }
        },
        get: originalLocationHref.get
    });
}

let signupToken = null;
let emailVerified = false;
let phoneVerified = false;
let signupSubmitting = false;
let loginSubmitting = false;

// Backend API configuration
const getApiBaseUrl = () => {
    return window.location.origin;
};
const API_BASE_URL = getApiBaseUrl();

// Global form submission interceptor - prevent any form from submitting normally
document.addEventListener('DOMContentLoaded', () => {
    console.log('Auth JS loading...');
    
    // Get all forms and buttons
    const signupForm = document.getElementById('signup-form');
    const loginForm = document.getElementById('login-form');
    const forgotPasswordForm = document.getElementById('forgot-password-form');
    const resetPasswordForm = document.getElementById('reset-password-form');
    // Also support old 'forgot-form' ID for backwards compatibility
    const forgotForm = document.getElementById('forgot-form') || document.getElementById('forgot-password-form');

    // Prevent ALL form submissions
    document.addEventListener('submit', (e) => {
        const formId = e.target.id;
        console.log('Form submit intercepted:', formId);
        if (formId === 'signup-form' || formId === 'login-form' || 
            formId === 'forgot-password-form' || formId === 'reset-password-form' ||
            formId === 'forgot-form') {
            e.preventDefault();
            e.stopPropagation();
            return false;
        }
    }, true);
    
    // Prevent default on submit buttons
    document.addEventListener('click', (e) => {
        if (e.target.tagName === 'BUTTON' && e.target.type === 'submit') {
            const form = e.target.closest('form');
            if (form && (form.id === 'signup-form' || form.id === 'login-form' || 
                form.id === 'forgot-password-form' || form.id === 'reset-password-form' ||
                form.id === 'forgot-form')) {
                e.preventDefault();
                e.stopPropagation();
            }
        }
    }, true);

    // DIRECT onclick handlers on buttons - most reliable method
    if (signupForm) {
        console.log('Signup form found');
        // Look for button with id signup-btn (most reliable)
        const signupBtn = document.getElementById('signup-btn');
        if (signupBtn) {
            console.log('Signup button found, adding onclick');
            signupBtn.onclick = function(e) {
                e.preventDefault();
                e.stopPropagation();
                handleSignup(e);
                return false;
            };
        }
        signupForm.addEventListener('submit', handleSignup);
    }

    if (loginForm) {
        console.log('Login form found');
        // Look for button with id login-btn (most reliable)
        const loginBtn = document.getElementById('login-btn');
        if (loginBtn) {
            console.log('Login button found, adding onclick');
            loginBtn.onclick = function(e) {
                e.preventDefault();
                e.stopPropagation();
                handleLogin(e);
                return false;
            };
        }
        loginForm.addEventListener('submit', handleLogin);
    }

    if (forgotPasswordForm) {
        forgotPasswordForm.addEventListener('submit', handleForgotPassword);
    } else if (forgotForm) {
        forgotForm.addEventListener('submit', handleForgotPassword);
    }

    if (resetPasswordForm) {
        resetPasswordForm.addEventListener('submit', handleResetPassword);
    }

    initTilt();
    console.log('Auth JS initialized');
});

function initTilt() {
    // Completely disable tilt on auth pages to prevent cursor flicker on primary buttons.
    // Remove any tilt-related event listeners and CSS transforms
    const tiltRoots = document.querySelectorAll('.tilt-root');
    tiltRoots.forEach((root) => {
        // Remove tilt-active class
        root.classList.remove('tilt-active');
        // Reset CSS custom properties
        root.style.removeProperty('--tilt-x');
        root.style.removeProperty('--tilt-y');
        // Remove the transform that causes the cursor issue
        root.style.transform = 'none';
        root.style.perspective = 'none';
    });
    
    // Remove any existing tilt mouse event listeners by cloning
    document.querySelectorAll('.tilt-root').forEach(root => {
        const newRoot = root.cloneNode(true);
        root.parentNode.replaceChild(newRoot, root);
    });
}

// ==================== SIGNUP FUNCTIONS ====================

async function handleSignup(e) {
    // Always prevent default
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    if (signupSubmitting) return;
    
    const username = document.getElementById('username')?.value;
    const email = document.getElementById('email')?.value;
    const phone = document.getElementById('phone')?.value;
    const password = document.getElementById('password')?.value;
    const confirmPassword = document.getElementById('confirm_password')?.value;
    const errorMessage = document.getElementById('error-message');
    // Get button by ID directly - more reliable
    const submitBtn = document.getElementById('signup-btn');
    
    console.log('handleSignup called', { username, email, submitBtn });
    
    // Validate required fields
    if (!username || !email || !password || !confirmPassword) {
        showError('Please fill in all required fields');
        return;
    }
    
    // Validate passwords match
    if (password !== confirmPassword) {
        showError('Passwords do not match');
        return;
    }
    
    // Validate password strength
    if (password.length < 6) {
        showError('Password must be at least 6 characters');
        return;
    }
    
    // Show loading state
    signupSubmitting = true;
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Creating Account...';
    }
    if (errorMessage) {
        errorMessage.style.display = 'none';
    }
    
    try {
        const response = await fetch(API_BASE_URL + '/signup', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, email, password, phone })
        });
        const rawText = await response.text();
        let data = {};
        try {
            data = rawText ? JSON.parse(rawText) : {};
        } catch (parseError) {
            data = { error: rawText || 'Unexpected server response' };
        }
        
        if (response.ok) {
            showToast('success', 'Account created successfully! Redirecting to login...');
            setTimeout(() => {
                window.location.href = '/login';
            }, 1500);
            return;
        } else {
            showError(data.error || 'Failed to create account. Please try again.');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<span>Create Account</span><i class="fa fa-arrow-right"></i>';
            }
        }
    } catch (error) {
        console.error('Signup error:', error);
        showError('An error occurred. Please try again.');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<span>Create Account</span><i class="fa fa-arrow-right"></i>';
        }
    } finally {
        signupSubmitting = false;
    }
}

function showVerificationSection(email, phone) {
    const signupForm = document.getElementById('signup-form');
    const verificationSection = document.getElementById('verification-section');
    
    // Hide signup form
    if (signupForm) {
        signupForm.style.display = 'none';
    }
    
    // Show verification section
    if (verificationSection) {
        verificationSection.style.display = 'block';
    }
    
    // Update progress
    updateProgress(2);
    
    // Setup email verification
    const emailAddressEl = document.getElementById('email-address');
    const emailVerificationEl = document.getElementById('email-verification');
    if (email && emailAddressEl) {
        const targetSpan = emailAddressEl.querySelector('.target');
        if (targetSpan) {
            targetSpan.textContent = email;
        }
        if (emailVerificationEl) {
            emailVerificationEl.style.display = 'block';
        }
    }
    
    // Setup phone verification
    const phoneNumberEl = document.getElementById('phone-number');
    const phoneVerificationEl = document.getElementById('phone-verification');
    if (phone && phoneNumberEl) {
        const targetSpan = phoneNumberEl.querySelector('.target');
        if (targetSpan) {
            targetSpan.textContent = phone;
        }
        if (phoneVerificationEl) {
            phoneVerificationEl.style.display = 'block';
        }
    }
    
    // Auto-send email OTP
    sendEmailOTP(email, 'verification');
}

function setupSignupOTPEvents() {
    // Send Email OTP
    const sendEmailOtpBtn = document.getElementById('send-email-otp');
    if (sendEmailOtpBtn) {
        sendEmailOtpBtn.addEventListener('click', () => {
            const email = document.getElementById('email')?.value;
            if (email) {
                sendEmailOTP(email, 'verification');
            } else {
                showError('Email is required');
            }
        });
    }
    
    // Verify Email OTP
    const verifyEmailOtpBtn = document.getElementById('verify-email-otp');
    if (verifyEmailOtpBtn) {
        verifyEmailOtpBtn.addEventListener('click', () => {
            const email = document.getElementById('email')?.value;
            const otp = document.getElementById('email-otp')?.value;
            if (email && otp) {
                verifyEmailOTP(email, otp);
            } else {
                showError('Please enter the OTP sent to your email');
            }
        });
    }
    
    // Send Phone OTP
    const sendPhoneOtpBtn = document.getElementById('send-phone-otp');
    if (sendPhoneOtpBtn) {
        sendPhoneOtpBtn.addEventListener('click', () => {
            const phone = document.getElementById('phone')?.value;
            if (phone) {
                sendPhoneOTP(phone, 'verification');
            } else {
                showError('Phone number is required');
            }
        });
    }
    
    // Verify Phone OTP
    const verifyPhoneOtpBtn = document.getElementById('verify-phone-otp');
    if (verifyPhoneOtpBtn) {
        verifyPhoneOtpBtn.addEventListener('click', () => {
            const phone = document.getElementById('phone')?.value;
            const otp = document.getElementById('phone-otp')?.value;
            if (phone && otp) {
                verifyPhoneOTP(phone, otp);
            } else {
                showError('Please enter the OTP sent to your phone');
            }
        });
    }
    
    // Complete Signup
    const completeSignupBtn = document.getElementById('complete-signup');
    if (completeSignupBtn) {
        completeSignupBtn.addEventListener('click', completeSignup);
    }
    
    // Allow Enter key to submit OTP
    const emailOtpInput = document.getElementById('email-otp');
    const phoneOtpInput = document.getElementById('phone-otp');
    
    if (emailOtpInput) {
        emailOtpInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const verifyBtn = document.getElementById('verify-email-otp');
                if (verifyBtn) verifyBtn.click();
            }
        });
    }
    
    if (phoneOtpInput) {
        phoneOtpInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const verifyBtn = document.getElementById('verify-phone-otp');
                if (verifyBtn) verifyBtn.click();
            }
        });
    }
}

async function sendEmailOTP(email, purpose) {
    const btn = document.getElementById('send-email-otp');
    if (!btn) return;
    
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Sending...';
    
    try {
        const response = await fetch(API_BASE_URL + '/api/send-email-otp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                email, 
                purpose,
                signupToken: signupToken  // Include signup token
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showToast('success', 'OTP sent to ' + email);
            btn.innerHTML = '<i class="fa fa-check"></i> Sent!';
            setTimeout(() => {
                btn.innerHTML = '<i class="fa fa-redo"></i> Resend';
                btn.disabled = false;
            }, 30000); // 30 seconds cooldown
        } else {
            showError(data.error || 'Failed to send OTP');
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    } catch (error) {
        console.error('Send OTP error:', error);
        showError('An error occurred');
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

async function verifyEmailOTP(email, otp) {
    if (!otp || otp.length !== 6) {
        showError('Please enter a valid 6-digit OTP');
        return;
    }
    
    const btn = document.getElementById('verify-email-otp');
    if (!btn) return;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Verifying...';
    
    try {
        const response = await fetch(API_BASE_URL + '/api/verify-email-otp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, otp })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            emailVerified = true;
            const emailStatus = document.getElementById('email-status');
            const emailOtpInput = document.getElementById('email-otp');
            
            if (emailStatus) {
                emailStatus.innerHTML = '<i class="fa fa-check-circle"></i> Verified';
                emailStatus.classList.add('verified');
            }
            if (emailOtpInput) {
                emailOtpInput.disabled = true;
            }
            btn.innerHTML = '<i class="fa fa-check"></i> Verified!';
            showToast('success', 'Email verified successfully!');
            checkSignupComplete();
        } else {
            showError(data.error || 'Invalid OTP');
            btn.disabled = false;
            btn.innerHTML = '<i class="fa fa-check"></i> Verify Email';
        }
    } catch (error) {
        console.error('Verify OTP error:', error);
        showError('An error occurred');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa fa-check"></i> Verify Email';
    }
}

async function sendPhoneOTP(phone, purpose) {
    if (!phone) {
        showError('Phone number is required');
        return;
    }
    
    const btn = document.getElementById('send-phone-otp');
    if (!btn) return;
    
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Sending...';
    
    try {
        const response = await fetch(API_BASE_URL + '/api/send-phone-otp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                phone, 
                purpose,
                signupToken: signupToken  // Include signup token
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showToast('success', 'OTP sent to ' + phone);
            btn.innerHTML = '<i class="fa fa-check"></i> Sent!';
            setTimeout(() => {
                btn.innerHTML = '<i class="fa fa-redo"></i> Resend';
                btn.disabled = false;
            }, 30000);
        } else {
            showError(data.error || 'Failed to send OTP');
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    } catch (error) {
        console.error('Send OTP error:', error);
        showError('An error occurred');
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

async function verifyPhoneOTP(phone, otp) {
    if (!otp || otp.length !== 6) {
        showError('Please enter a valid 6-digit OTP');
        return;
    }
    
    const btn = document.getElementById('verify-phone-otp');
    if (!btn) return;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Verifying...';
    
    try {
        const response = await fetch(API_BASE_URL + '/api/verify-phone-otp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone, otp })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            phoneVerified = true;
            const phoneStatus = document.getElementById('phone-status');
            const phoneOtpInput = document.getElementById('phone-otp');
            
            if (phoneStatus) {
                phoneStatus.innerHTML = '<i class="fa fa-check-circle"></i> Verified';
                phoneStatus.classList.add('verified');
            }
            if (phoneOtpInput) {
                phoneOtpInput.disabled = true;
            }
            btn.innerHTML = '<i class="fa fa-check"></i> Verified!';
            showToast('success', 'Phone verified successfully!');
            checkSignupComplete();
        } else {
            showError(data.error || 'Invalid OTP');
            btn.disabled = false;
            btn.innerHTML = '<i class="fa fa-check"></i> Verify Phone';
        }
    } catch (error) {
        console.error('Verify OTP error:', error);
        showError('An error occurred');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa fa-check"></i> Verify Phone';
    }
}

function checkSignupComplete() {
    const completeBtn = document.getElementById('complete-signup');
    const email = document.getElementById('email')?.value;
    const phone = document.getElementById('phone')?.value;
    
    // Check if all provided methods are verified
    let canComplete = emailVerified;
    if (phone) {
        canComplete = canComplete && phoneVerified;
    }
    
    if (completeBtn) {
        completeBtn.disabled = !canComplete;
        if (canComplete) {
            completeBtn.classList.add('active');
            updateProgress(3);
        } else {
            completeBtn.classList.remove('active');
        }
    }
}

async function completeSignup() {
    if (!signupToken) {
        showError('Signup session expired. Please start over.');
        return;
    }
    
    const btn = document.getElementById('complete-signup');
    if (!btn) return;
    
    const emailOtp = document.getElementById('email-otp')?.value || '';
    const phoneOtp = document.getElementById('phone-otp')?.value || '';
    const phone = document.getElementById('phone')?.value;
    
    // Require email OTP at minimum
    if (!emailOtp) {
        showError('Please enter the OTP sent to your email');
        return;
    }
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Creating Account...';
    
    try {
        const response = await fetch(API_BASE_URL + '/api/signup-complete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                signupToken: signupToken,
                emailOTP: emailOtp,
                phoneOTP: phoneOtp,
                emailVerified: emailVerified,
                phoneVerified: phoneVerified
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showToast('success', 'Account created successfully! Verify email and login.');
            setTimeout(() => {
                window.location.href = '/login';
            }, 2000);
        } else {
            showError(data.error || 'Failed to create account');
            btn.disabled = false;
            btn.innerHTML = '<span>Complete Registration</span><i class="fa fa-check"></i>';
        }
    } catch (error) {
        console.error('Complete signup error:', error);
        showError('An error occurred');
        btn.disabled = false;
        btn.innerHTML = '<span>Complete Registration</span><i class="fa fa-check"></i>';
    }
}

function updateProgress(step) {
    for (let i = 1; i <= 3; i++) {
        const stepEl = document.getElementById('step-' + i);
        if (stepEl) {
            const stepNumber = stepEl.querySelector('.step-number');
            if (i <= step) {
                stepEl.classList.add('active', 'completed');
                if (i < step && stepNumber) {
                    stepNumber.innerHTML = '<i class="fa fa-check"></i>';
                }
            } else {
                stepEl.classList.remove('active', 'completed');
                if (stepNumber) {
                    stepNumber.textContent = i;
                }
            }
        }
    }
}

// ==================== LOGIN FUNCTIONS ====================

async function handleLogin(e) {
    // Always prevent default
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    if (loginSubmitting) return;
    
    console.log('handleLogin called');
    const emailInput = document.getElementById('login-email') || document.getElementById('email');
    const email = emailInput?.value;
    const passwordInput = document.getElementById('login-password') || document.getElementById('password');
    const password = passwordInput?.value;
    const rememberCheckbox = document.getElementById('remember');
    const remember = rememberCheckbox ? rememberCheckbox.checked : true;
    const errorMessage = document.getElementById('error-message');
    // Get button by ID directly - more reliable
    const submitBtn = document.getElementById('login-btn');
    
    // Validate required fields
    if (!email || !password) {
        showError('Please enter email and password');
        return;
    }
    
    // Show loading state
    loginSubmitting = true;
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Signing In...';
    }
    if (errorMessage) {
        errorMessage.style.display = 'none';
    }
    
    try {
        const response = await fetch(API_BASE_URL + '/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email, password, remember })
        });
        const rawText = await response.text();
        let data = {};
        try {
            data = rawText ? JSON.parse(rawText) : {};
        } catch (parseError) {
            data = { error: rawText || 'Unexpected server response' };
        }
        
        if (response.ok) {
            // Success - redirect to dashboard
            showToast('success', 'Login successful! Redirecting...');
            setTimeout(() => {
                window.location.href = '/dashboard';
            }, 1500);
            return;
        } else {
            showError(data.error || 'Invalid credentials. Please try again.', errorMessage?.id || 'error-message');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<span>Sign In</span><i class="fa fa-arrow-right"></i>';
            }
        }
    } catch (error) {
        console.error('Login error:', error);
        showError('An error occurred. Please try again.', errorMessage?.id || 'error-message');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<span>Sign In</span><i class="fa fa-arrow-right"></i>';
        }
    } finally {
        loginSubmitting = false;
    }
}

// ==================== FORGOT PASSWORD FUNCTIONS ====================

// Direct click handler for the Send Reset Link button
function handleForgotPasswordClick() {
    console.log('handleForgotPasswordClick called');
    handleForgotPassword({ 
        preventDefault: function() {}, 
        stopPropagation: function() {}, 
        target: document.getElementById('forgot-password-form'),
        target: { querySelector: function(sel) { return document.querySelector(sel); } }
    });
}

// Direct click handler for the Login button
function handleLoginClick() {
    console.log('handleLoginClick called');
    handleLogin({ 
        preventDefault: function() {}, 
        stopPropagation: function() {}, 
        target: document.getElementById('login-form'),
        target: { querySelector: function(sel) { return document.querySelector(sel); } }
    });
}

// Direct click handler for the Signup button
function handleSignupClick() {
    console.log('handleSignupClick called');
    handleSignup({ 
        preventDefault: function() {}, 
        stopPropagation: function() {}, 
        target: document.getElementById('signup-form'),
        target: { querySelector: function(sel) { return document.querySelector(sel); } }
    });
}

async function handleForgotPassword(e) {
    if (e) e.preventDefault();

    // Find email input - check multiple possible IDs
    const emailInput = document.getElementById('forgot-email') ||
                       document.getElementById('email') ||
                       document.querySelector('input[name="email"]');
    const email = emailInput?.value;
    const errorMessage = document.getElementById('error-message');
    // Get button by ID directly - more reliable
    const submitBtn = document.getElementById('submit-btn');

    if (!email) {
        showError('Please enter your email address');
        return;
    }

    // Validate email format
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
        showError('Please enter a valid email address');
        return;
    }

    // Show loading state
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Verifying...';
    }
    if (errorMessage) {
        errorMessage.style.display = 'none';
    }

    try {
        // First verify the email exists in our system
        const checkResponse = await fetch(API_BASE_URL + '/api/check-email', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email })
        });

        const checkData = await checkResponse.json();

        if (!checkResponse.ok || !checkData.exists) {
            showError('No account found with this email address', errorMessage?.id || 'error-message');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fa fa-paper-plane"></i> Send Reset Link';
            }
            return;
        }

        // Email exists - directly show password reset form inline
        const authForm = document.querySelector('.auth-form');
        if (authForm) {
            authForm.innerHTML = `
                <div style="text-align: center; margin-bottom: 20px;">
                    <i class="fa fa-lock" style="font-size: 48px; color: #667eea; margin-bottom: 16px;"></i>
                    <h2 style="margin-bottom: 8px;">Reset Your Password</h2>
                    <p style="color: #666; font-size: 14px;">Enter a new password for ${email}</p>
                </div>
                
                <div class="form-group">
                    <label for="new-password"><i class="fa fa-lock"></i> New Password</label>
                    <input type="password" id="new-password" placeholder="Enter new password" required minlength="6">
                </div>
                
                <div class="form-group">
                    <label for="confirm-password"><i class="fa fa-lock"></i> Confirm Password</label>
                    <input type="password" id="confirm-password" placeholder="Confirm new password" required>
                </div>
                
                <div id="reset-error-message" class="error-message" style="display: none;"></div>
                
                <button type="button" class="auth-btn" id="reset-password-btn" onclick="handleDirectPasswordReset('${email}')">
                    <i class="fa fa-key"></i> Reset Password
                </button>
                
                <div style="text-align: center; margin-top: 16px;">
                    <a href="/login" style="color: #667eea; text-decoration: none; font-size: 14px;">
                        <i class="fa fa-arrow-left"></i> Back to Login
                    </a>
                </div>
            `;
        }

        showToast('success', 'Email verified! Please enter your new password.');
    } catch (error) {
        console.error('Forgot password error:', error);
        showError('An error occurred. Please try again.', errorMessage?.id || 'error-message');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fa fa-paper-plane"></i> Send Reset Link';
        }
    }
}

// Direct password reset without email - shows form inline
async function handleDirectPasswordReset(email) {
    const newPassword = document.getElementById('new-password')?.value;
    const confirmPassword = document.getElementById('confirm-password')?.value;
    const errorMessage = document.getElementById('reset-error-message');
    const submitBtn = document.getElementById('reset-password-btn');

    if (!newPassword || !confirmPassword) {
        showError('Please enter both password fields', 'reset-error-message');
        return;
    }

    if (newPassword !== confirmPassword) {
        showError('Passwords do not match', 'reset-error-message');
        return;
    }

    if (newPassword.length < 6) {
        showError('Password must be at least 6 characters', 'reset-error-message');
        return;
    }

    // Show loading state
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Resetting...';
    }
    if (errorMessage) {
        errorMessage.style.display = 'none';
    }

    try {
        const response = await fetch(API_BASE_URL + '/api/direct-reset-password', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email, password: newPassword })
        });

        const data = await response.json();

        if (response.ok) {
            // Show success message
            const authForm = document.querySelector('.auth-form');
            if (authForm) {
                authForm.innerHTML = `
                    <div style="text-align: center; padding: 40px 20px;">
                        <i class="fa fa-check-circle" style="font-size: 64px; color: #4caf50; margin-bottom: 20px;"></i>
                        <h2 style="margin-bottom: 12px;">Password Reset Successful!</h2>
                        <p style="color: #666; margin-bottom: 24px;">Your password has been changed successfully.</p>
                        <a href="/login" class="auth-btn" style="display: inline-block; text-decoration: none;">
                            <i class="fa fa-sign-in"></i> Sign In with New Password
                        </a>
                    </div>
                `;
            }
            showToast('success', 'Password reset successful!');
        } else {
            showError(data.error || 'Failed to reset password', 'reset-error-message');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fa fa-key"></i> Reset Password';
            }
        }
    } catch (error) {
        console.error('Direct password reset error:', error);
        showError('An error occurred. Please try again.', 'reset-error-message');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fa fa-key"></i> Reset Password';
        }
    }
}

async function handleResetPassword(e) {
    if (e) e.preventDefault();
    
    const passwordInput = document.getElementById('reset-password');
    const confirmPasswordInput = document.getElementById('reset-confirm-password');
    const password = passwordInput?.value;
    const confirmPassword = confirmPasswordInput?.value;
    const errorMessage = document.getElementById('error-message');
    const successMessage = document.getElementById('success-message');
    // Get button by ID directly - more reliable
    const submitBtn = document.getElementById('reset-password-btn');
    
    // Validate passwords
    if (!password || !confirmPassword) {
        showError('Please enter both passwords');
        return;
    }
    
    if (password !== confirmPassword) {
        showError('Passwords do not match');
        return;
    }
    
    if (password.length < 6) {
        showError('Password must be at least 6 characters');
        return;
    }
    
    // Show loading state
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Resetting...';
    }
    if (errorMessage) {
        errorMessage.style.display = 'none';
    }
    if (successMessage) {
        successMessage.style.display = 'none';
    }
    
    // Get reset token from URL
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');
    
    if (!token) {
        showError('Invalid reset link. Please request a new password reset.', errorMessage?.id || 'error-message');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<span>Reset Password</span><i class="fa fa-lock"></i>';
        }
        return;
    }
    
    try {
        const response = await fetch(API_BASE_URL + '/api/reset-password', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ token, password })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            if (successMessage) {
                successMessage.innerHTML = '<i class="fa fa-check-circle"></i><span>' + data.message + '</span>';
                successMessage.style.display = 'flex';
            }
            if (submitBtn) {
                submitBtn.innerHTML = '<i class="fa fa-check"></i> Reset!';
            }
            // Redirect to login after 2 seconds
            setTimeout(() => {
                window.location.href = '/login';
            }, 2000);
        } else {
            showError(data.error || 'Failed to reset password', errorMessage?.id || 'error-message');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<span>Reset Password</span><i class="fa fa-lock"></i>';
            }
        }
    } catch (error) {
        console.error('Reset password error:', error);
        showError('An error occurred. Please try again.', errorMessage?.id || 'error-message');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<span>Reset Password</span><i class="fa fa-lock"></i>';
        }
    }
}

// ==================== UTILITY FUNCTIONS ====================

function showError(message, elementId = 'error-message') {
    const errorMessage = document.getElementById(elementId);
    if (errorMessage) {
        errorMessage.innerHTML = '<i class="fa fa-exclamation-circle"></i><span>' + message + '</span>';
        errorMessage.style.display = 'flex';
    } else {
        console.error('Error message element not found:', elementId);
    }
}

function hideError(elementId = 'error-message') {
    const errorMessage = document.getElementById(elementId);
    if (errorMessage) {
        errorMessage.style.display = 'none';
    }
}

function showToast(type, message) {
    // Handle backward compatibility: if only one argument is passed, treat it as message with type 'success'
    if (typeof type === 'string' && typeof message === 'undefined') {
        message = type;
        type = 'success';
    }
    
    // Remove any existing toast
    const existingToast = document.querySelector('.toast-notification');
    if (existingToast) {
        existingToast.remove();
    }
    
    // Create toast element
    const toast = document.createElement('div');
    toast.className = 'toast-notification';
    toast.innerHTML = `
        <div class="toast-icon ${type}">
            <i class="fa fa-${type === 'success' ? 'check' : 'times'}"></i>
        </div>
        <div class="toast-content">
            <strong>${type === 'success' ? 'Success!' : 'Error!'}</strong>
            <span>${message}</span>
        </div>
    `;
    
    // Add styles if not exists
    if (!document.getElementById('toast-styles')) {
        const styles = document.createElement('style');
        styles.id = 'toast-styles';
        styles.textContent = `
            .toast-notification {
                position: fixed;
                top: 24px;
                right: 24px;
                background: #1d1d1f;
                color: white;
                padding: 16px 24px;
                border-radius: 14px;
                display: flex;
                align-items: center;
                gap: 16px;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
                transform: translateX(120%);
                transition: transform 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                z-index: 1000;
            }
            .toast-notification.active {
                transform: translateX(0);
            }
            .toast-icon {
                width: 44px;
                height: 44px;
                border-radius: 12px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 20px;
            }
            .toast-icon.success {
                background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
            }
            .toast-icon.error {
                background: linear-gradient(135deg, #cb2d3e 0%, #ef473a 100%);
            }
            .toast-icon.info {
                background: linear-gradient(135deg, #2193b0 0%, #6dd5ed 100%);
            }
            .toast-content {
                display: flex;
                flex-direction: column;
            }
            .toast-content strong {
                margin-bottom: 2px;
            }
            .toast-content span {
                font-size: 0.9rem;
                opacity: 0.9;
            }
        `;
        document.head.appendChild(styles);
    }
    
    document.body.appendChild(toast);
    
    // Show toast
    setTimeout(() => {
        toast.classList.add('active');
    }, 10);
    
    // Hide toast after 4 seconds
    setTimeout(() => {
        toast.classList.remove('active');
        setTimeout(() => {
            toast.remove();
        }, 400);
    }, 4000);
}
