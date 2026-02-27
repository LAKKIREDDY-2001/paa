import os
import re
import sqlite3
import random
import string
import json
import secrets
import time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, session, redirect, url_for, render_template, send_from_directory, make_response
from flask_cors import CORS
try:
    from flask_session import Session
except ImportError:
    Session = None
from werkzeug.middleware.proxy_fix import ProxyFix
import requests
from bs4 import BeautifulSoup
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=3)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

IS_PRODUCTION = os.environ.get('APP_ENV', '').lower() in ['production', 'prod'] or \
    os.environ.get('FLASK_ENV', '').lower() == 'production'

# Use a consistent secret key - generate once and store, or use environment variable
# This prevents sessions from being invalidated on app restart
app.secret_key = os.environ.get('SECRET_KEY', 'price-alerter-secret-key-2024-change-in-production')
if IS_PRODUCTION and not os.environ.get('SECRET_KEY'):
    print("WARNING: SECRET_KEY is not set in production. Set SECRET_KEY environment variable.")

# Session configuration - optimized for persistent login
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Changed from 'Strict' for better compatibility
app.config['SESSION_COOKIE_SECURE'] = IS_PRODUCTION
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_TYPE'] = os.environ.get('SESSION_TYPE', 'filesystem')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)  # 30 days persistent session
app.config['SESSION_COOKIE_NAME'] = 'price_alerter_session'  # Custom session cookie name
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'price_alerter:'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(app, supports_credentials=True, origins="*")

# Enable permanent sessions by default
@app.before_request
def make_session_permanent():
    # Only set permanent if not already set
    if not session.get('permanent'):
        session.permanent = True


def normalize_email(email):
    if not email:
        return ""
    return email.strip().lower()

def resolve_database_path():
    # Check for environment variable first - this takes priority
    configured_path = os.environ.get('DATABASE_PATH')
    if configured_path:
        db_dir = os.path.dirname(configured_path) or '.'
        try:
            os.makedirs(db_dir, exist_ok=True)
            if os.access(db_dir, os.W_OK):
                print(f"Using database path from environment: {configured_path}")
                return configured_path
            print(f"Configured DATABASE_PATH directory is not writable: {db_dir}")
        except Exception as e:
            print(f"Could not use DATABASE_PATH={configured_path}: {e}")

    def can_write_dir(path):
        return os.path.isdir(path) and os.access(path, os.W_OK | os.X_OK)

    # Render/host-provided persistent mount candidates.
    # Only use directories that already exist and are writable.
    persistent_dirs = [
        os.environ.get('RENDER_DISK_PATH', ''),
        os.environ.get('RENDER_DISK_MOUNT_PATH', ''),
        '/var/data',
        '/data'
    ]
    persistent_dirs = [p for p in persistent_dirs if p]

    for persist_dir in persistent_dirs:
        if can_write_dir(persist_dir):
            db_path = os.path.join(persist_dir, 'database.db')
            print(f"Using persistent directory: {persist_dir}")
            return db_path

    # For local development - use project directory.
    project_dir = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(project_dir, 'database.db')
    if (not IS_PRODUCTION) and os.access(project_dir, os.W_OK):
        print(f"Using project directory database: {local_path}")
        return local_path

    # Last resort: use tmp (ephemeral).
    print("INFO: Using /tmp database path (ephemeral).")
    print("INFO: For persistent data on Render, attach a disk and set DATABASE_PATH=/var/data/database.db.")
    return '/tmp/database.db'

DATABASE = resolve_database_path()
print(f"Using SQLite database: {DATABASE}")

if app.config.get('SESSION_TYPE') == 'filesystem':
    def resolve_session_file_dir():
        default_session_dir = os.path.join(os.path.dirname(DATABASE), 'flask_session')
        configured_session_dir = os.environ.get('SESSION_FILE_DIR', '').strip()

        candidates = []
        if configured_session_dir:
            candidates.append(configured_session_dir)
        candidates.append(default_session_dir)
        candidates.append('/tmp/flask_session')

        for candidate in candidates:
            try:
                # If directory exists, validate permissions.
                if os.path.isdir(candidate):
                    if os.access(candidate, os.W_OK | os.X_OK):
                        return candidate
                    continue

                # Create only when parent directory is writable.
                parent = os.path.dirname(candidate) or '.'
                if os.path.isdir(parent) and os.access(parent, os.W_OK | os.X_OK):
                    os.makedirs(candidate, exist_ok=True)
                    if os.access(candidate, os.W_OK | os.X_OK):
                        return candidate
            except Exception:
                continue

        # Guaranteed local fallback.
        local_tmp = '/tmp/flask_session'
        os.makedirs(local_tmp, exist_ok=True)
        return local_tmp

    app.config['SESSION_FILE_DIR'] = resolve_session_file_dir()
    print(f"Using session file directory: {app.config['SESSION_FILE_DIR']}")

# Initialize Flask-Session when available; fallback to Flask signed cookies.
if Session is not None:
    Session(app)
else:
    app.config.pop('SESSION_TYPE', None)
    print("WARNING: flask_session not installed; using default Flask session backend.")

# Email Configuration
def load_email_config():
    config = {
        'enabled': False,
        'smtp_server': 'smtp.gmail.com',
        'smtp_port': 587,
        'smtp_email': '',
        'smtp_password': '',
        'from_name': 'AI Price Alert',
        'provider': 'gmail'
    }
    config_file = 'email_config.json'
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception as e:
            print(f"Error loading email config: {e}")
    if os.environ.get('SMTP_ENABLED'):
        config['enabled'] = os.environ.get('SMTP_ENABLED').lower() == 'true'
    if os.environ.get('SMTP_SERVER'):
        config['smtp_server'] = os.environ.get('SMTP_SERVER')
    if os.environ.get('SMTP_PORT'):
        config['smtp_port'] = int(os.environ.get('SMTP_PORT'))
    if os.environ.get('SMTP_EMAIL'):
        config['smtp_email'] = os.environ.get('SMTP_EMAIL')
    if os.environ.get('SMTP_PASSWORD'):
        config['smtp_password'] = os.environ.get('SMTP_PASSWORD')
    if os.environ.get('SMTP_FROM_NAME'):
        config['from_name'] = os.environ.get('SMTP_FROM_NAME')
    return config

EMAIL_CONFIG = load_email_config()

# Load other configs
def load_json_config(filename, defaults):
    config = defaults.copy()
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
    return config

TWILIO_CONFIG = load_json_config('twilio_config.json', {
    'enabled': False, 'account_sid': '', 'auth_token': '', 'phone_number': ''
})

TELEGRAM_CONFIG = load_json_config('telegram_config.json', {
    'enabled': False, 'bot_token': '', 'webhook_url': '', 'bot_username': ''
})

WHATSAPP_CONFIG = load_json_config('whatsapp_config.json', {
    'enabled': False, 'twilio_account_sid': '', 'twilio_auth_token': '',
    'twilio_whatsapp_number': '+14155238886', 'from_name': 'AI Price Alert'
})

# ==================== EMAIL FUNCTIONS ====================

def send_mail(to_email, subject, html_body, text_body=None):
    if not EMAIL_CONFIG['enabled']:
        print(f"\n{'='*60}")
        print("📧 EMAIL SENT - DEMO MODE")
        print(f"{'='*60}")
        print(f"To: {to_email}")
        print(f"Subject: {subject}")
        print(f"{'='*60}\n")
        return True
    
    if not EMAIL_CONFIG.get('smtp_email') or not EMAIL_CONFIG.get('smtp_password'):
        print(f"Email not configured - skipping send to {to_email}")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{EMAIL_CONFIG['from_name']} <{EMAIL_CONFIG['smtp_email']}>"
        msg['To'] = to_email
        if text_body:
            text_part = MIMEText(text_body, 'plain')
            msg.attach(text_part)
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)
        smtp_port = EMAIL_CONFIG.get('smtp_port', 587)
        use_tls = EMAIL_CONFIG.get('use_tls', True)
        if use_tls:
            with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(EMAIL_CONFIG['smtp_email'], EMAIL_CONFIG['smtp_password'])
                server.send_message(msg)
        else:
            with smtplib.SMTP_SSL(EMAIL_CONFIG['smtp_server'], smtp_port, timeout=30) as server:
                server.login(EMAIL_CONFIG['smtp_email'], EMAIL_CONFIG['smtp_password'])
                server.send_message(msg)
        print(f"✓ Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"✗ Error sending email to {to_email}: {e}")
        return False

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def send_email_otp(email, otp, purpose="verification"):
    if EMAIL_CONFIG['enabled']:
        try:
            msg = MIMEText(f'Your AI Price Alert {purpose} code is: {otp}\n\nThis code expires in 10 minutes.')
            msg['Subject'] = f'AI Price Alert - {purpose.title()} Code'
            msg['From'] = f"{EMAIL_CONFIG['from_name']} <{EMAIL_CONFIG['smtp_email']}>"
            msg['To'] = email
            with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'], timeout=30) as server:
                server.starttls()
                server.login(EMAIL_CONFIG['smtp_email'], EMAIL_CONFIG['smtp_password'])
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"Email send error: {e}")
            return False
    else:
        print(f"\n{'='*50}")
        print(f"📧 EMAIL OTP ({purpose.upper()}) - DEMO MODE")
        print(f"{'='*50}")
        print(f"To: {email}")
        print(f"OTP: {otp}")
        print(f"{'='*50}\n")
        return True

def send_password_reset_email(email, reset_token):
    host_url = EMAIL_CONFIG.get('host_url', 'http://localhost:8081')
    reset_link = f"{host_url}/reset-password?token={reset_token}"
    email_content = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>Password Reset</title></head>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h1 style="color: #1a1a2e;">Password Reset Request</h1>
        <p>You requested to reset your password for AI Price Alert.</p>
        <p>Click the button below to reset your password:</p>
        <a href="{reset_link}" style="display: inline-block; padding: 16px 32px; background: linear-gradient(135deg, #667eea, #764ba2); color: white; text-decoration: none; border-radius: 8px; font-weight: bold;">Reset Password</a>
        <p style="color: #666; margin-top: 20px;">This link expires in 30 minutes.</p>
    </body>
    </html>
    '''
    return send_mail(to_email=email, subject='AI Price Alert - Password Reset', html_body=email_content)


def send_price_target_reached_email(to_email, product_name, product_url, current_price, target_price, currency_symbol):
    product_display = product_name or "Product"
    current_str = f"{currency_symbol}{current_price:.2f}"
    target_str = f"{currency_symbol}{target_price:.2f}"
    html_body = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>Price Target Reached</title></head>
    <body style="font-family: Arial, sans-serif; max-width: 640px; margin: 0 auto; padding: 20px;">
        <h2 style="color:#0f172a; margin-bottom: 12px;">Your price alert has triggered!</h2>
        <p style="color:#334155;">Great news. A tracked item reached your target price.</p>
        <div style="border:1px solid #e2e8f0; border-radius:12px; padding:16px; background:#f8fafc;">
            <p style="margin:0 0 8px 0;"><strong>Product:</strong> {product_display}</p>
            <p style="margin:0 0 8px 0;"><strong>Current price:</strong> {current_str}</p>
            <p style="margin:0;"><strong>Your target:</strong> {target_str}</p>
        </div>
        <p style="margin-top:16px;">
            <a href="{product_url}" style="display:inline-block; padding:12px 18px; background:#0ea5e9; color:#fff; text-decoration:none; border-radius:8px;">
                View Product
            </a>
        </p>
        <p style="color:#64748b; font-size:12px; margin-top:18px;">You received this because you created a tracker on AI Price Alert.</p>
    </body>
    </html>
    '''
    return send_mail(
        to_email=to_email,
        subject=f"Price dropped: {product_display}",
        html_body=html_body
    )

# ==================== DATABASE ====================

def init_db():
    """Initialize database - uses the already resolved DATABASE path"""
    try:
        conn = sqlite3.connect(DATABASE)
    except sqlite3.OperationalError as e:
        # Log the error but don't change the database path
        print(f"Database connection error: {e}")
        # Try once more with the same path before failing
        conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            phone TEXT,
            email_verified INTEGER DEFAULT 0,
            phone_verified INTEGER DEFAULT 0,
            two_factor_enabled INTEGER DEFAULT 0,
            two_factor_method TEXT DEFAULT 'none',
            remember_token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS otp_verification (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            email TEXT,
            phone TEXT,
            email_otp TEXT,
            phone_otp TEXT,
            email_otp_expiry TIMESTAMP,
            phone_otp_expiry TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reset_token TEXT NOT NULL UNIQUE,
            reset_token_expiry TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_signups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signup_token TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            email TEXT NOT NULL,
            password TEXT NOT NULL,
            phone TEXT,
            email_otp TEXT,
            email_otp_expiry TIMESTAMP,
            phone_otp TEXT,
            phone_otp_expiry TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trackers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            product_name TEXT,
            current_price REAL NOT NULL,
            target_price REAL NOT NULL,
            currency TEXT,
            currency_symbol TEXT,
            target_reached_notified INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # Backward-compatible migration for existing databases.
    cursor.execute("PRAGMA table_info(trackers)")
    tracker_columns = [row[1] for row in cursor.fetchall()]
    if 'target_reached_notified' not in tracker_columns:
        cursor.execute("ALTER TABLE trackers ADD COLUMN target_reached_notified INTEGER DEFAULT 0")
    
    conn.commit()
    conn.close()

# ==================== ROUTES ====================

@app.route('/')
def root():
    """Home page with SEO content"""
    return render_template('home.html')

@app.route('/home')
def home():
    """Home page alias"""
    return render_template('home.html')

@app.route('/amp')
@app.route('/amp/home')
def home_amp():
    """AMP home page"""
    return render_template('home_amp.html')

@app.route('/about')
def about():
    """About page with SEO content"""
    return render_template('about.html')

@app.route('/contact')
def contact():
    """Contact page with SEO content"""
    return render_template('contact.html')

@app.route('/privacy')
def privacy():
    """Privacy policy page with SEO content"""
    return render_template('privacy.html')

@app.route('/terms')
def terms():
    """Terms of service page with SEO content"""
    return render_template('terms.html')

@app.route('/blog')
def blog():
    """Blog listing page"""
    return render_template('blog.html')

@app.route('/blog/how-to-track-product-prices-online')
def blog_track_prices():
    """Blog post 1"""
    return render_template('blog_track_prices.html')

@app.route('/blog/best-price-alert-tools-india')
def blog_best_tools():
    """Blog post 2"""
    return render_template('blog_best_tools.html')

@app.route('/blog/save-money-price-trackers')
def blog_save_money():
    """Blog post 3"""
    return render_template('blog_save_money.html')

@app.route('/blog/amazon-price-history')
def blog_amazon_history():
    """Blog post 4"""
    return render_template('blog_amazon_history.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """Signup page - direct account creation"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Invalid request body"}), 400
        username = (data.get('username') or '').strip()
        email = normalize_email(data.get('email'))
        password = data.get('password')
        phone = (data.get('phone') or '').strip() or None

        if not all([username, email, password]):
            return jsonify({"error": "Missing data"}), 400

        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE lower(email) = ?", (email,))
            if cursor.fetchone():
                conn.close()
                return jsonify({"error": "Email already exists"}), 409

            # Generate remember token for lifetime login
            remember_token = secrets.token_urlsafe(32)
            
            cursor.execute("""
                INSERT INTO users (username, email, password, phone, email_verified, remember_token)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (username, email, generate_password_hash(password), phone, 1, remember_token))
            user_id = cursor.lastrowid
            conn.commit()
            conn.close()

            # DO NOT auto-login - user must sign in manually after signup
            # Create JSON response - redirect to login page after signup
            response_data = jsonify({
                "success": "Account created successfully!",
                "redirect": "/login"
            })

            print(f"New user signed up: {email}")
            return response_data, 201
        except Exception as e:
            print(f"Signup error: {e}")
            return jsonify({"error": "Signup failed. Please try again."}), 500

    return render_template('signup.html')

@app.route('/api/signup-complete', methods=['POST'])
def signup_complete():
    """Complete signup after OTP verification"""
    data = request.get_json()
    signup_token = data.get('signupToken')
    email_otp = data.get('emailOTP', '')
    
    if not signup_token:
        return jsonify({"error": "Signup token is required"}), 400
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pending_signups WHERE signup_token = ?", (signup_token,))
    pending = cursor.fetchone()
    
    if not pending:
        conn.close()
        return jsonify({"error": "Invalid or expired signup session. Please start over."}), 400
    
    signup_id, stored_token, username, email, password, phone, stored_email_otp, stored_email_otp_expiry, stored_phone_otp, stored_phone_otp_expiry, created_at = pending
    
    expiry = datetime.fromisoformat(created_at) + timedelta(minutes=30)
    if datetime.now() > expiry:
        cursor.execute("DELETE FROM pending_signups WHERE id = ?", (signup_id,))
        conn.commit()
        conn.close()
        return jsonify({"error": "Signup session expired. Please start over."}), 400
    
    # Verify email OTP
    email_verified = False
    if email_otp:
        if stored_email_otp and stored_email_otp == email_otp:
            if stored_email_otp_expiry:
                otp_expiry = datetime.fromisoformat(stored_email_otp_expiry)
                if datetime.now() > otp_expiry:
                    conn.close()
                    return jsonify({"error": "Email OTP has expired"}), 400
            email_verified = True
        else:
            conn.close()
            return jsonify({"error": "Invalid email OTP"}), 400
    
    if not email_verified:
        conn.close()
        return jsonify({"error": "Email verification is required", "requiresEmailVerification": True}), 400
    
    # Create the account
    try:
        cursor.execute("""
            INSERT INTO users (username, email, password, phone, email_verified)
            VALUES (?, ?, ?, ?, ?)
        """, (username, email, password, phone, 1))
        user_id = cursor.lastrowid
        
        cursor.execute("""
            INSERT INTO otp_verification (user_id, email, phone)
            VALUES (?, ?, ?)
        """, (user_id, email, phone))
        
        cursor.execute("DELETE FROM pending_signups WHERE id = ?", (signup_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Email already exists"}), 409
    finally:
        conn.close()
    
    return jsonify({
        "success": "Account created successfully!",
        "userId": user_id,
        "message": "Redirecting to login..."
    }), 201

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page - redirect to dashboard if already logged in"""
    # Check for remember_token cookie first - this is the key to persistent login
    remember_token = request.cookies.get('remember_token')
    
    # First try to restore session from remember token
    if remember_token and 'user_id' not in session:
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, email FROM users WHERE remember_token = ?", (remember_token,))
            user = cursor.fetchone()
            conn.close()
            if user:
                # Restore session
                session['user_id'] = user[0]
                session['username'] = user[1]
                session['email'] = user[2]
                session.permanent = True
                print(f"Session restored from remember_token for user: {user[1]}")
                return redirect(url_for('dashboard'))
        except Exception as e:
            print(f"Error restoring session from remember_token: {e}")
    
    # Also check if user is already in session
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        email = normalize_email(data.get('email'))
        password = data.get('password')
        remember = data.get('remember', True)

        if not email or not password:
            return jsonify({"error": "Missing data"}), 400
        
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE lower(email) = ?", (email,))
            user = cursor.fetchone()

            if user and check_password_hash(user[3], password):
                # Update last login timestamp
                cursor.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user[0],))
                
                # Generate remember token for persistent login (always, unless explicitly unchecked)
                token = secrets.token_urlsafe(32)
                cursor.execute("UPDATE users SET remember_token = ? WHERE id = ?", (token, user[0]))
                
                conn.commit()
                conn.close()
                
                # Set session
                session['user_id'] = user[0]
                session['username'] = user[1]
                session['email'] = user[2]
                session.permanent = True
                
                # Create JSON response properly
                response_data = jsonify({
                    "success": "Logged in successfully",
                    "redirect": "/dashboard"
                })
                
                # Set remember cookie (lasts 1 year)
                if remember:
                    response_data.set_cookie(
                        'remember_token',
                        token,
                        max_age=60 * 60 * 24 * 365,
                        httponly=True,
                        samesite='Lax',
                        secure=app.config.get('SESSION_COOKIE_SECURE', False)
                    )
                else:
                    response_data.delete_cookie('remember_token')
                
                print(f"User logged in: {email}, remember_token set: {token[:20]}...")
                return response_data, 200
            elif user and user[3] == password:
                # Backward compatibility: migrate legacy plaintext passwords to hashed format.
                hashed_password = generate_password_hash(password)
                cursor.execute("UPDATE users SET password = ?, last_login = CURRENT_TIMESTAMP WHERE id = ?", (hashed_password, user[0]))
                token = secrets.token_urlsafe(32)
                cursor.execute("UPDATE users SET remember_token = ? WHERE id = ?", (token, user[0]))
                conn.commit()
                conn.close()

                session['user_id'] = user[0]
                session['username'] = user[1]
                session['email'] = user[2]
                session.permanent = True

                response_data = jsonify({
                    "success": "Logged in successfully",
                    "redirect": "/dashboard"
                })

                if remember:
                    response_data.set_cookie(
                        'remember_token',
                        token,
                        max_age=60 * 60 * 24 * 365,
                        httponly=True,
                        samesite='Lax',
                        secure=app.config.get('SESSION_COOKIE_SECURE', False)
                    )
                else:
                    response_data.delete_cookie('remember_token')

                print(f"User logged in (legacy password migrated): {email}")
                return response_data, 200
            else:
                conn.close()
                return jsonify({"error": "Invalid credentials"}), 401
        except Exception as e:
            return jsonify({"error": f"Login failed: {str(e)}"}), 500
    
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    """Dashboard - requires login"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    remember_token = request.cookies.get('remember_token')

    if user_id or remember_token:
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            if user_id:
                cursor.execute("UPDATE users SET remember_token = NULL WHERE id = ?", (user_id,))
            elif remember_token:
                cursor.execute("UPDATE users SET remember_token = NULL WHERE remember_token = ?", (remember_token,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Logout token cleanup warning: {e}")

    session.clear()
    response = make_response(redirect(url_for('home')))
    response.delete_cookie('remember_token')
    response.delete_cookie(app.config.get('SESSION_COOKIE_NAME', 'session'))
    return response

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        data = request.get_json()
        email = normalize_email(data.get('email'))
        if not email:
            return jsonify({"error": "Email is required"}), 400
        
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE lower(email) = ?", (email,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            reset_token = secrets.token_urlsafe(32)
            expiry = datetime.now() + timedelta(minutes=30)
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO password_resets (user_id, reset_token, reset_token_expiry)
                VALUES (?, ?, ?)
            """, (user[0], reset_token, expiry.isoformat()))
            conn.commit()
            conn.close()
            send_password_reset_email(email, reset_token)
        
        return jsonify({"success": True, "message": "If an account exists, a reset link has been sent"}), 200
    
    return render_template('forgot-password.html')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    token = request.args.get('token')
    if not token:
        return render_template('error.html', error="Invalid reset link")
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, reset_token_expiry FROM password_resets WHERE reset_token = ?", (token,))
    reset_record = cursor.fetchone()
    
    if not reset_record:
        conn.close()
        return render_template('error.html', error="Invalid or expired reset link")
    
    expiry = datetime.fromisoformat(reset_record[1]) if reset_record[1] else None
    if expiry and datetime.now() > expiry:
        conn.close()
        return render_template('error.html', error="Reset link has expired")
    
    user_id = reset_record[0]
    
    if request.method == 'POST':
        data = request.get_json()
        new_password = data.get('password')
        if not new_password or len(new_password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        
        hashed = generate_password_hash(new_password)
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password = ? WHERE id = ?", (hashed, user_id))
        cursor.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Password reset successful"}), 200
    
    conn.close()
    return render_template('reset-password.html', token=token)

@app.route('/error')
def error_page():
    error = request.args.get('error', 'An unexpected error occurred')
    return render_template('error.html', error=error)

# ==================== API ROUTES ====================

@app.route('/health')
def health():
    """Simple health endpoint for Render liveness checks."""
    return "OK", 200

@app.route('/api/health')
def health_check():
    """Health check endpoint for debugging deployment issues"""
    import platform
    import sys
    
    health = {
        "status": "ok",
        "message": "Server is running",
        "database": "connected" if os.path.exists(DATABASE) else "not_found",
        "database_path": DATABASE,
        "python_version": sys.version,
        "platform": platform.platform(),
        "timestamp": datetime.now().isoformat()
    }
    
    # Try to connect to database
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        health["database_tables"] = [t[0] for t in tables]
        conn.close()
    except Exception as e:
        health["database_error"] = str(e)
    
    return jsonify(health)


@app.route('/api/self-heal/report', methods=['POST'])
def self_heal_report():
    """
    Lightweight runtime incident reporting endpoint used by the frontend self-heal layer.
    Never fails hard, never requires auth, and keeps payload bounded.
    """
    data = request.get_json(silent=True) or {}
    event_type = str(data.get('type', 'unknown'))[:64]
    message = str(data.get('message', ''))[:500]
    page = str(data.get('page', request.path))[:200]
    meta = data.get('meta', {})
    if not isinstance(meta, dict):
        meta = {}
    safe_meta = {}
    for k, v in list(meta.items())[:20]:
        safe_meta[str(k)[:64]] = str(v)[:200]

    user_id = session.get('user_id')
    print(f"[self-heal] type={event_type} page={page} user_id={user_id} message={message} meta={safe_meta}")
    return jsonify({"ok": True}), 200

@app.route('/api/user', methods=['GET'])
def get_user():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, phone FROM users WHERE id = ?", (session['user_id'],))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return jsonify({"id": user[0], "username": user[1], "email": user[2], "phone": user[3]})
    return jsonify({"error": "User not found"}), 404

@app.route('/api/trackers', methods=['GET', 'POST', 'PUT', 'DELETE'])
def trackers():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    if request.method == 'GET':
        cursor.execute("SELECT id, url, product_name, current_price, target_price, currency, currency_symbol, created_at FROM trackers WHERE user_id = ? ORDER BY created_at DESC", (session['user_id'],))
        trackers_list = cursor.fetchall()
        conn.close()
        result = []
        for t in trackers_list:
            result.append({
                "id": t[0], "url": t[1], "productName": t[2] or "Product",
                "currentPrice": t[3], "targetPrice": t[4],
                "currency": t[5], "currencySymbol": t[6], "createdAt": t[7]
            })
        return jsonify(result)
    
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        if not data.get('url'):
            conn.close()
            return jsonify({"error": "URL is required"}), 400

        cursor.execute("""
            INSERT INTO trackers (user_id, url, product_name, current_price, target_price, currency, currency_symbol)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session['user_id'], data.get('url'), data.get('productName'), 
              data.get('currentPrice'), data.get('targetPrice'), 
              data.get('currency', 'USD'), data.get('currencySymbol', '$')))
        tracker_id = cursor.lastrowid
        conn.commit()
        cursor.execute("SELECT created_at FROM trackers WHERE id = ?", (tracker_id,))
        created_at = cursor.fetchone()[0]
        conn.close()
        return jsonify({
            "id": tracker_id,
            "message": "Tracker created",
            "tracker": {
                "id": tracker_id,
                "url": data.get('url'),
                "productName": data.get('productName') or "Product",
                "currentPrice": data.get('currentPrice'),
                "targetPrice": data.get('targetPrice'),
                "currency": data.get('currency', 'USD'),
                "currencySymbol": data.get('currencySymbol', '$'),
                "createdAt": created_at
            }
        }), 201

    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
        tracker_id = data.get('id')
        if not tracker_id:
            conn.close()
            return jsonify({"error": "Tracker id is required"}), 400

        cursor.execute("""
            SELECT t.id, t.url, t.product_name, t.current_price, t.target_price, t.currency, t.currency_symbol,
                   COALESCE(t.target_reached_notified, 0), u.email
            FROM trackers t
            JOIN users u ON u.id = t.user_id
            WHERE t.id = ? AND t.user_id = ?
        """, (tracker_id, session['user_id']))
        existing = cursor.fetchone()
        if not existing:
            conn.close()
            return jsonify({"error": "Tracker not found"}), 404

        (
            _id, existing_url, existing_name, existing_current_price, existing_target_price,
            existing_currency, existing_currency_symbol, existing_notified, user_email
        ) = existing

        new_current_price = data.get('currentPrice')
        new_target_price = data.get('targetPrice')
        new_product_name = data.get('productName')
        new_currency = data.get('currency')
        new_currency_symbol = data.get('currencySymbol')

        final_current = float(new_current_price) if new_current_price is not None else float(existing_current_price)
        final_target = float(new_target_price) if new_target_price is not None else float(existing_target_price)
        final_name = new_product_name if new_product_name is not None else existing_name
        final_currency = new_currency if new_currency is not None else existing_currency
        final_symbol = new_currency_symbol if new_currency_symbol is not None else existing_currency_symbol

        was_below_or_equal = float(existing_current_price) <= float(existing_target_price)
        is_below_or_equal = final_current <= final_target
        should_notify_now = (not was_below_or_equal) and is_below_or_equal and int(existing_notified or 0) == 0
        reset_notified = (not is_below_or_equal)
        next_notified_value = 1 if should_notify_now else (0 if reset_notified else int(existing_notified or 0))

        cursor.execute("""
            UPDATE trackers
            SET current_price = ?,
                target_price = ?,
                product_name = ?,
                currency = ?,
                currency_symbol = ?,
                target_reached_notified = ?
            WHERE id = ? AND user_id = ?
        """, (
            final_current,
            final_target,
            final_name,
            final_currency,
            final_symbol,
            next_notified_value,
            tracker_id,
            session['user_id']
        ))
        updated_rows = cursor.rowcount
        conn.commit()
        conn.close()
        if updated_rows == 0:
            return jsonify({"error": "Tracker not found"}), 404

        if should_notify_now and user_email:
            try:
                send_price_target_reached_email(
                    to_email=user_email,
                    product_name=final_name,
                    product_url=existing_url,
                    current_price=final_current,
                    target_price=final_target,
                    currency_symbol=final_symbol or '$'
                )
            except Exception as e:
                print(f"Price alert email send failed for tracker {tracker_id}: {e}")

        return jsonify({"message": "Tracker updated"}), 200
    
    if request.method == 'DELETE':
        data = request.json
        tracker_id = data.get('id')
        cursor.execute("DELETE FROM trackers WHERE id = ? AND user_id = ?", (tracker_id, session['user_id']))
        conn.commit()
        conn.close()
        return jsonify({"message": "Tracker deleted"})

# ==================== PASSWORD RESET API ROUTES ====================

@app.route('/api/forgot-password', methods=['POST'])
def api_forgot_password():
    """API endpoint for forgot password - handles JSON requests"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400
    
    email = normalize_email(data.get('email'))
    if not email:
        return jsonify({"error": "Email is required"}), 400
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE lower(email) = ?", (email,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        reset_token = secrets.token_urlsafe(32)
        expiry = datetime.now() + timedelta(minutes=30)
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO password_resets (user_id, reset_token, reset_token_expiry)
            VALUES (?, ?, ?)
        """, (user[0], reset_token, expiry.isoformat()))
        conn.commit()
        conn.close()
        send_password_reset_email(email, reset_token)
    
    # Always return success to prevent email enumeration
    return jsonify({"success": True, "message": "If an account exists, a reset link has been sent"}), 200

@app.route('/api/reset-password', methods=['POST'])
def api_reset_password():
    """API endpoint for reset password - handles JSON requests"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400
    
    token = data.get('token')
    password = data.get('password')
    
    if not token:
        return jsonify({"error": "Token is required"}), 400
    
    if not password or len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, reset_token_expiry FROM password_resets WHERE reset_token = ?", (token,))
    reset_record = cursor.fetchone()
    
    if not reset_record:
        conn.close()
        return jsonify({"error": "Invalid or expired reset link"}), 400
    
    expiry = datetime.fromisoformat(reset_record[1]) if reset_record[1] else None
    if expiry and datetime.now() > expiry:
        conn.close()
        return jsonify({"error": "Reset link has expired"}), 400
    
    user_id = reset_record[0]
    hashed = generate_password_hash(password)
    cursor.execute("UPDATE users SET password = ? WHERE id = ?", (hashed, user_id))
    cursor.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "Password reset successful"}), 200

@app.route('/api/check-email', methods=['POST'])
def api_check_email():
    """API endpoint to check if email exists in the system"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400
    
    email = normalize_email(data.get('email'))
    if not email:
        return jsonify({"error": "Email is required"}), 400
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE lower(email) = ?", (email,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return jsonify({"exists": True, "email": email}), 200
    else:
        return jsonify({"exists": False, "email": email}), 200

@app.route('/api/direct-reset-password', methods=['POST'])
def api_direct_reset_password():
    """API endpoint for direct password reset without token"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400
    
    email = normalize_email(data.get('email'))
    password = data.get('password')
    
    if not email:
        return jsonify({"error": "Email is required"}), 400
    
    if not password or len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE lower(email) = ?", (email,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404
    
    user_id = user[0]
    hashed = generate_password_hash(password)
    cursor.execute("UPDATE users SET password = ? WHERE id = ?", (hashed, user_id))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "Password reset successful"}), 200

# ==================== PRICE TRACKING ====================

def parse_price(price_str):
    if not price_str:
        return None
    cleaned = str(price_str).strip()
    cleaned = re.sub(r'[^\d,.\s]', '', cleaned)
    cleaned = cleaned.replace(' ', '')

    if cleaned.count('.') > 1 and ',' not in cleaned:
        cleaned = cleaned.replace('.', '')
    if cleaned.count(',') > 1 and '.' not in cleaned:
        cleaned = cleaned.replace(',', '')
    if ',' in cleaned and '.' in cleaned:
        if cleaned.rfind(',') > cleaned.rfind('.'):
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    else:
        cleaned = cleaned.replace(',', '')

    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_price_candidates(text):
    if not text:
        return []
    patterns = [
        r'"price"\s*:\s*"?([0-9][0-9,]*\.?[0-9]*)"?',
        r'"salePrice"\s*:\s*"?([0-9][0-9,]*\.?[0-9]*)"?',
        r'"currentPrice"\s*:\s*"?([0-9][0-9,]*\.?[0-9]*)"?',
        r'"final_price"\s*:\s*"?([0-9][0-9,]*\.?[0-9]*)"?',
        r'"amount"\s*:\s*"?([0-9][0-9,]*\.?[0-9]*)"?',
        r'₹\s*([0-9][0-9,]*\.?[0-9]*)',
        r'INR\s*([0-9][0-9,]*\.?[0-9]*)',
        r'\$\s*([0-9][0-9,]*\.?[0-9]*)',
        r'USD\s*([0-9][0-9,]*\.?[0-9]*)',
        r'£\s*([0-9][0-9,]*\.?[0-9]*)',
        r'GBP\s*([0-9][0-9,]*\.?[0-9]*)',
        r'€\s*([0-9][0-9,]*\.?[0-9]*)',
        r'EUR\s*([0-9][0-9,]*\.?[0-9]*)',
        r'¥\s*([0-9][0-9,]*\.?[0-9]*)',
        r'JPY\s*([0-9][0-9,]*\.?[0-9]*)',
        r'AUD\s*([0-9][0-9,]*\.?[0-9]*)',
        r'CAD\s*([0-9][0-9,]*\.?[0-9]*)',
        r'SGD\s*([0-9][0-9,]*\.?[0-9]*)',
        r'AED\s*([0-9][0-9,]*\.?[0-9]*)',
    ]
    candidates = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = parse_price(match)
            if value and 1 <= value <= 10000000:
                candidates.append(value)
    return candidates


def extract_json_ld_prices(soup):
    """Extract prices from JSON-LD scripts with nested Offer/Product structures."""
    prices = []
    if not soup:
        return prices

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                lower_key = str(key).lower()
                if lower_key in {"price", "lowprice", "highprice"}:
                    parsed = parse_price(value)
                    if parsed and 1 <= parsed <= 10000000:
                        prices.append(parsed)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, (str, int, float)):
            # Handle embedded text nodes with currency markers.
            for candidate in extract_price_candidates(str(node)):
                prices.append(candidate)

    for script in soup.find_all('script', type='application/ld+json'):
        script_text = script.string or script.get_text() or ''
        if not script_text.strip():
            continue
        try:
            payload = json.loads(script_text)
            walk(payload)
        except (json.JSONDecodeError, TypeError):
            for candidate in extract_price_candidates(script_text):
                prices.append(candidate)
    return prices


def extract_amazon_asin(url):
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper()


def get_request_headers(url, site):
    parsed = urlparse(url)
    host = parsed.netloc
    language = "en-US,en;q=0.9"
    if site in {"amazon", "flipkart", "myntra", "ajio", "meesho", "snapdeal"}:
        language = "en-IN,en;q=0.9"
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": language,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Referer": f"{parsed.scheme}://{host}/"
    }


def is_captcha_like_response(status_code, html_text):
    text = (html_text or '').lower()
    if status_code in (429, 503):
        return True
    captcha_markers = [
        "captcha",
        "robot check",
        "enter the characters you see",
        "automated access",
        "sorry, we just need to make sure you're not a robot"
    ]
    return any(marker in text for marker in captcha_markers)


def normalize_product_url(url, site):
    """Normalize known product URLs to reduce anti-bot redirects and noisy params."""
    if not url:
        return url
    if site != 'amazon':
        return url
    asin = extract_amazon_asin(url)
    if asin:
        return f"https://www.amazon.in/dp/{asin}"
    return url


def get_fetch_candidates(url, site):
    """
    Return candidate URLs to fetch in order.
    Try canonicalized product URLs first where possible.
    """
    candidates = []
    normalized = normalize_product_url(url, site)
    candidates.append(normalized)
    if normalized != url:
        candidates.append(url)

    if site == 'amazon':
        asin = extract_amazon_asin(url)
        if asin:
            candidates.append(f"https://www.amazon.in/gp/aw/d/{asin}")
            candidates.append(f"https://www.amazon.in/dp/{asin}?th=1&psc=1")

    # Preserve order but remove duplicates.
    deduped = []
    seen = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped


CURRENCY_SYMBOLS = {
    "USD": "$",
    "INR": "₹",
    "GBP": "£",
    "EUR": "€",
    "JPY": "¥",
    "AUD": "A$",
    "CAD": "C$",
    "SGD": "S$",
    "AED": "AED"
}


def currency_symbol_for(code):
    return CURRENCY_SYMBOLS.get(code, "$")


def infer_currency_from_url(url):
    host = (urlparse(url).netloc or '').lower()
    if any(tld in host for tld in ['.in', 'amazon.in', 'flipkart', 'myntra', 'ajio', 'meesho', 'snapdeal']):
        return "INR"
    if any(tld in host for tld in ['.co.uk', '.uk']):
        return "GBP"
    if any(tld in host for tld in ['.de', '.fr', '.es', '.it', '.nl', '.eu']):
        return "EUR"
    if any(tld in host for tld in ['.jp']):
        return "JPY"
    if any(tld in host for tld in ['.com.au']):
        return "AUD"
    if any(tld in host for tld in ['.ca']):
        return "CAD"
    if any(tld in host for tld in ['.sg']):
        return "SGD"
    if any(tld in host for tld in ['.ae']):
        return "AED"
    return "USD"


def detect_currency_from_content(soup, html_text, fallback="USD"):
    text = (html_text or "")

    # 1) Explicit currency code from metadata
    code_patterns = [
        r'"priceCurrency"\s*:\s*"([A-Z]{3})"',
        r'price:currency["\']?\s*content=["\']([A-Z]{3})',
        r'currency["\']?\s*:\s*["\']([A-Z]{3})["\']'
    ]
    for pattern in code_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            code = match.group(1).upper()
            if code in CURRENCY_SYMBOLS:
                return code, currency_symbol_for(code)

    if soup:
        meta_currency = soup.find("meta", attrs={"property": "product:price:currency"})
        if meta_currency and meta_currency.get("content"):
            code = str(meta_currency.get("content")).strip().upper()
            if code in CURRENCY_SYMBOLS:
                return code, currency_symbol_for(code)

    # 2) Symbol detection fallback
    symbol_order = [
        ("₹", "INR"),
        ("£", "GBP"),
        ("€", "EUR"),
        ("¥", "JPY"),
        ("$", "USD"),
    ]
    for sym, code in symbol_order:
        if sym in text:
            return code, currency_symbol_for(code)

    return fallback, currency_symbol_for(fallback)


def get_site_info(url):
    url_lower = url.lower()
    if 'amazon' in url_lower:
        if 'amazon.in' in url_lower:
            return 'amazon', 'INR', '₹'
        elif 'amazon.co.uk' in url_lower:
            return 'amazon', 'GBP', '£'
        else:
            return 'amazon', 'USD', '$'
    elif 'flipkart' in url_lower:
        return 'flipkart', 'INR', '₹'
    elif 'myntra' in url_lower:
        return 'myntra', 'INR', '₹'
    elif 'ajio' in url_lower:
        return 'ajio', 'INR', '₹'
    elif 'meesho' in url_lower:
        return 'meesho', 'INR', '₹'
    elif 'snapdeal' in url_lower:
        return 'snapdeal', 'INR', '₹'
    else:
        inferred_currency = infer_currency_from_url(url)
        return 'unknown', inferred_currency, currency_symbol_for(inferred_currency)

def scrape_price(soup, site, currency_symbol):
    """Generic price scraper - improved to handle more cases"""

    # Universal selectors used by many ecommerce sites globally.
    universal_selectors = [
        'meta[property="product:price:amount"]',
        'meta[name="product:price:amount"]',
        'meta[itemprop="price"]',
        '[itemprop="price"]',
        '[data-price]',
        '[data-sale-price]',
        '[data-product-price]',
        '.price',
        '.product-price',
        '.sale-price',
        '.current-price'
    ]
    for selector in universal_selectors:
        elem = soup.select_one(selector)
        if not elem:
            continue
        value = elem.get('content') if elem.name == 'meta' else elem.get('data-price') or elem.get('data-sale-price') or elem.get_text()
        price = parse_price(value)
        if price and 1 <= price <= 10000000:
            return price
    
    # Try multiple selectors for Amazon
    if site == 'amazon':
        # Common Amazon rendered price element.
        price_elem = soup.select_one("span.a-price span.a-offscreen")
        if price_elem:
            price = parse_price(price_elem.get_text())
            if price:
                return price

        # Try new Amazon price structure
        price_elem = soup.find("span", {"class": "a-price"})
        if price_elem:
            whole = price_elem.find("span", {"class": "a-price-whole"})
            if whole:
                fraction = price_elem.find("span", {"class": "a-price-fraction"})
                whole_text = whole.get_text().replace(',', '').strip()
                if fraction and fraction.get_text().strip():
                    whole_text = f"{whole_text}.{fraction.get_text().strip()}"
                price = parse_price(whole_text)
                if price:
                    return price
        
        # Try alternative Amazon selectors
        price_elem = soup.select_one('.a-price-whole')
        if price_elem:
            price = parse_price(price_elem.get_text())
            if price:
                return price
        
        # Try product price ID
        price_elem = soup.find("span", {"id": "priceblock_ourprice"})
        if price_elem:
            price = parse_price(price_elem.get_text())
            if price:
                return price
        
        # Try deal price
        price_elem = soup.find("span", {"class": "a-price-whole"})
        if price_elem:
            price = parse_price(price_elem.get_text())
            if price:
                return price
        
        # Try to find any element with price text
        price_elem = soup.find(string=re.compile(r'₹\s*[\d,]+'))
        if price_elem:
            nums = re.findall(r'₹\s*([\d,]+\.?\d*)', price_elem)
            for match in nums:
                price = parse_price(match.replace(',', ''))
                if price and 50 < price < 100000:
                    return price
    
    # Flipkart - improved selectors for current website structure
    if site == 'flipkart':
        # Try the main price class (current Flipkart structure)
        price_elem = soup.find("div", {"class": "_30jeq3"})
        if price_elem:
            price = parse_price(price_elem.get_text())
            if price and price > 10:  # Filter out invalid prices
                return price
        
        # Try alternative Flipkart selectors
        price_elem = soup.find("div", {"class": "Nx9bqj"})
        if price_elem:
            price = parse_price(price_elem.get_text())
            if price and price > 10:
                return price
        
        # Try data attributes
        price_elem = soup.find("div", {"data-id": "price"})
        if price_elem:
            price = parse_price(price_elem.get_text())
            if price and price > 10:
                return price
        
        # Try finding by style or other attributes
        price_elem = soup.find(string=re.compile(r'₹[\d,]+'))
        if price_elem:
            nums = re.findall(r'₹([\d,]+)', price_elem)
            for match in nums:
                price = parse_price(match.replace(',', ''))
                if price and 100 < price < 100000:  # More specific range for Flipkart
                    return price
        
        # Last resort: search all text for valid price
        all_text = soup.get_text()
        prices = re.findall(r'₹\s*([\d,]+)', all_text)
        valid_prices = []
        for p in prices:
            price_val = parse_price(p.replace(',', ''))
            if price_val and 100 < price_val < 100000:  # Valid clothing price range
                valid_prices.append(price_val)
        if valid_prices:
            return max(valid_prices)  # Return highest price (usually current price)
    
    # Try multiple selectors for Myntra
    if site == 'myntra':
        price_elem = soup.find("span", {"class": "pdp-price"})
        if price_elem:
            price = parse_price(price_elem.get_text())
            if price:
                return price
    
    # Try multiple selectors for Ajio
    if site == 'ajio':
        price_elem = soup.find("span", {"class": "prod-price"})
        if price_elem:
            price = parse_price(price_elem.get_text())
            if price:
                return price
    
    # Try multiple selectors for Meesho
    if site == 'meesho':
        price_elem = soup.find("h3", {"class": "Sc-product-price"})
        if price_elem:
            price = parse_price(price_elem.get_text())
            if price:
                return price
    
    # Try multiple selectors for Snapdeal
    if site == 'snapdeal':
        price_elem = soup.find("span", {"class": "product-price"})
        if price_elem:
            price = parse_price(price_elem.get_text())
            if price:
                return price
    
    # Fallback: search for currency symbol anywhere in the page
    price_elem = soup.find(string=re.compile(r'₹\s*[\d,]+'))
    if price_elem:
        nums = re.findall(r'₹\s*([\d,]+\.?\d*)', price_elem)
        for match in nums:
            price = parse_price(match.replace(',', ''))
            if price and 50 < price < 100000:
                return price
    
    # Try for global symbols
    for symbol_pattern, min_val, max_val in [
        (r'\$\s*([\d,]+\.?\d*)', 1, 10000000),
        (r'£\s*([\d,]+\.?\d*)', 1, 10000000),
        (r'€\s*([\d,]+\.?\d*)', 1, 10000000),
        (r'¥\s*([\d,]+\.?\d*)', 1, 10000000),
    ]:
        price_elem = soup.find(string=re.compile(symbol_pattern))
        if price_elem:
            nums = re.findall(symbol_pattern, price_elem)
            for match in nums:
                price = parse_price(match.replace(',', ''))
                if price and min_val < price < max_val:
                    return price
    
    return None

@app.route('/get-price', methods=['POST'])
def get_price():
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    
    if not url:
        return jsonify({"error": "URL is required"}), 400
    
    if url.lower().startswith('test://'):
        mock_price = round(random.uniform(10, 500), 2)
        return jsonify({
            "price": mock_price, "currency": "USD", "currency_symbol": "$",
            "productName": "Test Product", "isTestMode": True
        })
    
    if not (url.startswith('http://') or url.startswith('https://')):
        return jsonify({"error": "Invalid URL format"}), 400

    parsed = urlparse(url)
    if not parsed.netloc:
        return jsonify({"error": "Invalid URL"}), 400
    if parsed.hostname in ['localhost', '127.0.0.1', '0.0.0.0']:
        return jsonify({"error": "Local URLs are not allowed"}), 400

    try:
        site, currency, currency_symbol = get_site_info(url)
        session_client = requests.Session()
        if site == 'amazon':
            session_client.cookies.set("i18n-prefs", "INR")
            session_client.cookies.set("lc-main", "en_IN")

        fetch_candidates = get_fetch_candidates(url, site)
        response = None
        soup = None
        price = None
        saw_captcha = False

        # Try multiple candidates + slight header variations before failing.
        header_variants = [
            {},
            {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"},
        ]
        for candidate_url in fetch_candidates:
            for variant in header_variants:
                headers = get_request_headers(candidate_url, site)
                headers.update(variant)
                current_response = session_client.get(candidate_url, headers=headers, timeout=20, allow_redirects=True)
                current_html = current_response.text or ''
                if is_captcha_like_response(current_response.status_code, current_html):
                    saw_captcha = True
                    time.sleep(0.6)
                    continue
                if current_response.status_code != 200:
                    continue

                current_soup = BeautifulSoup(current_response.content, "html.parser")
                current_price = scrape_price(current_soup, site, currency_symbol)

                if current_price is None:
                    json_ld_prices = extract_json_ld_prices(current_soup)
                    if json_ld_prices:
                        current_price = min(json_ld_prices)

                if current_price is None:
                    candidates = extract_price_candidates(current_html)
                    if candidates:
                        current_price = min(candidates)

                if current_price is not None:
                    detected_currency, detected_symbol = detect_currency_from_content(
                        current_soup,
                        current_html,
                        fallback=currency
                    )
                    currency = detected_currency
                    currency_symbol = detected_symbol
                    response = current_response
                    soup = current_soup
                    price = current_price
                    break
                else:
                    # Keep the best non-captcha HTML response for name extraction/error diagnosis.
                    response = current_response
                    soup = current_soup
            if price is not None:
                break

        if response is None:
            # No useful response received.
            status = 429 if saw_captcha else 502
            if saw_captcha:
                normalized = normalize_product_url(url, site)
                return jsonify({
                    "error": "Website temporarily blocked automated access (captcha). Please retry in a minute with a direct product URL.",
                    "suggestedUrl": normalized
                }), status
            return jsonify({"error": "Could not fetch product page. Please verify the URL and try again."}), status
        
        # Try to get product name from title
        product_name = "Product"
        if soup.title and soup.title.get_text():
            title = soup.title.get_text().strip()
            product_name = re.sub(r'\s*[-|]\s*(Amazon|Flipkart|Myntra|Ajio|Meesho|Snapdeal)\s*$', '', title, flags=re.IGNORECASE).strip()
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            product_name = og_title.get("content").strip()
        
        if price is None:
            html_text = response.text if response is not None else ""
            if is_captcha_like_response(response.status_code if response is not None else 0, html_text):
                normalized = normalize_product_url(url, site)
                return jsonify({
                    "error": "Website temporarily blocked automated access (captcha). Please retry in a minute with a direct product URL.",
                    "suggestedUrl": normalized
                }), 429
            return jsonify({"error": "Could not find price on this page. Use a product page URL with visible price."}), 404
        
        return jsonify({
            "price": price, "currency": currency, 
            "currency_symbol": currency_symbol, "productName": product_name
        })
    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timed out. Please try again."}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Could not connect to the website. Please check the URL."}), 502
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

# ==================== STATIC FILES ====================

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename, max_age=0)


@app.route('/robots.txt')
def robots_txt():
    host = request.host_url.rstrip('/')
    content = f"""User-agent: Mediapartners-Google
Allow: /

User-agent: Googlebot
Allow: /

User-agent: Googlebot-Image
Allow: /

User-agent: *
Allow: /

Sitemap: {host}/sitemap.xml
"""
    response = make_response(content)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return response


@app.route('/ads.txt')
def ads_txt():
    return send_from_directory('.', 'ads.txt', mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap_xml():
    host = request.host_url.rstrip('/')
    entries = [
        ("/", "2026-02-27", "daily", "1.0"),
        ("/home", "2026-02-27", "weekly", "0.9"),
        ("/about", "2026-02-27", "monthly", "0.6"),
        ("/contact", "2026-02-27", "monthly", "0.6"),
        ("/privacy", "2026-02-27", "yearly", "0.4"),
        ("/terms", "2026-02-27", "yearly", "0.4"),
        ("/blog", "2026-02-27", "weekly", "0.8"),
        ("/amp/home", "2026-02-27", "weekly", "0.7"),
        ("/blog/how-to-track-product-prices-online", "2026-02-27", "monthly", "0.7"),
        ("/blog/best-price-alert-tools-india", "2026-02-27", "monthly", "0.7"),
        ("/blog/save-money-price-trackers", "2026-02-27", "monthly", "0.7"),
        ("/blog/amazon-price-history", "2026-02-27", "monthly", "0.7")
    ]
    items = "\n".join([
        f"<url><loc>{host}{path}</loc><lastmod>{lastmod}</lastmod><changefreq>{freq}</changefreq><priority>{priority}</priority></url>"
        for path, lastmod, freq, priority in entries
    ])
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{items}
</urlset>"""
    response = make_response(content)
    response.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return response

# Catch-all route for SPA-style routing
# This ensures that any route that doesn't match API or static serves the appropriate page
@app.route('/<path:path>')
def catch_all(path):
    # Don't intercept API routes or static files
    if path.startswith('api/') or path.startswith('static/') or path == 'favicon.ico':
        return "Not Found", 404
    
    # For dashboard, check if user is logged in
    if path == 'dashboard' or path.startswith('dashboard/'):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return render_template('index.html')
    
    # For known exact routes, render the appropriate template
    known_routes = {
        'home': 'home.html',
        'about': 'about.html',
        'contact': 'contact.html',
        'privacy': 'privacy.html',
        'terms': 'terms.html',
        'blog': 'blog.html',
        'signup': 'signup.html',
        'login': 'login.html',
        'forgot-password': 'forgot-password.html',
    }

    if path in known_routes:
        return render_template(known_routes[path])

    # Unknown route should be a true 404 (avoid soft-404 duplicate content).
    return render_template('error.html', error="Page not found"), 404

@app.after_request
def add_no_cache_headers(response):
    # Explicitly allow snippets/indexing for public pages.
    path = request.path
    indexable = {
        '/', '/home', '/about', '/contact', '/privacy', '/terms', '/blog',
        '/blog/how-to-track-product-prices-online',
        '/blog/best-price-alert-tools-india',
        '/blog/save-money-price-trackers',
        '/blog/amazon-price-history'
    }
    if path in indexable:
        response.headers['X-Robots-Tag'] = 'index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1'
    elif path.startswith('/api/') or path == '/dashboard' or path.startswith('/dashboard/') or response.status_code >= 400:
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'

    if response.content_type and response.content_type.startswith('text/html'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# ==================== MAIN ====================

def initialize_app():
    """Lazy initialization function - only runs when needed"""
    print("=" * 50)
    print("🚀 AI Price Alert - Starting up...")
    print("=" * 50)
    try:
        init_db()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"⚠️  Database initialization warning: {e}")
    print("✅ App ready to serve requests")
    print("=" * 50)
    return True

# Initialize lazily - only when first request comes in
_app_initialized = False

@app.before_request
def ensure_app_initialized():
    """Initialize app on first request to avoid startup delays"""
    global _app_initialized
    if not _app_initialized:
        print("🔄 First request received - initializing app...")
        initialize_app()
        _app_initialized = True

if __name__ == "__main__":
    # Direct run mode (for local development)
    initialize_app()
    port = int(os.environ.get('PORT', 8081))
    print(f"🌐 Starting server on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    # Gunicorn/WSGI mode - initialize lazily via before_request hook
    # Don't run initialization here to avoid startup delays on Render
    print("📦 Running under WSGI server (Render) - lazy initialization enabled")
