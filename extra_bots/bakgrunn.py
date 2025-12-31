import discord
import os
import datetime
import chromadb
import asyncio
import aiohttp
import time
import random
from discord.ext import tasks
from dotenv import load_dotenv
from utils.db_handler import log_hardware, log_ai_performance

load_dotenv()

# --- SERVER KOBLING ---
CHROMA_CLIENT = chromadb.HttpClient(host='localhost', port=8081)
# Vi bruker egne kolleksjoner for å skille systemdata fra vanlige minner
log_collection = CHROMA_CLIENT.get_or_create_collection(name="system_logs")
perf_collection = CHROMA_CLIENT.get_or_create_collection(name="ai_performance")

client = discord.Client(intents=discord.Intents.all())

# --- GLOBALE STATS FOR TRACKING ---
rss_stats = {"total": 0, "success": 0}
ai_stats = {"tokens_generated": 0, "total_time": 0}

# --- HJELPEFUNKSJON: NETDATA API ---
async def hent_netdata_stats():
    """Henter utvidet hardware-profilering fra Netdata."""
    base_url = "http://127.0.0.1:19999/api/v1/data"
    stats = {}
    
    async with aiohttp.ClientSession() as session:
        try:
            # 1. CPU Frekvens & IPC
            async with session.get(f"{base_url}?chart=cpu.cpufreq&points=1&after=-1") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    val = data.get('data', [[]])[0]
                    if len(val) > 1: stats['cpu_mhz'] = int(val[1])

            # 2. Temperatur
            temp_charts = ['sensors.temperature_k10temp-pci-00c3_temp1_Tctl_input', 'sensors.temperature_acpitz-acpi-0_temp1_input']
            for chart in temp_charts:
                async with session.get(f"{base_url}?chart={chart}&points=1&after=-1") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        val = data.get('data', [[]])[0]
                        if len(val) > 1 and val[1] is not None:
                            stats['temp'] = round(float(val[1]), 1)
                            break

            # 3. CPU Stalled Cycles & IPC (Fra perf-modulen i Netdata)
            async with session.get(f"{base_url}?chart=perf.cpu_insn&points=1&after=-1") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Her regner vi ut IPC basert på rådata hvis tilgjengelig
                    val = data.get('data', [[]])[0]
                    if len(val) > 1: stats['ipc'] = round(float(val[1]) / 1000000, 2) # Forenklet ratio

        except Exception as e:
            print(f"⚠️ Netdata feil: {e}")
    
    return stats

# --- LOGGEFUNKSJONER ---
def logg_event(nivå, hendelse, detaljer="", kategori="system"):
    ts = datetime.datetime.now().timestamp()
    log_id = f"evt_{int(ts)}_{random.randint(100,999)}"
    doc = f"[{nivå}] {hendelse}: {detaljer}"
    
    log_collection.add(
        documents=[doc],
        metadatas=[{"level": nivå, "timestamp": ts, "category": kategori}],
        ids=[log_id]
    )

async def logg_ai_performance_hybrid(model_name, tokens, duration, ram_delta):
    """Logger TPS og ressursbruk til både SQLite og ChromaDB."""
    ts = datetime.datetime.now().timestamp()
    tps = round(tokens / duration, 2) if duration > 0 else 0
    
    # 1. Logg til SQLite (Statistikk)
    # Vi henter kjapt temp og load for kontekst
    load = os.getloadavg()[0]
    # Her bruker vi en dummy-verdi for temp siden vi ikke vil sinke inference med et API-kall
    log_ai_performance(tps, 0.0, load) 

    # 2. Logg til ChromaDB (Semantisk minne)
    perf_collection.add(
        documents=[f"AI Inference: {model_name} genererte {tokens} tokens på {duration}s ({tps} TPS)"],
        metadatas={
            "model": model_name,
            "tps": tps,
            "duration": duration,
            "ram_usage_mb": ram_delta,
            "timestamp": ts
        },
        ids=[f"perf_{int(ts)}"]
    )

# --- TASK LOOPS ---

@tasks.loop(minutes=10)
async def hardware_monitor_loop():
    """Hovedloop for hardware-overvåking (Hybrid-logging)."""
    stats = await hent_netdata_stats()
    load = os.getloadavg()
    
    ts = datetime.datetime.now().timestamp()
    temp = stats.get('temp', 0)
    ipc = stats.get('ipc', 0)
    
    # Beregn suksessrate for RSS
    rss_rate = (rss_stats['success'] / rss_stats['total'] * 100) if rss_stats['total'] > 0 else 100

    # 1. LOGG TIL SQLITE (Via db_handler)
    # Vi estimerer stalled cycles basert på load siden vi ikke har perf-modul for det direkte
    stalled_cycles = round(load[0] * 4.2, 1) 
    log_hardware(temp, ipc, stalled_cycles, load[0])

    # 2. LOGG TIL CHROMADB
    status_doc = (
        f"Systemstatus ved {datetime.datetime.now().strftime('%H:%M')}: "
        f"Temp er {temp}°C, IPC er {ipc}, CPU-load er {load[0]}. "
        f"RSS suksessrate er {rss_rate}%."
    )

    try:
        log_collection.add(
            documents=[status_doc],
            metadatas=[{
                "category": "hardware_snapshot",
                "temp": temp,
                "ipc": ipc,
                "load_1m": load[0],
                "rss_success_rate": rss_rate,
                "timestamp": ts
            }],
            ids=[f"hw_{int(ts)}"]
        )
        print(f"📊 Hybrid-logging utført: {status_doc}")
    except Exception as e:
        print(f"❌ ChromaDB logging feilet: {e}")

# --- DISCORD EVENTS ---

@client.event
async def on_ready():
    print(f"🕵️ Bakgrunnsbot {client.user} er online.")
    logg_event("INFO", "Systemstart", "Hardware-monitorering (Hybrid) er aktivert.")
    
    if not hardware_monitor_loop.is_running():
        hardware_monitor_loop.start()

@client.event
async def on_error(event, *args, **kwargs):
    import traceback
    logg_event("ERROR", f"Discord feil i {event}", traceback.format_exc(), kategori="error")

# --- UTILITY FOR ANDRE MODULER ---
def oppdater_rss_stats(success=True):
    rss_stats['total'] += 1
    if success: rss_stats['success'] += 1

def get_bg_client(): 
    return client