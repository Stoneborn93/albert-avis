import os
import hashlib
import asyncio
import edge_tts
import re
import random
import time
from pydub import AudioSegment, silence
from pydub.effects import speedup, normalize
# Vi logger stemme-generering til systemet
from utils.minne import lagre

# --- KONFIGURASJON ---
CACHE_DIR = "./data/voice_cache"
USE_RVC = False 
# Vi bruker "Iselin" som vår "Ida" - en behagelig norsk kvinnestemme
VOICE_NAME = "nb-NO-IselinNeural" 

if not os.path.exists(CACHE_DIR): os.makedirs(CACHE_DIR)

def get_filename_hash(text, mood):
    clean_text = text.lower().strip().replace("!", "").replace(".", "").replace("?", "")
    # Ny hash: _ida_v1 (Sikrer at vi regenererer filer med den nye stemmen)
    unique_str = f"{clean_text}_{mood}_ida_v1" 
    return hashlib.md5(unique_str.encode('utf-8')).hexdigest()

def get_voice_settings(name):
    """
    Beregner stemme basert på navn.
    Navnet "FORTELLER" gir alltid en dypere, roligere variant.
    """
    name = name.upper().strip()
    
    # 1. FORTELLERSTEMMEN (Litt dypere og tregere)
    if name == "FORTELLER":
        return "-5Hz", "-5%"

    # 2. KARAKTERSTEMMER (Deterministisk tilfeldighet basert på navn)
    seed_val = sum(ord(char) for char in name)
    random.seed(seed_val)

    possible_pitches = ["-2Hz", "+0Hz", "+2Hz", "+4Hz"]
    possible_rates = ["-5%", "+0%", "+5%", "+10%"]

    pitch = random.choice(possible_pitches)
    rate = random.choice(possible_rates)
    
    return pitch, rate

def analyze_text(text):
    """
    1. Henter ut metadata [CHARACTERS: ...]
    2. Fjerner metadata fra teksten (så det ikke leses høyt).
    3. Analyserer hvem som snakker ved å se på kontekst + metadata.
    """
    # --- 1. SJEKK ETTER METADATA ---
    known_characters = []
    meta_match = re.search(r'\[CHARACTERS:(.*?)\]', text)
    if meta_match:
        # Hent ut navnene
        chars_str = meta_match.group(1)
        known_characters = [c.strip() for c in chars_str.split(',') if c.strip()]
        
        # --- 2. FJERN METADATA FRA TEKSTEN ---
        text = re.sub(r'\[CHARACTERS:.*?\]', '', text).strip()

    # --- 3. ANALYSE AV TEKST ---
    parts = re.split(r'(".*?")', text)
    analyzed_segments = []
    
    # Ord som ofte starter setninger men IKKE er navn
    blacklist = ["Han", "Hun", "De", "Det", "Der", "Da", "Men", "Og", "Vi", "Jeg", "Du", "Plutselig", "Siden", "Etterpå"]
    
    for i, part in enumerate(parts):
        if not part.strip(): continue

        if part.startswith('"') and part.endswith('"'):
            # --- DETTE ER DIALOG ---
            content = part.replace('"', '').strip()
            speaker = "Ukjent_Karakter" # Fallback
            found_in_text = False
            
            # A. SJEKK ETTER SITATET ("Hei," sa Torvin)
            if i + 1 < len(parts):
                next_part = parts[i+1]
                match = re.search(r'(?:sa|sier|hvisket|ropte|spurte|svarte|brølte|tenkte|mumlet|skrek)\s+([A-ZÆØÅ][a-zæøå]+)', next_part)
                if match:
                    potential_name = match.group(1)
                    if potential_name not in blacklist:
                        speaker = potential_name
                        found_in_text = True

            # B. SJEKK FØR SITATET (Torvin reiste seg. "Hei.")
            if not found_in_text and i > 0:
                prev_part = parts[i-1]
                possible_names = re.findall(r'\b([A-ZÆØÅ][a-zæøå]+)\b', prev_part)
                
                if possible_names:
                    for name in reversed(possible_names):
                        if name not in blacklist:
                            speaker = name
                            found_in_text = True
                            break

            # C. FALLBACK TIL METADATA
            # Hvis vi ikke fant navnet i teksten, men Gemini fortalte oss hvem som er med:
            if not found_in_text and known_characters:
                # Vi velger den første i listen som "default" for denne scenen.
                speaker = known_characters[0]

            analyzed_segments.append((content, speaker))
            
        else:
            # --- DETTE ER FORTELLING ---
            analyzed_segments.append((part.strip(), "FORTELLER"))

    return analyzed_segments

def split_sentences(text):
    """Splitter lang tekst i setninger for pauser."""
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]

def vask_lydfil(file_path, silence_thresh=-45.0, min_silence_len=200):
    try:
        audio = AudioSegment.from_file(file_path)
        chunks = silence.split_on_silence(
            audio,
            min_silence_len=min_silence_len,
            silence_thresh=silence_thresh,
            keep_silence=100
        )
        if not chunks: return file_path
        output_audio = AudioSegment.empty()
        for chunk in chunks: output_audio += chunk
        output_audio = normalize(output_audio)
        output_audio.export(file_path, format="mp3")
        return file_path
    except Exception as e: return file_path

def apply_mood(audio_segment, mood):
    try:
        if mood == "hectic": return speedup(audio_segment, playback_speed=1.15)
        elif mood == "dramatic":
            # Senker farten litt og pitchen litt for dramatikk
            new_rate = int(audio_segment.frame_rate * 0.90)
            audio = audio_segment._spawn(audio_segment.raw_data, overrides={'frame_rate': new_rate})
            return audio.set_frame_rate(44100)
        elif mood == "calm":
             # Roligere tempo
             new_rate = int(audio_segment.frame_rate * 0.95)
             audio = audio_segment._spawn(audio_segment.raw_data, overrides={'frame_rate': new_rate})
             return audio.set_frame_rate(44100)
        return audio_segment
    except Exception as e: return audio_segment

async def generate_voice(text, mood="neutral"):
    start_time = time.time()
    file_hash = get_filename_hash(text, mood)
    cached_file = os.path.join(CACHE_DIR, f"{file_hash}.mp3")
    
    if os.path.exists(cached_file):
        return cached_file

    # Pause-konfigurasjon
    pause_ms = 600
    if mood == "dramatic": pause_ms = 1200 
    elif mood == "hectic": pause_ms = 150

    # 1. Analyser tekst (Inkludert metadata-lesing)
    segments = analyze_text(text)
    
    combined_audio = AudioSegment.empty()
    pause_segment = AudioSegment.silent(duration=pause_ms)
    short_pause = AudioSegment.silent(duration=300)
    
    temp_files = [] 
    segment_counter = 0

    try:
        for content, speaker in segments:
            
            # 2. Hent stemmeinnstillinger
            pitch, rate = get_voice_settings(speaker)
            
            # Mood-justering på toppen av personlig stemme
            if mood == "hectic":
                # Øk tempoet litt
                if "-" in rate: rate = "+0%"
                else: rate = "+15%"

            sentences = split_sentences(content)

            for sentence in sentences:
                if len(sentence) < 2: continue
                
                seg_path = os.path.join(CACHE_DIR, f"temp_{file_hash}_{segment_counter}.mp3")
                temp_files.append(seg_path)
                segment_counter += 1

                communicate = edge_tts.Communicate(
                    sentence, 
                    VOICE_NAME, 
                    rate=rate, 
                    pitch=pitch
                )
                await communicate.save(seg_path)
                
                seg_audio = AudioSegment.from_file(seg_path)
                
                # Velg riktig pause basert på om det er forteller eller dialog
                if speaker == "FORTELLER":
                    combined_audio += seg_audio + pause_segment
                else:
                    combined_audio += seg_audio + short_pause

        # 3. Legg på mood-effekter
        final_audio = apply_mood(combined_audio, mood)

        # 4. Lagre og vask
        temp_full = os.path.join(CACHE_DIR, f"temp_full_{file_hash}.mp3")
        final_audio.export(temp_full, format="mp3")
        final_file = vask_lydfil(temp_full, silence_thresh=-45.0)
        
        if os.path.exists(cached_file): os.remove(cached_file)
        os.rename(final_file, cached_file)
        
        # Rydd opp
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
        if os.path.exists(temp_full) and temp_full != final_file: os.remove(temp_full)

        duration = time.time() - start_time
        
        # LOGG TIL SYSTEMET
        try:
            char_count = len(text)
            lagre(
                tekst=f"Lyd generert ({mood}): {char_count} tegn på {duration:.2f}s",
                user="VoiceEngine",
                guild_id="SYSTEM",
                channel_id="Voice",
                kategori="Performance",
                kilde="Auto"
            )
        except: pass

        return cached_file

    except Exception as e:
        print(f"❌ Voice Engine Error: {e}")
        return None