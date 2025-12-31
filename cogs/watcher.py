import discord
import os
import asyncio
import time
from discord.ext import commands, tasks
from utils.minne import lagre

# --- KONFIGURASJON ---
WATCH_DIR = "./data/temp_vods"
TARGET_FILE = "stream.mp4"
CHANNEL_ID = 1445819040030527612 

# Vi gjetter at filen blir ca 11 GB for å lage progress-bar
ESTIMATED_TOTAL_GB = 11.0 
ESTIMATED_TOTAL_BYTES = ESTIMATED_TOTAL_GB * 1024**3

class FileWatcher(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.file_path = os.path.join(WATCH_DIR, TARGET_FILE)
        self.progress_msg = None 
        self.last_size = 0
        self.upload_finished = False
        # VIKTIG: Vi starter IKKE loopen her lenger, men i cog_load under.

    async def cog_load(self):
        """Kjøres automatisk når boten er klar."""
        print("[FileWatcher] 👀 Filovervåker lastet. Starter loop...")
        self.watch_loop.start()

    def cog_unload(self):
        self.watch_loop.cancel()

    def format_size(self, size_bytes):
        if size_bytes > 1024**3:
            return f"{size_bytes / (1024**3):.2f} GB"
        else:
            return f"{size_bytes / (1024**2):.1f} MB"

    def make_progress_bar(self, percent, length=15):
        filled_length = int(length * percent // 100)
        bar = "█" * filled_length + "░" * (length - filled_length)
        return f"[{bar}]"

    @tasks.loop(seconds=10) 
    async def watch_loop(self):
        if not self.bot.is_ready(): return

        # SJEKK 1: Er filen der i det hele tatt?
        file_exists = os.path.exists(self.file_path)
        
        if not file_exists:
            self.progress_msg = None
            self.last_size = 0
            self.upload_finished = False
            return

        # SJEKK 2: Filen er der
        if self.upload_finished: return

        try:
            current_size = os.path.getsize(self.file_path)
            
            # Beregn fart og ETA
            size_diff = current_size - self.last_size
            speed_bps = size_diff / 10.0
            speed_mb = speed_bps / (1024**2)
            percent = min(100, (current_size / ESTIMATED_TOTAL_BYTES) * 100)
            
            if speed_bps > 0:
                bytes_remaining = max(0, ESTIMATED_TOTAL_BYTES - current_size)
                seconds_left = int(bytes_remaining / speed_bps)
                m, s = divmod(seconds_left, 60)
                h, m = divmod(m, 60)
                eta_str = f"{h}t {m}m" if h > 0 else f"{m}m {s}s"
            else:
                eta_str = "Venter på data..."

            # A: Oppstart av overvåkning
            if self.progress_msg is None:
                channel = self.bot.get_channel(CHANNEL_ID)
                if channel:
                    print(f"🚀 Opplasting startet: {TARGET_FILE}")
                    self.progress_msg = await channel.send(
                        f"📥 **Mottar fil: `{TARGET_FILE}`**\n"
                        f"Starter overvåkning... 📡"
                    )

            # B: Oppdaterer fremdrift (kun hvis filstørrelsen har endret seg)
            elif current_size > self.last_size:
                bar = self.make_progress_bar(percent)
                status_text = (
                    f"📥 **Laster opp: `{TARGET_FILE}`**\n"
                    f"{bar} **{percent:.1f}%**\n"
                    f"📦 Størrelse: `{self.format_size(current_size)}` / ~{ESTIMATED_TOTAL_GB} GB\n"
                    f"🚀 Fart: `{speed_mb:.1f} MB/s`\n"
                    f"⏱️ ETA: `{eta_str}`"
                )
                try:
                    await self.progress_msg.edit(content=status_text)
                except:
                    pass # Melding kan ha blitt manuelt slettet

            # C: Ferdig registrert (størrelsen har stabilisert seg)
            elif current_size == self.last_size and current_size > 0:
                bar = self.make_progress_bar(100)
                final_text = (
                    f"✅ **Opplasting Fullført!**\n"
                    f"📁 Fil: `{TARGET_FILE}`\n"
                    f"📦 Endelig størrelse: `{self.format_size(current_size)}`\n"
                    f"Klar for transkribering! Kjør: `!transkriber_lokal` 🚀\n"
                    f"🗑️ *(Denne meldingen slettes automatisk om 1 time)*"
                )
                try:
                    await self.progress_msg.edit(content=final_text)
                    # Sletter meldingen om 1 time
                    await self.progress_msg.delete(delay=3600)
                except:
                    pass
                
                # Loggfør i Albert sitt minne (OPPDATERT)
                try:
                    lagre(
                        tekst=f"Filoverføring fullført: {TARGET_FILE} ({self.format_size(current_size)})", 
                        user="System", 
                        guild_id="LOCAL", 
                        channel_id="LOCAL", 
                        kategori="FileWatcher", 
                        kilde="Auto"
                    )
                except: pass
                
                print(f"✅ Fil ferdig! Melding slettes om 1t.")
                self.upload_finished = True 

            self.last_size = current_size

        except Exception as e:
            print(f"⚠️ Watcher Error: {e}")

    @watch_loop.before_loop
    async def before_watch_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(FileWatcher(bot))