# DiscordBotBlood

Simple hybrid Discord bot with moderation, tickets, auto-mod, and logging.

## Files
- `bot.py` — main bot code (slash commands + cogs)
- `config.py` — configuration template (set your token here or via env var)
- `requirements.txt` — Python dependencies

## Quick start
1. Install deps: `pip install -r requirements.txt`
2. Set your token: either export `DISCORD_TOKEN` or edit `config.py` (`BotConfig.BOT_TOKEN`).
3. Run the bot: `python bot.py`
4. Invite the bot with the `applications.commands` scope and necessary permissions (ban/kick/manage channels/messages).

## First-time setup
- `/setup-modlog <channel>` to select where logs go.
- `/ticket-setup <panel-channel> <ticket-category>` to drop the ticket panel and pick a category for ticket channels.

## Commands
- Moderation: `/ban`, `/kick`, `/mute`, `/unmute`, `/warn`, `/clear`, `/unban`, `/modlogs`
- Tickets: `/ticket-setup`, `/ticket-stats` (use the panel to create/close/claim)
- Utility: `/userinfo`, `/serverinfo`, `/help`
- Auto-mod: spam, invites, and mass-mentions are filtered automatically (needs Message Content intent enabled in the Dev Portal).

## Notes
- The bot uses SQLite for persistence (`hybrid_bot.db`).
- Message Content and Server Members intents should be enabled in the Discord Developer Portal for full functionality.
- Keep the bot's top role above the roles you want it to moderate.
- **Smart Permissions**: Respects role hierarchy and permissions
