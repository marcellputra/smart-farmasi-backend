from flask_restful import Resource
from flask import current_app, request, url_for
from flask_jwt_extended import create_access_token, decode_token, jwt_required, get_jwt_identity
from app.models import db, User, UserActivity, EmailOTP
from app.services.email_service import EmailDeliveryError, send_otp_email
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from werkzeug.utils import secure_filename
import datetime
import os
import random
import re
import uuid
import firebase_admin
from firebase_admin import auth as firebase_auth

# Initialize firebase_admin for Web fallback verification
if not firebase_admin._apps:
    try:
        firebase_admin.initialize_app()
    except Exception as e:
        print(f"Firebase Admin initialization warning: {e}")


OTP_PURPOSE_VERIFY_EMAIL = 'verify_email'
OTP_PURPOSE_PASSWORD_RESET = 'password_reset'
OTP_PURPOSE_EMAIL_CHANGE = 'email_change'
OTP_PURPOSE_PASSWORD_CHANGE = 'password_change'
OTP_PURPOSE_ADMIN_LOGIN = 'admin_login'
OTP_PURPOSE_APP_PASSWORD = 'app_password'
OTP_PURPOSE_DELETE_ACCOUNT = 'delete_account'
JWT_PURPOSE_APP_PASSWORD_SETUP = 'app_password_setup'


def _normalize_email(email):
    return (email or '').strip().lower()


def _verify_google_token(token):
    token = (token or '').strip()
    if not token:
        raise ValueError('Token Google wajib dikirim')

    client_ids = current_app.config.get('GOOGLE_CLIENT_IDS') or []
    last_error = None
    
    # 1. Try as standard Google ID Token (Mobile / Direct Web)
    for client_id in client_ids:
        try:
            id_info = google_id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                client_id,
                clock_skew_in_seconds=60,
            )
            if id_info.get('iss') in {
                'accounts.google.com',
                'https://accounts.google.com',
            }:
                return id_info
        except Exception as e:
            last_error = e
            continue

    # 2. Try as Firebase ID Token (Web Fallback via Popup)
    try:
        id_info = firebase_auth.verify_id_token(token)
        # Firebase token format: 'iss' matches 'https://securetoken.google.com/<project-id>'
        # Normalize fields to match google-auth format if needed (email is usually same)
        return id_info
    except Exception as e:
        # If both fail, raise the last relevant error
        raise last_error or e


def _is_otp_bypass_email(email):
    bypass_emails = current_app.config.get('OTP_BYPASS_EMAILS', set())
    return _normalize_email(email) in bypass_emails


def _generate_otp_code():
    return f'{random.SystemRandom().randint(0, 999999):06d}'


def _otp_expiry_time():
    expires_seconds = current_app.config.get('OTP_EXPIRES_SECONDS', 60)
    return datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_seconds)


def _expire_existing_otps(email, purpose=None, user_id=None):
    now = datetime.datetime.utcnow()
    query = EmailOTP.query.filter_by(email=_normalize_email(email), is_used=False)
    if purpose:
        query = query.filter_by(purpose=purpose)
    if user_id:
        query = query.filter_by(user_id=user_id)

    query.update({
        'is_used': True,
        'expires_at': now,
        'updated_at': now,
    }, synchronize_session=False)


def cleanup_expired_otps(app=None, retention_days=3):
    """Menghapus riwayat OTP yang sudah lebih dari X hari."""
    def _run_cleanup():
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
        deleted = EmailOTP.query.filter(EmailOTP.created_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
        return deleted

    if app:
        with app.app_context():
            return _run_cleanup()
    else:
        return _run_cleanup()


def _create_otp_for_user(user, purpose=OTP_PURPOSE_VERIFY_EMAIL, to_email=None):
    email = _normalize_email(to_email or user.email)
    _expire_existing_otps(email, purpose=purpose, user_id=user.id)
    otp_code = _generate_otp_code()
    otp = EmailOTP(
        user_id=user.id,
        email=email,
        purpose=purpose,
        expires_at=_otp_expiry_time(),
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow(),
    )
    otp.set_code(otp_code)
    db.session.add(otp)
    return otp, otp_code


def _latest_otp(email, purpose=OTP_PURPOSE_VERIFY_EMAIL, user_id=None, only_unused=False):
    query = EmailOTP.query.filter_by(email=_normalize_email(email), purpose=purpose)
    if user_id:
        query = query.filter_by(user_id=user_id)
    if only_unused:
        query = query.filter_by(is_used=False)
    return query.order_by(EmailOTP.created_at.desc()).first()


def _resend_retry_after(email, purpose=OTP_PURPOSE_VERIFY_EMAIL, user_id=None):
    latest_otp = _latest_otp(email, purpose=purpose, user_id=user_id)
    if not latest_otp or not latest_otp.created_at:
        return 0

    cooldown_seconds = current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 30)
    cooldown_until = latest_otp.created_at + datetime.timedelta(seconds=cooldown_seconds)
    remaining = (cooldown_until - datetime.datetime.utcnow()).total_seconds()
    return max(0, int(remaining) + 1)


def _send_user_otp(user, purpose=OTP_PURPOSE_VERIFY_EMAIL, to_email=None):
    recipient_email = _normalize_email(to_email or user.email)
    otp, otp_code = _create_otp_for_user(user, purpose=purpose, to_email=recipient_email)
    send_otp_email(recipient_email, otp_code, user.name, purpose=purpose)
    return otp


def _validate_password_strength(password):
    if not password:
        return 'Password wajib diisi'
    if len(password) < 8:
        return 'Password minimal 8 karakter'
    return None


def _validate_otp_or_error(user, email, otp_code, purpose):
    email = _normalize_email(email)
    otp_code = str(otp_code or '').strip()

    if not email or not otp_code:
        return None, ({'message': 'Email dan kode OTP wajib diisi'}, 400)

    if not re.fullmatch(r'\d{6}', otp_code):
        return None, ({'message': 'Kode OTP harus berisi 6 digit angka'}, 400)

    otp = _latest_otp(email, purpose=purpose, user_id=user.id, only_unused=True)
    if not otp:
        return None, ({'message': 'Kode OTP tidak ditemukan. Silakan kirim ulang kode.'}, 404)

    max_attempts = current_app.config.get('OTP_MAX_ATTEMPTS', 5)
    if otp.attempts >= max_attempts:
        otp.is_used = True
        db.session.commit()
        return None, ({'message': 'Percobaan OTP terlalu banyak. Silakan kirim ulang kode.'}, 429)

    if otp.is_expired:
        otp.is_used = True
        db.session.commit()
        return None, ({'message': 'Kode OTP sudah expired. Silakan kirim ulang kode.'}, 400)

    if not otp.check_code(otp_code):
        otp.attempts += 1
        remaining_attempts = max_attempts - otp.attempts
        if remaining_attempts <= 0:
            otp.is_used = True
            db.session.commit()
            return None, ({'message': 'Percobaan OTP terlalu banyak. Silakan kirim ulang kode.'}, 429)

        db.session.commit()
        return None, ({
            'message': f'Kode OTP salah. Sisa percobaan: {remaining_attempts}.',
            'remaining_attempts': remaining_attempts,
        }, 400)

    otp.is_used = True
    otp.updated_at = datetime.datetime.utcnow()
    return otp, None


def _profile_picture_url(user):
    if not user.profile_picture:
        return None
    return url_for('static', filename=user.profile_picture, _external=False)


def _serialize_user(user):
    return {
        'id': user.id,
        'name': user.name,
        'email': user.email,
        'role': user.role,
        'provider': user.login_provider,
        'has_password': bool(user.password_hash),
        'is_verified': user.is_verified,
        'email_verified_at': user.email_verified_at.isoformat() if user.email_verified_at else None,
        'profile_picture': user.profile_picture,
        'profile_picture_url': _profile_picture_url(user),

        # face login state
        'face_prompt_shown': user.face_prompt_shown,
        'face_registered': bool(user.face_recognition and user.face_recognition.is_active),
    }


def _profile_upload_dir():
    subdir = current_app.config.get('PROFILE_PHOTO_UPLOAD_SUBDIR', 'uploads/profile_pictures')
    return os.path.join(current_app.static_folder, *subdir.replace('\\', '/').split('/'))


def _profile_picture_path(relative_path):
    if not relative_path:
        return None
    static_root = os.path.abspath(current_app.static_folder)
    candidate = os.path.abspath(os.path.join(static_root, *relative_path.replace('\\', '/').split('/')))
    if not candidate.startswith(static_root + os.sep):
        return None
    return candidate


def _delete_profile_picture_file(relative_path):
    file_path = _profile_picture_path(relative_path)
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            current_app.logger.warning('Failed to delete profile photo: %s', file_path)


def _allowed_profile_photo(filename):
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    allowed = current_app.config.get('PROFILE_PHOTO_ALLOWED_EXTENSIONS', {'jpg', 'jpeg', 'png', 'webp'})
    return ext in allowed

class RegisterAPI(Resource):
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400
            
            name = data.get('name')
            email = _normalize_email(data.get('email'))
            password = data.get('password')
            password_confirmation = data.get('password_confirmation') or data.get('confirm_password')
            firebase_uid = data.get('firebase_uid') or None
            
            if not name or not email or not password:
                return {'message': 'Missing required fields (name, email, password)'}, 400

            if password_confirmation and password_confirmation != password:
                return {'message': 'Konfirmasi password tidak cocok'}, 400

            if not re.match(r'^[\w\.-]+@([\w-]+\.)+[\w-]{2,}$', email):
                return {'message': 'Format email tidak valid'}, 400

            user = User.query.filter_by(email=email).first()
            is_new_user = user is None

            if user and user.is_verified:
                if user.login_provider == 'google' and not user.password_hash:
                    return {
                        'message': 'Email ini sudah terdaftar lewat Google. Gunakan Lanjutkan dengan Google atau buat Password Aplikasi.',
                        'email': user.email,
                        'provider': 'google',
                        'can_create_app_password': True,
                    }, 409
                return {'message': 'Email already registered'}, 409

            if user:
                user.name = name
                if firebase_uid:
                    user.firebase_uid = firebase_uid
                user.login_provider = 'email'
                user.is_verified = False
                user.email_verified_at = None
            else:
                user = User(
                    name=name,
                    email=email,
                    role='user',
                    login_provider='email',
                    firebase_uid=firebase_uid,
                    is_verified=False,
                    email_verified_at=None,
                )
                db.session.add(user)

            user.set_password(password)

            db.session.flush()
            if _is_otp_bypass_email(user.email):
                _expire_existing_otps(user.email)
                user.mark_email_verified()
                user.is_active = True
                requires_otp = False
                message = 'Registrasi berhasil. Email admin khusus tidak memerlukan OTP.'
            else:
                _send_user_otp(user)
                requires_otp = True
                message = 'Registrasi berhasil. Kode OTP telah dikirim ke email Anda.'

            # Log activity
            activity = UserActivity(
                user_id=user.id,
                activity_type='register',
                description=f'User {"registered" if is_new_user else "requested OTP again"} via email (Firebase UID: {firebase_uid}, requires OTP: {requires_otp})'
            )
            db.session.add(activity)
            db.session.commit()

            response = {
                'message': message,
                'email': user.email,
                'requires_otp': requires_otp,
                'is_verified': user.is_verified,
            }
            if requires_otp:
                response.update({
                    'expires_in': current_app.config.get('OTP_EXPIRES_SECONDS', 60),
                    'resend_available_in': current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 30),
                })

            return response, 201
            
        except EmailDeliveryError as e:
            db.session.rollback()
            return {'message': str(e)}, 500
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class VerifyOTPAPI(Resource):
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            email = _normalize_email(data.get('email'))
            otp_code = str(data.get('otp') or data.get('otp_code') or data.get('code') or '').strip()

            if not email or not otp_code:
                return {'message': 'Email dan kode OTP wajib diisi'}, 400

            if not re.fullmatch(r'\d{6}', otp_code):
                return {'message': 'Kode OTP harus berisi 6 digit angka'}, 400

            user = User.query.filter_by(email=email).first()
            if not user:
                return {'message': 'User tidak ditemukan'}, 404

            if _is_otp_bypass_email(email):
                user.mark_email_verified()
                db.session.commit()
                return {
                    'message': 'Email admin khusus berhasil diverifikasi tanpa OTP.',
                    'user': _serialize_user(user),
                }, 200

            otp, error = _validate_otp_or_error(
                user,
                email,
                otp_code,
                OTP_PURPOSE_VERIFY_EMAIL,
            )
            if error:
                return error

            user.mark_email_verified()
            user.is_active = True

            activity = UserActivity(
                user_id=user.id,
                activity_type='verify_email',
                description='User verified email with OTP'
            )
            db.session.add(activity)
            db.session.commit()

            return {
                'message': 'Email berhasil diverifikasi. Silakan masuk.',
                'user': _serialize_user(user),
            }, 200

        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class ResendOTPAPI(Resource):
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            email = _normalize_email(data.get('email'))
            if not email:
                return {'message': 'Email wajib diisi'}, 400

            user = User.query.filter_by(email=email).first()
            if not user:
                return {'message': 'User tidak ditemukan'}, 404

            if _is_otp_bypass_email(email):
                user.mark_email_verified()
                db.session.commit()
                return {'message': 'Email admin khusus tidak memerlukan OTP. Silakan login.'}, 400

            if user.is_verified:
                return {'message': 'Email sudah terverifikasi. Silakan login.'}, 400

            retry_after = _resend_retry_after(
                email,
                purpose=OTP_PURPOSE_VERIFY_EMAIL,
                user_id=user.id,
            )
            if retry_after > 0:
                return {
                    'message': f'Tunggu {retry_after} detik sebelum mengirim ulang kode OTP.',
                    'retry_after': retry_after,
                }, 429

            _send_user_otp(user)

            activity = UserActivity(
                user_id=user.id,
                activity_type='resend_otp',
                description='User requested a new email OTP'
            )
            db.session.add(activity)
            db.session.commit()

            return {
                'message': 'Kode OTP baru telah dikirim ke email Anda.',
                'email': user.email,
                'expires_in': current_app.config.get('OTP_EXPIRES_SECONDS', 60),
                'resend_available_in': current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 30),
            }, 200

        except EmailDeliveryError as e:
            db.session.rollback()
            return {'message': str(e)}, 500
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class ForgotPasswordAPI(Resource):
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            email = _normalize_email(data.get('email'))
            if not email:
                return {'message': 'Email wajib diisi'}, 400

            user = User.query.filter_by(email=email).first()
            generic_message = 'Jika email terdaftar, kode OTP reset password telah dikirim.'

            if not user:
                return {'message': generic_message}, 200

            if user.login_provider == 'google' and not user.password_hash:
                return {
                    'message': 'Akun ini terhubung dengan Google. Gunakan Login Google atau buat Password Aplikasi.',
                    'email': user.email,
                    'provider': 'google',
                    'can_create_app_password': True,
                }, 400

            retry_after = _resend_retry_after(
                user.email,
                purpose=OTP_PURPOSE_PASSWORD_RESET,
                user_id=user.id,
            )
            if retry_after > 0:
                return {
                    'message': f'Tunggu {retry_after} detik sebelum mengirim ulang kode OTP.',
                    'retry_after': retry_after,
                }, 429

            _send_user_otp(user, purpose=OTP_PURPOSE_PASSWORD_RESET)

            activity = UserActivity(
                user_id=user.id,
                activity_type='forgot_password',
                description='User requested password reset OTP'
            )
            db.session.add(activity)
            db.session.commit()

            return {
                'message': generic_message,
                'email': user.email,
                'expires_in': current_app.config.get('OTP_EXPIRES_SECONDS', 60),
                'resend_available_in': current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 30),
            }, 200

        except EmailDeliveryError as e:
            db.session.rollback()
            return {'message': str(e)}, 500
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class ResetPasswordAPI(Resource):
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            email = _normalize_email(data.get('email'))
            otp_code = str(data.get('otp') or data.get('otp_code') or data.get('code') or '').strip()
            password = data.get('password') or data.get('new_password')
            password_confirmation = (
                data.get('password_confirmation')
                or data.get('confirm_password')
                or data.get('new_password_confirmation')
            )

            if not email:
                return {'message': 'Email wajib diisi'}, 400

            password_error = _validate_password_strength(password)
            if password_error:
                return {'message': password_error}, 400

            if password_confirmation and password_confirmation != password:
                return {'message': 'Konfirmasi password tidak cocok'}, 400

            user = User.query.filter_by(email=email).first()
            if not user:
                return {'message': 'User tidak ditemukan'}, 404

            if user.login_provider == 'google' and not user.password_hash:
                return {
                    'message': 'Akun ini belum memiliki password aplikasi. Gunakan fitur Password Aplikasi.',
                    'email': user.email,
                    'provider': 'google',
                    'can_create_app_password': True,
                }, 400

            otp, error = _validate_otp_or_error(
                user,
                user.email,
                otp_code,
                OTP_PURPOSE_PASSWORD_RESET,
            )
            if error:
                return error

            user.set_password(password)
            user.login_provider = 'email'
            user.mark_email_verified()
            user.is_active = True

            activity = UserActivity(
                user_id=user.id,
                activity_type='reset_password',
                description='User reset password with OTP'
            )
            db.session.add(activity)
            db.session.commit()

            return {'message': 'Password berhasil direset. Silakan login.'}, 200

        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class RequestAppPasswordAPI(Resource):
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            email = _normalize_email(data.get('email'))
            if not email:
                return {'message': 'Email wajib diisi'}, 400

            user = User.query.filter_by(email=email).first()
            if not user:
                return {'message': 'Akun tidak ditemukan. Silakan register terlebih dahulu.'}, 404

            if user.password_hash:
                return {'message': 'Akun ini sudah memiliki password aplikasi. Gunakan Ganti Password jika ingin mengubahnya.'}, 400

            if user.login_provider != 'google':
                return {'message': 'Password aplikasi hanya diperlukan untuk akun yang terdaftar lewat Google.'}, 400

            retry_after = _resend_retry_after(
                user.email,
                purpose=OTP_PURPOSE_APP_PASSWORD,
                user_id=user.id,
            )
            if retry_after > 0:
                return {
                    'message': f'Tunggu {retry_after} detik sebelum mengirim ulang kode OTP.',
                    'retry_after': retry_after,
                }, 429

            _send_user_otp(user, purpose=OTP_PURPOSE_APP_PASSWORD)

            activity = UserActivity(
                user_id=user.id,
                activity_type='request_app_password',
                description='User requested OTP to create app password'
            )
            db.session.add(activity)
            db.session.commit()

            return {
                'message': 'Kode OTP untuk membuat password aplikasi telah dikirim ke email Anda.',
                'email': user.email,
                'expires_in': current_app.config.get('OTP_EXPIRES_SECONDS', 60),
                'resend_available_in': current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 30),
            }, 200

        except EmailDeliveryError as e:
            db.session.rollback()
            return {'message': str(e)}, 500
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class VerifyAppPasswordOTPAPI(Resource):
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            email = _normalize_email(data.get('email'))
            otp_code = str(data.get('otp') or data.get('otp_code') or data.get('code') or '').strip()

            if not email:
                return {'message': 'Email wajib diisi'}, 400

            user = User.query.filter_by(email=email).first()
            if not user:
                return {'message': 'Akun tidak ditemukan'}, 404

            if user.password_hash:
                return {'message': 'Akun ini sudah memiliki password aplikasi.'}, 400

            if user.login_provider != 'google':
                return {'message': 'Password aplikasi hanya diperlukan untuk akun yang terdaftar lewat Google.'}, 400

            otp, error = _validate_otp_or_error(
                user,
                user.email,
                otp_code,
                OTP_PURPOSE_APP_PASSWORD,
            )
            if error:
                return error

            setup_token = create_access_token(
                identity=str(user.id),
                additional_claims={
                    "role": user.role,
                    "purpose": JWT_PURPOSE_APP_PASSWORD_SETUP,
                },
                expires_delta=datetime.timedelta(minutes=5),
            )

            activity = UserActivity(
                user_id=user.id,
                activity_type='verify_app_password_otp',
                description='User verified OTP before creating app password'
            )
            db.session.add(activity)
            db.session.commit()

            return {
                'message': 'OTP berhasil diverifikasi. Silakan buat password aplikasi.',
                'email': user.email,
                'setup_token': setup_token,
                'setup_expires_in': 300,
            }, 200

        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class SetAppPasswordAPI(Resource):
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            email = _normalize_email(data.get('email'))
            otp_code = str(data.get('otp') or data.get('otp_code') or data.get('code') or '').strip()
            setup_token = data.get('setup_token') or data.get('token')
            password = data.get('password') or data.get('new_password')
            password_confirmation = (
                data.get('password_confirmation')
                or data.get('confirm_password')
                or data.get('new_password_confirmation')
            )

            if not email:
                return {'message': 'Email wajib diisi'}, 400

            password_error = _validate_password_strength(password)
            if password_error:
                return {'message': password_error}, 400

            if password_confirmation and password_confirmation != password:
                return {'message': 'Konfirmasi password tidak cocok'}, 400

            user = User.query.filter_by(email=email).first()
            if not user:
                return {'message': 'Akun tidak ditemukan'}, 404

            if user.password_hash:
                return {'message': 'Akun ini sudah memiliki password aplikasi. Gunakan Ganti Password jika ingin mengubahnya.'}, 400

            if user.login_provider != 'google':
                return {'message': 'Password aplikasi hanya diperlukan untuk akun yang terdaftar lewat Google.'}, 400

            if setup_token:
                try:
                    decoded_token = decode_token(setup_token)
                except Exception:
                    return {'message': 'Sesi verifikasi OTP tidak valid atau sudah expired. Silakan kirim OTP ulang.'}, 401

                if (
                    decoded_token.get('sub') != str(user.id)
                    or decoded_token.get('purpose') != JWT_PURPOSE_APP_PASSWORD_SETUP
                ):
                    return {'message': 'Sesi verifikasi OTP tidak sesuai dengan akun ini.'}, 401
            else:
                otp, error = _validate_otp_or_error(
                    user,
                    user.email,
                    otp_code,
                    OTP_PURPOSE_APP_PASSWORD,
                )
                if error:
                    return error

            user.set_password(password)
            user.mark_email_verified()
            user.is_active = True

            activity = UserActivity(
                user_id=user.id,
                activity_type='set_app_password',
                description='User created app password for Google account'
            )
            db.session.add(activity)
            db.session.commit()

            access_token = create_access_token(
                identity=str(user.id),
                additional_claims={"role": user.role}
            )

            return {
                'message': 'Password aplikasi berhasil dibuat.',
                'token': access_token,
                'user': _serialize_user(user),
            }, 200

        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class RequestEmailChangeAPI(Resource):
    @jwt_required()
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            user_id = int(get_jwt_identity())
            user = User.query.get(user_id)
            if not user:
                return {'message': 'User tidak ditemukan'}, 404

            new_email = _normalize_email(data.get('new_email') or data.get('email'))
            current_password = data.get('current_password') or ''

            if not new_email:
                return {'message': 'Email baru wajib diisi'}, 400

            if not re.match(r'^[\w\.-]+@([\w-]+\.)+[\w-]{2,}$', new_email):
                return {'message': 'Format email baru tidak valid'}, 400

            if new_email == user.email:
                return {'message': 'Email baru sama dengan email saat ini'}, 400

            existing_user = User.query.filter_by(email=new_email).first()
            if existing_user:
                return {'message': 'Email baru sudah digunakan akun lain'}, 409

            if user.password_hash and not user.check_password(current_password):
                return {'message': 'Password saat ini tidak sesuai'}, 401

            retry_after = _resend_retry_after(
                new_email,
                purpose=OTP_PURPOSE_EMAIL_CHANGE,
                user_id=user.id,
            )
            if retry_after > 0:
                return {
                    'message': f'Tunggu {retry_after} detik sebelum mengirim ulang kode OTP.',
                    'retry_after': retry_after,
                }, 429

            _send_user_otp(user, purpose=OTP_PURPOSE_EMAIL_CHANGE, to_email=new_email)

            activity = UserActivity(
                user_id=user.id,
                activity_type='request_email_change',
                description=f'User requested email change to {new_email}'
            )
            db.session.add(activity)
            db.session.commit()

            return {
                'message': 'Kode OTP telah dikirim ke email baru Anda.',
                'email': new_email,
                'expires_in': current_app.config.get('OTP_EXPIRES_SECONDS', 60),
                'resend_available_in': current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 30),
            }, 200

        except EmailDeliveryError as e:
            db.session.rollback()
            return {'message': str(e)}, 500
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class ConfirmEmailChangeAPI(Resource):
    @jwt_required()
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            user_id = int(get_jwt_identity())
            user = User.query.get(user_id)
            if not user:
                return {'message': 'User tidak ditemukan'}, 404

            new_email = _normalize_email(data.get('new_email') or data.get('email'))
            otp_code = str(data.get('otp') or data.get('otp_code') or data.get('code') or '').strip()

            if not new_email:
                return {'message': 'Email baru wajib diisi'}, 400

            existing_user = User.query.filter_by(email=new_email).first()
            if existing_user and existing_user.id != user.id:
                return {'message': 'Email baru sudah digunakan akun lain'}, 409

            otp, error = _validate_otp_or_error(
                user,
                new_email,
                otp_code,
                OTP_PURPOSE_EMAIL_CHANGE,
            )
            if error:
                return error

            old_email = user.email
            user.email = new_email
            user.mark_email_verified()

            activity = UserActivity(
                user_id=user.id,
                activity_type='confirm_email_change',
                description=f'User changed email from {old_email} to {new_email}'
            )
            db.session.add(activity)
            db.session.commit()

            return {
                'message': 'Email akun berhasil diganti.',
                'user': _serialize_user(user),
            }, 200

        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class RequestPasswordChangeAPI(Resource):
    @jwt_required()
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            user_id = int(get_jwt_identity())
            user = User.query.get(user_id)
            if not user:
                return {'message': 'User tidak ditemukan'}, 404

            current_password = data.get('current_password') or ''
            new_password = data.get('new_password') or data.get('password')
            new_password_confirmation = (
                data.get('new_password_confirmation')
                or data.get('password_confirmation')
                or data.get('confirm_password')
            )

            if not user.password_hash:
                return {'message': 'Akun Google belum memiliki password aplikasi. Buat Password Aplikasi terlebih dahulu.'}, 400

            if not user.check_password(current_password):
                return {'message': 'Password saat ini tidak sesuai'}, 401

            password_error = _validate_password_strength(new_password)
            if password_error:
                return {'message': password_error}, 400

            if new_password_confirmation and new_password_confirmation != new_password:
                return {'message': 'Konfirmasi password baru tidak cocok'}, 400

            retry_after = _resend_retry_after(
                user.email,
                purpose=OTP_PURPOSE_PASSWORD_CHANGE,
                user_id=user.id,
            )
            if retry_after > 0:
                return {
                    'message': f'Tunggu {retry_after} detik sebelum mengirim ulang kode OTP.',
                    'retry_after': retry_after,
                }, 429

            _send_user_otp(user, purpose=OTP_PURPOSE_PASSWORD_CHANGE)

            activity = UserActivity(
                user_id=user.id,
                activity_type='request_password_change',
                description='User requested password change OTP'
            )
            db.session.add(activity)
            db.session.commit()

            return {
                'message': 'Kode OTP konfirmasi ganti password telah dikirim ke email Anda.',
                'email': user.email,
                'expires_in': current_app.config.get('OTP_EXPIRES_SECONDS', 60),
                'resend_available_in': current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 30),
            }, 200

        except EmailDeliveryError as e:
            db.session.rollback()
            return {'message': str(e)}, 500
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class ConfirmPasswordChangeAPI(Resource):
    @jwt_required()
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            user_id = int(get_jwt_identity())
            user = User.query.get(user_id)
            if not user:
                return {'message': 'User tidak ditemukan'}, 404

            current_password = data.get('current_password') or ''
            new_password = data.get('new_password') or data.get('password')
            new_password_confirmation = (
                data.get('new_password_confirmation')
                or data.get('password_confirmation')
                or data.get('confirm_password')
            )
            otp_code = str(data.get('otp') or data.get('otp_code') or data.get('code') or '').strip()

            if not user.password_hash:
                return {'message': 'Akun ini belum memiliki password aplikasi.'}, 400

            if not user.check_password(current_password):
                return {'message': 'Password saat ini tidak sesuai'}, 401

            password_error = _validate_password_strength(new_password)
            if password_error:
                return {'message': password_error}, 400

            if new_password_confirmation and new_password_confirmation != new_password:
                return {'message': 'Konfirmasi password baru tidak cocok'}, 400

            otp, error = _validate_otp_or_error(
                user,
                user.email,
                otp_code,
                OTP_PURPOSE_PASSWORD_CHANGE,
            )
            if error:
                return error

            user.set_password(new_password)

            activity = UserActivity(
                user_id=user.id,
                activity_type='confirm_password_change',
                description='User changed password with OTP'
            )
            db.session.add(activity)
            db.session.commit()

            return {'message': 'Password berhasil diganti.'}, 200

        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class LoginAPI(Resource):
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400
                
            email = _normalize_email(data.get('email'))
            password = data.get('password')
            
            if not email or not password:
                return {'message': 'Missing email or password'}, 400

            user = User.query.filter_by(email=email).first()
            
            if user and user.role in ['user', 'admin'] and user.login_provider == 'google' and not user.password_hash:
                return {
                    'message': 'Email ini terdaftar lewat Google. Gunakan Lanjutkan dengan Google atau buat Password Aplikasi.',
                    'email': user.email,
                    'provider': 'google',
                    'can_create_app_password': True,
                }, 403

            # Allow both 'user' and 'admin' roles for mobile app login
            if user and user.role in ['user', 'admin'] and user.check_password(password):
                # Professional Check: If soft-deleted, block and offer reactivation
                if user.deleted_at:
                    return {
                        'message': 'Akun Anda saat ini sedang dinonaktifkan untuk dijadwalkan dihapus permanen.',
                        'email': user.email,
                        'action': 'reactivate_prompt',
                        'provider': user.login_provider,
                    }, 403

                if user.login_provider == 'email' and not user.is_verified:
                    if _is_otp_bypass_email(user.email):
                        user.mark_email_verified()
                    else:
                        return {
                            'message': 'Email belum diverifikasi. Silakan verifikasi OTP terlebih dahulu.',
                            'email': user.email,
                            'requires_verification': True,
                        }, 403

                access_token = create_access_token(
                    identity=str(user.id),
                    additional_claims={"role": user.role}
                )
                
                # Log activity
                activity = UserActivity(
                    user_id=user.id,
                    activity_type='login',
                    description='User logged in via email'
                )
                db.session.add(activity)
                db.session.commit()

                return {
                    'token': access_token, 
                    'user': _serialize_user(user)
                }, 200
            
            return {'message': 'Invalid email, password, or unauthorized role'}, 401
        except Exception as e:
            return {'message': f'Internal Server Error: {str(e)}'}, 500

class ProfileAPI(Resource):
    @jwt_required()
    def get(self):
        try:
            user_id = get_jwt_identity()
            user = User.query.get(int(user_id))
            if not user:
                return {'message': 'User not found'}, 404
            profile = _serialize_user(user)
            profile['provider'] = user.login_provider
            return profile, 200
        except Exception as e:
            return {'message': f'Internal Server Error: {str(e)}'}, 500

    @jwt_required()
    def put(self):
        try:
            data = request.get_json() or {}
            user_id = get_jwt_identity()
            user = User.query.get(int(user_id))
            if not user:
                return {'message': 'User not found'}, 404

            name = re.sub(r'\s+', ' ', str(data.get('name') or '')).strip()
            if not name:
                return {'message': 'Nama lengkap wajib diisi'}, 400
            if len(name) > 100:
                return {'message': 'Nama lengkap maksimal 100 karakter'}, 400

            if user.name != name:
                user.name = name
                db.session.add(UserActivity(
                    user_id=user.id,
                    activity_type='update_profile',
                    description='User updated profile name'
                ))
                db.session.commit()

            return {
                'message': 'Profil berhasil diperbarui.',
                'user': _serialize_user(user),
            }, 200
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class ProfilePhotoAPI(Resource):
    @jwt_required()
    def post(self):
        saved_path = None
        try:
            user_id = get_jwt_identity()
            user = User.query.get(int(user_id))
            if not user:
                return {'message': 'User not found'}, 404

            photo = request.files.get('photo')
            if not photo or not photo.filename:
                return {'message': 'Foto profil wajib dipilih'}, 400
            if not _allowed_profile_photo(photo.filename):
                return {'message': 'Format foto harus JPG, JPEG, PNG, atau WEBP'}, 400

            max_bytes = current_app.config.get('PROFILE_PHOTO_MAX_BYTES', 2 * 1024 * 1024)
            photo_bytes = photo.read()
            if not photo_bytes:
                return {'message': 'File foto tidak boleh kosong'}, 400
            if len(photo_bytes) > max_bytes:
                return {'message': 'Ukuran foto maksimal 2 MB'}, 413

            upload_dir = _profile_upload_dir()
            os.makedirs(upload_dir, exist_ok=True)

            original = secure_filename(photo.filename)
            ext = original.rsplit('.', 1)[1].lower()
            filename = f'user_{user.id}_{uuid.uuid4().hex}.{ext}'
            saved_path = os.path.join(upload_dir, filename)
            with open(saved_path, 'wb') as handle:
                handle.write(photo_bytes)

            old_picture = user.profile_picture
            upload_subdir = current_app.config.get('PROFILE_PHOTO_UPLOAD_SUBDIR', 'uploads/profile_pictures')
            normalized_subdir = upload_subdir.strip('/').replace('\\', '/')
            user.profile_picture = f"{normalized_subdir}/{filename}"
            db.session.add(UserActivity(
                user_id=user.id,
                activity_type='update_profile_photo',
                description='User updated profile photo'
            ))
            db.session.commit()
            _delete_profile_picture_file(old_picture)

            return {
                'message': 'Foto profil berhasil diperbarui.',
                'user': _serialize_user(user),
            }, 200
        except Exception as e:
            db.session.rollback()
            if saved_path and os.path.exists(saved_path):
                try:
                    os.remove(saved_path)
                except OSError:
                    current_app.logger.warning('Failed to remove failed profile photo upload: %s', saved_path)
            return {'message': f'Internal Server Error: {str(e)}'}, 500

    @jwt_required()
    def delete(self):
        try:
            user_id = get_jwt_identity()
            user = User.query.get(int(user_id))
            if not user:
                return {'message': 'User not found'}, 404

            old_picture = user.profile_picture
            user.profile_picture = None
            db.session.add(UserActivity(
                user_id=user.id,
                activity_type='delete_profile_photo',
                description='User deleted profile photo'
            ))
            db.session.commit()
            _delete_profile_picture_file(old_picture)

            return {
                'message': 'Foto profil berhasil dihapus.',
                'user': _serialize_user(user),
            }, 200
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class LoginGoogleAPI(Resource):
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'message': 'No input data provided'}, 400

            id_info = _verify_google_token(data.get('id_token'))
            verified_email = _normalize_email(id_info.get('email'))
            requested_email = _normalize_email(data.get('email'))
            if requested_email and requested_email != verified_email:
                return {'message': 'Email request tidak cocok dengan token Google'}, 400

            firebase_uid = data.get('firebase_uid') or None
            google_id = id_info.get('sub')
            email = verified_email
            name = data.get('name') or id_info.get('name') or 'Google User'

            if not email:
                return {'message': 'Email is required'}, 400

            user = User.query.filter_by(email=email).first()

            if firebase_uid:
                uid_owner = User.query.filter_by(firebase_uid=firebase_uid).first()
                if uid_owner and uid_owner.email != email:
                    return {
                        'message': 'Akun Google ini sudah terhubung dengan email lain.'
                    }, 409

            if user:
                user.name = user.name or name
                if not user.firebase_uid and firebase_uid:
                    user.firebase_uid = firebase_uid
                user.login_provider = 'google'
                user.mark_email_verified()
            else:
                user = User(
                    name=name,
                    email=email,
                    firebase_uid=firebase_uid,
                    role='user',
                    login_provider='google',
                    is_verified=True,
                    email_verified_at=datetime.datetime.utcnow(),
                )
                db.session.add(user)
            
            db.session.commit()

            # Professional Check: If soft-deleted, block and offer reactivation
            if user and user.deleted_at:
                return {
                    'message': 'Akun Anda saat ini sedang dinonaktifkan untuk dijadwalkan dihapus permanen.',
                    'email': user.email,
                    'action': 'reactivate_prompt',
                    'provider': 'google',
                }, 403

            # Generate JWT token
            access_token = create_access_token(
                identity=str(user.id),
                additional_claims={"role": user.role}
            )
            
            # Log activity
            activity = UserActivity(
                user_id=user.id,
                activity_type='login_google',
                description=f'User logged in via Google (sub: {google_id})'
            )
            db.session.add(activity)
            db.session.commit()

            return {
                'token': access_token,
                'user': _serialize_user(user)
            }, 200

        except ValueError as e:
            db.session.rollback()
            return {'message': str(e)}, 401
        except Exception as e:
            db.session.rollback()
            return {'message': f'Login Google failed: {str(e)}'}, 500


class RequestDeleteAccountOtpAPI(Resource):
    @jwt_required()
    def post(self):
        try:
            current_user_id = get_jwt_identity()
            user = User.query.get(int(current_user_id))
            if not user:
                return {'message': 'Pengguna tidak ditemukan'}, 404

            retry_after = _resend_retry_after(user.email, purpose=OTP_PURPOSE_DELETE_ACCOUNT, user_id=user.id)
            if retry_after > 0:
                return {
                    'message': f'Silakan tunggu {retry_after} detik sebelum mengirim ulang kode OTP.',
                    'retry_after_seconds': retry_after,
                }, 429

            _send_user_otp(user, purpose=OTP_PURPOSE_DELETE_ACCOUNT)
            
            # Log activity
            db.session.add(UserActivity(
                user_id=user.id,
                activity_type='request_delete_otp',
                description='User requested OTP to delete account'
            ))
            db.session.commit()

            return {'message': f'Kode OTP penghapusan akun telah dikirim ke {user.email}.'}, 200
        except EmailDeliveryError as exc:
            db.session.rollback()
            return {'message': str(exc)}, 500
        except Exception as exc:
            db.session.rollback()
            return {'message': f'Gagal mengirim OTP: {str(exc)}'}, 500


class ConfirmDeleteAccountAPI(Resource):
    @jwt_required()
    def post(self):
        try:
            current_user_id = get_jwt_identity()
            user = User.query.get(int(current_user_id))
            if not user:
                return {'message': 'Pengguna tidak ditemukan'}, 404

            data = request.get_json() or {}
            
            # Validation depends on login provider
            if user.login_provider == 'google':
                otp_code = data.get('otp_code')
                if not otp_code:
                    return {'message': 'Kode OTP wajib diisi untuk akun Google'}, 400
                
                otp, error_res = _validate_otp_or_error(user, user.email, otp_code, OTP_PURPOSE_DELETE_ACCOUNT)
                if error_res:
                    return error_res[0], error_res[1]
            else:
                # Email provider requires password
                password = data.get('password')
                if not password:
                    return {'message': 'Password wajib diisi untuk konfirmasi'}, 400
                if not user.check_password(password):
                    return {'message': 'Password yang Anda masukkan salah'}, 401

            # Process Soft Deletion
            user.is_active = False
            user.deleted_at = datetime.datetime.utcnow()
            
            # Log activity
            activity = UserActivity(
                user_id=user.id,
                activity_type='account_deletion_scheduled',
                description='User requested account deletion. Scheduled for 30 days.'
            )
            db.session.add(activity)
            db.session.commit()

            return {
                'message': 'Akun Anda berhasil dinonaktifkan dan dijadwalkan untuk dihapus permanen dalam 30 hari.'
            }, 200
        except Exception as exc:
            db.session.rollback()
            return {'message': f'Gagal memproses penghapusan akun: {str(exc)}'}, 500


class ReactivateAccountAPI(Resource):
    def post(self):
        try:
            data = request.get_json() or {}
            email = _normalize_email(data.get('email'))
            password = data.get('password')
            google_token = data.get('google_token')

            if not email:
                return {'message': 'Email wajib diisi'}, 400

            user = User.query.filter_by(email=email).first()
            if not user:
                return {'message': 'Akun tidak ditemukan'}, 404

            # Authenticate before reactivating
            if google_token:
                try:
                    id_info = _verify_google_token(google_token)
                    g_email = _normalize_email(id_info.get('email'))
                    if g_email != email:
                        return {'message': 'Email token Google tidak cocok'}, 400
                except ValueError as e:
                    return {'message': f'Autentikasi Google gagal: {str(e)}'}, 401
            elif password:
                if not user.check_password(password):
                    return {'message': 'Password salah'}, 401
            else:
                return {'message': 'Autentikasi diperlukan untuk memulihkan akun'}, 400

            if not user.deleted_at:
                return {'message': 'Akun ini tidak dalam status penghapusan'}, 400

            # Perform Reactivation
            user.is_active = True
            user.deleted_at = None
            
            # Log activity
            activity = UserActivity(
                user_id=user.id,
                activity_type='account_reactivated',
                description='User restored account from scheduled deletion.'
            )
            db.session.add(activity)
            db.session.commit()

            # Generate new login token for instant access
            access_token = create_access_token(
                identity=str(user.id),
                additional_claims={"role": user.role}
            )

            return {
                'message': 'Selamat! Akun Anda berhasil diaktifkan kembali.',
                'token': access_token,
                'user': _serialize_user(user)
            }, 200
        except Exception as exc:
            db.session.rollback()
            return {'message': f'Gagal mengaktifkan kembali akun: {str(exc)}'}, 500


def prune_permanently_deleted_users(app=None, retention_days=30):
    """Menghapus permanen user yang sudah di-softdelete melebihi 30 hari."""
    def _run_pruning():
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
        expired_users = User.query.filter(
            User.is_active == False,
            User.deleted_at.isnot(None),
            User.deleted_at < cutoff
        ).all()
        
        count = 0
        for user in expired_users:
            db.session.delete(user)
            count += 1
            
        if count > 0:
            db.session.commit()
        return count

    if app:
        with app.app_context():
            return _run_pruning()
    else:
        return _run_pruning()
