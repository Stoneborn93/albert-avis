import discord
import asyncio
import os
from discord.ext import commands
from dotenv import load_dotenv
from utils.database import init_db

# Laster inn variabler fra .env filen
load_dotenv()

# --- INTENTS ---
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guilds = True
intents.members = True
intents.presences = True # Viktig for GameSpy

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print("--------------------------------------------------")
    print(f'✅ Hovedbot ({bot.user}) er online og klar!')
    
    # LISTER OPP ALLE MODULER SOM ER LASTET INN
    print("🧩 AKTIVE MODULER (COGS):")
    if bot.cogs:
        for cog_name in bot.cogs:
            print(f"   ✅ {cog_name}")
    else:
        print("   ⚠️ Ingen moduler lastet!")
    print("--------------------------------------------------")
    
    await init_db()

async def main():
    # 1. Last inn alle Cogs
    print("📦 Laster filer fra cogs-mappen...")
    for f in os.listdir('./cogs'):
        if f.endswith('.py'):
            try:
                await bot.load_extension(f'cogs.{f[:-3]}')
                # Denne printen kommer FØR on_ready
                print(f"   - Fant fil: {f}") 
            except Exception as e:
                print(f"❌ Kunne ikke laste {f}: {e}")

    # 2. Hent Tokens
    token_main = os.getenv("TOKEN_MAIN")
    token_pepe = os.getenv("TOKEN_PEPE")
    token_bg = os.getenv("TOKEN_BG")

    bot_tasks = []

    # --- HOVEDBOT ---
    if token_main:
        print("🚀 Starter Hovedbot prosess...")
        bot_tasks.append(bot.start(token_main))
    else:
        print("⚠️  ADVARSEL: Fant ikke TOKEN_MAIN.")

    # --- ANDRE BOTER ---
    # (Pepe og Bakgrunn lastes som før hvis de finnes)
    if token_pepe:
        try:
            from extra_bots.pepe import get_pepe_client
            print("🐸 Starter Pepe...")
            pepe = get_pepe_client()
            bot_tasks.append(pepe.start(token_pepe))
        except: pass

    if token_bg:
        try:
            # Prøver å finne filen enten i roten eller extra_bots
            try:
                from extra_bots.bakgrunn import get_bg_client
            except ImportError:
                from bakgrunn import get_bg_client
            
            print("🕵️ Starter Bakgrunnsbot...")
            bg = get_bg_client()
            bot_tasks.append(bg.start(token_bg))
        except: pass

    # 4. Kjør
    if bot_tasks:
        await asyncio.gather(*bot_tasks)
    else:
        print("❌ Ingen tokens funnet.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Botene er stoppet.")