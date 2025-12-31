import discord
import os
import asyncio
from discord.ext import commands
from pydub import AudioSegment
from pydub.silence import split_on_silence
from utils.minne import lagre

# --- KONFIGURASJON ---
TEMP_DIR = "./data/temp_vods"
UT_MAPPE_BASE = "./data/temp_vods/dataset_ready"

class KlippLyd(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_jobs = set()
        # Sikrer at datamapper eksisterer ved oppstart
        if not os.path.exists(TEMP_DIR): os.makedirs(TEMP_DIR)

    # --- SELVE JOBBEN (Kjøres i bakgrunnen) ---
    def _do_clipping_job(self, input_fil, ut_mappe, min_silence, silence_thresh):
        """Tung prosessering av lydfilen."""
        if not os.path.exists(input_fil):
            return f"❌ Finner ikke filen: {input_fil}"

        if not os.path.exists(ut_mappe):
            os.makedirs(ut_mappe)

        try:
            lyd = AudioSegment.from_wav(input_fil)
        except Exception as e:
            return f"❌ Feil ved lesing av lydfil: {e}"

        # Deler opp basert på stillhet
        chunks = split_on_silence(
            lyd, 
            min_silence_len=min_silence,
            silence_thresh=silence_thresh,
            keep_silence=150
        )

        lagret_antall = 0
        skipped_antall = 0

        for i, chunk in enumerate(chunks):
            lengde_ms = len(chunk)
            # Vi vil bare ha setninger, ikke støy eller hele taler
            if lengde_ms < 1000 or lengde_ms > 15000:
                skipped_antall += 1
                continue
                
            filnavn = os.path.join(ut_mappe, f"klipp_{lagret_antall:04d}.wav")
            try:
                # Standardiserer til Mono/44.1kHz for AI-trening
                chunk.set_channels(1).set_frame_rate(44100).export(filnavn, format="wav")
                lagret_antall += 1
            except:
                continue

        return {
            "antall": lagret_antall,
            "skipped": skipped_antall,
            "mappe": ut_mappe,
            "lengde_sek": len(lyd)/1000
        }

    # --- KOMMANDOEN ---
    @commands.command(name="klipp_dataset.wav", aliases=["klipp"])
    async def klipp_dataset(self, ctx, filnavn: str = "dataset.wav"):
        """Deler opp en wav-fil i mindre biter basert på stillhet."""
        full_sti = os.path.join(TEMP_DIR, filnavn)
        
        if filnavn in self.active_jobs:
            return await ctx.send("✋ Jeg jobber allerede med denne filen!")
        
        self.active_jobs.add(filnavn)
        status_msg = await ctx.send(f"✂️ **Starter oppdeling av `{filnavn}`...**\nJobber i bakgrunnen for å beskytte CPU.")

        # Kjører i tråd for å unngå 'Blocking' på mini-PC
        resultat = await asyncio.to_thread(
            self._do_clipping_job, 
            input_fil=full_sti, 
            ut_mappe=UT_MAPPE_BASE,
            min_silence=500,     # Krever 0.5 sekunder stillhet
            silence_thresh=-40   # Grense for hva som regnes som lyd
        )

        self.active_jobs.remove(filnavn)

        if isinstance(resultat, str):
            await status_msg.edit(content=resultat)
        else:
            embed = discord.Embed(title="✂️ Lydklipping Ferdig!", color=discord.Color.gold())
            embed.add_field(name="Filer opprettet", value=str(resultat['antall']), inline=True)
            embed.add_field(name="Forkastet (for kort/lang)", value=str(resultat['skipped']), inline=True)
            embed.add_field(name="Original lengde", value=f"{resultat['lengde_sek']:.1f}s", inline=False)
            embed.add_field(name="Lagret i", value=f"`{resultat['mappe']}`", inline=False)
            embed.set_footer(text="Datasettet er nå klart!")
            
            # Lagrer hendelsen i botens minne (OPPDATERT)
            lagre(
                tekst=f"Lyd-klipping fullført: {resultat['antall']} klipp fra {filnavn}", 
                user="System", 
                guild_id=ctx.guild.id, 
                channel_id=ctx.channel.id, 
                kategori="AudioWorker", 
                kilde="Kommando"
            )
            
            await status_msg.delete()
            await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(KlippLyd(bot))