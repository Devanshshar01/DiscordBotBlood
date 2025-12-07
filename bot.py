import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio
import datetime
import sqlite3
from typing import Optional, Union
import logging
from enum import Enum
import re
import os
import secrets
from collections import defaultdict
import traceback

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

# Try to load configuration values
try:
    from config import BotConfig, DatabaseConfig
except Exception:
    # Fallbacks if config is missing or misconfigured
    class BotConfig:  # type: ignore
        BOT_TOKEN = os.getenv("DISCORD_TOKEN", "")
        COMMAND_PREFIX = "!"
        CASE_INSENSITIVE = True
        BOT_STATUS = discord.Status.online
        BOT_ACTIVITY = discord.Activity(
            type=discord.ActivityType.watching,
            name="over your server | /help",
        )

    class DatabaseConfig:  # type: ignore
        DATABASE_NAME = "hybrid_bot.db"

# Set up logging
logging.basicConfig(level=logging.INFO)

class TicketCategory(Enum):
    GENERAL_SUPPORT = "General Support"
    TECHNICAL_SUPPORT = "Technical Support"
    REPORT_USER = "Report User"
    PARTNERSHIP = "Partnership"
    OTHER = "Other"

class ModAction(Enum):
    WARN = "warn"
    MUTE = "mute"
    KICK = "kick"
    BAN = "ban"
    SOFTBAN = "softban"

class HybridBot(commands.Bot):
    def __init__(self):
        # Request only the intents we actually use; message_content is needed for auto-mod.
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        super().__init__(
            command_prefix=getattr(BotConfig, "COMMAND_PREFIX", "!"),
            intents=intents,
            help_command=None,
            case_insensitive=getattr(BotConfig, "CASE_INSENSITIVE", True),
        )

        # Use configured database name with proper thread safety
        db_name = getattr(DatabaseConfig, "DATABASE_NAME", "hybrid_bot.db")
        self.db_connection = sqlite3.connect(db_name, check_same_thread=False)
        self.db_lock = asyncio.Lock()  # Thread-safe database operations
        self.setup_database()

    async def close(self):
        # Ensure DB connection closes cleanly on shutdown
        try:
            self.db_connection.close()
        except Exception:
            pass
        await super().close()
        
    async def setup_hook(self):
        """Called when the bot is starting up"""
        # Register all cogs
        await self.add_cog(ModerationCog(self))
        await self.add_cog(ModerationCog2(self))
        await self.add_cog(TicketCog(self))
        await self.add_cog(LoggingCog(self))
        await self.add_cog(AutoModCog(self))
        await self.add_cog(UtilityCog(self))
        try:
            from music import MusicCog

            await self.add_cog(MusicCog(self))
        except Exception as e:
            logging.error(f"Failed to load MusicCog: {e}")

        # Add help command to the slash command tree
        self.tree.add_command(help_command)
        
        # Set up global error handler
        self.tree.on_error = self.on_app_command_error

        # Register persistent views (require stable custom_ids)
        self.add_view(TicketCreateView())
        self.add_view(TicketControlView())
        await self.tree.sync()
        print(f"Synced slash commands for {self.user}")
    
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Global error handler for slash commands"""
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏱️ This command is on cooldown. Try again in {error.retry_after:.1f}s",
                ephemeral=True
            )
        elif isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command!",
                ephemeral=True
            )
        elif isinstance(error, app_commands.BotMissingPermissions):
            await interaction.response.send_message(
                "❌ I don't have the required permissions to execute this command!",
                ephemeral=True
            )
        else:
            logging.error(f"Command error: {error}")
            logging.error(traceback.format_exc())
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ An error occurred: {str(error)}",
                    ephemeral=True
                )

    def setup_database(self):
        """Set up the SQLite database"""
        cursor = self.db_connection.cursor()
        
        # Moderation logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mod_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                guild_id INTEGER NOT NULL,
                case_id INTEGER,
                active BOOLEAN DEFAULT 1
            )
        ''')
        
        # Warnings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                guild_id INTEGER NOT NULL
            )
        ''')
        
        # Tickets table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                channel_id INTEGER,
                category TEXT,
                status TEXT DEFAULT 'open',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                closed_at DATETIME,
                guild_id INTEGER NOT NULL,
                assigned_to INTEGER,
                priority TEXT DEFAULT 'medium'
            )
        ''')

        # Playlists tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playlist_songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER NOT NULL,
                song_title TEXT NOT NULL,
                song_url TEXT NOT NULL,
                duration INTEGER,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (playlist_id) REFERENCES playlists(id)
            )
        ''')

        # Radio tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS radio_channels (
                guild_id INTEGER PRIMARY KEY,
                voice_channel_id INTEGER NOT NULL,
                enabled BOOLEAN DEFAULT 1
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS radio_streams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                stream_url TEXT NOT NULL,
                stream_name TEXT NOT NULL
            )
        ''')
        
        # Guild settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                modlog_channel INTEGER,
                ticket_category INTEGER,
                ticket_log_channel INTEGER,
                mute_role INTEGER,
                auto_mod_enabled BOOLEAN DEFAULT 0,
                welcome_channel INTEGER,
                moderator_roles TEXT DEFAULT '[]'
            )
        ''')
        
        self.db_connection.commit()

    async def on_ready(self):
        print(f'{self.user} has landed! 🚀')
        print(f'Bot is in {len(self.guilds)} servers')
        
        # Set bot presence from config
        activity = getattr(BotConfig, "BOT_ACTIVITY", None)
        status = getattr(BotConfig, "BOT_STATUS", discord.Status.online)
        await self.change_presence(status=status, activity=activity)

class ModerationCog(commands.Cog):
    def __init__(self, bot: HybridBot):
        self.bot = bot
        
    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    @app_commands.describe(
        member="The member to ban",
        reason="Reason for the ban",
        delete_days="Days of messages to delete (0-7)"
    )
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = "No reason provided",
        delete_days: Optional[int] = 1
    ):
        # Check role hierarchy
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ You can't ban someone with a higher or equal role!", ephemeral=True)
            return
        
        if member == interaction.guild.owner:
            await interaction.response.send_message("❌ You can't ban the server owner!", ephemeral=True)
            return

        # Validate delete days
        if delete_days is not None:
            try:
                delete_days = int(delete_days)
            except Exception:
                await interaction.response.send_message("❌ Invalid delete days value!", ephemeral=True)
                return
            if delete_days < 0 or delete_days > 7:
                await interaction.response.send_message("❌ delete_days must be between 0 and 7.", ephemeral=True)
                return

        try:
            # Log the ban with async lock
            async with self.bot.db_lock:
                cursor = self.bot.db_connection.cursor()
                cursor.execute('''
                    INSERT INTO mod_logs (user_id, moderator_id, action, reason, guild_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (member.id, interaction.user.id, 'ban', reason, interaction.guild_id))
                case_id = cursor.lastrowid
                self.bot.db_connection.commit()
            
            # Create ban embed
            embed = discord.Embed(
                title="🔨 Member Banned",
                description=f"**{member}** has been banned from the server.",
                color=discord.Color.red(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="👤 User", value=f"{member} ({member.id})", inline=True)
            embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
            embed.add_field(name="📝 Reason", value=reason, inline=False)
            embed.add_field(name="🆔 Case ID", value=f"#{case_id}", inline=True)
            embed.set_thumbnail(url=member.display_avatar.url)
            
            # Try to DM the user before banning
            try:
                dm_embed = discord.Embed(
                    title="🚫 You have been banned",
                    description=f"You have been banned from **{interaction.guild.name}**",
                    color=discord.Color.red()
                )
                dm_embed.add_field(name="📝 Reason", value=reason, inline=False)
                dm_embed.add_field(name="🛡️ Moderator", value=str(interaction.user), inline=False)
                await member.send(embed=dm_embed)
            except:
                embed.add_field(name="📬 DM Status", value="❌ Could not send DM", inline=True)
            else:
                embed.add_field(name="📬 DM Status", value="✅ User notified", inline=True)
            
            # Ban the member (use correct API parameter)
            delete_seconds = (delete_days or 0) * 24 * 60 * 60
            await interaction.guild.ban(
                member,
                reason=f"[Case #{case_id}] {reason}",
                delete_message_seconds=delete_seconds,
            )
            
            await interaction.response.send_message(embed=embed)
            
            # Send to mod log
            await self.send_to_modlog(interaction.guild, embed)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to ban this member!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only()
    @app_commands.describe(
        member="The member to kick",
        reason="Reason for the kick"
    )
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = "No reason provided"
    ):
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ You can't kick someone with a higher or equal role!", ephemeral=True)
            return

        try:
            # Log the kick
            async with self.bot.db_lock:
                cursor = self.bot.db_connection.cursor()
                cursor.execute('''
                    INSERT INTO mod_logs (user_id, moderator_id, action, reason, guild_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (member.id, interaction.user.id, 'kick', reason, interaction.guild_id))
                case_id = cursor.lastrowid
                self.bot.db_connection.commit()
            
            # Create kick embed
            embed = discord.Embed(
                title="👢 Member Kicked",
                description=f"**{member}** has been kicked from the server.",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="👤 User", value=f"{member} ({member.id})", inline=True)
            embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
            embed.add_field(name="📝 Reason", value=reason, inline=False)
            embed.add_field(name="🆔 Case ID", value=f"#{case_id}", inline=True)
            embed.set_thumbnail(url=member.display_avatar.url)
            
            # Try to DM the user before kicking
            try:
                dm_embed = discord.Embed(
                    title="👢 You have been kicked",
                    description=f"You have been kicked from **{interaction.guild.name}**",
                    color=discord.Color.orange()
                )
                dm_embed.add_field(name="📝 Reason", value=reason, inline=False)
                dm_embed.add_field(name="🛡️ Moderator", value=str(interaction.user), inline=False)
                await member.send(embed=dm_embed)
            except:
                embed.add_field(name="📬 DM Status", value="❌ Could not send DM", inline=True)
            else:
                embed.add_field(name="📬 DM Status", value="✅ User notified", inline=True)
            
            # Kick the member
            await member.kick(reason=f"[Case #{case_id}] {reason}")
            
            await interaction.response.send_message(embed=embed)
            
            # Send to mod log
            await self.send_to_modlog(interaction.guild, embed)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to kick this member!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="mute", description="Mute a member in the server")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.describe(
        member="The member to mute",
        duration="Duration (e.g., 10m, 1h, 1d)",
        reason="Reason for the mute"
    )
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: Optional[str] = None,
        reason: Optional[str] = "No reason provided"
    ):

        # Parse duration
        mute_time = None
        if duration:
            mute_time = self.parse_duration(duration)
            if not mute_time:
                await interaction.response.send_message("❌ Invalid duration format! Use formats like: 10m, 1h, 1d", ephemeral=True)
                return

        # Role hierarchy safety checks
        if member == interaction.guild.owner:
            await interaction.response.send_message("❌ You can't mute the server owner!", ephemeral=True)
            return
        if member == interaction.user:
            await interaction.response.send_message("❌ You can't mute yourself!", ephemeral=True)
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ You can't mute someone with a higher or equal role!", ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("❌ I can't mute someone with a higher or equal role than mine!", ephemeral=True)
            return

        try:
            # Use Discord's timeout feature for temporary mutes
            if mute_time and mute_time <= datetime.timedelta(days=28):
                await member.timeout(mute_time, reason=reason)
                duration_text = f"for {duration}" if duration else "indefinitely"
            else:
                # Use role-based muting for longer durations
                mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
                if not mute_role:
                    # Create mute role if it doesn't exist
                    mute_role = await interaction.guild.create_role(
                        name="Muted",
                        color=discord.Color.dark_gray(),
                        reason="Auto-created mute role"
                    )
                    # Set permissions for mute role
                    for channel in interaction.guild.channels:
                        await channel.set_permissions(mute_role, send_messages=False, speak=False)
                
                await member.add_roles(mute_role, reason=reason)
                duration_text = f"for {duration}" if duration else "indefinitely"

            # Log the mute
            async with self.bot.db_lock:
                cursor = self.bot.db_connection.cursor()
                cursor.execute('''
                    INSERT INTO mod_logs (user_id, moderator_id, action, reason, guild_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (member.id, interaction.user.id, 'mute', reason, interaction.guild_id))
                case_id = cursor.lastrowid
                self.bot.db_connection.commit()

            # Create mute embed
            embed = discord.Embed(
                title="🔇 Member Muted",
                description=f"**{member}** has been muted {duration_text}.",
                color=discord.Color.dark_gray(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="👤 User", value=f"{member} ({member.id})", inline=True)
            embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
            embed.add_field(name="⏱️ Duration", value=duration or "Indefinite", inline=True)
            embed.add_field(name="📝 Reason", value=reason, inline=False)
            embed.add_field(name="🆔 Case ID", value=f"#{case_id}", inline=True)
            embed.set_thumbnail(url=member.display_avatar.url)

            await interaction.response.send_message(embed=embed)
            
            # Send to mod log
            await self.send_to_modlog(interaction.guild, embed)

        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to mute this member!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="warn", description="Warn a member")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.describe(
        member="The member to warn",
        reason="Reason for the warning"
    )
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str
    ):
        # Role hierarchy safety checks
        if member == interaction.guild.owner:
            await interaction.response.send_message("❌ You can't warn the server owner!", ephemeral=True)
            return
        if member == interaction.user:
            await interaction.response.send_message("❌ You can't warn yourself!", ephemeral=True)
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ You can't warn someone with a higher or equal role!", ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("❌ I can't warn someone with a higher or equal role than mine!", ephemeral=True)
            return

        try:
            # Add warning to database
            async with self.bot.db_lock:
                cursor = self.bot.db_connection.cursor()
                cursor.execute('''
                    INSERT INTO warnings (user_id, moderator_id, reason, guild_id)
                    VALUES (?, ?, ?, ?)
                ''', (member.id, interaction.user.id, reason, interaction.guild_id))
                
                # Get warning count
                cursor.execute('''
                    SELECT COUNT(*) FROM warnings WHERE user_id = ? AND guild_id = ?
                ''', (member.id, interaction.guild_id))
                warning_count = cursor.fetchone()[0]
                
                self.bot.db_connection.commit()

            # Create warning embed
            embed = discord.Embed(
                title="⚠️ Member Warned",
                description=f"**{member}** has received a warning.",
                color=discord.Color.yellow(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="👤 User", value=f"{member} ({member.id})", inline=True)
            embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
            embed.add_field(name="📊 Total Warnings", value=f"{warning_count}", inline=True)
            embed.add_field(name="📝 Reason", value=reason, inline=False)
            embed.set_thumbnail(url=member.display_avatar.url)

            # Try to DM the user
            try:
                dm_embed = discord.Embed(
                    title="⚠️ Warning Received",
                    description=f"You have received a warning in **{interaction.guild.name}**",
                    color=discord.Color.yellow()
                )
                dm_embed.add_field(name="📝 Reason", value=reason, inline=False)
                dm_embed.add_field(name="🛡️ Moderator", value=str(interaction.user), inline=False)
                dm_embed.add_field(name="📊 Total Warnings", value=f"{warning_count}", inline=False)
                await member.send(embed=dm_embed)
            except:
                embed.add_field(name="📬 DM Status", value="❌ Could not send DM", inline=True)
            else:
                embed.add_field(name="📬 DM Status", value="✅ User notified", inline=True)

            await interaction.response.send_message(embed=embed)
            
            # Send to mod log
            await self.send_to_modlog(interaction.guild, embed)

        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="modlogs", description="View moderation logs for a user")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.describe(member="The member to check logs for")
    async def modlogs(self, interaction: discord.Interaction, member: discord.Member):
        async with self.bot.db_lock:
            cursor = self.bot.db_connection.cursor()
            cursor.execute('''
                SELECT action, reason, timestamp, moderator_id, id
                FROM mod_logs 
                WHERE user_id = ? AND guild_id = ? 
                ORDER BY timestamp DESC 
                LIMIT 10
            ''', (member.id, interaction.guild_id))
        
        logs = cursor.fetchall()
        
        if not logs:
            embed = discord.Embed(
                title="📋 Moderation Logs",
                description=f"No moderation logs found for {member.mention}",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="📋 Moderation Logs",
                description=f"Recent moderation actions for {member.mention}",
                color=discord.Color.blue()
            )
            
            for i, (action, reason, timestamp, moderator_id, case_id) in enumerate(logs[:5], 1):
                moderator = interaction.guild.get_member(moderator_id)
                mod_name = moderator.display_name if moderator else f"Unknown ({moderator_id})"
                
                embed.add_field(
                    name=f"#{case_id} • {action.upper()}",
                    value=f"**Moderator:** {mod_name}\n**Reason:** {reason or 'No reason'}\n**Date:** {timestamp}",
                    inline=False
                )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    def parse_duration(self, duration_str: str) -> Optional[datetime.timedelta]:
        """Parse duration string into timedelta object"""
        pattern = r'(\d+)([smhd])'
        match = re.match(pattern, duration_str.lower())
        
        if not match:
            return None
            
        amount, unit = match.groups()
        amount = int(amount)
        
        if unit == 's':
            return datetime.timedelta(seconds=amount)
        elif unit == 'm':
            return datetime.timedelta(minutes=amount)
        elif unit == 'h':
            return datetime.timedelta(hours=amount)
        elif unit == 'd':
            return datetime.timedelta(days=amount)
        
        return None

    async def send_to_modlog(self, guild: discord.Guild, embed: discord.Embed):
        """Send moderation action to mod log channel"""
        cursor = self.bot.db_connection.cursor()
        cursor.execute('SELECT modlog_channel FROM guild_settings WHERE guild_id = ?', (guild.id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            channel = guild.get_channel(result[0])
            if channel:
                try:
                    await channel.send(embed=embed)
                except:
                    pass

# Additional moderation commands
class ModerationCog2(commands.Cog):
    def __init__(self, bot: HybridBot):
        self.bot = bot

    @app_commands.command(name="clear", description="Clear messages in a channel")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    async def clear(self, interaction: discord.Interaction, amount: int):
        
        if amount < 1 or amount > 100:
            await interaction.response.send_message("❌ Please specify a number between 1 and 100!", ephemeral=True)
            return

        try:
            deleted = await interaction.channel.purge(limit=amount)
            
            embed = discord.Embed(
                title="🧹 Messages Cleared",
                description=f"Successfully deleted {len(deleted)} messages.",
                color=discord.Color.green(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
            embed.add_field(name="📍 Channel", value=interaction.channel.mention, inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to delete messages!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="unban", description="Unban a user from the server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    @app_commands.describe(user_id="The ID of the user to unban")
    async def unban(self, interaction: discord.Interaction, user_id: str):

        try:
            user_id = int(user_id)
            user = await self.bot.fetch_user(user_id)
            
            await interaction.guild.unban(user, reason=f"Unbanned by {interaction.user}")
            
            embed = discord.Embed(
                title="✅ User Unbanned",
                description=f"**{user}** has been unbanned from the server.",
                color=discord.Color.green(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="👤 User", value=f"{user} ({user.id})", inline=True)
            embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
            embed.set_thumbnail(url=user.display_avatar.url)
            
            await interaction.response.send_message(embed=embed)
            
        except discord.NotFound:
            await interaction.response.send_message("❌ User not found or not banned!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please provide a valid user ID!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="unmute", description="Unmute a member in the server")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.describe(member="The member to unmute")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        # Role hierarchy safety checks
        if member == interaction.guild.owner:
            await interaction.response.send_message("❌ You can't unmute the server owner!", ephemeral=True)
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ You can't unmute someone with a higher or equal role!", ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("❌ I can't unmute someone with a higher or equal role than mine!", ephemeral=True)
            return

        try:
            # Try removing Discord timeout first
            if member.is_timed_out():
                await member.timeout(None, reason=f"Unmuted by {interaction.user}")
            
            # Also try removing Muted role if it exists
            mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
            if mute_role and mute_role in member.roles:
                await member.remove_roles(mute_role, reason=f"Unmuted by {interaction.user}")
            
            embed = discord.Embed(
                title="🔊 Member Unmuted",
                description=f"**{member}** has been unmuted.",
                color=discord.Color.green(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="👤 User", value=f"{member} ({member.id})", inline=True)
            embed.add_field(name="🛡️ Moderator", value=interaction.user.mention, inline=True)
            embed.set_thumbnail(url=member.display_avatar.url)
            
            await interaction.response.send_message(embed=embed)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to unmute this member!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

class TicketCog(commands.Cog):
    def __init__(self, bot: HybridBot):
        self.bot = bot

    @app_commands.command(name="ticket-setup", description="Set up the ticket system")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(
        channel="Channel to send the ticket panel to",
        category="Category to create tickets in"
    )
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        category: discord.CategoryChannel
    ):
        # Update guild settings
        async with self.bot.db_lock:
            cursor = self.bot.db_connection.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO guild_settings (guild_id, ticket_category)
                VALUES (?, ?)
            ''', (interaction.guild_id, category.id))
            self.bot.db_connection.commit()

        # Create ticket panel
        embed = discord.Embed(
            title="🎫 Support Desk",
            description="Tap a category to open a private ticket with staff.",
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="How it works",
            value="• Pick a category below\n• We create a private channel for you\n• Staff joins and helps\n• Close it when you’re done",
            inline=False
        )
        embed.add_field(
            name="Response goals",
            value="Fast for urgent issues, within a few minutes for the rest.",
            inline=False
        )
        embed.add_field(
            name="Tips",
            value="Include screenshots, links, and steps to reproduce if applicable.",
            inline=False
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.set_footer(text="We’re here to help — choose a category below.")

        view = TicketCreateView()
        
        try:
            await channel.send(embed=embed, view=view)
            await interaction.response.send_message(f"✅ Ticket system set up in {channel.mention}!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to set up ticket system: {str(e)}", ephemeral=True)

    @app_commands.command(name="ticket-stats", description="View ticket statistics")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def ticket_stats(self, interaction: discord.Interaction):
        async with self.bot.db_lock:
            cursor = self.bot.db_connection.cursor()
            
            # Get total tickets
            cursor.execute('SELECT COUNT(*) FROM tickets WHERE guild_id = ?', (interaction.guild_id,))
            total_tickets = cursor.fetchone()[0]
            
            # Get open tickets
            cursor.execute('SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = "open"', (interaction.guild_id,))
            open_tickets = cursor.fetchone()[0]
            
            # Get closed tickets
            cursor.execute('SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = "closed"', (interaction.guild_id,))
            closed_tickets = cursor.fetchone()[0]
            
            # Get tickets by category
            cursor.execute('''
                SELECT category, COUNT(*) FROM tickets 
                WHERE guild_id = ? 
                GROUP BY category
            ''', (interaction.guild_id,))
            category_stats = cursor.fetchall()

        embed = discord.Embed(
            title="📊 Ticket Dashboard",
            description="Snapshot of current support load.",
            color=discord.Color.teal(),
            timestamp=datetime.datetime.utcnow()
        )
        
        embed.add_field(name="Total", value=total_tickets, inline=True)
        embed.add_field(name="Open", value=open_tickets, inline=True)
        embed.add_field(name="Closed", value=closed_tickets, inline=True)

        if total_tickets:
            pct_open = round((open_tickets / total_tickets) * 100, 1)
            pct_closed = round((closed_tickets / total_tickets) * 100, 1)
            embed.add_field(
                name="Status mix",
                value=f"🟢 {pct_open}% open\n🔴 {pct_closed}% closed",
                inline=True
            )
        
        if category_stats:
            categories_text = "\n".join([f"• {cat}: {count}" for cat, count in category_stats])
            embed.add_field(name="By category", value=categories_text, inline=False)
        else:
            embed.add_field(name="By category", value="No tickets yet.", inline=False)
        
        await interaction.response.send_message(embed=embed)

class TicketCreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="Select a ticket category...",
        min_values=1,
        max_values=1,
        custom_id="ticket_create_select",
        options=[
            discord.SelectOption(
                label="General Support",
                description="Get help with general questions",
                emoji="❓",
                value="general"
            ),
            discord.SelectOption(
                label="Technical Support",
                description="Report bugs or technical issues",
                emoji="🔧",
                value="technical"
            ),
            discord.SelectOption(
                label="Report User",
                description="Report rule violations or misconduct",
                emoji="🚨",
                value="report"
            ),
            discord.SelectOption(
                label="Partnership",
                description="Discuss partnerships and collaborations",
                emoji="🤝",
                value="partnership"
            ),
            discord.SelectOption(
                label="Other",
                description="Other inquiries not listed above",
                emoji="💬",
                value="other"
            )
        ]
    )
    async def select_category(self, interaction: discord.Interaction, select: discord.ui.Select):
        await self.create_ticket(interaction, select.values[0])

    async def create_ticket(self, interaction: discord.Interaction, category: str):
        # Check if user already has an open ticket
        bot = interaction.client
        async with bot.db_lock:
            cursor = bot.db_connection.cursor()
            cursor.execute('''
                SELECT channel_id FROM tickets 
                WHERE user_id = ? AND guild_id = ? AND status = 'open'
            ''', (interaction.user.id, interaction.guild_id))
            existing_ticket = cursor.fetchone()
        if existing_ticket:
            channel = interaction.guild.get_channel(existing_ticket[0])
            if channel:
                await interaction.response.send_message(
                    f"❌ You already have an open ticket: {channel.mention}",
                    ephemeral=True
                )
                return

        # Get ticket category from database
        async with bot.db_lock:
            cursor = bot.db_connection.cursor()
            cursor.execute('SELECT ticket_category FROM guild_settings WHERE guild_id = ?', (interaction.guild_id,))
            result = cursor.fetchone()
        
        if not result or not result[0]:
            await interaction.response.send_message(
                "❌ Ticket system not configured! Please ask an admin to run `/ticket-setup`",
                ephemeral=True
            )
            return

        ticket_category_channel = interaction.guild.get_channel(result[0])
        if not ticket_category_channel:
            await interaction.response.send_message(
                "❌ Ticket category not found! Please ask an admin to reconfigure the ticket system.",
                ephemeral=True
            )
            return

        # Generate ticket ID
        ticket_id = f"ticket-{secrets.token_hex(4)}"
        
        # Create ticket channel
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True
            )
        }

        # Allow staff (any role with manage_messages) to view tickets
        staff_roles = [role for role in interaction.guild.roles if role.permissions.manage_messages]
        for role in staff_roles:
            overwrites[role] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
                manage_messages=True
            )

        try:
            channel = await ticket_category_channel.create_text_channel(
                name=f"{category}-{interaction.user.name}",
                overwrites=overwrites,
                topic=f"Ticket by {interaction.user} | ID: {ticket_id}"
            )

            # Add to database
            async with bot.db_lock:
                cursor = bot.db_connection.cursor()
                cursor.execute('''
                    INSERT INTO tickets (ticket_id, user_id, channel_id, category, guild_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (ticket_id, interaction.user.id, channel.id, category, interaction.guild_id))
                bot.db_connection.commit()

            # Create welcome embed
            category_emojis = {
                "general": "❓",
                "technical": "🔧",
                "report": "🚨",
                "partnership": "🤝",
                "other": "💬"
            }

            embed = discord.Embed(
                title=f"{category_emojis.get(category, '🎫')} Support Ticket",
                description=f"Hello {interaction.user.mention}! Thanks for creating a ticket.",
                color=discord.Color.green()
            )
            embed.add_field(
                name="📋 Information",
                value=f"**Category:** {category.title()}\n**Ticket ID:** `{ticket_id}`\n**Created:** {discord.utils.format_dt(datetime.datetime.utcnow())}",
                inline=False
            )
            embed.add_field(
                name="📝 Next Steps",
                value="Please describe your issue or question in detail. Our staff will be with you shortly!",
                inline=False
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)

            view = TicketControlView()
            await channel.send(f"📢 {interaction.user.mention}", embed=embed, view=view)
            
            await interaction.response.send_message(
                f"✅ Ticket created successfully! Please head to {channel.mention}",
                ephemeral=True
            )

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to create ticket: {str(e)}",
                ephemeral=True
            )

class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_close_button")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        cursor = bot.db_connection.cursor()
        
        # Get ticket info
        cursor.execute('''
            SELECT ticket_id, user_id FROM tickets 
            WHERE channel_id = ? AND status = 'open'
        ''', (interaction.channel_id,))
        
        ticket_info = cursor.fetchone()
        if not ticket_info:
            await interaction.response.send_message("❌ This is not a valid ticket channel!", ephemeral=True)
            return

        ticket_id, ticket_user_id = ticket_info
        
        # Check permissions
        if (interaction.user.id != ticket_user_id and 
            not interaction.user.guild_permissions.manage_channels):
            await interaction.response.send_message("❌ You can only close your own tickets!", ephemeral=True)
            return

        # Confirm closure
        embed = discord.Embed(
            title="🔒 Close this ticket?",
            description="We’ll archive the conversation and delete the channel after confirmation.",
            color=discord.Color.red()
        )
        view = TicketCloseConfirmView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.primary, emoji="🎯", custom_id="ticket_claim_button")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ You don't have permission to claim tickets!", ephemeral=True)
            return

        bot = interaction.client
        async with bot.db_lock:
            cursor = bot.db_connection.cursor()
            
            # Update ticket assignment
            cursor.execute('''
                UPDATE tickets SET assigned_to = ? WHERE channel_id = ?
            ''', (interaction.user.id, interaction.channel_id))
            bot.db_connection.commit()

        embed = discord.Embed(
            title="🎯 Ticket Claimed",
            description=f"{interaction.user.mention} has claimed this ticket and will assist you.",
            color=discord.Color.blue()
        )
        
        await interaction.response.send_message(embed=embed)

class TicketCloseConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Yes, Close", style=discord.ButtonStyle.danger, custom_id="ticket_confirm_close_button")
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        async with bot.db_lock:
            cursor = bot.db_connection.cursor()
            
            # Update ticket status
            cursor.execute('''
                UPDATE tickets SET status = 'closed', closed_at = CURRENT_TIMESTAMP 
                WHERE channel_id = ?
            ''', (interaction.channel_id,))
            bot.db_connection.commit()

        # Create transcript (simplified)
        transcript = f"Ticket Transcript\n\nTicket closed by: {interaction.user}\nClosed at: {datetime.datetime.utcnow()}\n\n"
        
        # Send closing message
        embed = discord.Embed(
            title="🔒 Ticket Closed",
            description="This ticket has been closed. The channel will be deleted in 5 seconds.",
            color=discord.Color.red()
        )
        
        await interaction.response.edit_message(embed=embed, view=None)
        
        # Delete channel after 5 seconds
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except:
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="ticket_cancel_close_button")
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Ticket closure cancelled.", embed=None, view=None)

# Auto-moderation cog with features similar to Dyno/Vortex
class AutoModCog(commands.Cog):
    def __init__(self, bot: HybridBot):
        self.bot = bot
        self.spam_cache = defaultdict(lambda: defaultdict(list))
        self.invite_pattern = re.compile(r'discord(?:app)?\.(?: com|gg)/(?:invite/)?([a-zA-Z0-9-]+)')
        
        # Load config values
        try:
            from config import ModerationConfig
            self.spam_threshold = getattr(ModerationConfig, 'SPAM_THRESHOLD', 5)
            self.spam_timeout = getattr(ModerationConfig, 'SPAM_TIMEOUT_DURATION', 5)
            self.mass_mention_threshold = getattr(ModerationConfig, 'MASS_MENTION_THRESHOLD', 5)
            self.mass_mention_timeout = getattr(ModerationConfig, 'MASS_MENTION_TIMEOUT', 10)
        except:
            # Fallback values
            self.spam_threshold = 5
            self.spam_timeout = 5
            self.mass_mention_threshold = 5
            self.mass_mention_timeout = 10
        
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        # Skip auto-mod for moderators
        if message.author.guild_permissions.manage_messages:
            return
            
        # Check for spam
        await self.check_spam(message)
        
        # Check for invites
        await self.check_invites(message)
        
        # Check for mass mentions
        await self.check_mass_mentions(message)

    async def check_spam(self, message: discord.Message):
        """Check for spam messages"""
        user_id = message.author.id
        channel_id = message.channel.id
        current_time = datetime.datetime.utcnow()
        
        # Add current message timestamp
        self.spam_cache[user_id][channel_id].append(current_time)
        
        # Remove messages older than 5 seconds (prevent unbounded growth)
        cutoff = current_time - datetime.timedelta(seconds=5)
        self.spam_cache[user_id][channel_id] = [
            ts for ts in self.spam_cache[user_id][channel_id] if ts > cutoff
        ]
        
        # Check if user exceeded spam threshold
        if len(self.spam_cache[user_id][channel_id]) > self.spam_threshold:
            try:
                # Delete recent messages
                deleted_count = 0
                async for msg in message.channel.history(limit=15):
                    if (msg.author.id == user_id and 
                        current_time - msg.created_at <= datetime.timedelta(seconds=5)):
                        try:
                            await msg.delete()
                            deleted_count += 1
                        except:
                            pass
                
                # Timeout the user
                await message.author.timeout(
                    datetime.timedelta(minutes=self.spam_timeout),
                    reason="Auto-mod: Spam detection"
                )
                
                # Send warning
                embed = discord.Embed(
                    title="🚨 Auto-Moderation Action",
                    description=f"{message.author.mention} has been timed out for spam.",
                    color=discord.Color.red()
                )
                embed.add_field(name="📝 Reason", value=f"Spam detection ({self.spam_threshold}+ messages in 5 seconds)", inline=False)
                embed.add_field(name="⏱️ Duration", value=f"{self.spam_timeout} minutes", inline=False)
                embed.add_field(name="🗑️ Deleted", value=f"{deleted_count} messages", inline=False)
                
                await message.channel.send(embed=embed, delete_after=10)
                
                # Clear cache for user
                self.spam_cache[user_id][channel_id].clear()
                
            except discord.Forbidden:
                pass
            except Exception as e:
                logging.error(f"Spam check error: {e}")

    async def check_invites(self, message: discord.Message):
        """Check for Discord invite links"""
        if self.invite_pattern.search(message.content):
            try:
                await message.delete()
                
                embed = discord.Embed(
                    title="🚨 Auto-Moderation Action",
                    description=f"{message.author.mention}, Discord invite links are not allowed!",
                    color=discord.Color.orange()
                )
                embed.add_field(name="📝 Action", value="Message deleted", inline=False)
                
                await message.channel.send(embed=embed, delete_after=5)
                
            except discord.Forbidden:
                pass
            except Exception as e:
                logging.error(f"Invite check error: {e}")

    async def check_mass_mentions(self, message: discord.Message):
        """Check for mass mentions"""
        mention_count = len(message.mentions) + len(message.role_mentions)
        
        if mention_count > self.mass_mention_threshold:
            try:
                await message.delete()
                
                # Timeout for mass mentions
                await message.author.timeout(
                    datetime.timedelta(minutes=self.mass_mention_timeout),
                    reason="Auto-mod: Mass mentions"
                )
                
                embed = discord.Embed(
                    title="🚨 Auto-Moderation Action",
                    description=f"{message.author.mention} has been timed out for mass mentions.",
                    color=discord.Color.red()
                )
                embed.add_field(name="📝 Reason", value=f"Mass mentions ({mention_count} mentions)", inline=False)
                embed.add_field(name="⏱️ Duration", value=f"{self.mass_mention_timeout} minutes", inline=False)
                
                await message.channel.send(embed=embed, delete_after=10)
                
            except discord.Forbidden:
                pass
            except Exception as e:
                logging.error(f"Mass mention check error: {e}")

# Logging cog for comprehensive server logs
class LoggingCog(commands.Cog):
    def __init__(self, bot: HybridBot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Log deleted messages"""
        if message.author.bot:
            return
            
        embed = discord.Embed(
            title="🗑️ Message Deleted",
            description=f"Message by {message.author.mention} was deleted in {message.channel.mention}",
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="📝 Content", value=message.content[:1000] or "*No content*", inline=False)
        embed.add_field(name="👤 Author", value=f"{message.author} ({message.author.id})", inline=True)
        embed.add_field(name="📍 Channel", value=message.channel.mention, inline=True)
        embed.set_thumbnail(url=message.author.display_avatar.url)
        
        await self.send_to_log_channel(message.guild, embed, "message")

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Log edited messages"""
        if before.author.bot or before.content == after.content:
            return
            
        embed = discord.Embed(
            title="📝 Message Edited",
            description=f"Message by {before.author.mention} was edited in {before.channel.mention}",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="📝 Before", value=before.content[:500] or "*No content*", inline=False)
        embed.add_field(name="📝 After", value=after.content[:500] or "*No content*", inline=False)
        embed.add_field(name="👤 Author", value=f"{before.author} ({before.author.id})", inline=True)
        embed.add_field(name="📍 Channel", value=before.channel.mention, inline=True)
        embed.set_thumbnail(url=before.author.display_avatar.url)
        
        await self.send_to_log_channel(before.guild, embed, "message")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Log member joins"""
        embed = discord.Embed(
            title="📥 Member Joined",
            description=f"{member.mention} joined the server",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="👤 User", value=f"{member} ({member.id})", inline=True)
        embed.add_field(name="📅 Account Created", value=discord.utils.format_dt(member.created_at, 'R'), inline=True)
        embed.add_field(name="📊 Member Count", value=member.guild.member_count, inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await self.send_to_log_channel(member.guild, embed, "member")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Log member leaves"""
        embed = discord.Embed(
            title="📤 Member Left",
            description=f"{member} left the server",
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="👤 User", value=f"{member} ({member.id})", inline=True)
        embed.add_field(name="📅 Joined", value=discord.utils.format_dt(member.joined_at, 'R') if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="📊 Member Count", value=member.guild.member_count, inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await self.send_to_log_channel(member.guild, embed, "member")

    async def send_to_log_channel(self, guild: discord.Guild, embed: discord.Embed, log_type: str):
        """Send log message to appropriate channel"""
        async with self.bot.db_lock:
            cursor = self.bot.db_connection.cursor()
            cursor.execute('SELECT modlog_channel FROM guild_settings WHERE guild_id = ?', (guild.id,))
            result = cursor.fetchone()
        
        if result and result[0]:
            channel = guild.get_channel(result[0])
            if channel:
                try:
                    await channel.send(embed=embed)
                except:
                    pass

# Additional utility commands
class UtilityCog(commands.Cog):
    def __init__(self, bot: HybridBot):
        self.bot = bot

    @app_commands.command(name="userinfo", description="Get information about a user")
    @app_commands.describe(member="The member to get info about")
    async def userinfo(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if member is None:
            member = interaction.user
        
        embed = discord.Embed(
            title="👤 User Information",
            color=member.color if member.color != discord.Color.default() else discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="📝 Username", value=f"{member}", inline=True)
        embed.add_field(name="🆔 User ID", value=member.id, inline=True)
        embed.add_field(name="📅 Account Created", value=discord.utils.format_dt(member.created_at, 'F'), inline=False)
        embed.add_field(name="📅 Joined Server", value=discord.utils.format_dt(member.joined_at, 'F') if member.joined_at else "Unknown", inline=False)
        
        if member.roles[1:]:  # Exclude @everyone role
            roles = ", ".join([role.mention for role in member.roles[1:][:10]])  # Limit to 10 roles
            if len(member.roles) > 11:
                roles += f" and {len(member.roles) - 11} more..."
            embed.add_field(name="🎭 Roles", value=roles, inline=False)
        
        embed.add_field(name="📊 Join Position", value=sum(1 for m in interaction.guild.members if m.joined_at and member.joined_at and m.joined_at < member.joined_at) + 1, inline=True)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Get information about the server")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        
        embed = discord.Embed(
            title="🏰 Server Information",
            description=f"Information about **{guild.name}**",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )
        
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        embed.add_field(name="👑 Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
        embed.add_field(name="🆔 Server ID", value=guild.id, inline=True)
        embed.add_field(name="📅 Created", value=discord.utils.format_dt(guild.created_at, 'F'), inline=True)
        embed.add_field(name="👥 Members", value=guild.member_count, inline=True)
        embed.add_field(name="💬 Channels", value=len(guild.channels), inline=True)
        embed.add_field(name="🎭 Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="😀 Emojis", value=len(guild.emojis), inline=True)
        embed.add_field(name="📈 Boost Level", value=guild.premium_tier, inline=True)
        embed.add_field(name="💎 Boosts", value=guild.premium_subscription_count, inline=True)
        
        if guild.features:
            features = ", ".join(guild.features)
            embed.add_field(name="✨ Features", value=features, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setup-modlog", description="Set up moderation logging")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(channel="Channel to send moderation logs to")
    async def setup_modlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with self.bot.db_lock:
            cursor = self.bot.db_connection.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO guild_settings (guild_id, modlog_channel)
                VALUES (?, ?)
            ''', (interaction.guild_id, channel.id))
            self.bot.db_connection.commit()

        embed = discord.Embed(
            title="✅ Moderation Logging Setup",
            description=f"Moderation logs will now be sent to {channel.mention}",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed)

# Help command
@app_commands.command(name="help", description="Show help information")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Hybrid Bot - Help",
        description="A powerful Discord bot combining the best of Dyno, Vortex, and modern ticket systems!",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🛡️ Moderation Commands",
        value="`/ban` - Ban a member\n`/kick` - Kick a member\n`/mute` - Mute a member\n`/unmute` - Unmute a member\n`/warn` - Warn a member\n`/clear` - Clear messages\n`/unban` - Unban a user\n`/modlogs` - View user's moderation history",
        inline=False
    )
    
    embed.add_field(
        name="🎫 Ticket System",
        value="`/ticket-setup` - Set up the ticket system\n`/ticket-stats` - View ticket statistics\nUse the ticket panel to create tickets\nStaff can claim and close tickets",
        inline=False
    )
    
    embed.add_field(
        name="🔧 Utility Commands",
        value="`/userinfo` - Get user information\n`/serverinfo` - Get server information\n`/setup-modlog` - Set up moderation logging",
        inline=False
    )
    
    embed.add_field(
        name="🤖 Auto-Moderation Features",
        value="• Automatic spam detection\n• Discord invite filtering\n• Mass mention protection\n• Comprehensive message/member logging",
        inline=False
    )
    
    embed.add_field(
        name="📊 Key Features",
        value="• Modern slash commands\n• Beautiful embeds and UI\n• SQLite database logging\n• Persistent views and buttons\n• User-friendly interface\n• Comprehensive moderation tools",
        inline=False
    )
    
    embed.set_footer(text="Made with ❤️ for your Discord server")
    
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    # Create bot instance and run
    bot = HybridBot()

    # Determine token from environment or config
    token = os.getenv("DISCORD_TOKEN") or getattr(BotConfig, "BOT_TOKEN", "")
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        print("❌ No Discord token provided. Set DISCORD_TOKEN env var or config.BotConfig.BOT_TOKEN.")
    else:
        bot.run(token)