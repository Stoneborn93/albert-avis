import discord
import io
import aiohttp
import random
import asyncio
import time
import math
import os
import chromadb
from ollama import AsyncClient
from datetime import datetime, time as dtime
from discord.ext import commands, tasks
from utils.ai_motor import ask_mistral, ask_gemini, ask_openai
from utils.minne import hent, lagre
from utils.database import add_event, get_events
from utils.db_handler import log_ai_performance
from utils.voice_engine import generate_voice 

# --- KONFIGURASJON ---
CHAN_GENERELL = "generelt-prat"
CHAN_GPT      = "chatgpt"
CHAN_KODE     = "kode-hjelp"
CHAN_MAT      = "matlagingstips"
CHAN_RPG      = "rpg-eventyr" 
CMD_CHANNEL   = "chat-commands"

# DATABASE KOBLING (Server-modus)
CHROMA_HOST = "localhost"
CHROMA_PORT = 8081

class HovedChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.local_model = "command-r"
        
        # Sikre at datamappen finnes (for midlertidige filer osv, ikke db)
        if not os.path.exists("./data"): 
            os.makedirs("./data")
        
        # Koble til ChromaDB Server
        print(f"[HovedChat] 🔌 Kobler til ChromaDB på port {CHROMA_PORT}...")
        self.chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        
        # Hent samlinger
        self.log_collection = self.chroma_client.get_or_create_collection(name="system_logs")
        self.news_collection = self.chroma_client.get_or_create_collection(name="news_articles")
        
        # Start tidsstyrte oppgaver
        self.daily_hype.start()
        self.daglig_meny_sjekk.start()

    def cog_unload(self):
        self.daily_hype.cancel()
        self.daglig_meny_sjekk.cancel()

    # --- HJELPEFUNKSJONER ---

    def hent_nyhets_kontekst(self, query, n_results=5):
        """Søker i ChromaDB etter nyheter."""
        try:
            results = self.news_collection.query(
                query_texts=[query],
                n_results=n_results
            )
            if results['documents'] and results['documents'][0]:
                funn = results['documents'][0]
                relevante = [doc for doc in funn if len(doc) > 20]
                if relevante:
                    return "\n".join([f"- {sak}" for sak in relevante])
            return None
        except Exception as e:
            print(f"[RAG] Feil under nyhetssøk: {e}")
            return None

    async def les_vedlegg(self, message):
        """Leser innholdet av tekstfiler lagt ved meldingen."""
        if not message.attachments: return ""
        tekst_innhold = ""
        for vedlegg in message.attachments:
            tillatte_typer = ('text', 'json', 'javascript', 'python', 'xml', 'html')
            er_tekst = vedlegg.content_type and any(t in vedlegg.content_type for t in tillatte_typer)
            if er_tekst or vedlegg.filename.endswith(('.py', '.js', '.html', '.txt', '.md', '.json', '.sh')):
                try:
                    fil_bytes = await vedlegg.read()
                    innhold = fil_bytes.decode('utf-8')
                    tekst_innhold += f"\n\n--- FIL '{vedlegg.filename}' ---\n{innhold}\n"
                except Exception as e: 
                    print(f"Kunne ikke lese vedlegg {vedlegg.filename}: {e}")
        return tekst_innhold

    async def send_smart(self, channel, text):
        """Sender lange meldinger i biter på 1900 tegn."""
        MAX_LEN = 1900 
        for i in range(0, len(text), MAX_LEN):
            await channel.send(text[i:i+MAX_LEN])

    async def spill_av_lyd(self, ctx, filsti):
        """Kobler til VC, spiller lyd, laster opp fil, og kobler fra."""
        if not os.path.exists(filsti): return

        # 1. Last opp filen i chatten først (så den ligger der)
        try:
            await ctx.channel.send(file=discord.File(filsti))
        except Exception as e:
            print(f"Kunne ikke laste opp lydfil: {e}")

        # 2. Bli med i Voice Channel hvis brukeren er der
        if ctx.author.voice and ctx.author.voice.channel:
            vc_channel = ctx.author.voice.channel
            try:
                vc = await vc_channel.connect()
                
                # Spill av
                vc.play(discord.FFmpegPCMAudio(filsti))
                
                # Vent til ferdig
                while vc.is_playing():
                    await asyncio.sleep(1)
                
                await vc.disconnect()
            except Exception as e:
                print(f"Feil med Voice Chat: {e}")
                # Prøv å koble fra hvis vi henger
                if ctx.guild.voice_client:
                    await ctx.guild.voice_client.disconnect()

    async def stream_ai_response(self, channel, prompt, system_prompt, status_msg=None, model="command-r", bot_name="Albert", target_len=1800):
        """Strømmer svar fra lokal AI (Ollama) til Discord."""
        base_status = status_msg.content if status_msg else ""
        if status_msg:
            await status_msg.edit(content=base_status + f"\n🤖 **Starter generering ({model}).**")
        
        start_gen = time.time()
        full_text = ""
        display_msg = None
        last_ui_update = 0

        try:
            async for part in await AsyncClient(timeout=None).chat(
                model=model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': prompt},
                ],
                stream=True,
                options={"num_thread": 8}
            ):
                content = part['message']['content']
                full_text += content
                
                now = time.time()
                if now - last_ui_update > 4:
                    elapsed = now - start_gen
                    words = len(full_text.split())
                    wps = round(words / elapsed, 2) if elapsed > 0 else 0
                    prosent = min(int((len(full_text) / target_len) * 100), 100)
                    bar = "█" * (prosent // 10) + "░" * (10 - (prosent // 10))
                    
                    if status_msg:
                        await status_msg.edit(content=base_status + f"\n🤖 **Fremdrift: `{bar}` {prosent}%**\n⚡ Hastighet: `{wps} ord/sek`")
                    
                    preview = f"✍️ **{bot_name} skriver...**\n\n{full_text}"
                    if not display_msg: 
                        display_msg = await channel.send(preview)
                    else:
                        if len(preview) < 2000: 
                            await display_msg.edit(content=preview)
                    last_ui_update = now

            duration = round(time.time() - start_gen, 2)
            final_wps = round(len(full_text.split()) / duration, 2) if duration > 0 else 0
            
            try:
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    curr_temp = int(f.read().strip()) / 1000
                log_ai_performance(final_wps, round(curr_temp, 1), os.getloadavg()[0])
            except: pass

            if status_msg:
                await status_msg.edit(content=base_status + f"\n✅ **Ferdig på {duration}s.**")

            if display_msg:
                if len(full_text) < 2000: await display_msg.edit(content=full_text)
                else:
                    await display_msg.delete()
                    await self.send_smart(channel, full_text)
            else:
                await self.send_smart(channel, full_text)

            return full_text

        except Exception as e:
            print(f"Streamingfeil: {e}")
            await channel.send("💥 Beklager, hjernen min kortsluttet litt.")
            return "Feil."

    # --- TASKS (PERIODISKE OPPGAVER) ---

    @tasks.loop(time=dtime(hour=23, minute=59))
    async def daily_hype(self):
        """
        1. Henter rådata.
        2. Lager en DETALJERT master-rapport (for hukommelse).
        3. Lagrer master-rapporten i ChromaDB.
        4. Lager en KORT oppsummering for Discord.
        """
        await self.bot.wait_until_ready()
        print("🕛 Kjører Nattlig Nyhetsoppsummering (23:59)...")
        
        channel = discord.utils.get(self.bot.get_all_channels(), name="nyheter")
        if not channel:
            channel = discord.utils.get(self.bot.get_all_channels(), name=CHAN_GENERELL)
        if not channel: return

        try:
            # 1. Hent rådata (øker n_results for å få med ALT)
            results = self.news_collection.query(
                query_texts=["gaming technology ai news today"],
                n_results=30 
            )
            
            if not results['documents'] or not results['documents'][0]:
                print("⚠️ Ingen nyheter funnet i ChromaDB.")
                return

            raw_news = "\n".join(results['documents'][0])
            dato_id = datetime.now().strftime("%Y-%m-%d")

            # 2. Generer MASTER-RAPPORT (Lang og detaljert)
            master_prompt = (
                f"Her er dagens rånyheter:\n{raw_news}\n\n"
                "OPPGAVE: Skriv en omfattende og detaljert dagsrapport. "
                "Få med alle viktige detaljer, tall, navn og sitater. "
                "Ikke tenk på lengde, dette er for arkivering. "
                "Del inn i kategorier: Gaming, Teknologi, AI og Verden."
            )
            print("📝 Genererer Master-rapport for arkivet...")
            master_report = await ask_gemini(master_prompt)

            # 3. Lagre Master-rapporten i ChromaDB
            try:
                self.news_collection.add(
                    documents=[f"MASTER-RAPPORT {dato_id}:\n{master_report}"],
                    metadatas=[{
                        "category": "daily_master_report", 
                        "timestamp": datetime.now().timestamp(),
                        "date": dato_id
                    }],
                    ids=[f"report_{dato_id}"]
                )
                print(f"✅ Master-rapport for {dato_id} lagret i minnet.")
            except Exception as e:
                print(f"⚠️ Kunne ikke lagre master-rapport (kanskje den finnes?): {e}")

            # 4. Generer DISCORD-POST (Kort og gøy) basert på Master-rapporten
            discord_prompt = (
                f"Her er dagens detaljerte rapport:\n{master_report}\n\n"
                "OPPGAVE: Lag en engasjerende 'Døgnoppsummering' for Discord (Max 1800 tegn). "
                "Målgruppen er gamere. Bruk humor, emojis og punktlister. "
                "Start med: '🌙 **Dagens Siste Nytt!**' og nevn at hele rapporten er arkivert i minnet mitt."
            )
            
            print("📢 Genererer Discord-innlegg...")
            discord_svar = await ask_gemini(discord_prompt)
            
            # 5. Send til kanal
            await self.send_smart(channel, discord_svar)
            
        except Exception as e:
            print(f"❌ Feil under daily_hype: {e}")

    @tasks.loop(time=dtime(hour=8, minute=0))
    async def daglig_meny_sjekk(self): pass

    # --- KOMMANDOER ---

    @commands.command(name="generer_rapport")
    @commands.has_permissions(administrator=True)
    async def generer_rapport(self, ctx):
        """Tvinger frem en ny dagsrapport og oppsummering NÅ."""
        await ctx.send("📅 Starter generering av Dagsrapport og Nyhetsoppsummering...")
        await self.daily_hype() # Kaller tasken manuelt
        await ctx.send("✅ Ferdig! Sjekk nyhetskanalen.")

    @commands.command(name="albert_form")
    async def albert_form(self, ctx):
        """Sjekker status på maskinvare og AI-ytelse."""
        try:
            perf_results = self.log_collection.query(
                query_texts=["produserte ord sekunder"],
                where={"category": "system_logs"},
                n_results=5
            )
            hw_results = self.log_collection.query(
                query_texts=["Hardware Status cpu temp"],
                where={"category": "hardware"},
                n_results=1
            )
            
            svar = "### 📊 Systemhelse & Ytelse\n"
            if hw_results['documents'] and hw_results['documents'][0]:
                svar += "**🖥️ Maskinvare (Siste):**\n"
                for doc in hw_results['documents'][0]:
                    svar += f"- {doc}\n"
                svar += "\n"
                
            if perf_results['documents'] and perf_results['documents'][0]:
                svar += "**🚀 Siste jobber:**\n"
                for doc in perf_results['documents'][0]:
                    svar += f"- {doc}\n"
            
            await ctx.send(svar)
        except Exception as e:
            await ctx.send(f"Feil ved henting av logg: {e}")

    @commands.command(name="gem")
    async def gem(self, ctx, *, prompt: str):
        """Direkte prat med Gemini."""
        status_msg = await ctx.send("🔵 **Kobler til Gemini...**")
        try:
            context_list = []
            async for msg in ctx.channel.history(limit=5, before=ctx.message):
                if msg.content:
                    clean_content = msg.content.replace("!gem", "").strip()
                    context_list.append(f"{msg.author.name}: {clean_content}")
            
            context_str = "\n".join(reversed(context_list))
            await status_msg.edit(content="🧠 **Gemini tenker...**")
            
            svar = await ask_gemini(prompt, context_str)
            await status_msg.delete()
            
            header = f"✨ **Gemini-svar til {ctx.author.display_name}:**\n"
            await ctx.reply(header + svar)
            
        except Exception as e:
            await status_msg.edit(content="❌ Kunne ikke kontakte Gemini.")

    @commands.command(name="lagre")
    @commands.has_permissions(administrator=True)
    async def lagre_kommando(self, ctx):
        """Lagrer svaret fra forrige melding i langtidsminnet."""
        try: await ctx.message.delete()
        except: pass

        if not ctx.message.reference:
            msg = await ctx.send("❌ Du må svare på Gemini-meldingen du vil lagre.")
            await asyncio.sleep(5)
            await msg.delete()
            return

        try:
            target_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)

            if target_msg.author == self.bot.user and "✨ **Gemini-svar til" in target_msg.content:
                prompt_text = "Ukjent spørsmål"
                if target_msg.reference:
                    orig_msg = await ctx.channel.fetch_message(target_msg.reference.message_id)
                    prompt_text = orig_msg.content.replace("!gem", "").strip()
                
                gemini_svar = target_msg.content.split(":**\n", 1)[-1]
                leksjon = f"SPØRSMÅL: {prompt_text}\nSVAR: {gemini_svar}"
                
                # OPPDATERT: Bruker ny lagre-syntaks
                lagre(
                    tekst=leksjon, 
                    user=ctx.author.name, 
                    guild_id=ctx.guild.id, 
                    channel_id=ctx.channel.id, 
                    kategori="Lærdom", 
                    kilde="Manuell"
                )
                
                await target_msg.add_reaction("🧠")
            else:
                msg = await ctx.send("❌ Du kan bare lagre svar generert med !gem.")
                await asyncio.sleep(5)
                await msg.delete()
        except Exception as e:
            print(f"❌ Feil ved manuell lagring: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # OPPDATERT: Bruker ny lagre-syntaks
        if not message.content.startswith("!"):
            lagre(
                tekst=message.content, 
                user=message.author.name, 
                guild_id=message.guild.id, 
                channel_id=message.channel.id,
                kategori="Chatlogg",
                kilde="Auto"
            )

        channel_name = message.channel.name
        is_tagged = self.bot.user in message.mentions
        target_channels = [CHAN_GENERELL, CHAN_GPT, CHAN_KODE, CHAN_MAT, CHAN_RPG]

        if is_tagged or channel_name in target_channels:
            if channel_name == CHAN_GENERELL and not is_tagged: return 

            async with message.channel.typing():
                clean = message.content.replace(f"<@{self.bot.user.id}>", "").strip()
                prompt_full = clean + await self.les_vedlegg(message)
                status_msg = await message.channel.send(f"🔍 **Mottatt fra {message.author.name}...**")
                
                # --- RPG LOGIKK ---
                if channel_name == CHAN_RPG:
                    # Spesialprompt for RPG
                    sys_prompt = (
                        "Du er Game Master i et rollespill. "
                        "Vurder situasjonen: Er den [CALM], [HECTIC], [DRAMATIC] eller [NEUTRAL]? "
                        "Start svaret ditt med taggen, f.eks '[HECTIC] Orcen angriper!'. "
                        "Deretter beskriv hva som skjer."
                    )
                    
                    svar = await self.stream_ai_response(message.channel, prompt_full, sys_prompt, status_msg)
                    
                    # Trekk ut stemning og tekst for lyd
                    mood = "neutral"
                    voice_text = svar
                    
                    if "[HECTIC]" in svar: mood = "hectic"
                    elif "[DRAMATIC]" in svar: mood = "dramatic"
                    elif "[CALM]" in svar: mood = "calm"
                    
                    voice_text = voice_text.replace("[HECTIC]", "").replace("[DRAMATIC]", "").replace("[CALM]", "").replace("[NEUTRAL]", "")
                    
                    status_lyd = await message.channel.send("🎤 **Klargjør stemmebåndene...**")
                    filsti = await generate_voice(voice_text, mood=mood)
                    await status_lyd.delete()
                    
                    if filsti:
                        await self.spill_av_lyd(message, filsti)

                # --- VANLIG LOGIKK ---
                elif channel_name == CHAN_GENERELL:
                    sys_prompt = "Du er Albert, en nøytral assistent."
                    kontekst_deler = []
                    
                    # OPPDATERT: Hent minne, men EKSKLUDER RPG-lore!
                    gammel_prat = hent(
                        clean, 
                        guild_id=message.guild.id, 
                        ekskluder_kategori="RPG_LORE"
                    )
                    if gammel_prat: kontekst_deler.append(f"### HISTORIKK:\n{gammel_prat}")
                    
                    nyheter = self.hent_nyhets_kontekst(clean)
                    if nyheter: kontekst_deler.append(f"### NYHETER:\n{nyheter}")
                    
                    if kontekst_deler:
                        sys_prompt = f"Du er Albert. Bruk denne konteksten:\n\n" + "\n\n".join(kontekst_deler)
                    await self.stream_ai_response(message.channel, prompt_full, sys_prompt, status_msg)
                
                elif channel_name == CHAN_KODE:
                    await self.stream_ai_response(message.channel, prompt_full, "Du er en koding-ekspert.", status_msg, bot_name="Kode-Pepe")
                elif channel_name == CHAN_GPT:
                    await self.stream_ai_response(message.channel, prompt_full, "Du er ChatGPT.", status_msg, bot_name="ChatGPT")
                else: 
                    # OPPDATERT: Enkelt søk i generelt minne
                    mem = hent(clean, guild_id=message.guild.id)
                    svar = await ask_gemini(clean, mem)
                    await self.send_smart(message.channel, svar)

async def setup(bot):
    await bot.add_cog(HovedChat(bot))