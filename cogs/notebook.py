import discord
import os
import aiohttp
import asyncio
from discord.ext import commands
from utils.pdf_tools import extract_text_from_pdf, save_temp_pdf
from google import genai
from dotenv import load_dotenv
# Vi legger til logging for systemoversikt
from utils.minne import lagre

load_dotenv()

class Notebook(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_notebooks = {} # {channel_id: {"session": chat, "navn": str}}

    async def start_gemini_session(self, bok_tekst):
        """Starter en chat-sesjon med boka i minnet via Google Cloud"""
        api_key = os.getenv("GEMINI_KEY")
        client = genai.Client(api_key=api_key)
        
        # Vi bruker Flash for hastighet og kostnadseffektivitet
        chat = client.chats.create(model="gemini-1.5-flash")
        
        initial_prompt = (
            f"Du er en ekspert på følgende dokument. "
            f"Svar på alle spørsmål basert KUN på denne teksten. Svar alltid på NORSK.\n\n"
            f"--- START DOKUMENT ---\n{bok_tekst}\n--- SLUTT DOKUMENT ---"
        )
        
        # Vi bruker thread for å ikke blokkere boten mens Gemini laster inn boka
        await asyncio.to_thread(chat.send_message, initial_prompt)
        return chat

    @commands.command(name="notebook")
    async def notebook_command(self, ctx):
        """Last opp en PDF for å starte en Notebook-sesjon."""
        if not ctx.message.attachments:
            return await ctx.send("📎 Legg ved en PDF-fil i meldingen!")

        vedlegg = ctx.message.attachments[0]
        if not vedlegg.filename.endswith(".pdf"):
            return await ctx.send("⛔ Beklager, jeg støtter bare PDF-filer for øyeblikket.")

        status_msg = await ctx.send(f"📚 Analyserer **{vedlegg.filename}**... Dette kan ta litt tid.")

        try:
            fil_data = await vedlegg.read()
            # Bruker dine eksisterende verktøy i utils/
            temp_path = save_temp_pdf(fil_data, f"temp_{ctx.channel.id}.pdf")
            
            # Ekstraherer tekst lokalt før vi sender til skyen
            bok_tekst = await asyncio.to_thread(extract_text_from_pdf, temp_path)
            
            if os.path.exists(temp_path):
                os.remove(temp_path)

            if not bok_tekst or len(bok_tekst.strip()) < 10:
                return await status_msg.edit(content="❌ PDF-en ser ut til å være tom eller består kun av bilder.")

            # Starter sesjonen
            chat_session = await self.start_gemini_session(bok_tekst)
            
            self.active_notebooks[ctx.channel.id] = {
                "session": chat_session,
                "navn": vedlegg.filename
            }
            
            # LOGG TIL SYSTEMET (NYTT)
            lagre(
                tekst=f"Startet Notebook-sesjon: {vedlegg.filename} ({len(bok_tekst)} tegn)",
                user=ctx.author.name,
                guild_id=ctx.guild.id,
                channel_id=ctx.channel.id,
                kategori="Notebook",
                kilde="Kommando"
            )

            await status_msg.edit(content=f"✅ **Notebook klar!**\nJeg har lest **{vedlegg.filename}** ({len(bok_tekst)} tegn).\nBruk `!spør [ditt spørsmål]` for å snakke med dokumentet.")

        except Exception as e:
            await status_msg.edit(content=f"❌ Feil ved opprettelse av Notebook: {e}")

    @commands.command(name="spør")
    async def spor_command(self, ctx, *, spørsmål: str):
        """Spør den aktive boka i kanalen."""
        if ctx.channel.id not in self.active_notebooks:
            return await ctx.send("❌ Ingen aktiv Notebook her. Last opp en fil med `!notebook` først.")

        data = self.active_notebooks[ctx.channel.id]
        chat = data["session"]

        async with ctx.typing():
            try:
                # Vi bruker to_thread her også for å unngå 'blocking'
                response = await asyncio.to_thread(chat.send_message, spørsmål)
                svar_tekst = response.text

                # Bruker din smarte send-logikk (hvis du har den tilgjengelig, ellers enkel splitt)
                if len(svar_tekst) > 1950:
                    for i in range(0, len(svar_tekst), 1950):
                        await ctx.send(svar_tekst[i:i+1950])
                else:
                    await ctx.send(f"📘 **Fra {data['navn']}:**\n{svar_tekst}")
                    
            except Exception as e:
                await ctx.send(f"⚠️ Gemini støtte på et problem: {e}")

    @commands.command(name="lukk_notebook")
    async def lukk_command(self, ctx):
        """Avslutter Notebook-sesjonen i kanalen."""
        if ctx.channel.id in self.active_notebooks:
            del self.active_notebooks[ctx.channel.id]
            await ctx.send("🗑️ Notebook-sesjonen er avsluttet og minnet er slettet.")
        else:
            await ctx.send("Det er ingen aktiv sesjon å lukke.")

async def setup(bot):
    await bot.add_cog(Notebook(bot))