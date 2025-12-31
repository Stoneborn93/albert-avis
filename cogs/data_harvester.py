import discord
import feedparser
import asyncio
import chromadb
import datetime
import os
import sqlite3
import time
import aiohttp
from discord.ext import commands, tasks
from utils.db_handler import log_hardware, get_latest_hw_logs, log_ai_performance, get_latest_ai_perf

# --- KONFIGURASJON ---
EXTRA_FEEDS = {
    "Steam_Patch_Notes": "https://store.steampowered.com/feeds/news.xml",
    "Hardware_Updates": "https://www.tomshardware.com/feeds/all",
}

# VIKTIG ENDRING: Kobler til Server (Docker) i stedet for fil
CHROMA_HOST = "localhost"
CHROMA_PORT = 8081

print(f"[DataHarvester] 🔌 Kobler til ChromaDB på port {CHROMA_PORT}...")
# Bruker HttpClient for å unngå fil-konflikt med Docker
CHROMA_CLIENT = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

# Sikrer at samlingen finnes
COLLECTION = CHROMA_CLIENT.get_or_create_collection(name="raw_intel")

MSG_STORE_FILE = "last_lager_msg.txt"
ADMIN_CHANNEL_ID = 1454818043841740989 
DB_PATH = "./data/albert_stats.db"

class DataHarvester(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.seen_ids = set()
        self.last_msg_id = self.load_msg_id()
        self.start_time = time.time()
        self.harvest_stats = {"success": 0, "fail": 0}

    def load_msg_id(self):
        if os.path.exists(MSG_STORE_FILE):
            with open(MSG_STORE_FILE, "r") as f:
                try: return int(f.read().strip())
                except: return None
        return None

    def save_msg_id(self, msg_id):
        with open(MSG_STORE_FILE, "w") as f:
            f.write(str(msg_id))
        self.last_msg_id = msg_id

    def get_folder_size(self, path):
        """Regner ut størrelsen på en mappe i MB."""
        total_size = 0
        try:
            if os.path.exists(path):
                for dirpath, dirnames, filenames in os.walk(path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        if not os.path.islink(fp):
                            total_size += os.path.getsize(fp)
                return round(total_size / (1024 * 1024), 2)
        except Exception:
            pass
        return 0.0

    def get_db_size(self):
        try:
            if os.path.exists(DB_PATH):
                size_bytes = os.path.getsize(DB_PATH)
                return round(size_bytes / (1024 * 1024), 2)
            return 0.0
        except: return 0.0

    def get_cpu_temp(self):
        for zone in ["thermal_zone0", "thermal_zone1"]:
            path = f"/sys/class/thermal/{zone}/temp"
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        temp = int(f.read().strip()) / 1000
                        return round(temp, 1)
                except: continue
        return 0.0

    async def cog_load(self):
        print("[DataHarvester] 📡 Systemovervåking og lagringsoversikt aktiv.")
        self.harvest_loop.start()
        self.hardware_logger.start()
        self.status_updater.start()

    def cog_unload(self):
        self.harvest_loop.cancel()
        self.hardware_logger.cancel()
        self.status_updater.cancel()

    async def generate_status_text(self):
        now_ts = datetime.datetime.now().timestamp()
        et_dogn_siden = now_ts - (24 * 60 * 60)
        
        # Oppetid formatert
        uptime_sec = int(time.time() - self.start_time)
        d = uptime_sec // 86400
        h = (uptime_sec % 86400) // 3600
        m = (uptime_sec % 3600) // 60
        uptime_str = f"{f'{d}d ' if d > 0 else ''}{h}t {m}m"

        total_attempts = self.harvest_stats["success"] + self.harvest_stats["fail"]
        success_rate = round((self.harvest_stats["success"] / total_attempts) * 100, 1) if total_attempts > 0 else 100.0

        try:
            news_coll = CHROMA_CLIENT.get_or_create_collection(name="news_articles")
            raw_coll = CHROMA_CLIENT.get_or_create_collection(name="raw_intel")
            
            # Sjekk om collection er tom før get()
            if news_coll.count() == 0:
                news_data = {'ids': [], 'metadatas': []}
            else:
                news_data = news_coll.get(include=["metadatas"])

            if raw_coll.count() == 0:
                raw_data = {'ids': [], 'metadatas': []}
            else:
                raw_data = raw_coll.get(include=["metadatas"])

            news_sources = {}; news_24h = 0
            if news_data['metadatas']:
                for m in news_data['metadatas']:
                    if m: # Sikring mot None
                        src = m.get('category', 'Ukjent')
                        news_sources[src] = news_sources.get(src, 0) + 1
                        if m.get('timestamp', 0) > et_dogn_siden: news_24h += 1

            raw_sources = {}; raw_24h = 0
            if raw_data['metadatas']:
                for m in raw_data['metadatas']:
                    if m:
                        src = m.get('source', 'Ukjent')
                        raw_sources[src] = raw_sources.get(src, 0) + 1
                        if m.get('timestamp', 0) > et_dogn_siden: raw_24h += 1

            latest_logs = get_latest_hw_logs(1)
            hw_info = f"`{latest_logs[0][2]}°C` | Load: `{latest_logs[0][5]}`" if latest_logs else "N/A"
            
            ai_perf = get_latest_ai_perf()
            ai_info = f"`{ai_perf[0]} t/s` @ `{ai_perf[1]}°C`" if ai_perf else "Ingen data"

            # Lagringsdata
            # Merk: get_folder_size vil nå returnere 0 eller serverens størrelse, 
            # men vi bryr oss ikke så mye om det akkurat nå siden data ligger i Docker.
            sqlite_mb = self.get_db_size()
            chroma_path_local = "./data/chroma_news" # Denne mappen er mountet i docker
            chroma_mb = self.get_folder_size(chroma_path_local)

            msg = f"### 📦 Systemstatus (Oppdatert: <t:{int(now_ts)}:t>)\n"
            msg += f"🌡️ **Hardware:** {hw_info}\n"
            msg += f"⏱️ **Oppetid:** `{uptime_str}` | 💾 **Lagring:** `{round(sqlite_mb + chroma_mb, 2)} MB` totalt\n"
            msg += f" └ SQLite: `{sqlite_mb} MB` | Chroma: `{chroma_mb} MB`\n\n"
            
            msg += f"**📊 Ytelse & Lagring**\n"
            msg += f" ├ RSS Suksessrate: `{success_rate}%` ({total_attempts} sjekker)\n"
            msg += f" ├ Siste AI-ytelse: {ai_info}\n"
            msg += f" └ ChromaDB Total: `{len(news_data['ids']) + len(raw_data['ids'])}` noder\n\n"

            msg += f"**📰 Nyhetsarkiv** ({len(news_data['ids'])} totalt, {news_24h} siste 24t)\n"
            for src, count in sorted(news_sources.items(), key=lambda x: x[1], reverse=True)[:5]:
                msg += f" ├ {src}: `{count}`\n"
            
            msg += f"\n**📡 Rådata & Intel** ({len(raw_data['ids'])} totalt, {raw_24h} siste 24t)\n"
            for src, count in sorted(raw_sources.items(), key=lambda x: x[1], reverse=True):
                msg += f" ├ {src}: `{count}`\n"
            
            return msg
        except Exception as e:
            return f"⚠️ Kunne ikke generere status: {e}"

    async def update_live_status(self):
        channel = self.bot.get_channel(ADMIN_CHANNEL_ID)
        if not channel: return
        content = await self.generate_status_text()
        if self.last_msg_id:
            try:
                msg = await channel.fetch_message(self.last_msg_id)
                await msg.edit(content=content)
                return
            except: pass
        new_msg = await channel.send(content)
        self.save_msg_id(new_msg.id)

    @tasks.loop(minutes=10)
    async def status_updater(self):
        await self.bot.wait_until_ready()
        await self.update_live_status()

    @tasks.loop(minutes=30)
    async def harvest_loop(self):
        await self.bot.wait_until_ready()
        rss_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8'
        }
        
        for name, url in EXTRA_FEEDS.items():
            try:
                async with aiohttp.ClientSession(headers=rss_headers) as session:
                    async with session.get(url, timeout=15) as response:
                        if response.status == 200:
                            xml_data = await response.text()
                            feed = feedparser.parse(xml_data)
                            
                            if (feed.bozo and not feed.entries) or len(feed.entries) == 0:
                                raise Exception("Parsing feilet.")

                            for entry in feed.entries[:5]:
                                entry_id = entry.get('id', entry.link)
                                if entry_id not in self.seen_ids:
                                    COLLECTION.add(
                                        documents=[f"{entry.title}: {entry.description}"],
                                        metadatas=[{"source": name, "timestamp": datetime.datetime.now().timestamp()}],
                                        ids=[entry_id]
                                    )
                                    self.seen_ids.add(entry_id)
                            self.harvest_stats["success"] += 1
                        else:
                            self.harvest_stats["fail"] += 1
            except Exception: 
                self.harvest_stats["fail"] += 1

    @tasks.loop(minutes=5)
    async def hardware_logger(self):
        try:
            temp = self.get_cpu_temp()
            load = os.getloadavg()[0]
            ipc_sim = round(2.5 - (load * 0.1), 2)
            stalled_sim = round(load * 5.5, 1)
            log_hardware(temp, ipc_sim, stalled_sim, load)
        except Exception as e: print(f"⚠️ Hardware Logger feil: {e}")

    @commands.command(name="lager")
    async def lager_status(self, ctx):
        await self.update_live_status()
        if ctx.channel.id != ADMIN_CHANNEL_ID:
            await ctx.send(f"✅ Dashboard oppdatert.", delete_after=5)

async def setup(bot):
    await bot.add_cog(DataHarvester(bot))