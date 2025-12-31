import discord
from discord.ext import commands
import random
import json
import os
import asyncio
from utils.minne import hent, lagre



# 🔹 AI-motor + felles minne (fra kompisen din)
from utils.ai_motor import ask_mistral, ask_gemini   # async AI-funksjon
from utils.minne import hent, lagre     # felles minne (Chroma / vector-db)

# ---------- KONFIG ---------- #

# Endringer her
INTRO_MAPPE = "./data/intros"  # Dette er mappen for intro-lydene
SOUNDBOARD_DIR = "./data/soundboard"

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

client = discord.Client(intents=intents)
# Endringer her

# Denne brukes fortsatt til !pepesave / !pepewhoami (personlig “profil”-minne)
MEMORY_FILE = "pepe_memory.json"

# Kanal der Pepe skal svare på ALT (mode 3-auto-chat)
CHAT_CHANNEL_ID = 1443690072162439168  # bytt om du vil

# PEPE PERSONA (går inn som system_prompt til ask_mistral)
PEPE_PERSONA = (
    "Du er Pepe the King Prawn. Du er arrogant, selvsikker, og en uimotståelig stjerne. "
    "Svar aldri kjedelig. Du er den mest fabulous i rommet. "
    "Vist du blir spurt på norsk så kan du svare på norsk. "
    "Vist du blir spurt på engelsk så kan du svare på engelsk. "
    "KUN KORTE SVAR! "
    "Du er ein king prawn, ikkje ein skarMUSser."
    "Hvis du er usikker eller ikke klarer å svare, er det eneste ordet du skal returnere: **JEG_VET_IKKE**." # <-- NY RESTART-INSTRUKS
)

# ---------- PEPE-PERSONLEGHEIT ---------- #

PEPE_ENDINGS = [
    "okay?",
    "okay, okay?",
    "you know?",
    "amigo.",
    "my friend, okay?",
]

PEPE_QUOTES = [
    "I am not a shrimp, I am a king prawn, okay!",
    "Relax, I am the professional here, okay!",
    "Beauty like this does not come for free, okay!",
    "I don’t do work, I do appearances, okay!",
    "You are lucky I am even reading this, okay!",
    "I am the star, everyone else is background, okay!",
    "Do not question the prawn, okay!",
]

FLIRTS = [
    "Are you Wi-Fi? Because I am feeling a connection, okay?",
    "If being fabulous is a crime, you and I are going to jail, okay?",
    "You must be special, I don't say this to everyone… okay, maybe I do.",
    "You shine almost as bright as me, okay?",
    "If good looks could kill, we would both be wanted, okay?",
]

INSULTS = [
    "You type like a shrimp, not a king prawn, okay?",
    "That message? I give it a 2 out of 10, okay?",
    "Even Gonzo makes more sense than you sometimes, okay?",
    "This is not your best work, amigo, okay?",
    "I have seen better ideas in the dumpster behind the Muppet Theater, okay?",
]

FUN_FACTS = [
    "Fun fact: I am not a shrimp, I am a KING PRAWN, okay!",
    "Fun fact: I am the most handsome crustacean in showbiz, okay!",
    "Fun fact: Working is overrated, looking good is full-time, okay!",
    "Fun fact: If you disagree with me, you are wrong, okay!",
    "Fun fact: I only take advice from myself, okay!",
]

EIGHT_BALL_ANSWERS = [
    "Yes, of course, okay?",
    "No, terrible idea, okay?",
    "Maybe… if you are as fabulous as me, okay?",
    "Ask again later, I am busy being legendary, okay?",
    "Absolutely not, amigo.",
    "Definitely yes, don't mess it up, okay?",
    "Mmm… I would say no, okay?",
    "It is possible, but unlikely, like you being more stylish than me, okay?",
]

PEPE_REPLIES = [
    "Eg treng ikkje superhjerne for å meine noko, okay?",
    "Eg seier berre ting slik dei er, amigo!",
    "Dette er berre mine legendariske tankar, okay?",
    "Høyr no… eg veit kanskje ikkje alt, men eg er fortsatt den vakraste her inne, okeeeey?",
    "La meg tenke… okei, ferdig. Her er svaret ditt!",
    "Eg har ingen doktorgrad, men eg har stil, og det er viktigare, okay?",
    "Eg analyserte det du sa i tre millisekund. Her er mitt majestetiske svar, okay?",
    "Eg improviserer alt eg seier. Genialt, sant?",
    "Hmmm… dette luktar som noko ein kongeprawn bør svare på, okay?",
    "Eg brukar instinkta mine — og dei er alltid riktige, okeeeey?",
]

PEPE_NEGATIVE = [
    "Dette var ikkje ditt sterkaste øyeblikk, okay?",
    "Eg forventar meir… mykje meir, amigo.",
    "Hmm… nei, det der var ikkje bra.",
    "Eg er ikkje imponert, okeeeey?",
    "Dette er veldig ‘shrimp energy’, okay?",
    "Eg trudde du kunne bedre enn dette… kanskje ikkje.",
    "Nei, nei, nei… prøv igjen.",
    "Dette får meg til å revurdere heile vennskapet vårt, okay?",
    "Eg kjenner fysisk smerte av å lese dette.",
    "Dette var svakare enn Gonzo sine kjærleiksbrev, okay?",
]

PEPE_TOXIC = [
    "Bro… kor kjem desse tankane frå? Søppeldunken?",
    "Eg har sett smartere krabbar i fiskedisken, okay?",
    "Det du skriv får meg til å smelte… av skuffelse.",
    "Eg ville sagt det var bra, men eg lygar ikkje så mykje.",
    "Dette var så dårlig at eg nesten blei ein shrimp.",
    "Du prøvar… og det er søtt. Men fortsatt feil.",
    "Eg føler du og hjernen din har tatt ferie utan meg.",
    "Eg kunne svart betre i søvne… og eg søv FABULOUS, okay?",
    "Dette var så toxic at til og med *eg* blei stolt.",
    "Om dumskap var ein sport, hadde du tatt gull, okay?",
]

PEPE_FLIRTY = [
    "Ooooh, snakk meir til meg sånn, okay?",
    "Du prøvar å sjarmere meg, sant? Det fungerer… litt.",
    "Åh, du er farleg, amigo… farleg søt.",
    "Hvis blikk kunne drepe, hadde eg dødd lykkelig, okay?",
    "Eg er ikkje lett å imponere, men du er på god vei.",
    "Du får meg nesten til å gløyme at eg er ein kongeprawn.",
    "Stopp… du får meg til å rødme i skjella mine.",
    "Du må slutte å være så søt, okay? Dette blir for mykje.",
    "Eg hadde gitt deg ein klem, men eg er for fabulous for det.",
    "Careful… keep talking like that and I might like you, okay?",
]

PEPE_MEMES = [
    "Bruh… eg kan ikkje ein gong…",
    "Dette er 100% certified Pepe moment, okay?",
    "When you say that and my last braincell leaves the chat.",
    "Eg skal ikkje seie ‘cringe’… men… du veit.",
    "Dette får meg til å reinstallere livet mitt.",
    "Loading… error… too much nonsense detected.",
    "Dette høyrest ut som eit TikTok-hack ingen trengte.",
    "Eg hadde eit svar, men eg ctrl+Z’et det.",
    "This ain’t it, chief. Okay?",
    "Eg rapporterte meldinga di… til meg sjølv for underhaldning.",
]

# Superliste for random AI-svar
PEPE_SUPERLIST = (
    PEPE_REPLIES +
    PEPE_NEGATIVE +
    PEPE_TOXIC +
    PEPE_FLIRTY +
    PEPE_MEMES
)

TRIGGER_WORDS = ["shrimp", "prawn", "reke", "rekekonge"]


def pepe_style(text: str) -> str:
    """Legg til typisk Pepe-ending på tekst."""
    ending = random.choice(PEPE_ENDINGS)
    if text.endswith((".", "?", "!")):
        return text + " " + ending
    return text + ", " + ending


# ---------- LOKALT MINNE FOR !pepesave / !pepewhoami ---------- #

def load_memory() -> dict:
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_memory(memory: dict) -> None:
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def get_user_memory(memory: dict, user_id: int) -> dict:
    uid = str(user_id)
    if uid not in memory:
        memory[uid] = {"facts": []}
    return memory[uid]


def add_user_fact(memory: dict, user_id: int, fact: str) -> None:
    user_mem = get_user_memory(memory, user_id)
    if fact not in user_mem["facts"]:
        user_mem["facts"].append(fact)


# ---------- DISCORD KLIENT ---------- #

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------- EVENTS ---------- #

@bot.event
async def on_ready():
    print(f"🦐 Logged in as {bot.user}")
    activity = discord.Game(name="Being fabulous, okay?")
    await bot.change_presence(status=discord.Status.online, activity=activity)


@bot.event
async def on_message(message: discord.Message):

    #Endringer her
    # --- Sett intro ---
    if message.content == "!sett_intro":
        if not message.attachments:
            await message.channel.send("🐸 Du må legge ved en MP3-fil!")
            return
        
        fil = message.attachments[0]
        if not fil.filename.endswith(".mp3"):
            await message.channel.send("🐸 Kun MP3-filer, amigo!")
            return

        filnavn = f"{INTRO_MAPPE}/{message.author.id}.mp3"

        try:
            await fil.save(filnavn)
            await message.channel.send(f"🐸 Nice! Intro lagret for {message.author.name}.")
        except Exception as e:
            await message.channel.send(f"Feil ved lagring: {e}")

    # --- Test intro ---
    if message.content == "!test_intro":
        kanal = message.author.voice.channel if message.author.voice else None
        await spill_intro(message.author, kanal)

    # SOUND: !sound <filnavn>
    if message.content.startswith("!sound"):
        parts = message.content.split(" ")
        if len(parts) < 2:
            await message.channel.send("Bruk: !sound <filnavn.mp3>")
            return

        sound_name = parts[1]

        if not message.author.voice or not message.author.voice.channel:
            await message.channel.send("Du må være i voice-kanal for å spille av lyd!")
            return

        ok = await play_sound(message.author.voice.channel, sound_name)

        if not ok:
            await message.channel.send("Kunne ikke finne denne filen i soundboard‑mappen.")
        return
    # -------------------------------------------------------
    # 1. Legg til lyd: bruker laster opp MP3 + skriver:
    #    !sb_add <navn>
    # -------------------------------------------------------
    if message.content.startswith("!sb_add"):
        deler = message.content.split(" ", 1)
        if len(deler) < 2:
            await message.channel.send("Bruk: `!sb_add <navn>` + last opp en .mp3 fil.")
            return

        navn = deler[1].strip().lower().replace(" ", "_")

        if not message.attachments:
            await message.channel.send("Du må laste opp en MP3-fil sammen med kommandoen.")
            return

        fil = message.attachments[0]
        if not fil.filename.endswith(".mp3"):
            await message.channel.send("Kun MP3-filer støttes.")
            return

        lagringssti = f"{SOUNDBOARD_DIR}/{navn}.mp3"

        try:
            await fil.save(lagringssti)
            await message.channel.send(f"🔊 Lyd **{navn}** ble lagt til soundboardet!")
        except Exception as e:
            await message.channel.send(f"Feil ved lagring: {e}")

    # -------------------------------------------------------
    # 2. List alle lydene
    # -------------------------------------------------------
    if message.content == "!sb_list":
        filer = os.listdir(SOUNDBOARD_DIR)
        lyder = [f[:-4] for f in filer if f.endswith(".mp3")]

        if not lyder:
            await message.channel.send("Soundboardet er tomt.")
            return

        await message.channel.send("🎵 **Tilgjengelige lyder:**\n" + "\n".join(f"- {l}" for l in lyder))

    # -------------------------------------------------------
    # 3. Spill av lyd: !sb_play <navn>
    # -------------------------------------------------------
    if message.content.startswith("!sb_play"):
        deler = message.content.split(" ", 1)
        if len(deler) < 2:
            await message.channel.send("Bruk: `!sb_play <navn>`")
            return

        navn = deler[1].strip().lower()
        filsti = f"{SOUNDBOARD_DIR}/{navn}.mp3"

        if not os.path.exists(filsti):
            await message.channel.send(f"Fant ikke lyden `{navn}`.")
            return

        if not message.author.voice:
            await message.channel.send("Du må være i en voice‑kanal for å spille av lyder.")
            return

        voice_channel = message.author.voice.channel

        try:
            vc = await voice_channel.connect()

            source = discord.FFmpegPCMAudio(filsti)
            vc.play(source)

            # Vent til ferdig eller maks 10 sek
            teller = 0
            while vc.is_playing() and teller < 10:
                await asyncio.sleep(1)
                teller += 1

            await vc.disconnect()

        except Exception as e:
            await message.channel.send(f"Feil ved avspilling: {e}")
        #Endringer her


    # ikkje svar på oss sjølv
    if message.author == bot.user:
        return

    # ----- MODE 3: Pepe svarer på ALT i ein bestemt kanal -----
    if message.channel.id == CHAT_CHANNEL_ID:
        async with message.channel.typing():
            # hent relevant minne frå felles minnesystem
            mem = hent(message.content, message.channel.id)


                                                                                    #Endringer her også
            # bruk AI-motoren (Mistral eller kva kompisen din har satt opp)
            svar = await ask_mistral(
                clean_text, 
                context=mem, 
                system_prompt=PEPE_PERSONA # Bruker persona inkludert feilkoden
            )
            
            # --- 2. FALLBACK TIL GEMINI (Kort og Smart) ---
            # Hvis Mistral feilet, eller ga opp:
            if "JEG_VET_IKKE" in svar or len(svar.strip()) < 5:
                print("Pepe: Mistral ga opp. Sender til Gemini.")
                
                # Siden PEPE_PERSONA allerede ligger i filen, sender vi den rett til Gemini
                svar = await ask_gemini(
                    clean_text, 
                    context=mem, 
                    system_prompt=PEPE_PERSONA 
                )
                
                                                                                    #Endringer

            # 3. STYLE OG SEND
            svar_stil = pepe_style(svar)
            await message.channel.send(svar_stil)
            lagre("Pepe", f"Pepe: {svar}", message.channel.id)
            
            return
            

            # style svaret som Pepe + send
            svar_stil = pepe_style(svar)
            await message.channel.send(svar_stil)

            # logg samtalen i minne-systemet
            lagre(str(message.author.id), f"{message.author.display_name}: {message.content}", message.channel.id)
            lagre("Pepe", f"Pepe: {svar}", message.channel.id)

        return  # viktig så han ikkje prøver commands her samtidig

    # ----- TRIGGER: reke/shrimp/prawn i andre kanalar -----
    lower = message.content.lower()
    if any(word in lower for word in TRIGGER_WORDS):
        await message.channel.send("I am not a shrimp, I am a KING PRAWN, okay?! 🦐👑")

    # ----- tillat !-kommandor -----
    await bot.process_commands(message)

# Endringer her
# ---- VOICE HANDLING ----
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    # Bruker joinet en voice-kanal
    if before.channel is None and after.channel is not None:
        await asyncio.sleep(0.7)  # litt delay for stabilitet
        await spill_intro(member, after.channel)

# ---- SPILL AV INTRO ----
async def spill_intro(member, channel):
    if not channel:
        return

    # Finn mp3-fil
    filsti = f"{INTRO_MAPPE}/{member.id}.mp3"
    if not os.path.exists(filsti):
        return

    # Hopp ut hvis boten allerede spiller noe annet
    if client.voice_clients:
        return

    try:
        # Koble til voice
        vc = await channel.connect()

        # Spill av lyd
        source = discord.FFmpegPCMAudio(filsti)
        vc.play(source)

        # Vent mens lyden spiller (max 10 sek)
        teller = 0
        while vc.is_playing() and teller < 10:
            await asyncio.sleep(1)
            teller += 1

        # Koble fra etterpå
        await vc.disconnect()

    except Exception as e:
        print(f"Feil med intro for {member.name}: {e}")
        try:
            if client.voice_clients:
                await client.voice_clients[0].disconnect()
        except:
            pass

# ---- EXPORT ----
def get_pepe_client():
    return client
# Endringer her

# ---------- KOMMANDOAR ---------- #

@bot.command(name="pepehelp")
async def pepehelp(ctx: commands.Context):
    text = (
        "**Pepe the King Prawn – commands, okay?**\n"
        "`!pepehelp` – viser denne meldinga\n"
        "`!pepeintro` – Pepe introduserer seg\n"
        "`!pepeping` – sjekk om Pepe er våken\n"
        "`!pepequote` – random sitat frå Pepe\n"
        "`!pepeflirt [@brukar]` – Pepe flørter\n"
        "`!pepeinsult [@brukar]` – Pepe roastar\n"
        "`!peperate <ting>` – Pepe gir 1–10\n"
        "`!pepefact` – random 'fun fact'\n"
        "`!pepe8ball <spørsmål>` – magisk Pepe 8-ball\n"
        "`!pepesave <tekst>` – lagre noko Pepe skal huske om deg (lokal profil)\n"
        "`!pepewhoami` – sjå kva Pepe huskar om deg\n"
        "`!pepechat <melding>` – AI-samtale med Pepe i denne kanalen\n\n"
        f"I kanalen med ID `{CHAT_CHANNEL_ID}` svarer han automatisk på ALT, okay?"
    )
    await ctx.send(text)


@bot.command(name="pepeintro")
async def pepeintro(ctx: commands.Context):
    msg = (
        "Hola, I am Pepe the King Prawn, okay?! 🦐👑\n"
        "I am not a shrimp, I am a star. You talk, I judge, okay?"
    )
    await ctx.send(pepe_style(msg))


@bot.command(name="pepeping")
async def pepeping(ctx: commands.Context):
    await ctx.send("I am awake and fabulous, okay? 🦐")


@bot.command(name="pepequote")
async def pepequote(ctx: commands.Context):
    quote = random.choice(PEPE_QUOTES)
    await ctx.send(pepe_style(quote))


@bot.command(name="pepeflirt")
async def pepeflirt(ctx: commands.Context, member: discord.Member | None = None):
    target = member.mention if member else ctx.author.mention
    flirt = random.choice(FLIRTS)
    await ctx.send(pepe_style(f"{target} {flirt}"))


@bot.command(name="pepeinsult")
async def pepeinsult(ctx: commands.Context, member: discord.Member | None = None):
    target = member.mention if member else ctx.author.mention
    insult = random.choice(INSULTS)
    await ctx.send(pepe_style(f"{target} {insult}"))


@bot.command(name="peperate")
async def peperate(ctx: commands.Context, *, thing: str):
    score = random.randint(1, 10)
    msg = f"I rate `{thing}` a **{score}/10**, okay."
    if score <= 3:
        msg += " That is very shrimp energy, okay."
    elif score <= 6:
        msg += " Not bad, but not king prawn level, okay."
    else:
        msg += " Now THAT is closer to my style, okay!"
    await ctx.send(pepe_style(msg))


@bot.command(name="pepefact")
async def pepefact(ctx: commands.Context):
    fact = random.choice(FUN_FACTS)
    await ctx.send(pepe_style(fact))


@bot.command(name="pepe8ball")
async def pepe8ball(ctx: commands.Context, *, question: str):
    answer = random.choice(EIGHT_BALL_ANSWERS)
    await ctx.send(pepe_style(f"You asked: `{question}`\nMy answer: {answer}"))


@bot.command(name="pepesave")
async def pepesave(ctx: commands.Context, *, info: str):
    """Lagrer enkel profil-info om brukeren i lokal JSON."""
    memory = load_memory()
    add_user_fact(memory, ctx.author.id, info)
    save_memory(memory)
    await ctx.send(pepe_style("Greitt, eg skal prøve å huske det, okay."))


@bot.command(name="pepewhoami")
async def pepewhoami(ctx: commands.Context):
    """Viser kva Pepe har lagra om deg i lokal JSON."""
    memory = load_memory()
    user_mem = get_user_memory(memory, ctx.author.id)
    facts = user_mem.get("facts", [])
    if not facts:
        await ctx.send(pepe_style("Eg veit ingenting om deg endå, okay. Bruk !pepesave."))
        return
    text = "Dette er det eg trur eg veit om deg, okay:\n- " + "\n- ".join(facts)
    await ctx.send(pepe_style(text))


@bot.command(name="pepechat")
async def pepechat(ctx: commands.Context, *, message: str):
    """
    Manuell AI-chat med Pepe i vilkårleg kanal (utanfor auto-chat-kanalen).
    Bruker same AI-motor og minne som auto-chat.
    """
    async with ctx.typing():
        mem = hent(message, ctx.channel.id)
        svar = await ask_mistral(
            message,
            context=mem,
            system_prompt=PEPE_PERSONA,
        )
        svar_stil = pepe_style(svar)
        await ctx.send(svar_stil)
        lagre(str(ctx.author.id), f"{ctx.author.display_name}: {message}", ctx.channel.id)
        lagre("Pepe", f"Pepe: {svar}", ctx.channel.id)


# ---------- VOICE-KOMMANDOER ---------- #

@bot.command(name="pepejoin")
async def pepejoin(ctx: commands.Context):
    """Pepe joiner voice-kanalen du er i."""
    if ctx.author.voice is None:
        await ctx.send("Du er ikkje i ein voice-kanal, okay?")
        return

    channel = ctx.author.voice.channel

    if ctx.voice_client is not None:
        # Flytt Pepe til din kanal hvis han alt er kobla til ein annan
        await ctx.voice_client.move_to(channel)
    else:
        await channel.connect()

    await ctx.send("Eg er i voice-kanalen, okay? 🎙️🦐")


@bot.command(name="pepeleave")
async def pepeleave(ctx: commands.Context):
    """Pepe forlater voice-kanalen."""
    if ctx.voice_client is None:
        await ctx.send("Eg er ikkje i nokon voice-kanal, okay?")
        return

    await ctx.voice_client.disconnect()
    await ctx.send("Eg stikk frå voice, okay. 🤌")


@bot.command(name="pepevoice")
async def pepevoice(ctx: commands.Context):
    """Pepe spelar av ei lydfil i voice-kanalen."""
    if ctx.voice_client is None:
        await ctx.send("Eg må vere i ein voice-kanal først, bruk !pepejoin, okay?")
        return

    vc: discord.VoiceClient = ctx.voice_client

    if vc.is_playing():
        await ctx.send("Eg pratar allereie, okay?")
        return

    # Spel av ei lokal lydfil – t.d. 'pepe_line.mp3'
    audio_source = discord.FFmpegPCMAudio("pepe_line.mp3")
    vc.play(audio_source)

    await ctx.send("Lytt nøye no, okay? 🔊🦐")

# Endringer fra stian

def get_pepe_client():
    # VIKTIG: Lager mappen for intro-lydene hvis den mangler
    os.makedirs(INTRO_MAPPE, exist_ok=True) 
    # Returnerer bot-objektet (definert som 'bot' øverst i filen)
    return bot