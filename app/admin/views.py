from flask import session, redirect, url_for, request, flash
from flask_admin import Admin, expose, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_admin.theme import Bootstrap4Theme
from app.models import User, UserActivity, ChatHistory, DiseaseNews, db
from .controllers import AdminController
from .components import AdminUIComponents

class MyHomeView(AdminIndexView):
    def is_accessible(self):
        return session.get('is_admin') == True

    def inaccessible_callback(self, name, **kwargs):
        flash('Please login to access the dashboard.', 'warning')
        return redirect(url_for('admin_auth.login', next=request.url))

    @expose('/')
    def index(self):
        stats = AdminController.get_dashboard_stats()
        recent_activities = AdminController.get_recent_activities()
        recent_users = AdminController.get_recent_users()
        
        return self.render('admin/index.html', 
                         total_users=stats.get('total_users', 0),
                         active_today=stats.get('active_today', 0),
                         total_scans=stats.get('total_scans', 0),
                         total_symptoms=stats.get('total_symptoms', 0),
                         total_consultations=stats.get('total_consultations', 0),
                         total_activities=stats.get('total_activities', 0),
                         recent_activities=recent_activities,
                         recent_users=recent_users)

    @expose('/api/analytics')
    def get_analytics_data(self):
        from flask import jsonify
        import datetime
        from app.models import DiseaseNews
        
        # Check accessibility manually to ensure it's not bypassed (just in case)
        if not self.is_accessible():
            return jsonify({'error': 'Unauthorized'}), 403
            
        days = request.args.get('days', default=7, type=int)
        if days not in [7, 15, 30]:
            days = 7
            
        # Calculate range
        now = datetime.datetime.utcnow()
        start_date = now - datetime.timedelta(days=days)
        
        # 1. Query Activity trends
        results = db.session.query(
            db.func.date(UserActivity.timestamp).label('date'),
            UserActivity.activity_type,
            db.func.count(UserActivity.id)
        ).filter(
            UserActivity.timestamp >= start_date,
            UserActivity.activity_type.in_(['scan', 'symptom_check', 'chatbot'])
        ).group_by(
            db.func.date(UserActivity.timestamp),
            UserActivity.activity_type
        ).order_by(
            db.func.date(UserActivity.timestamp).asc()
        ).all()
        
        # Populate all dates in the range
        dates_range = [(now.date() - datetime.timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days-1, -1, -1)]
        activity_data = {
            'labels': dates_range,
            'scans': [0] * len(dates_range),
            'symptoms': [0] * len(dates_range),
            'chatbot': [0] * len(dates_range)
        }
        
        date_map = {date: idx for idx, date in enumerate(dates_range)}
        
        for row in results:
            row_date = row[0]
            # Format date to string 'YYYY-MM-DD'
            if isinstance(row_date, (datetime.datetime, datetime.date)):
                date_str = row_date.strftime('%Y-%m-%d')
            else:
                date_str = str(row_date)
                
            if date_str in date_map:
                idx = date_map[date_str]
                if row[1] == 'scan':
                    activity_data['scans'][idx] = row[2]
                elif row[1] == 'symptom_check':
                    activity_data['symptoms'][idx] = row[2]
                elif row[1] == 'chatbot':
                    activity_data['chatbot'][idx] = row[2]
                    
        # 2. Disease alert level distribution
        alert_counts = db.session.query(
            DiseaseNews.alert_level,
            db.func.count(DiseaseNews.id)
        ).group_by(DiseaseNews.alert_level).all()
        
        alerts = {'low': 0, 'medium': 0, 'high': 0}
        for level, count in alert_counts:
            level_str = level.value if hasattr(level, 'value') else str(level)
            alerts[level_str.lower()] = count
            
        # 3. Top diseases by news — uses view_count if available, else trend_score
        # (view_count starts at 0 until users open articles; trend_score is always populated)
        disease_views = db.session.query(
            DiseaseNews.disease_name,
            db.func.sum(
                db.case(
                    (DiseaseNews.view_count > 0, DiseaseNews.view_count),
                    else_=DiseaseNews.trend_score
                )
            ).label('score')
        ).filter(
            DiseaseNews.disease_name != None,
            DiseaseNews.disease_name != '',
            DiseaseNews.is_active == True
        ).group_by(DiseaseNews.disease_name).order_by(
            db.text('score DESC')
        ).limit(5).all()

        disease_data = {
            'labels': [row[0] for row in disease_views],
            'views': [int(row[1]) if row[1] is not None else 0 for row in disease_views]
        }
        
        # 4. User growth per day
        user_growth = AdminController.get_user_growth(days=days)

        # 5. Summary analytics metrics
        total_scans = sum(activity_data['scans'])
        total_symptoms = sum(activity_data['symptoms'])
        total_chats = sum(activity_data['chatbot'])
        total_volume = total_scans + total_symptoms + total_chats
        
        feature_sums = {'Medication Scans': total_scans, 'Symptom Checks': total_symptoms, 'AI Chats': total_chats}
        most_active = max(feature_sums, key=feature_sums.get) if total_volume > 0 else 'N/A'
        
        summary = {
            'total_volume': total_volume,
            'most_active_feature': most_active,
            'scans_percentage': int(total_scans / total_volume * 100) if total_volume > 0 else 0,
            'symptoms_percentage': int(total_symptoms / total_volume * 100) if total_volume > 0 else 0,
            'chats_percentage': int(total_chats / total_volume * 100) if total_volume > 0 else 0,
        }
        
        return jsonify({
            'status': 'success',
            'days': days,
            'activities': activity_data,
            'alerts': alerts,
            'diseases': disease_data,
            'user_growth': user_growth,
            'summary': summary
        })

    @expose('/api/viral-news')
    def get_viral_news(self):
        """Returns top viral disease news for the admin dashboard table."""
        from flask import jsonify
        if not self.is_accessible():
            return jsonify({'error': 'Unauthorized'}), 403
        alert_filter = request.args.get('alert_level', default=None)
        limit = request.args.get('limit', default=20, type=int)
        data = AdminController.get_viral_news(alert_level=alert_filter, limit=limit)
        return jsonify({'status': 'success', 'news': data, 'total': len(data)})

    @expose('/users/<int:user_id>/delete', methods=['POST'])
    def delete_user(self, user_id):
        current_admin_id = session.get('user_id')
        success, message = AdminController.delete_user(user_id, current_admin_id)
        flash(message, 'success' if success else 'danger')
        return redirect(request.referrer or url_for('admin.index'))

class SecureModelView(ModelView):
    def is_accessible(self):
        return session.get('is_admin') == True

    def inaccessible_callback(self, name, **kwargs):
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('admin_auth.login'))

class UserAdmin(SecureModelView):
    """View for managing users."""
    column_list = ['id', 'name', 'email', 'role', 'login_provider', 'created_at']
    column_searchable_list = ['name', 'email']
    form_columns = ['name', 'email', 'role', 'is_active', 'login_provider']
    
    column_formatters = {
        'created_at': AdminUIComponents.date_formatter,
        'role': lambda v, c, m, p: m.role.upper() if m.role else 'USER',
    }

    def delete_model(self, model):
        current_admin_id = session.get('user_id')
        success, message = AdminController.delete_user(model.id, current_admin_id)
        if not success:
            flash(message, 'danger')
        else:
            flash(message, 'success')
        return success

class ActivityAdmin(SecureModelView):
    """View for monitoring user activities."""
    column_list = ['id', 'user', 'activity_type', 'timestamp']
    column_filters = ['activity_type', 'user.email']
    
    column_formatters = {
        'activity_type': AdminUIComponents.status_badge_formatter,
        'timestamp': AdminUIComponents.date_formatter
    }

class ChatHistoryAdmin(SecureModelView):
    """View for auditing AI chatbot conversations."""
    column_list = ['id', 'user', 'user_message', 'bot_response', 'timestamp']
    column_searchable_list = ['user_message', 'bot_response', 'user.email']
    column_filters = ['user.email', 'timestamp']
    column_formatters = {
        'timestamp': AdminUIComponents.date_formatter
    }

class DiseaseNewsAdmin(SecureModelView):
    """View for managing epidemic alerts & health news."""
    column_list = ['id', 'title', 'disease_name', 'country', 'source_name', 'alert_level', 'region_scope', 'is_trending', 'view_count', 'published_at']
    column_searchable_list = ['title', 'disease_name', 'summary']
    column_filters = ['alert_level', 'region_scope', 'is_trending']
    form_choices = {
        'alert_level': [('low', 'LOW'), ('medium', 'MEDIUM'), ('high', 'HIGH')],
        'region_scope': [('indonesia', 'Indonesia'), ('international', 'International')]
    }
    column_formatters = {
        'alert_level': AdminUIComponents.status_badge_formatter,
        'published_at': AdminUIComponents.date_formatter
    }

# Initialize the Admin instance with our custom Home View
admin = Admin(
    name='SEHATI', 
    index_view=MyHomeView(name='Dashboard', menu_icon_type='fa', menu_icon_value='fa-th-large'),
    theme=Bootstrap4Theme()
)

def init_admin(app):
    """Initializes the admin panel for the Flask app."""
    admin.init_app(app)
    
    # Add other views
    admin.add_view(UserAdmin(User, db.session, name='Users', menu_icon_type='fa', menu_icon_value='fa-users'))
    admin.add_view(ActivityAdmin(UserActivity, db.session, name='Activities', menu_icon_type='fa', menu_icon_value='fa-history'))
    admin.add_view(ChatHistoryAdmin(ChatHistory, db.session, name='Chatbot Logs', menu_icon_type='fa', menu_icon_value='fa-robot'))
    admin.add_view(DiseaseNewsAdmin(DiseaseNews, db.session, name='Disease Alerts', menu_icon_type='fa', menu_icon_value='fa-newspaper'))
