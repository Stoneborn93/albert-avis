import discord
import os
import asyncio
import torch
import textwrap
import datetime
import time
import warnings
import torchaudio
import gc
import pysrt
import difflib
import subprocess
import json
from discord.ext import commands
from dotenv import load_dotenv
from transformers import pipeline
from utils.job_queue import queue_manager 
# Importerer den nye motoren og minne-logging
from utils.ai_motor import ask_gemini
from utils.minne import lagre

# Skjul irriterende advarsler
warnings.filterwarnings("ignore", message=".*return_token_timestamps.*")

load_dotenv()

# --- KONFIGURASJON ---
TEMP_DIR = "./data/temp_vods"
CHUNKS_DIR = "./data/temp_vods/chunks"
MODEL_PATH = "./data/models/stian-whisper"

# --- REGLER ---
MAX_LINE_LENGTH = 43  
MAX_LINES = 2         
MIN_DISPLAY_TIME = 3.0  
MAX_BLOCK_DURATION = 8.0 
MAX_MERGE_GAP = 2.0      
MIN_TEXT_LENGTH = 5 
BAD_PHRASES = ["Takk for meg", "Undertekster av", "Amara.org", "Teksting av", "Hade bra", "Vi sees", "Ha det", "...", "???"]

class VodReporter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pipe = None 
        self.vad_model = None
        self.utils = None
        self.stop_requested = False
        
        if not os.path.exists(TEMP_DIR): os.makedirs(TEMP_DIR)
        if not os.path.exists(CHUNKS_DIR): os.makedirs(CHUNKS_DIR)

    async def cog_load(self):
        print("🔄 Starter modell-lasting i bakgrunnen...")
        asyncio.create_task(self.load_models())

    def cog_unload(self):
        self.stop_requested = True

    async def load_models(self):
        from peft import PeftModel, PeftConfig
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
        
        print(f"🧠 Laster Stian-Whisper fra {MODEL_PATH}...")
        try:
            peft_config = PeftConfig.from_pretrained(MODEL_PATH)
            
            base_model = WhisperForConditionalGeneration.from_pretrained(
                peft_config.base_model_name_or_path
            )
            
            model = PeftModel.from_pretrained(base_model, MODEL_PATH)
            processor = WhisperProcessor.from_pretrained(peft_config.base_model_name_or_path, language="no", task="transcribe")

            self.pipe = await asyncio.to_thread(
                pipeline, 
                "automatic-speech-recognition", 
                model=model, 
                tokenizer=processor.tokenizer, 
                feature_extractor=processor.feature_extractor
            )
            print("✅ Stian-Whisper er klar!")
        except Exception as e:
            print(f"❌ Whisper feilet: {e}")

        print("🕵️ Laster VAD...")
        try:
            self.vad_model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False)
            self.utils = utils
            print("✅ VAD er klar!")
        except Exception as e:
            print(f"❌ VAD feilet: {e}")

    # --- HJELPEFUNKSJONER ---
    
    def get_media_duration(self, filepath):
        try:
            cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "json", filepath
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            data = json.loads(result.stdout)
            return float(data['format']['duration'])
        except Exception as e:
            print(f"⚠️ Kunne ikke lese lengde på {filepath}: {e}")
            return None 

    async def clean_audio(self, input_path):
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        clean_path = os.path.join(TEMP_DIR, f"{base_name}_clean.wav")
        if os.path.exists(clean_path) and os.path.getsize(clean_path) > 1024:
            return clean_path
        cmd = ["ffmpeg", "-y", "-i", input_path, "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "16000", clean_path]
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await process.communicate()
        if not os.path.exists(clean_path) or os.path.getsize(clean_path) < 1024: raise Exception("Lyd-uttrekking feilet.")
        return clean_path

    def format_duration(self, seconds):
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h}t {m}m {s}s" if h else f"{m}m {s}s"

    def format_timestamp(self, seconds):
        if seconds is None: return "00:00:00,000"
        seconds = float(seconds)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

    def smart_format_text(self, text):
        return "\n".join(textwrap.wrap(text, width=MAX_LINE_LENGTH)[:MAX_LINES])

    def is_junk(self, text):
        if not text or len(text) < MIN_TEXT_LENGTH: return True 
        for bad in BAD_PHRASES:
            if bad.lower() in text.lower(): return True
        return False

    def merge_segments(self, timestamps):
        if not timestamps: return []
        merged = []
        current_block = timestamps[0].copy()
        for next_seg in timestamps[1:]:
            curr_end = current_block['end'] / 16000
            next_start = next_seg['start'] / 16000
            total_dur = (next_seg['end'] / 16000) - (current_block['start'] / 16000)
            if (next_start - curr_end < MAX_MERGE_GAP) and (total_dur <= MAX_BLOCK_DURATION):
                current_block['end'] = next_seg['end'] 
            else:
                merged.append(current_block)
                current_block = next_seg.copy()
        merged.append(current_block)
        return merged

    def calculate_eta(self, current_idx, total_items, batch_size):
        remaining_items = total_items - current_idx
        remaining_batches = (remaining_items + batch_size - 1) // batch_size
        seconds_left = remaining_batches * 6 
        return self.format_duration(seconds_left)

    # --- JOBB 1: OVERSETT ---
    async def run_translation_job(self, ctx, srt_path, output_path):
        if not os.path.exists(srt_path):
             return await ctx.send(f"❌ Finner ikke filen: `{srt_path}`. Har du kjørt `!vask` først?")

        status_msg = await ctx.send("🇺🇸 **Starter oversettelse av polert fil...**")
        try:
            subs = pysrt.open(srt_path, encoding='utf-8')
            total = len(subs)
            batch = 20
            parts = []
            
            for i in range(0, total, batch):
                chunk = subs[i:i+batch]
                text = "\n\n".join([str(s) for s in chunk])
                
                percent = int((i/total)*100)
                eta = self.calculate_eta(i, total, batch)
                await status_msg.edit(content=f"🇺🇸 **Oversetter til Engelsk**\n📊 {percent}% ({i}/{total})\n⏱️ ETA: {eta}")

                prompt = f"Translate Norsk SRT to idiomatic English. MAINTAIN EXACT TIMING from input. Adapt idioms. KEEP SRT FORMAT. Max 43 chars/line. INPUT:\n{text}"
                
                # Bruker den nye ai_motor.ask_gemini
                res_text = await ask_gemini(prompt, system_prompt="Du er en profesjonell SRT-oversetter.")
                
                parts.append(res_text.replace("```srt", "").replace("```", "").strip())
                await asyncio.sleep(2) # Redusert ventetid siden ask_gemini er mer effektiv

            with open(output_path, "w", encoding='utf-8') as f: f.write("\n\n".join(parts))
            await status_msg.delete()
            embed = discord.Embed(title="🇺🇸 Oversettelse Ferdig!", description="Basert på polert norsk fil.", color=discord.Color.blue())
            await ctx.send(embed=embed, file=discord.File(output_path))
        except Exception as e: await ctx.send(f"❌ Feil under oversettelse: {e}")

    # --- JOBB 2: VASK ---
    async def run_polish_job(self, ctx, srt_path, output_path):
        status_msg = await ctx.send("🇳🇴 **Vasker norsk tekst...**")
        try:
            subs = pysrt.open(srt_path, encoding='utf-8')
            total = len(subs)
            batch = 20
            parts = []
            
            for i in range(0, total, batch):
                chunk = subs[i:i+batch]
                text = "\n\n".join([str(s) for s in chunk])
                
                percent = int((i/total)*100)
                eta = self.calculate_eta(i, total, batch)
                await status_msg.edit(content=f"🇳🇴 **Vasker Norsk Tekst**\n📊 {percent}% ({i}/{total})\n⏱️ ETA: {eta}")

                prompt = f"Fix grammar/spelling in Norwegian Bokmål SRT. KEEP SRT FORMAT. Max 43 chars/line. INPUT:\n{text}"
                
                # Bruker den nye ai_motor.ask_gemini
                res_text = await ask_gemini(prompt, system_prompt="Du er en nøyaktig korrekturleser.")
                
                parts.append(res_text.replace("```srt", "").replace("```", "").strip())
                await asyncio.sleep(2)

            with open(output_path, "w", encoding='utf-8') as f: f.write("\n\n".join(parts))
            await status_msg.delete()
            embed = discord.Embed(title="✨ Norsk Vask Ferdig!", color=discord.Color.green())
            await ctx.send(embed=embed, file=discord.File(output_path))
        except Exception as e: await ctx.send(f"❌ Feil under vask: {e}")

    # --- JOBB 3: TRENINGSDATA ---
    async def run_training_dataset_job(self, ctx, srt_path, output_path):
        status_msg = await ctx.send("🏋️ **Genererer treningsdata...**")
        try:
            subs = pysrt.open(srt_path, encoding='utf-8')
            total = len(subs)
            batch = 20
            parts = []
            
            for i in range(0, total, batch):
                chunk = subs[i:i+batch]
                text = "\n\n".join([str(s) for s in chunk])
                
                percent = int((i/total)*100)
                eta = self.calculate_eta(i, total, batch)
                await status_msg.edit(content=f"🏋️ **Genererer Treningsdata**\n📊 {percent}% ({i}/{total})\n⏱️ ETA: {eta}")

                prompt = f"Create VERBATIM training dataset (Dialect->Bokmål). KEEP SRT FORMAT. No summarizing. INPUT:\n{text}"
                
                # Bruker den nye ai_motor.ask_gemini
                res_text = await ask_gemini(prompt, system_prompt="Du er en ekspert på norske dialekter.")
                
                parts.append(res_text.replace("```srt", "").replace("```", "").strip())
                await asyncio.sleep(2)

            with open(output_path, "w", encoding='utf-8') as f: f.write("\n\n".join(parts))
            await status_msg.delete()
            embed = discord.Embed(title="💾 Treningsdata Ferdig!", color=discord.Color.purple())
            await ctx.send(embed=embed, file=discord.File(output_path))
        except Exception as e: await ctx.send(f"❌ Feil under generering av treningsdata: {e}")

    # --- JOBB 4: DIFF ---
    async def run_diff_job(self, ctx, filnavn, mode="TRAIN"):
        base_name = filnavn.replace(".srt", "")
        original_path = os.path.join(TEMP_DIR, f"{base_name}.srt")
        
        if mode == "TRAIN":
            compared_path = os.path.join(TEMP_DIR, f"{base_name}_TRAIN.srt")
            suffix = "TRAIN_DIFF"
        else:
            compared_path = os.path.join(TEMP_DIR, f"{base_name}_polert.srt")
            suffix = "POLERT_DIFF"
            
        output_html = os.path.join(TEMP_DIR, f"{base_name}_{suffix}.html")

        if not os.path.exists(original_path) or not os.path.exists(compared_path):
            return await ctx.send(f"❌ Mangler filer! Sjekk at du har kjørt jobbene først.")

        status_msg = await ctx.send(f"🔍 **Lager rapport ({mode})...**")

        try:
            with open(original_path, 'r', encoding='utf-8') as f1: original_lines = f1.readlines()
            with open(compared_path, 'r', encoding='utf-8') as f2: new_lines = f2.readlines()

            diff = difflib.HtmlDiff(wrapcolumn=60)
            html_content = await asyncio.to_thread(diff.make_file, original_lines, new_lines, fromdesc="Original", todesc=f"Ny ({mode})", context=True, numlines=2)

            with open(output_html, "w", encoding='utf-8') as f: f.write(html_content)
            await status_msg.delete()
            embed = discord.Embed(title=f"📊 Endringsrapport ({mode})", color=discord.Color.orange())
            await ctx.send(embed=embed, file=discord.File(output_html))
        except Exception as e: await ctx.send(f"❌ Diff feilet: {e}")

    # --- TRANSKRIBERINGSJOBB ---
    async def run_transcription_job(self, ctx, lyd_sti, jobb_id):
        srt_sti = f"{TEMP_DIR}/{jobb_id}.srt"
        status_msg = await ctx.send(f"📊 **Jobb startet:** {jobb_id}")
        
        renset_fil = None
        try:
            renset_fil = await self.clean_audio(lyd_sti)
            (get_speech_timestamps, _, read_audio, _, _) = self.utils
            wav = read_audio(renset_fil)
            timestamps = get_speech_timestamps(wav, self.vad_model, threshold=0.5, min_speech_duration_ms=250)
            merged = self.merge_segments(timestamps)
            
            if not merged: return await ctx.send("❌ Fant ingen stemme!")

            final_srt = ""
            counter = 1
            waveform, sr = torchaudio.load(renset_fil)
            total_segs = len(merged)
            start_time = time.time()
            processed_duration = 0.01

            for i, ts in enumerate(merged):
                if self.stop_requested: break
                
                start = int(ts['start'])
                end = int(ts['end'])
                chunk = waveform[:, start:end].numpy()[0]
                chunk_dur = (end-start)/16000
                
                t0 = time.time()
                res = await asyncio.to_thread(self.pipe, chunk, generate_kwargs={"language": "no", "task": "transcribe"})
                proc_time = time.time() - t0
                processed_duration += chunk_dur

                text = res['text'].strip()
                if not self.is_junk(text):
                    t_start = self.format_timestamp(start/16000)
                    t_end = self.format_timestamp(end/16000)
                    final_srt += f"{counter}\n{t_start} --> {t_end}\n{self.smart_format_text(text)}\n\n"
                    counter += 1
                
                if i % 10 == 0:
                    speed = processed_duration / (time.time() - start_time)
                    remaining = total_segs - i
                    eta_sec = remaining * proc_time 
                    await status_msg.edit(content=f"📝 **Transkriberer**\n📊 {int((i/total_segs)*100)}% ferdig\n⚡ Fart: {speed:.1f}x\n⏱️ ETA: {self.format_duration(eta_sec)}")
                
                if i % 50 == 0: gc.collect()

            with open(srt_sti, "w", encoding="utf-8") as f: f.write(final_srt)
            
            total_tid = time.time() - start_time
            lagre(
                tekst=f"Transkribering fullført: {jobb_id} (Tid: {total_tid:.1f}s)", 
                user="WhisperBot", 
                guild_id=ctx.guild.id, 
                channel_id=ctx.channel.id, 
                kategori="VOD_Transcribe", 
                kilde="Auto"
            )
            
            await status_msg.delete()
            await ctx.send(f"✅ **Ferdig!** (`{jobb_id}`)", file=discord.File(srt_sti))
            
        except Exception as e:
            await ctx.send(f"❌ Feil: {e}")
        finally:
            if renset_fil and os.path.exists(renset_fil):
                try: os.remove(renset_fil) 
                except: pass

    # --- KOMMANDOER MED KØ-SYSTEM ---
    
    @commands.command()
    async def oversett(self, ctx, filnavn: str):
        base = filnavn.replace(".srt", "")
        polert_sti = f"{TEMP_DIR}/{base}_polert.srt"
        output_sti = f"{TEMP_DIR}/{base}_engelsk.srt"
        
        await queue_manager.add_job(
            job_type="vod_translate",
            func=self.run_translation_job,
            args=(ctx, polert_sti, output_sti),
            user_ctx=ctx
        )

    @commands.command()
    async def vask(self, ctx, filnavn: str):
        base = filnavn.replace(".srt", "")
        await queue_manager.add_job(
            job_type="vod_polish",
            func=self.run_polish_job,
            args=(ctx, f"{TEMP_DIR}/{base}.srt", f"{TEMP_DIR}/{base}_polert.srt"),
            user_ctx=ctx
        )

    @commands.command()
    async def treningsdata(self, ctx, filnavn: str):
        base = filnavn.replace(".srt", "")
        await queue_manager.add_job(
            job_type="vod_train",
            func=self.run_training_dataset_job,
            args=(ctx, f"{TEMP_DIR}/{base}.srt", f"{TEMP_DIR}/{base}_TRAIN.srt"),
            user_ctx=ctx
        )

    @commands.command()
    async def diff(self, ctx, filnavn: str, type: str = "train"):
        mode = "TRAIN" if type.lower() == "train" else "POLERT"
        await queue_manager.add_job(
            job_type="vod_diff",
            func=self.run_diff_job,
            args=(ctx, filnavn, mode),
            user_ctx=ctx
        )

    @commands.command()
    async def transkriber_lokal(self, ctx, filnavn: str):
        if not self.pipe: return await ctx.send("⚠️ Laster modell...")
        path = os.path.join(TEMP_DIR, filnavn)
        if not os.path.exists(path): return await ctx.send(f"❌ Finner ikke {filnavn}")
        
        duration = self.get_media_duration(path)
        
        await queue_manager.add_job(
            job_type="vod_transcribe",
            func=self.run_transcription_job,
            args=(ctx, path, filnavn),
            user_ctx=ctx,
            complexity=duration
        )

async def setup(bot):
    await bot.add_cog(VodReporter(bot))