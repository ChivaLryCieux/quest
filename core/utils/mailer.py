import logging
import threading

import resend

from core.config.settings import Config

logger = logging.getLogger(__name__)

# 同步 resend 全局 api_key 的锁：切换模式时不互相覆盖
_api_key_lock = threading.Lock()


class MailService:
    def __init__(self, api_key=None, mail_from=None, mail_to=None):
        self.api_key = api_key or Config.RESEND_API_KEY
        self.mail_from = mail_from or Config.MAIL_FROM
        self.mail_to = mail_to or Config.MAIL_TO
        self.enabled = bool(Config.ENABLE_MAIL_REPORT and self.api_key and self.mail_to)
        if not self.enabled:
            logger.info("MailService disabled (ENABLE_MAIL_REPORT/API key/MAIL_TO not fully configured)")

    def send_alert(self, subject, html):
        if not self.enabled:
            return False

        try:
            with _api_key_lock:
                resend.api_key = self.api_key
                resend.Emails.send({
                    "from": self.mail_from,
                    "to": self.mail_to,
                    "subject": subject,
                    "html": html,
                })
            logger.info("Alert email sent: %s", subject)
            return True
        except Exception as exc:
            logger.error("Failed to send alert email: %s", exc)
            return False
