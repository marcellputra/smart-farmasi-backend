from markupsafe import Markup

class AdminUIComponents:
    """
    Helper class for generating UI components and formatters.
    Ensures consistency between the dashboard and the mobile app's look.
    """
    
    @staticmethod
    def status_badge_formatter(view, context, model, name):
        """Formats activity types into modern badges."""
        val = getattr(model, name)
        badge_class = "badge-other"
        
        if val == "login":
            badge_class = "badge-login"
        elif val == "register":
            badge_class = "badge-register"
            
        return Markup(
            f'<span class="modern-badge {badge_class}">{val}</span>'
        )

    @staticmethod
    def date_formatter(view, context, model, name):
        """Standardizes date formatting for the admin panel."""
        val = getattr(model, name)
        if not val:
            return ""
        return val.strftime('%d %b %Y, %H:%M')

    @staticmethod
    def boolean_badge_formatter(view, context, model, name):
        """Formats boolean values into modern pill badges."""
        val = getattr(model, name)
        badge_class = "badge-success" if val else "badge-secondary"
        text = "YES" if val else "NO"
        
        return Markup(
            f'<span class="modern-badge {badge_class}" style="font-size: 0.7rem; padding: 4px 10px;">{text}</span>'
        )
