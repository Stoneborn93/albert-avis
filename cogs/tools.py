import discord
import random
import re
from discord.ext import commands
# Vi legger til logging så vi kan huske hvem som har flaks/uflaks
from utils.minne import lagre

class Tools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignorer meldinger fra botter (inkludert seg selv)
        if message.author.bot:
            return

        # Regex-mønster: Ser etter !d etterfulgt av ett eller flere siffer
        match = re.match(r'^!d(\d+)$', message.content.lower().strip())
        
        if match:
            try:
                # Henter X fra !dX
                sider = int(match.group(1))
                
                if sider < 1:
                    return await message.channel.send("⚠️ En terning må ha minst én side.")
                
                # Sperre for absurde tall
                if sider > 1000000:
                    return await message.channel.send("⚠️ Det der er mer en kule enn en terning. Prøv under en million.")

                resultat = random.randint(1, sider)
                
                # Bestemmer drama-effekter
                emoji = "🎲"
                status = ""
                
                if resultat == sider and sider > 1:
                    emoji = "✨"
                    status = "**CRITICAL SUCCESS!**"
                elif resultat == 1 and sider > 1:
                    emoji = "💀"
                    status = "**CRITICAL FAIL!**"
                
                # Send melding til Discord
                await message.channel.send(
                    f"{emoji} {message.author.display_name} ruller en **D{sider}**...\n"
                    f"> Resultat: **{resultat}** {status}"
                )

                # LOGG TIL SYSTEMET (NYTT)
                # Vi logger resultatet slik at boten husker hvem som har flaks
                lagre(
                    tekst=f"Terningkast D{sider}: {resultat} {status}",
                    user=message.author.name,
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    kategori="Spillmekanikk",
                    kilde="Tools"
                )

            except ValueError:
                pass

async def setup(bot):
    await bot.add_cog(Tools(bot))