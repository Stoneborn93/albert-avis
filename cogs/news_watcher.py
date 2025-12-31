import discord
import feedparser
import chromadb
import os
import datetime
import asyncio
import re
import time
import aiohttp
import pytz
from discord.ext import commands, tasks
from dotenv import load_dotenv
from ollama import AsyncClient  # <--- Brukes for lokal generering
from utils.ai_motor import ask_gemini # <--- Beholdes som backup
from utils.job_queue import queue_manager
from utils.minne import lagre

load_dotenv()

# --- KONFIGURASJON ---
RSS_FEEDS = {
    "NYHETER_TOPP": "https://www.nrk.no/toppsaker.rss",
    "NYHETER_SPORT": "https://www.nrk.no/sport/toppsaker.rss",
    "SPILL_GAMERNO": "https://www.gamer.no/feeds/general.xml",
    "TECH_TEKNO": "https://www.tek.no/feeds/general.xml",
    "TECH_DIGI": "https://www.digi.no/feeds/general.xml"
}

SUMMARY_CHANNEL_ID = 1454474141565714452
CHROMA_PORT = 8081
NORWAY_TZ = pytz.timezone('Europe/Oslo')
LOCAL_MODEL = "command-r" # Modellen vi bruker lokalt

# Filstier
WEBSITE_FOLDER = "/home/stianborn/min_discord_bot/prosjekt_v2"
HTML_FILENAME = "index.html"
SHORT_SUMMARY_FILENAME = "discord_cache.txt"

class NewsWatcher(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not os.path.exists("./data"): os.makedirs("./data")
        
        print(f"[NewsWatcher] 🔌 Kobler til ChromaDB på port {CHROMA_PORT}...")
        self.chroma_client = chromadb.HttpClient(host='localhost', port=CHROMA_PORT)
        self.collection = self.chroma_client.get_or_create_collection(name="news_articles")
        self.seen_titles = set() 

    async def cog_load(self):
        print("[NewsWatcher] 📰 Starter tidsstyring...")
        if not self.schedule_manager.is_running():
            self.schedule_manager.start()

    def cog_unload(self):
        self.schedule_manager.cancel()

    def clean_html(self, raw_html):
        if not raw_html: return ""
        cleanr = re.compile('<.*?>')
        return re.sub(cleanr, '', raw_html).strip()

    async def ask_local_albert(self, prompt):
        """Hjelpefunksjon for å spørre den lokale modellen."""
        try:
            print(f"[NewsWatcher] 🧠 Albert ({LOCAL_MODEL}) tenker...")
            response = await AsyncClient().generate(model=LOCAL_MODEL, prompt=prompt)
            return response['response']
        except Exception as e:
            print(f"[NewsWatcher] ⚠️ Lokal modell feilet: {e}. Bytter til backup...")
            return None

    async def _fetch_rss_data(self):
        """Henter RSS data og lagrer i ChromaDB."""
        print(f"[NewsWatcher] 🔄 Starter RSS-innhenting...")
        total_new = 0
        HEADERS = {'User-Agent': 'Mozilla/5.0'}

        for category, rss_url in RSS_FEEDS.items():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(rss_url, headers=HEADERS, timeout=15) as response:
                        if response.status != 200: continue
                        xml_data = await response.text()
                        feed = feedparser.parse(xml_data)

                if not feed or not hasattr(feed, 'entries'): continue

                for entry in feed.entries:
                    url = entry.get('link')
                    title = entry.get('title', 'Ingen tittel')
                    
                    if not url or self.collection.get(ids=[url])['ids']: continue
                    
                    title_fingerprint = title[:50].lower()
                    if title_fingerprint in self.seen_titles: continue

                    summary = self.clean_html(entry.get('summary', entry.get('description', '')))
                    
                    self.collection.add(
                        documents=[f"[{category}] {title}: {summary}"],
                        metadatas=[{"category": category, "timestamp": datetime.datetime.now().timestamp()}],
                        ids=[url]
                    )
                    self.seen_titles.add(title_fingerprint)
                    total_new += 1
            except Exception as e:
                print(f"❌ RSS Feil ({category}): {e}")
        print(f"[NewsWatcher] 📦 Runden ferdig. Fant {total_new} nye saker.")

    async def generate_midnight_content(self, start_ts, end_ts, date_str):
        """Genererer innhold lokalt med Command-R."""
        print("[NewsWatcher] 🏭 Starter nattproduksjon med Lokal AI...")
        
        results = self.collection.get(
            where={"$and": [{"timestamp": {"$gte": start_ts}}, {"timestamp": {"$lt": end_ts}}]}
        )
        
        if not results['documents']:
            print("[NewsWatcher] ⚠️ Ingen nyheter funnet for i dag.")
            return False

        # Begrenser tekstmengden litt for å ikke kvele den lokale modellen
        # Command-R har stort vindu (128k), men vi holder det ryddig.
        raw_text = "\n".join(results['documents'])
        
        # --- STEG 1: KORT VERSJON (DISCORD) ---
        short_prompt = (
            f"Du er nyhetsankeret Albert. Oppsummer dagens viktigste saker ({date_str}) kort og konsist for Discord.\n"
            f"Bruk punktorlister og emojis.\n"
            f"Maks 1500 tegn totalt.\n"
            f"Ikke bruk markdown overskrifter (#), bruk heller fet tekst (**).\n\n"
            f"NYHETSKILDER:\n{raw_text[:12000]}"
        )
        
        # Prøv lokalt først, så backup
        short_summary = await self.ask_local_albert(short_prompt)
        if not short_summary:
            short_summary = await ask_gemini(short_prompt)

        with open(os.path.join(WEBSITE_FOLDER, SHORT_SUMMARY_FILENAME), "w", encoding="utf-8") as f:
            f.write(short_summary)
        print("[NewsWatcher] ✅ Kort versjon lagret (Lokal).")

        # --- STEG 2: LANG VERSJON (HTML) ---
        long_prompt = (
            f"Du er redaktør for nettavisen 'Itchy Norwegian News'.\n"
            f"Skriv hovedinnholdet til dagens utgave ({date_str}) i HTML-format.\n"
            f"Regler:\n"
            f"1. IKKE skriv <html>, <head> eller <body>. Start rett på <h2>.\n"
            f"2. Bruk <h2> for seksjoner (f.eks. 'Gaming', 'Teknologi', 'Verden').\n"
            f"3. Bruk <p> for avsnitt.\n"
            f"4. Vær grundig, kritisk og detaljert.\n"
            f"5. Ikke inkluder kodeblokker (```html), kun rå tekst.\n\n"
            f"NYHETSGRUNNLAG:\n{raw_text[:20000]}"
        )

        html_body = await self.ask_local_albert(long_prompt)
        if not html_body:
            html_body = await ask_gemini(long_prompt)

        # Rens bort markdown hvis modellen glemte seg
        html_body = html_body.replace("```html", "").replace("```", "")

        # --- STEG 3: SETT SAMMEN HTML ---
        full_html = f"""
        <!DOCTYPE html>
        <html lang="no">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Dagens Nyheter - {date_str}</title>
            <style>
                body {{
                    background-color: #121212;
                    color: #e0e0e0;
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    margin: 0;
                    padding: 0;
                }}
                .container {{
                    max_width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                header {{
                    background-color: #1f1f1f;
                    padding: 40px 20px;
                    text-align: center;
                    border-bottom: 2px solid #333;
                    margin-bottom: 40px;
                }}
                h1 {{
                    font-family: 'Georgia', serif;
                    font-size: 2.5em;
                    margin: 0;
                    color: #ffffff;
                    letter-spacing: 1px;
                }}
                .date {{
                    color: #888;
                    font-size: 0.9em;
                    margin-top: 10px;
                    text-transform: uppercase;
                }}
                h2 {{
                    color: #bb86fc;
                    border-bottom: 1px solid #333;
                    padding-bottom: 10px;
                    margin-top: 40px;
                    font-family: 'Georgia', serif;
                }}
                p {{
                    margin-bottom: 15px;
                    font-size: 1.1em;
                }}
                .article-box {{
                    background-color: #1e1e1e;
                    padding: 25px;
                    border-radius: 8px;
                    margin-bottom: 30px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.3);
                }}
                footer {{
                    text-align: center;
                    padding: 40px;
                    color: #555;
                    font-size: 0.8em;
                    margin-top: 50px;
                    border-top: 1px solid #333;
                }}
                a {{ color: #03dac6; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <header>
                <h1>Itchy Norwegian News</h1>
                <div class="date">{date_str}</div>
            </header>
            
            <div class="container">
                <div class="article-box">
                    {html_body}
                </div>
            </div>

            <footer>
                Generert av Albert AI (Lokal) • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
            </footer>
        </body>
        </html>
        """

        with open(os.path.join(WEBSITE_FOLDER, HTML_FILENAME), "w", encoding="utf-8") as f:
            f.write(full_html)
        print("[NewsWatcher] ✅ Lang HTML-versjon lagret (Lokal).")
        return True

    async def publish_to_discord(self):
        """Leser filen og poster til Discord."""
        print("[NewsWatcher] 🚀 Publisering til Discord...")
        channel = self.bot.get_channel(SUMMARY_CHANNEL_ID)
        if not channel: return

        filepath = os.path.join(WEBSITE_FOLDER, SHORT_SUMMARY_FILENAME)
        if not os.path.exists(filepath): return

        with open(filepath, "r", encoding="utf-8") as f:
            short_text = f.read()

        final_msg = "## 🗞️ Here are yesterday's news.\n"
        final_msg += "🌐 Les den fulle, detaljerte utgaven her: [https://nyheter.itchynorwegian.no](https://nyheter.itchynorwegian.no)\n\n"
        final_msg += short_text

        if len(final_msg) <= 2000:
            await channel.send(final_msg)
        else:
            parts = [final_msg[i:i+1900] for i in range(0, len(final_msg), 1900)]
            for part in parts: await channel.send(part)

    # --- HOVED-LOOP ---
    @tasks.loop(minutes=1)
    async def schedule_manager(self):
        now = datetime.datetime.now(NORWAY_TZ)

        # 1. HENT
        if now.minute == 0 and now.hour in [6, 12, 18]:
            await self._fetch_rss_data()
        elif now.hour == 23 and now.minute == 58:
            await self._fetch_rss_data()

        # 2. PRODUSER (NATT)
        if now.hour == 23 and now.minute == 59:
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()
            dato_str = now.strftime('%d.%m.%Y')
            await self.generate_midnight_content(start_of_day, end_of_day, dato_str)

        # 3. PUBLISER (MORGEN)
        if now.hour == 7 and now.minute == 0:
            await self.publish_to_discord()

    # --- KOMMANDOER ---
    @commands.command(name="produser_avis")
    @commands.has_permissions(administrator=True)
    async def force_production(self, ctx):
        status = await ctx.send("🏭 Starter manuell produksjon (Lokal AI)...")
        now = datetime.datetime.now(NORWAY_TZ)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()
        dato_str = now.strftime('%d.%m.%Y')
        
        success = await self.generate_midnight_content(start_of_day, end_of_day, dato_str)
        if success:
            await status.edit(content="✅ Filene er generert lokalt.")
        else:
            await status.edit(content="⚠️ Produksjon avbrutt.")

    @commands.command(name="hent_nyheter")
    @commands.has_permissions(administrator=True)
    async def force_news_fetch(self, ctx):
        await self._fetch_rss_data()
        await ctx.send("✅ Nyheter hentet.")

    @commands.command(name="nyhets_status")
    async def nyhets_status(self, ctx):
        total = self.collection.count()
        now_no = datetime.datetime.now(NORWAY_TZ).strftime('%H:%M')
        await ctx.send(f"### 📰 Status\n📦 **Artikler:** `{total}`\n🧠 **Modell:** `{LOCAL_MODEL}`\n⌚ **Tid:** `{now_no}`")

    @schedule_manager.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(NewsWatcher(bot))