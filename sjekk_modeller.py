import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

# Sjekker begge navnene i tilfelle du ikke byttet i .env ennå
api_key = os.getenv("GEMINI_KEY") or os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ Fant ingen API-nøkkel! Sjekk .env filen.")
else:
    genai.configure(api_key=api_key)
    print("🔍 Søker etter tilgjengelige modeller...")
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"✅ {m.name}")
    except Exception as e:
        print(f"❌ Noe gikk galt: {e}")
