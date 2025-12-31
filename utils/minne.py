import chromadb
from datetime import datetime
import uuid
import os

# --- KONFIGURASJON ---
# Vi kobler nå til en lokal server (Docker) i stedet for direkte filtilgang.
# Sørg for at Docker kjører på port 8000.
CHROMA_HOST = "localhost"
CHROMA_PORT = 8081

print(f"🔌 Kobler til ChromaDB Server på {CHROMA_HOST}:{CHROMA_PORT}...")

try:
    # Koble til via HTTP (Server-modus)
    client = chromadb.HttpClient(
        host=CHROMA_HOST, 
        port=CHROMA_PORT,
        settings=chromadb.config.Settings(allow_reset=True, anonymized_telemetry=False)
    )
    print("✅ Tilkobling til minne-server opprettet.")
except Exception as e:
    print(f"❌ KRITISK: Kunne ikke koble til ChromaDB Server. Kjører Docker? Feil: {e}")
    # Fallback eller stopp her kan vurderes, men vi lar den kræsje så du ser feilen.
    raise e

# Hent begge samlingene vi trenger
memory_collection = client.get_or_create_collection(name="discord_memory")
log_collection = client.get_or_create_collection(name="system_logs")

def logg_feil(kilde, feilmelding):
    """Lagrer kritiske feil i system-journalen."""
    try:
        ts = datetime.now().timestamp()
        log_collection.add(
            documents=[f"❌ [MINNE-FEIL] Kilde: '{kilde}' | Feil: {feilmelding}"],
            metadatas=[{
                "category": "Error",
                "task": "MinneLagring",
                "timestamp": ts,
                "duration": 0
            }],
            ids=[f"error_{kilde}_{ts}"]
        )
        print(f"⚠️ Feil loggført i journalen: {feilmelding}")
    except Exception as e:
        print(f"💀 KRISE: Klarte ikke logge feilen til DB: {e}")

def lagre(tekst, user, guild_id, channel_id, kategori="Generelt", kilde="Chat"):
    """
    Lagrer minne. Ved feil, logges det til systemjournalen.
    """
    try:
        timestamp = datetime.now().timestamp()
        
        metadata = {
            "user": str(user),
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
            "kategori": str(kategori),
            "kilde": str(kilde),
            "timestamp": timestamp
        }

        # Unik ID
        unik_id = f"{guild_id}_{channel_id}_{uuid.uuid4()}"

        memory_collection.add(
            documents=[tekst],
            metadatas=[metadata],
            ids=[unik_id]
        )
        
    except Exception as e:
        # HER skjer loggingen du ba om
        print(f"❌ Minne-lagringsfeil: {e}")
        logg_feil(kilde=kilde, feilmelding=str(e))

def hent(sokeord, guild_id, n_results=5, ekskluder_kategori=None, kun_kategori=None):
    """Henter minne isolert til server."""
    try:
        server_filter = {
            "$or": [
                {"guild_id": str(guild_id)},
                {"guild_id": "GLOBAL"}
            ]
        }
        
        final_filter = server_filter
        extra_filters = []
        
        if ekskluder_kategori:
            extra_filters.append({"kategori": {"$ne": ekskluder_kategori}})
        
        if kun_kategori:
            extra_filters.append({"kategori": kun_kategori})

        if extra_filters:
            all_conditions = [server_filter] + extra_filters
            final_filter = {"$and": all_conditions}

        res = memory_collection.query(
            query_texts=[sokeord],
            where=final_filter,
            n_results=n_results
        )
        
        historikk = []
        if res['documents'] and res['documents'][0]:
            docs = res['documents'][0]
            metas = res['metadatas'][0]
            
            for i, doc in enumerate(docs):
                meta = metas[i]
                timestamp = meta.get('timestamp', 0)
                bruker = meta.get('user', 'Ukjent')
                # kilde = meta.get('kilde', 'Chat') # Ubrukt variabel fjernet for ryddighet
                kat = meta.get('kategori', 'Generelt')
                
                dato = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')
                historikk.append(f"[{dato}] [{kat}] {bruker}: {doc}")
        
        return "\n".join(historikk) if historikk else None

    except Exception as e:
        print(f"⚠️ Kunne ikke hente minne: {e}")
        return None

def slett_kategori(guild_id, kategori):
    """Sletter alt minne i en kategori for en server."""
    try:
        memory_collection.delete(
            where={
                "$and": [
                    {"guild_id": str(guild_id)},
                    {"kategori": kategori}
                ]
            }
        )
        return True
    except Exception as e:
        print(f"❌ Feil ved sletting: {e}")
        logg_feil(kilde=f"SlettKategori_{kategori}", feilmelding=str(e))
        return False

def søk_i_kilde(spørsmål, kilde_navn, guild_id, antall=5):
    """Søker spesifikt i en kilde (f.eks en bok)."""
    try:
        res = memory_collection.query(
            query_texts=[spørsmål],
            where={
                "$and": [
                    {"kilde": kilde_navn},
                    {"guild_id": str(guild_id)}
                ]
            },
            n_results=antall
        )
        return res['documents'][0] if res['documents'] else []
    except Exception as e:
        print(f"🔍 Søkefeil i kilde '{kilde_navn}': {e}")
        return []