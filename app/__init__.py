from flask import Flask, render_template, redirect, url_for
from app.models import db, bcrypt
from app.admin.views import init_admin
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_migrate import Migrate
import os
from app import config

def create_app():
    app = Flask(__name__)
    app.config.from_object(config)
    
    db.init_app(app)
    bcrypt.init_app(app)
    JWTManager(app)
    CORS(app)
    Migrate(app, db)
    
    from app.admin.auth import admin_auth
    app.register_blueprint(admin_auth)
    
    init_admin(app)
    
    from app.api.auth import (
        ConfirmEmailChangeAPI,
        ConfirmPasswordChangeAPI,
        ForgotPasswordAPI,
        LoginAPI,
        LoginGoogleAPI,
        ProfileAPI,
        ProfilePhotoAPI,
        RegisterAPI,
        RequestEmailChangeAPI,
        RequestAppPasswordAPI,
        RequestPasswordChangeAPI,
        ResendOTPAPI,
        ResetPasswordAPI,
        SetAppPasswordAPI,
        VerifyAppPasswordOTPAPI,
        VerifyOTPAPI,
        RequestDeleteAccountOtpAPI,
        ConfirmDeleteAccountAPI,
        ReactivateAccountAPI,
    )
    from app.api.users import SaveActivityAPI
    from app.api.disease_news import (
        DiseaseNewsImageProxyAPI,
        DiseaseNewsTrendingAPI,
        DiseaseNewsListAPI,
        DiseaseNewsRefreshAPI,
        DiseaseNewsViewAPI,
    )
    from app.api.chatbot import ChatbotAPI, ChatHistoryAPI, ChatSessionListAPI, ChatSessionDetailAPI

    from app.api.face import FacePromptShownAPI, FaceRegisterAPI, FaceLoginAPI, FaceDeleteAPI
    
    from flask_restful import Api
    api = Api(app)
    api.add_resource(RegisterAPI, '/api/register', '/register')
    api.add_resource(VerifyOTPAPI, '/api/verify-otp', '/verify-otp')
    api.add_resource(ResendOTPAPI, '/api/resend-otp', '/resend-otp')
    api.add_resource(ForgotPasswordAPI, '/api/forgot-password')
    api.add_resource(ResetPasswordAPI, '/api/reset-password')
    api.add_resource(RequestAppPasswordAPI, '/api/request-app-password')
    api.add_resource(VerifyAppPasswordOTPAPI, '/api/verify-app-password-otp')
    api.add_resource(SetAppPasswordAPI, '/api/set-app-password')
    api.add_resource(RequestEmailChangeAPI, '/api/account/request-email-change')
    api.add_resource(ConfirmEmailChangeAPI, '/api/account/confirm-email-change')
    api.add_resource(RequestPasswordChangeAPI, '/api/account/request-password-change')
    api.add_resource(ConfirmPasswordChangeAPI, '/api/account/confirm-password-change')
    api.add_resource(RequestDeleteAccountOtpAPI, '/api/account/request-delete-otp')
    api.add_resource(ConfirmDeleteAccountAPI, '/api/account/delete')
    api.add_resource(ReactivateAccountAPI, '/api/account/reactivate')
    api.add_resource(LoginAPI, '/api/login')
    api.add_resource(LoginGoogleAPI, '/api/login/google')
    api.add_resource(ProfileAPI, '/api/profile')
    api.add_resource(ProfilePhotoAPI, '/api/profile/photo')
    api.add_resource(FacePromptShownAPI, '/api/face/mark-prompt-shown')
    api.add_resource(FaceRegisterAPI, '/api/face/register')
    api.add_resource(FaceLoginAPI, '/api/face/login')
    api.add_resource(FaceDeleteAPI, '/api/face/delete')
    api.add_resource(SaveActivityAPI, '/api/activity')
    
    # Disease News endpoints
    api.add_resource(DiseaseNewsTrendingAPI, '/api/disease-news/trending')
    api.add_resource(DiseaseNewsListAPI,     '/api/disease-news')
    api.add_resource(DiseaseNewsRefreshAPI,  '/api/disease-news/refresh')
    api.add_resource(DiseaseNewsImageProxyAPI, '/api/disease-news/image')
    api.add_resource(DiseaseNewsViewAPI,     '/api/disease-news/<int:news_id>/view')
    api.add_resource(ChatbotAPI, '/api/chatbot')
    api.add_resource(ChatHistoryAPI, '/api/chatbot/history')
    api.add_resource(ChatSessionListAPI, '/api/chatbot/sessions')
    api.add_resource(ChatSessionDetailAPI, '/api/chatbot/sessions/<int:session_id>')
    
    @app.route('/')
    def index():
        return redirect(url_for('admin_auth.login'))

    # Start background scheduler for disease news auto-refresh and cleanup
    from app.scheduler import start_scheduler

    # Jalankan scheduler hanya jika bukan di Vercel
    if os.environ.get("VERCEL") != "1":
        if os.environ.get("WERKZEUG_RUN_MAIN") != "false":
            start_scheduler(app)

    return app
