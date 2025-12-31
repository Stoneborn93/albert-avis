import asyncio
import time
import datetime
import chromadb
import statistics

# --- KONFIGURASJON ---
# Vi kobler nå til serveren som kjører i bakgrunnen
# Dette hindrer "Database Locked" feil
CHROMA_HOST = 'localhost'
# Endret fra 8000 til 8081 for å matche Docker-containeren
CHROMA_PORT = 8081

class JobQueue:
    def __init__(self):
        self.queue = []
        self.is_processing = False
        self.current_job = None
        
        # --- ENDRING: SERVER KOBLING ---
        # Bruker HttpClient mot systemd-tjenesten din
        print(f"[KØ] 🔌 Kobler til ChromaDB på port {CHROMA_PORT}...")
        self.chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        self.log_collection = self.chroma_client.get_or_create_collection(name="system_logs")
        
        # Start arbeideren
        asyncio.create_task(self.worker())

    async def add_job(self, job_type, func, args=(), kwargs=None, user_ctx=None, complexity=None):
        """
        Legger en jobb i køen og returnerer estimert varighet.
        :param complexity: Et tall som sier hvor stor jobben er (f.eks sekunder video).
                           Hvis None, brukes flatt gjennomsnitt.
        """
        if kwargs is None: kwargs = {}
        
        # 1. Beregn estimat
        avg_duration = self.get_average_duration(job_type, complexity)
        
        job = {
            'type': job_type,
            'func': func,
            'args': args,
            'kwargs': kwargs,
            'added_at': time.time(),
            'estimated_duration': avg_duration,
            'complexity': complexity, # Lagrer hvor stor jobben var
            'ctx': user_ctx,
            'status_msg': None # Vi lagrer Discord-meldingen her så vi kan redigere den senere
        }
        
        # Beregn ventetid FØR vi legger til denne jobben
        wait_time = self.calculate_wait_time()
        
        self.queue.append(job)
        print(f"[KØ] 📥 Jobb lagt til: {job_type}. Kompleksitet: {complexity}. Estimat: {avg_duration/60:.1f}m.")
        
        # 2. Send første melding til bruker
        if user_ctx:
            timer = int(wait_time // 3600)
            minutter = int((wait_time % 3600) // 60)
            
            tekst = f"⏳ **Jobb satt i kø: {job_type}**\n"
            if complexity and "vod" in job_type:
                tekst += f"📼 Video lengde: `{int(complexity/60)} min`\n"
            
            if self.is_processing or len(self.queue) > 1:
                plass = len(self.queue)
                tekst += f"🚦 Du er nummer **{plass}** i køen.\n"
                tekst += f"🕒 Estimert start: `{timer}t {minutter}m` (inkl. kjøletid)."
            else:
                tekst += "🚀 Starter straks!"

            # Lagre meldingen i jobben, slik at vi kan redigere den senere!
            msg = await user_ctx.send(tekst)
            job['status_msg'] = msg
            
        return avg_duration

    def get_average_duration(self, job_type, complexity=None):
        """
        Regner ut estimat. 
        Hvis complexity er satt (f.eks video-lengde), ser den på 'tid per sekund'.
        Hvis ikke, ser den på 'tid per jobb'.
        """
        try:
            results = self.log_collection.get(where={"task": job_type}, limit=15)
            
            ratios = []
            flat_times = []

            if results['metadatas']:
                for meta in results['metadatas']:
                    # Samle data for flatt snitt
                    if 'duration' in meta: flat_times.append(meta['duration'])
                    
                    # Samle data for faktor-basert snitt (Tid / Kompleksitet)
                    if 'complexity' in meta and meta['complexity'] is not None and meta['complexity'] > 0:
                        ratio = meta['duration'] / meta['complexity']
                        ratios.append(ratio)

            # SCENARIO 1: Vi har en video-lengde (complexity) og historikk på ratio
            if complexity and ratios:
                avg_ratio = statistics.mean(ratios)
                estimat = complexity * avg_ratio
                print(f"[KØ] 🧠 Smart estimat: {complexity}s * {avg_ratio:.4f} = {estimat:.1f}s")
                return estimat

            # SCENARIO 2: Vi har historikk, men bruker flatt snitt (typisk nyheter)
            if flat_times:
                return statistics.mean(flat_times)

            # SCENARIO 3: Ingen historikk (Default verdier)
            if "vod" in job_type.lower(): 
                # Gjetter at video-prosessering tar 4x tiden av videoen hvis vi ikke vet
                return complexity * 4 if complexity else 72000 
            if "news" in job_type.lower(): return 900 # 15 min
            return 60
            
        except Exception as e:
            print(f"[KØ] ⚠️ Stat-feil: {e}")
            return 300

    def calculate_wait_time(self):
        """Summerer all tid i køen + pauser + gjenværende av nåværende jobb."""
        total_wait = 0
        cooldown = 300 # 5 minutter pause mellom jobber
        
        # Tid for jobber som venter
        for job in self.queue:
            total_wait += job['estimated_duration'] + cooldown
            
        # Tid for jobben som kjører NÅ
        if self.is_processing and self.current_job:
            elapsed = time.time() - self.current_job['start_time']
            remaining = max(0, self.current_job['estimated_duration'] - elapsed)
            total_wait += remaining + cooldown
            
        return total_wait

    async def update_waiting_users(self):
        """
        MAGIEN: Går gjennom hele køen og oppdaterer meldingene til brukerne
        med ny, mer nøyaktig tid fordi en jobb nettopp ble ferdig.
        """
        accumulated_wait = 0
        
        # Start med pausen som kommer nå
        if self.queue: accumulated_wait += 300 
        
        for i, job in enumerate(self.queue):
            # Hvis jobben har en Discord-melding lagret, oppdater den!
            if job['status_msg']:
                timer = int(accumulated_wait // 3600)
                minutter = int((accumulated_wait % 3600) // 60)
                
                ny_tekst = f"⏳ **Oppdatering:** Jobb-køen beveger seg!\n"
                ny_tekst += f"🚦 Du er nå nummer **{i+1}** i køen.\n"
                if i == 0:
                    ny_tekst += f"🔜 **Du er neste!** (Starter om ca 5 min kjøling...)"
                else:
                    ny_tekst += f"🕒 Nytt estimat: `{timer}t {minutter}m`"
                
                try:
                    await job['status_msg'].edit(content=ny_tekst)
                except: pass # Meldingen kan være slettet av bruker
            
            # Legg til denne jobbens tid i regnestykket for nestemann
            accumulated_wait += job['estimated_duration'] + 300

    async def worker(self):
        while True:
            if self.queue:
                self.is_processing = True
                job = self.queue.pop(0)
                self.current_job = job
                self.current_job['start_time'] = time.time()
                
                print(f"[KØ] 🚀 Starter jobb: {job['type']}")
                
                # Oppdater melding til den som starter NÅ
                if job['status_msg']:
                    try: await job['status_msg'].edit(content=f"🚀 **Din jobb ({job['type']}) starter NÅ!**\n*(Vennligst vent mens mini-PC jobber...)*")
                    except: pass

                try:
                    start_time = time.time()
                    # Kjør jobben (håndterer både async og sync funksjoner)
                    if asyncio.iscoroutinefunction(job['func']):
                        await job['func'](*job['args'], **job['kwargs'])
                    else:
                        await asyncio.to_thread(job['func'], *job['args'], **job['kwargs'])
                        
                    duration = time.time() - start_time
                    
                    print(f"[KØ] ✅ Ferdig: {job['type']} ({duration:.1f}s)")
                    
                    # Lagre statistikk (inkludert complexity hvis det finnes)
                    self.log_job_stats(job['type'], duration, job['complexity'])
                    
                    if job['ctx']:
                        await job['ctx'].send(f"✅ **Jobb ferdig!** ({job['type']})\n⏱️ Tid: `{int(duration/60)}m {int(duration%60)}s`")
                    
                    # Slett "kø-meldingen" siden jobben er ferdig
                    if job['status_msg']:
                        try: await job['status_msg'].delete()
                        except: pass

                except Exception as e:
                    print(f"[KØ] ❌ Feil: {e}")
                    if job['ctx']: await job['ctx'].send(f"❌ **Jobb feilet:** {e}")
                
                self.is_processing = False
                self.current_job = None
                
                # --- OPPDATER ALLE SOM VENTER ---
                # Nå som vi vet nøyaktig hvor lang tid denne jobben tok,
                # og at den er ferdig, oppdaterer vi ETA for alle andre.
                await self.update_waiting_users()
                
                # 5 min pause
                if self.queue:
                    print("[KØ] 🧊 5 min kjøling...")
                    await asyncio.sleep(300)
            else:
                await asyncio.sleep(5)

    def log_job_stats(self, job_type, duration, complexity=None):
        timestamp = datetime.datetime.now().timestamp()
        log_id = f"job_stat_{job_type}_{int(timestamp)}"
        
        metadata = {
            "category": "system_logs",
            "task": job_type,
            "duration": duration,
            "timestamp": timestamp
        }
        # Lagre complexity (f.eks videolengde) hvis vi har det
        if complexity:
            metadata["complexity"] = complexity
            
        try:
            self.log_collection.add(documents=["Jobb statistikk"], metadatas=[metadata], ids=[log_id])
        except: pass

queue_manager = JobQueue()