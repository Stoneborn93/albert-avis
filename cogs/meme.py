import discord
import aiohttp
import random
import datetime
from discord.ext import commands, tasks
# Vi legger til logging slik at meme-aktivitet vises i systemloggen
from utils.minne import lagre

# --- KONFIGURASJON ---
MEME_CHANNEL_NAME = "memes"
SUBREDDITS = ["norge", "dankmemes", "memes", "wholesomememes", "ProgrammerHumor"]

class MemeManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.todays_schedule = set()
        # VIKTIG: Vi starter IKKE loopen her lenger, men i cog_load under.

    async def cog_load(self):
        """Kjøres automatisk når boten er klar."""
        print("[Meme] 🐸 Meme-modul lastet. Starter loop...")
        self.meme_loop.start()

    def cog_unload(self):
        self.meme_loop.cancel()

    async def plan_day(self):
        """Trekker lodd og bestemmer når memes skal komme i dag"""
        self.todays_schedule.clear()
        
        antall = random.randint(1, 5)
        now = datetime.datetime.now()
        start_hour = 6 
        end_hour = 23
        
        if now.hour > start_hour:
            start_hour = now.hour
            if now.minute > 58: start_hour += 1 

        if start_hour >= end_hour:
             print("⚠️ Dagen er snart over, planlegger ingen nye memes før i morgen.")
             return

        possible_times = []
        for h in range(start_hour, end_hour + 1):
            for m in range(0, 60):
                if h == now.hour and m <= now.minute:
                    continue
                possible_times.append((h, m))
        
        if not possible_times: return

        real_count = min(antall, len(possible_times))
        valgte_tidspunkter = random.sample(possible_times, real_count)
        self.todays_schedule = set(valgte_tidspunkter)
        
        print(f"🎲 Meme-lotteriet: {real_count} memes planlagt.")

    async def get_meme(self):
        """Henter 1 tilfeldig meme fra Reddit med 'Falsk ID'"""
        url = f"https://www.reddit.com/r/{random.choice(SUBREDDITS)}/hot.json?limit=50"
        
        # HER ER MAGIEN: Vi later som vi er en vanlig Windows-PC med Chrome
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        print(f"❌ Reddit blokkerte oss igjen! Status: {response.status}")
                        return None
                    
                    data = await response.json()
                    posts = data['data']['children']
                    valid_memes = []
                    
                    for post in posts:
                        item = post['data']
                        if 'url_overridden_by_dest' in item:
                            img = item['url_overridden_by_dest']
                            if img.endswith(('.jpg', '.png', '.gif', '.jpeg')):
                                valid_memes.append(item)
                    
                    if valid_memes:
                        return random.choice(valid_memes)
                    return None
        except Exception as e:
            print(f"❌ Nettverksfeil mot Reddit: {e}")
            return None

    # --- LOOPEN ---
    @tasks.loop(minutes=1)
    async def meme_loop(self):
        now = datetime.datetime.now()
        
        # Ny dag kl 06:00
        if now.hour == 6 and now.minute == 0:
            await self.plan_day()
            return
            
        current_time = (now.hour, now.minute)
        
        if current_time in self.todays_schedule:
            self.todays_schedule.remove(current_time)
            
            channel = discord.utils.get(self.bot.get_all_channels(), name=MEME_CHANNEL_NAME)
            if channel:
                print(f"⏰ Tid for meme! Klokken er {now.strftime('%H:%M')}")
                meme = await self.get_meme()
                if meme:
                    embed = discord.Embed(title=meme['title'], color=discord.Color.random())
                    embed.set_image(url=meme['url_overridden_by_dest'])
                    embed.set_footer(text=f"🎲 Dagens loddtreknings-meme • r/{meme['subreddit']}")
                    await channel.send(embed=embed)
                    print("✅ Meme postet suksessfullt.")
                    
                    # LOGG TIL DATABASEN (NYTT)
                    lagre(
                        tekst=f"Postet meme: {meme['title']} (r/{meme['subreddit']})",
                        user="AutoMeme",
                        guild_id=channel.guild.id,
                        channel_id=channel.id,
                        kategori="Humor",
                        kilde="Reddit"
                    )
                else:
                    print("❌ Klarte ikke hente meme (Reddit 403?).")

    @meme_loop.before_loop
    async def before_meme_loop(self):
        await self.bot.wait_until_ready()
        if not self.todays_schedule:
            await self.plan_day()

    # --- TEST-KOMMANDOER ---
    
    @commands.command()
    async def meme(self, ctx):
        """Henter 1 meme NÅ (for testing)"""
        print(f"🟢 !meme kommando kjørt av {ctx.author}")
        msg = await ctx.send("🔍 Sniker meg forbi Reddit-vaktene...")
        
        meme = await self.get_meme()
        
        if meme:
            embed = discord.Embed(title=meme['title'], color=discord.Color.random())
            embed.set_image(url=meme['url_overridden_by_dest'])
            embed.set_footer(text=f"Manuelt hentet • r/{meme['subreddit']}")
            await msg.edit(content="", embed=embed)
            print("✅ !meme levert.")
        else:
            await msg.edit(content="⛔ Reddit blokkerte oss (403) eller fant ingen bilder.")
            print("❌ !meme feilet.")

    @commands.command()
    async def meme_plan(self, ctx):
        if not self.todays_schedule:
            await ctx.send("📅 Ingen flere memes i dag.")
        else:
            sortert = sorted(list(self.todays_schedule))
            tekst = "**📅 Plan:**\n"
            for t in sortert:
                tekst += f"🕒 `{t[0]:02d}:{t[1]:02d}`\n"
            await ctx.send(tekst)

async def setup(bot):
    await bot.add_cog(MemeManager(bot))