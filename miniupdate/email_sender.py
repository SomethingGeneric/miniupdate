"""
Email sender for miniupdate.

Sends update reports via SMTP email.
"""

import smtplib
import logging
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.policy import SMTP
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from .package_managers import PackageUpdate
from .inventory import Host
from .os_detector import OSInfo


logger = logging.getLogger(__name__)


class UpdateReport:
    """Contains update information for a single host."""

    def __init__(
        self,
        host: Host,
        os_info: Optional[OSInfo],
        updates: List[PackageUpdate],
        error: Optional[str] = None,
        command_output: Optional[str] = None,
    ):
        self.host = host
        self.os_info = os_info
        self.updates = updates
        self.error = error
        self.command_output = command_output  # Store stdout/stderr from failed commands
        self.timestamp = datetime.now()

    @property
    def has_updates(self) -> bool:
        """Check if host has available updates."""
        return len(self.updates) > 0

    @property
    def has_security_updates(self) -> bool:
        """Check if host has security updates."""
        return any(update.security for update in self.updates)

    @property
    def security_updates(self) -> List[PackageUpdate]:
        """Get only security updates."""
        return [update for update in self.updates if update.security]

    @property
    def regular_updates(self) -> List[PackageUpdate]:
        """Get only regular (non-security) updates."""
        return [update for update in self.updates if not update.security]


class EmailSender:
    """Handles sending email reports via SMTP."""

    def __init__(self, smtp_config: Dict[str, Any]):
        self.smtp_config = smtp_config

    def send_update_report(self, reports: List[UpdateReport]) -> bool:
        """
        Send update report email.

        Args:
            reports: List of UpdateReport objects

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            # Generate email content
            subject = self._generate_subject(reports)
            html_body = self._generate_html_body(reports)
            text_body = self._generate_text_body(reports)

            # Save HTML report to reports/ directory with datestamp
            self._save_html_report(html_body, "check")

            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.smtp_config["from_email"]

            # Handle multiple recipients
            to_emails = self.smtp_config["to_email"]
            if isinstance(to_emails, str):
                to_emails = [to_emails]
            msg["To"] = ", ".join(to_emails)

            # Attach text and HTML versions
            text_part = MIMEText(text_body, "plain", "utf-8")
            html_part = MIMEText(html_body, "html", "utf-8")
            msg.attach(text_part)
            msg.attach(html_part)

            # Send email
            return self._send_email(msg, to_emails)

        except Exception as e:
            logger.error(f"Failed to send update report: {e}")
            return False

    def _generate_subject(self, reports: List[UpdateReport]) -> str:
        """Generate email subject line."""
        total_hosts = len(reports)
        hosts_with_updates = sum(1 for report in reports if report.has_updates)
        hosts_with_security = sum(
            1 for report in reports if report.has_security_updates
        )

        if hosts_with_security > 0:
            return f"[SECURITY] System Updates Report: {hosts_with_security} hosts need security updates"
        elif hosts_with_updates > 0:
            return f"System Updates Report: {hosts_with_updates}/{total_hosts} hosts have updates available"
        else:
            return f"System Updates Report: All {total_hosts} hosts up to date"

    def _generate_html_body(self, reports: List[UpdateReport]) -> str:
        """Generate HTML email body."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background-color: #f0f0f0; padding: 15px; border-radius: 5px; }}
                .summary {{ margin: 20px 0; }}
                .host {{ margin: 15px 0; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }}
                .host-name {{ font-weight: bold; font-size: 1.1em; color: #333; }}
                .os-info {{ color: #666; font-size: 0.9em; }}
                .security {{ background-color: #ffe6e6; border-color: #ff9999; }}
                .no-updates {{ background-color: #e6ffe6; border-color: #99ff99; }}
                .error {{ background-color: #fff0e6; border-color: #ffcc99; }}
                .updates-list {{ margin: 10px 0; }}
                .update-item {{ margin: 5px 0; padding: 5px; background-color: #f9f9f9; }}
                .security-update {{ background-color: #ffeeee; font-weight: bold; }}
                table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>System Updates Report</h2>
                <p>Generated on: {timestamp}</p>
            </div>
        """

        # Summary
        html += self._generate_summary_html(reports)

        # Individual host reports
        html += "<h3>Individual Host Reports</h3>"

        for report in sorted(
            reports,
            key=lambda r: (not r.has_security_updates, not r.has_updates, r.host.name),
        ):
            html += self._generate_host_html(report)

        html += """
        </body>
        </html>
        """

        return html

    def _generate_summary_html(self, reports: List[UpdateReport]) -> str:
        """Generate summary section for HTML email."""
        total_hosts = len(reports)
        hosts_with_updates = [r for r in reports if r.has_updates]
        hosts_with_security = [r for r in reports if r.has_security_updates]
        hosts_with_errors = [r for r in reports if r.error]

        html = f"""
        <div class="summary">
            <h3>Summary</h3>
            <table>
                <tr><th>Metric</th><th>Count</th></tr>
                <tr><td>Total Hosts Checked</td><td>{total_hosts}</td></tr>
                <tr><td>Hosts with Updates</td><td>{len(hosts_with_updates)}</td></tr>
                <tr><td>Hosts with Security Updates</td><td style="{'background-color: #ffeeee;' if hosts_with_security else ''}">{len(hosts_with_security)}</td></tr>
                <tr><td>Hosts with Errors</td><td>{len(hosts_with_errors)}</td></tr>
            </table>
        """

        if hosts_with_security:
            html += "<h4 style='color: red;'>Hosts Requiring Security Updates:</h4><ul>"
            for report in hosts_with_security:
                security_count = len(report.security_updates)
                html += f"<li><strong>{report.host.name}</strong> - {security_count} security updates</li>"
            html += "</ul>"

        html += "</div>"
        return html

    def _generate_host_html(self, report: UpdateReport) -> str:
        """Generate HTML for a single host report."""
        css_class = "host"
        if report.error:
            css_class += " error"
        elif report.has_security_updates:
            css_class += " security"
        elif not report.has_updates:
            css_class += " no-updates"

        html = f'<div class="{css_class}">'
        html += (
            f'<div class="host-name">{report.host.name} ({report.host.hostname})</div>'
        )

        if report.os_info:
            html += f'<div class="os-info">{report.os_info}</div>'

        if report.error:
            html += f'<div style="color: red;">Error: {report.error}</div>'
            # Show command output if available (for failed package updates)
            if report.command_output:
                html += f'<div><strong>Command Output:</strong><pre style="white-space: pre-wrap; font-size: 12px; max-height: 300px; overflow-y: auto; background-color: #f8f8f8; padding: 8px; border-radius: 3px;">{report.command_output}</pre></div>'
        elif not report.has_updates:
            html += '<div style="color: green;">✓ No updates available</div>'
        else:
            if report.has_security_updates:
                html += f'<div><strong style="color: red;">Security Updates ({len(report.security_updates)}):</strong></div>'
                html += '<div class="updates-list">'
                for update in report.security_updates:
                    html += (
                        f'<div class="update-item security-update">🔒 {update}</div>'
                    )
                html += "</div>"

            if report.regular_updates:
                html += f"<div><strong>Regular Updates ({len(report.regular_updates)}):</strong></div>"
                html += '<div class="updates-list">'
                for update in report.regular_updates:
                    html += f'<div class="update-item">{update}</div>'
                html += "</div>"

        html += "</div>"
        return html

    def _generate_text_body(self, reports: List[UpdateReport]) -> str:
        """Generate plain text email body."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        text = f"""System Updates Report
Generated on: {timestamp}

"""

        # Summary
        total_hosts = len(reports)
        hosts_with_updates = [r for r in reports if r.has_updates]
        hosts_with_security = [r for r in reports if r.has_security_updates]
        hosts_with_errors = [r for r in reports if r.error]

        text += f"""SUMMARY:
Total Hosts Checked: {total_hosts}
Hosts with Updates: {len(hosts_with_updates)}
Hosts with Security Updates: {len(hosts_with_security)}
Hosts with Errors: {len(hosts_with_errors)}

"""

        if hosts_with_security:
            text += "HOSTS REQUIRING SECURITY UPDATES:\n"
            for report in hosts_with_security:
                security_count = len(report.security_updates)
                text += f"- {report.host.name}: {security_count} security updates\n"
            text += "\n"

        # Individual host reports
        text += "INDIVIDUAL HOST REPORTS:\n"
        text += "=" * 50 + "\n\n"

        for report in sorted(
            reports,
            key=lambda r: (not r.has_security_updates, not r.has_updates, r.host.name),
        ):
            text += f"Host: {report.host.name} ({report.host.hostname})\n"

            if report.os_info:
                text += f"OS: {report.os_info}\n"

            if report.error:
                text += f"ERROR: {report.error}\n"
                # Show command output if available (for failed package updates)
                if report.command_output:
                    text += f"Command Output:\n"
                    for line in report.command_output.split("\n"):
                        text += f"  {line}\n"
            elif not report.has_updates:
                text += "Status: No updates available\n"
            else:
                if report.has_security_updates:
                    text += f"SECURITY UPDATES ({len(report.security_updates)}):\n"
                    for update in report.security_updates:
                        text += f"  [SECURITY] {update}\n"

                if report.regular_updates:
                    text += f"Regular Updates ({len(report.regular_updates)}):\n"
                    for update in report.regular_updates:
                        text += f"  {update}\n"

            text += "\n" + "-" * 50 + "\n\n"

        return text

    def _save_html_report(self, html_body: str, report_type: str = "check") -> None:
        """Save HTML report to reports/ directory with datestamp."""
        try:
            # Create reports directory if it doesn't exist
            reports_dir = Path("reports")
            reports_dir.mkdir(exist_ok=True)

            # Generate filename with datestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{report_type}_report_{timestamp}.html"
            filepath = reports_dir / filename

            # Write HTML report to file
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_body)

            logger.info(f"HTML report saved to {filepath}")

        except Exception as e:
            logger.error(f"Failed to save HTML report: {e}")

    def _send_email(self, msg: MIMEMultipart, to_emails: List[str]) -> bool:
        """Send the email message via SMTP."""
        try:
            # Validate email configuration for strict SMTP servers like maddy
            from_email = self.smtp_config["from_email"]
            if not from_email or "@" not in from_email:
                logger.error(f"Invalid from_email format: {from_email}")
                logger.debug(
                    "from_email must be a valid email address for SMTP compliance"
                )
                return False

            logger.debug(
                f"Initiating SMTP connection to {self.smtp_config['smtp_server']}:{self.smtp_config['smtp_port']}"
            )
            logger.debug(f"TLS enabled: {self.smtp_config.get('use_tls', True)}")
            logger.debug(f"Recipients: {', '.join(to_emails)}")
            logger.debug(f"From: {from_email}")

            # Create SMTP connection
            if self.smtp_config.get("use_tls", True):
                logger.debug("Creating SMTP connection with TLS")
                server = smtplib.SMTP(
                    self.smtp_config["smtp_server"], self.smtp_config["smtp_port"]
                )
                # Explicitly call EHLO before starting TLS for better compatibility
                server.ehlo()
                logger.debug("Starting TLS encryption")
                server.starttls()
                # EHLO again after TLS as required by RFC
                server.ehlo()
            else:
                logger.debug("Creating SMTP connection without TLS")
                server = smtplib.SMTP(
                    self.smtp_config["smtp_server"], self.smtp_config["smtp_port"]
                )
                # Call EHLO for proper SMTP handshake
                server.ehlo()

            logger.debug("SMTP connection established")

            # Authenticate if credentials provided
            if "username" in self.smtp_config and "password" in self.smtp_config:
                logger.debug(f"Authenticating as user: {self.smtp_config['username']}")
                server.login(self.smtp_config["username"], self.smtp_config["password"])
                logger.debug("SMTP authentication successful")
            else:
                logger.debug("No SMTP authentication credentials provided")

            # Send email
            logger.debug("Sending email message...")
            # Use SMTP policy to ensure proper CRLF line endings for SMTP compliance
            # This is required by RFC 5321 and strict SMTP servers like maddy
            text = msg.as_string(policy=SMTP)
            logger.debug(f"Email message size: {len(text)} bytes")
            # Log first few lines of message for debugging (without sensitive content)
            first_lines = "\n".join(text.split("\n")[:5])
            logger.debug(f"Message headers: {repr(first_lines[:200])}")
            server.sendmail(self.smtp_config["from_email"], to_emails, text)
            server.quit()
            logger.debug("SMTP connection closed")

            logger.info(f"Update report sent to {', '.join(to_emails)}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP Authentication failed: {e}")
            logger.debug(
                f"Check username/password for {self.smtp_config.get('username', 'N/A')}"
            )
            return False
        except smtplib.SMTPConnectError as e:
            logger.error(f"Failed to connect to SMTP server: {e}")
            logger.debug(
                f"Server: {self.smtp_config['smtp_server']}:{self.smtp_config['smtp_port']}"
            )
            return False
        except smtplib.SMTPRecipientsRefused as e:
            logger.error(f"Recipients refused by SMTP server: {e}")
            logger.debug(f"Rejected recipients: {e.recipients}")
            return False
        except smtplib.SMTPDataError as e:
            logger.error(f"SMTP data error: {e}")
            logger.debug(f"This may indicate message format issues or server rejection")
            return False
        except smtplib.SMTPServerDisconnected as e:
            logger.error(f"SMTP server disconnected unexpectedly: {e}")
            logger.debug(
                f"This may indicate server-side connection issues or policy violations"
            )
            return False
        except ConnectionResetError as e:
            logger.error(f"Connection reset by SMTP server: {e}")
            logger.debug(
                f"Server may have rejected the connection due to policy violations"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to send email via SMTP: {e}")
            logger.debug(f"Error type: {type(e).__name__}")
            return False

    def send_automated_update_report(self, reports, unmapped_hosts=None) -> bool:
        """
        Send automated update report email.

        Args:
            reports: List of AutomatedUpdateReport objects
            unmapped_hosts: List of hosts not in VM mapping or opt-out list

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            # Import here to avoid circular imports
            from .update_automator import UpdateResult

            # Generate email content
            subject = self._generate_automated_subject(reports)
            html_body = self._generate_automated_html_body(reports, unmapped_hosts)
            text_body = self._generate_automated_text_body(reports, unmapped_hosts)

            # Save HTML report to reports/ directory with datestamp
            self._save_html_report(html_body, "automated_update")

            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.smtp_config["from_email"]

            # Handle multiple recipients
            to_emails = self.smtp_config["to_email"]
            if isinstance(to_emails, str):
                to_emails = [to_emails]
            msg["To"] = ", ".join(to_emails)

            # Attach text and HTML versions
            text_part = MIMEText(text_body, "plain", "utf-8")
            html_part = MIMEText(html_body, "html", "utf-8")
            msg.attach(text_part)
            msg.attach(html_part)

            # Send email
            return self._send_email(msg, to_emails)

        except Exception as e:
            logger.error(f"Failed to generate automated update email: {e}")
            return False

    def _generate_automated_subject(self, reports) -> str:
        """Generate email subject for automated updates."""
        from .update_automator import UpdateResult

        total = len(reports)
        successful = sum(1 for r in reports if r.result == UpdateResult.SUCCESS)
        no_updates = sum(1 for r in reports if r.result == UpdateResult.NO_UPDATES)
        opt_out = sum(1 for r in reports if r.result == UpdateResult.OPT_OUT)
        critical = sum(1 for r in reports if r.result == UpdateResult.REVERT_FAILED)
        reverted = sum(1 for r in reports if r.result == UpdateResult.REVERTED)
        failed = total - successful - no_updates - opt_out - critical - reverted

        if critical > 0:
            return f"🚨 URGENT: {critical} host(s) failed update+revert, {failed} other failures - miniupdate"
        elif failed > 0 or reverted > 0:
            return f"⚠️ Update Issues: {failed} failed, {reverted} reverted, {successful} success - miniupdate"
        elif successful > 0:
            if opt_out > 0:
                return f"✅ Updates Applied: {successful} updated, {opt_out} opt-out, {no_updates} up-to-date - miniupdate"
            else:
                return f"✅ Updates Applied: {successful} updated, {no_updates} up-to-date - miniupdate"
        elif opt_out > 0:
            return f"📋 Check Complete: {opt_out} opt-out (manual updates needed), {no_updates} up-to-date - miniupdate"
        else:
            return f"📋 No Updates Needed: {no_updates} hosts checked - miniupdate"

    def _generate_automated_html_body(self, reports, unmapped_hosts=None) -> str:
        """Generate HTML email body for automated updates."""
        from .update_automator import UpdateResult

        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
                .container { max-width: 800px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; margin: -20px -20px 20px -20px; border-radius: 8px 8px 0 0; }
                .summary { background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; border-left: 4px solid #007bff; }
                .host { margin: 15px 0; padding: 15px; border-radius: 5px; border-left: 4px solid #28a745; }
                .host.critical { border-left-color: #dc3545; background-color: #fff5f5; }
                .host.reverted { border-left-color: #ffc107; background-color: #fffbf0; }
                .host.failed { border-left-color: #fd7e14; background-color: #fff8f0; }
                .host.success { border-left-color: #28a745; background-color: #f8fff8; }
                .host.no-updates { border-left-color: #6c757d; background-color: #f8f9fa; }
                .host-name { font-weight: bold; font-size: 16px; margin-bottom: 5px; }
                .host-details { color: #666; font-size: 14px; margin-bottom: 10px; }
                .status { font-weight: bold; padding: 4px 8px; border-radius: 3px; display: inline-block; }
                .status.success { background-color: #d4edda; color: #155724; }
                .status.critical { background-color: #f8d7da; color: #721c24; }
                .status.reverted { background-color: #fff3cd; color: #856404; }
                .status.failed { background-color: #fdecea; color: #b52d3a; }
                .updates-list { margin-top: 10px; }
                .update-item { background-color: #e9ecef; padding: 5px 8px; margin: 2px 0; border-radius: 3px; }
                .security-update { background-color: #f8d7da; color: #721c24; font-weight: bold; }
                .error-details { background-color: #f8d7da; color: #721c24; padding: 8px; border-radius: 3px; margin-top: 5px; }
                .timing { color: #666; font-size: 12px; }
            </style>
        </head>
        <body>
            <div class="container">
        """

        html += self._generate_automated_header_html()
        html += self._generate_automated_summary_html(reports)

        # Show unmapped hosts warning first if there are any
        if unmapped_hosts:
            html += self._generate_unmapped_hosts_html(unmapped_hosts)

        # Group hosts by result type for better organization
        critical_hosts = [r for r in reports if r.result == UpdateResult.REVERT_FAILED]
        reverted_hosts = [r for r in reports if r.result == UpdateResult.REVERTED]
        failed_hosts = [
            r
            for r in reports
            if r.result
            in [
                UpdateResult.FAILED_UPDATES,
                UpdateResult.FAILED_REBOOT,
                UpdateResult.FAILED_AVAILABILITY,
                UpdateResult.FAILED_SNAPSHOT,
            ]
        ]
        successful_hosts = [r for r in reports if r.result == UpdateResult.SUCCESS]
        opt_out_hosts = [r for r in reports if r.result == UpdateResult.OPT_OUT]
        no_update_hosts = [r for r in reports if r.result == UpdateResult.NO_UPDATES]

        # Show critical failures first
        if critical_hosts:
            html += (
                '<h2 style="color: #dc3545;">🚨 CRITICAL FAILURES (Revert Failed)</h2>'
            )
            for report in critical_hosts:
                html += self._generate_automated_host_html(report)

        # Then reverted hosts
        if reverted_hosts:
            html += '<h2 style="color: #ffc107;">⚠️ Reverted Hosts</h2>'
            for report in reverted_hosts:
                html += self._generate_automated_host_html(report)

        # Then other failures
        if failed_hosts:
            html += '<h2 style="color: #fd7e14;">❌ Failed Updates</h2>'
            for report in failed_hosts:
                html += self._generate_automated_host_html(report)

        # Then opt-out hosts (check-only)
        if opt_out_hosts:
            html += '<h2 style="color: #ff9800;">⚠️ Opt-out Hosts (Check Only)</h2>'
            for report in opt_out_hosts:
                html += self._generate_automated_host_html(report)

        # Finally successful hosts and no-update hosts
        if successful_hosts:
            html += '<h2 style="color: #28a745;">✅ Successfully Updated</h2>'
            for report in successful_hosts:
                html += self._generate_automated_host_html(report)

        if no_update_hosts:
            html += '<h2 style="color: #6c757d;">📋 No Updates Needed</h2>'
            for report in no_update_hosts:
                html += self._generate_automated_host_html(report)

        html += """
            </div>
        </body>
        </html>
        """

        return html

    def _generate_automated_header_html(self) -> str:
        """Generate header HTML for automated updates."""
        return f"""
            <div class="header">
                <h1>🤖 Automated System Updates Report</h1>
                <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        """

    def _generate_automated_summary_html(self, reports) -> str:
        """Generate summary HTML for automated updates."""
        from .update_automator import UpdateResult

        total = len(reports)
        successful_updates = sum(1 for r in reports if r.result == UpdateResult.SUCCESS)
        no_updates_needed = sum(
            1 for r in reports if r.result == UpdateResult.NO_UPDATES
        )
        opt_out_hosts = sum(1 for r in reports if r.result == UpdateResult.OPT_OUT)
        critical_failures = sum(
            1 for r in reports if r.result == UpdateResult.REVERT_FAILED
        )
        reverted_hosts = sum(1 for r in reports if r.result == UpdateResult.REVERTED)
        other_failures = (
            total
            - successful_updates
            - no_updates_needed
            - opt_out_hosts
            - critical_failures
            - reverted_hosts
        )

        total_updates_applied = sum(
            len(r.update_report.updates)
            for r in reports
            if r.result == UpdateResult.SUCCESS
        )
        total_security_updates = sum(
            len(r.update_report.security_updates)
            for r in reports
            if r.result == UpdateResult.SUCCESS
        )

        html = f"""
        <div class="summary">
            <h2>📊 Summary</h2>
            <ul>
                <li><strong>Total hosts processed:</strong> {total}</li>
                <li><strong>✅ Successfully updated:</strong> {successful_updates}</li>
                <li><strong>📋 No updates needed:</strong> {no_updates_needed}</li>
                <li><strong>⚠️ Opt-out hosts (check-only):</strong> {opt_out_hosts}</li>
                <li><strong>🔄 Reverted to snapshot:</strong> {reverted_hosts}</li>
                <li><strong>❌ Other failures:</strong> {other_failures}</li>
        """

        if critical_failures > 0:
            html += f'<li><strong style="color: #dc3545;">🚨 CRITICAL: Revert failures:</strong> {critical_failures}</li>'

        if successful_updates > 0:
            html += f"""
                <li><strong>Total updates applied:</strong> {total_updates_applied}</li>
                <li><strong>Security updates applied:</strong> {total_security_updates}</li>
            """

        html += """
            </ul>
        </div>
        """

        return html

    def _generate_unmapped_hosts_html(self, unmapped_hosts) -> str:
        """Generate HTML error block for unmapped inventory hosts."""
        html = """
        <div class="summary" style="background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <h2 style="color: #721c24;">🚨 Configuration Warning: Unmapped Inventory Hosts</h2>
            <p><strong>The following hosts are not configured in either the VM mapping file or the opt-out list:</strong></p>
            <ul>
        """

        for host in unmapped_hosts:
            html += f"<li><strong>{host.name}</strong> ({host.hostname})</li>"

        html += """
            </ul>
            <p><strong>Action Required:</strong></p>
            <ul>
                <li>Add these hosts to your <code>vm_mapping.toml</code> file if they should receive automated updates, OR</li>
                <li>Add them to the <code>opt_out_hosts</code> list in <code>config.toml</code> if they should only be checked (no automated updates)</li>
            </ul>
            <p><em>Without proper configuration, these hosts may not behave as expected during automated updates.</em></p>
        </div>
        """

        return html

    def _generate_automated_host_html(self, report) -> str:
        """Generate HTML for a single automated update report."""
        from .update_automator import UpdateResult

        # Determine CSS class and status
        if report.result == UpdateResult.REVERT_FAILED:
            css_class = "host critical"
            status_class = "status critical"
            status_text = "CRITICAL: Revert Failed"
        elif report.result == UpdateResult.REVERTED:
            css_class = "host reverted"
            status_class = "status reverted"
            status_text = "Reverted to Snapshot"
        elif report.result in [
            UpdateResult.FAILED_UPDATES,
            UpdateResult.FAILED_REBOOT,
            UpdateResult.FAILED_AVAILABILITY,
            UpdateResult.FAILED_SNAPSHOT,
        ]:
            css_class = "host failed"
            status_class = "status failed"
            status_text = f"Failed: {report.result.value.replace('_', ' ').title()}"
        elif report.result == UpdateResult.SUCCESS:
            css_class = "host success"
            status_class = "status success"
            status_text = "Successfully Updated"
        elif report.result == UpdateResult.OPT_OUT:
            css_class = "host opt-out"
            status_class = "status warning"
            status_text = "Opt-out (Check Only)"
        elif report.result == UpdateResult.NO_UPDATES:
            css_class = "host no-updates"
            status_class = "status success"
            status_text = "No Updates Needed"
        else:
            css_class = "host unknown"
            status_class = "status warning"
            status_text = f"Unknown: {report.result.value}"

        html = f'<div class="{css_class}">'
        html += (
            f'<div class="host-name">{report.host.name} ({report.host.hostname})</div>'
        )
        html += f'<div class="{status_class}">{status_text}</div>'

        # Add timing information
        if report.end_time:
            duration = (report.end_time - report.start_time).total_seconds()
            html += f'<div class="timing">Duration: {int(duration)}s</div>'

        # Add OS info if available
        if report.update_report.os_info:
            html += f'<div class="host-details">{report.update_report.os_info}</div>'

        # Add VM mapping info if available
        if report.vm_mapping:
            html += f'<div class="host-details">VM: {report.vm_mapping.vmid} on {report.vm_mapping.node}'
            if report.snapshot_name:
                html += f" (Snapshot: {report.snapshot_name})"
            html += "</div>"

        # Show updates if successful or opt-out
        if (
            report.result == UpdateResult.SUCCESS
            or report.result == UpdateResult.OPT_OUT
        ) and report.update_report.has_updates:
            security_updates = report.update_report.security_updates
            regular_updates = report.update_report.regular_updates

            # Add prefix for opt-out hosts to clarify these are available updates, not applied ones
            prefix = "Available " if report.result == UpdateResult.OPT_OUT else ""
            action = (
                "require manual application"
                if report.result == UpdateResult.OPT_OUT
                else "applied"
            )

            if security_updates:
                html += f"<div><strong>🔒 {prefix}Security Updates ({len(security_updates)}) - {action}:</strong></div>"
                html += '<div class="updates-list">'
                for update in security_updates:
                    html += f'<div class="update-item security-update">{update}</div>'
                html += "</div>"

            if regular_updates:
                html += f"<div><strong>{prefix}Regular Updates ({len(regular_updates)}) - {action}:</strong></div>"
                html += '<div class="updates-list">'
                for update in regular_updates:
                    html += f'<div class="update-item">{update}</div>'
                html += "</div>"

        # Show error details if there are any
        if report.error_details:
            html += f'<div class="error-details"><strong>Error:</strong> {report.error_details}</div>'
        elif report.update_report.error:
            html += f'<div class="error-details"><strong>Error:</strong> {report.update_report.error}</div>'

        # Show command output if available (for failed package updates)
        if report.update_report.command_output:
            html += f'<div class="error-details"><strong>Command Output:</strong><pre style="white-space: pre-wrap; font-size: 12px; max-height: 300px; overflow-y: auto;">{report.update_report.command_output}</pre></div>'

        html += "</div>"
        return html

    def _generate_automated_text_body(self, reports, unmapped_hosts=None) -> str:
        """Generate plain text email body for automated updates."""
        from .update_automator import UpdateResult

        text = "🤖 AUTOMATED SYSTEM UPDATES REPORT\n"
        text += "=" * 50 + "\n"
        text += f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        # Summary
        total = len(reports)
        successful_updates = sum(1 for r in reports if r.result == UpdateResult.SUCCESS)
        no_updates_needed = sum(
            1 for r in reports if r.result == UpdateResult.NO_UPDATES
        )
        opt_out_hosts = sum(1 for r in reports if r.result == UpdateResult.OPT_OUT)
        critical_failures = sum(
            1 for r in reports if r.result == UpdateResult.REVERT_FAILED
        )
        reverted_hosts = sum(1 for r in reports if r.result == UpdateResult.REVERTED)
        other_failures = (
            total
            - successful_updates
            - no_updates_needed
            - opt_out_hosts
            - critical_failures
            - reverted_hosts
        )

        text += "📊 SUMMARY\n"
        text += "-" * 20 + "\n"
        text += f"Total hosts processed: {total}\n"
        text += f"✅ Successfully updated: {successful_updates}\n"
        text += f"📋 No updates needed: {no_updates_needed}\n"
        text += f"⚠️ Opt-out hosts (check-only): {opt_out_hosts}\n"
        text += f"🔄 Reverted to snapshot: {reverted_hosts}\n"
        text += f"❌ Other failures: {other_failures}\n"

        if critical_failures > 0:
            text += f"🚨 CRITICAL: Revert failures: {critical_failures}\n"

        text += "\n"

        # Show unmapped hosts warning if there are any
        if unmapped_hosts:
            text += "🚨 CONFIGURATION WARNING: UNMAPPED INVENTORY HOSTS\n"
            text += "=" * 60 + "\n"
            text += "The following hosts are not configured in either the VM mapping\n"
            text += "file or the opt-out list:\n\n"
            for host in unmapped_hosts:
                text += f"  - {host.name} ({host.hostname})\n"
            text += "\nACTION REQUIRED:\n"
            text += "- Add these hosts to your vm_mapping.toml file if they should\n"
            text += "  receive automated updates, OR\n"
            text += "- Add them to the opt_out_hosts list in config.toml if they\n"
            text += "  should only be checked (no automated updates)\n"
            text += "\nWithout proper configuration, these hosts may not behave as\n"
            text += "expected during automated updates.\n"
            text += "\n"

        # Group and show hosts
        critical_hosts = [r for r in reports if r.result == UpdateResult.REVERT_FAILED]
        reverted_hosts = [r for r in reports if r.result == UpdateResult.REVERTED]
        failed_hosts = [
            r
            for r in reports
            if r.result
            in [
                UpdateResult.FAILED_UPDATES,
                UpdateResult.FAILED_REBOOT,
                UpdateResult.FAILED_AVAILABILITY,
                UpdateResult.FAILED_SNAPSHOT,
            ]
        ]
        successful_hosts = [r for r in reports if r.result == UpdateResult.SUCCESS]
        opt_out_hosts = [r for r in reports if r.result == UpdateResult.OPT_OUT]
        no_update_hosts = [r for r in reports if r.result == UpdateResult.NO_UPDATES]

        if critical_hosts:
            text += "🚨 CRITICAL FAILURES (Revert Failed)\n"
            text += "-" * 40 + "\n"
            for report in critical_hosts:
                text += self._generate_automated_host_text(report)
                text += "\n"

        if reverted_hosts:
            text += "⚠️ REVERTED HOSTS\n"
            text += "-" * 20 + "\n"
            for report in reverted_hosts:
                text += self._generate_automated_host_text(report)
                text += "\n"

        if failed_hosts:
            text += "❌ FAILED UPDATES\n"
            text += "-" * 20 + "\n"
            for report in failed_hosts:
                text += self._generate_automated_host_text(report)
                text += "\n"

        if successful_hosts:
            text += "✅ SUCCESSFULLY UPDATED\n"
            text += "-" * 25 + "\n"
            for report in successful_hosts:
                text += self._generate_automated_host_text(report)
                text += "\n"

        if opt_out_hosts:
            text += "⚠️ OPT-OUT HOSTS (CHECK ONLY)\n"
            text += "-" * 30 + "\n"
            for report in opt_out_hosts:
                text += self._generate_automated_host_text(report)
                text += "\n"

        if no_update_hosts:
            text += "📋 NO UPDATES NEEDED\n"
            text += "-" * 25 + "\n"
            for report in no_update_hosts:
                text += self._generate_automated_host_text(report)
                text += "\n"

        return text

    def _generate_automated_host_text(self, report) -> str:
        """Generate plain text for a single automated update report."""
        from .update_automator import UpdateResult

        text = f"{report.host.name} ({report.host.hostname})\n"

        # Status
        if report.result == UpdateResult.REVERT_FAILED:
            text += "  Status: 🚨 CRITICAL - Revert Failed\n"
        elif report.result == UpdateResult.REVERTED:
            text += "  Status: 🔄 Reverted to Snapshot\n"
        elif report.result in [
            UpdateResult.FAILED_UPDATES,
            UpdateResult.FAILED_REBOOT,
            UpdateResult.FAILED_AVAILABILITY,
            UpdateResult.FAILED_SNAPSHOT,
        ]:
            text += f"  Status: ❌ Failed - {report.result.value.replace('_', ' ').title()}\n"
        elif report.result == UpdateResult.SUCCESS:
            text += "  Status: ✅ Successfully Updated\n"
        elif report.result == UpdateResult.OPT_OUT:
            text += "  Status: ⚠️ Opt-out (Check Only)\n"
        elif report.result == UpdateResult.NO_UPDATES:
            text += "  Status: 📋 No Updates Needed\n"
        else:
            text += f"  Status: ❓ Unknown ({report.result.value})\n"

        # Timing
        if report.end_time:
            duration = (report.end_time - report.start_time).total_seconds()
            text += f"  Duration: {int(duration)}s\n"

        # OS info
        if report.update_report.os_info:
            text += f"  OS: {report.update_report.os_info}\n"

        # VM info
        if report.vm_mapping:
            text += f"  VM: {report.vm_mapping.vmid} on {report.vm_mapping.node}\n"
            if report.snapshot_name:
                text += f"  Snapshot: {report.snapshot_name}\n"

        # Updates
        if (
            report.result == UpdateResult.SUCCESS
            or report.result == UpdateResult.OPT_OUT
        ) and report.update_report.has_updates:
            security_updates = report.update_report.security_updates
            regular_updates = report.update_report.regular_updates

            # Add prefix for opt-out hosts to clarify these are available updates, not applied ones
            prefix = "Available " if report.result == UpdateResult.OPT_OUT else ""

            if security_updates:
                text += f"  🔒 {prefix}Security Updates ({len(security_updates)}):\n"
                for update in security_updates:
                    text += f"    - {update}\n"

            if regular_updates:
                text += f"  {prefix}Regular Updates ({len(regular_updates)}):\n"
                for update in regular_updates:
                    text += f"    - {update}\n"

            if report.result == UpdateResult.OPT_OUT:
                text += "  ⚠️ Note: Updates listed above require manual application\n"

        # Errors
        if report.error_details:
            text += f"  Error: {report.error_details}\n"
        elif report.update_report.error:
            text += f"  Error: {report.update_report.error}\n"

        # Command output if available (for failed package updates)
        if report.update_report.command_output:
            text += f"  Command Output:\n"
            # Indent the command output for better readability
            for line in report.update_report.command_output.split("\n"):
                text += f"    {line}\n"

        return text
