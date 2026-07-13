# Smart Farmasi Backend

Flask + Flask-Admin backend for Smart Farmasi mobile app.

## Setup

1. Create database in phpMyAdmin:
   - Database: `smart_farmasi_db`
   - Charset: `utf8mb4_general_ci`

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Initialize migrations:
   ```bash
   flask --app run.py db init
   flask --app run.py db migrate -m "Initial migration"
   flask --app run.py db upgrade
   ```

4. Run server:
   ```bash
   python run.py
   ```

## API Endpoints

- POST `/api/register` - Register new user (name, email, password)
- POST `/api/login` - Login (email, password)
- GET `/api/profile` - Get user profile (requires JWT token)
- POST `/api/activity` - Save user activity (requires JWT token)

## Admin Dashboard

Access at `http://localhost:5000/admin/`

Features:
- User Management (CRUD, role assignment)
- User Activity monitoring
- Dashboard stats (total users, today's users, activities)