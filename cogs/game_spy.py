import discord
import asyncio
import chromadb
import datetime
import re
from discord.ext import commands, tasks
from collections import Counter
from utils.ai_motor import ask_gemini
from utils.gaming_harvester import GamingHarvester
from dotenv import load_dotenv

# Laster .env for sikkerhets skyld, selv om harvester/ai_motor tar seg av det meste
load_dotenv()

# Initialiserer harvesteren
harvester = GamingHarvester()

# --- KONFIGURASJON ---
CHROMA_HOST = "localhost"
CHROMA_PORT = 8081

CHROMA_CLIENT = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
GAME_COLLECTION = CHROMA_CLIENT.get_or_create_collection(name="game_stats")
GUIDE_COLLECTION = CHROMA_CLIENT.get_or_create_collection(name="game_guides")

TIME_INCREMENT = 10 
THRESHOLD_MINUTES = 6000 # 100 timer
CLEANUP_DAYS = 180 
STATUS_CHANNEL_ID = 1454801359005290558 

class GameSpy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = Counter()
        self.known_genres = {} 
        self.game_cache = {} 
        
        try:
            results = GAME_COLLECTION.get()
            if results['ids']:
                for i, game_name in enumerate(results['ids']):
                    self.game_cache[game_name] = results['metadatas'][i]
                    if 'genre' in results['metadatas'][i]:
                        self.known_genres[game_name] = results['metadatas'][i]['genre']
        except: pass

    async def cog_load(self):
        print("[GameSpy] 🕵️ Modul lastet. Jeger-modus og Deep Search aktiv.")
        self.spy_loop.start()
        self.cleanup_loop.start()

    def cog_unload(self):
        self.spy_loop.cancel()
        self.cleanup_loop.cancel()

    def clean_game_name(self, name):
        """Fjerner spesialtegn og gjør alt til små bokstaver for sammenligning."""
        return re.sub(r'[^a-zA-Z0-9 ]', '', name).lower().strip()

    async def get_game_genre(self, game_name):
        if game_name in self.known_genres: return self.known_genres[game_name]
        prompt = (
            f"Classify the video game '{game_name}' into ONE of these categories: "
            "FPS, RPG, STRATEGY, MOBA, SPORTS, SIMULATION, HORROR, OTHER. "
            "Answer ONLY with the category name."
        )
        try:
            genre = await ask_gemini(prompt)
            genre = genre.strip().upper().replace(".", "")
            valid_genres = ["FPS", "RPG", "STRATEGY", "MOBA", "SPORTS", "SIMULATION", "HORROR", "OTHER"]
            if genre not in valid_genres: genre = "OTHER"
            self.known_genres[game_name] = genre
            return genre
        except: return "OTHER"

    async def update_game_stats(self, game_name, player_count):
        now_ts = datetime.datetime.now().timestamp()
        clean_new = self.clean_game_name(game_name)
        existing_name = None
        for cached_name in self.game_cache.keys():
            if self.clean_game_name(cached_name) == clean_new:
                existing_name = cached_name
                break
        
        target_name = existing_name or game_name
        data = self.game_cache.get(target_name, {
            "genre": await self.get_game_genre(target_name), 
            "total_minutes": 0, 
            "last_played": now_ts, 
            "tracked": False
        })

        added_minutes = player_count * TIME_INCREMENT
        data["total_minutes"] = int(data.get("total_minutes", 0)) + added_minutes
        data["last_played"] = now_ts
        
        if data["total_minutes"] >= THRESHOLD_MINUTES and not data.get("tracked", False):
            data["tracked"] = True
            await self.announce_milestone(target_name, data["total_minutes"])
            asyncio.create_task(self.trigger_guide_harvest(target_name))
        
        self.game_cache[target_name] = data
        try:
            GAME_COLLECTION.upsert(
                ids=[target_name],
                documents=[f"{target_name} - {data['genre']} - {data['total_minutes']} mins"],
                metadatas=[data]
            )
        except: pass

    async def trigger_guide_harvest(self, game_name):
        success = await harvester.harvest_game(game_name)
        if success:
            print(f"[JEGER] 💎 Rådata for {game_name} er lagret.")

    async def announce_milestone(self, game, minutes):
        channel = self.bot.get_channel(STATUS_CHANNEL_ID)
        hours = int(minutes / 60)
        if channel:
            await channel.send(f"🏆 **Ny milepæl!**\nSpillet **{game}** har passert **{hours} timer**!\n✅ Albert starter nå en Deep Dive innhøsting av guider.")

    @tasks.loop(minutes=TIME_INCREMENT)
    async def spy_loop(self):
        await self.bot.wait_until_ready()
        current_activity = Counter()
        for guild in self.bot.guilds:
            for member in guild.members:
                if not member.bot:
                    for activity in member.activities:
                        if hasattr(activity, 'type') and activity.type == discord.ActivityType.playing:
                            current_activity[activity.name] += 1
        self.active_games = current_activity
        if current_activity:
            for game, count in current_activity.items():
                await self.update_game_stats(game, count)

    @tasks.loop(hours=24)
    async def cleanup_loop(self):
        now_ts = datetime.datetime.now().timestamp()
        removed_games = []
        for game, data in self.game_cache.items():
            if data.get("tracked") and (now_ts - data.get("last_played", 0)) > (CLEANUP_DAYS * 86400):
                data["tracked"] = False
                removed_games.append(game)
        if removed_games:
            channel = self.bot.get_channel(STATUS_CHANNEL_ID)
            if channel: await channel.send(f"🗑️ Opprydding inaktive spill: {', '.join(removed_games)}")

    # --- KOMMANDOER ---

    @commands.command(name="hvaspilles")
    async def hvaspilles(self, ctx):
        if not self.active_games:
            return await ctx.send("📭 Ingen spiller noe nå.")
        msg = "### 🎮 Akkurat nå\n"
        for game, count in self.active_games.most_common(10):
            msg += f"• **{game}**: {count} spillere\n"
        await ctx.send(msg)

    @commands.command(name="spilltid")
    async def game_time(self, ctx, *, spillnavn: str):
        clean_input = self.clean_game_name(spillnavn)
        found = next((g for g in self.game_cache if clean_input in self.clean_game_name(g)), None)
        if found:
            data = self.game_cache[found]
            hours = round(data.get("total_minutes", 0) / 60, 1)
            status = "✅ Overvåkes" if data.get("tracked") else "❌ Nei"
            await ctx.send(f"📊 **{found}**: `{hours} timer` ({status})")
        else:
            await ctx.send(f"Fant ikke '{spillnavn}'.")

    @commands.command(name="guru")
    async def guru_query(self, ctx, *, question: str):
        """Spør Gaming-Guru Albert. Bruker Smart-Router + Deep Dive rådata."""
        async with ctx.typing():
            # 1. SMART ROUTER: Identifiser spillnavnet
            identification_prompt = (
                f"Analyze this user query: '{question}'\n"
                f"Identify if a video game is mentioned. "
                f"If yes, return the FULL OFFICIAL game title (correct typos like 'Battlefiel' to 'Battlefield'). "
                f"If no specific game is mentioned, return exactly: NONE"
            )
            detected_game = await ask_gemini(identification_prompt)
            detected_game = detected_game.strip().replace('"', '').replace("'", "") # Rydd opp svaret

            print(f"[Guru] 🧠 Analyserte forespørsel: '{question}' -> Spill: '{detected_game}'")

            # 2. SØK I MINNET (Med eller uten filter)
            results = None
            
            if detected_game != "NONE":
                # FILTERERT SØK: Vi vet hvilket spill det er, søk KUN i det spillets bøtte
                results = GUIDE_COLLECTION.query(
                    query_texts=[question], 
                    n_results=5, # Færre, men mer presise treff
                    where={"game": detected_game} # <-- MAGIEN SKJER HER
                )
            else:
                # GENERELT SØK: Brukeren nevnte ikke et spesifikt spill
                results = GUIDE_COLLECTION.query(
                    query_texts=[question], 
                    n_results=3
                )

            # 3. BEHANDLE RESULTATENE
            context = ""
            found_data = False
            
            if results and results['documents'] and results['documents'][0]:
                found_data = True
                context_parts = []
                for i, doc in enumerate(results['documents'][0]):
                    meta = results['metadatas'][0][i]
                    source = meta.get('source', 'Ukjent kilde')
                    game_tag = meta.get('game', 'Ukjent spill')
                    context_parts.append(f"[{game_tag}] KILDE {i+1} ({source}):\n{doc}")
                context = "\n\n---\n\n".join(context_parts)
            else:
                context = "Ingen spesifikke rådata funnet i biblioteket."

            # 4. GENERER SVAR MED GEMINI
            # Hvis vi fant et spesifikt spill men ingen data, vær ærlig.
            if detected_game != "NONE" and not found_data:
                await ctx.send(f"🧐 Jeg skjønner at du spør om **{detected_game}**, men jeg har dessverre ikke rukket å samle guider for dette spillet ennå.\n*(Tips: Jeg begynner automatisk å samle data når spillet når 100 timer spilt i serveren!)*")
                return

            system_instruction = (
                f"Du er Albert, en Gaming Guru. Svar på norsk.\n"
                f"Brukeren spør om: {question}\n"
                f"Spill identifisert: {detected_game}\n\n"
                f"Her er informasjonen du har hentet fra din kunnskapsbase:\n{context}\n\n"
                f"INSTRUKSER:\n"
                f"1. Bruk kunnskapsbasen til å gi et presist og taktisk svar.\n"
                f"2. Hvis kildene er uenige, påpek det.\n"
                f"3. Hvis informasjonen mangler i basen, bruk din generelle kunnskap, men nevn at dette er 'generell kunnskap' og ikke fra guidene."
            )
            
            answer = await ask_gemini(system_instruction)
            
            # 5. SEND SVAR (Splitter ved lange meldinger)
            if len(answer) > 2000:
                parts = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
                for part in parts: await ctx.send(part)
            else:
                await ctx.send(answer)

    @commands.command(name="guru_test")
    @commands.has_permissions(administrator=True)
    async def guru_test(self, ctx, *, spillnavn: str):
        """Manuelt trigger dyp innhøsting av guider."""
        # Bruk harvesterens autokorrektur først for å sikre riktig navn
        corrected_name = harvester.autocorrect_game_name(spillnavn)
        
        status = await ctx.send(f"🤿 Albert starter dyp-søking (Deep Dive) etter **{corrected_name}**...")
        
        if await harvester.harvest_game(corrected_name):
            total = GUIDE_COLLECTION.count()
            await status.edit(content=f"✅ Suksess! Biblioteket har nå `{total}` dokumenter. Albert er klar for spørsmål om **{corrected_name}**.")
        else:
            await status.edit(content=f"❌ Fant ingen gode guider for **{corrected_name}**.")

async def setup(bot):
    await bot.add_cog(GameSpy(bot))