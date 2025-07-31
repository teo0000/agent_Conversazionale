from fastapi import FastAPI, Request, File, UploadFile
from fastapi.responses import JSONResponse
import speech_recognition as sr
from gtts import gTTS
import io
from agent import agent_node, State, graph, serialize_messages # Importa il grafo e le funzioni necessarie
import logging
from pydub import AudioSegment
import os
from fastapi.middleware.cors import CORSMiddleware
import re # Aggiunto per la pulizia del testo
from fastapi.responses import StreamingResponse
import requests
from fastapi import Body
from dotenv import load_dotenv
import base64
import os
import asyncio # Aggiunto per lo streaming
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from typing import List, Dict, Any

load_dotenv()
DID_API_KEY = os.getenv("DID_API_KEY")

app = FastAPI()
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.info("Test log dal file main.py")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "*"],  # Permetti richieste dal tuo frontend React
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

# --- NUOVO ENDPOINT PER LA CHAT IN STREAMING ---

# 1. Definiamo un modello per la richiesta (compatibile con Vercel AI SDK)
class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]

async def stream_generator(chat_request: ChatRequest):
    """
    Genera la risposta in streaming usando il grafo da agent.py.
    """
    # Prepara lo stato iniziale per il grafo
    initial_state = State(messages=chat_request.messages)

    # Usa astream_log per ottenere i chunk di output man mano che vengono prodotti
    # Questo ci permette di inviare solo il contenuto dei messaggi dell'assistente
    async for op in graph.astream_log(initial_state):
        for op_val in op.values():
            # Cerchiamo l'output del nodo agente principale
            if op_val.get("metadata", {}).get("name") == "main_agent_flow_node":
                messages = op_val.get("output", {}).get("messages", [])
                if messages:
                    # L'ultimo messaggio è di solito quello dell'assistente
                    last_message = messages[-1]
                    # Assicuriamoci che sia un messaggio dell'AI e non una chiamata a un tool
                    if last_message.get("type") == "ai" and last_message.get("content"):
                        # Invia solo il contenuto del messaggio
                        yield last_message["content"]
                        # Aggiungiamo un piccolo delay per un effetto di "scrittura" più naturale
                        await asyncio.sleep(0.05)

@app.post("/api/chat")
async def chat_streaming_endpoint(request: ChatRequest):
    """
    Endpoint che riceve la cronologia della chat e restituisce la risposta in streaming.
    Ora utilizza il grafo completo definito in agent.py.
    """
    logger.info(f"Richiesta di streaming ricevuta per /api/chat con {len(request.messages)} messaggi.")
    # Passiamo l'intera richiesta al generatore di streaming
    return EventSourceResponse(stream_generator(request))

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

