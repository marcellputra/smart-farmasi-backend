import os

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'), override=True)
except ImportError:
    pass

SECRET_KEY = os.environ.get('SECRET_KEY')
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
SQLALCHEMY_TRACK_MODIFICATIONS = False
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')
NEWS_API_KEY = os.environ.get('NEWS_API_KEY') or ''
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') or ''
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY') or ''
OPENROUTER_MODEL = os.environ.get('OPENROUTER_MODEL') or 'google/gemini-2.5-flash'
SEARCH_SERVICE_URL = os.environ.get('SEARCH_SERVICE_URL') or 'http://127.0.0.1:8000'
GROQ_API_KEY = os.environ.get('GROQ_API_KEY') or ''
GROQ_MODEL = os.environ.get('GROQ_MODEL') or 'llama-3.3-70b-versatile'

GOOGLE_WEB_CLIENT_ID = (
    os.environ.get('GOOGLE_WEB_CLIENT_ID')
    or os.environ.get('GOOGLE_CLIENT_ID')
    or '691571373089-t2r3oajabh78af9r1veh4oc5hhb4ebjg.apps.googleusercontent.com'
)
GOOGLE_ANDROID_CLIENT_ID = (
    os.environ.get('GOOGLE_ANDROID_CLIENT_ID')
    or '691571373089-0bel2hsakmfo8u8841oljlc0iruhk8q1.apps.googleusercontent.com'
)
GOOGLE_CLIENT_IDS = [
    client_id.strip()
    for client_id in (
        os.environ.get('GOOGLE_CLIENT_IDS')
        or f'{GOOGLE_WEB_CLIENT_ID},{GOOGLE_ANDROID_CLIENT_ID}'
    ).split(',')
    if client_id.strip()
]

MAIL_USERNAME = os.environ.get('MAIL_USERNAME') or ''
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD') or ''
MAIL_HOST = os.environ.get('MAIL_HOST') or 'smtp.gmail.com'
MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
MAIL_USE_TLS = (os.environ.get('MAIL_USE_TLS') or 'true').lower() in ('true', '1', 'yes', 'on')
MAIL_USE_SSL = (os.environ.get('MAIL_USE_SSL') or 'false').lower() in ('true', '1', 'yes', 'on')
MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or MAIL_USERNAME

OTP_EXPIRES_SECONDS = int(os.environ.get('OTP_EXPIRES_SECONDS') or 180)
OTP_RESEND_COOLDOWN_SECONDS = int(os.environ.get('OTP_RESEND_COOLDOWN_SECONDS') or 180)
OTP_MAX_ATTEMPTS = int(os.environ.get('OTP_MAX_ATTEMPTS') or 5)
ADMIN_OTP_REQUIRED = (os.environ.get('ADMIN_OTP_REQUIRED') or 'true').lower() in ('true', '1', 'yes', 'on')
OTP_BYPASS_EMAILS = {
    email.strip().lower()
    for email in (os.environ.get('OTP_BYPASS_EMAILS') or 'admin1@gmail.com').split(',')
    if email.strip()
}

PROFILE_PHOTO_UPLOAD_SUBDIR = os.environ.get(
    'PROFILE_PHOTO_UPLOAD_SUBDIR',
    'uploads/profile_pictures',
)
PROFILE_PHOTO_MAX_BYTES = int(os.environ.get('PROFILE_PHOTO_MAX_BYTES') or 2 * 1024 * 1024)
PROFILE_PHOTO_ALLOWED_EXTENSIONS = {
    ext.strip().lower()
    for ext in (os.environ.get('PROFILE_PHOTO_ALLOWED_EXTENSIONS') or 'jpg,jpeg,png,webp').split(',')
    if ext.strip()
}
