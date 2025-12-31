import pymupdf4llm
import pathlib
import os

def extract_text_from_pdf(file_path):
    """
    Bruker PyMuPDF4LLM til å gjøre PDF om til Markdown.
    Dette bevarer tabeller slik at AI-modeller forstår strukturen.
    """
    try:
        if not os.path.exists(file_path):
            print(f"❌ Filen ble ikke funnet: {file_path}")
            return None
            
        # Konverterer til markdown (strålende for LLMer)
        md_text = pymupdf4llm.to_markdown(file_path)
        return md_text
        
    except Exception as e:
        print(f"❌ PDF Markdown Feil: {e}")
        return None

# --- HJELPEFUNKSJON FOR DISCORD-OPPLASTING ---
def save_temp_pdf(file_bytes, filename="temp.pdf"):
    """
    Lagrer bytes fra Discord-vedlegg som en fysisk fil.
    Dette er nødvendig da pymupdf4llm krever en filsti.
    """
    try:
        # Sikrer at vi har en ryddig filsti
        path = pathlib.Path(filename)
        with open(path, "wb") as f:
            f.write(file_bytes)
        return str(path.absolute())
    except Exception as e:
        print(f"❌ Feil ved lagring av temp-fil: {e}")
        return filename