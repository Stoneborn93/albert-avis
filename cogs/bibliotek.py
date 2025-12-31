import discord
import os
import asyncio
from discord.ext import commands
from utils.pdf_tools import extract_text_from_pdf, save_temp_pdf
from utils.minne import lagre, søk_i_kilde
from utils.ai_motor import ask_mistral

BOOKS_DIR = "./data/boker"

class Bibliotek(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not os.path.exists(BOOKS_DIR): os.makedirs(BOOKS_DIR)

    def chunk_text(self, text, chunk_size=1500):
        """
        Deler tekst. Vi øker størrelsen litt siden Markdown tar mer plass.
        Vi prøver å splitte ved linjeskift (\n) for å ikke ødelegge tabeller.
        """
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end >= len(text):
                chunks.append(text[start:])
                break
            
            # Prøv å finn nærmeste linjeskift for å ikke kutte midt i en tabell
            newline = text.rfind('\n', start, end)
            if newline != -1 and newline > start:
                end = newline
            
            chunks.append(text[start:end])
            start = end
        return chunks

    async def prosesser_bok(self, ctx, filsti, visningsnavn):
        """Kjernen i læringen"""
        status_msg = await ctx.send(f"🧠 Konverterer **{visningsnavn}** til AI-vennlig format (Markdown)...")
        
        try:
            # 1. Konverter PDF til Markdown (Bevarer tabeller!)
            markdown_tekst = extract_text_from_pdf(filsti)
            
            if not markdown_tekst:
                await status_msg.edit(content="❌ Feil: Kunne ikke lese tekst. Er PDF-en et bilde?")
                return

            # 2. Del opp
            biter = self.chunk_text(markdown_tekst)
            totalt = len(biter)
            
            await status_msg.edit(content=f"🧩 Fant {len(markdown_tekst)} tegn. Lagrer {totalt} biter i biblioteket...")

            # 3. Lagre i ChromaDB (Nå med server-isolering)
            for i, bit in enumerate(biter):
                # VIKTIG: Bruker den nye lagre()-syntaksen
                lagre(
                    tekst=bit, 
                    user="Bibliotekar", 
                    guild_id=ctx.guild.id, 
                    channel_id=ctx.channel.id, 
                    kategori="Fakta",  # Bøker er fakta, ikke RPG
                    kilde=visningsnavn
                )
                if i % 10 == 0: await asyncio.sleep(0.01) # Pause for CPU

            await status_msg.edit(content=f"✅ Ferdig! **{visningsnavn}** er lagret med tabeller og struktur intakt.")

        except Exception as e:
            await status_msg.edit(content=f"❌ Feil: {e}")

    # --- KOMMANDO 1: LAST OPP VIA DISCORD ---
    @commands.command()
    async def lær_pdf(self, ctx):
        if not ctx.message.attachments:
            await ctx.send("📎 Legg ved en PDF!")
            return
        
        vedlegg = ctx.message.attachments[0]
        if not vedlegg.filename.endswith(".pdf"): return
        
        # Vi må lagre filen midlertidig for at verktøyet skal virke
        fil_data = await vedlegg.read()
        temp_path = save_temp_pdf(fil_data, vedlegg.filename)
        
        await self.prosesser_bok(ctx, temp_path, vedlegg.filename)
        
        # Rydd opp temp-filen etterpå
        try: os.remove(temp_path)
        except: pass

    # --- KOMMANDO 2: LÆR FRA LOKAL MAPPE (Best for store filer) ---
    @commands.command()
    async def lær_lokal(self, ctx, *, filnavn: str):
        full_sti = os.path.join(BOOKS_DIR, filnavn)
        
        if not os.path.exists(full_sti):
            await ctx.send(f"❌ Finner ikke `{filnavn}` i `data/boker`.")
            return

        await self.prosesser_bok(ctx, full_sti, filnavn)

    # --- SPØR OM BOKEN ---
    @commands.command()
    async def bok(self, ctx, filnavn: str, *, spørsmål: str):
        async with ctx.typing():
            # Søk i databasen (Nå med server-isolering)
            funn = søk_i_kilde(spørsmål, filnavn, guild_id=ctx.guild.id, antall=6)
            
            if not funn:
                await ctx.send(f"Fant ingen svar i **{filnavn}**. (Husk nøyaktig filnavn).")
                return

            kontekst = "\n---\n".join(funn)
            
            # Instruks til Mistral om å lese tabeller
            system = (
                "Du er en bibliotekar. Du har fått utdrag fra en bok i Markdown-format. "
                "Dette betyr at tabeller ser slik ut: '| Header | Verdi |'. "
                "Les tabellene nøye for å finne svaret. Svar KUN basert på teksten."
            )
            
            svar = await ask_mistral(spørsmål, context=[kontekst], system_prompt=system)
            await ctx.send(f"📘 **{filnavn}:**\n{svar}")

async def setup(bot):
    await bot.add_cog(Bibliotek(bot))