import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import chromadb
import re
import time
import hashlib
import random
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi
import google.generativeai as genai
import os
from dotenv import load_dotenv

# Laster inn miljøvariabler fra .env
load_dotenv()

# --- KONFIGURASJON ---
CHROMA_HOST = "localhost"
CHROMA_PORT = 8081
CHROMA_CLIENT = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
GUIDE_COLLECTION = CHROMA_CLIENT.get_or_create_collection(name="game_guides")

# Henter nøkkel fra .env
GEMINI_API_KEY = os.getenv("GEMINI_KEY")

class GamingHarvester:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # Konfigurer Gemini
        if GEMINI_API_KEY:
            genai.configure(api_key=GEMINI_API_KEY)
            self.has_gemini = True
        else:
            self.has_gemini = False
            print("[Harvester] ⚠️ Gemini API-nøkkel mangler i .env (GEMINI_KEY). Autokorrektur vil være begrenset.")

        # STRICT WHITELIST
        self.trusted_domains = [
            # Norske/Nordiske
            "gamer.no", "tek.no", "gamereactor.no", "pressfire.no", 
            "sweclockers.com", "fz.se", 
            
            # Internasjonale giganter
            "ign.com", "gamespot.com", "pcgamer.com", "eurogamer.net", 
            "gameinformer.com", "gamesradar.com", "destructoid.com", 
            "kotaku.com", "polygon.com", "rockpapershotgun.com", 
            "shacknews.com", "vg247.com", "theverge.com",
            
            # Dedikerte guide-sider og wikier
            "fextralife.com", "wiki.gg", "fandom.com", "powerpyx.com", 
            "metabomb.net", "icy-veins.com", "maxroll.gg", "wowhead.com",
            "steamcommunity.com" 
        ]

    def clean_text(self, text):
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def get_content_hash(self, text):
        return hashlib.md5(text[:500].encode()).hexdigest()

    def fetch_youtube_transcript(self, url):
        """Henter transkripsjon (tekst) fra en YouTube-video."""
        try:
            video_id = None
            parsed_url = urlparse(url)
            if "youtube.com" in parsed_url.netloc:
                video_id = parse_qs(parsed_url.query).get("v", [None])[0]
            elif "youtu.be" in parsed_url.netloc:
                video_id = parsed_url.path[1:]
            
            if not video_id:
                return None

            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['no', 'en', 'en-US', 'en-GB'])
            full_text = " ".join([entry['text'] for entry in transcript_list])
            return self.clean_text(full_text)
            
        except Exception:
            return None

    def autocorrect_game_name(self, raw_name):
        """
        Bruker Gemini til å finne korrekt, offisiell tittel.
        """
        print(f"[Harvester] 🧠 Sjekker stavemåte for '{raw_name}'...")
        
        if not self.has_gemini:
            return raw_name

        try:
            model = genai.GenerativeModel('gemini-pro')
            prompt = f"""
            Task: Verify and standardize this video game title.
            Input: "{raw_name}"
            
            Instructions:
            1. If the input is a typo (e.g., "Farming Sim 25"), output the official full title (e.g., "Farming Simulator 25").
            2. If the input is already correct, output it exactly as is.
            3. Do NOT assume it is a different game unless it is clearly a misspelling.
            4. Return ONLY the title.
            """
            response = model.generate_content(prompt)
            corrected = response.text.strip()
            return corrected
        except Exception as e:
            print(f"[Harvester] ⚠️ Gemini feilet i navnesjekk: {e}")
            return raw_name

    async def fetch_raw_data(self, url):
        try:
            response = requests.get(url, headers=self.headers, timeout=random.randint(10, 20))
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            for trash in soup(["script", "style", "nav", "footer", "aside", "header", "form", "button", "iframe", "ins", "ads", "noscript"]):
                trash.decompose()

            tags = soup.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li', 'td', 'div', 'span'])
            
            content = []
            for tag in tags:
                text = self.clean_text(tag.get_text())
                if len(text) > 20 and text not in content:
                    content.append(text)
            
            if not content:
                return None

            return "\n".join(content)
        except Exception:
            return None

    async def harvest_game(self, raw_input):
        # 1. AUTOKORREKTUR
        game_name = self.autocorrect_game_name(raw_input)
        
        if game_name.lower() != raw_input.lower():
            print(f"[Harvester] ✨ Endret navn fra '{raw_input}' -> '{game_name}'")
        
        search_name = game_name
        if len(game_name.split()) == 1:
            search_name = f"{game_name} game"

        print(f"[Harvester] 🤿 Starter Strict-Whitelist søk for {search_name} (Max 50 results)...")
        
        domain_buckets = {dom: [] for dom in self.trusted_domains}
        domain_buckets["youtube"] = []
        
        all_found_urls = []
        
        # 2. TOSPRÅKLIG SØK
        try:
            with DDGS() as ddgs:
                # NORSKE SØK
                norske_queries = [
                    f"Gamer.no {search_name} guide",
                    f"{search_name} tips og triks norsk",
                    f"{search_name} gjennomgang",
                    f"{search_name} guide youtube norsk"
                ]
                for q in norske_queries:
                    print(f"[Harvester] 🇳🇴 Søker (Norsk): {q}")
                    results_gen = ddgs.text(q, max_results=50, region='no-no')
                    results_list = list(results_gen) if results_gen else []
                    print(f"   🔎 Fant {len(results_list)} treff")
                    
                    for r in results_list:
                        if r['href'] not in all_found_urls:
                            all_found_urls.append(r['href'])
                    time.sleep(2)

                # ENGELSKE SØK
                engelske_queries = [
                    f"{search_name} full walkthrough guide",
                    f"{search_name} advanced tips and tricks",
                    f"{search_name} guide youtube"
                ]
                for q in engelske_queries:
                    print(f"[Harvester] 🇬🇧 Søker (Engelsk): {q}")
                    results_gen = ddgs.text(q, max_results=50, region='wt-wt')
                    results_list = list(results_gen) if results_gen else []
                    print(f"   🔎 Fant {len(results_list)} treff")
                    
                    for r in results_list:
                        if r['href'] not in all_found_urls:
                            all_found_urls.append(r['href'])
                    time.sleep(2)

        except Exception as e:
            print(f"[Harvester] ❌ Søkefeil: {e}")

        # 3. SORTER URL-er (STRICT FILTER)
        discarded_count = 0
        approved_count = 0
        
        for url in all_found_urls:
            if "youtube.com" in url or "youtu.be" in url:
                domain_buckets["youtube"].append(url)
                approved_count += 1
                continue

            matched = False
            for dom in self.trusted_domains:
                if dom in url:
                    domain_buckets[dom].append(url)
                    matched = True
                    approved_count += 1
                    break
            
            if not matched:
                discarded_count += 1

        print(f"[Harvester] 🔗 Filtrering ferdig: {approved_count} godkjente. (Kastet {discarded_count} ukjente/usikre)")

        # 4. ROUND ROBIN HENTING
        sources_found = 0
        seen_hashes = set()
        active_buckets = self.trusted_domains + ["youtube"]
        
        while any(domain_buckets.values()) and sources_found < 35:
            for dom in active_buckets:
                if not domain_buckets[dom]:
                    continue
                
                url = domain_buckets[dom].pop(0)
                print(f"[Harvester] 📥 Henter ({sources_found + 1}): {url[:50]}...")
                
                if dom == "youtube":
                    raw_content = self.fetch_youtube_transcript(url)
                else:
                    raw_content = await self.fetch_raw_data(url)
                
                if raw_content and len(raw_content) > 300:
                    name_parts = game_name.lower().split()
                    if not any(part in raw_content.lower() for part in name_parts if len(part) > 3):
                         print(f"   ⚠️  Forkastet (Innhold mangler referanse til spillet)")
                         continue

                    h = self.get_content_hash(raw_content)
                    if h in seen_hashes: continue
                    seen_hashes.add(h)

                    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                    doc_id = f"deep_{game_name.lower().replace(' ', '_')}_{url_hash}"
                    
                    is_nordic = any(x in url for x in [".no", ".se", ".dk", "gamer.no", "tek.no", "sweclockers", "pressfire"])
                    
                    GUIDE_COLLECTION.upsert(
                        ids=[doc_id],
                        documents=[raw_content],
                        metadatas={
                            "game": game_name, 
                            "source": url, 
                            "timestamp": str(time.time()),
                            "lang": "no" if is_nordic else "en"
                        }
                    )
                    sources_found += 1
                    print(f"   ✅ Lagret ({dom}) - Lengde: {len(raw_content)}")
                else:
                    if dom == "youtube":
                        print(f"   ⚠️  Ingen transkripsjon funnet")
                    else:
                        print(f"   ⚠️  Forkastet (Lite/ingen tekst)")

                time.sleep(random.uniform(3.0, 6.0))

        print(f"[Harvester] ✨ Ferdig! Lagret {sources_found} kilder for {game_name}.")
        return sources_found > 0

harvester = GamingHarvester()