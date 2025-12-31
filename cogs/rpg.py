import discord
import asyncio
import os
import re
import random
from datetime import datetime
from discord.ext import commands
from utils.ai_motor import ask_mistral, ask_gemini
from utils.minne import lagre
from utils.voice_engine import generate_voice 

# Konfigurasjon
SUMMARY_CHANNEL = "rpg-oppsummert"
RPG_CATEGORY_NAME = "RPG Eventyr"

PACING = {
    "kort": "Dette er et One-Shot. Høyt tempo, driv historien mot en slutt raskt.",
    "middels": "Standard eventyr. Balanser utforsking, dialog og kamp.",
    "lang": "Episk saga. Bygg verdenen sakte. Introduser lore og detaljer."
}

# --- STRENG FANTASY PROMPT MED METADATA ---
FANTASY_SYSTEM_PROMPT = (
    "Du er en Game Master for et 'High Fantasy' rollespill (D&D-stil).\n\n"
    "VIKTIG TEKNISK INSTRUKS:\n"
    "Start HVERT svar med en liste over karakterer som snakker eller er aktive i scenen (både spillere og NPCer), i klammeparentes.\n"
    "Eksempel: [CHARACTERS: Torvin, Kroverten, Heksa]\n"
    "Deretter skriver du historien som vanlig boktekst (novelle-stil).\n\n"
    "REGLER:\n"
    "1. Handlingen foregår i en fantasiverden, ALDRI i virkeligheten.\n"
    "2. Bruk spillernes karakter-navn (hvis oppgitt), ikke brukernavn.\n"
    "3. ALDRI bruk ekte stedsnavn fra Norge (som Lauvstad, Ørsta).\n"
    "4. Bruk begreper som 'båt' eller 'skip', ikke 'ferge'.\n"
    "5. Hold tonen episk, mystisk og innlevende."
)

class RPG(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {} 

    # --- HJELPEFUNKSJONER ---
    async def send_as_persona(self, channel, text, name="Game Master"):
        # VIKTIG: Fjern [CHARACTERS: ...] før vi viser til spillerne
        clean_text = re.sub(r'\[CHARACTERS:.*?\]', '', text, flags=re.DOTALL).strip()
        
        try:
            hooks = await channel.webhooks()
            hook = discord.utils.get(hooks, name="RPG_Bot")
            if not hook: hook = await channel.create_webhook(name="RPG_Bot")
            avatar = "https://cdn-icons-png.flaticon.com/512/3408/3408569.png"
            msg = await hook.send(content=clean_text, username=name, avatar_url=avatar, wait=True)
            return msg
        except Exception as e:
            msg = await channel.send(f"**{name}:** {clean_text}")
            return msg

    async def neste_tur(self, ctx, game):
        """Håndterer bytte av tur i tur-basert modus."""
        if game["mode"] != "tur": return

        # Øk indeks
        game["turn_index"] = (game["turn_index"] + 1) % len(game["turn_order"])
        neste_spiller_id = game["turn_order"][game["turn_index"]]
        
        # Hent karakterinfo
        neste_spiller = ctx.guild.get_member(neste_spiller_id)
        char_data = game["characters"].get(neste_spiller_id, {"name": "Ukjent"})
        
        navn = char_data['name']
        mention = neste_spiller.mention if neste_spiller else "Spiller"
        
        await ctx.send(f"👉 **Din tur, {navn}!** ({mention})")

    async def klargjor_intro(self, ctx, game, channel_text):
        """Genererer intro i bakgrunnen."""
        try:
            # Bygg intro-prompt med info om karakterene
            intro_prompt = f"Lag en atmosfærisk intro for et rollespill. {game['pacing']}"
            if game["characters"]:
                intro_prompt += "\nIntroduser disse heltene som er tilstede: " + ", ".join([f"{v['name']} ({v['desc']})" for k,v in game['characters'].items()])
            
            # Får tilbake tekst som inkluderer [CHARACTERS: ...]
            raw_response = await ask_gemini(intro_prompt, system_prompt=FANTASY_SYSTEM_PROMPT)
            
            # Lagre i logg
            game["full_transcript"].append(f"DM: {raw_response}")
            
            # Send tekst til chat (vasker bort metadata automatisk)
            await self.send_as_persona(channel_text, raw_response, "Game Master")

            # Generer Lyd (sender RÅTEKST med metadata til voice engine)
            if game.get("use_tts"):
                ren_tekst_for_lyd = raw_response.replace("*", "").replace("_", "").replace("`", "")
                lydfil = await generate_voice(ren_tekst_for_lyd, mood="dramatic")
                
                if lydfil:
                    game["pending_intro_audio"] = lydfil
                    voice_chan_id = game.get("voice_channel_id")
                    if voice_chan_id:
                        vc_chan = ctx.guild.get_channel(voice_chan_id)
                        if vc_chan: await vc_chan.connect()
        
        except Exception as e:
            print(f"Feil under klargjøring av intro: {e}")
            await channel_text.send(f"(Teknisk feil under generering: {e})")

    async def snakk_i_voice(self, ctx, text_with_metadata, mood="neutral"):
        """Genererer lyd og spiller av umiddelbart."""
        if ctx.channel.id not in self.active_games: return
        game = self.active_games[ctx.channel.id]
        if not game.get("voice_channel_id"): return
        voice_channel = ctx.guild.get_channel(game["voice_channel_id"])
        if not voice_channel: return

        try:
            # Send metadata videre til voice engine
            ren_tekst = text_with_metadata.replace("*", "").replace("_", "").replace("`", "")
            
            lydfil_sti = await generate_voice(ren_tekst, mood=mood)
            if not lydfil_sti: return

            bot_vc = ctx.guild.voice_client
            if not bot_vc: bot_vc = await voice_channel.connect()
            elif bot_vc.channel.id != voice_channel.id: await bot_vc.move_to(voice_channel)

            if bot_vc.is_playing(): bot_vc.stop()
            bot_vc.play(discord.FFmpegPCMAudio(lydfil_sti))
            
        except Exception as e: print(f"Voice Error: {e}")

    async def summarize_background(self, cid, text):
        summary = await ask_mistral(
            f"Oppsummer dette kort på norsk for DM (Fantasy-kontekst):\n{text}", 
            system_prompt="Du er en effektiv sekretær."
        )
        if cid in self.active_games:
            self.active_games[cid]["summary_history"].append(f"[Arkiv]: {summary}")

    # ==========================================
    # KOMMANDO: !karakter (Registrering)
    # ==========================================
    @commands.command(name="karakter")
    async def karakter(self, ctx, navn: str, *, beskrivelse: str = "Eventyrer"):
        """Registrer din karakter. Eks: !karakter Torvin Dverg med øks"""
        if ctx.channel.id not in self.active_games: return
        game = self.active_games[ctx.channel.id]
        
        # Lagre karakterdata
        game["characters"][ctx.author.id] = {"name": navn, "desc": beskrivelse}
        game["players"].add(ctx.author.id) 
        
        # Hvis de ikke er i tur-rekkefølgen, legg dem til
        if ctx.author.id not in game["turn_order"]:
            game["turn_order"].append(ctx.author.id)

        await ctx.send(f"👤 **{ctx.author.mention} er nå registrert som: {navn}** ({beskrivelse})")

    # ==========================================
    # KOMMANDO: !modus (Fri / Tur)
    # ==========================================
    @commands.command(name="modus")
    async def modus(self, ctx, valg: str):
        """Sett 'fri' eller 'tur'."""
        if ctx.channel.id not in self.active_games: return
        game = self.active_games[ctx.channel.id]
        
        if valg.lower() == "tur":
            game["mode"] = "tur"
            # Bland rekkefølgen for variasjon
            random.shuffle(game["turn_order"])
            game["turn_index"] = 0
            
            if not game["turn_order"]:
                await ctx.send("⚠️ Ingen spillere registrert enda! Bruk `!karakter`.")
            else:
                first_id = game["turn_order"][0]
                char = game["characters"].get(first_id, {"name": "Noen"})
                await ctx.send(f"🔄 **Tur-modus AKTIVERT!**\nFørste tur: **{char['name']}**")
                
        elif valg.lower() == "fri":
            game["mode"] = "fri"
            await ctx.send("⚡ **Fri modus AKTIVERT!** Alle kan svare når de vil.")

    # ==========================================
    # KOMMANDO: !neste (Hopp over tur)
    # ==========================================
    @commands.command(name="neste")
    async def neste(self, ctx):
        """Tving neste tur (hvis noen sovner)."""
        if ctx.channel.id not in self.active_games: return
        game = self.active_games[ctx.channel.id]
        if game["mode"] == "tur":
            await ctx.send("⏩ Hopper over turen...")
            await self.neste_tur(ctx, game)

    # ==========================================
    # KOMMANDO: !start (Trigger spillet)
    # ==========================================
    @commands.command(name="start")
    async def start_game_trigger(self, ctx):
        """Kjøres av spillerne når de er klare."""
        if ctx.channel.id not in self.active_games: return
        game = self.active_games[ctx.channel.id]
        
        if game["status"] != "venter_på_start":
            await ctx.send("⚠️ Spillet er allerede i gang!")
            return

        # Sjekk om Albert er klar (har han en lydfil?)
        intro_lyd = game.get("pending_intro_audio")
        if game.get("use_tts") and not intro_lyd:
            await ctx.send("✋ **Vent litt, genererer lyd...**\nJeg joiner VC når jeg er klar!")
            return

        # Oppdater status
        game["status"] = "running"
        await ctx.send("🎲 **La eventyret begynne!**")

        if intro_lyd:
            vc_chan = ctx.guild.get_channel(game["voice_channel_id"])
            if vc_chan:
                bot_vc = ctx.guild.voice_client
                if not bot_vc: bot_vc = await vc_chan.connect()
                bot_vc.play(discord.FFmpegPCMAudio(intro_lyd))
            game["pending_intro_audio"] = None
        
        # Hvis tur-modus er på ved start
        if game["mode"] == "tur" and game["turn_order"]:
            first_id = game["turn_order"][0]
            char = game["characters"].get(first_id, {"name": "Noen"})
            await ctx.send(f"👉 Første tur: **{char['name']}**")

    # ==========================================
    # KOMMANDO: !handling (Spille)
    # ==========================================
    @commands.command(name="handling")
    async def handling(self, ctx, *, args: str):
        """Utfører en handling i spillet."""
        if ctx.channel.id not in self.active_games: return
        game = self.active_games[ctx.channel.id]
        
        if game["status"] == "venter_på_start":
            await ctx.send("⛔ Spillet har ikke startet enda! Skriv **!start** når dere er klare.")
            return

        # 1. SJEKK TUR (hvis modus er 'tur')
        if game["mode"] == "tur":
            current_player_id = game["turn_order"][game["turn_index"]]
            if ctx.author.id != current_player_id:
                char = game["characters"].get(current_player_id, {"name": "Noen"})
                await ctx.send(f"⛔ Vent på tur! Det er **{char['name']}** sin tur nå.")
                return

        # 2. IDENTIFISER KARAKTER
        # Hvis spilleren ikke har registrert seg med !karakter, bruk brukernavn
        char_data = game["characters"].get(ctx.author.id, {
            "name": ctx.author.display_name, 
            "desc": "Eventyrer"
        })
        char_name = char_data["name"]

        # Sikre at spilleren er registrert i systemet
        if ctx.author.id not in game["players"]:
            game["players"].add(ctx.author.id)
            if ctx.author.id not in game["turn_order"]:
                game["turn_order"].append(ctx.author.id)

        # 3. KONSTRUER INPUT TIL AI
        # Her sender vi "Torvin svinger øksen" i stedet for "User123 svinger øksen"
        prompt_input = f"{char_name} ({char_data['desc']}) handling: {args}"
        
        game["log"].append(prompt_input)
        game["full_transcript"].append(prompt_input)

        if len(game["log"]) > 15:
            old = game["log"][:5]
            game["log"] = game["log"][5:]
            asyncio.create_task(self.summarize_background(ctx.channel.id, "\n".join(old)))

        async with ctx.channel.typing():
            hist = "\n".join(game["summary_history"])
            now = "\n".join(game["log"])
            
            prompt = (
                f"{game['pacing']}\nARKIV:\n{hist}\nNÅ:\n{now}\n\n"
                "VIKTIG: Start svaret med en av disse taggene for å sette stemningen:\n"
                "[CALM], [HECTIC], [DRAMATIC], [NEUTRAL].\n"
                "HUSK: Start svaret med [CHARACTERS: Navn1, Navn2] før teksten."
            )
            
            raw_svar = await ask_gemini(prompt, system_prompt=FANTASY_SYSTEM_PROMPT)
            
            mood = "neutral"
            ren_tekst = raw_svar
            
            if "[HECTIC]" in raw_svar: mood = "hectic"
            elif "[DRAMATIC]" in raw_svar: mood = "dramatic"
            elif "[CALM]" in raw_svar: mood = "calm"
            
            ren_tekst = ren_tekst.replace("[HECTIC]", "").replace("[DRAMATIC]", "").replace("[CALM]", "").replace("[NEUTRAL]", "").strip()
            
            game["log"].append(f"DM: {ren_tekst}")
            game["full_transcript"].append(f"DM: {ren_tekst}")
            
            # Send tekst (vasker bort metadata)
            await self.send_as_persona(ctx.channel, ren_tekst)
            
            if game.get("use_tts"):
                asyncio.create_task(self.snakk_i_voice(ctx, ren_tekst, mood=mood))

            # 4. GÅ TIL NESTE TUR (hvis tur-modus)
            if game["mode"] == "tur":
                await self.neste_tur(ctx, game)

    # ==========================================
    # KOMMANDO: !inviter
    # ==========================================
    @commands.command(name="inviter")
    async def inviter(self, ctx):
        """Inviterer spillere til kanalen."""
        if ctx.channel.id not in self.active_games: return
        game = self.active_games[ctx.channel.id]
        
        if ctx.author.id != game["owner"] and not ctx.author.guild_permissions.administrator:
            await ctx.send("⛔ Kun eier/admin kan invitere.")
            return
        
        voice_chan = ctx.guild.get_channel(game["voice_channel_id"])
        
        for user in ctx.message.mentions:
            if user.id not in game["players"]:
                await ctx.channel.set_permissions(user, read_messages=True, send_messages=True)
                if voice_chan:
                    await voice_chan.set_permissions(user, connect=True, speak=True, view_channel=True)
                
                game["players"].add(user.id)
                game["turn_order"].append(user.id)
                
                await ctx.send(f"👋 **{user.mention} ble med!** Husk å bruke `!karakter [Navn]`.")

    # ==========================================
    # HOVEDKOMMANDO (!rpg) - START og SLUTT
    # ==========================================
    @commands.command(name="rpg")
    async def rpg(self, ctx, *, args: str):
        args = args.strip()
        
        # --- START NYTT SPILL ---
        if args.lower().startswith("start"):
            if not ctx.guild.me.guild_permissions.manage_channels:
                await ctx.send("⛔ Mangler 'Manage Channels' rettighet!")
                return

            parts = args.split()
            mode = "middels"
            if len(parts) > 1:
                pot_mode = parts[1].lower()
                if pot_mode in PACING: mode = pot_mode
            pacing_txt = PACING.get(mode, PACING["middels"])

            vil_ha_lyd = "tts" in args.lower()
            lyd_status = "PÅ 🔊" if vil_ha_lyd else "AV 🔇"

            cat = discord.utils.get(ctx.guild.categories, name=RPG_CATEGORY_NAME)
            if not cat:
                try:
                    overwrites = {ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False), ctx.guild.me: discord.PermissionOverwrite(read_messages=True)}
                    cat = await ctx.guild.create_category(RPG_CATEGORY_NAME, overwrites=overwrites)
                except: return

            overwrites = {
                ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
                ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True),
                ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True)
            }
            
            # Legg til mentions umiddelbart
            initial_players = {ctx.author.id}
            initial_turn_order = [ctx.author.id]

            for user in ctx.message.mentions:
                overwrites[user] = discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True)
                initial_players.add(user.id)
                if user.id not in initial_turn_order: initial_turn_order.append(user.id)

            base_name = ctx.author.name.lower().replace(' ','-')
            c_name_text = f"eventyr-{base_name}"
            c_name_voice = f"Talekanal-{base_name}"

            try:
                chan_text = await ctx.guild.create_text_channel(c_name_text, category=cat, overwrites=overwrites)
                chan_voice = await ctx.guild.create_voice_channel(c_name_voice, category=cat, overwrites=overwrites)

                # Initialize Game Data
                self.active_games[chan_text.id] = {
                    "owner": ctx.author.id, 
                    "start": datetime.now(),
                    "log": [], "summary_history": [], "full_transcript": [],
                    "players": initial_players, 
                    "characters": {}, # Ny: Lagrer navn og klasse
                    "turn_order": initial_turn_order, # Ny: Rekkefølge
                    "turn_index": 0, # Ny: Hvem sin tur det er
                    "mode": "fri", # fri eller tur
                    "pacing": pacing_txt, 
                    "pacing_raw": mode,
                    "use_tts": vil_ha_lyd,
                    "voice_channel_id": chan_voice.id,
                    "status": "venter_på_start",
                    "pending_intro_audio": None
                }
                
                # Registrer eieren automatisk med brukernavn som start
                self.active_games[chan_text.id]["characters"][ctx.author.id] = {"name": ctx.author.display_name, "desc": "Eventyrer"}
                
                confirm = await ctx.send(f"⚔️ Eventyret er opprettet: {chan_text.mention}")
                
                # Tilpasset velkomstmelding med nye instruksjoner
                velkomst_text = (
                    f"📜 **RPG EVENTYR KLARGJØRES**\n"
                    f"**Lyd:** {lyd_status}\n"
                    f"─────────────────────\n"
                    f"1️⃣ **Registrer deg:** `!karakter [Navn] [Rolle]`\n"
                    f"2️⃣ **Velg modus:** `!modus tur` eller `!modus fri` (Default: Fri)\n"
                    f"3️⃣ **Start:** Gå i talekanalen og skriv `!start`\n"
                    f"─────────────────────\n"
                    f"**Kommandoer:**\n"
                    f"🔹 `!handling [tekst]` - Utfør en handling.\n"
                    f"🔹 `!neste` - Hopp til neste spiller (i tur-modus).\n"
                    f"🔹 `!inviter @navn` - Inviter spillere.\n"
                    f"🔹 `!rpg slutt` - Avslutt spillet."
                )
                
                v_msg = await self.send_as_persona(chan_text, velkomst_text, "Game Master")
                try: await v_msg.pin()
                except: pass
                
                asyncio.create_task(self.klargjor_intro(ctx, self.active_games[chan_text.id], chan_text))

                await asyncio.sleep(4)
                try: 
                    await ctx.message.delete()
                    await confirm.delete()
                except: pass

            except Exception as e: await ctx.send(f"Feil under opprettelse: {e}")
            return

        # --- SLUTT ---
        if args.lower() == "slutt":
            if ctx.channel.id not in self.active_games: return
            game = self.active_games[ctx.channel.id]
            
            if ctx.author.id != game["owner"]:
                await ctx.send(f"⛔ Kun eieren (<@{game['owner']}>) kan avslutte.")
                return

            await ctx.send("🔥 Avslutter eventyret og skriver sagaen...")
            
            async with ctx.channel.typing():
                full_text = "\n".join(game["full_transcript"])
                prompt = f"Skriv en episk saga basert på loggen. Maks 1900 tegn.\nVIKTIG: Skriv på NORSK.\nLogg:\n{full_text}"
                saga = await ask_gemini(prompt, system_prompt="Legendarisk Fantasy-forfatter.")
                
                sum_chan = discord.utils.get(ctx.guild.channels, name=SUMMARY_CHANNEL)
                if not sum_chan:
                    try: sum_chan = await ctx.guild.create_text_channel(SUMMARY_CHANNEL)
                    except: sum_chan = ctx.channel

                if sum_chan: 
                    start_dato = game["start"].strftime('%d-%m-%Y')
                    msg = f"**📜 SAGAEN OM {start_dato}**\n*(Spilt av {', '.join([game['characters'].get(pid, {'name':'Ukjent'})['name'] for pid in game['players']])})*\n─────────────────────\n{saga}"
                    if len(msg) > 2000: msg = msg[:1990] + "..."
                    await sum_chan.send(msg, silent=True)
                
                if game.get("use_tts"):
                    filnavn = f"./data/saga_{ctx.channel.id}.mp3"
                    await sum_chan.send("🎧 **Lager lydbok... vent litt.**", delete_after=10)
                    saga_lyd = await generate_voice(saga, mood="dramatic")
                    if saga_lyd:
                        await sum_chan.send(content=f"🎙️ **Lydbok:** Sagaen om {start_dato}", file=discord.File(saga_lyd), silent=True)
                        try: os.remove(saga_lyd)
                        except: pass

                # RETTET: Bruker riktig navngitte parametere
                lagre(
                    tekst=f"RPG-SAGA: {saga[:600]}...",
                    user="System", 
                    guild_id=ctx.guild.id, 
                    channel_id=ctx.channel.id, 
                    kategori="RPG_LORE",
                    kilde="RPG"
                )
            
            # Opprydding
            voice_chan_id = game.get("voice_channel_id")
            if voice_chan_id:
                vc = ctx.guild.get_channel(voice_chan_id)
                if vc:
                    try: await vc.delete()
                    except: pass
            
            if ctx.guild.voice_client:
                await ctx.guild.voice_client.disconnect()

            await asyncio.sleep(4)
            del self.active_games[ctx.channel.id]
            await ctx.channel.delete()
            return

async def setup(bot):
    await bot.add_cog(RPG(bot))