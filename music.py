import asyncio
import datetime
import math
import re
import shutil
import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

try:
    import lyricsgenius
except Exception:
    lyricsgenius = None

try:
    import spotipy  # noqa: F401
except Exception:
    pass

try:
    from config import MusicConfig
except Exception:
    class MusicConfig:  # type: ignore
        MAX_QUEUE_SIZE = 50
        MAX_SONG_DURATION = 600
        INACTIVITY_TIMEOUT = 300
        DEFAULT_VOLUME = 50
        ENABLE_VOTE_SKIP = True
        VOTE_SKIP_RATIO = 0.5
        SEARCH_RESULTS_LIMIT = 5

# ===========================
# HIGH-FIDELITY AUDIO CONFIGURATION
# ===========================

# FFmpeg Options - Broadcast Quality PCM Pipeline
# Optimized for Discord's Opus codec (48kHz, stereo, no transcoding artifacts)
FFMPEG_OPTIONS_BASE = {
    "before_options": (
        "-reconnect 1 "              # Auto-reconnect on network drops
        "-reconnect_streamed 1 "     # Reconnect for streaming sources
        "-reconnect_delay_max 5 "    # Max 5s reconnect delay
        "-analyzeduration 0 "        # Instant playback start
        "-loglevel panic "           # Suppress FFmpeg logs
        "-nostats "                  # No stats output
        "-multiple_requests 1"       # Better HLS/DASH handling
    ),
    "options": (
        "-vn "                       # No video processing
        "-ac 2 "                     # Force stereo (Discord native)
        "-ar 48000 "                 # 48kHz sample rate (Discord native)
        "-f s16le "                  # Raw PCM 16-bit little-endian
        "-acodec pcm_s16le "         # PCM codec (no compression)
        "-loglevel panic "           # Suppress output logs
        "-bufsize 512k "             # Large buffer for stability
        "-flush_packets 0"           # Reduce latency
    ),
}

# yt-dlp Options - Maximum Audio Quality Extraction
# Prefers Opus (Discord's native codec) to avoid re-encoding
YT_DLP_OPTIONS = {
    # Format selection - CRITICAL for audio quality
    "format": (
        "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio/best"
    ),
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": False,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "extract_flat": False,
    "source_address": "0.0.0.0",  # Bind to default network interface
    "socket_timeout": 30,
    "retries": 10,                 # Retry failed downloads
    "fragment_retries": 10,        # Retry failed fragments
    "extractor_retries": 3,        # Retry extractor calls
    "file_access_retries": 3,      # Retry file access
    "cachedir": False,             # Don't cache to disk
    
    # Audio quality parameters
    "prefer_ffmpeg": True,
    "keepvideo": False,
    "postprocessors": [],          # No post-processing (preserves quality)
}

# Try to find FFmpeg executable
FFMPEG_EXECUTABLE = shutil.which("ffmpeg")
if not FFMPEG_EXECUTABLE:
    # Try common installation paths
    possible_paths = [
        r"C:\ffmpeg\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            FFMPEG_EXECUTABLE = path
            break
    if not FFMPEG_EXECUTABLE:
        FFMPEG_EXECUTABLE = "ffmpeg"  # Fall back to system PATH

# ===========================
# AUDIO FILTERS - HIGH QUALITY DSP
# ===========================

# Parametric EQ Bass Boost - Proper frequency shaping, no distortion
BASSBOOST_FILTER = (
    "equalizer=f=40:t=h:width=50:g=10,"    # Sub-bass boost
    "equalizer=f=100:t=h:width=100:g=8,"   # Bass boost
    "equalizer=f=200:t=h:width=100:g=4"    # Low-mid warmth
)

# Nightcore - True speed and pitch shift
NIGHTCORE_FILTER = (
    "asetrate=48000*1.25,"                  # Increase sample rate (pitch up)
    "aresample=48000,"                      # Resample to Discord native
    "atempo=1.1"                            # Speed up slightly
)

# 8D Audio - Spatial panning effect
AUDIO_8D_FILTER = (
    "apulsator=hz=0.125,"                   # Slow pulsing effect
    "stereotools=mlev=0.015625"             # Subtle stereo widening
)

# Karaoke - Vocal reduction (center channel removal)
KARAOKE_FILTER = (
    "pan=stereo|c0=c0-c1|c1=c1-c0"         # Phase cancellation
)

# Normalize - Loudness normalization to prevent clipping
NORMALIZE_FILTER = (
    "loudnorm=I=-16:LRA=11:TP=-1.5"        # EBU R128 standard
)


class LoopMode(Enum):
    NONE = 0
    ONE = 1
    QUEUE = 2


@dataclass
class Track:
    title: str
    url: str
    webpage_url: str
    duration: int
    thumbnail: Optional[str]
    uploader: Optional[str]
    requester: Optional[discord.Member]
    # Audio quality metadata
    acodec: Optional[str] = None
    abr: Optional[float] = None
    asr: Optional[int] = None
    format_note: Optional[str] = None

    @property
    def safe_title(self) -> str:
        return self.title or "Unknown"
    
    @property
    def is_opus(self) -> bool:
        """Check if source is already Opus codec"""
        return self.acodec and "opus" in self.acodec.lower()
    
    @property
    def quality_info(self) -> str:
        """Return audio quality information"""
        parts = []
        if self.acodec:
            parts.append(f"codec:{self.acodec}")
        if self.abr:
            parts.append(f"{int(self.abr)}kbps")
        if self.asr:
            parts.append(f"{self.asr}Hz")
        return " | ".join(parts) if parts else "Unknown quality"


class HighFidelityAudioSource:
    """
    High-fidelity audio source with Opus passthrough optimization.
    Automatically detects if source can bypass FFmpeg decoding for zero-loss quality.
    """
    def __init__(self, track: Track, *, bassboost: bool = False, nightcore: bool = False, 
                 audio_8d: bool = False, karaoke: bool = False, normalize: bool = False):
        self.track = track
        self.bassboost = bassboost
        self.nightcore = nightcore
        self.audio_8d = audio_8d
        self.karaoke = karaoke
        self.normalize = normalize

    def _build_filters(self) -> Optional[str]:
        """Build FFmpeg audio filter chain"""
        filters = []
        
        if self.bassboost:
            filters.append(BASSBOOST_FILTER)
        if self.nightcore:
            filters.append(NIGHTCORE_FILTER)
        if self.audio_8d:
            filters.append(AUDIO_8D_FILTER)
        if self.karaoke:
            filters.append(KARAOKE_FILTER)
        if self.normalize:
            filters.append(NORMALIZE_FILTER)
        
        return ",".join(filters) if filters else None

    def to_discord_source(self, url: str, volume: float = 1.0) -> discord.AudioSource:
        """
        Create Discord audio source with maximum quality.
        Uses Opus passthrough when possible, otherwise high-quality PCM pipeline.
        """
        filter_str = self._build_filters()
        
        # Check if we can use direct Opus passthrough (no filters, opus source)
        # This gives MAXIMUM quality with zero transcoding
        can_passthrough = (
            not filter_str and 
            self.track.is_opus and 
            self.track.asr == 48000
        )
        
        if can_passthrough:
            # OPUS PASSTHROUGH MODE - Zero quality loss
            # Discord native format, no re-encoding needed
            print(f"[AUDIO] Using Opus passthrough for: {self.track.safe_title}")
            try:
                # Direct Opus stream - best possible quality
                source = discord.FFmpegOpusAudio(
                    url,
                    executable=FFMPEG_EXECUTABLE,
                    bitrate=128  # Discord's Opus bitrate
                )
                return discord.PCMVolumeTransformer(source, volume=volume) if volume != 1.0 else source
            except Exception as e:
                print(f"[AUDIO] Opus passthrough failed, falling back to PCM: {e}")
        
        # HIGH-QUALITY PCM MODE
        # Use broadcast-quality FFmpeg pipeline
        opts = dict(FFMPEG_OPTIONS_BASE)
        
        # Add audio filters if specified
        if filter_str:
            opts["options"] = opts["options"] + f" -af {filter_str}"
        
        print(f"[AUDIO] Using high-fidelity PCM pipeline for: {self.track.safe_title}")
        print(f"[AUDIO] Quality: {self.track.quality_info}")
        if filter_str:
            print(f"[AUDIO] Filters: {filter_str}")
        
        # Create FFmpeg PCM audio source
        source = discord.FFmpegPCMAudio(
            url,
            executable=FFMPEG_EXECUTABLE,
            **opts
        )
        
        # Apply volume transformation (safe, no clipping)
        return discord.PCMVolumeTransformer(source, volume=volume)


class MusicPlayer:
    """
    High-fidelity music player with broadcast-quality audio pipeline.
    Supports Opus passthrough, advanced DSP filters, and stable streaming.
    """
    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self.queue_list: List[Track] = []
        self.current: Optional[Track] = None
        self.voice: Optional[discord.VoiceClient] = None
        self.loop_mode = LoopMode.NONE
        self.volume = MusicConfig.DEFAULT_VOLUME / 100
        self.playback_task: Optional[asyncio.Task] = None
        self.inactivity_task: Optional[asyncio.Task] = None
        
        # Audio filter states
        self.bassboost = False
        self.nightcore = False
        self.audio_8d = False
        self.karaoke = False
        self.normalize = True  # Auto-normalization enabled by default
        
        self.vote_skip: set[int] = set()

    def start(self):
        if self.playback_task is None or self.playback_task.done():
            self.playback_task = asyncio.create_task(self.player_loop())

    async def player_loop(self):
        """
        Main playback loop with high-quality audio processing.
        Handles track queuing, filter application, and error recovery.
        """
        await self.bot.wait_until_ready()
        while True:
            try:
                if self.loop_mode == LoopMode.ONE and self.current:
                    track = self.current
                else:
                    self.current = None
                    track = await asyncio.wait_for(self.queue.get(), timeout=MusicConfig.INACTIVITY_TIMEOUT)
                    if track in self.queue_list:
                        self.queue_list.remove(track)
                    self.current = track

                self.vote_skip.clear()
                
                # Create high-fidelity audio source with current filter settings
                source = HighFidelityAudioSource(
                    track, 
                    bassboost=self.bassboost, 
                    nightcore=self.nightcore,
                    audio_8d=self.audio_8d,
                    karaoke=self.karaoke,
                    normalize=self.normalize
                )
                
                # Get the direct audio URL
                audio_url = track.url
                
                if not self.voice or not self.voice.is_connected():
                    print(f"[PLAYER] Voice client disconnected, stopping playback")
                    break
                
                # Create audio source with volume control
                # Volume is applied safely to prevent clipping
                audio_source = source.to_discord_source(audio_url, volume=self.volume)
                
                print(f"[PLAYER] Now playing: {track.safe_title}")
                print(f"[PLAYER] Volume: {int(self.volume * 100)}%")
                
                # Start playback
                self.voice.play(
                    audio_source,
                    after=lambda e: asyncio.run_coroutine_threadsafe(
                        self.on_track_end(e), 
                        self.bot.loop
                    )
                )
                
                # Wait while playing
                while self.voice and (self.voice.is_playing() or self.voice.is_paused()):
                    await asyncio.sleep(1)
                
                # Handle loop modes
                if self.loop_mode == LoopMode.ONE:
                    continue
                if self.loop_mode == LoopMode.QUEUE:
                    self.queue_list.append(track)
                await asyncio.sleep(0.1)
                
            except asyncio.TimeoutError:
                print(f"[PLAYER] Inactivity timeout, disconnecting")
                await self.disconnect()
                break
            except Exception as e:
                print(f"[PLAYER] Playback error: {e}")
                import traceback
                traceback.print_exc()
                await self.disconnect()
                break

    async def on_track_end(self, error: Optional[Exception]):
        if error:
            print(f"[PLAYER] Track ended with error: {error}")

    async def connect(self, channel: discord.VoiceChannel):
        if self.voice and self.voice.is_connected():
            if self.voice.channel.id != channel.id:
                await self.voice.move_to(channel)
        else:
            self.voice = await channel.connect()
        self.start()

    async def enqueue(self, track: Track):
        if self.queue.qsize() + len(self.queue_list) >= MusicConfig.MAX_QUEUE_SIZE:
            raise ValueError("Queue is already full.")
        self.queue_list.append(track)
        await self.queue.put(track)

    async def skip(self):
        if self.voice and self.voice.is_playing():
            self.voice.stop()

    async def pause(self):
        if self.voice and self.voice.is_playing():
            self.voice.pause()

    async def resume(self):
        if self.voice and self.voice.is_paused():
            self.voice.resume()

    async def stop(self):
        self.queue_list.clear()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except Exception:
                break
        if self.voice:
            self.voice.stop()
        self.current = None
        self.loop_mode = LoopMode.NONE

    async def disconnect(self):
        await self.stop()
        if self.voice and self.voice.is_connected():
            await self.voice.disconnect(force=True)
        self.voice = None

    def set_volume(self, volume: int):
        """Set volume with safety clamping (0-100)"""
        self.volume = max(0, min(100, volume)) / 100
        if self.voice and self.voice.source and isinstance(self.voice.source, discord.PCMVolumeTransformer):
            self.voice.source.volume = self.volume

    def toggle_bass(self) -> bool:
        self.bassboost = not self.bassboost
        return self.bassboost

    def toggle_nightcore(self) -> bool:
        self.nightcore = not self.nightcore
        return self.nightcore
    
    def toggle_8d(self) -> bool:
        self.audio_8d = not self.audio_8d
        return self.audio_8d
    
    def toggle_karaoke(self) -> bool:
        self.karaoke = not self.karaoke
        return self.karaoke
    
    def toggle_normalize(self) -> bool:
        self.normalize = not self.normalize
        return self.normalize

    def shuffle(self):
        if len(self.queue_list) > 1:
            import random
            random.shuffle(self.queue_list)
            # rebuild queue
            new_queue = asyncio.Queue()
            for t in self.queue_list:
                new_queue.put_nowait(t)
            self.queue = new_queue

    def cycle_loop(self) -> LoopMode:
        if self.loop_mode == LoopMode.NONE:
            self.loop_mode = LoopMode.ONE
        elif self.loop_mode == LoopMode.ONE:
            self.loop_mode = LoopMode.QUEUE
        else:
            self.loop_mode = LoopMode.NONE
        return self.loop_mode

    def remaining(self) -> List[Track]:
        return list(self.queue_list)


class MusicCog(commands.Cog):
    """
    High-Fidelity Music Cog with broadcast-quality audio pipeline.
    Features: Opus passthrough, advanced filters, stable streaming, quality monitoring.
    """
    playlist_group = app_commands.Group(name="playlist", description="Manage personal playlists")
    radio_group = app_commands.Group(name="radio", description="24/7 radio mode")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: Dict[int, MusicPlayer] = {}
        self.radio_tasks: Dict[int, asyncio.Task] = {}
        
        # High-quality yt-dlp extractor
        self.ytdl = yt_dlp.YoutubeDL(YT_DLP_OPTIONS)
        self.genius_client = None
        
        print("[MUSIC] High-Fidelity Music System Initialized")
        print(f"[MUSIC] FFmpeg: {FFMPEG_EXECUTABLE}")
        print(f"[MUSIC] Audio Pipeline: Opus passthrough + 48kHz PCM")

    # Helpers
    def get_player(self, guild: discord.Guild) -> MusicPlayer:
        if guild.id not in self.players:
            self.players[guild.id] = MusicPlayer(self.bot, guild)
        return self.players[guild.id]

    async def ensure_voice(self, interaction: discord.Interaction) -> discord.VoiceChannel:
        if not interaction.user.voice or not interaction.user.voice.channel:
            raise commands.CommandError("You must be in a voice channel.")
        channel = interaction.user.voice.channel
        return channel

    async def search(self, query: str, limit: int = 5) -> List[Track]:
        if re.match(r"https?://", query):
            # direct URL handling
            info = await asyncio.to_thread(self.ytdl.extract_info, query, download=False)
            if info is None:
                raise commands.CommandError("Could not extract that link.")
            entries = info.get("entries")
            if entries:
                first = entries[0]
                return [self._info_to_track(first, requester=None)]
            return [self._info_to_track(info, requester=None)]
        # search
        info = await asyncio.to_thread(self.ytdl.extract_info, f"ytsearch{limit}:{query}", download=False)
        if not info or not info.get("entries"):
            raise commands.CommandError("No results found.")
        return [self._info_to_track(e, requester=None) for e in info["entries"] if e]

    def _info_to_track(self, info: dict, requester: Optional[discord.Member]) -> Track:
        """
        Extract track information with audio quality metadata.
        Captures codec, bitrate, and sample rate for quality monitoring.
        """
        duration = info.get("duration") or 0
        
        # Extract the direct playable URL (prefer url, then webpage_url)
        url = info.get("url")
        if not url:
            url = info.get("webpage_url")
        # If still no URL, try to get it from formats
        if not url and info.get("formats"):
            for fmt in info["formats"]:
                if fmt.get("url"):
                    url = fmt["url"]
                    break
        
        # Extract audio quality metadata
        acodec = info.get("acodec") or "unknown"
        abr = info.get("abr") or info.get("tbr")  # Audio bitrate
        asr = info.get("asr") or info.get("sample_rate")  # Sample rate
        format_note = info.get("format_note") or info.get("format")
        
        track = Track(
            title=info.get("title") or "Unknown",
            url=url or info.get("webpage_url"),
            webpage_url=info.get("webpage_url") or url,
            duration=duration,
            thumbnail=info.get("thumbnail"),
            uploader=info.get("uploader") or info.get("channel"),
            requester=requester,
            acodec=acodec,
            abr=abr,
            asr=asr,
            format_note=format_note
        )
        
        # Log quality information
        print(f"[EXTRACT] {track.safe_title}")
        print(f"[EXTRACT] Quality: {track.quality_info}")
        
        return track

    def format_duration(self, seconds: int) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def progress_bar(self, position: float, duration: float, size: int = 14) -> str:
        if duration <= 0:
            return "?"
        ratio = min(max(position / duration, 0), 1)
        filled = int(ratio * size)
        return "▬" * filled + "🔘" + "▬" * (size - filled)

    def ensure_not_full(self, player: MusicPlayer):
        if player.queue.qsize() + len(player.queue_list) >= MusicConfig.MAX_QUEUE_SIZE:
            raise commands.CommandError("Queue is already full.")

    async def add_playlist_entries(self, interaction: discord.Interaction, info: dict, player: MusicPlayer):
        entries = info.get("entries") or []
        added = 0
        for entry in entries:
            if not entry:
                continue
            if entry.get("duration", 0) > MusicConfig.MAX_SONG_DURATION:
                continue
            track = self._info_to_track(entry, requester=interaction.user)
            player.queue_list.append(track)
            await player.queue.put(track)
            added += 1
            if player.queue.qsize() + len(player.queue_list) >= MusicConfig.MAX_QUEUE_SIZE:
                break
        return added

    # Slash commands

    @app_commands.command(name="play", description="Play a song or add to queue")
    @app_commands.checks.cooldown(1, 3)
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        channel = await self.ensure_voice(interaction)
        player = self.get_player(interaction.guild)
        self.ensure_not_full(player)
        await player.connect(channel)

        # handle search or URL
        try:
            info = await asyncio.to_thread(self.ytdl.extract_info, query, download=False)
        except Exception:
            info = None

        if info and info.get("entries"):
            # playlist or search list
            added = await self.add_playlist_entries(interaction, info, player)
            await interaction.followup.send(content=f"✅ Added {added} tracks to queue.")
        elif info:
            track = self._info_to_track(info, requester=interaction.user)
            if track.duration and track.duration > MusicConfig.MAX_SONG_DURATION:
                await interaction.followup.send(content="❌ This song exceeds the maximum duration limit.")
                return
            await player.enqueue(track)
            await interaction.followup.send(content=f"✅ Added to queue: **{track.safe_title}**")
        else:
            # manual search
            results = await self.search(query, limit=MusicConfig.SEARCH_RESULTS_LIMIT)
            view = SearchSelectView(self, interaction.user, results, player)
            embed = discord.Embed(title="🔍 Select a result", color=discord.Color.blurple())
            for idx, r in enumerate(results, 1):
                embed.add_field(name=f"{idx}. {r.safe_title}", value=f"{self.format_duration(r.duration)}", inline=False)
            await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="skip", description="Skip the current track")
    @app_commands.checks.cooldown(1, 3)
    async def skip(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.current:
            await interaction.response.send_message("❌ Nothing is playing.", ephemeral=True)
            return
        # vote skip
        channel = interaction.user.voice.channel if interaction.user.voice else None
        if channel and MusicConfig.ENABLE_VOTE_SKIP:
            listeners = [m for m in channel.members if not m.bot]
            if len(listeners) > 1:
                player.vote_skip.add(interaction.user.id)
                required = math.ceil(len(listeners) * MusicConfig.VOTE_SKIP_RATIO)
                if len(player.vote_skip) < required:
                    await interaction.response.send_message(f"🗳️ Vote registered ({len(player.vote_skip)}/{required}).", ephemeral=True)
                    return
        await player.skip()
        await interaction.response.send_message("⏭️ Skipped.")

    @app_commands.command(name="pause", description="Pause playback")
    async def pause(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        await player.pause()
        await interaction.response.send_message("⏸️ Paused.")

    @app_commands.command(name="resume", description="Resume playback")
    async def resume(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        await player.resume()
        await interaction.response.send_message("▶️ Resumed.")

    @app_commands.command(name="stop", description="Stop playback and clear queue")
    async def stop(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        await player.stop()
        await interaction.response.send_message("⏹️ Stopped and cleared queue.")

    @app_commands.command(name="queue", description="Show the queue")
    async def queue(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.queue_list:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)
            return
        lines = []
        for idx, t in enumerate(player.queue_list[:10], 1):
            lines.append(f"`{idx}.` {t.safe_title} ({self.format_duration(t.duration)})")
        embed = discord.Embed(title="Queue", description="\n".join(lines), color=discord.Color.blurple())
        if len(player.queue_list) > 10:
            embed.set_footer(text=f"and {len(player.queue_list) - 10} more...")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="remove", description="Remove a track from the queue")
    async def remove(self, interaction: discord.Interaction, position: int):
        player = self.get_player(interaction.guild)
        if position < 1 or position > len(player.queue_list):
            await interaction.response.send_message("Invalid position.", ephemeral=True)
            return
        removed = player.queue_list.pop(position - 1)
        # rebuild queue
        new_q = asyncio.Queue()
        for t in player.queue_list:
            new_q.put_nowait(t)
        player.queue = new_q
        await interaction.response.send_message(f"Removed **{removed.safe_title}** from queue.")

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        player.shuffle()
        await interaction.response.send_message("🔀 Shuffled queue.")

    @app_commands.command(name="loop", description="Toggle loop mode")
    async def loop(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        mode = player.cycle_loop()
        label = {LoopMode.NONE: "off", LoopMode.ONE: "single", LoopMode.QUEUE: "queue"}[mode]
        await interaction.response.send_message(f"🔁 Loop set to **{label}**.")

    @app_commands.command(name="nowplaying", description="Show current track")
    async def nowplaying(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.current:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        track = player.current
        embed = discord.Embed(title="Now Playing", color=discord.Color.blurple(), url=track.webpage_url)
        embed.add_field(name="Title", value=f"[{track.safe_title}]({track.webpage_url})", inline=False)
        embed.add_field(name="Duration", value=self.format_duration(track.duration), inline=True)
        if track.requester:
            embed.add_field(name="Requested by", value=track.requester.mention, inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        await interaction.response.send_message(embed=embed, view=MusicControlView(self, interaction.user, player))

    @app_commands.command(name="volume", description="Set playback volume (0-100)")
    async def volume(self, interaction: discord.Interaction, volume: app_commands.Range[int, 0, 100]):
        player = self.get_player(interaction.guild)
        player.set_volume(volume)
        await interaction.response.send_message(f"🔊 Volume set to {volume}%.")

    @app_commands.command(name="seek", description="Seek to timestamp (mm:ss)")
    async def seek(self, interaction: discord.Interaction, timestamp: str):
        await interaction.response.send_message("Seeking is not supported in this simplified player.", ephemeral=True)

    @app_commands.command(name="forward", description="Forward by N seconds")
    async def forward(self, interaction: discord.Interaction, seconds: int):
        await interaction.response.send_message("Seeking is not supported in this simplified player.", ephemeral=True)

    @app_commands.command(name="rewind", description="Rewind by N seconds")
    async def rewind(self, interaction: discord.Interaction, seconds: int):
        await interaction.response.send_message("Seeking is not supported in this simplified player.", ephemeral=True)

    @app_commands.command(name="bassboost", description="Toggle parametric EQ bass boost")
    async def bassboost(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        state = player.toggle_bass()
        await interaction.response.send_message(f"🎵 Bass boost {'enabled' if state else 'disabled'}. Restart playback for effect.")

    @app_commands.command(name="nightcore", description="Toggle nightcore filter (speed+pitch)")
    async def nightcore(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        state = player.toggle_nightcore()
        await interaction.response.send_message(f"⚡ Nightcore {'enabled' if state else 'disabled'}. Restart playback for effect.")
    
    @app_commands.command(name="8d", description="Toggle 8D spatial audio effect")
    async def audio_8d(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        state = player.toggle_8d()
        await interaction.response.send_message(f"🌀 8D Audio {'enabled' if state else 'disabled'}. Restart playback for effect.")
    
    @app_commands.command(name="karaoke", description="Toggle karaoke mode (vocal reduction)")
    async def karaoke(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        state = player.toggle_karaoke()
        await interaction.response.send_message(f"🎤 Karaoke mode {'enabled' if state else 'disabled'}. Restart playback for effect.")
    
    @app_commands.command(name="normalize", description="Toggle audio normalization (anti-clipping)")
    async def normalize(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        state = player.toggle_normalize()
        await interaction.response.send_message(f"📊 Audio normalization {'enabled' if state else 'disabled'}.")
    
    @app_commands.command(name="quality", description="Show current audio quality info")
    async def quality(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.current:
            await interaction.response.send_message("❌ Nothing is playing.", ephemeral=True)
            return
        
        track = player.current
        embed = discord.Embed(title="🎵 Audio Quality Info", color=discord.Color.green())
        embed.add_field(name="Track", value=track.safe_title, inline=False)
        embed.add_field(name="Quality", value=track.quality_info, inline=False)
        embed.add_field(name="Opus Passthrough", value="✅ Yes" if track.is_opus else "❌ No (PCM pipeline)", inline=True)
        embed.add_field(name="Volume", value=f"{int(player.volume * 100)}%", inline=True)
        
        filters_active = []
        if player.bassboost:
            filters_active.append("Bass Boost")
        if player.nightcore:
            filters_active.append("Nightcore")
        if player.audio_8d:
            filters_active.append("8D Audio")
        if player.karaoke:
            filters_active.append("Karaoke")
        if player.normalize:
            filters_active.append("Normalize")
        
        embed.add_field(
            name="Active Filters",
            value=", ".join(filters_active) if filters_active else "None",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)

    # Playlist commands
    @playlist_group.command(name="create", description="Create a playlist")
    async def playlist_create(self, interaction: discord.Interaction, name: str):
        async with self.bot.db_lock:
            cur = self.bot.db_connection.cursor()
            cur.execute("INSERT INTO playlists (user_id, guild_id, name) VALUES (?, ?, ?)", (interaction.user.id, interaction.guild_id, name))
            self.bot.db_connection.commit()
        await interaction.response.send_message(f"✅ Playlist **{name}** created.")

    @playlist_group.command(name="add", description="Add a song to a playlist")
    async def playlist_add(self, interaction: discord.Interaction, name: str, song: str):
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db_lock:
            cur = self.bot.db_connection.cursor()
            cur.execute("SELECT id FROM playlists WHERE user_id=? AND guild_id=? AND name=?", (interaction.user.id, interaction.guild_id, name))
            row = cur.fetchone()
            if not row:
                await interaction.followup.send("Playlist not found.", ephemeral=True)
                return
            playlist_id = row[0]
        info = await asyncio.to_thread(self.ytdl.extract_info, song, download=False)
        if info is None:
            await interaction.followup.send("Could not add that song.", ephemeral=True)
            return
        track = self._info_to_track(info, requester=interaction.user)
        async with self.bot.db_lock:
            cur = self.bot.db_connection.cursor()
            cur.execute(
                "INSERT INTO playlist_songs (playlist_id, song_title, song_url, duration) VALUES (?, ?, ?, ?)",
                (playlist_id, track.safe_title, track.webpage_url, track.duration),
            )
            self.bot.db_connection.commit()
        await interaction.followup.send(f"Added **{track.safe_title}** to **{name}**.", ephemeral=True)

    @playlist_group.command(name="remove", description="Remove a track from a playlist")
    async def playlist_remove(self, interaction: discord.Interaction, name: str, position: int):
        async with self.bot.db_lock:
            cur = self.bot.db_connection.cursor()
            cur.execute("SELECT id FROM playlists WHERE user_id=? AND guild_id=? AND name=?", (interaction.user.id, interaction.guild_id, name))
            row = cur.fetchone()
            if not row:
                await interaction.response.send_message("Playlist not found.", ephemeral=True)
                return
            playlist_id = row[0]
            cur.execute("SELECT id, song_title FROM playlist_songs WHERE playlist_id=? ORDER BY id", (playlist_id,))
            songs = cur.fetchall()
            if position < 1 or position > len(songs):
                await interaction.response.send_message("Invalid position.", ephemeral=True)
                return
            song_id, title = songs[position - 1]
            cur.execute("DELETE FROM playlist_songs WHERE id=?", (song_id,))
            self.bot.db_connection.commit()
        await interaction.response.send_message(f"Removed **{title}** from **{name}**.")

    @playlist_group.command(name="play", description="Play a saved playlist")
    async def playlist_play(self, interaction: discord.Interaction, name: str):
        channel = await self.ensure_voice(interaction)
        player = self.get_player(interaction.guild)
        await player.connect(channel)
        async with self.bot.db_lock:
            cur = self.bot.db_connection.cursor()
            cur.execute("SELECT id FROM playlists WHERE user_id=? AND guild_id=? AND name=?", (interaction.user.id, interaction.guild_id, name))
            row = cur.fetchone()
            if not row:
                await interaction.response.send_message("Playlist not found.", ephemeral=True)
                return
            playlist_id = row[0]
            cur.execute("SELECT song_title, song_url, duration FROM playlist_songs WHERE playlist_id=? ORDER BY id", (playlist_id,))
            songs = cur.fetchall()
        added = 0
        for title, url, duration in songs:
            if duration and duration > MusicConfig.MAX_SONG_DURATION:
                continue
            track = Track(title=title, url=url, webpage_url=url, duration=duration or 0, thumbnail=None, uploader=None, requester=interaction.user)
            await player.enqueue(track)
            added += 1
            if player.queue.qsize() + len(player.queue_list) >= MusicConfig.MAX_QUEUE_SIZE:
                break
        await interaction.response.send_message(f"Queued {added} tracks from **{name}**.")

    @playlist_group.command(name="list", description="List your playlists")
    async def playlist_list(self, interaction: discord.Interaction):
        async with self.bot.db_lock:
            cur = self.bot.db_connection.cursor()
            cur.execute("SELECT name, created_at FROM playlists WHERE user_id=? AND guild_id=?", (interaction.user.id, interaction.guild_id))
            rows = cur.fetchall()
        if not rows:
            await interaction.response.send_message("You have no playlists.", ephemeral=True)
            return
        lines = [f"• {name} (created {created_at})" for name, created_at in rows]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @playlist_group.command(name="delete", description="Delete a playlist")
    async def playlist_delete(self, interaction: discord.Interaction, name: str):
        async with self.bot.db_lock:
            cur = self.bot.db_connection.cursor()
            cur.execute("SELECT id FROM playlists WHERE user_id=? AND guild_id=? AND name=?", (interaction.user.id, interaction.guild_id, name))
            row = cur.fetchone()
            if not row:
                await interaction.response.send_message("Playlist not found.", ephemeral=True)
                return
            pid = row[0]
            cur.execute("DELETE FROM playlist_songs WHERE playlist_id=?", (pid,))
            cur.execute("DELETE FROM playlists WHERE id=?", (pid,))
            self.bot.db_connection.commit()
        await interaction.response.send_message(f"Deleted playlist **{name}**.")

    @radio_group.command(name="setup", description="Set a radio voice channel")
    async def radio_setup(self, interaction: discord.Interaction, voice_channel: discord.VoiceChannel):
        async with self.bot.db_lock:
            cur = self.bot.db_connection.cursor()
            cur.execute("INSERT OR REPLACE INTO radio_channels (guild_id, voice_channel_id, enabled) VALUES (?, ?, 1)", (interaction.guild_id, voice_channel.id))
            self.bot.db_connection.commit()
        await interaction.response.send_message(f"Radio channel set to {voice_channel.mention}.")
        await self.start_radio(interaction.guild)

    @radio_group.command(name="add", description="Add a radio stream URL")
    async def radio_add(self, interaction: discord.Interaction, url: str, name: str):
        async with self.bot.db_lock:
            cur = self.bot.db_connection.cursor()
            cur.execute("INSERT INTO radio_streams (guild_id, stream_url, stream_name) VALUES (?, ?, ?)", (interaction.guild_id, url, name))
            self.bot.db_connection.commit()
        await interaction.response.send_message("Added radio stream.")

    @radio_group.command(name="list", description="List radio streams")
    async def radio_list(self, interaction: discord.Interaction):
        async with self.bot.db_lock:
            cur = self.bot.db_connection.cursor()
            cur.execute("SELECT id, stream_name, stream_url FROM radio_streams WHERE guild_id=?", (interaction.guild_id,))
            rows = cur.fetchall()
        if not rows:
            await interaction.response.send_message("No radio streams.", ephemeral=True)
            return
        lines = [f"`{rid}` • {name} — {url}" for rid, name, url in rows]
        await interaction.response.send_message("\n".join(lines))

    @radio_group.command(name="remove", description="Remove a radio stream")
    async def radio_remove(self, interaction: discord.Interaction, stream_id: int):
        async with self.bot.db_lock:
            cur = self.bot.db_connection.cursor()
            cur.execute("DELETE FROM radio_streams WHERE id=? AND guild_id=?", (stream_id, interaction.guild_id))
            self.bot.db_connection.commit()
        await interaction.response.send_message("Removed radio stream if it existed.")

    async def start_radio(self, guild: discord.Guild):
        if guild.id in self.radio_tasks and not self.radio_tasks[guild.id].done():
            return

        async def radio_loop():
            while True:
                try:
                    async with self.bot.db_lock:
                        cur = self.bot.db_connection.cursor()
                        cur.execute("SELECT voice_channel_id, enabled FROM radio_channels WHERE guild_id=?", (guild.id,))
                        row = cur.fetchone()
                        if not row or not row[1]:
                            await asyncio.sleep(30)
                            continue
                        voice_channel_id = row[0]
                        cur.execute("SELECT stream_url FROM radio_streams WHERE guild_id=?", (guild.id,))
                        streams = [r[0] for r in cur.fetchall()]
                    if not streams:
                        await asyncio.sleep(30)
                        continue
                    channel = guild.get_channel(voice_channel_id)
                    if not channel or not isinstance(channel, discord.VoiceChannel):
                        await asyncio.sleep(30)
                        continue
                    player = self.get_player(guild)
                    await player.connect(channel)
                    for url in streams:
                        if not player.voice or not player.voice.is_connected():
                            break
                        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS_BASE)
                        player.voice.play(source)
                        while player.voice.is_playing():
                            await asyncio.sleep(5)
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(10)

        self.radio_tasks[guild.id] = asyncio.create_task(radio_loop())

    # Lyrics
    @app_commands.command(name="lyrics", description="Fetch song lyrics")
    async def lyrics(self, interaction: discord.Interaction, query: str):
        if lyricsgenius is None:
            await interaction.response.send_message("Lyrics library not installed.", ephemeral=True)
            return
        token = None
        try:
            from config import BotConfig  # type: ignore

            token = getattr(BotConfig, "GENIUS_TOKEN", None)
        except Exception:
            token = None
        if not token:
            await interaction.response.send_message("No Genius API token configured.", ephemeral=True)
            return
        self.genius_client = self.genius_client or lyricsgenius.Genius(token, timeout=5, retries=1)
        await interaction.response.defer()
        song = await asyncio.to_thread(self.genius_client.search_song, query)
        if not song:
            await interaction.followup.send("No lyrics found.")
            return
        text = song.lyrics
        if len(text) > 4000:
            text = text[:4000] + "..."
        embed = discord.Embed(title=f"Lyrics: {song.title}", description=f"```{text}```", color=discord.Color.green())
        await interaction.followup.send(embed=embed)

    @play.error
    @skip.error
    @pause.error
    @resume.error
    @stop.error
    @queue.error
    @remove.error
    @shuffle.error
    @loop.error
    @nowplaying.error
    @volume.error
    async def music_error(self, interaction: discord.Interaction, error: Exception):
        msg = "❌ " + (str(error) or "Something went wrong")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


class SearchSelectView(discord.ui.View):
    def __init__(self, cog: MusicCog, user: discord.User, results: List[Track], player: MusicPlayer):
        super().__init__(timeout=60)
        self.cog = cog
        self.user = user
        self.results = results
        self.player = player
        options = [discord.SelectOption(label=t.safe_title[:100], description=cog.format_duration(t.duration), value=str(idx)) for idx, t in enumerate(results)]
        self.select = discord.ui.Select(placeholder="Select a track", options=options, min_values=1, max_values=1)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user.id

    async def select_callback(self, interaction: discord.Interaction):
        idx = int(self.select.values[0])
        track = self.results[idx]
        track.requester = interaction.user
        await self.player.enqueue(track)
        await interaction.response.edit_message(content=f"✅ Added **{track.safe_title}**", embed=None, view=None)


class MusicControlView(discord.ui.View):
    def __init__(self, cog: MusicCog, user: discord.User, player: MusicPlayer):
        super().__init__(timeout=120)
        self.cog = cog
        self.user = user
        self.player = player

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only voice channel members can control
        return interaction.user.voice and interaction.user.voice.channel and self.player.voice and interaction.user.voice.channel.id == self.player.voice.channel.id

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary)
    async def play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.player.voice and self.player.voice.is_playing():
            await self.player.pause()
            await interaction.response.send_message("Paused.", ephemeral=True)
        else:
            await self.player.resume()
            await interaction.response.send_message("Resumed.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.player.skip()
        await interaction.response.send_message("Skipped.", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        mode = self.player.cycle_loop()
        label = {LoopMode.NONE: "off", LoopMode.ONE: "single", LoopMode.QUEUE: "queue"}[mode]
        await interaction.response.send_message(f"Loop set to {label}.", ephemeral=True)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.shuffle()
        await interaction.response.send_message("Shuffled queue.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.player.stop()
        await interaction.response.send_message("Stopped.", ephemeral=True)
