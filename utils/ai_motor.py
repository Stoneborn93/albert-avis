import aiohttp
import os
import json
import base64
import asyncio
from pathlib import Path
from google import genai
from google.genai import types
from openai import OpenAI
from dotenv import load_dotenv
# Vi logger API-bruk for å ha kontroll
from utils.minne import lagre

load_dotenv()

# --- HJELPEFUNKSJONER (Synkrone) ---
def _run_gemini_sync(api_key, model, contents):
    """Kjører selve Google-kallet synkront (blokkerende)."""
    client = genai.Client(api_key=api_key)
    return client.models.generate_content(
        model=model,
        contents=contents
    )

def _run_imagen_sync(api_key, prompt):
    """Kjører bildegenerering synkront via SDK."""
    client = genai.Client(api_key=api_key)
    return client.models.generate_images(
        model='imagen-3.0-generate-001',
        prompt=prompt,
        config=types.GenerateImageConfig(
            sample_count=1,
            include_rai_reason=True,
            output_mime_type="image/png"
        )
    )

# --- ALBERT / COMMAND-R (Lokal) ---
async def ask_albert(prompt, context_text="", system_prompt=""):
    """
    Sender forespørsel til lokal Ollama (Command-R).
    context_text bør være ferdig formatert fra utils.minne.hent().
    """
    url = os.getenv("OLLAMA_URL")
    
    instruks = (
        "Du er Albert. Bruk informasjonen under 'MINNE/KONTEKST' "
        "til å gi et nøyaktig og personlig tilpasset svar.\n"
    )

    full_prompt = (
        f"System: {system_prompt}\n{instruks}\n"
        f"MINNE/KONTEKST:\n{context_text}\n\n"
        f"Bruker: {prompt}"
    )
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"model": "command-r", "prompt": full_prompt, "stream": False}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['response']
                return f"Albert feil: {resp.status}"
    except Exception as e:
        return f"Ollama Error: {e}"

# --- GEMINI TEKST (Google) ---
async def ask_gemini(prompt, context_text="", system_prompt="", model="gemini-2.0-flash"):
    """
    Sender forespørsel til Google Gemini.
    Kjører i tråd for å unngå å blokkere boten.
    """
    try:
        full_content = (
            f"System Instruks: {system_prompt}\n\n"
            f"RELEVANT KONTEKST:\n{context_text}\n\n"
            f"Oppgave/Spørsmål: {prompt}"
        )
        
        # Kjør det blokkerende kallet i en egen tråd så boten ikke fryser
        response = await asyncio.to_thread(
            _run_gemini_sync, 
            os.getenv("GEMINI_KEY"), 
            model, 
            full_content
        )
        
        # LOGG TIL SYSTEMET
        try:
            lagre(
                tekst=f"Gemini forespørsel ({model})",
                user="AI_Motor",
                guild_id="API",
                channel_id="Google",
                kategori="Kostnad",
                kilde="Auto"
            )
        except: pass
        
        return response.text
    except Exception as e: 
        return f"Gemini feil: {e}"

# --- MISTRAL (Lokal) ---
async def ask_mistral(prompt, context=[], system_prompt=""):
    """
    Enkel Mistral-hjelper. Context kan være liste eller streng.
    """
    url = os.getenv("OLLAMA_URL")
    
    if isinstance(context, list):
        history_txt = "\n".join(context)
    else:
        history_txt = context

    full_prompt = f"System: {system_prompt}\nKontekst:\n{history_txt}\n\nBruker: {prompt}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"model": "mistral", "prompt": full_prompt, "stream": False}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['response']
                return f"Mistral feil: {resp.status}"
    except: 
        return "Mistral sover..."

# --- CHATGPT (OpenAI) ---
async def ask_openai(prompt, context_text="", system_prompt=""):
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_KEY"))
        msgs = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Kontekst:\n{context_text}\n\nSpørsmål: {prompt}"}
        ]
        # OpenAI-kall er også blokkerende, men vi lar det stå for nå (eller bruk to_thread her også hvis du vil)
        res = client.chat.completions.create(model="gpt-4o-mini", messages=msgs)
        
        # LOGG TIL SYSTEMET
        try:
            lagre(
                tekst=f"OpenAI forespørsel (GPT-4o-mini)",
                user="AI_Motor",
                guild_id="API",
                channel_id="OpenAI",
                kategori="Kostnad",
                kilde="Auto"
            )
        except: pass
        
        return res.choices[0].message.content
    except Exception as e: 
        return f"OpenAI feil: {e}"

# --- BILDEGENERERING ---
async def generate_and_save_image(prompt, filename="./data/dagens_quiz.png"):
    """
    Genererer bilde med Imagen 3 via SDK (eller DALL-E 3 fallback).
    """
    # 1. Prøv Google Imagen 3 via SDK
    try:
        response = await asyncio.to_thread(
            _run_imagen_sync,
            os.getenv("GEMINI_KEY"),
            prompt
        )
        
        # Hent første bilde fra responsen
        if response.generated_images:
            image_bytes = response.generated_images[0].image.image_bytes
            with open(filename, "wb") as f:
                f.write(image_bytes)
            
            # Logg
            try:
                lagre("Genererte bilde (Imagen 3 SDK)", "AI_Motor", "API", "Google", "Bilde", "Auto")
            except: pass
            
            return filename
    except Exception as e:
        print(f"Imagen 3 feilet, prøver DALL-E. Feil: {e}")

    # 2. Fallback til DALL-E 3 hvis Gemini feiler
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_KEY"))
        response = client.images.generate(model="dall-e-3", prompt=prompt, n=1)
        image_url = response.data[0].url
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                if resp.status == 200:
                    with open(filename, "wb") as f:
                        f.write(await resp.read())
                    
                    # Logg
                    try:
                        lagre("Genererte bilde (DALL-E 3)", "AI_Motor", "API", "OpenAI", "Bilde", "Auto")
                    except: pass
                    
                    return filename
    except: return None

# --- TTS (OpenAI - for Quiz/Generelt) ---
async def generate_narrator_voice(text, filename="forteller.mp3"):
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_KEY"))
        if len(text) > 4000: text = text[:4000]
        response = client.audio.speech.create(model="tts-1", voice="onyx", input=text)
        response.stream_to_file(Path(filename))
        return filename
    except: return None