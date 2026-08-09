"""
Sends the alert via ntfy.sh push notification (default, no signup needed)
and/or email. Controlled by the NOTIFY_METHOD env var: "ntfy", "email", or "both".
"""
import os
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

NOTIFY_METHOD = os.environ.get("NOTIFY_METHOD", "ntfy")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))


def send_ntfy(title, message, image_path=None):
    if not NTFY_TOPIC:
        print("NTFY_TOPIC not set, skipping ntfy notification")
        return
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": "high",
        "Tags": "chart_with_upwards_trend,gold",
    }
    try:
        if image_path and os.path.exists(image_path):
            headers["Filename"] = "signal.png"
            headers["Message"] = message.replace("\n", " | ").encode("utf-8")
            with open(image_path, "rb") as f:
                requests.put(url, data=f, headers=headers, timeout=20)
        else:
            requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=20)
    except requests.RequestException as e:
        print(f"ntfy send failed: {e}")


def send_email(subject, body, image_path=None):
    if not (EMAIL_FROM and EMAIL_PASSWORD and EMAIL_TO):
        print("Email credentials not fully set, skipping email notification")
        return
    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            img = MIMEImage(f.read())
            img.add_header("Content-Disposition", "attachment", filename="signal.png")
            msg.attach(img)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"Email send failed: {e}")


def notify(title, message, image_path=None):
    if NOTIFY_METHOD in ("ntfy", "both"):
        send_ntfy(title, message, image_path)
    if NOTIFY_METHOD in ("email", "both"):
        send_email(title, message, image_path)
