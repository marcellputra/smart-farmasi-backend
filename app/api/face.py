from flask import request
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token

from app.models import db, User, FaceRecognition
from app.services.face_service import face_service
from app.api.auth import _serialize_user

class FacePromptShownAPI(Resource):
    @jwt_required()
    def post(self):
        try:
            user_id = get_jwt_identity()
            user = User.query.get(int(user_id))

            if not user:
                return {'message': 'User not found'}, 404

            if not user.face_prompt_shown:
                user.face_prompt_shown = True
                db.session.commit()

            return {
                'message': 'Face prompt marked as shown',
                'face_prompt_shown': True
            }, 200

        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class FaceRegisterAPI(Resource):
    @jwt_required()
    def post(self):
        try:
            user_id = get_jwt_identity()
            user = User.query.get(int(user_id))

            if not user:
                return {'message': 'User not found'}, 404

            photo = request.files.get('photo')
            if not photo:
                return {'message': 'Photo is required'}, 400

            image_bytes = photo.read()
            if not image_bytes:
                return {'message': 'Photo is empty'}, 400

            embedding = face_service.generate_embedding(image_bytes)
            embedding_json = face_service.embedding_to_json(embedding)

            face_data = FaceRecognition.query.filter_by(user_id=user.id).first()

            if face_data:
                face_data.face_encoding = embedding_json
                face_data.is_active = True
            else:
                face_data = FaceRecognition(
                    user_id=user.id,
                    face_encoding=embedding_json,
                    is_active=True
                )
                db.session.add(face_data)

            user.face_prompt_shown = True
            db.session.commit()

            return {
                'message': 'Face registered successfully',
                'face_registered': True,
                'face_prompt_shown': True
            }, 200

        except ValueError as e:
            db.session.rollback()
            return {'message': str(e)}, 400

        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class FaceLoginAPI(Resource):
    def post(self):
        try:
            photo = request.files.get('photo')
            if not photo:
                return {'message': 'Photo is required'}, 400

            image_bytes = photo.read()
            if not image_bytes:
                return {'message': 'Photo is empty'}, 400

            login_embedding = face_service.generate_embedding(image_bytes)
            all_faces = FaceRecognition.query.filter_by(is_active=True).all()

            if not all_faces:
                return {'message': 'Belum ada data wajah terdaftar'}, 404

            best_user = None
            best_score = 0.0

            for face_data in all_faces:
                if not face_data.user:
                    continue

                saved_embedding = face_service.json_to_embedding(face_data.face_encoding)
                result = face_service.verify(login_embedding, saved_embedding)

                if result['score'] > best_score:
                    best_score = result['score']
                    best_user = face_data.user

            threshold = 0.75
            if not best_user or best_score < threshold:
                return {
                    'message': 'Wajah tidak dikenali',
                    'score': best_score
                }, 401

            if not best_user.is_active or best_user.deleted_at:
                return {'message': 'Akun tidak aktif'}, 403

            access_token = create_access_token(
                identity=str(best_user.id),
                additional_claims={"role": best_user.role}
            )

            return {
                'token': access_token,
                'user': _serialize_user(best_user),
                'login_method': 'face',
                'score': best_score
            }, 200

        except ValueError as e:
            return {'message': str(e)}, 400

        except Exception as e:
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class FaceDeleteAPI(Resource):
    @jwt_required()
    def delete(self):
        try:
            user_id = get_jwt_identity()
            user = User.query.get(int(user_id))

            if not user:
                return {'message': 'User not found'}, 404

            face_data = FaceRecognition.query.filter_by(
                user_id=user.id,
                is_active=True
            ).first()

            if not face_data:
                return {'message': 'Data wajah tidak ditemukan atau sudah dihapus'}, 404

            face_data.is_active = False
            db.session.commit()

            return {
                'message': 'Data wajah berhasil dihapus',
                'face_registered': False
            }, 200

        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500