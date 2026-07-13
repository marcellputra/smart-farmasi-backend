from flask import Blueprint, request, render_template, redirect, url_for, flash, session, jsonify, current_app
from app.models import User, db, UserActivity
from flask_jwt_extended import create_access_token
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from app.api.auth import (
    OTP_PURPOSE_ADMIN_LOGIN,
    _is_otp_bypass_email,
    _resend_retry_after,
    _send_user_otp,
    _validate_otp_or_error,
)
from app.services.email_service import EmailDeliveryError
import datetime
import os

admin_auth = Blueprint('admin_auth', __name__)


def _complete_admin_login(user, activity_type='admin_login', description='Admin logged into dashboard'):
    session.pop('pending_admin_2fa_user_id', None)
    session.pop('pending_admin_2fa_email', None)
    session['is_admin'] = True
    session['user_id'] = user.id
    session['user_name'] = user.name

    activity = UserActivity(
        user_id=user.id,
        activity_type=activity_type,
        description=description
    )
    db.session.add(activity)
    db.session.commit()


@admin_auth.route('/admin/login', methods=['GET', 'POST'])
def login():
    if session.get('is_admin'):
        return redirect(url_for('admin.index'))
        
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email, role='admin').first()
        
        if user and user.check_password(password):
            if (
                current_app.config.get('ADMIN_OTP_REQUIRED', True)
                and not _is_otp_bypass_email(user.email)
            ):
                session['pending_admin_2fa_user_id'] = user.id
                session['pending_admin_2fa_email'] = user.email

                retry_after = _resend_retry_after(
                    user.email,
                    purpose=OTP_PURPOSE_ADMIN_LOGIN,
                    user_id=user.id,
                )
                if retry_after == 0:
                    try:
                        _send_user_otp(user, purpose=OTP_PURPOSE_ADMIN_LOGIN)
                        db.session.commit()
                        flash('Kode OTP admin telah dikirim ke email Anda.', 'success')
                    except EmailDeliveryError as exc:
                        db.session.rollback()
                        flash(str(exc), 'danger')
                        return redirect(url_for('admin_auth.login'))
                else:
                    flash(f'Kode OTP sebelumnya masih berlaku. Coba resend dalam {retry_after} detik.', 'info')

                return redirect(url_for('admin_auth.verify_otp'))

            _complete_admin_login(user)
            flash('Welcome back, Admin!', 'success')
            return redirect(url_for('admin.index'))
        else:
            flash('Invalid email or password, or you are not an admin.', 'danger')
            
    return render_template('admin/login.html')


@admin_auth.route('/admin/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if session.get('is_admin'):
        return redirect(url_for('admin.index'))

    user_id = session.get('pending_admin_2fa_user_id')
    if not user_id:
        flash('Silakan login ulang untuk melanjutkan verifikasi admin.', 'warning')
        return redirect(url_for('admin_auth.login'))

    user = User.query.get(user_id)
    if not user or user.role != 'admin':
        session.pop('pending_admin_2fa_user_id', None)
        session.pop('pending_admin_2fa_email', None)
        flash('Sesi verifikasi admin tidak valid. Silakan login ulang.', 'danger')
        return redirect(url_for('admin_auth.login'))

    if request.method == 'POST':
        otp_code = request.form.get('otp')
        otp, error = _validate_otp_or_error(
            user,
            user.email,
            otp_code,
            OTP_PURPOSE_ADMIN_LOGIN,
        )
        if error:
            message, status = error
            flash(message.get('message', 'Verifikasi OTP gagal.'), 'danger' if status >= 400 else 'warning')
        else:
            _complete_admin_login(
                user,
                activity_type='admin_login_otp',
                description='Admin logged into dashboard with OTP'
            )
            flash('Verifikasi admin berhasil. Welcome back!', 'success')
            return redirect(url_for('admin.index'))

    return render_template(
        'admin/verify_otp.html',
        email=user.email,
        expires_in=current_app.config.get('OTP_EXPIRES_SECONDS', 60),
        resend_available_in=current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 30),
    )


@admin_auth.route('/admin/resend-otp', methods=['POST'])
def resend_otp():
    user_id = session.get('pending_admin_2fa_user_id')
    if not user_id:
        flash('Silakan login ulang untuk meminta OTP baru.', 'warning')
        return redirect(url_for('admin_auth.login'))

    user = User.query.get(user_id)
    if not user or user.role != 'admin':
        flash('Sesi verifikasi admin tidak valid.', 'danger')
        return redirect(url_for('admin_auth.login'))

    retry_after = _resend_retry_after(
        user.email,
        purpose=OTP_PURPOSE_ADMIN_LOGIN,
        user_id=user.id,
    )
    if retry_after > 0:
        flash(f'Tunggu {retry_after} detik sebelum resend OTP.', 'warning')
        return redirect(url_for('admin_auth.verify_otp'))

    try:
        _send_user_otp(user, purpose=OTP_PURPOSE_ADMIN_LOGIN)
        db.session.commit()
        flash('Kode OTP admin baru telah dikirim ke email Anda.', 'success')
    except EmailDeliveryError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')

    return redirect(url_for('admin_auth.verify_otp'))

@admin_auth.route('/admin/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        activity = UserActivity(
            user_id=user_id,
            activity_type='admin_logout',
            description='Admin logged out'
        )
        db.session.add(activity)
        db.session.commit()
        
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('admin_auth.login'))
@admin_auth.route('/admin/register', methods=['GET', 'POST'])
def register():
    if session.get('is_admin'):
        return redirect(url_for('admin.index'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
        else:
            user = User(
                name=name,
                email=email,
                role='admin',
                login_provider='email',
                is_verified=True,
                email_verified_at=datetime.datetime.utcnow()
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            
            # Log activity
            activity = UserActivity(
                user_id=user.id,
                activity_type='admin_register',
                description='New admin account created via web'
            )
            db.session.add(activity)
            db.session.commit()
            
            flash('Admin account created! Please login.', 'success')
            return redirect(url_for('admin_auth.login'))
            
    return render_template('admin/register.html')

@admin_auth.route('/admin/login/google', methods=['POST'])
def google_login():
    token = request.json.get('id_token')
    if not token:
        return jsonify({'error': 'No token provided'}), 400
        
    try:
        # Verify Google ID Token
        # NOTE: Replace with your actual Google Client ID from Google Cloud Console
        # We try to get it from env or use a placeholder
        client_id = os.environ.get('GOOGLE_CLIENT_ID') or "691571373089-t2r3oajabh78af9r1veh4oc5hhb4ebjg.apps.googleusercontent.com"
        
        id_info = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
        
        email = id_info['email'].strip().lower()
        name = id_info.get('name', 'Google User')
        google_id = id_info['sub']
        
        # Check if user exists and is an admin
        user = User.query.filter_by(email=email).first()
        
        if not user:
            return jsonify({'error': 'User not found. Please register as an admin first.'}), 404
            
        if user.role != 'admin':
            return jsonify({'error': 'Access denied. You do not have admin privileges.'}), 403
            
        # Update user's firebase_uid if it was empty (using google sub as identifier for sync)
        if not user.firebase_uid:
            user.firebase_uid = google_id
        user.mark_email_verified()
        db.session.commit()
            
        # Set Admin Session
        session['is_admin'] = True
        session['user_id'] = user.id
        session['user_name'] = user.name
        
        # Log activity
        activity = UserActivity(
            user_id=user.id,
            activity_type='admin_login_google',
            description='Admin logged in via Google'
        )
        db.session.add(activity)
        db.session.commit()
        
        return jsonify({'success': True, 'redirect': url_for('admin.index')})
        
    except ValueError:
        # Invalid token
        return jsonify({'error': 'Invalid token'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_auth.route('/admin/register/google', methods=['POST'])
def google_register():
    token = request.json.get('id_token')
    if not token:
        return jsonify({'error': 'No token provided'}), 400
        
    try:
        client_id = os.environ.get('GOOGLE_CLIENT_ID') or "691571373089-t2r3oajabh78af9r1veh4oc5hhb4ebjg.apps.googleusercontent.com"
        id_info = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
        
        email = id_info['email'].strip().lower()
        name = id_info.get('name', 'Google User')
        google_id = id_info['sub']
        
        user = User.query.filter_by(email=email).first()
        
        if user:
            # If user exists, just log them in (if they are admin)
            if user.role != 'admin':
                return jsonify({'error': 'Email already registered as a non-admin user.'}), 403
            user.mark_email_verified()
        else:
            # Create new admin user
            user = User(
                name=name,
                email=email,
                role='admin',
                login_provider='google',
                firebase_uid=google_id,
                is_verified=True,
                email_verified_at=datetime.datetime.utcnow()
            )
            # No password needed for Google login
            db.session.add(user)
            db.session.commit()
            
            # Log registration
            activity = UserActivity(
                user_id=user.id,
                activity_type='admin_register_google',
                description='New admin registered via Google'
            )
            db.session.add(activity)
            db.session.commit()
            
        # Set Session
        session['is_admin'] = True
        session['user_id'] = user.id
        session['user_name'] = user.name
        db.session.commit()
        
        return jsonify({'success': True, 'redirect': url_for('admin.index')})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
