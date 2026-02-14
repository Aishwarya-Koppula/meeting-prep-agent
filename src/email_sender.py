"""
Email delivery module using Gmail SMTP.

Renders the daily digest into a beautiful HTML email using Jinja2
templates and sends it via Gmail's SMTP server.

How Gmail SMTP works:
    1. Connect to smtp.gmail.com on port 587
    2. Start TLS encryption (secure connection)
    3. Login with your email + App Password (NOT your regular password)
    4. Send the email
    5. Close the connection

Setting up Gmail App Password:
    1. Go to https://myaccount.google.com/security
    2. Enable 2-Step Verification (required)
    3. Go to App Passwords (search for it)
    4. Generate a password for "Mail"
    5. Use that 16-character password in your .env file

See docs/SETUP.md for detailed instructions.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.models import DailyDigest
from src.config import EmailConfig

logger = logging.getLogger(__name__)


class EmailSender:
    """
    Renders and sends the daily digest email via Gmail SMTP.

    Usage:
        sender = EmailSender(config)
        success = sender.send_digest(digest)
    """

    def __init__(self, config: EmailConfig):
        self.config = config

        # Set up Jinja2 template environment
        # Looks for templates in src/templates/ directory
        template_dir = Path(__file__).parent / "templates"
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True,  # Prevents XSS in HTML output
        )

    def send_digest(self, digest: DailyDigest) -> bool:
        """
        Render the digest to HTML and send via SMTP.

        Args:
            digest: The daily digest containing all prep briefs

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            # Step 1: Render HTML from template
            html_body = self._render_html(digest)
            text_body = self._render_plain_text(digest)

            # Step 2: Build the subject line
            date_str = digest.date.strftime("%b %d, %Y")
            subject = self.config.subject_template.format(date=date_str)

            # Step 3: Send via SMTP
            success = self._send_smtp(subject, html_body, text_body)

            if success:
                logger.info(f"Digest email sent to {self.config.recipient}")
            return success

        except Exception as e:
            logger.error(f"Failed to send digest email: {e}")
            return False

    def _render_html(self, digest: DailyDigest) -> str:
        """
        Render the HTML email template with Jinja2.

        The template receives the digest data as template variables.
        """
        template = self.jinja_env.get_template("email_template.html")
        context = digest.to_email_context()
        return template.render(**context)

    def _render_plain_text(self, digest: DailyDigest) -> str:
        """
        Create a plain text version of the digest.

        This is shown by email clients that don't support HTML
        (rare but good practice to include).
        """
        lines = []
        lines.append(f"Meeting Prep Brief - {digest.date.strftime('%A, %B %d, %Y')}")
        lines.append(f"You have {digest.total_meetings} meeting(s) today")
        lines.append("=" * 50)
        lines.append("")

        for brief in digest.briefs:
            event = brief.event.event
            lines.append(f"[{brief.event.priority.value.upper()}] {event.title}")
            lines.append(
                f"  Time: {event.start_time.strftime('%I:%M %p')} - "
                f"{event.end_time.strftime('%I:%M %p')} "
                f"({brief.event.duration_minutes} min)"
            )

            if event.attendees:
                lines.append(f"  Attendees: {', '.join(event.attendees)}")

            lines.append(f"\n  Summary: {brief.summary}")

            if brief.talking_points:
                lines.append("\n  Talking Points:")
                for tp in brief.talking_points:
                    lines.append(f"    - [{tp.category}] {tp.point}")

            if brief.suggested_questions:
                lines.append("\n  Questions to Ask:")
                for q in brief.suggested_questions:
                    lines.append(f"    - \"{q}\"")

            if brief.context_notes:
                lines.append(f"\n  Prep: {brief.context_notes}")

            if event.meeting_link:
                lines.append(f"\n  Join: {event.meeting_link}")

            lines.append("")
            lines.append("-" * 50)
            lines.append("")

        lines.append(f"\nGenerated at {digest.generated_at.strftime('%I:%M %p')}")
        lines.append("by AI Meeting Prep Agent")

        return "\n".join(lines)

    def _send_smtp(self, subject: str, html_body: str, text_body: str) -> bool:
        """
        Send email via Gmail SMTP.

        Steps:
        1. Create MIME multipart message (contains both HTML and plain text)
        2. Connect to Gmail SMTP server
        3. Start TLS encryption
        4. Authenticate with App Password
        5. Send the email
        """
        # Build the email message
        msg = MIMEMultipart("alternative")
        msg["From"] = self.config.sender
        msg["To"] = self.config.recipient
        msg["Subject"] = subject

        # Attach plain text first, then HTML
        # Email clients prefer the last part, so HTML is shown by default
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            # Connect and send
            with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port) as server:
                server.starttls()  # Upgrade to encrypted connection
                server.login(self.config.sender, self.config.app_password)
                server.sendmail(
                    self.config.sender,
                    self.config.recipient,
                    msg.as_string(),
                )

            logger.info("Email sent successfully via SMTP")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error(
                "SMTP authentication failed. "
                "Make sure you're using a Gmail App Password, not your regular password. "
                "See docs/SETUP.md for instructions."
            )
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return False
