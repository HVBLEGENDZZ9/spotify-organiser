"""AWS SES email service for notifications.

Handles:
- Subscription confirmation emails
- Expiry reminder emails (10-day, 5-day, same-day)
- Welcome emails after Spotify linking
"""

import logging
from typing import Optional
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from .config import get_settings

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via AWS SES."""
    
    def __init__(self):
        self.settings = get_settings()
        
        # Initialize SES client
        if self.settings.aws_access_key_id and self.settings.aws_secret_access_key:
            self.ses_client = boto3.client(
                'ses',
                region_name=self.settings.aws_region,
                aws_access_key_id=self.settings.aws_access_key_id,
                aws_secret_access_key=self.settings.aws_secret_access_key
            )
            logger.info("AWS SES client initialized")
        else:
            self.ses_client = None
            logger.warning("AWS SES credentials not configured")
    
    def _mask_email(self, email: str) -> str:
        """Mask email address for safe logging (e.g., j***@g***.com)."""
        if not email or '@' not in email:
            return '***@***'
        local, domain = email.split('@', 1)
        domain_parts = domain.rsplit('.', 1)
        masked_local = local[0] + '***' if local else '***'
        masked_domain = domain_parts[0][0] + '***' if domain_parts[0] else '***'
        tld = domain_parts[1] if len(domain_parts) > 1 else 'com'
        return f"{masked_local}@{masked_domain}.{tld}"
    
    def is_configured(self) -> bool:
        """Check if email service is properly configured."""
        return self.ses_client is not None and bool(self.settings.ses_from_email)
    
    def _get_from_address(self) -> str:
        """Get the formatted 'From' address."""
        if self.settings.ses_from_name:
            return f"{self.settings.ses_from_name} <{self.settings.ses_from_email}>"
        return self.settings.ses_from_email
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None
    ) -> bool:
        """
        Send an email via AWS SES.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML content of the email
            text_body: Plain text content (optional, derived from HTML if not provided)
            
        Returns:
            True if email was sent successfully
        """
        if not self.is_configured():
            logger.warning(f"Email service not configured, skipping email to {self._mask_email(to_email)}")
            return False
        
        try:
            message_body = {
                'Html': {
                    'Charset': 'UTF-8',
                    'Data': html_body
                }
            }
            
            if text_body:
                message_body['Text'] = {
                    'Charset': 'UTF-8',
                    'Data': text_body
                }
            
            response = self.ses_client.send_email(
                Source=self._get_from_address(),
                Destination={
                    'ToAddresses': [to_email]
                },
                Message={
                    'Subject': {
                        'Charset': 'UTF-8',
                        'Data': subject
                    },
                    'Body': message_body
                }
            )
            
            message_id = response.get('MessageId')
            logger.info(f"Email sent successfully (ID: {message_id[:8]}***)")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"Failed to send email: {error_code} - {error_message}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending email: {e}")
            return False
    
    # ============== Email Templates ==============
    
    async def send_subscription_confirmation(
        self,
        to_email: str,
        user_name: str,
        amount: int,
        end_date: datetime
    ) -> bool:
        """
        Send subscription confirmation email.
        
        Args:
            to_email: User's email
            user_name: User's display name
            amount: Amount paid in paise
            end_date: Subscription end date
        """
        amount_inr = amount / 100
        formatted_date = end_date.strftime("%B %d, %Y")
        
        subject = "🎉 Welcome to Spotify Organizer Pro!"
        
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0a0a0a; color: #ffffff; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
                .header {{ text-align: center; margin-bottom: 40px; }}
                .logo {{ font-size: 32px; font-weight: bold; background: linear-gradient(135deg, #1DB954, #1ed760); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
                .content {{ background: linear-gradient(135deg, rgba(29, 185, 84, 0.1), rgba(30, 215, 96, 0.05)); border: 1px solid rgba(29, 185, 84, 0.2); border-radius: 16px; padding: 32px; margin-bottom: 24px; }}
                h1 {{ color: #1DB954; margin-bottom: 16px; }}
                .highlight {{ color: #1ed760; font-weight: bold; }}
                .details {{ background: rgba(255, 255, 255, 0.05); border-radius: 12px; padding: 20px; margin: 24px 0; }}
                .detail-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.1); }}
                .detail-row:last-child {{ border-bottom: none; }}
                .footer {{ text-align: center; color: #888; font-size: 14px; margin-top: 40px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">🎵 Spotify Organizer</div>
                </div>
                
                <div class="content">
                    <h1>Welcome aboard, {user_name}! 🚀</h1>
                    <p>Your subscription is now active! Here's what happens next:</p>
                    
                    <ul>
                        <li>✅ Your liked songs will be organized automatically every 24 hours</li>
                        <li>✅ AI-powered genre classification keeps your playlists fresh</li>
                        <li>✅ Sit back and enjoy your perfectly organized music library</li>
                    </ul>
                    
                    <div class="details">
                        <div class="detail-row">
                            <span>Amount Paid</span>
                            <span class="highlight">₹{amount_inr:.0f}</span>
                        </div>
                        <div class="detail-row">
                            <span>Subscription Valid Until</span>
                            <span class="highlight">{formatted_date}</span>
                        </div>
                    </div>
                    
                    <p>We've already started organizing your library. Check your Spotify playlists soon!</p>
                </div>
                
                <div class="footer">
                    <p>Made with ❤️ for music lovers</p>
                    <p>Questions? Reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""
        Welcome to Spotify Organizer Pro, {user_name}!
        
        Your subscription is now active!
        
        What happens next:
        - Your liked songs will be organized automatically every 24 hours
        - AI-powered genre classification keeps your playlists fresh
        - Sit back and enjoy your perfectly organized music library
        
        Subscription Details:
        - Amount Paid: ₹{amount_inr:.0f}
        - Valid Until: {formatted_date}
        
        We've already started organizing your library. Check your Spotify playlists soon!
        
        Made with love for music lovers.
        """
        
        return await self.send_email(to_email, subject, html_body, text_body)
    
    async def send_expiry_reminder(
        self,
        to_email: str,
        user_name: str,
        days_remaining: int,
        end_date: datetime
    ) -> bool:
        """
        Send subscription expiry reminder email.
        
        Args:
            to_email: User's email
            user_name: User's display name
            days_remaining: Days until subscription expires
            end_date: Subscription end date
        """
        formatted_date = end_date.strftime("%B %d, %Y")
        
        if days_remaining == 0:
            subject = "⚠️ Your Spotify Organizer subscription expires TODAY"
            urgency_message = "Your subscription expires <strong>today</strong>."
            urgency_color = "#ff4444"
        elif days_remaining <= 5:
            subject = f"⏰ Only {days_remaining} days left on your Spotify Organizer subscription"
            urgency_message = f"Your subscription expires in <strong>{days_remaining} days</strong>."
            urgency_color = "#ff8c00"
        else:
            subject = f"📅 Your Spotify Organizer subscription expires in {days_remaining} days"
            urgency_message = f"Your subscription expires in <strong>{days_remaining} days</strong>."
            urgency_color = "#ffd700"
        
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0a0a0a; color: #ffffff; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
                .header {{ text-align: center; margin-bottom: 40px; }}
                .logo {{ font-size: 32px; font-weight: bold; background: linear-gradient(135deg, #1DB954, #1ed760); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
                .content {{ background: linear-gradient(135deg, rgba(29, 185, 84, 0.1), rgba(30, 215, 96, 0.05)); border: 1px solid rgba(29, 185, 84, 0.2); border-radius: 16px; padding: 32px; margin-bottom: 24px; }}
                .urgency {{ background: {urgency_color}22; border: 1px solid {urgency_color}; border-radius: 12px; padding: 20px; margin: 24px 0; text-align: center; }}
                .urgency strong {{ color: {urgency_color}; }}
                .cta-button {{ display: inline-block; background: linear-gradient(135deg, #1DB954, #1ed760); color: #000000; text-decoration: none; padding: 16px 32px; border-radius: 50px; font-weight: bold; margin: 20px 0; }}
                .footer {{ text-align: center; color: #888; font-size: 14px; margin-top: 40px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">🎵 Spotify Organizer</div>
                </div>
                
                <div class="content">
                    <h1>Hey {user_name}! 👋</h1>
                    
                    <div class="urgency">
                        <p>{urgency_message}</p>
                        <p>Expiry date: <strong>{formatted_date}</strong></p>
                    </div>
                    
                    <p>Don't let your music library fall into chaos! Renew now to keep your:</p>
                    
                    <ul>
                        <li>🎯 Automatic daily playlist organization</li>
                        <li>🤖 AI-powered genre classification</li>
                        <li>✨ Perfectly curated listening experience</li>
                    </ul>
                    
                    <center>
                        <a href="{self.settings.frontend_url}" class="cta-button">Renew Subscription</a>
                    </center>
                </div>
                
                <div class="footer">
                    <p>Made with ❤️ for music lovers</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""
        Hey {user_name}!
        
        {urgency_message.replace('<strong>', '').replace('</strong>', '')}
        Expiry date: {formatted_date}
        
        Don't let your music library fall into chaos! Renew now to keep your:
        - Automatic daily playlist organization
        - AI-powered genre classification  
        - Perfectly curated listening experience
        
        Renew at: {self.settings.frontend_url}
        
        Made with love for music lovers.
        """
        
        return await self.send_email(to_email, subject, html_body, text_body)
    
    async def send_welcome_email(
        self,
        to_email: str,
        user_name: str
    ) -> bool:
        """
        Send welcome email after user signs up (before payment).
        """
        subject = "👋 Welcome to Spotify Organizer!"
        
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0a0a0a; color: #ffffff; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
                .header {{ text-align: center; margin-bottom: 40px; }}
                .logo {{ font-size: 32px; font-weight: bold; background: linear-gradient(135deg, #1DB954, #1ed760); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
                .content {{ background: linear-gradient(135deg, rgba(29, 185, 84, 0.1), rgba(30, 215, 96, 0.05)); border: 1px solid rgba(29, 185, 84, 0.2); border-radius: 16px; padding: 32px; margin-bottom: 24px; }}
                .cta-button {{ display: inline-block; background: linear-gradient(135deg, #1DB954, #1ed760); color: #000000; text-decoration: none; padding: 16px 32px; border-radius: 50px; font-weight: bold; margin: 20px 0; }}
                .footer {{ text-align: center; color: #888; font-size: 14px; margin-top: 40px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">🎵 Spotify Organizer</div>
                </div>
                
                <div class="content">
                    <h1>Welcome, {user_name}! 🎉</h1>
                    
                    <p>Thanks for signing up! You're one step away from having the most organized Spotify library ever.</p>
                    
                    <p>Here's what Spotify Organizer does:</p>
                    
                    <ul>
                        <li>🎯 Automatically organizes your liked songs into genre playlists</li>
                        <li>🤖 Uses AI to classify songs by language, mood, and genre</li>
                        <li>⏰ Runs every 24 hours to keep your library fresh</li>
                        <li>🔒 Your data stays on Spotify - we never store your music</li>
                    </ul>
                    
                    <center>
                        <a href="{self.settings.frontend_url}" class="cta-button">Get Started</a>
                    </center>
                </div>
                
                <div class="footer">
                    <p>Made with ❤️ for music lovers</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return await self.send_email(to_email, subject, html_body)


def get_email_service() -> EmailService:
    """Get email service instance."""
    return EmailService()
