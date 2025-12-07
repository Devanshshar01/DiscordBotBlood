# Music System Guide

This guide explains how to use the music features in `DiscordBotBlood` (slash commands, playlists, radio, filters, and controls).

## 1) Prerequisites
- Intents: Enable **Message Content** and **Server Members** in the Discord Developer Portal.
- Dependencies: Install from `requirements.txt` (needs FFmpeg available on PATH).
- Voice: For voice features, PyNaCl is required (included in requirements). FFmpeg must be installed.
- Token: Set `DISCORD_TOKEN` in `.env` or `config.py`.

## 2) Quick start
1) Run the bot: `python bot.py`
2) Join a voice channel.
3) Play something: `/play never gonna give you up` (or a YouTube/Spotify/SoundCloud link).
4) View current track & controls: `/nowplaying` (buttons: play/pause, skip, loop, shuffle, stop).

## 3) Core music commands
- `/play <query|url>` — Plays immediately if idle, otherwise enqueues. Supports YouTube (search/links/playlists), SoundCloud, Spotify links/playlists (resolved via yt-dlp).
- `/skip` — Skip current track (vote-skip applies if enabled and multiple listeners).
- `/pause` / `/resume` — Pause/resume playback.
- `/stop` — Stop and clear the queue.
- `/queue` — Show up to 10 queued items (first page).
- `/remove <position>` — Remove by queue position (1-based).
- `/shuffle` — Shuffle queue.
- `/loop` — Cycles loop modes: off → single → queue.
- `/nowplaying` — Shows current track with embed + button controls.
- `/volume <0-100>` — Set playback volume.
- `/bassboost` — Toggle bass boost filter.
- `/nightcore` — Toggle nightcore filter.
- `/lyrics <query>` — Fetch lyrics via Genius (requires `GENIUS_TOKEN` in config/env).

### Limits & safety
- Max queue size: 50 (from `MusicConfig.MAX_QUEUE_SIZE`).
- Max song duration: 10 minutes (from `MusicConfig.MAX_SONG_DURATION`).
- Cooldowns: 3s on key commands.
- Only users in a voice channel can control playback.
- Vote-skip: requires 50% of non-bot listeners when enabled.

## 4) Playlists (per-user per-guild, stored in SQLite)
- `/playlist create <name>` — Create a personal playlist.
- `/playlist add <name> <song>` — Add a song (search/url) to your playlist.
- `/playlist remove <name> <position>` — Remove entry by position.
- `/playlist play <name>` — Enqueue all songs from the playlist (respects queue size & duration limits).
- `/playlist list` — List your playlists.
- `/playlist delete <name>` — Delete a playlist (and its songs).

## 5) Radio (24/7 mode)
- `/radio setup <voice_channel>` — Set the voice channel for radio mode (starts background loop).
- `/radio add <url> <name>` — Add a stream URL to rotate (e.g., shoutcast/icecast/YouTube radio).
- `/radio list` — List configured streams.
- `/radio remove <id>` — Remove a stream by id.
Behavior: The bot stays connected to the configured channel and cycles through stored streams. It auto-retries on disconnect.

## 6) Buttons (Now Playing)
- ⏯️ Play/Pause
- ⏭️ Skip
- 🔁 Loop mode toggle
- 🔀 Shuffle
- ⏹️ Stop
Permissions check: only members in the same voice channel can use the buttons.

## 7) Filters
- Bassboost: FFmpeg EQ filters, toggled by `/bassboost`.
- Nightcore: Speed/pitch filter, toggled by `/nightcore`.
Note: Filters replace the active filter set; they do not stack beyond the two toggles.

## 8) Configuration knobs (`config.py` > `MusicConfig`)
- `MAX_QUEUE_SIZE` (default 50)
- `MAX_SONG_DURATION` (default 600 seconds)
- `INACTIVITY_TIMEOUT` (default 300 seconds)
- `DEFAULT_VOLUME` (percent)
- `ENABLE_VOTE_SKIP` (True/False)
- `VOTE_SKIP_RATIO` (0.5)
- `SEARCH_RESULTS_LIMIT` (default 5)

## 9) Tips & troubleshooting
- If audio is silent: ensure FFmpeg is installed and on PATH; ensure the bot and user are in the same voice region and channel; check role/VC permissions (connect/speak).
- If links fail (age/region restricted): try another source or a direct YouTube link; yt-dlp handles many fallbacks automatically.
- Queue full / duration too long: adjust `MusicConfig` if you need higher limits.
- Lyrics: set `GENIUS_TOKEN` in environment or `BotConfig`.
- Voice warning about PyNaCl: install with `pip install PyNaCl` (already in requirements).

## 10) Typical flows
- Quick music: `/play <query>` → `/nowplaying` buttons to control.
- Party queue: multiple users `/play` to enqueue; use `/queue` to view; `/shuffle` to mix; `/loop` for repeat.
- Save & reuse: `/playlist create chill`, `/playlist add chill lofi hip hop`, later `/playlist play chill`.
- Radio mode: `/radio setup <vc>` then `/radio add <stream_url> <name>`; let it run 24/7.

Enjoy the music features! If you want richer progress bars, ETA display, or seeking, we can extend `music.py` further.
