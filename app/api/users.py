from flask_restful import Resource
from flask import request
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import User, UserActivity, db

class SaveActivityAPI(Resource):
    @jwt_required()
    def get(self):
        try:
            user_id = get_jwt_identity()
            exclude_types = [
                'login', 'login_google', 'register', 'verify_email', 'resend_otp',
                'forgot_password', 'reset_password', 'request_app_password',
                'verify_app_password_otp', 'set_app_password', 'request_email_change',
                'confirm_email_change', 'request_password_change', 'confirm_password_change',
                'update_profile', 'update_profile_photo', 'delete_profile_photo',
                'request_delete_otp', 'account_deletion_scheduled', 'account_reactivated'
            ]
            activities = UserActivity.query.filter(
                UserActivity.user_id == int(user_id),
                ~UserActivity.activity_type.in_(exclude_types)
            ).order_by(UserActivity.timestamp.desc()).all()
            
            return {
                'status': 'success',
                'activities': [
                    {
                        'id': a.id,
                        'activity_type': a.activity_type,
                        'description': a.description,
                        'timestamp': a.timestamp.isoformat()
                    } for a in activities
                ]
            }, 200
        except Exception as e:
            return {'message': f'Internal Server Error: {str(e)}'}, 500

    @jwt_required()
    def post(self):
        try:
            user_id = get_jwt_identity()
            data = request.get_json()
            
            if not data or 'activity_type' not in data:
                return {'message': 'Missing activity_type'}, 400
                
            activity = UserActivity(
                user_id=int(user_id),
                activity_type=data['activity_type'],
                description=data.get('description', '')
            )
            db.session.add(activity)
            db.session.commit()
            return {'message': 'Activity saved successfully'}, 201
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500