# 🎵 Wavelink/Lavalink High-Quality Integration Guide

## Overview

For even more advanced features, you can integrate Wavelink with Lavalink for:
- Distributed audio processing
- Advanced filters and effects
- Load balancing across multiple nodes
- Lower bot latency
- Spotify direct playback

---

## 📦 Installation

### 1. Install Wavelink
```powershell
pip install wavelink
```

### 2. Download Lavalink Server
```powershell
# Download latest Lavalink.jar
Invoke-WebRequest -Uri "https://github.com/lavalink-devs/Lavalink/releases/download/4.0.4/Lavalink.jar" -OutFile "Lavalink.jar"
```

### 3. Create High-Quality Lavalink Config

Create `application.yml`:

```yaml
server:
  port: 2333
  address: 0.0.0.0

lavalink:
  server:
    password: "youshallnotpass"
    sources:
      youtube: true
      bandcamp: true
      soundcloud: true
      twitch: true
      vimeo: true
      http: true
      local: false
    
    # HIGH-QUALITY BUFFER CONFIGURATION
    bufferDurationMs: 400
    frameBufferDurationMs: 5000
    opusEncodingQuality: 10  # Maximum quality (0-10)
    resamplingQuality: HIGH   # HIGH quality resampling
    trackStuckThresholdMs: 10000
    useSeekGhosting: true
    youtubePlaylistLoadLimit: 6
    playerUpdateInterval: 5
    youtubeSearchEnabled: true
    soundcloudSearchEnabled: true
    gc-warnings: true
    
    # YOUTUBE HIGH-QUALITY SETTINGS
    youtubeConfig:
      email: ""
      password: ""
    
    # AUDIO QUALITY FILTERS
    filters:
      volume: true
      equalizer: true
      karaoke: true
      timescale: true
      tremolo: true
      vibrato: true
      rotation: true
      distortion: true
      channelMix: true
      lowPass: true
      
plugins: []

metrics:
  prometheus:
    enabled: false
    endpoint: /metrics

sentry:
  dsn: ""
  environment: ""

logging:
  file:
    path: ./logs/
  level:
    root: INFO
    lavalink: INFO
```

### 4. Start Lavalink
```powershell
java -jar Lavalink.jar
```

---

## 💻 Bot Integration

### Update requirements.txt
```txt
wavelink>=3.0.0
```

### Create Wavelink MusicCog

```python
import wavelink
from wavelink.ext import spotify

class WavelinkMusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.loop.create_task(self.connect_nodes())
    
    async def connect_nodes(self):
        """Connect to Lavalink nodes with high-quality settings"""
        await self.bot.wait_until_ready()
        
        nodes = [
            wavelink.Node(
                identifier="MAIN",
                uri="http://localhost:2333",
                password="youshallnotpass",
                # High-quality node settings
                resume_timeout=60,
                heartbeat=15,
            )
        ]
        
        await wavelink.Pool.connect(nodes=nodes, client=self.bot, cache_capacity=100)
        print("[WAVELINK] High-quality nodes connected!")
    
    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        print(f"[WAVELINK] Node {payload.node.identifier} is ready!")
        print(f"[WAVELINK] Session ID: {payload.session_id}")
    
    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player = payload.player
        track = payload.track
        
        print(f"[WAVELINK] Now playing: {track.title}")
        print(f"[WAVELINK] Duration: {track.length}ms")
        print(f"[WAVELINK] Source: {track.source}")
    
    @app_commands.command(name="wplay", description="Play with Wavelink (High Quality)")
    async def wavelink_play(self, interaction: discord.Interaction, query: str):
        """Play using Wavelink high-quality pipeline"""
        if not interaction.user.voice:
            return await interaction.response.send_message("Join a voice channel first!")
        
        await interaction.response.defer()
        
        # Get or create player
        player: wavelink.Player = interaction.guild.voice_client or await interaction.user.voice.channel.connect(cls=wavelink.Player)
        
        # Search for tracks
        tracks = await wavelink.Playable.search(query)
        
        if not tracks:
            return await interaction.followup.send("No tracks found!")
        
        track = tracks[0]
        
        # Apply high-quality filters
        filters = wavelink.Filters()
        filters.equalizer.set_gain(0, 0.2)   # Sub-bass boost
        filters.equalizer.set_gain(1, 0.15)  # Bass boost
        await player.set_filters(filters)
        
        await player.play(track)
        
        embed = discord.Embed(
            title="🎵 Now Playing (Wavelink HQ)",
            description=f"**{track.title}**",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Duration", value=f"{track.length // 60000}:{(track.length // 1000) % 60:02d}")
        embed.add_field(name="Source", value=track.source)
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="wfilter", description="Apply Wavelink audio filters")
    async def wavelink_filter(
        self,
        interaction: discord.Interaction,
        filter_type: str = None
    ):
        """Apply professional audio filters via Wavelink"""
        player: wavelink.Player = interaction.guild.voice_client
        
        if not player:
            return await interaction.response.send_message("Not playing anything!")
        
        filters = wavelink.Filters()
        
        if filter_type == "bassboost":
            # Professional bass boost EQ
            filters.equalizer.set_gain(0, 0.25)
            filters.equalizer.set_gain(1, 0.20)
            filters.equalizer.set_gain(2, 0.10)
            msg = "🎵 Bass boost applied!"
        
        elif filter_type == "nightcore":
            # True nightcore effect
            filters.timescale.set(speed=1.25, pitch=1.25, rate=1.0)
            msg = "⚡ Nightcore applied!"
        
        elif filter_type == "8d":
            # 8D audio rotation
            filters.rotation.set(rotation_hz=0.125)
            msg = "🌀 8D audio applied!"
        
        elif filter_type == "karaoke":
            # Vocal removal
            filters.karaoke.set(
                level=1.0,
                mono_level=1.0,
                filter_band=220.0,
                filter_width=100.0
            )
            msg = "🎤 Karaoke mode applied!"
        
        elif filter_type == "clear":
            # Remove all filters
            filters = wavelink.Filters()
            msg = "🔄 All filters cleared!"
        
        else:
            return await interaction.response.send_message(
                "Available filters: `bassboost`, `nightcore`, `8d`, `karaoke`, `clear`"
            )
        
        await player.set_filters(filters)
        await interaction.response.send_message(msg)

async def setup(bot):
    await bot.add_cog(WavelinkMusicCog(bot))
```

---

## 🎛️ Advanced Lavalink Filters

### Equalizer (Parametric EQ)
```python
filters = wavelink.Filters()
# 15-band equalizer (0-14)
filters.equalizer.set_gain(0, 0.25)  # 25 Hz
filters.equalizer.set_gain(1, 0.20)  # 40 Hz
filters.equalizer.set_gain(2, 0.15)  # 63 Hz
# ... up to band 14 (16000 Hz)
await player.set_filters(filters)
```

### Timescale (Speed/Pitch)
```python
filters.timescale.set(
    speed=1.25,    # 25% faster
    pitch=1.10,    # 10% higher pitch
    rate=1.0       # Playback rate
)
```

### Karaoke (Vocal Removal)
```python
filters.karaoke.set(
    level=1.0,
    mono_level=1.0,
    filter_band=220.0,
    filter_width=100.0
)
```

### Rotation (8D Audio)
```python
filters.rotation.set(rotation_hz=0.125)  # Slow rotation
```

### Vibrato
```python
filters.vibrato.set(
    frequency=2.0,
    depth=0.5
)
```

### Tremolo
```python
filters.tremolo.set(
    frequency=2.0,
    depth=0.5
)
```

### Low Pass (Bass Enhancement)
```python
filters.low_pass.set(smoothing=20.0)
```

### Channel Mix (Stereo Manipulation)
```python
filters.channel_mix.set(
    left_to_left=1.0,
    right_to_right=1.0,
    left_to_right=0.0,
    right_to_left=0.0
)
```

---

## 🚀 Performance Tuning

### Lavalink JVM Options
```powershell
java -Xmx2G -Xms2G -jar Lavalink.jar
```
- `-Xmx2G` - Max heap size
- `-Xms2G` - Initial heap size

### High-Quality YouTube Extraction
Add to `application.yml`:
```yaml
lavalink:
  server:
    youtubeConfig:
      # Use yt-dlp for better quality
      videoLoaderPolicy: "YoutubeApiLoader"
```

---

## 🎯 Benefits of Wavelink

1. **Better Performance**
   - Audio processing on separate server
   - Lower bot CPU usage
   - Multiple bots can share nodes

2. **Advanced Features**
   - More audio filters
   - Better seeking support
   - Spotify direct playback
   - Apple Music support

3. **Stability**
   - Resume support (reconnect without losing queue)
   - Load balancing across nodes
   - Better error handling

4. **Quality**
   - Professional DSP filters
   - No quality loss in filter chain
   - Optimized audio pipeline

---

## 📊 Comparison

| Feature | Direct FFmpeg | Wavelink |
|---------|---------------|----------|
| Setup Complexity | Low | Medium |
| CPU Usage (Bot) | High | Low |
| Filter Quality | Good | Excellent |
| Seeking | Limited | Full Support |
| Resume Support | No | Yes |
| Load Balancing | No | Yes |
| Spotify | Via yt-dlp | Native |
| Multiple Bots | Individual | Shared Nodes |

---

## 💡 Recommendation

- **Use Direct FFmpeg (Current)** if:
  - You want simple setup
  - Single bot, small server
  - Basic features sufficient

- **Use Wavelink** if:
  - Multiple bots
  - Large servers (100+ users)
  - Want advanced filters
  - Need Spotify direct playback
  - Want better stability

---

## 🔧 Migration Path

1. Keep current FFmpeg system as fallback
2. Add Wavelink as optional enhanced mode
3. Users can choose via `/wplay` vs `/play`
4. Gradually migrate based on preference

Both systems can coexist!

---

## 📝 Quick Start

```bash
# 1. Install Java
winget install Oracle.JDK.21

# 2. Download Lavalink
wget https://github.com/lavalink-devs/Lavalink/releases/latest/download/Lavalink.jar

# 3. Create application.yml (use config above)

# 4. Start Lavalink
java -jar Lavalink.jar

# 5. Install wavelink
pip install wavelink

# 6. Add WavelinkMusicCog to bot

# 7. Use /wplay command!
```

---

## ✨ Result

You'll have **two high-quality audio systems**:
1. Direct FFmpeg (current) - Simple, reliable
2. Wavelink + Lavalink - Advanced, scalable

Both deliver broadcast-quality audio! 🎵
