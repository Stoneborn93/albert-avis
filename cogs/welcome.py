import discord
from discord.ext import commands
import asyncio
import json
import os
# Vi legger til logging for å holde oversikt over hvem som bruker AI-en
from utils.minne import lagre

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ai_category_name = "🔒 PERSONLIG AI"
        self.main_category_name = "💬 SAMFUNN"
        self.command_chan_name = "chat-commands"
        
        self.role_configs = {
            "🍳": "Kokk",
            "😂": "Memelord",
            "⚔️": "Eventyrer",
            "🎮": "Gamer",
            "🤖": "AI-Privat"
        }
        
        self.fixed_channels = [
            "daglig-quiz",
            "memes",
            "matlaging",
            "generelt-prat",
            "rpg-oppsummering",
            "spill-nytt",
            self.command_chan_name
        ]

    async def create_structure(self, guild):
        """Oppretter roller, kategorier og alle faste kanaler basert på navn."""
        # 1. Roller
        for emoji, role_name in self.role_configs.items():
            if not discord.utils.get(guild.roles, name=role_name):
                await guild.create_role(name=role_name, reason="Albert automatisk oppsett")

        # 2. Hovedkategori
        main_category = discord.utils.get(guild.categories, name=self.main_category_name)
        if not main_category:
            main_category = await guild.create_category(self.main_category_name)

        # 3. Faste Kanaler
        for chan_name in self.fixed_channels:
            if not discord.utils.get(guild.text_channels, name=chan_name):
                await guild.create_text_channel(chan_name, category=main_category)

        # 4. AI-kategori
        ai_category = discord.utils.get(guild.categories, name=self.ai_category_name)
        if not ai_category:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)
            }
            ai_category = await guild.create_category(self.ai_category_name, overwrites=overwrites)
        
        return ai_category

    def lag_kommando_embed(self):
        """Genererer den faste oversikten over kommandoer."""
        embed = discord.Embed(
            title="🤖 BOT KOMMANDOER",
            description="Her er oversikten over hva Albert, Pepe og 3mil kan gjøre.",
            color=discord.Color.blue()
        )
        embed.add_field(name="⚔️ Rollespill (RPG)", value=(
            "`!rpg start [lengde] [tts]` - Start spill.\n"
            "`!rpg invite @venn` - Inviter noen.\n"
            "`!rpg [handling]` - Gjør noe i spillet.\n"
            "`!rpg slutt` - Avslutt og lagre sagaen."
        ), inline=False)
        embed.add_field(name="🐸 Pepe & Lyd", value=(
            "`!sb` - Åpne Soundboard.\n"
            "`!sett_intro` - Last opp MP3 for intro-låt.\n"
            "`!pepe kom` / `!pepe stikk` - Styr Pepe."
        ), inline=False)
        embed.add_field(name="🧠 AI & Chat", value=(
            "`@Albert [spørsmål]` - Snakk med boten.\n"
            "`#kode-hjelp` - Gemini Pro programmering.\n"
            "`#matlagingstips` - Oppskrifter.\n"
            "`!gem [spørsmål]` - Chat uten minnelagring."
        ), inline=False)
        embed.add_field(name="⚙️ Annet", value=(
            "`!nytt_event YYYY-MM-DD Tittel` - Kalender.\n"
            "`!lagre` - (Svar på melding) Lagre leksjon til Albert.\n"
            "`!dilemma` / `!drøm` / `!rap` - Minispill."
        ), inline=False)
        return embed

    @commands.command(name="setup_welcome")
    @commands.has_permissions(administrator=True)
    async def setup_welcome(self, ctx):
        """Kjører fullt oppsett og oppdaterer kommandoliste dynamisk."""
        await self.create_structure(ctx.guild)
        
        # Oppdater/Send kommandoliste i #chat-commands ved å lete etter eksisterende melding
        cmd_chan = discord.utils.get(ctx.guild.text_channels, name=self.command_chan_name)
        if cmd_chan:
            eksisterende_msg = None
            # Let gjennom historikken for å finne forrige liste
            async for message in cmd_chan.history(limit=20):
                if message.author == self.bot.user and message.embeds:
                    if message.embeds[0].title == "🤖 BOT KOMMANDOER":
                        eksisterende_msg = message
                        break
            
            new_embed = self.lag_kommando_embed()
            if eksisterende_msg:
                await eksisterende_msg.edit(embed=new_embed)
            else:
                await cmd_chan.send(embed=new_embed)

        # Velkomstmelding
        embed = discord.Embed(
            title="👋 Velkommen!",
            description="Velg rollene dine for å åpne kanalene:\n\n🍳 Kokk | 😂 Memelord | ⚔️ Eventyrer | 🎮 Gamer | 🤖 Personlig AI",
            color=discord.Color.green()
        )
        msg = await ctx.send(embed=embed)
        for emoji in self.role_configs.keys():
            await msg.add_reaction(emoji)
            await asyncio.sleep(0.5) # Unngå rate limits

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id: return
        emoji = str(payload.emoji)
        if emoji not in self.role_configs: return

        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        role = discord.utils.get(guild.roles, name=self.role_configs[emoji])

        if role:
            await member.add_roles(role)
            if emoji == "🤖":
                category = discord.utils.get(guild.categories, name=self.ai_category_name)
                chan_name = f"ai-{member.name}".lower()
                if not discord.utils.get(category.text_channels, name=chan_name):
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(view_channel=False),
                        member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
                    }
                    new_chan = await guild.create_text_channel(chan_name, category=category, overwrites=overwrites)
                    
                    # LOGG TIL SYSTEMET (NYTT)
                    lagre(
                        tekst=f"Opprettet personlig AI-kanal: {chan_name}",
                        user="System",
                        guild_id=guild.id,
                        channel_id=new_chan.id,
                        kategori="Setup",
                        kilde="Welcome"
                    )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        emoji = str(payload.emoji)
        if emoji not in self.role_configs: return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        role = discord.utils.get(guild.roles, name=self.role_configs[emoji])
        if role:
            await member.remove_roles(role)
            if emoji == "🤖":
                category = discord.utils.get(guild.categories, name=self.ai_category_name)
                channel = discord.utils.get(category.text_channels, name=f"ai-{member.name}".lower())
                if channel: await channel.delete()

async def setup(bot):
    await bot.add_cog(Welcome(bot))