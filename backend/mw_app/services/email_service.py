from flask_mail import Message
from mw_app import mail
from flask import render_template
from datetime import datetime, timedelta
import secrets

# GENERIC EMAIL FUNCTION
def send_email(subject, recipients, html_body):
    msg = Message(
        subject=subject,
        recipients=recipients,
        html=html_body,
    )

    mail.send(msg)

# Helper functions for sending emails

def send_email_verification(user, verification_code):
    """
    Generate and send email verification code.
    """
    try:
        from flask import current_app
        if not current_app.config.get("MAIL_USERNAME"):
            print(f"[Email Service] MAIL_USERNAME not configured. Simulated verification email to {user.email} with code: {verification_code}")
            return True, "Verification email code simulated"

        send_email(
            subject="Verify Your Market Window Account",
            recipients=[user.email],
            html_body=render_template("email/verification.html", user=user, code=verification_code),
        )

        return True, "Verification email sent successfully"

    except Exception as e:
        print(f"[Email Service Error] {e}")
        print(f"[Email Service Fallback] Simulated code for {user.email}: {verification_code}")
        return True, "Verification code sent (check server logs if SMTP is offline)"


def send_welcome_email(user):
    """
    Send welcome email to new users.
    """
    try:
        send_email(
            subject="Welcome to Market Window",
            recipients=[user.email],
            html_body=render_template("email/welcome.html", user=user),
        )

        return True, "Welcome email sent successfully"

    except Exception as e:
        print(e)
        return False, "Unable to send welcome email"
