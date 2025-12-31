import discord
import os
import random
from datetime import datetime, time
from zoneinfo import ZoneInfo
from discord.ext import commands, tasks
from utils.ai_motor import ask_gemini, generate_and_save_image
from utils.database import (
    set_quiz_state, get_quiz_state, add_quiz_score, 
    log_quiz_message, get_active_quiz_messages, clear_quiz_messages
)
# NYTT: Logging til systemet
from utils.minne import lagre
from difflib import SequenceMatcher

QUIZ_CHANNEL_NAME = "daglig-quiz"
BILDE_FILSTI = "./data/dagens_quiz.png"

# Sjekk at mappen finnes
if not os.path.exists("./data"):
    os.makedirs("./data")

FALLBACK_QUIZ = [
    ("Super Mario", "Spill", "A short plumber with a red hat and mustache jumping"),
    ("Batman", "Film", "A dark superhero with bat ears standing on a rooftop at night"),
    ("Ringenes Herre", "Film", "A gold ring with glowing elvish text in fire"),
    ("Minecraft", "Spill", "A green pixelated exploding creature in a blocky world"),
    ("Titanic", "Film", "A giant ship sinking in icy water at night")
]

class Quiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # VIKTIG: Vi starter IKKE loopen her, men i cog_load under.

    async def cog_load(self):
        """Kjøres automatisk når boten laster modulen."""
        print("[Quiz] 🧠 Quiz-modul lastet. Starter timer...")
        self.daily_quiz.start()

    def cog_unload(self):
        self.daily_quiz.cancel()

    async def avslutt_gammel_quiz(self):
        """Redigerer gamle meldinger for å vise fasit"""
        state = await get_quiz_state()
        if not state: return 
        
        gammelt_svar = state[0]
        meldinger = await get_active_quiz_messages()
        
        for guild_id, channel_id, message_id in meldinger:
            try:
                channel = self.bot.get_channel(int(channel_id))
                if channel:
                    msg = await channel.fetch_message(int(message_id))
                    embed = discord.Embed(
                        title="🛑 QUIZ AVSLUTTET",
                        description=f"Fasiten var: **{gammelt_svar}**",
                        color=discord.Color.red()
                    )
                    # Fjerner bildet og legger til fasit-embed
                    await msg.edit(content=None, embed=embed, attachments=[])
            except Exception as e: 
                print(f"Kunne ikke redigere gammel melding: {e}")
        
        await clear_quiz_messages()

    async def lag_ny_quiz(self):
        await self.avslutt_gammel_quiz()

        print("--- STARTER NY QUIZ GENERERING ---")
        prompt = (
            "Oppgave: Velg en TILFELDIG kjent film, TV-serie, spill eller sted. "
            "Ikke velg Titanic. Prøv å variere. "
            "Format: TITTEL|KATEGORI|BILDEPROMPT (på engelsk for bildegeneratoren)"
        )
        
        try:
            res = await ask_gemini(prompt, system_prompt="Du er en uforutsigbar Quizmaster.")
            print(f"DEBUG: Gemini svarte: '{res}'")
            
            res = res.replace("```", "").strip()
            if "|" in res:
                t, c, p = res.split("|")
                tittel = t.strip()
                kategori = c.strip()
                bilde_prompt = p.strip()
            else:
                raise ValueError("Feil format fra Gemini")

        except Exception as e:
            print(f"⚠️ Gemini feilet ({e}). Bruker fallback.")
            tittel, kategori, bilde_prompt = random.choice(FALLBACK_QUIZ)

        path = await generate_and_save_image(bilde_prompt, BILDE_FILSTI)
        
        if path:
            print(f"✅ Bilde lagret ({tittel}). Sender ut...")
            await set_quiz_state(tittel, kategori, bilde_prompt)
            
            # LOGG START AV QUIZ
            lagre(
                tekst=f"Ny quiz generert: {tittel} ({kategori})", 
                user="QuizMaster", 
                guild_id="GLOBAL", 
                channel_id="0", 
                kategori="Quiz", 
                kilde="Auto"
            )
            
            for guild in self.bot.guilds:
                chan = discord.utils.get(guild.channels, name=QUIZ_CHANNEL_NAME)
                if chan:
                    try:
                        msg = await chan.send(
                            f"🎬 **DAGENS GLOBALE QUIZ!**\nKategori: **{kategori}**\n"
                            "Hva er dette? 👉 Send svar på DM! (3 forsøk)", 
                            file=discord.File(path)
                        )
                        await log_quiz_message(guild.id, chan.id, msg.id)
                    except Exception as ex:
                        print(f"Sendingsfeil i {guild.name}: {ex}")
        else:
            print("❌ Bildegenerering feilet helt.")

    # --- TIDSSTYRING MED NORSK TID ---
    @tasks.loop(time=time(hour=12, minute=0, tzinfo=ZoneInfo("Europe/Oslo"))) 
    async def daily_quiz(self):
        print(f"⏰ LOOOP: Starter daglig quiz nå! (Tid: {datetime.now()})")
        try:
            await self.lag_ny_quiz()
        except Exception as e:
            print(f"❌ KRITISK FEIL i daily_quiz loop: {e}")

    @daily_quiz.before_loop
    async def before_quiz(self):
        await self.bot.wait_until_ready()

    @commands.command()
    async def forcequiz(self, ctx):
        if not ctx.author.guild_permissions.administrator: return
        await ctx.send("Genererer ny quiz... sjekk terminalen.")
        await self.lag_ny_quiz()

    @commands.Cog.listener()
    async def on_message(self, message):
        # Sjekker at det er DM og ikke bot
        if message.author.bot or not isinstance(message.channel, discord.DMChannel): return
        
        state = await get_quiz_state()
        if not state or not state[2]: return # Sjekker om quiz er aktiv

        fasit = state[0].lower()
        gjett = message.content.lower().strip()
        
        # Bruker SequenceMatcher for å være litt snill på stavefeil (>80% likhet)
        ratio = SequenceMatcher(None, fasit, gjett).ratio()
        
        if ratio > 0.8 or (len(gjett) > 4 and gjett in fasit):
            await message.channel.send(f"🎉 **RIKTIG!** Svaret var: {state[0]}")
            await add_quiz_score(message.author.id)
            await message.channel.send("Du fikk +1 poeng!")
            
            # LOGG VINNER
            lagre(
                tekst=f"Vinner funnet: {message.author.name} gjettet {state[0]}", 
                user=message.author.name, 
                guild_id="DM", 
                channel_id="DM", 
                kategori="Quiz", 
                kilde="User"
            )
        else:
            await message.channel.send("❌ Feil svar, prøv igjen!")

async def setup(bot):
    await bot.add_cog(Quiz(bot))