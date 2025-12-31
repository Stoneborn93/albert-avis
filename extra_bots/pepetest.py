import discord
from discord.ext import commands
import random
import os
import asyncio

# 🔹 AI-motor + felles minne
from utils.ai_motor import ask_mistral, ask_gemini
from utils.minne import hent, lagre

# ---------- KONFIGURASJON ---------- #

INTRO_MAPPE = "./data/intros"
SOUNDBOARD_DIR = "./data/soundboard"
# Kanal ID der Pepe svarer automatisk (Endre denne til din kanal-ID)
CHAT_CHANNEL_ID = 1443690072162439168 

# PEPE PERSONA (Hovedinstruksjon)
PEPE_PERSONA = (
    "Du er Pepe the King Prawn. Du er arrogant, selvsikker, og en uimotståelig stjerne. "
    "Svar aldri kjedelig. Du er den mest fabulous i rommet. "
    "Hvis du blir spurt på norsk, svar på norsk (bruk bokmål). "
    "Hvis du blir spurt på engelsk, svar på engelsk. "
    "Bruk engelske slangord som 'amigo', 'okay' og 'fabulous' ofte. "
    "KUN KORTE SVAR! Du er en king prawn, ikke en forfatter. "
    "VIKTIG: Hvis du er usikker, ikke vet svaret, eller trenger hjelp, returner KUN ordet: **JEG_VET_IKKE**"
)

# ---------- LISTER OG DATA ---------- #

PEPE_ENDINGS = ["okay?", "okay, okay?", "you know?", "amigo.", "my friend, okay?"]

PEPE_QUOTES = [
    "I am not a shrimp, I am a king prawn, okay!",
    "Relax, I am the professional here, okay!",
    "Beauty like this does not come for free, okay!",
    "I don’t do work, I do appearances, okay!",
    "Do not question the prawn, okay!",
]

FLIRTS = [
    "Are you Wi-Fi? Because I am feeling a connection, okay?",
    "If being fabulous is a crime, you and I are going to jail, okay?",
    "You shine almost as bright as me, okay?",
]

INSULTS = [
    "You type like a shrimp, not a king prawn, okay?",
    "That message? I give it a 2 out of 10, okay?",
    "Even Gonzo makes more sense than you sometimes, okay?",
]

FUN_FACTS = [
    "Fun fact: I am not a shrimp, I am a KING PRAWN, okay!",
    "Fun fact: Working is overrated, looking good is full-time, okay!",
    "Fun fact: I only take advice from myself, okay!",
]

EIGHT_BALL_ANSWERS = [
    "Yes, of course, okay?",
    "No, terrible idea, okay?",
    "Maybe… if you are as fabulous as me, okay?",
    "Ask again later, I am busy being legendary, okay?",
    "Absolutely not, amigo.",
]

TRIGGER_WORDS = ["shrimp", "prawn", "reke", "rekekonge"]


def pepe_style(text: str) -> str:
    """Legger til typisk Pepe-ending på tekst."""
    ending = random.choice(PEPE_ENDINGS)
    if text.endswith((".", "?", "!")):
        return text + " " + ending
    return text + ", " + ending


# ---------- DISCORD BOT SETUP ---------- #

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------- EVENTS ---------- #

@bot.event
async def on_ready():
    print(f"🦐 PEPE er online som {bot.user}")
    activity = discord.Game(name="Being fabulous, okay?")
    await bot.change_presence(status=discord.Status.online, activity=activity)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return

    # --- 1. MODE 3: AUTO-CHAT (AI) ---
    if message.channel.id == CHAT_CHANNEL_ID:
        async with message.channel.typing():
            # Hent minne
            clean_text = message.content.replace(f"<@{bot.user.id}>", "").strip()
            mem = hent(clean_text, message.channel.id)

            # A) Prøv Mistral først
            svar = await ask_mistral(clean_text, context=mem, system_prompt=PEPE_PERSONA)

            # B) Fallback til Gemini hvis Mistral ikke vet
            if "JEG_VET_IKKE" in svar or len(svar.strip()) < 3:
                print("Pepe: Mistral ga opp. Sender til Gemini.")
                svar = await ask_gemini(clean_text, context=mem, system_prompt=PEPE_PERSONA)

            # C) Send svar
            svar_stil = pepe_style(svar)
            await message.channel.send(svar_stil)
            
            # D) Lagre samtalen
            lagre(str(message.author.id), f"{message.author.display_name}: {message.content}", message.channel.id)
            lagre("Pepe", f"Pepe: {svar}", message.channel.id)

        return # Viktig: Ikke behandle kommandoer i denne kanalen

    # --- 2. TRIGGER WORDS (Reker osv) ---
    lower = message.content.lower()
    if any(word in lower for word in TRIGGER_WORDS):
        await message.channel.send("I am not a shrimp, I am a KING PRAWN, okay?! 🦐👑")

    # --- 3. PROSESSER KOMMANDOER ---
    await bot.process_commands(message)


@bot.event
async def on_voice_state_update(member, before, after):
    """Spiller intro når noen joiner en kanal."""
    if member.bot: return

    # Bruker joinet en voice-kanal (var ikke i en før, men er i en nå)
    if before.channel is None and after.channel is not None:
        await asyncio.sleep(1.0) # Vent litt så brukeren rekker å koble til
        await spill_intro(member, after.channel)


# ---------- HJELPEFUNKSJONER FOR LYD ---------- #

async def spill_intro(member, channel):
    if not channel: return

    filsti = f"{INTRO_MAPPE}/{member.id}.mp3"
    if not os.path.exists(filsti): return # Ingen intro lagret

    # Ikke avbryt hvis boten er opptatt
    if bot.voice_clients: return

    try:
        vc = await channel.connect()
        vc.play(discord.FFmpegPCMAudio(filsti))
        
        teller = 0
        while vc.is_playing() and teller < 10:
            await asyncio.sleep(1)
            teller += 1
        
        await vc.disconnect()
    except Exception as e:
        print(f"Feil med intro: {e}")
        # Prøv å koble fra ved feil
        if bot.voice_clients:
            await bot.voice_clients[0].disconnect()


# ---------- KOMMANDOER: SOUNDBOARD ---------- #

@bot.command(name="sb_add")
async def sb_add(ctx: commands.Context, navn: str):
    """Legg til en lyd i soundboardet: !sb_add <navn> (legg ved mp3)"""
    navn = navn.strip().lower().replace(" ", "_")

    if not ctx.message.attachments or not ctx.message.attachments[0].filename.endswith(".mp3"):
        await ctx.send("🐸 Du må laste opp en MP3-fil, amigo!")
        return

    lagringssti = f"{SOUNDBOARD_DIR}/{navn}.mp3"
    try:
        await ctx.message.attachments[0].save(lagringssti)
        await ctx.send(f"🔊 Lyd **{navn}** ble lagt til, okay!")
    except Exception as e:
        await ctx.send(f"Feil: {e}")

@bot.command(name="sb_list")
async def sb_list(ctx: commands.Context):
    """Viser alle lyder i soundboardet."""
    if not os.path.exists(SOUNDBOARD_DIR):
        await ctx.send("Ingen lyder enda.")
        return
    
    filer = os.listdir(SOUNDBOARD_DIR)
    lyder = [f[:-4] for f in filer if f.endswith(".mp3")]
    
    if not lyder:
        await ctx.send("Soundboardet er tomt.")
    else:
        await ctx.send("🎵 **Lyder:**\n" + "\n".join(f"- {l}" for l in lyder))

@bot.command(name="sb_play")
async def sb_play(ctx: commands.Context, navn: str):
    """Spill av en lyd: !sb_play <navn>"""
    navn = navn.strip().lower()
    filsti = f"{SOUNDBOARD_DIR}/{navn}.mp3"

    if not os.path.exists(filsti):
        await ctx.send(f"Fant ikke lyden `{navn}`, okay?")
        return

    if not ctx.author.voice:
        await ctx.send("Du må være i en voice-kanal!")
        return

    try:
        vc = await ctx.author.voice.channel.connect()
        vc.play(discord.FFmpegPCMAudio(filsti))
        while vc.is_playing(): await asyncio.sleep(1)
        await vc.disconnect()
    except Exception as e:
        await ctx.send(f"Kunne ikke spille av: {e}")


# ---------- KOMMANDOER: INTRO ---------- #

@bot.command(name="sett_intro")
async def sett_intro(ctx: commands.Context):
    """Last opp MP3 som din intro."""
    if not ctx.message.attachments or not ctx.message.attachments[0].filename.endswith(".mp3"):
        await ctx.send("🐸 MP3-fil kreves, amigo!")
        return
    
    filnavn = f"{INTRO_MAPPE}/{ctx.author.id}.mp3"
    await ctx.message.attachments[0].save(filnavn)
    await ctx.send(f"🐸 Intro lagret for {ctx.author.name}, okay!")

@bot.command(name="test_intro")
async def test_intro(ctx: commands.Context):
    """Test din egen intro."""
    if ctx.author.voice:
        await spill_intro(ctx.author, ctx.author.voice.channel)
    else:
        await ctx.send("Gå i en voice-kanal først.")


# ---------- KOMMANDOER: GENERAL PEPE ---------- #

@bot.command(name="pepehelp")
async def pepehelp(ctx: commands.Context):
    msg = (
        "**PEPE COMMANDS, OKAY?**\n"
        "`!sb_add <navn>` - Last opp lyd til soundboard\n"
        "`!sb_play <navn>` - Spill lyd\n"
        "`!sb_list` - Se alle lyder\n"
        "`!sett_intro` - Last opp din intro (mp3)\n"
        "`!pepefact` - Vis en fakta\n"
        "`!pepeinsult` - Bli roastet\n"
    )
    await ctx.send(msg)

@bot.command(name="pepefact")
async def pepefact(ctx: commands.Context):
    await ctx.send(pepe_style(random.choice(FUN_FACTS)))

@bot.command(name="pepeinsult")
async def pepeinsult(ctx: commands.Context, member: discord.Member = None):
    target = member.mention if member else "You"
    await ctx.send(pepe_style(f"{target}, {random.choice(INSULTS)}"))

@bot.command(name="pepejoin")
async def pepejoin(ctx: commands.Context):
    if ctx.author.voice:
        await ctx.author.voice.channel.connect()
        await ctx.send("I am here now, okay? 🦐")

@bot.command(name="pepeleave")
async def pepeleave(ctx: commands.Context):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Leaving the building. 🤌")


# ---------- EXPORT TIL MAIN.PY ---------- #

def get_pepe_client():
    # Sikrer at mappene finnes før oppstart
    os.makedirs(INTRO_MAPPE, exist_ok=True)
    os.makedirs(SOUNDBOARD_DIR, exist_ok=True)
    return bot