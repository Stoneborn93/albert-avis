import asyncio
import os
import google.genai # Importerer hele pakken for å sjekke versjon
from google import genai # Importerer klienten
from dotenv import load_dotenv
import sys

load_dotenv()

async def test_bilde():
    print("="*30)
    print("🧪 Tester Google Imagen...")
    print(f"🐍 Python versjon: {sys.version.split()[0]}")
    
    # SJEKK VERSJONEN I KODEN
    try:
        version = google.genai.__version__
        print(f"📦 google-genai versjon: {version}")
    except:
        print("📦 Klarte ikke finne versjonsnummer!")

    print("="*30)

    api_key = os.getenv("GEMINI_KEY")
    if not api_key:
        print("❌ Fant ingen GEMINI_KEY i .env filen!")
        return

    client = genai.Client(api_key=api_key)
    
    try:
        print("Forsøker å generere bilde...")
        # Vi bruker en veldig liten config for å bare teste at funksjonen finnes
        response = client.models.generate_image(
            model='imagen-3.0-generate-001',
            prompt='Test',
            config={'number_of_images': 1}
        )
        print("✅ SUKSESS! Funksjonen 'generate_image' finnes og virker.")
        
    except AttributeError as e:
        print(f"\n❌ FEIL (Versjonsproblem): {e}")
        print("-> Konklusjon: Biblioteket er FORTSATT for gammelt.")
    except Exception as e:
        # Hvis vi får en annen feil (f.eks. API key feil), betyr det at funksjonen i det minste FINNES.
        print(f"\n✅ Delvis suksess: Funksjonen finnes, men feilet på noe annet: {e}")

if __name__ == "__main__":
    asyncio.run(test_bilde())