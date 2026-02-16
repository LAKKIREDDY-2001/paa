import os
import re
import sqlite3
import random
import string
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, session, redirect, url_for, render_template, send_from_directory, make_response
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=3)

# Use a consistent secret key - generate once and store, or use environment variable
# This prevents sessions from being invalidated on app restart
app.secret_key = os.environ.get('SECRET_KEY', 'price-alerter-secret-key-2024-change-in-production')

# Session configuration - optimized for persistent login
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Changed from 'Strict' for better compatibility
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)  # 30 days persistent session
app.config['SESSION_COOKIE_NAME'] = 'price_alerter_session'  # Custom session cookie name
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(app, supports_credentials=True, origins="*")

# Enable permanent sessions by default
@app.before_request
def make_session_permanent():
    # Only set permanent if not already set
    if not session.get('permanent'):
        session.permanent = True

def resolve_database_path():
    # Check for environment variable first - this takes priority
    configured_path = os.environ.get('DATABASE_PATH')
    if configured_path:
        db_dir = os.path.dirname(configured_path) or '.'
        os.makedirs(db_dir, exist_ok=True)
        if os.access(db_dir, os.W_OK):
            print(f"Using database path from environment: {configured_path}")
            return configured_path

    # Render persistent disk mount paths - check these FIRST for persistence
    # These paths persist across deploys/restarts on Render
    render_persistent_paths = [
        '/var/data/database.db',
        '/opt/render/project/src/database.db',
        '/home/app/database.db'
    ]
    for render_path in render_persistent_paths:
        render_dir = os.path.dirname(render_path)
        try:
            os.makedirs(render_dir, exist_ok=True)
            if os.access(render_dir, os.W_OK):
                print(f"Using Render persistent database: {render_path}")
                return render_path
        except:
            continue

    # Try /data directory (common in containerized deployments like Railway, etc.)
    data_dir = '/data'
    try:
        os.makedirs(data_dir, exist_ok=True)
        if os.access(data_dir, os.W_OK):
            db_path = os.path.join(data_dir, 'database.db')
            print(f"Using /data directory database: {db_path}")
            return db_path
    except:
        pass

    # For local development - use project directory
    local_path = os.path.join(os.getcwd(), 'database.db')
    local_dir = os.path.dirname(local_path) or '.'
    if os.access(local_dir, os.W_OK):
        print(f"Using local database: {local_path}")
        return local_path

    # Last resort: tmp directory (NOT PERSISTENT - data will be lost on restart)
    print("WARNING: Using tmp directory - data will NOT persist across restarts!")
    return '/tmp/database.db'

DATABASE = resolve_database_path()
print(f"Using SQLite database: {DATABASE}")

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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
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
    """Signup page - direct account creation (OTP removed)"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Invalid request body"}), 400
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        phone = data.get('phone')

        if not all([username, email, password]):
            return jsonify({"error": "Missing data"}), 400

        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
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

            # Auto-login after signup
            session['user_id'] = user_id
            session['username'] = username
            session['email'] = email
            session.permanent = True
            
            response = jsonify({
                "success": "Account created successfully!",
                "redirect": "/dashboard"
            }), 201
            
            # Set remember cookie for lifetime login (1 year)
            response = make_response(response)
            response.set_cookie('remember_token', remember_token, max_age=60*60*24*365, httponly=True, samesite='Lax')
            
            return response
        except Exception:
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
    # Check for remember_token cookie first
    remember_token = request.cookies.get('remember_token')
    if remember_token and 'user_id' not in session:
        # Try to restore session from remember token
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
            return redirect(url_for('dashboard'))
    
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        email = data.get('email')
        password = data.get('password')
        remember = data.get('remember', False)

        if not email or not password:
            return jsonify({"error": "Missing data"}), 400
        
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cursor.fetchone()

            if user and check_password_hash(user[3], password):
                # Update last login timestamp
                cursor.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user[0],))
                
                # Generate remember token if "Remember me" is checked
                if remember:
                    token = secrets.token_urlsafe(32)
                    cursor.execute("UPDATE users SET remember_token = ? WHERE id = ?", (token, user[0]))
                else:
                    # Clear remember token if not checked
                    cursor.execute("UPDATE users SET remember_token = NULL WHERE id = ?", (user[0],))
                
                conn.commit()
                conn.close()
                
                # Set session
                session['user_id'] = user[0]
                session['username'] = user[1]
                session['email'] = user[2]
                session.permanent = True
                
                response = jsonify({
                    "success": "Logged in successfully",
                    "redirect": "/dashboard"
                }), 200
                
                # Set remember cookie if enabled (lasts 1 year)
                if remember:
                    response = make_response(response)
                    response.set_cookie('remember_token', token, max_age=60*60*24*365, httponly=True, samesite='Lax')
                
                return response
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
    session.pop('user_id', None)
    return redirect(url_for('home'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        data = request.get_json()
        email = data.get('email')
        if not email:
            return jsonify({"error": "Email is required"}), 400
        
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
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

@app.route('/api/trackers', methods=['GET', 'POST', 'DELETE'])
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
        data = request.json
        cursor.execute("""
            INSERT INTO trackers (user_id, url, product_name, current_price, target_price, currency, currency_symbol)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session['user_id'], data.get('url'), data.get('productName'), 
              data.get('currentPrice'), data.get('targetPrice'), 
              data.get('currency', 'USD'), data.get('currencySymbol', '$')))
        tracker_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return jsonify({"id": tracker_id, "message": "Tracker created"}), 201
    
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
    
    email = data.get('email')
    if not email:
        return jsonify({"error": "Email is required"}), 400
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
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
    
    email = data.get('email')
    if not email:
        return jsonify({"error": "Email is required"}), 400
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
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
    
    email = data.get('email')
    password = data.get('password')
    
    if not email:
        return jsonify({"error": "Email is required"}), 400
    
    if not password or len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
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
    price_str = re.sub(r'[^\d.]', '', price_str)
    try:
        return float(price_str)
    except ValueError:
        return None

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
        return 'unknown', 'USD', '$'

def scrape_price(soup, site, currency_symbol):
    """Generic price scraper - improved to handle more cases"""
    
    # Try multiple selectors for Amazon
    if site == 'amazon':
        # Try new Amazon price structure
        price_elem = soup.find("span", {"class": "a-price"})
        if price_elem:
            whole = price_elem.find("span", {"class": "a-price-whole"})
            if whole:
                price = parse_price(whole.get_text())
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
    
    # Try for $ symbol (USD/GBP)
    price_elem = soup.find(string=re.compile(r'\$\s*[\d,]+\.?\d*'))
    if price_elem:
        nums = re.findall(r'\$\s*([\d,]+\.?\d*)', price_elem)
        for match in nums:
            price = parse_price(match.replace(',', ''))
            if price and 1 < price < 10000:
                return price
    
    return None

@app.route('/get-price', methods=['POST'])
def get_price():
    data = request.json
    url = data.get('url')
    
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

    # Enhanced headers to avoid being blocked
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return jsonify({"error": f"Failed to fetch page (Status: {response.status_code})"}), response.status_code
        
        soup = BeautifulSoup(response.content, "html.parser")
        site, currency, currency_symbol = get_site_info(url)
        price = scrape_price(soup, site, currency_symbol)
        
        # Try to get product name from title
        product_name = "Product"
        if soup.title:
            title = soup.title.get_text().strip()
            product_name = re.sub(r'\s*[-|]\s*(Amazon|Flipkart|Myntra|Ajio|Meesho|Snapdeal)\s*$', '', title, flags=re.IGNORECASE).strip()
        
        if price is None:
            # Last resort: try to find any price-like pattern in the entire HTML
            html_text = response.text
            # Try to find any currency pattern
            price_patterns = [
                r'₹\s*([\d,]+\.?\d*)',
                r'INR\s*([\d,]+\.?\d*)',
                r'\$\s*([\d,]+\.?\d*)',
                r'USD\s*([\d,]+\.?\d*)',
                r'£\s*([\d,]+\.?\d*)',
                r'GBP\s*([\d,]+\.?\d*)'
            ]
            for pattern in price_patterns:
                matches = re.findall(pattern, html_text)
                for match in matches:
                    price = parse_price(match.replace(',', ''))
                    if price and 50 < price < 100000:
                        return jsonify({
                            "price": price, "currency": currency, 
                            "currency_symbol": currency_symbol, "productName": product_name
                        })
            
            return jsonify({"error": "Could not find price on this page. The website structure may have changed."}), 404
        
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
    
    # For known routes, render the appropriate template
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
    
    # Check if it's a known route
    for route, template in known_routes.items():
        if path == route or path.startswith(route + '/'):
            return render_template(template)
    
    # Default to home page for unknown routes
    return render_template('home.html')

@app.after_request
def add_no_cache_headers(response):
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
