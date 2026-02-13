"""
Email sender abstraction for notification delivery.

Supports multiple providers:
- SendGrid (production)
- SMTP (development)
- Mock (testing)

Story 9.1 - Notification Framework (Events → Channels)
"""

import os
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    """Email message data."""
    to_email: str
    to_name: Optional[str]
    subject: str
    html_body: str
    text_body: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    reply_to: Optional[str] = None
    tags: Optional[List[str]] = None


class EmailSender(ABC):
    """Abstract base class for email sending."""

    @abstractmethod
    async def send(self, message: EmailMessage) -> bool:
        """
        Send an email asynchronously.

        Args:
            message: Email message to send

        Returns:
            True on success, False on failure
        """
        pass

    @abstractmethod
    def send_sync(self, message: EmailMessage) -> bool:
        """
        Send an email synchronously.

        Args:
            message: Email message to send

        Returns:
            True on success, False on failure
        """
        pass


class SendGridEmailSender(EmailSender):
    """SendGrid email sender implementation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
    ):
        """
        Initialize SendGrid sender.

        Args:
            api_key: SendGrid API key (or from SENDGRID_API_KEY env var)
            from_email: Default sender email (or from NOTIFICATION_FROM_EMAIL env var)
            from_name: Default sender name (or from NOTIFICATION_FROM_NAME env var)
        """
        self.api_key = api_key or os.getenv("SENDGRID_API_KEY")
        self.from_email = from_email or os.getenv(
            "NOTIFICATION_FROM_EMAIL", "notifications@example.com"
        )
        self.from_name = from_name or os.getenv(
            "NOTIFICATION_FROM_NAME", "MarkInsight"
        )

        if not self.api_key:
            logger.warning("SendGrid API key not configured")

    async def send(self, message: EmailMessage) -> bool:
        """Send email via SendGrid API."""
        return self._send_impl(message)

    def send_sync(self, message: EmailMessage) -> bool:
        """Send email synchronously via SendGrid API."""
        return self._send_impl(message)

    def _send_impl(self, message: EmailMessage) -> bool:
        """Internal send implementation."""
        if not self.api_key:
            logger.error("Cannot send email: SendGrid API key not configured")
            return False

        try:
            import httpx

            from_email = message.from_email or self.from_email
            from_name = message.from_name or self.from_name

            payload = {
                "personalizations": [
                    {
                        "to": [{"email": message.to_email, "name": message.to_name or ""}],
                    }
                ],
                "from": {"email": from_email, "name": from_name},
                "subject": message.subject,
                "content": [
                    {"type": "text/html", "value": message.html_body},
                ],
            }

            if message.text_body:
                payload["content"].insert(0, {"type": "text/plain", "value": message.text_body})

            if message.reply_to:
                payload["reply_to"] = {"email": message.reply_to}

            if message.tags:
                payload["categories"] = message.tags

            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

            if response.status_code in (200, 202):
                logger.info(
                    "Email sent successfully",
                    extra={
                        "to_email": message.to_email,
                        "subject": message.subject,
                    },
                )
                return True
            else:
                logger.error(
                    "SendGrid API error",
                    extra={
                        "status_code": response.status_code,
                        "response": response.text,
                        "to_email": message.to_email,
                    },
                )
                return False

        except Exception as e:
            logger.error(
                "Failed to send email via SendGrid",
                extra={
                    "to_email": message.to_email,
                    "error": str(e),
                },
                exc_info=True,
            )
            return False


class SMTPEmailSender(EmailSender):
    """SMTP email sender for development/testing."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 587,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = True,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
    ):
        """
        Initialize SMTP sender.

        Args:
            host: SMTP server host
            port: SMTP server port
            username: SMTP username (optional)
            password: SMTP password (optional)
            use_tls: Whether to use TLS
            from_email: Default sender email
            from_name: Default sender name
        """
        self.host = host or os.getenv("SMTP_HOST", "localhost")
        self.port = port or int(os.getenv("SMTP_PORT", "587"))
        self.username = username or os.getenv("SMTP_USERNAME")
        self.password = password or os.getenv("SMTP_PASSWORD")
        self.use_tls = use_tls
        self.from_email = from_email or os.getenv(
            "NOTIFICATION_FROM_EMAIL", "notifications@example.com"
        )
        self.from_name = from_name or os.getenv(
            "NOTIFICATION_FROM_NAME", "MarkInsight"
        )

    async def send(self, message: EmailMessage) -> bool:
        """Send email via SMTP."""
        return self._send_impl(message)

    def send_sync(self, message: EmailMessage) -> bool:
        """Send email synchronously via SMTP."""
        return self._send_impl(message)

    def _send_impl(self, message: EmailMessage) -> bool:
        """Internal send implementation."""
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            from_email = message.from_email or self.from_email
            from_name = message.from_name or self.from_name

            msg = MIMEMultipart("alternative")
            msg["Subject"] = message.subject
            msg["From"] = f"{from_name} <{from_email}>"
            msg["To"] = message.to_email

            if message.reply_to:
                msg["Reply-To"] = message.reply_to

            if message.text_body:
                msg.attach(MIMEText(message.text_body, "plain"))
            msg.attach(MIMEText(message.html_body, "html"))

            with smtplib.SMTP(self.host, self.port) as server:
                if self.use_tls:
                    server.starttls()
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.sendmail(from_email, [message.to_email], msg.as_string())

            logger.info(
                "Email sent via SMTP",
                extra={
                    "to_email": message.to_email,
                    "subject": message.subject,
                },
            )
            return True

        except Exception as e:
            logger.error(
                "Failed to send email via SMTP",
                extra={
                    "to_email": message.to_email,
                    "error": str(e),
                },
                exc_info=True,
            )
            return False


class MockEmailSender(EmailSender):
    """Mock email sender for testing."""

    def __init__(self):
        """Initialize mock sender."""
        self.sent_messages: List[EmailMessage] = []

    async def send(self, message: EmailMessage) -> bool:
        """Record email in sent_messages list."""
        self.sent_messages.append(message)
        logger.info(
            "Mock email sent",
            extra={
                "to_email": message.to_email,
                "subject": message.subject,
            },
        )
        return True

    def send_sync(self, message: EmailMessage) -> bool:
        """Record email synchronously."""
        self.sent_messages.append(message)
        return True

    def clear(self) -> None:
        """Clear sent messages."""
        self.sent_messages.clear()


def get_email_sender() -> EmailSender:
    """
    Get configured email sender based on environment.

    Returns:
        Appropriate EmailSender implementation
    """
    provider = os.getenv("NOTIFICATION_EMAIL_PROVIDER", "sendgrid").lower()

    if provider == "smtp":
        return SMTPEmailSender()
    elif provider == "mock":
        return MockEmailSender()
    else:
        return SendGridEmailSender()
