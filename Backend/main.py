from fastapi import FastAPI, Request, File, UploadFile
from fastapi.responses import JSONResponse
import speech_recognition as sr
from gtts import gTTS
import io
from lolll import agent_node, State
import logging
from pydub import AudioSegment
import os
from fastapi.middleware.cors import CORSMiddleware
import re # Aggiunto per la pulizia del testo
from fastapi.responses import StreamingResponse # Aggiunto per TTS

app = FastAPI()
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.info("Test log dal file main.py")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Puoi specificare l'origine esatta se vuoi essere più restrittivo
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/agent")
async def agent_endpoint(request: Request):
    """
    Endpoint per gestire le richieste dell'agente.
    """
    try:
        # Leggi i dati JSON inviati dal frontend
        data = await request.json()
        messages = data.get("messages", [])

        # Prepara lo stato iniziale per l'agente
        initial_state = State(
            session_token=None,
            user_id=None,
            messages=messages,
        )

        # Esegui l'agente con lo stato iniziale
        final_state = agent_node(initial_state)

        # Restituisci i messaggi finali come risposta
        return {"messages": final_state["messages"]}
    except Exception as e:
        logger.error(f"Errore nell'endpoint /agent: {e}", exc_info=True)
        return JSONResponse(
            content={"error": f"Errore interno del server: {str(e)}"}, status_code=500
        )

@app.post("/agent/audio")
async def audio_agent(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    temp_webm = "temp.webm"
    temp_wav = "temp.wav"
    with open(temp_webm, "wb") as f:
        f.write(audio_bytes)
    # Converte da webm/opus a wav PCM
    try:
        audio = AudioSegment.from_file(temp_webm)
        audio.export(temp_wav, format="wav")
        os.remove(temp_webm) # Rimuovi webm dopo la conversione

        # Trascrivi l'audio
        r = sr.Recognizer()
        with sr.AudioFile(temp_wav) as source:
            audio_data = r.record(source) # Rinomina per evitare confusione con la variabile 'audio' precedente
        
        text = r.recognize_google(audio_data, language="it-IT")

        # L'endpoint /agent/audio dovrebbe restituire solo il testo trascritto.
        # La logica per ottenere la risposta dell'agente e poi sintetizzarla
        # dovrebbe essere gestita dal frontend che prima chiama /agent con il testo,
        # poi /agent/tts con la risposta dell'agente.
        return {
            "transcribed_text": text # Restituisce il testo trascritto
        }
    except sr.UnknownValueError:
        return JSONResponse({"error": "Non è stato possibile riconoscere la voce. Riprova parlando più chiaramente."}, status_code=400)
    except Exception as e:
        logger.error(f"Errore durante l'elaborazione dell'audio: {e}", exc_info=True)
        return JSONResponse({"error": f"Errore durante l'elaborazione dell'audio: {str(e)}"}, status_code=500)
    finally:
        # Pulisci i file temporanei in ogni caso
        if os.path.exists(temp_webm) and temp_webm != temp_wav : # Evita di provare a rimuovere webm se è lo stesso di wav (non dovrebbe succedere qui)
             try: os.remove(temp_webm)
             except OSError: pass # Ignora se non può essere rimosso (potrebbe essere già stato rimosso)
        if os.path.exists(temp_wav):
            try: os.remove(temp_wav)
            except OSError: pass # Ignora se non può essere rimosso

@app.post("/agent/tts")
async def text_to_speech_endpoint(request: Request):
    """
    Endpoint per convertire testo in audio e restituirlo.
    """
    try:
        data = await request.json()
        text_to_speak = data.get("text")
        if not text_to_speak:
            return JSONResponse({"error": "Nessun testo fornito per la sintesi vocale."}, status_code=400)

        # Pulisci il testo dal Markdown prima di inviarlo a gTTS
        cleaned_text = re.sub(r'\*\*(.*?)\*\*', r'\1', text_to_speak) # Rimuove **testo** -> testo
        # Se usi anche asterischi singoli per il corsivo e vuoi rimuoverli:
        # cleaned_text = re.sub(r'\*(.*?)\*', r'\1', cleaned_text)

        tts = gTTS(text=cleaned_text, lang="it")
        audio_fp = io.BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0) # Torna all'inizio del buffer di byte
        return StreamingResponse(audio_fp, media_type="audio/mpeg")
    except Exception as e:
        logger.error(f"Errore durante la sintesi vocale (TTS): {e}", exc_info=True)
        return JSONResponse({"error": f"Errore durante la sintesi vocale: {str(e)}"}, status_code=500)