from app import create_app
from app.models import db, User

app = create_app()
with app.app_context():
    users = User.query.all()
    print("=== DAFTAR USER DI DATABASE ===")
    for u in users:
        print(f"Name: {u.name} | Email: {u.email}")
    if not users:
        print("Database Kosong!")
