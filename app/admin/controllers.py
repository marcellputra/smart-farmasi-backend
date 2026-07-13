from app.models import User, UserActivity, EmailOTP, DiseaseNews, db
from datetime import datetime, timedelta

class AdminController:
    """
    Controller handling the business logic for the Admin Dashboard.
    Provides stats specifically for Smart Pharmacy features.
    """
    
    @staticmethod
    def get_dashboard_stats():
        """Fetches aggregated data for Smart Pharmacy features."""
        total_users = User.query.count()
        today = datetime.now().date()
        new_users_today = User.query.filter(db.func.date(User.created_at) == today).count()
        
        # Feature-specific stats from Activity Logs
        total_scans = UserActivity.query.filter_by(activity_type='scan').count()
        total_symptoms = UserActivity.query.filter_by(activity_type='symptom_check').count()
        total_consultations = UserActivity.query.filter_by(activity_type='chatbot').count()
        
        return {
            'total_users': total_users,
            'active_today': new_users_today,
            'total_scans': total_scans,
            'total_symptoms': total_symptoms,
            'total_consultations': total_consultations,
            'total_activities': UserActivity.query.count()
        }

    @staticmethod
    def get_recent_activities(limit=10):
        """Fetches the most recent user activities."""
        return UserActivity.query.order_by(UserActivity.timestamp.desc()).limit(limit).all()

    @staticmethod
    def get_recent_users(limit=8):
        """Fetches the newest users for quick admin actions."""
        return User.query.order_by(User.created_at.desc()).limit(limit).all()

    @staticmethod
    def get_viral_news(alert_level=None, limit=20):
        """Returns top disease news sorted by view_count then trend_score (most viral first).
        Optionally filters by alert_level ('low', 'medium', 'high').
        """
        from sqlalchemy import case as sa_case
        query = DiseaseNews.query.filter(DiseaseNews.is_active == True)
        if alert_level and alert_level in ('low', 'medium', 'high'):
            query = query.filter(DiseaseNews.alert_level == alert_level)
        # Sort: view_count first; if equal (both 0), fall back to trend_score
        news_list = query.order_by(
            DiseaseNews.view_count.desc(),
            DiseaseNews.trend_score.desc()
        ).limit(limit).all()
        return [
            {
                'id': n.id,
                'title': n.title,
                'disease_name': n.disease_name or '-',
                'country': n.country or 'International',
                'source_name': n.source_name,
                'alert_level': n.alert_level if isinstance(n.alert_level, str) else (n.alert_level.value if hasattr(n.alert_level, 'value') else str(n.alert_level)),
                'is_trending': n.is_trending,
                'view_count': n.view_count or 0,
                'trend_score': n.trend_score or 0,
                'region_scope': n.region_scope,
                'published_at': n.published_at.strftime('%d %b %Y') if n.published_at else '-',
            }
            for n in news_list
        ]

    @staticmethod
    def get_user_growth(days=30):
        """Returns daily user registration counts for the given number of past days."""
        now = datetime.utcnow()
        start = now - timedelta(days=days - 1)
        # Build a full date range
        dates_range = [
            (start.date() + timedelta(days=i)).strftime('%Y-%m-%d')
            for i in range(days)
        ]
        # Query grouped by date
        rows = db.session.query(
            db.func.date(User.created_at).label('day'),
            db.func.count(User.id).label('count')
        ).filter(
            User.created_at >= start
        ).group_by(
            db.func.date(User.created_at)
        ).all()

        count_map = {str(r.day): r.count for r in rows}
        return {
            'labels': dates_range,
            'counts': [count_map.get(d, 0) for d in dates_range],
        }

    @staticmethod
    def delete_user(user_id, current_admin_id=None):

        """Deletes a user and their dependent records safely."""
        user = User.query.get(user_id)
        if not user:
            return False, 'User tidak ditemukan.'

        if current_admin_id and user.id == current_admin_id:
            return False, 'Anda tidak bisa menghapus akun admin yang sedang digunakan.'

        if user.role == 'admin':
            admin_count = User.query.filter_by(role='admin').count()
            if admin_count <= 1:
                return False, 'Tidak bisa menghapus admin terakhir.'

        user_email = user.email
        try:
            EmailOTP.query.filter_by(user_id=user.id).delete(synchronize_session=False)
            UserActivity.query.filter_by(user_id=user.id).delete(synchronize_session=False)
            User.query.filter_by(id=user.id).delete(synchronize_session=False)
            db.session.commit()
            return True, f'User {user_email} berhasil dihapus.'
        except Exception as exc:
            db.session.rollback()
            return False, f'Gagal menghapus user: {exc}'
