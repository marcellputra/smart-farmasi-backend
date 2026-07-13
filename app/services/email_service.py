from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

from flask import current_app


class EmailDeliveryError(Exception):
    pass


_OTP_PURPOSE_COPY = {
    'verify_email': {
        'subject': 'Kode OTP Verifikasi Email Smart Farmasi',
        'title': 'Verifikasi Email',
        'intro': 'Masukkan kode OTP berikut untuk menyelesaikan verifikasi email Anda.',
        'fallback': 'Kode OTP verifikasi email Anda adalah:',
    },
    'password_reset': {
        'subject': 'Kode OTP Reset Password Smart Farmasi',
        'title': 'Reset Password',
        'intro': 'Masukkan kode OTP berikut untuk membuat password baru akun Anda.',
        'fallback': 'Kode OTP reset password Anda adalah:',
    },
    'email_change': {
        'subject': 'Kode OTP Verifikasi Email Baru Smart Farmasi',
        'title': 'Verifikasi Email Baru',
        'intro': 'Masukkan kode OTP berikut untuk mengaktifkan email baru di akun Anda.',
        'fallback': 'Kode OTP verifikasi email baru Anda adalah:',
    },
    'password_change': {
        'subject': 'Kode OTP Ganti Password Smart Farmasi',
        'title': 'Konfirmasi Ganti Password',
        'intro': 'Masukkan kode OTP berikut untuk menyelesaikan perubahan password akun Anda.',
        'fallback': 'Kode OTP ganti password Anda adalah:',
    },
    'admin_login': {
        'subject': 'Kode OTP Login Admin Smart Farmasi',
        'title': 'Login Admin',
        'intro': 'Masukkan kode OTP berikut untuk masuk ke dashboard admin Smart Farmasi.',
        'fallback': 'Kode OTP login admin Anda adalah:',
    },
    'app_password': {
        'subject': 'Kode OTP Buat Password Aplikasi Smart Farmasi',
        'title': 'Buat Password Aplikasi',
        'intro': 'Masukkan kode OTP berikut untuk menautkan password aplikasi ke akun Google Anda.',
        'fallback': 'Kode OTP buat password aplikasi Anda adalah:',
    },
    'delete_account': {
        'subject': 'PENTING: Kode OTP Penghapusan Akun Smart Farmasi',
        'title': 'Konfirmasi Hapus Akun',
        'intro': 'PERINGATAN KEAMANAN: Masukkan kode OTP berikut untuk menyetujui penonaktifan dan penghapusan akun Anda.',
        'fallback': 'Kode OTP konfirmasi hapus akun Anda adalah:',
    },
}


def send_otp_email(to_email, otp_code, recipient_name=None, purpose='verify_email'):
    mail_username = current_app.config.get('MAIL_USERNAME')
    mail_password = current_app.config.get('MAIL_PASSWORD')
    mail_host = current_app.config.get('MAIL_HOST')
    mail_port = current_app.config.get('MAIL_PORT')
    mail_use_tls = current_app.config.get('MAIL_USE_TLS')
    mail_use_ssl = current_app.config.get('MAIL_USE_SSL')
    sender = current_app.config.get('MAIL_DEFAULT_SENDER') or mail_username

    if not mail_username or not mail_password:
        raise EmailDeliveryError('Konfigurasi SMTP belum lengkap. Isi MAIL_USERNAME dan MAIL_PASSWORD di .env.')

    app_name = 'Smart Farmasi'
    name = recipient_name or 'Pengguna'
    copy = _OTP_PURPOSE_COPY.get(purpose, _OTP_PURPOSE_COPY['verify_email'])
    subject = copy['subject']

    expires_minutes = current_app.config.get('OTP_EXPIRES_SECONDS', 180) // 60

    plain_body = (
        f'Halo {name},\n\n'
        f"{copy['fallback']} {otp_code}\n"
        f'Kode ini berlaku selama {expires_minutes} menit dan hanya bisa digunakan satu kali.\n\n'
        'Jika Anda tidak melakukan permintaan ini di Smart Farmasi, abaikan email ini.'
    )
    html_body = f"""
    <div style="margin:0;padding:24px;background:#f6faf8;font-family:Arial,sans-serif;color:#111827;">
      <div style="max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden;">
        <div style="background:#0b6e4f;padding:22px 26px;color:#ffffff;">
          <h1 style="margin:0;font-size:22px;">{copy['title']}</h1>
          <p style="margin:6px 0 0;font-size:14px;opacity:.9;">{app_name}</p>
        </div>
        <div style="padding:26px;">
          <p style="margin:0 0 12px;font-size:15px;">Halo {name},</p>
          <p style="margin:0 0 18px;font-size:15px;line-height:1.6;">
            {copy['intro']}
          </p>
          <div style="letter-spacing:8px;font-size:32px;font-weight:700;color:#0b6e4f;background:#e6f4ef;border-radius:12px;padding:18px 20px;text-align:center;">
            {otp_code}
          </div>
          <p style="margin:18px 0 0;font-size:14px;color:#6b7280;line-height:1.6;">
            Kode ini berlaku selama {expires_minutes} menit dan hanya bisa digunakan satu kali.
          </p>
          <p style="margin:10px 0 0;font-size:13px;color:#9ca3af;">
            Jika Anda tidak melakukan permintaan ini di Smart Farmasi, abaikan email ini.
          </p>
        </div>
      </div>
    </div>
    """

    message = MIMEMultipart('alternative')
    message['Subject'] = subject
    message['From'] = sender
    message['To'] = to_email
    message.attach(MIMEText(plain_body, 'plain'))
    message.attach(MIMEText(html_body, 'html'))

    try:
        if mail_use_ssl:
            with smtplib.SMTP_SSL(mail_host, mail_port) as server:
                server.login(mail_username, mail_password)
                server.sendmail(sender, [to_email], message.as_string())
        else:
            with smtplib.SMTP(mail_host, mail_port) as server:
                if mail_use_tls:
                    server.starttls()
                server.login(mail_username, mail_password)
                server.sendmail(sender, [to_email], message.as_string())
    except Exception as exc:
        raise EmailDeliveryError(f'Gagal mengirim email OTP: {exc}') from exc
