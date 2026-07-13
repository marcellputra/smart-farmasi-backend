"""
Scheduler untuk auto-refresh Disease News setiap 1 jam
dan safety cleanup cache setiap 2 hari.
Diinisialisasi dari create_app() di app/__init__.py.
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = None


def start_scheduler(app):
    """Mulai background scheduler. Hanya dipanggil sekali saat app start."""
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info("Scheduler already running, skipping.")
        return

    from app.api.disease_news import (
        cleanup_inactive_disease_news,
        fetch_and_store_disease_news,
    )
    from app.api.auth import cleanup_expired_otps, prune_permanently_deleted_users

    def refresh_job():
        logger.info("[Scheduler] Running disease news refresh...")
        try:
            saved = fetch_and_store_disease_news(app=app)
            logger.info("[Scheduler] Done: %d berita baru.", saved)
        except Exception as exc:
            logger.error("[Scheduler] Error: %s", exc)

    def cleanup_job():
        logger.info("[Scheduler] Running disease news cleanup...")
        try:
            deleted = cleanup_inactive_disease_news(app=app, retention_days=2)
            logger.info("[Scheduler] Cleanup done: %d berita inactive dihapus.", deleted)
        except Exception as exc:
            logger.error("[Scheduler] Cleanup error: %s", exc)

    def cleanup_otp_job():
        logger.info("[Scheduler] Running OTP cleanup...")
        try:
            deleted = cleanup_expired_otps(app=app, retention_days=3)
            logger.info("[Scheduler] OTP Cleanup done: %d OTP lama dihapus.", deleted)
        except Exception as exc:
            logger.error("[Scheduler] OTP Cleanup error: %s", exc)

    def prune_deleted_accounts_job():
        logger.info("[Scheduler] Running soft-deleted accounts pruning...")
        try:
            purged = prune_permanently_deleted_users(app=app, retention_days=30)
            if purged > 0:
                logger.info("[Scheduler] Pruning done: %d akun terhapus permanen dibersihkan.", purged)
        except Exception as exc:
            logger.error("[Scheduler] Pruning error: %s", exc)

    _scheduler = BackgroundScheduler(daemon=True, timezone="Asia/Jakarta")
    _scheduler.add_job(
        func=refresh_job,
        trigger=IntervalTrigger(hours=1),
        id="disease_news_refresh",
        name="Disease News Auto-Refresh",
        replace_existing=True,
    )
    _scheduler.add_job(
        func=cleanup_job,
        trigger=IntervalTrigger(days=2),
        id="disease_news_cleanup",
        name="Disease News Inactive Cleanup",
        replace_existing=True,
    )
    _scheduler.add_job(
        func=cleanup_otp_job,
        trigger=IntervalTrigger(days=3),
        id="otp_cleanup",
        name="OTP Expired Cleanup",
        replace_existing=True,
    )
    _scheduler.add_job(
        func=prune_deleted_accounts_job,
        trigger=IntervalTrigger(days=1),
        id="prune_deleted_users",
        name="Prune Scheduled User Deletions",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("[Scheduler] Disease news and user cleanup scheduler started.")

    # Jalankan sekali saat startup setelah 10 detik (hindari blocking startup)
    import threading
    def initial_fetch():
        import time
        time.sleep(10)
        refresh_job()

    t = threading.Thread(target=initial_fetch, daemon=True)
    t.start()


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Stopped.")
