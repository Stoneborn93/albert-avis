import discord
from discord.ext import commands, tasks
import time
import datetime
from utils.db_handler import (
    update_game_time, 
    get_server_scoreboard, 
    save_scoreboard_msg, 
    get_scoreboard_msg,
    get_personal_stats
)

class GameMonitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Format: {(user_id, server_id): (game_name, start_time)}
        self.active_sessions = {}
        self.scoreboard_updater.start()

    def cog_unload(self):
        self.scoreboard_updater.cancel()

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        """Tracker når folk starter og slutter å spille."""
        if after.bot:
            return

        user_id = after.id
        server_id = after.guild.id
        
        # Finn nåværende spill (håndterer både før og etter)
        before_game = next((activity.name for activity in before.activities if activity.type == discord.ActivityType.playing), None)
        after_game = next((activity.name for activity in after.activities if activity.type == discord.ActivityType.playing), None)

        # SCENARIO 1: Begynt å spille et nytt spill
        if before_game != after_game and after_game is not None:
            if (user_id, server_id) in self.active_sessions:
                await self.end_session(user_id, server_id)
            
            self.active_sessions[(user_id, server_id)] = (after_game, time.time())

        # SCENARIO 2: Sluttet å spille
        elif after_game is None and (user_id, server_id) in self.active_sessions:
            await self.end_session(user_id, server_id)

    async def end_session(self, user_id, server_id):
        """Beregner tid og lagrer til database."""
        if (user_id, server_id) in self.active_sessions:
            game_name, start_time = self.active_sessions.pop((user_id, server_id))
            duration = int(time.time() - start_time)
            
            if duration > 10:
                update_game_time(user_id, server_id, game_name, duration)

    def format_time(self, seconds):
        """Konverterer sekunder til timer og minutter."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours}t {minutes}m"
        return f"{minutes}m"

    async def generate_scoreboard_embed(self, guild):
        """Lager det globale scoreboardet (Spill + Total tid)."""
        data = get_server_scoreboard(guild.id)
        
        embed = discord.Embed(
            title=f"🌍 Global Spill-topp - {guild.name}",
            description="Total tid brukt i spill av alle medlemmer på serveren.",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )

        if not data:
            embed.description = "Ingen spilldata registrert ennå. Begynn å spille!"
            return embed

        table = "```\nRank  Spill                Total tid\n"
        table += "--------------------------------------\n"
        
        # Merk: data fra db_handler inneholder nå (game_name, sum_seconds)
        for i, (game_name, seconds) in enumerate(data, 1):
            game = game_name[:20]
            time_str = self.format_time(seconds)
            table += f"{i:<5} {game:<20} {time_str}\n"
        
        table += "```"
        embed.add_field(name="Server-statistikk", value=table, inline=False)
        embed.set_footer(text="Oppdateres automatisk hver time • Bruk !game_time for din stat")
        return embed

    @tasks.loop(hours=1)
    async def scoreboard_updater(self):
        """Går gjennom alle servere og oppdaterer låste meldinger."""
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            msg_data = get_scoreboard_msg(guild.id)
            if msg_data:
                channel_id, message_id = msg_data
                channel = guild.get_channel(int(channel_id))
                if channel:
                    try:
                        msg = await channel.fetch_message(int(message_id))
                        embed = await self.generate_scoreboard_embed(guild)
                        await msg.edit(embed=embed)
                    except Exception:
                        pass

    @commands.command(name="game_time")
    async def game_time(self, ctx):
        """Viser brukerens personlige topp 5 spill på denne serveren."""
        data = get_personal_stats(ctx.author.id, ctx.guild.id)
        
        if not data:
            return await ctx.send(f"❓ Jeg har ikke registrert noe spilletid på deg ennå, {ctx.author.display_name}.")

        embed = discord.Embed(
            title=f"🎮 Dine timer - {ctx.author.display_name}",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        
        total_personal_seconds = sum(item[1] for item in data)
        desc = f"Du har spilt totalt **{self.format_time(total_personal_seconds)}** fordelt på dine toppspill:\n\n"
        
        for game, seconds in data:
            desc += f"• **{game}**: {self.format_time(seconds)}\n"
            
        embed.description = desc
        embed.set_footer(text=f"Data for {ctx.guild.name}")
        await ctx.send(embed=embed)

    @commands.command(name="setup_scoreboard")
    @commands.has_permissions(administrator=True)
    async def setup_scoreboard(self, ctx):
        """Setter opp en permanent scoreboard-melding i denne kanalen."""
        try:
            await ctx.message.delete()
        except:
            pass

        embed = await self.generate_scoreboard_embed(ctx.guild)
        msg = await ctx.send(embed=embed)
        save_scoreboard_msg(ctx.guild.id, ctx.channel.id, msg.id)

async def setup(bot):
    await bot.add_cog(GameMonitor(bot))