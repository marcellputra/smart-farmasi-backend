from app import create_app
from app.models import db, User
import datetime
import os
import sys

def seed_admin():
    app = create_app()
    with app.app_context():
        # Check if admin already exists
        admin_email = 'admin@smartfarmasi.com'
        existing_admin = User.query.filter_by(email=admin_email).first()
        
        if existing_admin:
            print(f"Admin with email {admin_email} already exists.")
            # Ensure it's an admin
            existing_admin.role = 'admin'
            existing_admin.mark_email_verified()
            db.session.commit()
        else:
            admin = User(
                name='Super Admin',
                email=admin_email,
                role='admin',
                login_provider='email',
                is_verified=True,
                email_verified_at=datetime.datetime.utcnow()
            )
            admin_password = os.environ.get('ADMIN_PASSWORD') or 'admin123'
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            print(f"Default admin created successfully: {admin_email} / {admin_password}")

if __name__ == '__main__':
    seed_admin()
