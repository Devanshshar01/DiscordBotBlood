# Configuration Template for Hybrid Discord Bot
# Copy this to config.py and customize your settings

import discord

class BotConfig:
    """Main bot configuration"""
    
    # Bot Token (REQUIRED - Get from Discord Developer Portal)
    BOT_TOKEN = ""
    
    # Bot Settings
    COMMAND_PREFIX = "!"
    CASE_INSENSITIVE = True
    
    # Bot Status
    BOT_STATUS = discord.Status.online
    BOT_ACTIVITY = discord.Activity(
        type=discord.ActivityType.watching,
        name="over your server | /help"
    )

class ModerationConfig:
    """Moderation system settings"""
    
    # Auto-moderation thresholds
    SPAM_THRESHOLD = 5  # messages in 5 seconds
    SPAM_TIMEOUT_DURATION = 5  # minutes
    
    MASS_MENTION_THRESHOLD = 5  # mentions per message
    MASS_MENTION_TIMEOUT = 10  # minutes
    
    # Auto-mod features
    ANTI_SPAM_ENABLED = True
    ANTI_INVITE_ENABLED = True
    ANTI_MASS_MENTION_ENABLED = True
    
    # Moderation embed colors
    BAN_COLOR = discord.Color.red()
    KICK_COLOR = discord.Color.orange()
    MUTE_COLOR = discord.Color.dark_gray()
    WARN_COLOR = discord.Color.yellow()
    SUCCESS_COLOR = discord.Color.green()
    
    # Default reasons
    DEFAULT_BAN_REASON = "No reason provided"
    DEFAULT_KICK_REASON = "No reason provided"
    DEFAULT_MUTE_REASON = "No reason provided"
    
    # Auto-punishments for warnings (optional)
    AUTO_PUNISHMENTS = {
        3: "kick",      # 3 warnings = kick
        5: "tempban",   # 5 warnings = temporary ban
        7: "ban"        # 7 warnings = permanent ban
    }
    AUTO_PUNISHMENT_ENABLED = False  # Set to True to enable

class TicketConfig:
    """Ticket system configuration"""
    
    # Ticket categories with emojis
    TICKET_CATEGORIES = [
        {
            "label": "General Support",
            "description": "Get help with general questions",
            "emoji": "❓",
            "value": "general"
        },
        {
            "label": "Technical Support", 
            "description": "Report bugs or technical issues",
            "emoji": "🔧",
            "value": "technical"
        },
        {
            "label": "Report User",
            "description": "Report rule violations or misconduct", 
            "emoji": "🚨",
            "value": "report"
        },
        {
            "label": "Partnership",
            "description": "Discuss partnerships and collaborations",
            "emoji": "🤝", 
            "value": "partnership"
        },
        {
            "label": "Other",
            "description": "Other inquiries not listed above",
            "emoji": "💬",
            "value": "other"
        }
    ]
    
    # Ticket embed settings
    TICKET_EMBED_COLOR = discord.Color.blue()
    TICKET_CREATION_COLOR = discord.Color.green()
    TICKET_CLOSE_COLOR = discord.Color.red()
    
    # Ticket channel settings
    MAX_TICKETS_PER_USER = 1
    AUTO_CLOSE_INACTIVE_TICKETS = False
    INACTIVE_TIMEOUT_HOURS = 48
    
    # Ticket transcripts
    GENERATE_TRANSCRIPTS = True
    TRANSCRIPT_CHANNEL_NAME = "ticket-transcripts"
    
    # Ticket panel message
    TICKET_PANEL_TITLE = "🎫 Support Tickets"
    TICKET_PANEL_DESCRIPTION = "Need help? Create a support ticket by selecting a category below!"
    TICKET_INSTRUCTIONS = """📋 How it works:
• Select a category from the dropdown menu below
• A private channel will be created for you  
• Our staff will assist you as soon as possible
• Close your ticket when you're done"""

class LoggingConfig:
    """Logging system settings"""
    
    # What to log
    LOG_MESSAGE_DELETES = True
    LOG_MESSAGE_EDITS = True
    LOG_MEMBER_JOINS = True
    LOG_MEMBER_LEAVES = True
    LOG_ROLE_CHANGES = True
    LOG_CHANNEL_CHANGES = True
    LOG_MODERATION_ACTIONS = True
    
    # Log embed colors
    DELETE_LOG_COLOR = discord.Color.red()
    EDIT_LOG_COLOR = discord.Color.orange()
    JOIN_LOG_COLOR = discord.Color.green()
    LEAVE_LOG_COLOR = discord.Color.red()
    MOD_LOG_COLOR = discord.Color.blue()
    
    # Log retention (days)
    LOG_RETENTION_DAYS = 90

class DatabaseConfig:
    """Database configuration"""
    
    # SQLite database file
    DATABASE_NAME = "hybrid_bot.db"
    
    # Backup settings
    AUTO_BACKUP = True
    BACKUP_INTERVAL_HOURS = 24
    MAX_BACKUPS = 7

class EmbedConfig:
    """Embed styling configuration"""
    
    # Default colors
    PRIMARY_COLOR = discord.Color.blue()
    SUCCESS_COLOR = discord.Color.green()
    WARNING_COLOR = discord.Color.yellow()
    ERROR_COLOR = discord.Color.red()
    INFO_COLOR = discord.Color.light_gray()
    
    # Footer settings
    DEFAULT_FOOTER = "Made with ❤️ for your Discord server"
    INCLUDE_TIMESTAMP = True
    
    # Thumbnail settings
    USE_USER_AVATARS = True
    USE_SERVER_ICONS = True

class PermissionConfig:
    """Permission requirements"""
    
    # Moderation permissions
    BAN_PERMISSION = "ban_members"
    KICK_PERMISSION = "kick_members"  
    MUTE_PERMISSION = "manage_roles"
    WARN_PERMISSION = "manage_messages"
    CLEAR_PERMISSION = "manage_messages"
    
    # Ticket permissions
    TICKET_SETUP_PERMISSION = "manage_guild"
    TICKET_CLAIM_PERMISSION = "manage_messages"
    TICKET_CLOSE_PERMISSION = "manage_channels"
    
    # Logging permissions
    SETUP_LOGS_PERMISSION = "manage_guild"

class CustomizationConfig:
    """Custom messages and responses"""
    
    # Success messages
    BAN_SUCCESS_MESSAGE = "🔨 {user} has been banned from the server."
    KICK_SUCCESS_MESSAGE = "👢 {user} has been kicked from the server."
    MUTE_SUCCESS_MESSAGE = "🔇 {user} has been muted."
    WARN_SUCCESS_MESSAGE = "⚠️ {user} has been warned."
    
    # Error messages
    NO_PERMISSION_MESSAGE = "❌ You don't have permission to use this command!"
    USER_NOT_FOUND_MESSAGE = "❌ User not found!"
    HIGHER_ROLE_MESSAGE = "❌ You can't moderate someone with a higher or equal role!"
    BOT_MISSING_PERMISSIONS = "❌ I don't have the required permissions!"
    
    # Ticket messages
    TICKET_CREATED_MESSAGE = "✅ Ticket created successfully! Please head to {channel}"
    TICKET_CLOSED_MESSAGE = "🔒 This ticket has been closed."
    TICKET_ALREADY_EXISTS = "❌ You already have an open ticket: {channel}"
    
    # DM messages for moderation actions
    SEND_DM_ON_BAN = True
    SEND_DM_ON_KICK = True  
    SEND_DM_ON_MUTE = True
    SEND_DM_ON_WARN = True
    
    BAN_DM_MESSAGE = "🚫 You have been banned from **{guild}**\n📝 Reason: {reason}\n🛡️ Moderator: {moderator}"
    KICK_DM_MESSAGE = "👢 You have been kicked from **{guild}**\n📝 Reason: {reason}\n🛡️ Moderator: {moderator}"
    MUTE_DM_MESSAGE = "🔇 You have been muted in **{guild}**\n📝 Reason: {reason}\n⏱️ Duration: {duration}\n🛡️ Moderator: {moderator}"
    WARN_DM_MESSAGE = "⚠️ You have received a warning in **{guild}**\n📝 Reason: {reason}\n📊 Total warnings: {count}\n🛡️ Moderator: {moderator}"

# Example usage in main bot file:
"""
from config import BotConfig, ModerationConfig, TicketConfig

# In your bot initialization:
bot = HybridBot(
    command_prefix=BotConfig.COMMAND_PREFIX,
    case_insensitive=BotConfig.CASE_INSENSITIVE
)

# Use in commands:
await ctx.send(embed=discord.Embed(
    title="Success",
    color=ModerationConfig.SUCCESS_COLOR
))
"""