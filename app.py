import os
import re
import sqlite3
import random
import string
import json
import secrets
import time
import logging
import ipaddress
import threading
import hashlib
import hmac
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, session, redirect, url_for, render_template, send_from_directory, make_response, g
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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=3)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("pricealerter")
rate_limit_lock = threading.Lock()
price_cache_lock = threading.Lock()
RATE_LIMIT_STATE = {}
PRODUCT_SNAPSHOT_CACHE = {}

IS_PRODUCTION = os.environ.get('APP_ENV', '').lower() in ['production', 'prod'] or \
    os.environ.get('FLASK_ENV', '').lower() == 'production'

# Use a consistent secret key - generate once and store, or use environment variable
# This prevents sessions from being invalidated on app restart
app.secret_key = os.environ.get('SECRET_KEY', 'price-alerter-secret-key-2024-change-in-production')
if IS_PRODUCTION and not os.environ.get('SECRET_KEY'):
    print("WARNING: SECRET_KEY is not set in production. Set SECRET_KEY environment variable.")

COOKIE_DOMAIN = os.environ.get('COOKIE_DOMAIN', '').strip()
if not COOKIE_DOMAIN and IS_PRODUCTION:
    COOKIE_DOMAIN = '.pricealerter.in'

# Session configuration - optimized for persistent login
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Changed from 'Strict' for better compatibility
app.config['SESSION_COOKIE_SECURE'] = IS_PRODUCTION
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_DOMAIN'] = COOKIE_DOMAIN or None
app.config['SESSION_TYPE'] = os.environ.get('SESSION_TYPE', 'filesystem')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)  # 30 days persistent session
app.config['SESSION_COOKIE_NAME'] = 'price_alerter_session'  # Custom session cookie name
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'price_alerter:'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(
    app,
    supports_credentials=True,
    origins=[
        origin.strip()
        for origin in os.environ.get(
            'CORS_ORIGINS',
            'https://pricealerter.in,https://app.pricealerter.in,http://localhost:8081,http://127.0.0.1:8081'
        ).split(',')
        if origin.strip()
    ]
)

# Enable permanent sessions by default
@app.before_request
def make_session_permanent():
    # Only set permanent if not already set
    if not session.get('permanent'):
        session.permanent = True
    g.request_started_at = time.time()


def remember_cookie_domain():
    return app.config.get('SESSION_COOKIE_DOMAIN') or None


def set_remember_cookie(response, token):
    cookie_kwargs = {
        "max_age": 60 * 60 * 24 * 365,
        "httponly": True,
        "samesite": app.config.get('SESSION_COOKIE_SAMESITE', 'Lax'),
        "secure": app.config.get('SESSION_COOKIE_SECURE', False),
        "path": "/"
    }
    domain = remember_cookie_domain()
    if domain:
        cookie_kwargs["domain"] = domain
    response.set_cookie('remember_token', token, **cookie_kwargs)


def clear_remember_cookie(response):
    cookie_kwargs = {"path": "/"}
    domain = remember_cookie_domain()
    if domain:
        cookie_kwargs["domain"] = domain
    response.delete_cookie('remember_token', **cookie_kwargs)


def clear_auth_cookies(response):
    cookie_kwargs = {"path": "/"}
    domain = remember_cookie_domain()
    if domain:
        cookie_kwargs["domain"] = domain
    response.delete_cookie('remember_token', **cookie_kwargs)
    response.delete_cookie(app.config.get('SESSION_COOKIE_NAME', 'session'), **cookie_kwargs)


def restore_user_session_from_cookie():
    global _app_initialized
    g.current_user = None

    if not _app_initialized:
        initialize_app()
        _app_initialized = True

    user_id = session.get('user_id')
    if user_id:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, email FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            conn.close()
            if user:
                session['username'] = user['username']
                session['email'] = user['email']
                g.current_user = user
                return
        except Exception as e:
            logger.warning("Session validation failed for user_id=%s: %s", user_id, e)
        session.clear()

    remember_token = (request.cookies.get('remember_token') or '').strip()
    if not remember_token:
        return

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email FROM users WHERE remember_token = ?", (remember_token,))
        user = cursor.fetchone()
        conn.close()
        if not user:
            return
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['email'] = user['email']
        session.permanent = True
        session.modified = True
        g.current_user = user
        logger.info("session_restored_from_remember_cookie user_id=%s path=%s", user['id'], request.path)
    except Exception as e:
        logger.warning("Remember-token restoration failed: %s", e)


@app.before_request
def restore_authenticated_user():
    restore_user_session_from_cookie()


@app.after_request
def log_request(response):
    started_at = getattr(g, "request_started_at", None)
    if started_at is not None and request.path.startswith("/api/"):
        duration_ms = int((time.time() - started_at) * 1000)
        logger.info(
            "api_request method=%s path=%s status=%s duration_ms=%s ip=%s",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            client_ip()
        )
    return response


def normalize_email(email):
    if not email:
        return ""
    return email.strip().lower()


PHONE_PATTERN = re.compile(r'^\+?[1-9]\d{9,14}$')


def normalize_phone(phone):
    raw_phone = str(phone or "").strip()
    if not raw_phone:
        raise ValueError("Phone number is required")

    cleaned = re.sub(r"[^\d+]", "", raw_phone)
    if cleaned.count("+") > 1 or ("+" in cleaned and not cleaned.startswith("+")):
        raise ValueError("Invalid phone number format")
    if "+" not in cleaned:
        cleaned = f"+{cleaned}"
    if not PHONE_PATTERN.match(cleaned):
        raise ValueError("Please enter a valid phone number with country code")
    return cleaned


def api_error(message, status=400, details=None):
    payload = {"error": message}
    if details:
        payload["details"] = details
    return jsonify(payload), status


def get_request_json():
    return request.get_json(silent=True) or {}


def get_db_connection():
    conn = sqlite3.connect(DATABASE, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 20000")
    return conn


def parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def client_ip():
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded_for or request.remote_addr or "unknown"


def rate_limit_key():
    return f"{client_ip()}:{request.endpoint or request.path}"


def is_rate_limited(limit=None, window_seconds=None):
    if limit is None:
        limit = RATE_LIMIT_MAX_REQUESTS
    if window_seconds is None:
        window_seconds = RATE_LIMIT_WINDOW_SECONDS
    now = time.time()
    key = rate_limit_key()
    with rate_limit_lock:
        state = RATE_LIMIT_STATE.get(key)
        if not state or (now - state["window_start"]) >= window_seconds:
            RATE_LIMIT_STATE[key] = {"window_start": now, "count": 1}
            return False, 0

        state["count"] += 1
        retry_after = max(1, int(window_seconds - (now - state["window_start"])))
        if state["count"] > limit:
            return True, retry_after
        return False, retry_after


def too_many_requests(retry_after):
    response = jsonify({"error": "Too many requests. Please slow down and try again."})
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


def cache_get(key):
    now = time.time()
    with price_cache_lock:
        entry = PRODUCT_SNAPSHOT_CACHE.get(key)
        if not entry:
            return None
        if now - entry["created_at"] > PRICE_CACHE_TTL_SECONDS:
            PRODUCT_SNAPSHOT_CACHE.pop(key, None)
            return None
        return dict(entry["value"])


def cache_set(key, value):
    with price_cache_lock:
        if len(PRODUCT_SNAPSHOT_CACHE) > 500:
            oldest_key = min(PRODUCT_SNAPSHOT_CACHE, key=lambda item: PRODUCT_SNAPSHOT_CACHE[item]["created_at"])
            PRODUCT_SNAPSHOT_CACHE.pop(oldest_key, None)
        PRODUCT_SNAPSHOT_CACHE[key] = {"created_at": time.time(), "value": dict(value)}


def cron_signature_is_valid():
    incoming_secret = request.headers.get('X-Cron-Secret', '').strip()
    if not CRON_SECRET or not hmac.compare_digest(incoming_secret, CRON_SECRET):
        return False

    timestamp = request.headers.get("X-Cron-Timestamp", "").strip()
    signature = request.headers.get("X-Cron-Signature", "").strip()
    if not timestamp and not signature:
        return True

    if not timestamp or not signature or not timestamp.isdigit():
        return False

    current_ts = int(time.time())
    request_ts = int(timestamp)
    if abs(current_ts - request_ts) > CRON_SIGNATURE_TTL_SECONDS:
        return False

    expected = hmac.new(
        CRON_SECRET.encode("utf-8"),
        f"{request.path}:{timestamp}".encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

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
SMTP_RETRY_ATTEMPTS = max(1, int(os.environ.get("SMTP_RETRY_ATTEMPTS", "2")))
CRON_SECRET = os.environ.get("CRON_SECRET", "").strip()
CRON_SIGNATURE_TTL_SECONDS = max(60, int(os.environ.get("CRON_SIGNATURE_TTL_SECONDS", "300")))
PRICE_CACHE_TTL_SECONDS = max(15, int(os.environ.get("PRICE_CACHE_TTL_SECONDS", "60")))
DEFAULT_TRACKER_CHECK_INTERVAL_SECONDS = max(300, int(os.environ.get("DEFAULT_TRACKER_CHECK_INTERVAL_SECONDS", "900")))
RATE_LIMIT_WINDOW_SECONDS = max(10, int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60")))
RATE_LIMIT_MAX_REQUESTS = max(5, int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "45")))

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
    'twilio_whatsapp_number': '+14155238886', 'from_name': 'AI Price Alert',
    'welcome_content_sid': ''
})

if os.environ.get('TWILIO_ACCOUNT_SID'):
    TWILIO_CONFIG['account_sid'] = os.environ.get('TWILIO_ACCOUNT_SID', '')
if os.environ.get('TWILIO_AUTH_TOKEN'):
    TWILIO_CONFIG['auth_token'] = os.environ.get('TWILIO_AUTH_TOKEN', '')
if os.environ.get('TWILIO_PHONE_NUMBER'):
    TWILIO_CONFIG['phone_number'] = os.environ.get('TWILIO_PHONE_NUMBER', '')
if os.environ.get('TWILIO_ENABLED'):
    TWILIO_CONFIG['enabled'] = os.environ.get('TWILIO_ENABLED', '').lower() == 'true'

if os.environ.get('TWILIO_WHATSAPP_ACCOUNT_SID'):
    WHATSAPP_CONFIG['twilio_account_sid'] = os.environ.get('TWILIO_WHATSAPP_ACCOUNT_SID', '')
if os.environ.get('TWILIO_WHATSAPP_AUTH_TOKEN'):
    WHATSAPP_CONFIG['twilio_auth_token'] = os.environ.get('TWILIO_WHATSAPP_AUTH_TOKEN', '')
if os.environ.get('TWILIO_WHATSAPP_NUMBER'):
    WHATSAPP_CONFIG['twilio_whatsapp_number'] = os.environ.get('TWILIO_WHATSAPP_NUMBER', '')
if os.environ.get('TWILIO_WHATSAPP_ENABLED'):
    WHATSAPP_CONFIG['enabled'] = os.environ.get('TWILIO_WHATSAPP_ENABLED', '').lower() == 'true'
if os.environ.get('TWILIO_WHATSAPP_WELCOME_CONTENT_SID'):
    WHATSAPP_CONFIG['welcome_content_sid'] = os.environ.get('TWILIO_WHATSAPP_WELCOME_CONTENT_SID', '').strip()

# ==================== EMAIL FUNCTIONS ====================

def send_mail(to_email, subject, html_body, text_body=None):
    if not EMAIL_CONFIG['enabled']:
        logger.info("Email demo mode: to=%s subject=%s", to_email, subject)
        return True
    
    if not EMAIL_CONFIG.get('smtp_email') or not EMAIL_CONFIG.get('smtp_password'):
        logger.warning("Email not configured - skipping send to %s", to_email)
        return False
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{EMAIL_CONFIG['from_name']} <{EMAIL_CONFIG['smtp_email']}>"
    msg['To'] = to_email
    if text_body:
        msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    smtp_port = int(EMAIL_CONFIG.get('smtp_port', 587))
    use_tls = parse_bool(EMAIL_CONFIG.get('use_tls', True), default=True)

    for attempt in range(1, SMTP_RETRY_ATTEMPTS + 1):
        try:
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
            logger.info("Email sent successfully to %s", to_email)
            return True
        except Exception as e:
            logger.warning("Email send attempt %s failed for %s: %s", attempt, to_email, e)
            if attempt < SMTP_RETRY_ATTEMPTS:
                time.sleep(1.5 * attempt)
    return False

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def send_email_otp(email, otp, purpose="verification"):
    text_body = f"Your AI Price Alert {purpose} code is: {otp}\n\nThis code expires in 10 minutes."
    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif;">
        <h2>AI Price Alert</h2>
        <p>Your {purpose} code is:</p>
        <p style="font-size: 24px; font-weight: bold; letter-spacing: 4px;">{otp}</p>
        <p>This code expires in 10 minutes.</p>
      </body>
    </html>
    """
    return send_mail(
        to_email=email,
        subject=f'AI Price Alert - {purpose.title()} Code',
        html_body=html_body,
        text_body=text_body
    )

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


def send_alert_created_email(to_email, product_name, product_url, target_price, currency_symbol):
    product_display = product_name or "Product"
    target_str = f"{currency_symbol}{target_price:.2f}"
    html_body = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>Tracker Created</title></head>
    <body style="font-family: Arial, sans-serif; max-width: 640px; margin: 0 auto; padding: 20px;">
        <h2 style="color:#0f172a; margin-bottom: 12px;">Your price alert is live</h2>
        <p style="color:#334155;">We started tracking <strong>{product_display}</strong>.</p>
        <div style="border:1px solid #e2e8f0; border-radius:12px; padding:16px; background:#f8fafc;">
            <p style="margin:0 0 8px 0;"><strong>Target price:</strong> {target_str}</p>
            <p style="margin:0;"><strong>Status:</strong> Active and monitoring</p>
        </div>
        <p style="margin-top:16px;">
            <a href="{product_url}" style="display:inline-block; padding:12px 18px; background:#0ea5e9; color:#fff; text-decoration:none; border-radius:8px;">
                View Product
            </a>
        </p>
    </body>
    </html>
    '''
    return send_mail(
        to_email=to_email,
        subject=f"Tracking started: {product_display}",
        html_body=html_body
    )


def send_phone_notification(phone, message, prefer_whatsapp=True):
    phone = str(phone or "").strip()
    if not phone:
        return False

    try:
        from twilio.rest import Client  # type: ignore
    except Exception:
        logger.info("twilio not installed; skipping phone notification")
        return False

    try:
        if prefer_whatsapp and WHATSAPP_CONFIG.get("enabled"):
            account_sid = WHATSAPP_CONFIG.get("twilio_account_sid") or TWILIO_CONFIG.get("account_sid")
            auth_token = WHATSAPP_CONFIG.get("twilio_auth_token") or TWILIO_CONFIG.get("auth_token")
            from_number = WHATSAPP_CONFIG.get("twilio_whatsapp_number")
            if account_sid and auth_token and from_number:
                client = Client(account_sid, auth_token)
                client.messages.create(
                    body=message[:1500],
                    from_=f"whatsapp:{from_number}",
                    to=f"whatsapp:{phone}"
                )
                return True

        if TWILIO_CONFIG.get("enabled"):
            account_sid = TWILIO_CONFIG.get("account_sid")
            auth_token = TWILIO_CONFIG.get("auth_token")
            from_number = TWILIO_CONFIG.get("phone_number")
            if account_sid and auth_token and from_number:
                client = Client(account_sid, auth_token)
                client.messages.create(
                    body=message[:1500],
                    from_=from_number,
                    to=phone
                )
                return True
    except Exception as e:
        logger.warning("Phone notification failed for %s: %s", phone, e)

    return False


def send_whatsapp_template_message(phone, content_sid, content_variables):
    phone = str(phone or "").strip()
    content_sid = str(content_sid or "").strip()
    if not phone or not content_sid:
        return False

    try:
        from twilio.rest import Client  # type: ignore
    except Exception:
        logger.info("twilio not installed; skipping WhatsApp template send")
        return False

    try:
        account_sid = WHATSAPP_CONFIG.get("twilio_account_sid") or TWILIO_CONFIG.get("account_sid")
        auth_token = WHATSAPP_CONFIG.get("twilio_auth_token") or TWILIO_CONFIG.get("auth_token")
        from_number = WHATSAPP_CONFIG.get("twilio_whatsapp_number")
        if not (account_sid and auth_token and from_number):
            logger.warning("WhatsApp template send skipped due to missing Twilio config")
            return False

        client = Client(account_sid, auth_token)
        client.messages.create(
            from_=f"whatsapp:{from_number}",
            content_sid=content_sid,
            content_variables=json.dumps(content_variables or {}),
            to=f"whatsapp:{phone}"
        )
        return True
    except Exception as e:
        logger.warning("WhatsApp template send failed for %s: %s", phone, e)
        return False

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
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    
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
            product_image TEXT,
            current_price REAL NOT NULL,
            target_price REAL NOT NULL,
            currency TEXT,
            currency_symbol TEXT,
            alert_rules TEXT,
            best_time_to_buy TEXT,
            archive_status TEXT DEFAULT 'active',
            target_reached_notified INTEGER DEFAULT 0,
            last_checked_at TIMESTAMP,
            last_check_error TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracker_id INTEGER NOT NULL,
            price REAL NOT NULL,
            currency TEXT,
            currency_symbol TEXT,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tracker_id, recorded_at),
            FOREIGN KEY (tracker_id) REFERENCES trackers(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notification_preferences (
            user_id INTEGER PRIMARY KEY,
            push_enabled INTEGER DEFAULT 0,
            email_enabled INTEGER DEFAULT 1,
            in_app_enabled INTEGER DEFAULT 1,
            phone_enabled INTEGER DEFAULT 0,
            alert_drop_percentage REAL DEFAULT 10,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            endpoint TEXT NOT NULL UNIQUE,
            subscription_json TEXT NOT NULL,
            user_agent TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tracker_id INTEGER,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            channel TEXT DEFAULT 'in_app',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (tracker_id) REFERENCES trackers(id) ON DELETE SET NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recently_viewed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tracker_id INTEGER NOT NULL,
            viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, tracker_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (tracker_id) REFERENCES trackers(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS job_locks (
            job_name TEXT PRIMARY KEY,
            locked_until TIMESTAMP,
            heartbeat_at TIMESTAMP,
            owner_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Backward-compatible migration for existing databases.
    cursor.execute("PRAGMA table_info(trackers)")
    tracker_columns = [row[1] for row in cursor.fetchall()]
    if 'target_reached_notified' not in tracker_columns:
        cursor.execute("ALTER TABLE trackers ADD COLUMN target_reached_notified INTEGER DEFAULT 0")
    if 'last_checked_at' not in tracker_columns:
        cursor.execute("ALTER TABLE trackers ADD COLUMN last_checked_at TIMESTAMP")
    if 'last_check_error' not in tracker_columns:
        cursor.execute("ALTER TABLE trackers ADD COLUMN last_check_error TEXT")
    if 'updated_at' not in tracker_columns:
        cursor.execute("ALTER TABLE trackers ADD COLUMN updated_at TIMESTAMP")
        cursor.execute("UPDATE trackers SET updated_at = COALESCE(updated_at, created_at)")
    if 'product_image' not in tracker_columns:
        cursor.execute("ALTER TABLE trackers ADD COLUMN product_image TEXT")
    if 'alert_rules' not in tracker_columns:
        cursor.execute("ALTER TABLE trackers ADD COLUMN alert_rules TEXT")
    if 'best_time_to_buy' not in tracker_columns:
        cursor.execute("ALTER TABLE trackers ADD COLUMN best_time_to_buy TEXT")
    if 'archive_status' not in tracker_columns:
        cursor.execute("ALTER TABLE trackers ADD COLUMN archive_status TEXT DEFAULT 'active'")
    cursor.execute("PRAGMA table_info(notification_preferences)")
    pref_columns = [row[1] for row in cursor.fetchall()]
    if 'phone_enabled' not in pref_columns:
        cursor.execute("ALTER TABLE notification_preferences ADD COLUMN phone_enabled INTEGER DEFAULT 0")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trackers_user_created ON trackers(user_id, created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trackers_due_checks ON trackers(last_checked_at, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_history_tracker_time ON price_history(tracker_id, recorded_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_time ON notifications(user_id, created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recently_viewed_user_time ON recently_viewed(user_id, viewed_at DESC)")
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_trackers_user_url_unique ON trackers(user_id, url)")
    except sqlite3.IntegrityError:
        logger.warning("Skipping unique tracker index creation because duplicate tracker rows already exist")
    
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
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        email = normalize_email(data.get('email'))
        password = data.get('password')
        remember = parse_bool(data.get('remember'), default=True)

        if not email or not password:
            return jsonify({"error": "Missing data"}), 400
        
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE lower(email) = ?", (email,))
            user = cursor.fetchone()

            if user and check_password_hash(user[3], password):
                # Update last login timestamp
                token = secrets.token_urlsafe(32) if remember else None
                cursor.execute(
                    "UPDATE users SET last_login = CURRENT_TIMESTAMP, remember_token = ? WHERE id = ?",
                    (token, user[0])
                )
                
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
                
                if remember:
                    set_remember_cookie(response_data, token)
                else:
                    clear_remember_cookie(response_data)
                
                print(f"User logged in: {email}, remember_enabled: {bool(token)}")
                return response_data, 200
            elif user and user[3] == password:
                # Backward compatibility: migrate legacy plaintext passwords to hashed format.
                hashed_password = generate_password_hash(password)
                token = secrets.token_urlsafe(32) if remember else None
                cursor.execute(
                    "UPDATE users SET password = ?, last_login = CURRENT_TIMESTAMP, remember_token = ? WHERE id = ?",
                    (hashed_password, token, user[0])
                )
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
                    set_remember_cookie(response_data, token)
                else:
                    clear_remember_cookie(response_data)

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
    clear_auth_cookies(response)
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
        return api_error("Not logged in", status=401)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, phone FROM users WHERE id = ?", (session['user_id'],))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        response = jsonify({"id": user["id"], "username": user["username"], "email": user["email"], "phone": user["phone"]})
        response.headers["Cache-Control"] = "no-store"
        return response
    return api_error("User not found", status=404)


@app.route('/api/connect-whatsapp', methods=['GET', 'POST'])
def connect_whatsapp():
    if 'user_id' not in session:
        return api_error("Not logged in", status=401)

    if request.method == 'GET':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT phone FROM users WHERE id = ?", (session['user_id'],))
        user = cursor.fetchone()
        prefs = get_notification_preferences(cursor, session['user_id'])
        conn.close()
        return jsonify({
            "connected": bool(user and user["phone"]),
            "phone": user["phone"] if user else None,
            "phoneEnabled": bool(prefs["phone_enabled"]),
            "message": "Use POST to connect or update a WhatsApp number."
        })

    limited, retry_after = is_rate_limited(limit=5, window_seconds=300)
    if limited:
        return too_many_requests(retry_after)

    data = get_request_json()
    try:
        phone = normalize_phone(data.get("phone"))
    except ValueError as exc:
        return api_error(str(exc), status=400)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return api_error("User not found", status=404)

    cursor.execute("""
        UPDATE users
        SET phone = ?, phone_verified = 1
        WHERE id = ?
    """, (phone, session['user_id']))

    get_notification_preferences(cursor, session['user_id'])
    cursor.execute("""
        UPDATE notification_preferences
        SET phone_enabled = 1, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
    """, (session['user_id'],))

    welcome_content_sid = (data.get("contentSid") or WHATSAPP_CONFIG.get("welcome_content_sid") or "").strip()
    welcome_variables = data.get("contentVariables")
    if not isinstance(welcome_variables, dict):
        welcome_variables = {
            "1": user["username"],
            "2": "Price Alerter"
        }

    whatsapp_sent = send_whatsapp_template_message(phone, welcome_content_sid, welcome_variables)
    create_in_app_notification(
        cursor,
        session['user_id'],
        None,
        "WhatsApp connected",
        "Your WhatsApp alerts are now enabled. Check your phone for the welcome template message." if whatsapp_sent
        else "Your WhatsApp alerts are enabled, but the welcome template message could not be sent.",
        channel="whatsapp" if whatsapp_sent else "system"
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "phone": phone,
        "whatsappSent": bool(whatsapp_sent),
        "message": "WhatsApp connected successfully." if whatsapp_sent else "WhatsApp connected, but the template welcome message could not be sent right now. Configure an approved template Content SID first."
    })

@app.route('/api/trackers', methods=['GET', 'POST', 'PUT', 'DELETE'])
def trackers():
    if 'user_id' not in session:
        return api_error("Not logged in", status=401)

    if request.method in {"POST", "PUT", "DELETE"}:
        limited, retry_after = is_rate_limited(limit=20, window_seconds=60)
        if limited:
            return too_many_requests(retry_after)

    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'GET':
        cursor.execute("""
            SELECT id, url, product_name, product_image, current_price, target_price, currency, currency_symbol,
                   created_at, updated_at, best_time_to_buy, archive_status, last_checked_at, last_check_error, alert_rules
            FROM trackers
            WHERE user_id = ? AND archive_status != 'archived'
            ORDER BY created_at DESC
        """, (session['user_id'],))
        trackers_list = cursor.fetchall()
        conn.close()
        return jsonify([
            {
                "id": t["id"],
                "url": t["url"],
                "productName": t["product_name"] or "Product",
                "productImage": t["product_image"],
                "currentPrice": t["current_price"],
                "targetPrice": t["target_price"],
                "currency": t["currency"],
                "currencySymbol": t["currency_symbol"],
                "createdAt": t["created_at"],
                "updatedAt": t["updated_at"],
                "bestTimeToBuy": json.loads(t["best_time_to_buy"]) if t["best_time_to_buy"] else None,
                "archiveStatus": t["archive_status"],
                "lastCheckedAt": t["last_checked_at"],
                "lastCheckError": t["last_check_error"],
                "alertRules": json.loads(t["alert_rules"]) if t["alert_rules"] else []
            }
            for t in trackers_list
        ])
    
    if request.method == 'POST':
        try:
            data = validate_tracker_input(get_request_json())
        except ValueError as e:
            conn.close()
            return api_error(str(e), status=400)
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("""
                SELECT id, url, product_name, product_image, current_price, target_price, currency, currency_symbol, created_at, best_time_to_buy, alert_rules
                FROM trackers
                WHERE user_id = ? AND url = ?
                LIMIT 1
            """, (session['user_id'], data["url"]))
            existing_tracker = cursor.fetchone()
            if existing_tracker:
                conn.commit()
                conn.close()
                return jsonify({
                    "error": "You are already tracking this product URL.",
                    "tracker": {
                        "id": existing_tracker["id"],
                        "url": existing_tracker["url"],
                        "productName": existing_tracker["product_name"] or "Product",
                        "productImage": existing_tracker["product_image"],
                        "currentPrice": existing_tracker["current_price"],
                        "targetPrice": existing_tracker["target_price"],
                        "currency": existing_tracker["currency"],
                        "currencySymbol": existing_tracker["currency_symbol"],
                        "createdAt": existing_tracker["created_at"],
                        "bestTimeToBuy": json.loads(existing_tracker["best_time_to_buy"]) if existing_tracker["best_time_to_buy"] else None,
                        "alertRules": json.loads(existing_tracker["alert_rules"]) if existing_tracker["alert_rules"] else []
                    }
                }), 409

            cursor.execute("""
                INSERT INTO trackers (user_id, url, product_name, product_image, current_price, target_price, currency, currency_symbol, alert_rules, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                session['user_id'],
                data["url"],
                data["productName"],
                data.get("productImage"),
                data["currentPrice"],
                data["targetPrice"],
                data["currency"],
                data["currencySymbol"],
                json.dumps(data.get("alertRules") or [])
            ))
            tracker_id = cursor.lastrowid
            store_price_history(cursor, tracker_id, data["currentPrice"], data["currency"], data["currencySymbol"])
            create_in_app_notification(cursor, session['user_id'], tracker_id, "Tracker created", f"Tracking started for {data['productName']}.")
            cursor.execute("SELECT email, phone FROM users WHERE id = ?", (session['user_id'],))
            user_contact = cursor.fetchone()
            conn.commit()
            cursor.execute("SELECT created_at FROM trackers WHERE id = ?", (tracker_id,))
            created_at = cursor.fetchone()["created_at"]
            conn.close()
            if user_contact:
                try:
                    if user_contact["email"]:
                        send_alert_created_email(
                            user_contact["email"],
                            data["productName"],
                            data["url"],
                            data["targetPrice"],
                            data["currencySymbol"]
                        )
                except Exception as e:
                    logger.warning("Tracker created email failed for user=%s tracker=%s: %s", session['user_id'], tracker_id, e)
                try:
                    if user_contact["phone"]:
                        prefs_conn = get_db_connection()
                        prefs_cursor = prefs_conn.cursor()
                        prefs = get_notification_preferences(prefs_cursor, session['user_id'])
                        prefs_conn.close()
                        if prefs and bool(prefs["phone_enabled"]):
                            phone_sent = send_phone_notification(
                                user_contact["phone"],
                                (
                                    f"Price alert created\n"
                                    f"{data['productName']}\n"
                                    f"Target: {data['currencySymbol']}{float(data['targetPrice']):.2f}\n"
                                    f"{data['url']}"
                                ),
                                prefer_whatsapp=True
                            )
                            if phone_sent:
                                notify_conn = get_db_connection()
                                notify_cursor = notify_conn.cursor()
                                create_in_app_notification(
                                    notify_cursor,
                                    session['user_id'],
                                    tracker_id,
                                    "WhatsApp alert sent",
                                    f"Tracker confirmation was delivered on WhatsApp for {data['productName']}.",
                                    channel="whatsapp"
                                )
                                notify_conn.commit()
                                notify_conn.close()
                except Exception as e:
                    logger.warning("Tracker created phone notification failed for user=%s tracker=%s: %s", session['user_id'], tracker_id, e)
            return jsonify({
                "id": tracker_id,
                "message": "Tracker created",
                "tracker": {
                    "id": tracker_id,
                    "url": data["url"],
                    "productName": data["productName"],
                    "productImage": data.get("productImage"),
                    "currentPrice": data["currentPrice"],
                    "targetPrice": data["targetPrice"],
                    "currency": data["currency"],
                    "currencySymbol": data["currencySymbol"],
                    "createdAt": created_at,
                    "bestTimeToBuy": "Start tracking",
                    "alertRules": data.get("alertRules") or []
                }
            }), 201
        except sqlite3.IntegrityError:
            conn.rollback()
            conn.close()
            return api_error("You are already tracking this product URL.", status=409)

    if request.method == 'PUT':
        try:
            data = validate_tracker_input(get_request_json(), require_id=True)
        except ValueError as e:
            conn.close()
            return api_error(str(e), status=400)

        cursor.execute("""
            SELECT t.id, t.url, t.product_name, t.current_price, t.target_price, t.currency, t.currency_symbol,
                   t.product_image, t.alert_rules, COALESCE(t.target_reached_notified, 0) AS target_reached_notified, u.email
            FROM trackers t
            JOIN users u ON u.id = t.user_id
            WHERE t.id = ? AND t.user_id = ?
        """, (data["id"], session['user_id']))
        existing = cursor.fetchone()
        if not existing:
            conn.close()
            return api_error("Tracker not found", status=404)

        final_current = data.get("currentPrice", float(existing["current_price"]))
        final_target = data.get("targetPrice", float(existing["target_price"]))
        final_name = data.get("productName", existing["product_name"])
        final_currency = data.get("currency", existing["currency"])
        final_symbol = data.get("currencySymbol", existing["currency_symbol"])
        final_image = data.get("productImage", existing["product_image"])
        final_alert_rules = data.get("alertRules")
        if final_alert_rules is None:
            final_alert_rules = json.loads(existing["alert_rules"]) if existing["alert_rules"] else parse_alert_rules({}, default_target=final_target)

        was_below_or_equal = float(existing["current_price"]) <= float(existing["target_price"])
        is_below_or_equal = final_current <= final_target
        should_notify_now = (not was_below_or_equal) and is_below_or_equal and int(existing["target_reached_notified"] or 0) == 0
        reset_notified = (not is_below_or_equal)
        next_notified_value = 1 if should_notify_now else (0 if reset_notified else int(existing["target_reached_notified"] or 0))

        cursor.execute("""
            UPDATE trackers
            SET current_price = ?,
                target_price = ?,
                product_name = ?,
                product_image = ?,
                currency = ?,
                currency_symbol = ?,
                alert_rules = ?,
                target_reached_notified = ?,
                last_check_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
        """, (
            final_current,
            final_target,
            final_name,
            final_image,
            final_currency,
            final_symbol,
            json.dumps(final_alert_rules),
            next_notified_value,
            data["id"],
            session['user_id']
        ))
        store_price_history(cursor, data["id"], final_current, final_currency, final_symbol)
        track_recent_view(cursor, session['user_id'], data["id"])
        if should_notify_now:
            create_in_app_notification(
                cursor,
                session['user_id'],
                data["id"],
                "Target reached",
                f"{final_name or 'Product'} reached your target price of {final_symbol or '$'}{final_target:.2f}."
            )
        updated_rows = cursor.rowcount
        conn.commit()
        conn.close()
        if updated_rows == 0:
            return api_error("Tracker not found", status=404)

        if should_notify_now and existing["email"]:
            try:
                send_price_target_reached_email(
                    to_email=existing["email"],
                    product_name=final_name,
                    product_url=existing["url"],
                    current_price=final_current,
                    target_price=final_target,
                    currency_symbol=final_symbol or '$'
                )
            except Exception as e:
                logger.warning("Price alert email send failed for tracker %s: %s", data["id"], e)

        return jsonify({"message": "Tracker updated"}), 200
    
    if request.method == 'DELETE':
        payload = get_request_json()
        tracker_id = payload.get('id')
        if not tracker_id:
            conn.close()
            return api_error("Tracker id is required", status=400)
        archive_requested = parse_bool(payload.get('archive'), default=False)
        if archive_requested:
            cursor.execute("UPDATE trackers SET archive_status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?", (tracker_id, session['user_id']))
        else:
            cursor.execute("DELETE FROM trackers WHERE id = ? AND user_id = ?", (tracker_id, session['user_id']))
        conn.commit()
        deleted = cursor.rowcount
        conn.close()
        if deleted == 0:
            return api_error("Tracker not found", status=404)
        return jsonify({"message": "Tracker archived" if archive_requested else "Tracker deleted"})


@app.route('/api/internal/run-price-checks', methods=['POST'])
def run_price_checks_endpoint():
    if not cron_signature_is_valid():
        return api_error("Unauthorized", status=401)

    limited, retry_after = is_rate_limited(limit=10, window_seconds=60)
    if limited:
        return too_many_requests(retry_after)

    try:
        limit = int(request.args.get('limit', 20))
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 100))

    owner_id = secrets.token_hex(12)
    if not acquire_job_lock("price_checks", owner_id, ttl_seconds=max(300, DEFAULT_TRACKER_CHECK_INTERVAL_SECONDS)):
        return jsonify({"success": False, "message": "Price check job is already running"}), 202

    try:
        summary = run_tracker_price_checks(limit=limit)
        return jsonify({"success": True, "summary": summary}), 200
    finally:
        release_job_lock("price_checks", owner_id)


@app.route('/api/trackers/<int:tracker_id>/history', methods=['GET'])
def tracker_history(tracker_id):
    if 'user_id' not in session:
        return api_error("Not logged in", status=401)

    days = request.args.get('days', '30')
    try:
        days = max(7, min(int(days), 365))
    except ValueError:
        days = 30

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.product_name, t.current_price, t.currency_symbol, t.created_at
        FROM trackers t
        WHERE t.id = ? AND t.user_id = ?
    """, (tracker_id, session['user_id']))
    tracker = cursor.fetchone()
    if not tracker:
        conn.close()
        return api_error("Tracker not found", status=404)

    cursor.execute("""
        SELECT price, currency, currency_symbol, recorded_at
        FROM price_history
        WHERE tracker_id = ? AND recorded_at >= datetime('now', ?)
        ORDER BY recorded_at ASC
    """, (tracker_id, f"-{days} days"))
    history = cursor.fetchall()
    insight = compute_buy_insight(history, float(tracker["current_price"]))
    track_recent_view(cursor, session['user_id'], tracker_id)
    conn.commit()
    conn.close()
    return jsonify({
        "trackerId": tracker_id,
        "productName": tracker["product_name"] or "Product",
        "currencySymbol": tracker["currency_symbol"] or "$",
        "history": [
            {
                "price": row["price"],
                "currency": row["currency"],
                "currencySymbol": row["currency_symbol"],
                "recordedAt": row["recorded_at"]
            } for row in history
        ],
        "insight": insight
    })


@app.route('/api/notification-preferences', methods=['GET', 'POST'])
def notification_preferences():
    if 'user_id' not in session:
        return api_error("Not logged in", status=401)

    conn = get_db_connection()
    cursor = conn.cursor()
    prefs = get_notification_preferences(cursor, session['user_id'])

    if request.method == 'POST':
        data = get_request_json()
        cursor.execute("""
            UPDATE notification_preferences
            SET push_enabled = ?, email_enabled = ?, in_app_enabled = ?, phone_enabled = ?, alert_drop_percentage = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (
            1 if parse_bool(data.get("pushEnabled"), default=bool(prefs["push_enabled"])) else 0,
            1 if parse_bool(data.get("emailEnabled"), default=bool(prefs["email_enabled"])) else 0,
            1 if parse_bool(data.get("inAppEnabled"), default=bool(prefs["in_app_enabled"])) else 0,
            1 if parse_bool(data.get("phoneEnabled"), default=bool(prefs["phone_enabled"])) else 0,
            max(1, min(float(data.get("alertDropPercentage", prefs["alert_drop_percentage"])), 90)),
            session['user_id']
        ))
        conn.commit()
        prefs = get_notification_preferences(cursor, session['user_id'])

    payload = {
        "pushEnabled": bool(prefs["push_enabled"]),
        "emailEnabled": bool(prefs["email_enabled"]),
        "inAppEnabled": bool(prefs["in_app_enabled"]),
        "phoneEnabled": bool(prefs["phone_enabled"]),
        "alertDropPercentage": prefs["alert_drop_percentage"]
    }
    conn.close()
    return jsonify(payload)


@app.route('/api/push-subscriptions', methods=['POST'])
def save_push_subscription():
    if 'user_id' not in session:
        return api_error("Not logged in", status=401)
    data = get_request_json()
    subscription = data.get("subscription")
    if not isinstance(subscription, dict) or not subscription.get("endpoint"):
        return api_error("Invalid push subscription", status=400)

    conn = get_db_connection()
    cursor = conn.cursor()
    get_notification_preferences(cursor, session['user_id'])
    cursor.execute("""
        INSERT INTO push_subscriptions (user_id, endpoint, subscription_json, user_agent, is_active, updated_at)
        VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(endpoint) DO UPDATE SET
            subscription_json = excluded.subscription_json,
            user_agent = excluded.user_agent,
            is_active = 1,
            updated_at = CURRENT_TIMESTAMP
    """, (
        session['user_id'],
        subscription.get("endpoint"),
        json.dumps(subscription),
        request.headers.get("User-Agent", "")[:500]
    ))
    cursor.execute("UPDATE notification_preferences SET push_enabled = 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (session['user_id'],))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route('/api/push-config', methods=['GET'])
def push_config():
    return jsonify({
        "publicKey": os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    })


@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    if 'user_id' not in session:
        return api_error("Not logged in", status=401)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, tracker_id, title, message, channel, is_read, created_at
        FROM notifications
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 30
    """, (session['user_id'],))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([
        {
            "id": row["id"],
            "trackerId": row["tracker_id"],
            "title": row["title"],
            "message": row["message"],
            "channel": row["channel"],
            "isRead": bool(row["is_read"]),
            "createdAt": row["created_at"]
        } for row in rows
    ])


@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
def mark_notification_read(notification_id):
    if 'user_id' not in session:
        return api_error("Not logged in", status=401)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notification_id, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route('/api/recently-viewed', methods=['GET'])
def get_recently_viewed():
    if 'user_id' not in session:
        return api_error("Not logged in", status=401)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT rv.tracker_id, rv.viewed_at, t.product_name, t.product_image, t.current_price, t.currency_symbol, t.url
        FROM recently_viewed rv
        JOIN trackers t ON t.id = rv.tracker_id
        WHERE rv.user_id = ?
        ORDER BY rv.viewed_at DESC
        LIMIT 8
    """, (session['user_id'],))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([
        {
            "trackerId": row["tracker_id"],
            "viewedAt": row["viewed_at"],
            "productName": row["product_name"],
            "productImage": row["product_image"],
            "currentPrice": row["current_price"],
            "currencySymbol": row["currency_symbol"],
            "url": row["url"]
        } for row in rows
    ])

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

SUPPORTED_STORES = {
    "amazon",
    "flipkart",
    "myntra",
    "ajio",
    "meesho",
    "snapdeal",
    "generic",
}


class ProductSnapshotError(Exception):
    def __init__(self, message, status=400, payload=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.payload = payload or {}


def parse_numeric_field(value, field_name, minimum=0.01):
    parsed = parse_price(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be a valid number")
    if parsed < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return round(float(parsed), 2)


def validate_product_url(url):
    cleaned_url = (url or "").strip()
    if not cleaned_url:
        return False, "URL is required", None
    if len(cleaned_url) > 2048:
        return False, "URL is too long", None

    parsed = urlparse(cleaned_url)
    if parsed.scheme not in {"http", "https"}:
        return False, "Only http and https product URLs are supported", None
    if parsed.username or parsed.password:
        return False, "URLs with embedded credentials are not allowed", None

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "Invalid URL", None
    if hostname.endswith(".onion"):
        return False, "Unsupported host", None
    if parsed.port and parsed.port not in {80, 443}:
        return False, "Only standard web ports are allowed", None

    if hostname in {"localhost", "0.0.0.0"} or hostname.endswith(".local"):
        return False, "Local URLs are not allowed", None

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, "Private network URLs are not allowed", None
    except ValueError:
        pass

    site, currency, symbol = get_site_info(cleaned_url)
    return True, None, {
        "url": cleaned_url,
        "site": site,
        "currency": currency,
        "currency_symbol": symbol,
        "is_supported_store": True,
        "is_known_store": site in SUPPORTED_STORES and site != "generic"
    }


def parse_alert_rules(payload, default_target=None):
    rules = []
    if default_target is not None:
        rules.append({"type": "target_price", "value": round(float(default_target), 2)})

    raw_rules = payload.get("alertRules")
    if isinstance(raw_rules, list):
        for rule in raw_rules[:5]:
            if not isinstance(rule, dict):
                continue
            rule_type = str(rule.get("type") or "").strip().lower()
            try:
                rule_value = round(float(rule.get("value")), 2)
            except (TypeError, ValueError):
                continue
            if rule_type in {"target_price", "percentage_drop"} and rule_value > 0:
                rules.append({"type": rule_type, "value": rule_value})

    deduped = []
    seen = set()
    for rule in rules:
        key = (rule["type"], rule["value"])
        if key in seen:
            continue
        deduped.append(rule)
        seen.add(key)
    return deduped


def store_price_history(cursor, tracker_id, price, currency, currency_symbol):
    cursor.execute("""
        SELECT price, recorded_at FROM price_history
        WHERE tracker_id = ?
        ORDER BY recorded_at DESC
        LIMIT 1
    """, (tracker_id,))
    latest = cursor.fetchone()
    if latest and float(latest["price"]) == float(price):
        return
    cursor.execute("""
        INSERT INTO price_history (tracker_id, price, currency, currency_symbol)
        VALUES (?, ?, ?, ?)
    """, (tracker_id, price, currency, currency_symbol))


def create_in_app_notification(cursor, user_id, tracker_id, title, message, channel="in_app"):
    cursor.execute("""
        INSERT INTO notifications (user_id, tracker_id, title, message, channel)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, tracker_id, title[:120], message[:500], channel))


def track_recent_view(cursor, user_id, tracker_id):
    cursor.execute("""
        INSERT INTO recently_viewed (user_id, tracker_id, viewed_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, tracker_id) DO UPDATE SET viewed_at = CURRENT_TIMESTAMP
    """, (user_id, tracker_id))


def get_notification_preferences(cursor, user_id):
    cursor.execute("""
        SELECT user_id, push_enabled, email_enabled, in_app_enabled, phone_enabled, alert_drop_percentage
        FROM notification_preferences
        WHERE user_id = ?
    """, (user_id,))
    prefs = cursor.fetchone()
    if prefs:
        return prefs
    cursor.execute("""
        INSERT INTO notification_preferences (user_id, push_enabled, email_enabled, in_app_enabled, phone_enabled, alert_drop_percentage)
        VALUES (?, 0, 1, 1, 0, 10)
    """, (user_id,))
    cursor.execute("""
        SELECT user_id, push_enabled, email_enabled, in_app_enabled, phone_enabled, alert_drop_percentage
        FROM notification_preferences
        WHERE user_id = ?
    """, (user_id,))
    return cursor.fetchone()


def compute_buy_insight(history_points, current_price):
    if not history_points:
        return {"label": "Start tracking", "confidence": 55, "summary": "Need more price history to estimate buying windows."}

    prices = [float(point["price"]) for point in history_points]
    lowest = min(prices)
    highest = max(prices)
    avg_price = sum(prices) / len(prices)
    if current_price <= lowest * 1.02:
        return {"label": "Buy now", "confidence": 88, "summary": "Current price is near the tracked low."}
    if current_price <= avg_price * 0.97:
        return {"label": "Good deal", "confidence": 76, "summary": "Current price is below the tracked average."}
    if current_price >= highest * 0.97:
        return {"label": "Wait", "confidence": 80, "summary": "Current price is close to the recent high."}
    return {"label": "Watch closely", "confidence": 67, "summary": "Price is mid-range. A better drop may still come."}

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
        return 'generic', inferred_currency, currency_symbol_for(inferred_currency)


def create_retry_session(site):
    session_client = requests.Session()
    retries = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "HEAD"])
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=8, pool_maxsize=8)
    session_client.mount("https://", adapter)
    session_client.mount("http://", adapter)
    if site == 'amazon':
        session_client.cookies.set("i18n-prefs", "INR")
        session_client.cookies.set("lc-main", "en_IN")
    return session_client

def scrape_price(soup, site, currency_symbol):
    """Enhanced price scraper with site-specific selectors"""
    
    # Site-specific selectors (highest priority)
    site_selectors = {
        'amazon': [
            "span.a-price span.a-offscreen",
            "span.a-price-whole",
            "span[data-testid='priceblock_ourprice']",
            "#priceblock_ourprice",
            ".a-price-symbol + .a-price-whole",
            ".dealprice + .a-price-whole"
        ],
        'flipkart': [
            "._30jeq3",
            ".Nx9bqj",
            "._25b18c ._30jeq3",
            "[data-testid='final-price']",
            ".B_NuCI[data-testid*='price']"
        ],
        'myntra': [
            "span.pdp-price",
            ".pdp-priceSmall",
            "[data-testid='pdp-price']",
            ".priceRange__currentPrice"
        ],
        'ajio': [
            "span.prod-price",
            ".prod-price",
            "[data-testid='product-price']"
        ],
        'meesho': [
            "h3.Sc-product-price",
            "[data-testid='product-price']",
            ".product-price"
        ],
        'snapdeal': [
            "span.product-price",
            ".product-price",
            "[data-testid='product-price']"
        ],
        'reliance': [
            "._1U1JPL",
            "[data-testid='price']",
            ".price-block .current-price"
        ],
        'generic': []
    };
    
    # Site-specific selectors first
    if site in site_selectors:
        for selector in site_selectors[site]:
            elem = soup.select_one(selector)
            if elem:
                value = elem.get_text(strip=True) or elem.get('content')
                price = parse_price(value)
                if price and 1 <= price <= 1000000:
                    return price
    
    # Universal selectors (fallback)
    universal_selectors = [
        'meta[property="product:price:amount"]',
        'meta[itemprop="price"]',
        '[itemprop="price"]',
        '[data-price]',
        '[data-current-price]',
        '[class*="price"]',
        '.price',
        '.product-price',
        '.sale-price'
    ]
    
    for selector in universal_selectors:
        elem = soup.select_one(selector)
        if elem:
            value = elem.get('content') or elem.get('data-price') or elem.get('data-sale-price') or elem.get_text(strip=True)
            price = parse_price(value)
            if price and 1 <= price <= 1000000:
                return price
    
    return None
    
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

    generic_text_blocks = []
    if soup:
        generic_text_blocks.extend([
            soup.get_text(" ", strip=True),
            " ".join(node.get("content", "") for node in soup.find_all("meta") if node.get("content"))
        ])

    for block in generic_text_blocks:
        if not block:
            continue
        candidates = extract_price_candidates(block)
        if candidates:
            sensible = [candidate for candidate in candidates if 1 <= candidate <= 10000000]
            if sensible:
                return min(sensible)
    
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


def extract_product_name(soup):
    product_name = "Product"
    if soup and soup.title and soup.title.get_text():
        title = soup.title.get_text().strip()
        product_name = re.sub(
            r'\s*[-|]\s*(Amazon|Flipkart|Myntra|Ajio|Meesho|Snapdeal)\s*$',
            '',
            title,
            flags=re.IGNORECASE
        ).strip() or product_name
    if soup:
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            product_name = og_title.get("content").strip()
    return product_name


def extract_product_image(soup):
    if not soup:
        return None
    selectors = [
        ("meta", {"property": "og:image"}, "content"),
        ("meta", {"name": "twitter:image"}, "content"),
        ("meta", {"itemprop": "image"}, "content"),
    ]
    for tag_name, attrs, attr in selectors:
        node = soup.find(tag_name, attrs=attrs)
        if node and node.get(attr):
            return str(node.get(attr)).strip()
    img = soup.find("img")
    if img and img.get("src"):
        return str(img.get("src")).strip()
    return None


def fetch_product_snapshot(url):
    valid, error_message, url_meta = validate_product_url(url)
    if not valid:
        raise ProductSnapshotError(error_message, status=400)

    cache_key = url_meta["url"]
    cached_snapshot = cache_get(cache_key)
    if cached_snapshot:
        cached_snapshot["cached"] = True
        return cached_snapshot

    site = url_meta["site"]
    currency = url_meta["currency"]
    currency_symbol = url_meta["currency_symbol"]
    session_client = create_retry_session(site)
    fetch_candidates = get_fetch_candidates(url_meta["url"], site)

    response = None
    saw_captcha = False
    header_variants = [
        {},
        {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"},
        {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"},
    ]

    for candidate_url in fetch_candidates:
        for variant in header_variants:
            headers = get_request_headers(candidate_url, site)
            headers.update(variant)
            logger.info("Scrape attempt site=%s url=%s", site, candidate_url)
            current_response = session_client.get(candidate_url, headers=headers, timeout=20, allow_redirects=True)
            current_html = current_response.text or ''
            response = current_response

            if is_captcha_like_response(current_response.status_code, current_html):
                saw_captcha = True
                time.sleep(0.7)
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
                result = {
                    "price": current_price,
                    "currency": detected_currency,
                    "currency_symbol": detected_symbol,
                    "productName": extract_product_name(current_soup),
                    "productImage": extract_product_image(current_soup),
                    "supportedStore": url_meta["is_supported_store"],
                    "knownStore": url_meta.get("is_known_store", False),
                    "site": site,
                    "cached": False
                }
                cache_set(cache_key, result)
                return result

    if response is None:
        if saw_captcha:
            raise ProductSnapshotError(
                "Website temporarily blocked automated access (captcha). Please retry in a minute with a direct product URL.",
                status=429,
                payload={"suggestedUrl": normalize_product_url(url_meta["url"], site)}
            )
        raise ProductSnapshotError("Could not fetch product page. Please verify the URL and try again.", status=502)

    html_text = response.text if response is not None else ""
    if is_captcha_like_response(response.status_code if response is not None else 0, html_text):
        raise ProductSnapshotError(
            "Website temporarily blocked automated access (captcha). Please retry in a minute with a direct product URL.",
            status=429,
            payload={"suggestedUrl": normalize_product_url(url_meta["url"], site)}
        )

    hint = "Use a direct product page URL with a visible price."
    if not url_meta.get("is_known_store", False):
        hint = "This page is being handled by the global generic scraper. Use a direct product page with a visible price, currency, and product title."
    raise ProductSnapshotError(
        "Could not find price on this page. " + hint,
        status=404,
        payload={"supportedStore": url_meta["is_supported_store"], "knownStore": url_meta.get("is_known_store", False), "site": site}
    )


def validate_tracker_input(data, require_id=False):
    payload = data or {}
    tracker_id = payload.get("id")
    if require_id and not tracker_id:
        raise ValueError("Tracker id is required")

    cleaned = {}
    if tracker_id is not None:
        try:
            cleaned["id"] = int(tracker_id)
        except (TypeError, ValueError):
            raise ValueError("Tracker id must be a valid integer")

    if payload.get("url") is not None:
        valid, error_message, url_meta = validate_product_url(payload.get("url"))
        if not valid:
            raise ValueError(error_message)
        cleaned["url"] = url_meta["url"]

    if payload.get("currentPrice") is not None:
        cleaned["currentPrice"] = parse_numeric_field(payload.get("currentPrice"), "Current price")
    if payload.get("targetPrice") is not None:
        cleaned["targetPrice"] = parse_numeric_field(payload.get("targetPrice"), "Target price")

    if "currentPrice" in cleaned and "targetPrice" in cleaned and cleaned["targetPrice"] > cleaned["currentPrice"] * 10:
        raise ValueError("Target price looks too high compared with the current price")

    if payload.get("productImage") is not None:
        cleaned["productImage"] = str(payload.get("productImage") or "").strip()[:1000] or None

    if require_id:
        if "productName" in payload:
            cleaned["productName"] = str(payload.get("productName") or "Product").strip()[:255]
        if "currency" in payload:
            cleaned["currency"] = str(payload.get("currency") or "USD").strip().upper()[:5]
        if "currencySymbol" in payload:
            base_currency = cleaned.get("currency") or str(payload.get("currency") or "USD").strip().upper()[:5]
            cleaned["currencySymbol"] = str(payload.get("currencySymbol") or currency_symbol_for(base_currency)).strip()[:5]
        if "targetPrice" in cleaned:
            cleaned["alertRules"] = parse_alert_rules(payload, default_target=cleaned["targetPrice"])
    else:
        cleaned["productName"] = str(payload.get("productName") or "Product").strip()[:255]
        cleaned["currency"] = str(payload.get("currency") or "USD").strip().upper()[:5]
        cleaned["currencySymbol"] = str(payload.get("currencySymbol") or currency_symbol_for(cleaned["currency"])).strip()[:5]
        cleaned["alertRules"] = parse_alert_rules(payload, default_target=cleaned.get("targetPrice"))
    return cleaned


def notify_if_target_reached(user_email, tracker_url, tracker_name, old_price, new_price, target_price, currency_symbol):
    if float(old_price) > float(target_price) and float(new_price) <= float(target_price) and user_email:
        return send_price_target_reached_email(
            to_email=user_email,
            product_name=tracker_name,
            product_url=tracker_url,
            current_price=float(new_price),
            target_price=float(target_price),
            currency_symbol=currency_symbol or '$'
        )
    return False


def send_push_notifications(cursor, user_id, title, message, url):
    cursor.execute("""
        SELECT endpoint, subscription_json
        FROM push_subscriptions
        WHERE user_id = ? AND is_active = 1
    """, (user_id,))
    subscriptions = cursor.fetchall()
    if not subscriptions:
        return 0

    try:
        from pywebpush import webpush, WebPushException  # type: ignore
    except Exception:
        logger.info("pywebpush not installed; skipping remote push delivery")
        return 0

    vapid_private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    vapid_email = os.environ.get("VAPID_CLAIMS_SUB", "mailto:support@pricealerter.in").strip()
    if not vapid_private_key:
        logger.info("VAPID_PRIVATE_KEY missing; skipping remote push delivery")
        return 0

    sent = 0
    payload = json.dumps({"title": title, "body": message, "url": url})
    for row in subscriptions:
        try:
            webpush(
                subscription_info=json.loads(row["subscription_json"]),
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": vapid_email}
            )
            sent += 1
        except Exception as e:
            logger.warning("Push delivery failed for endpoint=%s: %s", row["endpoint"], e)
            cursor.execute("UPDATE push_subscriptions SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE endpoint = ?", (row["endpoint"],))
    return sent


def acquire_job_lock(job_name, owner_id, ttl_seconds=900):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.utcnow()
    locked_until = now + timedelta(seconds=ttl_seconds)
    cursor.execute("""
        INSERT INTO job_locks (job_name, locked_until, heartbeat_at, owner_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(job_name) DO UPDATE SET
            locked_until = excluded.locked_until,
            heartbeat_at = excluded.heartbeat_at,
            owner_id = excluded.owner_id
        WHERE job_locks.locked_until IS NULL OR job_locks.locked_until < ?
    """, (job_name, locked_until.isoformat(), now.isoformat(), owner_id, now.isoformat()))
    acquired = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return acquired


def release_job_lock(job_name, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE job_locks
        SET locked_until = NULL, heartbeat_at = ?, owner_id = NULL
        WHERE job_name = ? AND owner_id = ?
    """, (datetime.utcnow().isoformat(), job_name, owner_id))
    conn.commit()
    conn.close()


def run_tracker_price_checks(limit=20):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.user_id, t.url, t.product_name, t.current_price, t.target_price, t.currency, t.currency_symbol, t.alert_rules,
               COALESCE(t.target_reached_notified, 0) AS target_reached_notified, u.email, u.phone,
               t.last_checked_at, t.created_at
        FROM trackers t
        JOIN users u ON u.id = t.user_id
        WHERE t.last_checked_at IS NULL
           OR t.last_checked_at <= datetime('now', ?)
        ORDER BY COALESCE(t.last_checked_at, t.created_at) ASC, t.created_at ASC
        LIMIT ?
    """, (f"-{DEFAULT_TRACKER_CHECK_INTERVAL_SECONDS} seconds", limit))
    tracker_rows = cursor.fetchall()

    checked = 0
    updated = 0
    alerts_sent = 0
    failures = []

    for tracker in tracker_rows:
        checked += 1
        try:
            snapshot = fetch_product_snapshot(tracker["url"])
            new_price = round(float(snapshot["price"]), 2)
            cursor.execute("""
                SELECT current_price, target_price, target_reached_notified, currency_symbol, product_name, email, phone, url
                FROM (
                    SELECT t.current_price, t.target_price, COALESCE(t.target_reached_notified, 0) AS target_reached_notified,
                           t.currency_symbol, t.product_name, u.email, u.phone, t.url
                    FROM trackers t
                    JOIN users u ON u.id = t.user_id
                    WHERE t.id = ?
                )
            """, (tracker["id"],))
            current_state = cursor.fetchone()
            if not current_state:
                continue

            old_price = round(float(current_state["current_price"]), 2)
            current_target = round(float(current_state["target_price"]), 2)
            should_notify = old_price > current_target and new_price <= current_target
            next_notified_value = 1 if should_notify else (0 if new_price > current_target else int(current_state["target_reached_notified"] or 0))
            current_alert_rules = []
            try:
                current_alert_rules = json.loads(tracker["alert_rules"]) if tracker.get("alert_rules") else []
            except Exception:
                current_alert_rules = []
            percentage_drop = 0
            if old_price > 0:
                percentage_drop = round(((old_price - new_price) / old_price) * 100, 2)
            cursor.execute("""
                SELECT price, recorded_at FROM price_history
                WHERE tracker_id = ?
                ORDER BY recorded_at DESC
                LIMIT 12
            """, (tracker["id"],))
            recent_history = cursor.fetchall()
            insight = compute_buy_insight(recent_history, new_price)

            cursor.execute("""
                UPDATE trackers
                SET current_price = ?, product_name = ?, currency = ?, currency_symbol = ?, target_reached_notified = ?,
                    product_image = COALESCE(?, product_image),
                    best_time_to_buy = ?,
                    last_checked_at = CURRENT_TIMESTAMP, last_check_error = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                new_price,
                snapshot.get("productName") or tracker["product_name"],
                snapshot.get("currency") or tracker["currency"],
                snapshot.get("currency_symbol") or tracker["currency_symbol"],
                next_notified_value,
                snapshot.get("productImage"),
                json.dumps(insight),
                tracker["id"]
            ))
            store_price_history(cursor, tracker["id"], new_price, snapshot.get("currency") or tracker["currency"], snapshot.get("currency_symbol") or tracker["currency_symbol"])
            updated += 1

            if should_notify:
                prefs = get_notification_preferences(cursor, tracker["user_id"])
                notification_title = "Price target reached"
                notification_message = f"{snapshot.get('productName') or current_state['product_name'] or 'Product'} is now {snapshot.get('currency_symbol') or current_state['currency_symbol'] or '$'}{new_price:.2f}."
                if prefs and bool(prefs["in_app_enabled"]):
                    create_in_app_notification(cursor, tracker["user_id"], tracker["id"], notification_title, notification_message)
                push_sent = 0
                if prefs and bool(prefs["push_enabled"]):
                    push_sent = send_push_notifications(cursor, tracker["user_id"], notification_title, notification_message, current_state["url"])
                if prefs and bool(prefs["email_enabled"]):
                    if notify_if_target_reached(
                        current_state["email"],
                        current_state["url"],
                        snapshot.get("productName") or current_state["product_name"] or "Product",
                        old_price,
                        new_price,
                        current_target,
                        snapshot.get("currency_symbol") or current_state["currency_symbol"]
                    ):
                        alerts_sent += 1
                elif push_sent:
                    alerts_sent += 1
                if current_state["phone"] and prefs and bool(prefs["phone_enabled"]):
                    phone_sent = send_phone_notification(
                        current_state["phone"],
                        (
                            f"Price dropped alert\n"
                            f"{snapshot.get('productName') or current_state['product_name'] or 'Product'}\n"
                            f"{snapshot.get('currency_symbol') or current_state['currency_symbol'] or '$'}{old_price:.2f} -> "
                            f"{snapshot.get('currency_symbol') or current_state['currency_symbol'] or '$'}{new_price:.2f}\n"
                            f"{current_state['url']}"
                        ),
                        prefer_whatsapp=True
                    )
                    if phone_sent:
                        create_in_app_notification(
                            cursor,
                            tracker["user_id"],
                            tracker["id"],
                            "WhatsApp alert sent",
                            f"WhatsApp notification delivered for {snapshot.get('productName') or current_state['product_name'] or 'Product'}.",
                            channel="whatsapp"
                        )
            else:
                percentage_rules = [float(rule.get("value")) for rule in current_alert_rules if rule.get("type") == "percentage_drop"]
                drop_threshold = min(percentage_rules) if percentage_rules else float((get_notification_preferences(cursor, tracker["user_id"])["alert_drop_percentage"]))
                if percentage_drop >= drop_threshold:
                    message = f"{snapshot.get('productName') or current_state['product_name'] or 'Product'} dropped {percentage_drop:.1f}% to {snapshot.get('currency_symbol') or current_state['currency_symbol'] or '$'}{new_price:.2f}."
                    create_in_app_notification(cursor, tracker["user_id"], tracker["id"], "Price drop detected", message)
        except ProductSnapshotError as e:
            cursor.execute("""
                UPDATE trackers
                SET last_checked_at = CURRENT_TIMESTAMP, last_check_error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (e.message[:500], tracker["id"]))
            failures.append({
                "trackerId": tracker["id"],
                "url": tracker["url"],
                "error": e.message,
                "status": e.status
            })
        except Exception:
            logger.exception("Unexpected tracker refresh failure for %s", tracker["url"])
            cursor.execute("""
                UPDATE trackers
                SET last_checked_at = CURRENT_TIMESTAMP, last_check_error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, ("Unexpected refresh failure", tracker["id"]))
            failures.append({
                "trackerId": tracker["id"],
                "url": tracker["url"],
                "error": "Unexpected refresh failure",
                "status": 500
            })

    conn.commit()
    conn.close()
    return {
        "checked": checked,
        "updated": updated,
        "alertsSent": alerts_sent,
        "failures": failures,
    }


@app.route('/get-price', methods=['POST'])
def get_price():
    data = get_request_json()
    url = (data.get('url') or '').strip()

    if not url:
        return api_error("URL is required", status=400)

    limited, retry_after = is_rate_limited(limit=25, window_seconds=60)
    if limited:
        return too_many_requests(retry_after)

    if url.lower().startswith('test://'):
        mock_price = round(random.uniform(10, 500), 2)
        return jsonify({
            "price": mock_price,
            "currency": "USD",
            "currency_symbol": "$",
            "productName": "Test Product",
            "isTestMode": True
        })

    try:
        snapshot = fetch_product_snapshot(url)
        return jsonify(snapshot)
    except ProductSnapshotError as e:
        payload = {"error": e.message}
        payload.update(e.payload)
        return jsonify(payload), e.status
    except requests.exceptions.Timeout:
        return api_error("Request timed out. Please try again.", status=504)
    except requests.exceptions.ConnectionError:
        return api_error("Could not connect to the website. Please check the URL.", status=502)
    except Exception:
        logger.exception("Unexpected get-price failure")
        return api_error("Unexpected server error while fetching the product price.", status=500)

# ==================== STATIC FILES ====================

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename, max_age=0)


@app.route('/service-worker.js')
def service_worker():
    response = make_response(send_from_directory('static', 'service-worker.js'))
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    return response


@app.route('/favicon.ico')
def favicon():
    response = make_response(send_from_directory('static', 'favicon.svg'))
    response.headers['Cache-Control'] = 'public, max-age=86400'
    response.headers['Content-Type'] = 'image/svg+xml; charset=utf-8'
    return response


@app.route('/site.webmanifest')
def site_webmanifest():
    response = make_response(send_from_directory('static', 'site.webmanifest'))
    response.headers['Cache-Control'] = 'public, max-age=86400'
    response.headers['Content-Type'] = 'application/manifest+json; charset=utf-8'
    return response


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


@app.errorhandler(404)
def handle_not_found(error):
    if request.path.startswith('/api/'):
        return api_error("Endpoint not found", status=404)
    return render_template('error.html', error="Page not found"), 404


@app.errorhandler(500)
def handle_server_error(error):
    logger.exception("Unhandled application error")
    if request.path.startswith('/api/'):
        return api_error("Internal server error", status=500)
    return render_template('error.html', error="Something went wrong. Please try again."), 500

@app.after_request
def add_no_cache_headers(response):
    path = request.path or '/'
    is_html = bool(response.content_type and response.content_type.startswith('text/html'))

    public_indexable_paths = {
        '/', '/home', '/about', '/contact', '/privacy', '/terms', '/blog',
        '/blog/how-to-track-product-prices-online',
        '/blog/best-price-alert-tools-india',
        '/blog/save-money-price-trackers',
        '/blog/amazon-price-history',
        '/amp', '/amp/home'
    }
    explicit_noindex_paths = {
        '/login', '/signup', '/forgot-password', '/reset-password', '/dashboard', '/error'
    }

    # Make indexing intent explicit to Google for all main pages.
    if path in public_indexable_paths and response.status_code < 400:
        response.headers['X-Robots-Tag'] = 'index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1'
    elif (
        path in explicit_noindex_paths
        or path.startswith('/dashboard/')
        or path.startswith('/api/')
        or response.status_code >= 400
    ):
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'

    # Public pages should be cacheable; private/auth/error pages should not.
    if is_html:
        if path in public_indexable_paths and response.status_code < 400:
            response.headers['Cache-Control'] = 'public, max-age=300'
            response.headers.pop('Pragma', None)
            response.headers.pop('Expires', None)
        else:
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
