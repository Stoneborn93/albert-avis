import discord
import time
import asyncio
import ollama
import datetime
import chromadb
import os
import subprocess
from discord.ext import commands
# Endret import: Bruker nå den nye minne-modulen
from utils.minne import lagre 

# --- KONFIGURASJON ---
CATEGORY_NAME = "🤖 Bot Kanaler"
ADMIN_CHANNEL = "chat-commands"
LOG_CHANNEL = "albert-logs"

# Database-kobling (Oppdatert til Docker Server)
CHROMA_HOST = "localhost"
CHROMA_PORT = 8081

# Kanaler som skal være SYNLIGE for alle fra start
PUBLIC_CHANNELS = ["meme", "generelt-prat"]

# Kanaler som skal være SKJULTE (Admin only) fra start
HIDDEN_CHANNELS = ["vod-lab", "quiz-room", "albert-logs"] 

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Koble til ChromaDB Server
        print(f"[Admin] 🔌 Kobler til ChromaDB på port {CHROMA_PORT}...")
        try:
            self.chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
            
            # Henter/Lager samlinger (Sikrer at de eksisterer så vi unngår feilmeldinger)
            self.log_collection = self.chroma_client.get_or_create_collection(name="system_logs")
            self.mem_collection = self.chroma_client.get_or_create_collection(name="discord_memory")
            self.news_collection = self.chroma_client.get_or_create_collection(name="news_articles")
            
        except Exception as e:
            print(f"❌ [Admin] KRITISK: Kunne ikke koble til databasen: {e}")

    async def cog_check(self, ctx):
        # Tillat !meg, !slett_meg og !husk for alle, sjekk admin for resten
        if ctx.command.name in ["meg", "slett_meg", "husk"]:
            return True
        return ctx.author.guild_permissions.administrator or await self.bot.is_owner(ctx.author)

    # --- EVENT: KJØRES NÅR BOTEN JOINER NY SERVER ---
    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        print(f"👋 Ble med i ny server: {guild.name}. Starter oppsett...")
        await self.setup_server_structure(guild)

    async def setup_server_structure(self, guild):
        """Bygger kategorier og kanaler med riktige rettigheter"""
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        if not category:
            try:
                category = await guild.create_category(CATEGORY_NAME, overwrites=overwrites)
                print(f"✅ Opprettet kategori: {CATEGORY_NAME}")
            except Exception as e:
                print(f"❌ Kunne ikke lage kategori: {e}")
                return

        admin_chan = discord.utils.get(guild.text_channels, name=ADMIN_CHANNEL)
        if not admin_chan:
            admin_chan = await guild.create_text_channel(ADMIN_CHANNEL, category=category)
            await admin_chan.send(
                "🎛️ **Velkommen til Kontrollpanelet!**\n"
                "Her kan admins styre boten. Ingen andre ser denne kanalen.\n\n"
                "**Kommandoer:**\n"
                "`!reboot_system` - Full restart av bot-tjenesten på Mini-PC.\n"
                "`!status` - Se hvilke kanaler som er synlige.\n"
                "`!veksle [kanalnavn]` - Skru av/på synlighet for en kanal.\n"
                "`!reload_all` - Oppdaterer all kode i alle moduler.\n"
                "`!test_ai` - Sjekker kontakt med lokale og eksterne AI-modeller.\n"
                "`!logg [timer]` - Henter systemlogger fra ChromaDB.\n"
                "`!meg` - Få en fil med alt boten vet om deg (DM).\n"
                "`!husk [info]` - Lagre personlig info i mitt minne.\n"
                "`!slett_meg` - Sletter alle dine data fra boten."
            )

        for name in HIDDEN_CHANNELS:
            chan = discord.utils.get(guild.text_channels, name=name)
            if not chan:
                await guild.create_text_channel(name, category=category)

        for name in PUBLIC_CHANNELS:
            chan = discord.utils.get(guild.text_channels, name=name)
            if not chan:
                new_chan = await guild.create_text_channel(name, category=category)
                await new_chan.set_permissions(guild.default_role, view_channel=True)

    # --- KOMMANDOER FOR Å STYRE KANALER ---

    @commands.command()
    async def setup_server(self, ctx):
        """Kjør denne manuelt hvis boten allerede er i serveren"""
        await ctx.send("🏗️ Bygger/Oppdaterer kanalstruktur...")
        await self.setup_server_structure(ctx.guild)
        await ctx.send("✅ Ferdig!")

    @commands.command()
    async def status(self, ctx):
        """Viser hvilke bot-kanaler som er synlige for folket"""
        status_msg = "**📺 Kanal Status:**\n"
        for channel in ctx.guild.text_channels:
            if channel.category and channel.category.name == CATEGORY_NAME:
                perms = channel.overwrites_for(ctx.guild.default_role)
                is_visible = perms.view_channel
                icon = "🟢 (Synlig)" if is_visible else "🔴 (Skjult)"
                status_msg += f"{icon} `#{channel.name}`\n"
        await ctx.send(status_msg)

    @commands.command()
    async def veksle(self, ctx, channel_name: str):
        """Skru av/på synlighet for en kanal"""
        if channel_name == ADMIN_CHANNEL:
            await ctx.send("⛔ Du kan ikke endre synligheten på admin-kanalen.")
            return

        channel = discord.utils.get(ctx.guild.text_channels, name=channel_name)
        if not channel:
            await ctx.send(f"❌ Finner ikke kanalen `#{channel_name}`.")
            return

        current_perms = channel.overwrites_for(ctx.guild.default_role)
        is_visible = current_perms.view_channel
        new_state = not is_visible
        
        if new_state:
            await channel.set_permissions(ctx.guild.default_role, view_channel=True)
            await ctx.send(f"🟢 Kanalen {channel.mention} er nå **SYNLIG** for alle.")
        else:
            await channel.set_permissions(ctx.guild.default_role, view_channel=False)
            await ctx.send(f"🔴 Kanalen {channel.mention} er nå **SKJULT** (Admin only).")

    # --- ADMIN KOMMANDOER (Reload/Load/Reboot) ---

    @commands.command(name="reboot_system")
    async def reboot_system(self, ctx):
        """Restarter hele Albert-tjenesten på Mini-PC-en via systemctl."""
        confirm_msg = await ctx.send("⚡ **Full systemrestart initiert.** Albert vil være utilgjengelig i ca. 10-15 sekunder mens tjenesten starter på nytt. Skriv `JA` for å bekrefte.")

        def check(m):
            return m.author == ctx.author and m.content == "JA" and m.channel == ctx.channel

        try:
            await self.bot.wait_for('message', check=check, timeout=15.0)
            await ctx.send("🔄 Utfører restart... Se etter meg i loggen om noen sekunder.")
            subprocess.run(["sudo", "systemctl", "restart", "albert"])
            
        except asyncio.TimeoutError:
            await ctx.send("Restart avbrutt (tidsavbrudd).")
        except Exception as e:
            await ctx.send(f"❌ Kunne ikke utføre restart: {e}")

    @commands.command()
    async def load(self, ctx, module: str):
        try:
            await self.bot.load_extension(f'cogs.{module}')
            await ctx.send(f"✅ Modulen `{module}.py` lastet.")
        except Exception as e:
            await ctx.send(f"❌ Feil: {e}")

    @commands.command()
    async def unload(self, ctx, module: str):
        try:
            await self.bot.unload_extension(f'cogs.{module}')
            await ctx.send(f"✅ Modulen `{module}.py` avsluttet.")
        except Exception as e:
            await ctx.send(f"❌ Feil: {e}")

    @commands.command()
    async def reload(self, ctx, module: str):
        try:
            await self.bot.reload_extension(f'cogs.{module}') 
            await ctx.send(f"🔄 Modulen `{module}.py` er relastet.")
        except Exception as e:
            await ctx.send(f"❌ Feil: {e}")

    @commands.command(name="reload_all")
    async def reload_all(self, ctx):
        """Relaster alle aktive moduler samtidig"""
        status_msg = await ctx.send("🔄 **Relaster alle moduler...**")
        extensions = list(self.bot.extensions.keys())
        vellykkede = []
        feilede = []

        for ext in extensions:
            try:
                await self.bot.reload_extension(ext)
                vellykkede.append(ext.split('.')[-1])
            except Exception as e:
                feilede.append(f"{ext.split('.')[-1]} ({e})")

        svar = "### 🔄 Oppdatering fullført\n"
        if vellykkede:
            svar += f"✅ **Vellykket:** `{', '.join(vellykkede)}`\n"
        if feilede:
            svar += f"❌ **Feilet:** `{', '.join(feilede)}`"
            
        await status_msg.edit(content=svar)

    @commands.command(name="test_ai")
    async def test_ai(self, ctx):
        """Tester kontakt med både lokal Ollama og ekstern Gemini"""
        status_msg = await ctx.send("🔍 **Starter AI-diagnose...**")
        local_start = time.time()
        try:
            await asyncio.to_thread(
                ollama.chat, 
                model="command-r", 
                messages=[{'role': 'user', 'content': 'ping'}],
                options={"num_predict": 5}
            )
            local_dur = round(time.time() - local_start, 2)
            local_status = f"✅ **Lokal (Command-R):** OK ({local_dur}s)"
        except Exception as e:
            local_status = f"❌ **Lokal (Command-R):** Feilet ({e})"

        from utils.ai_motor import ask_gemini
        gemini_start = time.time()
        try:
            await ask_gemini("Svar bare 'pong'")
            gemini_dur = round(time.time() - gemini_start, 2)
            gemini_status = f"✅ **Sky (Gemini):** OK ({gemini_dur}s)"
        except Exception as e:
            gemini_status = f"❌ **Sky (Gemini):** Feilet ({e})"

        await status_msg.edit(content=f"### 🧠 AI Diagnose-rapport\n{local_status}\n{gemini_status}")

    @commands.command(name="logg")
    async def logg(self, ctx, timer: int = 24):
        """Henter systemlogger fra ChromaDB for de siste x timene"""
        try:
            fritid = datetime.datetime.now().timestamp() - (timer * 3600)
            results = self.log_collection.get(
                where={"timestamp": {"$gte": fritid}}
            )
            
            if results['documents']:
                svar = f"### 📜 Systemlogg siste {timer} timer:\n"
                # Vis de siste 12 loggene
                log_entries = results['documents'][-12:] 
                for logg in log_entries:
                    svar += f"* {logg}\n"
                await ctx.send(svar[:2000])
            else:
                await ctx.send(f"Ingen logger funnet for de siste {timer} timene.")
        except Exception as e:
            await ctx.send(f"❌ Kunne ikke hente logg: {e}")

    # --- BRUKER-DATA KOMMANDOER ---

    @commands.command(name="husk")
    async def husk(self, ctx, *, info: str):
        """Lar brukeren lagre informasjon om seg selv i Alberts minne."""
        try:
            # OPPDATERT: Bruker den nye lagre()-funksjonen riktig
            lagre(
                tekst=info,
                user=ctx.author.name,
                guild_id=ctx.guild.id,
                channel_id=ctx.channel.id,
                kategori="Brukerinfo",
                kilde="Kommando"
            )
            await ctx.message.add_reaction("🧠")
            await ctx.send(f"Oppfattet, {ctx.author.display_name}. Jeg har lagret dette i minnet mitt.")
        except Exception as e:
            await ctx.send(f"❌ Kunne ikke lagre minne: {e}")

    @commands.command(name="meg")
    async def meg(self, ctx):
        """Sender en .txt fil med alt boten vet om brukeren på DM."""
        user_name = ctx.author.name
        await ctx.message.add_reaction("📁")
        
        # Sjekker nå i de riktige nye samlingene
        collections = {
            "discord_memory": self.mem_collection,
            "system_logs": self.log_collection,
            "news_articles": self.news_collection
        }
        all_found = []
        
        for coll_name, coll in collections.items():
            try:
                res = coll.get()
                for i in range(len(res['ids'])):
                    doc = res['documents'][i]
                    meta = res['metadatas'][i]
                    # Enkelt søk etter brukernavn i tekst eller metadata
                    if user_name.lower() in doc.lower() or any(user_name.lower() in str(v).lower() for v in meta.values()):
                        all_found.append(f"[{coll_name}] {doc} | Meta: {meta}")
            except: continue

        if not all_found:
            await ctx.send(f"Fant ingen lagrede data om deg, {ctx.author.display_name}.")
            return

        file_path = f"data_{user_name}.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"Data for {user_name}\nTotal treff: {len(all_found)}\n\n" + "\n".join(all_found))
        
        try:
            await ctx.author.send(content="Her er dine data:", file=discord.File(file_path))
            await ctx.send(f"✅ Sendt på DM til {ctx.author.mention}")
        except:
            await ctx.send("❌ Kunne ikke sende DM. Sjekk personverninnstillingene dine.")
        finally:
            if os.path.exists(file_path): os.remove(file_path)

    @commands.command(name="slett_meg")
    async def slett_meg(self, ctx):
        """Sletter alle rader i databasen som er knyttet til brukeren."""
        user_name = ctx.author.name
        confirm_msg = await ctx.send(f"⚠️ Er du sikker på at du vil slette ALT jeg vet om deg, {ctx.author.mention}? (Svar 'JA' innen 30 sek)")

        def check(m): return m.author == ctx.author and m.content == "JA"

        try:
            await self.bot.wait_for('message', check=check, timeout=30.0)
            
            collections = {
                "discord_memory": self.mem_collection,
                "system_logs": self.log_collection,
                "news_articles": self.news_collection
            }
            total_deleted = 0
            
            for coll_name, coll in collections.items():
                try:
                    res = coll.get()
                    to_delete = []
                    for i in range(len(res['ids'])):
                        if user_name.lower() in res['documents'][i].lower() or any(user_name.lower() in str(v).lower() for v in res['metadatas'][i].values()):
                            to_delete.append(res['ids'][i])
                    
                    if to_delete:
                        coll.delete(ids=to_delete)
                        total_deleted += len(to_delete)
                except: continue

            await ctx.send(f"🗑️ Sletting fullført. Fjernet {total_deleted} rader knyttet til deg.")
        except asyncio.TimeoutError:
            await ctx.send("Sletting avbrutt.")

async def setup(bot):
    await bot.add_cog(Admin(bot))