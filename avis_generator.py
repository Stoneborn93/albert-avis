import os
import datetime
import asyncio
import subprocess
# Husk å importere database-funksjonen din her når den er klar
# from utils.minne import hent_siste_nyheter
from utils.ai_motor import ask_mistral

async def skriv_morgenavis():
    """
    Henter nyheter, genererer HTML og pusher til GitHub.
    """
    print("📰 Setter pressen i gang...")
    
    # 1. Hent data (Placeholder for nå)
    nyheter = [
        {"tittel": "Velkommen til Alberts Avis", "kilde": "System", "tekst": "Dette er første utgave sendt fra Linux-serveren!"},
        {"tittel": "Været i Ørsta", "kilde": "Meteorologisk", "tekst": "Sannsynligvis regn, men god stemning inne."}
    ]

    if not nyheter:
        return

    # 2. Design HTML
    dato = datetime.datetime.now().strftime("%d. %B %Y")
    
    html_innhold = f"""
    <!DOCTYPE html>
    <html lang="no">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Alberts Morgenavis - {dato}</title>
        <style>
            body {{ font-family: 'Georgia', serif; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }}
            .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 40px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
            header {{ text-align: center; border-bottom: 3px double #333; padding-bottom: 20px; margin-bottom: 30px; }}
            h1 {{ font-size: 3em; margin: 0; text-transform: uppercase; letter-spacing: 2px; }}
            .dato {{ font-style: italic; color: #666; margin-top: 5px; }}
            .artikkel {{ border-bottom: 1px solid #ddd; padding: 20px 0; }}
            h2 {{ font-family: 'Arial', sans-serif; margin-bottom: 10px; color: #2c3e50; }}
            .ingress {{ line-height: 1.6; font-size: 1.1em; }}
            footer {{ text-align: center; margin-top: 50px; font-size: 0.8em; color: #999; }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>Alberts Morgenavis</h1>
                <div class="dato">{dato}</div>
            </header>
    """

    for sak in nyheter:
        html_innhold += f"""
            <div class="artikkel">
                <h2>{sak['tittel']}</h2>
                <p class="ingress">{sak['tekst']}</p>
            </div>
        """

    html_innhold += """
            <footer>Generert av Albert AI</footer>
        </div>
    </body>
    </html>
    """

    # 3. Lagre filen
    # VIKTIG: Dette må matche mappen du klonet i Steg 5
    mappe = "./albert-avis" 
    
    # Sjekk at mappen faktisk finnes
    if not os.path.exists(mappe):
        print(f"❌ Feil: Finner ikke mappen '{mappe}'. Har du kjørt git clone?")
        return

    filsti = os.path.join(mappe, "index.html")
    
    with open(filsti, "w", encoding="utf-8") as f:
        f.write(html_innhold)
        
    print(f"✅ Avis trykket: {filsti}")

    # 4. Last opp til GitHub (Linux-kommandoer)
    try:
        # Vi kjører git-kommandoene inne i Avis-mappen (cwd=mappe)
        subprocess.run(["git", "add", "index.html"], cwd=mappe, check=True)
        
        # Sjekk om det er endringer før vi committer
        status = subprocess.run(["git", "status", "--porcelain"], cwd=mappe, capture_output=True, text=True)
        
        if status.stdout.strip():
            subprocess.run(["git", "commit", "-m", f"Ny avis: {dato}"], cwd=mappe, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=mappe, check=True)
            print("🚀 Avisen er publisert på GitHub!")
        else:
            print("ℹ️ Ingen endringer i avisen, skipper opplasting.")
            
    except subprocess.CalledProcessError as e:
        print(f"❌ Git feilet: {e}")
    except Exception as e:
        print(f"❌ Noe gikk galt: {e}")

# Test-kjøring
if __name__ == "__main__":
    asyncio.run(skriv_morgenavis())