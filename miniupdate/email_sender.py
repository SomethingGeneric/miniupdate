"""
Email sender for miniupdate.

Sends update reports via SMTP email.
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from typing import List, Dict, Any, Optional
from .package_managers import PackageUpdate
from .inventory import Host
from .os_detector import OSInfo


logger = logging.getLogger(__name__)


class UpdateReport:
    """Contains update information for a single host."""
    
    def __init__(self, host: Host, os_info: Optional[OSInfo], 
                 updates: List[PackageUpdate], error: Optional[str] = None):
        self.host = host
        self.os_info = os_info
        self.updates = updates
        self.error = error
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
            
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.smtp_config['from_email']
            
            # Handle multiple recipients
            to_emails = self.smtp_config['to_email']
            if isinstance(to_emails, str):
                to_emails = [to_emails]
            msg['To'] = ', '.join(to_emails)
            
            # Attach text and HTML versions
            text_part = MIMEText(text_body, 'plain', 'utf-8')
            html_part = MIMEText(html_body, 'html', 'utf-8')
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
        hosts_with_security = sum(1 for report in reports if report.has_security_updates)
        
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
        
        for report in sorted(reports, key=lambda r: (not r.has_security_updates, not r.has_updates, r.host.name)):
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
        html += f'<div class="host-name">{report.host.name} ({report.host.hostname})</div>'
        
        if report.os_info:
            html += f'<div class="os-info">{report.os_info}</div>'
        
        if report.error:
            html += f'<div style="color: red;">Error: {report.error}</div>'
        elif not report.has_updates:
            html += '<div style="color: green;">✓ No updates available</div>'
        else:
            if report.has_security_updates:
                html += f'<div><strong style="color: red;">Security Updates ({len(report.security_updates)}):</strong></div>'
                html += '<div class="updates-list">'
                for update in report.security_updates:
                    html += f'<div class="update-item security-update">🔒 {update}</div>'
                html += '</div>'
            
            if report.regular_updates:
                html += f'<div><strong>Regular Updates ({len(report.regular_updates)}):</strong></div>'
                html += '<div class="updates-list">'
                for update in report.regular_updates:
                    html += f'<div class="update-item">{update}</div>'
                html += '</div>'
        
        html += '</div>'
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
        
        for report in sorted(reports, key=lambda r: (not r.has_security_updates, not r.has_updates, r.host.name)):
            text += f"Host: {report.host.name} ({report.host.hostname})\n"
            
            if report.os_info:
                text += f"OS: {report.os_info}\n"
            
            if report.error:
                text += f"ERROR: {report.error}\n"
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
    
    def _send_email(self, msg: MIMEMultipart, to_emails: List[str]) -> bool:
        """Send the email message via SMTP."""
        try:
            # Create SMTP connection
            if self.smtp_config.get('use_tls', True):
                server = smtplib.SMTP(self.smtp_config['smtp_server'], 
                                    self.smtp_config['smtp_port'])
                server.starttls()
            else:
                server = smtplib.SMTP(self.smtp_config['smtp_server'], 
                                    self.smtp_config['smtp_port'])
            
            # Authenticate if credentials provided
            if 'username' in self.smtp_config and 'password' in self.smtp_config:
                server.login(self.smtp_config['username'], 
                           self.smtp_config['password'])
            
            # Send email
            text = msg.as_string()
            server.sendmail(self.smtp_config['from_email'], to_emails, text)
            server.quit()
            
            logger.info(f"Update report sent to {', '.join(to_emails)}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email via SMTP: {e}")
            return False