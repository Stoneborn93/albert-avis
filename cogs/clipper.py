import discord
import os
import asyncio
from discord.ext import commands
import re
from utils.minne import lagre

# --- KONFIGURASJON ---
TEMP_DIR = "./data/temp_vods"
OUTPUT_DIR = "./data/highlights"

# Ord vi ser etter (Du kan legge til flere her!)
TRIGGER_WORDS = [
    "faen", "helvete", "satan", "jævla", "shit", 
    "jada", "konge", "nydelig", "let's go", "lets go",
    "nei nei", "hjelp", "hahaha", "latter", "clip that",
    "klipp det", "fuck",
]

# Hvor mye tid rundt ordet vil du ha?
CLIP_BEFORE = 40 # Sekunder før ordet sies
CLIP_AFTER = 20   # Sekunder etter ordet sies

class Clipper(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)

    def parse_time(self, time_str):
        """Gjør om '00:01:20,500' til sekunder (float)."""
        try:
            h, m, s_ms = time_str.split(':')
            s, ms = s_ms.split(',')
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
        except Exception as e:
            print(f"Feil ved parsing av tid '{time_str}': {e}")
            return 0.0

    def parse_srt(self, srt_path):
        """Leser SRT og finner tidspunkter med trigger-ord."""
        timestamps = []
        
        if not os.path.exists(srt_path):
            return []

        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Regex for å finne blokker: Nummer -> Tid -> Tekst
        blocks = re.split(r'\n\n', content)
        
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) >= 3:
                tidsserie = lines[1] # "00:00:05,000 --> 00:00:08,000"
                if ' --> ' not in tidsserie: continue
                
                tekst = " ".join(lines[2:]).lower() # Selve teksten
                
                # Sjekk om noen av trigger-ordene er i teksten
                if any(word in tekst for word in TRIGGER_WORDS):
                    start_str = tidsserie.split(' --> ')[0]
                    start_sec = self.parse_time(start_str)
                    timestamps.append((start_sec, tekst))
                    
        return timestamps

    def merge_clips(self, clips):
        """Slår sammen klipp som er veldig nærme hverandre."""
        if not clips: return []
        merged = []
        
        # Sorter basert på tid
        clips.sort(key=lambda x: x[0])
        
        current_start = max(0, clips[0][0] - CLIP_BEFORE)
        current_end = clips[0][0] + CLIP_AFTER
        current_words = [clips[0][1]]

        for i in range(1, len(clips)):
            sec, word = clips[i]
            next_start = max(0, sec - CLIP_BEFORE)
            next_end = sec + CLIP_AFTER
            
            # Hvis starten på neste klipp er før slutten på forrige (overlapp)
            if next_start < current_end:
                current_end = max(current_end, next_end) # Forleng klippet
                if word not in current_words:
                    current_words.append(word)
            else:
                # Lagre det forrige og start nytt
                merged.append((current_start, current_end, ", ".join(current_words)))
                current_start = next_start
                current_end = next_end
                current_words = [word]
                
        merged.append((current_start, current_end, ", ".join(current_words)))
        return merged

    @commands.command()
    async def lag_klipp(self, ctx, filnavn: str = "stream.mp4"):
        """Lager høydepunkter basert på SRT-filen."""
        
        srt_fil = f"{TEMP_DIR}/{filnavn}.srt"
        video_fil = f"{TEMP_DIR}/{filnavn}"
        
        # Sjekk filer
        if not os.path.exists(srt_fil):
            alt_srt = f"{TEMP_DIR}/{filnavn.replace('.mp4', '_clean.wav.srt')}"
            if os.path.exists(alt_srt):
                srt_fil = alt_srt
            else:
                return await ctx.send(f"❌ Finner ikke SRT-fil for `{filnavn}`. Har du transkribert den?")
        
        if not os.path.exists(video_fil):
             return await ctx.send(f"❌ Finner ikke videofilen `{video_fil}`.")

        await ctx.send(f"🕵️ **Leser gjennom teksten og leter etter action...**")
        
        raw_clips = self.parse_srt(srt_fil)
        if not raw_clips:
            return await ctx.send("🤷 Fant ingen trigger-ord i teksten.")
            
        final_clips = self.merge_clips(raw_clips)
        
        await ctx.send(f"🎬 Fant **{len(final_clips)}** potensielle klipp! Starter klipping med FFmpeg...")
        
        created_files = []
        for i, (start, end, words) in enumerate(final_clips):
            duration = end - start
            # Rens filnavn for ulovlige tegn
            safe_words = re.sub(r'[^\w\s-]', '', words[:30]).strip().replace(" ", "_")
            ut_fil = f"{OUTPUT_DIR}/klipp_{i+1}_{safe_words}.mp4"
            
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", video_fil,
                "-t", str(duration),
                "-c", "copy", 
                ut_fil
            ]
            
            process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await process.communicate()
            
            if os.path.exists(ut_fil):
                created_files.append(ut_fil)

        if created_files:
            # RETTET: Bruker navngitte argumenter for å treffe riktig i den nye minne.py
            lagre(
                tekst=f"Genererte {len(created_files)} høydepunkter fra {filnavn}", 
                user="System", 
                guild_id=ctx.guild.id, 
                channel_id=ctx.channel.id, 
                kategori="Klipp", 
                kilde="Clipper"
            )
            await ctx.send(f"✅ **Ferdig!** Har laget {len(created_files)} klipp i mappen `{OUTPUT_DIR}`.")
        else:
            await ctx.send("❌ Klippingen feilet. Sjekk om FFmpeg er installert.")

async def setup(bot):
    await bot.add_cog(Clipper(bot))