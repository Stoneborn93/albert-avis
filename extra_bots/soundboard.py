import discord
import os
import asyncio
# Vi legger til logging
from utils.minne import lagre

SOUNDBOARD_DIR = "./data/soundboard"

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

client = discord.Client(intents=intents)

# ---------------------------------
#   Sørg for at mappe finnes
# ---------------------------------
os.makedirs(SOUNDBOARD_DIR, exist_ok=True)


@client.event
async def on_ready():
    print("🔊 Soundboard-modul er aktiv!")


@client.event
async def on_message(message):
    if message.author.bot:
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
            
            # LOGG
            lagre(
                tekst=f"La til ny lyd: {navn}",
                user=message.author.name,
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                kategori="Soundboard",
                kilde="AddCmd"
            )
            
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
            
            # LOGG
            lagre(
                tekst=f"Spilte av lyd: {navn}",
                user=message.author.name,
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                kategori="Soundboard",
                kilde="PlayCmd"
            )

            # Vent til ferdig eller maks 10 sek
            teller = 0
            while vc.is_playing() and teller < 10:
                await asyncio.sleep(1)
                teller += 1

            await vc.disconnect()

        except Exception as e:
            await message.channel.send(f"Feil ved avspilling: {e}")


def get_soundboard_client():
    return client