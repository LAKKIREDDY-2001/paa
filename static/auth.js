// Auth JavaScript - Handles Signup, Login, and Password Reset

let signupToken = null;
let emailVerified = false;
let phoneVerified = false;

// Backend API configuration
// For local development: use empty string or 'http://localhost:8081'
// For production/preview: set to your deployed backend URL
// Auto-detect from current page to avoid CORS issues
const getApiBaseUrl = () => {
    const currentUrl = window.location.origin;
    // Use current page origin if on localhost/127.0.0.1
    if (currentUrl.includes('localhost') || currentUrl.includes('127.0.0.1')) {
        return currentUrl;
    }
    // For network IP access, use localhost:8081 as fallback
    return 'http://localhost:8081';
};
const API_BASE_URL = getApiBaseUrl();

document.addEventListener('DOMContentLoaded', () => {
    const signupForm = document.getElementById('signup-form');
    const loginForm = document.getElementById('login-form');
    const forgotPasswordForm = document.getElementById('forgot-password-form');
    const resetPasswordForm = document.getElementById('reset-password-form');
    const forgotForm = document.getElementById('forgot-form'); // Legacy ID support

    if (signupForm) {
        signupForm.addEventListener('submit', handleSignup);
        setupSignupOTPEvents();
    }

    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }

    // Handle forgot password - check both IDs for compatibility
    if (forgotPasswordForm) {
        forgotPasswordForm.addEventListener('submit', handleForgotPassword);
    } else if (forgotForm) {
        // Legacy support for forgot-form ID
        forgotForm.addEventListener('submit', handleForgotPassword);
    }

    if (resetPasswordForm) {
        resetPasswordForm.addEventListener('submit', handleResetPassword);
    }

    initTilt();
});

function initTilt() {
    const tiltRoots = document.querySelectorAll('.tilt-root');
    if (!tiltRoots.length) return;
    if (window.matchMedia('(hover: none)').matches) return;

    tiltRoots.forEach((root) => {
        let rect = null;
        const maxTilt = parseFloat(root.dataset.tilt || '7');

        const handleMove = (event) => {
            if (!rect) rect = root.getBoundingClientRect();
            const x = (event.clientX - rect.left) / rect.width;
            const y = (event.clientY - rect.top) / rect.height;
            const tiltX = (0.5 - y) * maxTilt;
            const tiltY = (x - 0.5) * maxTilt;
            root.classList.add('tilt-active');
            root.style.setProperty('--tilt-x', tiltX.toFixed(2) + 'deg');
            root.style.setProperty('--tilt-y', tiltY.toFixed(2) + 'deg');
        };

        const handleLeave = () => {
            root.classList.remove('tilt-active');
            root.style.setProperty('--tilt-x', '0deg');
            root.style.setProperty('--tilt-y', '0deg');
            rect = null;
        };

        root.addEventListener('mousemove', handleMove);
        root.addEventListener('mouseleave', handleLeave);
    });
}

// ==================== SIGNUP FUNCTIONS ====================

async function handleSignup(e) {
    e.preventDefault();
    
    const username = document.getElementById('username')?.value;
    const email = document.getElementById('email')?.value;
    const phone = document.getElementById('phone')?.value;
    const password = document.getElementById('password')?.value;
    const confirmPassword = document.getElementById('confirm_password')?.value;
    const errorMessage = document.getElementById('error-message');
    const submitBtn = e.target?.querySelector('button[type="submit"]');
    
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
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Sending OTP...';
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
            // Store signup token and show verification section
            signupToken = data.signupToken;
            showVerificationSection(email, phone);
        } else {
            showError(data.error || 'Failed to send OTP. Please try again.');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<span>Continue to Verification</span><i class="fa fa-arrow-right"></i>';
            }
        }
    } catch (error) {
        console.error('Signup error:', error);
        showError('An error occurred. Please try again.');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<span>Continue to Verification</span><i class="fa fa-arrow-right"></i>';
        }
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
    e.preventDefault();
    
    // Get email and password
    const emailInput = document.getElementById('login-email') || document.getElementById('email');
    const email = emailInput?.value;
    const passwordInput = document.getElementById('login-password') || document.getElementById('password');
    const password = passwordInput?.value;
    const errorMessage = document.getElementById('error-message');
    const submitBtn = document.getElementById('login-btn');
    
    // Validate required fields
    if (!email || !password) {
        showError('Please enter email and password');
        return;
    }
    
    // Show loading state
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
            body: JSON.stringify({ email, password })
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
    }
}

// ==================== FORGOT PASSWORD FUNCTIONS ====================

async function handleForgotPassword(e) {
    e.preventDefault();

    // Find email input - check multiple possible IDs
    const emailInput = document.getElementById('forgot-email') ||
                       document.getElementById('email') ||
                       document.querySelector('input[name="email"]');
    const email = emailInput?.value;
    const errorMessage = document.getElementById('error-message');
    const successMessage = document.getElementById('success-message');
    const submitBtn = e.target?.querySelector('button[type="submit"]');

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
        submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Sending...';
    }
    if (errorMessage) {
        errorMessage.style.display = 'none';
    }
    if (successMessage) {
        successMessage.style.display = 'none';
    }

    try {
        const response = await fetch(API_BASE_URL + '/api/forgot-password', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email })
        });

        const data = await response.json();

        if (response.ok) {
            // Show success message inline (works on all pages)
            const authForm = document.querySelector('.auth-form');
            if (authForm) {
                authForm.innerHTML = `
                    <div style="text-align: center; padding: 20px 0;">
                        <i class="fa fa-check-circle" style="font-size: 64px; color: #4caf50; margin-bottom: 20px;"></i>
                        <h2 style="margin-bottom: 12px;">Check your email</h2>
                        <p style="color: #666; margin-bottom: 24px;">We've sent password reset instructions to ${email}</p>
                        <p style="color: #888; font-size: 13px; margin-bottom: 24px;">Click the link in the email to reset your password. The link expires in 30 minutes.</p>
                        <a href="/login" class="auth-btn" style="display: inline-block; text-decoration: none;">
                            <i class="fa fa-arrow-left"></i> Back to Login
                        </a>
                    </div>
                `;
            }

            // Also show toast notification
            showToast('success', 'Password reset instructions sent!');
        } else {
            showError(data.error || 'Failed to send reset link', errorMessage?.id || 'error-message');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fa fa-paper-plane"></i> Send Reset Link';
            }
        }
    } catch (error) {
        console.error('Forgot password error:', error);
        showError('An error occurred. Please try again.', errorMessage?.id || 'error-message');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fa fa-paper-plane"></i> Send Reset Link';
        }
    }
}

async function handleResetPassword(e) {
    e.preventDefault();
    
    const passwordInput = document.getElementById('reset-password');
    const confirmPasswordInput = document.getElementById('reset-confirm-password');
    const password = passwordInput?.value;
    const confirmPassword = confirmPasswordInput?.value;
    const errorMessage = document.getElementById('error-message');
    const successMessage = document.getElementById('success-message');
    const submitBtn = e.target?.querySelector('button[type="submit"]');
    
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
