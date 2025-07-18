import re
import os
import getpass
import requests
from typing import Annotated, Optional, List, Dict, Any
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from pydantic import BaseModel, Field  # Assicurati che sia la versione corretta per la tua installazione
import dateutil.tz
from langgraph.prebuilt import create_react_agent
import dateparser
import json
import logging
import datetime
import pprint
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
import sys
import uuid # Aggiunto per generare ID univoci più brevi
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
# Configura il logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')  # Cambiato a INFO per meno verbosità, DEBUG se necessario
logger = logging.getLogger(__name__)  # Logger specifico per questo modulo

# Imposta la chiave API OpenAI
def _set_env(var: str):
    if not os.environ.get(var):
        os.environ[var] = getpass.getpass(f"{var}: ")
_set_env("OPENAI_API_KEY")

# Configurazione LibreBooking
LIBREBOOKING_API_URL = "http://localhost/Web/Services/index.php"

# 📌 Definisci lo stato
class State(TypedDict):
    session_token: Optional[str]
    user_id: Optional[str]
    messages: Annotated[list, add_messages]
    # Campi non più usati attivamente
    reference_number_to_delete: Optional[str] = None
    reservation_details_to_confirm: Optional[str] = None
    confirmation_pending: bool = False
    # Campo per la logica di prenotazione automatica
    auto_book_target: Optional[Dict[str, str]] = None
    available_accessories: Optional[List[Dict[str, Any]]] = None
    # Nuovi campi di stato per il flusso guidato
    needs_initial_accessories_check: bool = False # Indipendente dalla richiesta utente
    availability_check_done: bool = False # Nuovo flag
    details_asked: bool = False # Nuovo flag
    # Nuovi campi per il flusso di aggiornamento post-creazione
    awaiting_accessories_update: bool = False
    last_created_ref: Optional[str] = None

# 🔑 Funzione di Autenticazione (Helper)
def authenticate(username: str, password: str) -> dict:
    """Autentica l'utente e restituisce token di sessione e ID utente."""
    auth_url = f"{LIBREBOOKING_API_URL}/Authentication/Authenticate"
    auth_data = {"username": username, "password": password}
    try:
        response = requests.post(auth_url, json=auth_data)
        response.raise_for_status()
        data = response.json()
        token = data.get("sessionToken")
        uid = data.get("userId")
        if token and uid:
            logger.info(f"Autenticazione riuscita per user_id: {uid}")
            return {"session_token": token, "user_id": uid}
        else:
            logger.error(f"Autenticazione fallita: token o user_id mancanti. Risposta: {data}")
            return {}
    except requests.RequestException as e:
        logger.error(f"❌ Errore autenticazione: {e}", exc_info=True)
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"❌ Errore parsing JSON autenticazione: {e}", exc_info=True)
        return {}

# --- Tool: authenticate_tool ---
class AuthenticateToolArgs(BaseModel):
    pass
@tool(args_schema=AuthenticateToolArgs)
def authenticate_tool() -> dict:
    """
    Autentica l'utente usando credenziali predefinite (admin/password). Restituisce session_token e user_id.
    **CONDIZIONE D'USO:** Chiama questo strumento SOLO se non è già disponibile un token di sessione valido dalla conversazione corrente
    o se una precedente chiamata API protetta è fallita a causa di un errore di autenticazione (es. token scaduto).
    """
    return authenticate("admin", "password")

# --- Tool: get_reservation ---
class GetReservationArgs(BaseModel):
    session_token: str = Field(..., description="Il token di sessione valido ottenuto dall'autenticazione.")
    user_id: str = Field(..., description="L'ID utente valido ottenuto dall'autenticazione.")
    reference_number: str = Field(..., description="Il numero di riferimento valido della prenotazione da recuperare (almeno 10 caratteri).")
@tool(args_schema=GetReservationArgs)
def get_reservation(session_token: str, user_id: str, reference_number: str) -> str:
    """
    Recupera i dettagli di una prenotazione dato il numero di riferimento, includendo l'ID della risorsa se disponibile.
    **FLUSSO CANCELLAZIONE - Step 1:** Se l'utente vuole cancellare, chiama questo tool per ottenere i dettagli.
    **Step 2:** L'agente DEVE mostrare i dettagli restituiti all'utente.
    **Step 3:** L'agente DEVE poi chiedere ESATTAMENTE: 'Vuoi cancellare questa prenotazione? Rispondi "sì" per confermare.'
    NON procedere alla cancellazione senza questi passaggi.
    """
    if not all([session_token, user_id, reference_number]): return "❌ Errore: Mancano token, user ID o numero di riferimento."
    if len(reference_number) < 10: return "⚠️ Inserisci un numero di riferimento valido (almeno 10 caratteri)."
    headers = {"X-Booked-SessionToken": session_token, "X-Booked-UserId": user_id}
    try:
        logging.info(f"get_reservation: Tentativo recupero dettagli per {reference_number}")
        response = requests.get(f"{LIBREBOOKING_API_URL}/Reservations/{reference_number}", headers=headers)
        response.raise_for_status()
        data = response.json()

        resource_id = data.get('resourceId')
        start_date_str = data.get('startDate', 'N/D') # N/D = Non Disponibile
        end_date_str = data.get('endDate', 'N/D')
        title = data.get('title', 'N/D')

        # Costruisci la stringa dei dettagli includendo l'ID se presente
        if resource_id:
            details_string = (f"Risorsa: (ID: {resource_id}), Inizio: {start_date_str}, "
                              f"Fine: {end_date_str}, Titolo: {title}, Riferimento: {reference_number}")
        else:
            details_string = (f"Risorsa: (ID non disponibile), Inizio: {start_date_str}, "
                              f"Fine: {end_date_str}, Titolo: {title}, Riferimento: {reference_number}")
            logging.warning(f"get_reservation: resourceId mancante nella risposta API per {reference_number}")

        logging.info(f"get_reservation: Dettagli recuperati: {details_string}")
        return details_string
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401: return "❌ Errore Autenticazione: Token non valido/scaduto. Riesegui l'autenticazione."
        if e.response.status_code == 404: return f"⚠️ Prenotazione '{reference_number}' non trovata."
        logging.error(f"Errore HTTP recupero prenotazione {reference_number}: {e}", exc_info=True)
        return f"❌ Errore HTTP ({e.response.status_code}) nel recupero."
    except requests.RequestException as e:
        logging.error(f"Errore generico recupero prenotazione {reference_number}: {e}", exc_info=True)
        return "❌ Errore di rete o del server nel recupero."
    except json.JSONDecodeError as e:
        logging.error(f"Errore parsing JSON per prenotazione {reference_number}: {e}", exc_info=True)
        return "❌ Errore nell'analisi della risposta del server."


# --- Tool: delete_reservation ---
class DeleteReservationArgs(BaseModel):
    session_token: str = Field(..., description="Il token di sessione valido ottenuto dall'autenticazione.")
    user_id: str = Field(..., description="L'ID utente valido ottenuto dall'autenticazione.")
    reference_number: str = Field(..., description="Il numero di riferimento ESATTO della prenotazione da cancellare (es. '68025dd1d1b7b187492421'), ottenuto dalla conversazione precedente.")
@tool(args_schema=DeleteReservationArgs)
def delete_reservation(session_token: str, user_id: str, reference_number: str) -> str:
    """
    Cancella una prenotazione.
    **FLUSSO CANCELLAZIONE - Step 4:** Chiama questo tool **SOLO E SOLTANTO SE** sono stati eseguiti i seguenti passaggi:
    1. L'utente ha chiesto di cancellare.
    2. L'agente ha chiamato `get_reservation`.
    3. L'agente ha mostrato i dettagli all'utente.
    4. L'agente ha chiesto 'Vuoi cancellare questa prenotazione? Rispondi "sì" per confermare.'
    5. L'utente ha risposto **esplicitamente 'sì'** a quella specifica domanda.
    Richiede token, user ID e il numero di riferimento ESATTO.
    Se l'utente risponde 'no' o altro, NON chiamare questo tool.
    """
    if not all([session_token, user_id, reference_number]): return "❌ Errore: Mancano token, user ID o numero di riferimento per la cancellazione."
    logging.info(f"delete_reservation: Tentativo cancellazione per {reference_number} (confermata dall'utente)")
    headers = {"X-Booked-SessionToken": session_token, "X-Booked-UserId": user_id}
    try:
        response = requests.delete(f"{LIBREBOOKING_API_URL}/Reservations/{reference_number}", headers=headers)
        response.raise_for_status()
        logging.info(f"delete_reservation: Prenotazione {reference_number} cancellata.")
        return f"✅ Prenotazione {reference_number} cancellata con successo."
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401: return "❌ Errore Autenticazione: Token non valido/scaduto. Riesegui l'autenticazione."
        if e.response.status_code == 404: return f"⚠️ Prenotazione '{reference_number}' non trovata. Già cancellata?"
        logging.error(f"Errore HTTP cancellazione {reference_number}: {e}", exc_info=True)
        return f"❌ Errore HTTP ({e.response.status_code}) durante la cancellazione."
    except requests.RequestException as e:
        logging.error(f"Errore generico cancellazione {reference_number}: {e}", exc_info=True)
        return "❌ Errore di rete o del server durante la cancellazione."
    except json.JSONDecodeError as e: # Anche se DELETE di solito non restituisce JSON, gestisci per sicurezza
        logging.error(f"Errore parsing JSON risposta cancellazione {reference_number}: {e}", exc_info=True)
        return f"❌ Errore analisi risposta server post-cancellazione."

# --- Tool: parse_date ---
class ParseDateArgs(BaseModel):
    user_input: str = Field(..., description="La stringa fornita dall'utente contenente la data e/o l'ora da interpretare.")
@tool(args_schema=ParseDateArgs)
def parse_date(user_input: str) -> str | None:
    """Interpreta date/ore (anche relative). Output JSON con 'iso_datetime' e 'time_specified'. Imposta mezzanotte se ora non specificata."""
    try:
        original_input_lower = user_input.lower()
        processed_input = original_input_lower
        # Normalizza input per evitare errori di parsing
        processed_input = re.sub(r"\b(alle|ore)\s+(\d{1,2})(?!\s*[:\d])", r"\2:00", processed_input, flags=re.IGNORECASE)
        processed_input = re.sub(r"\b(alle|ore)\s+(\d{1,2}:\d{2})", r"\2", processed_input, flags=re.IGNORECASE)
        logger.info(f"parse_date: Input='{user_input}', Processed='{processed_input}'")

        # Impostazioni per il parsing delle date - SPOSTATO QUI
        settings = {
            'PREFER_DATES_FROM': 'future',
            'TIMEZONE': 'Europe/Rome',
            'RETURN_AS_TIMEZONE_AWARE': True,
            # 'DATE_ORDER': 'DMY' # Verrà impostato condizionatamente
            'RELATIVE_BASE': datetime.datetime.now(),  # Usa data e ora attuali del computer
        }
        languages = ['it', 'en']

        # --- Pre-processing per espressioni tipo "mercoledì prossimo" ---
        giorni_settimana = {
            "lunedì": 0, "martedì": 1, "mercoledì": 2, "giovedì": 3,
            "venerdì": 4, "sabato": 5, "domenica": 6
        }
        for nome_giorno, idx in giorni_settimana.items():
            pattern = rf"{nome_giorno} prossimo"
            if re.search(pattern, processed_input):
                base = settings["RELATIVE_BASE"]
                # Calcola il prossimo giorno della settimana
                days_ahead = idx - base.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                next_day = base + datetime.timedelta(days=days_ahead)
                # Sostituisci "mercoledì prossimo" con la data calcolata (formato italiano)
                processed_input = re.sub(pattern, next_day.strftime("%d/%m/%Y"), processed_input)
                logger.debug(f"parse_date: Sostituito '{nome_giorno} prossimo' con '{next_day.strftime('%d/%m/%Y')}' -> '{processed_input}'")
                break

        # Controlla se l'input contiene un orario specifico
        time_pattern = r'\b\d{1,2}:\d{2}\b'
        time_specified_in_input = bool(re.search(time_pattern, processed_input))
        time_keywords = ['noon', 'midnight', 'afternoon', 'morning', 'evening', 'mezzogiorno', 'mezzanotte', 'pomeriggio', 'mattina', 'sera']
        if not time_specified_in_input:
            for keyword in time_keywords:
                if keyword in original_input_lower:
                    time_specified_in_input = True
                    break
        if not time_specified_in_input and re.search(r"\b(alle|ore)\s+\d", original_input_lower):
            time_specified_in_input = True
        logger.debug(f"parse_date: Orario specificato? {time_specified_in_input}")

        # Controlla se processed_input (ciò che vedrà dateparser) assomiglia a una data ISO.
        # Regex per YYYY-MM-DD[Tt]HH:MM:SS (con opzionali frazioni di secondo e timezone)
        iso_datetime_pattern = r'^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[\+\-]\d{2}:\d{2})?$'
        # Regex per YYYY-MM-DD
        iso_date_pattern = r'^\d{4}-\d{2}-\d{2}$'

        if not (re.match(iso_datetime_pattern, processed_input) or re.match(iso_date_pattern, processed_input)):
            # Se non è una data/datetime ISO stretta, potrebbe essere "DD/MM/YYYY" o linguaggio naturale.
            # In questi casi, specialmente per l'italiano "DD/MM/YYYY", DMY è preferito.
            settings['DATE_ORDER'] = 'DMY'
            logger.debug(f"parse_date: Input '{processed_input}' non è ISO stretta. Usando DATE_ORDER: DMY.")
        else:
            logger.debug(f"parse_date: Input '{processed_input}' sembra ISO. Non usando DATE_ORDER esplicito.")

        # Parsing della data
        logger.debug(f"parse_date: Tentativo parsing con dateparser per '{processed_input}' con impostazioni: {settings}")
        target_date = dateparser.parse(processed_input, settings=settings, languages=languages)

        if not target_date:
            logger.warning(f"parse_date: dateparser.parse ha restituito None per '{processed_input}'")
            return None
        else:
            logger.debug(f"parse_date: dateparser.parse ha restituito: {target_date}")

        # Se l'ora non è specificata, forza a mezzanotte
        if not time_specified_in_input and (target_date.hour != 0 or target_date.minute != 0 or target_date.second != 0 or target_date.microsecond != 0):
            logger.debug(f"parse_date: Orario non specificato, ma dedotto ({target_date.time()}), forzando a mezzanotte.")
            target_date = target_date.replace(hour=0, minute=0, second=0, microsecond=0)

        # Verifica che la data sia valida e non nel passato
        now = datetime.datetime.now(target_date.tzinfo)
        if target_date < now:
            logger.warning(f"parse_date: La data '{target_date}' è nel passato. Ignorata.")
            return None

        # Converti la data in UTC per garantire coerenza con l'API
        utc_date = target_date.astimezone(datetime.timezone.utc)

        # Restituisci il risultato in formato JSON
        iso_string = utc_date.isoformat()
        result = {"iso_datetime": iso_string, "time_specified": time_specified_in_input}
        json_output = json.dumps(result)
        logger.info(f"parse_date: Output JSON='{json_output}'")
        return json_output
    except Exception as e:
        logger.error(f"Errore imprevisto in parse_date durante l'elaborazione di '{user_input}': {e}", exc_info=True)
        return None

# --- Tool: get_resources ---
class GetResourcesArgs(BaseModel):
    session_token: str = Field(..., description="Il token di sessione valido ottenuto dall'autenticazione.")
    user_id: str = Field(..., description="L'ID utente valido ottenuto dall'autenticazione.")
@tool(args_schema=GetResourcesArgs)
def get_resources(session_token: str, user_id: str) -> list | str:
    """
    Recupera l'elenco delle risorse disponibili (ID e nome) per l'utente autenticato.
    **CONDIZIONE D'USO:** Chiama questo strumento se l'utente chiede informazioni sulle risorse disponibili
    e l'elenco non è già stato fornito o se si sospetta che possa essere cambiato.
    """
    if not all([session_token, user_id]): return "❌ Errore: Mancano token o user ID."
    headers = {"X-Booked-SessionToken": session_token, "X-Booked-UserId": user_id}
    try:
        response = requests.get(f"{LIBREBOOKING_API_URL}/Resources/", headers=headers)
        response.raise_for_status()
        resources = response.json().get("resources", [])
        logger.debug(f"Risorse recuperate: {len(resources)}.")
        simplified_resources = [
            {"resourceId": r.get("resourceId"), "name": r.get("name")}
            for r in resources if r.get("resourceId") and r.get("name")
        ]
        if not simplified_resources:
             logger.warning("get_resources: Nessuna risorsa con ID e nome trovata nella risposta API.")
             return "⚠️ Nessuna risorsa trovata o formato risposta API inatteso."
        return simplified_resources
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401: return "❌ Errore Autenticazione: Token non valido/scaduto."
        logger.error(f"❌ Errore HTTP recupero risorse: {e}", exc_info=True)
        return f"❌ Errore HTTP ({e.response.status_code}) recupero risorse."
    except requests.RequestException as e: logger.error(f"❌ Errore generico recupero risorse: {e}", exc_info=True); return f"❌ Errore rete/server recupero risorse."
    except json.JSONDecodeError as e: logger.error(f"❌ Errore parsing JSON per risorse: {e}", exc_info=True); return f"❌ Errore analisi risposta risorse."
    except Exception as e:
        logger.error(f"❌ Errore imprevisto elaborazione risorse: {e}", exc_info=True)
        return "❌ Errore interno elaborazione risorse."



# --- Tool: create_reservation ---
class CreateReservationArgs(BaseModel):
    session_token: str = Field(..., description="The valid session token obtained from authentication.")
    user_id: str = Field(..., description="The valid user ID obtained from authentication.")
    title: str = Field(default="", description="Reservation title (optional).")
    description: str = Field(default="", description="Reservation description (optional).")
    startDateTime: str = Field(..., description='ISO 8601 start date/time (from parse_date).')
    endDateTime: str = Field(..., description='ISO 8601 end date/time (calculated or from parse_date).')
    resourceId: str = Field(..., description="Specific resource ID (from get_resources).")
    accessories: List[Dict[str, Any]] = Field(..., description="List of accessories to book with the reservation. Each item should be a dict with 'accessoryId' (str) and 'quantityRequested' (int). Example: [{'accessoryId': '1', 'quantityRequested': 1}]. Se non sono richiesti accessori, passare una lista vuota []. **Questo campo è obbligatorio.**")


@tool(args_schema=CreateReservationArgs)
def  create_reservation(session_token: str, user_id: str, startDateTime: str, endDateTime: str, resourceId: str, accessories: List[Dict[str, Any]], title: str = "", description: str = "") -> str:
    """
    Crea una prenotazione per una risorsa specifica in un intervallo di tempo.
    Richiede una lista di accessori (anche vuota []), ciascuno con 'accessoryId' e 'quantityRequested'.
    **GESTIONE FALLIMENTI:** Se questo tool fallisce perché la risorsa non è disponibile
    (es. errore HTTP 409 o messaggio di conflitto) e in precedenza avevi verificato
    che altre risorse erano disponibili per lo stesso orario (tramite `get_availability`),
    l'agente può tentare di prenotare **SOLO UNA SINGOLA RISORSA ALTERNATIVA**.
    Non effettuare chiamate multiple a `create_reservation` per diverse alternative in un unico turno.
    Dopo aver tentato la singola alternativa, riporta l'esito (successo o fallimento di quel tentativo).
    """
    if not all([session_token, user_id, startDateTime, endDateTime, resourceId, accessories is not None]): # Aggiunto controllo accessories is not None
        return "❌ Errore: Mancano informazioni essenziali (token, user ID, date, resource ID)."

    if not resourceId.isdigit():
        logger.error(f"create_reservation: resourceId non valido '{resourceId}'. Deve essere un numero.")
        return f"❌ Errore: resourceId '{resourceId}' non valido. Deve essere un numero."

    headers = {"X-Booked-SessionToken": session_token, "X-Booked-UserId": user_id}
    body = {
        "title": title if title else "Reservation",
        "description": description,
        "startDateTime": startDateTime,
        "endDateTime": endDateTime,
        "resourceId": resourceId,
        "userId": user_id,
        "termsAccepted": True,
        "allowParticipation": False,
        "accessories": accessories,  # Passa direttamente la lista di accessori

    }
    if accessories: # Ora accessories è sempre una lista, potrebbe essere vuota
        # Modifica qui per far corrispondere le aspettative dell'API
        # basandoci sull'errore "Undefined property: stdClass::$quantityRequested"
        processed_accessories = []
        for acc in accessories:
            qty_req_val = acc.get("quantityRequested")
            if qty_req_val is None: # Fallback se l'LLM ha usato "quantity"
                qty_req_val = acc.get("quantityRequested")
            
            # Assicura che sia un intero se non None, altrimenti l'API potrebbe rifiutarlo
            if qty_req_val is not None:
                try: qty_req_val = int(qty_req_val)
                except (ValueError, TypeError): qty_req_val = None # Lascia che l'API lo segnali come errore se non è un intero valido

            processed_accessories.append({"accessoryId": acc.get("accessoryId"), "quantityRequested": qty_req_val})
        body["accessories"] = processed_accessories

    log_body = {k: v for k, v in body.items() if k != "session_token"} # Non loggare il token nel corpo se per errore finisce lì
    logger.debug(f"create_reservation: Corpo della richiesta: {json.dumps(log_body)}")

    try:
        response = requests.post(f"{LIBREBOOKING_API_URL}/Reservations/", json=body, headers=headers)
        logger.debug(f"create_reservation: Risposta API: Status={response.status_code}, Body={response.text[:500]}")
        response.raise_for_status()

        response_data = response.json()
        ref_num = response_data.get("referenceNumber")
        message = response_data.get("message", "Prenotazione creata.")

        if ref_num:
            logger.info(f"create_reservation: Prenotazione creata con successo. Numero di riferimento: {ref_num}")
            # --- MODIFICA PER CORREGGERE LA VISUALIZZAZIONE DELL'ORARIO ---
            try:
                # startDateTime arriva in formato UTC (es. "2025-06-28T08:00:00+00:00")
                start_dt_utc = dateparser.parse(startDateTime) # This is already UTC
                if start_dt_utc:
                    # Converti in fuso orario locale per la visualizzazione
                    local_tz = dateutil.tz.gettz('Europe/Rome')
                    start_dt_local = start_dt_utc.astimezone(local_tz)
                    start_formatted = start_dt_local.strftime('%d/%m/%Y alle %H:%M')
                else:
                    start_formatted = startDateTime # Fallback
            except Exception:
                start_formatted = startDateTime # Fallback in caso di qualsiasi errore
            # --- FINE MODIFICA VISUALIZZAZIONE ---
            
            # Aggiungi l'orario UTC per l'LLM nel messaggio del tool
            utc_time_for_llm = startDateTime # startDateTime è già in UTC
            accessories_message_part = ""
            if accessories: # 'accessories' è l'argomento passato al tool con 'quantityRequested'
                accessory_details_list = []
                # Nota: qui abbiamo solo gli ID. Per i nomi, l'agente dovrebbe averli recuperati
                # da get_accessories e idealmente passati o usati per costruire la descrizione.
                for acc_req in accessories:
                    accessory_details_list.append(
                        f"{acc_req.get('quantityRequested', 'N/A')}x ID:{acc_req.get('accessoryId', 'N/A')}"
                    )
                if accessory_details_list:
                    accessories_message_part = f" con accessori: {', '.join(accessory_details_list)}"

            return (f"✅ {message} Prenotazione per la risorsa {resourceId} il {start_formatted} (UTC: {utc_time_for_llm}){accessories_message_part}.\n"
                    f"Numero di riferimento: {ref_num}. Conservalo per future modifiche o cancellazioni. Titolo: '{title}'. Descrizione: '{description}'.")
        else:
            logger.warning("create_reservation: Prenotazione creata ma il numero di riferimento è vuoto.")
            # Anche se il ref_num è vuoto, la prenotazione potrebbe essere stata creata.
            # Il messaggio API dovrebbe indicarlo.
            return f"⚠️ {message} (Attenzione: il numero di riferimento non è stato restituito chiaramente, ma la prenotazione potrebbe essere stata creata)."

    except requests.exceptions.HTTPError as e:
        error_details = "Dettagli non disponibili."
        try:
            error_data = e.response.json()
            error_details = error_data.get("message", json.dumps(error_data))
        except json.JSONDecodeError:
            error_details = e.response.text[:500]
        logger.error(f"❌ HTTP {e.response.status_code} errore durante la creazione della prenotazione: {error_details}")
        if e.response.status_code == 409 or "overlaps" in error_details.lower():
            return "❌ Errore: La risorsa è già prenotata per l'intervallo di tempo specificato."
        return f"❌ Errore HTTP ({e.response.status_code}): {error_details}"

    except requests.RequestException as e:
        logger.error(f"❌ Errore di rete durante la creazione della prenotazione: {e}")
        return "❌ Errore di rete durante la creazione della prenotazione."

    except json.JSONDecodeError as e:
        logger.error(f"❌ Errore nel parsing della risposta JSON: {e}")
        return "❌ Errore nel parsing della risposta del server."

    except Exception as e:
        logger.error(f"❌ Errore imprevisto durante la creazione della prenotazione: {e}", exc_info=True)
        return "❌ Errore interno durante la creazione della prenotazione."

# --- Tool: update_reservation ---
class UpdateReservationArgs(BaseModel):
    session_token: str = Field(..., description="The valid session token obtained from authentication.")
    user_id: str = Field(..., description="The valid user ID obtained from authentication (for headers).")
    reference_number: str = Field(..., description="The EXACT reference number of the reservation to update.")
    startDateTime: str = Field(..., description="The NEW start date/time in ISO 8601 format (obtained from parse_date).")
    endDateTime: str = Field(..., description="The NEW end date/time in ISO 8601 format (calculated or from parse_date).")
    resourceId: str = Field(..., description="The **valid** ID of the resource for the updated reservation (can be the same or a new one, obtained from get_reservation or get_resources). DO NOT use 'N/A'.")
    title: Optional[str] = Field(None, description="The NEW title for the reservation (optional). If not provided, a default ('Reservation') will be used.")
    description: Optional[str] = Field(None, description="The NEW description for the reservation (optional).")
    num_people: Optional[int] = Field(None, description="The number of people for the reservation. This will automatically add the corresponding number of chairs.")
    accessories: Optional[List[Dict[str, Any]]] = Field(None, description="Optional list of other accessories to update (e.g., projector). Each item should be a dict with 'accessoryId' and 'quantityRequested'. **Do NOT include chairs here; use 'num_people' instead.**")
    
    updateScope: Optional[str] = Field(None, description="Specifies the scope of the update (optional). Possible values: 'this' (this occurrence only), 'full' (entire series), 'future' (this and future occurrences). Default is usually 'full'.")

@tool(args_schema=UpdateReservationArgs)
def update_reservation(
    session_token: str,
    user_id: str,
    reference_number: str,
    startDateTime: str,
    endDateTime: str,
    resourceId: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    num_people: Optional[int] = None,
    accessories: Optional[List[Dict[str, Any]]] = None,
    updateScope: Optional[str] = None
) -> str:
    """
    Updates an existing reservation. Use this to change time, resource, title, description, or add accessories.
    **IMPORTANT**: To specify the number of attendees, use the `num_people` parameter. This will automatically handle adding the correct number of chairs. Do NOT add chairs to the `accessories` list.
    The `accessories` list is for other items like projectors or microphones.
    Requires the exact reference number and all other reservation details. It's often necessary to call `get_reservation` first to retrieve current details.
    """
    if not all([session_token, user_id, reference_number, startDateTime, endDateTime, resourceId]):
        return "❌ Error: Missing essential information (token, user ID, ref number, dates, resource ID) for the update."

    if not resourceId or not resourceId.isdigit():
        logging.error(f"update_reservation: Attempt to update reservation {reference_number} with invalid resourceId: '{resourceId}'")
        return f"❌ Error: The resource ID '{resourceId}' provided for the update is invalid. It must be a number obtained from get_reservation or get_resources."

    headers = {"X-Booked-SessionToken": session_token, "X-Booked-UserId": user_id}
    # Note: Update uses POST on the specific reservation URL
    api_url = f"{LIBREBOOKING_API_URL}/Reservations/{reference_number}"

    # Build the request body, always include description (even if empty)
    body = {
        "userId": user_id, # Usually required by the API
        "startDateTime": startDateTime,
        "endDateTime": endDateTime,
        "resourceId": resourceId,
        "termsAccepted": True, # Assuming terms acceptance
        "allowParticipation": False, # Default participation
        "title": title if title is not None else "Reservation", # Use default if not provided
        "description": description if description is not None else "" # Always include, empty if None
    }

    # --- NEW LOGIC to handle accessories and num_people ---
    final_accessories = accessories.copy() if accessories is not None else []

    if num_people is not None and num_people > 0:
        # Assume chair accessory has ID '1'. This is a reasonable simplification based on get_accessories output.
        chair_accessory_id = '1'
        # Remove any existing chair entry from the list to avoid duplicates if the LLM adds it anyway
        final_accessories = [acc for acc in final_accessories if acc.get('accessoryId') != chair_accessory_id]
        # Add the new chair request based on num_people
        final_accessories.append({'accessoryId': chair_accessory_id, 'quantityRequested': num_people})
        logging.info(f"update_reservation: Added/updated {num_people} chairs (ID: {chair_accessory_id}) to the request.")

    body["accessories"] = final_accessories # Add the final list to the body

    # Handle optional updateScope parameter
    params = {}
    if updateScope and updateScope in ['this', 'full', 'future']:
        params['updateScope'] = updateScope
    elif updateScope:
        # Warn if an invalid scope value is provided
        logging.warning(f"update_reservation: Invalid updateScope '{updateScope}', it will be ignored.")

    logging.debug(f"Updating reservation {reference_number} - URL: {api_url}, Params: {params}, Body: {json.dumps(body)}")

    try:
        # Use POST for updates as per typical REST patterns for this kind of operation
        response = requests.post(api_url, headers=headers, params=params, json=body)
        logging.debug(f"Update API response: Status={response.status_code}, Body={response.text[:500]}")
        response.raise_for_status() # Check for HTTP errors
        response_data = response.json()
        message = response_data.get("message", "Reservation updated.")
        # The reference number might change if only 'this' or 'future' occurrences are updated
        updated_ref = response_data.get("referenceNumber", reference_number)

        return (f"✅ {message}\n"
                f"Reservation with reference **{updated_ref}** updated successfully.")

    except requests.exceptions.HTTPError as e:
        error_details = "Details unavailable."; error_code = e.response.status_code
        try: error_data = e.response.json(); error_details = error_data.get("message", json.dumps(error_data))
        except json.JSONDecodeError: error_details = e.response.text[:500]
        logging.error(f"❌ HTTP {error_code} error updating reservation {reference_number}: {error_details}", exc_info=True)
        if error_code == 401: return "❌ Authentication Error: Invalid/expired token."
        if error_code == 404: return f"❌ Error: Reservation with reference '{reference_number}' not found."
        # Check for conflicts during update
        if "overlaps" in str(error_details).lower() or error_code == 409:
             start_f = dateparser.parse(startDateTime).strftime('%H:%M') if dateparser.parse(startDateTime) else startDateTime
             end_f = dateparser.parse(endDateTime).strftime('%H:%M') if dateparser.parse(endDateTime) else endDateTime
             return f"❌ Conflict: New time ({start_f} - {end_f}) for resource {resourceId} is already booked or invalid."
        if error_code == 400 and "resourceid" in str(error_details).lower():
             return f"❌ Error: The provided resource ID '{resourceId}' is invalid or does not exist."
        # Generic HTTP error
        return f"❌ Error ({error_code}) updating reservation: {error_details}"
    except requests.RequestException as e:
        logging.error(f"❌ Generic error updating reservation {reference_number}: {e}", exc_info=True)
        return f"❌ Network/server error during update: {e}"
    except json.JSONDecodeError as e:
        logging.error(f"❌ Error parsing JSON update response {reference_number}: {e}", exc_info=True)
        return f"❌ Error parsing server response post-update."
    except Exception as e:
        logging.error(f"❌ Unexpected error in update_reservation for {reference_number}: {e}", exc_info=True)
        return f"❌ Internal error during reservation update {reference_number}."

# --- Tool: get_availability_by_checking_bookings (Nuovo Tool) ---
class GetAvailabilityByBookingsArgs(BaseModel):
    session_token: str = Field(..., description="Il token di sessione valido ottenuto dall'autenticazione.")
    user_id: str = Field(..., description="L'ID utente valido ottenuto dall'autenticazione.")
    resource_id: str = Field(..., description="L'ID specifico della risorsa da verificare.")
    dateTime: str = Field(..., description="La data/ora ISO 8601 esatta per cui verificare la disponibilità (da parse_date, con time_specified=true). Si assume una durata di 1 ora.")

@tool(args_schema=GetAvailabilityByBookingsArgs)
def get_availability_by_checking_bookings(session_token: str, user_id: str, resource_id: str, dateTime: str) -> str:
    """
    Verifica la disponibilità di una risorsa specifica per una data/ora ISO 8601 precisa (con orario specificato),
    controllando la presenza di prenotazioni esistenti. Assume una durata standard di 1 ora per la verifica.
    Questo tool offre un metodo alternativo per verificare la disponibilità basandosi sui dati diretti delle prenotazioni.

    CONDIZIONI D'USO OBBLIGATORIE:
    1.  CHIAMARE `parse_date` PRIMA: È necessario avere la stringa ISO 8601 da `parse_date`.
    2.  VERIFICARE `time_specified`: Chiamare questo tool SOLO SE `parse_date` ha restituito `time_specified: true`.
        Se è `false`, NON CHIAMARE QUESTO TOOL, ma chiedere all'utente di specificare un orario.
    3.  VERIFICARE `resource_id`: Chiamare questo tool SOLO SE si dispone di un `resource_id` specifico.
    """
    if not all([session_token, user_id, resource_id, dateTime]):
        return "❌ Errore: Mancano token, user ID, ID risorsa o data/ora per la verifica."

    if not resource_id.isdigit():
        logging.error(f"get_availability_by_checking_bookings: ID risorsa non valido '{resource_id}'. Deve essere un numero.")
        return f"❌ Errore: ID risorsa '{resource_id}' non valido. Deve essere un numero."

    try:
        start_dt = dateparser.parse(dateTime)
        if not start_dt:
            return f"❌ Errore: Formato data/ora non valido '{dateTime}'. Atteso ISO 8601."

        # Assumiamo una durata di 1 ora per la verifica, come per la creazione automatica.
        req_start_dt = start_dt # Rinomino per chiarezza
        req_end_dt = req_start_dt + datetime.timedelta(hours=1)

    except Exception as e:
        logger.error(f"Errore nella preparazione delle date per get_availability_by_checking_bookings: {e}", exc_info=True)
        return f"❌ Errore interno durante la preparazione delle date per la verifica."

    headers = {"X-Booked-SessionToken": session_token, "X-Booked-UserId": user_id}
    # Assumiamo che l'API /Reservations/ supporti filtri per resourceId e un intervallo di tempo.
    # I nomi dei parametri (es. 'resourceId', 'startDateTime', 'endDateTime') sono ipotetici
    # e dovrebbero essere verificati con la documentazione dell'API LibreBooking.
    # Per una verifica di sovrapposizione robusta, l'API dovrebbe trovare prenotazioni dove:
    # (ReservationStart < SlotEnd) AND (ReservationEnd > SlotStart)
    # Qui simuliamo una query che potrebbe restituire prenotazioni *all'interno* o *sovrapposte* all'intervallo.
    params = {
        "resourceId": resource_id,
        "startDateTime": req_start_dt.isoformat(),
        "endDateTime": req_end_dt.isoformat()
    }
    api_url = f"{LIBREBOOKING_API_URL}/Reservations/"
    logging.info(f"get_availability_by_checking_bookings: Controllo prenotazioni per risorsa {resource_id} tra {req_start_dt.isoformat()} e {req_end_dt.isoformat()} all'URL {api_url} con parametri {params}")

    try:
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        # Assumiamo che la risposta sia una lista di prenotazioni, possibilmente sotto una chiave "reservations".
        reservations_found = data.get("reservations", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

        if not reservations_found:
            # Nessuna prenotazione restituita dall'API nell'intervallo, quindi sicuramente disponibile.
            return f"✅ Risorsa {resource_id}: Disponibile il {req_start_dt.strftime('%d/%m/%Y alle %H:%M')} (verificato tramite controllo prenotazioni)."

        # Se sono state trovate prenotazioni, esegui un controllo di sovrapposizione preciso.
        found_strict_overlap = False
        for booking_data in reservations_found:
            booking_start_str = booking_data.get('startDate')
            booking_end_str = booking_data.get('endDate')

            if not booking_start_str or not booking_end_str:
                logger.warning(f"Prenotazione per risorsa {resource_id} con dati di inizio/fine mancanti: {booking_data}")
                continue # Salta questa prenotazione

            try:
                # Impostazioni per garantire che le date API siano interpretate correttamente
                # e siano confrontabili con req_start_dt (che è timezone-aware, Europe/Rome).
                api_date_parse_settings = {
                    'TIMEZONE': 'Europe/Rome',      # Assume che le date API naive siano in ora di Roma
                    'RETURN_AS_TIMEZONE_AWARE': True # Assicura che diventino aware
                }
                existing_booking_start_dt = dateparser.parse(booking_start_str, settings=api_date_parse_settings)
                existing_booking_end_dt = dateparser.parse(booking_end_str, settings=api_date_parse_settings)

                if not existing_booking_start_dt or not existing_booking_end_dt:
                    logger.warning(f"Impossibile interpretare le date per la prenotazione {booking_data.get('referenceNumber', 'N/A')} sulla risorsa {resource_id}: start='{booking_start_str}', end='{booking_end_str}'")
                    continue

                # Condizione di sovrapposizione stretta: (ReqStart < ExistingEnd) AND (ReqEnd > ExistingStart)
                is_overlapping = (req_start_dt < existing_booking_end_dt) and \
                                 (req_end_dt > existing_booking_start_dt)

                if is_overlapping:
                    logger.info(f"Trovata sovrapposizione per risorsa {resource_id} alle {req_start_dt.strftime('%H:%M')}. "
                                f"Slot richiesto: [{req_start_dt.isoformat()}, {req_end_dt.isoformat()}]. "
                                f"Prenotazione esistente: [{existing_booking_start_dt.isoformat()}, {existing_booking_end_dt.isoformat()}] "
                                f"(Ref: {booking_data.get('referenceNumber', 'N/A')})")
                    found_strict_overlap = True
                    break # Trovata una sovrapposizione, non serve controllare oltre

            except Exception as e:
                logger.error(f"Errore durante l'analisi o il confronto delle date per una prenotazione sulla risorsa {resource_id}: {e}", exc_info=True)
                continue # Salta questa prenotazione in caso di errore

        if found_strict_overlap:
            return f"❌ Risorsa {resource_id}: Non disponibile il {req_start_dt.strftime('%d/%m/%Y alle %H:%M')} (prenotazione esistente trovata in conflitto)."
        else:
            # Nessuna sovrapposizione stretta trovata tra le prenotazioni restituite dalla query API.
            return f"✅ Risorsa {resource_id}: Disponibile il {req_start_dt.strftime('%d/%m/%Y alle %H:%M')} (verificato tramite controllo prenotazioni)."

    except requests.exceptions.HTTPError as e:
        logging.error(f"Errore HTTP in get_availability_by_checking_bookings per risorsa {resource_id}: {e.response.text}", exc_info=True)
        return f"❌ Errore HTTP ({e.response.status_code}) durante la verifica della disponibilità basata su prenotazioni."
    except Exception as e:
        logging.error(f"Errore generico in get_availability_by_checking_bookings per risorsa {resource_id}: {e}", exc_info=True)
        return f"❌ Errore interno durante la verifica della disponibilità basata su prenotazioni."

# --- Tool: get_accessories ---
class GetAccessoriesArgs(BaseModel):
    session_token: str = Field(..., description="Il token di sessione valido ottenuto dall'autenticazione.")
    user_id: str = Field(..., description="L'ID utente valido ottenuto dall'autenticazione.")

@tool(args_schema=GetAccessoriesArgs)
def get_accessories(session_token: str, user_id: str) -> list | str:
    """
    Recupera la lista di tutti gli accessori disponibili.
    Chiama questo tool quando l'utente chiede informazioni sugli accessori disponibili o vuole aggiungere accessori a una prenotazione.
    """
    if not all([session_token, user_id]):
        return "❌ Errore: Mancano token o user ID."
    headers = {"X-Booked-SessionToken": session_token, "X-Booked-UserId": user_id}
    try:
        response = requests.get(f"{LIBREBOOKING_API_URL}/Accessories/", headers=headers)
        response.raise_for_status()
        accessories = response.json().get("accessories", [])
        if not accessories:
            logger.warning("get_accessories: Nessun accessorio trovato nella risposta API.")
            return "⚠️ Nessun accessorio trovato."
        simplified_accessories = [
            {"id": a.get("id"), "name": a.get("name"), "quantityAvailable": a.get("quantityAvailable")}
            for a in accessories if a.get("id") and a.get("name")
        ]
        return simplified_accessories
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            return "❌ Errore Autenticazione: Token non valido/scaduto."
        logger.error(f"❌ Errore HTTP recupero accessori: {e}", exc_info=True)
        return f"❌ Errore HTTP ({e.response.status_code}) recupero accessori."
    except requests.RequestException as e:
        logger.error(f"❌ Errore generico recupero accessori: {e}", exc_info=True)
        return f"❌ Errore rete/server recupero accessori."
    except json.JSONDecodeError as e:
        logger.error(f"❌ Errore parsing JSON per accessori: {e}", exc_info=True)
        return f"❌ Errore analisi risposta accessori."
    except Exception as e:
        logger.error(f"❌ Errore imprevisto elaborazione accessori: {e}", exc_info=True)
        return "❌ Errore interno elaborazione accessori."

# Funzione di serializzazione - INVARIATO

# --- Nuovi Nodi per il Grafo Guidato ---

def initial_processing_node(state: State) -> State:
    """
    Nodo iniziale: gestisce l'autenticazione e analizza la prima richiesta utente.
    """
    logger.info(">>> [initial_processing_node] Chiamato")
    messages = state["messages"]
    new_messages_for_state = list(messages) # Lavora su una copia per lo stato

    # 1. Autenticazione (se necessaria)
    if not state.get("session_token") or not state.get("user_id"):
        logger.info("initial_processing_node: Autenticazione necessaria.")
        # Chiamata diretta al tool, non tramite LLM per questo passaggio specifico
        auth_result = authenticate_tool.invoke({})
        if isinstance(auth_result, dict) and auth_result.get("session_token"):
            state["session_token"] = auth_result["session_token"]
            state["user_id"] = auth_result["user_id"]
            logger.info(f"initial_processing_node: Autenticazione riuscita: Token={state['session_token'][:5]}..., UserID={state['user_id']}")
            # Aggiungiamo un ToolMessage per tracciare l'azione, come farebbe un agente
            # Questo aiuta anche l'LLM nei nodi successivi a "sapere" che l'autenticazione è avvenuta
            # e ad avere il risultato del tool nella cronologia.
            auth_tool_call_id = f"call_{uuid.uuid4().hex[:20]}" # ID più breve
            new_messages_for_state.append(
                AIMessage(
                    content="", # L'LLM non ha bisogno di contenuto qui, solo della tool_call
                    tool_calls=[{"name": "authenticate_tool", "args": {}, "id": auth_tool_call_id, "type":"tool_call"}]
                )
            )
            new_messages_for_state.append(
                ToolMessage(
                    content=json.dumps(auth_result),
                    name="authenticate_tool",
                    tool_call_id=auth_tool_call_id
                )
            )
        else:
            logger.error("initial_processing_node: Autenticazione fallita.")
            error_msg = AIMessage(content="Autenticazione fallita. Impossibile procedere.")
            new_messages_for_state.append(error_msg)
            # Sovrascrivi i messaggi nello stato con quelli aggiornati
            return {**state, "messages": new_messages_for_state}

    # 2. Analizza la prima richiesta utente (se presente) per parole chiave "persone" o "accessori"
    #    e se l'intento è una prenotazione.
    first_user_message_content = ""
    if messages and isinstance(messages[0], HumanMessage):
        first_user_message_content = messages[0].content.lower()
    elif messages and isinstance(messages[0], dict) and messages[0].get("type") == "human": # Gestisce messaggi serializzati
        first_user_message_content = messages[0].get("content", "").lower()

    is_booking_intent = "prenota" in first_user_message_content or \
                        "riserva" in first_user_message_content or \
                        "sala" in first_user_message_content # Semplice euristica

    mentions_people = bool(re.search(r'\b(\d+)\s*(persone|persona)\b', first_user_message_content))
    mentions_accessories_keywords = any(keyword in first_user_message_content for keyword in ["proiettore", "lavagna", "sedie", "accessori"])

    if is_booking_intent and (mentions_people or mentions_accessories_keywords):
        logger.info("initial_processing_node: Rilevata richiesta di prenotazione con menzione di persone/accessori.")
        state["needs_initial_accessories_check"] = True
        state["awaiting_accessories_update"] = False # Ensure this is false at start of new flow
    else:
        state["needs_initial_accessories_check"] = False

    # Aggiorna i messaggi nello stato
    return {**state, "messages": new_messages_for_state}


def get_accessories_node(state: State) -> State:
    """
    Chiama il tool get_accessories e aggiorna lo stato.
    """
    logger.info(">>> [get_accessories_node] Chiamato")
    session_token = state.get("session_token")
    user_id = state.get("user_id")
    new_messages_for_state = list(state.get("messages", []))

    if not session_token or not user_id:
        logger.error("get_accessories_node: Token o User ID mancanti.")
        new_messages_for_state.append(AIMessage(content="Errore: Autenticazione mancante per recuperare gli accessori."))
        return {**state, "messages": new_messages_for_state, "available_accessories": None, "needs_initial_accessories_check": False,
        "awaiting_accessories_update":False}

    try:
        accessories_result = get_accessories.invoke({"session_token": session_token, "user_id": user_id})
        tool_call_id = f"call_{uuid.uuid4().hex[:20]}" # ID più breve
        new_messages_for_state.append(AIMessage(content="", tool_calls=[{"name": "get_accessories", "args": {}, "id": tool_call_id, "type":"tool_call"}]))
        new_messages_for_state.append(ToolMessage(content=json.dumps(accessories_result) if isinstance(accessories_result, list) else str(accessories_result), tool_call_id=tool_call_id, name="get_accessories"))

        if isinstance(accessories_result, list):
            logger.info(f"get_accessories_node: Accessori recuperati: {len(accessories_result)}")
            return {**state, "messages": new_messages_for_state, "available_accessories": accessories_result, "needs_initial_accessories_check": False}
        else: # Errore o formato inatteso
            logger.warning(f"get_accessories_node: get_accessories non ha restituito una lista: {accessories_result}")
            return {**state, "messages": new_messages_for_state, "available_accessories": None, "needs_initial_accessories_check": False}
    except Exception as e:
        logger.error(f"get_accessories_node: Errore durante la chiamata a get_accessories: {e}", exc_info=True)
        new_messages_for_state.append(AIMessage(content=f"Errore durante il recupero degli accessori: {e}"))
        return {**state, "messages": new_messages_for_state, "available_accessories": None, "needs_initial_accessories_check": False}


def ask_details_node(state: State) -> State:
    """
    Nodo che formula la domanda sui dettagli degli accessori all'utente.
    Assume che la disponibilità sia stata verificata e una sala scelta.
    """
    logger.info(">>> [ask_details_node] Chiamato")
    new_messages_for_state = list(state.get("messages", []))
    last_ai_message_content_for_context = "Disponibilità confermata." # Default

    # Cerca l'ultimo messaggio dell'agente che conferma la disponibilità della sala
    # per fornire contesto nella domanda.
    for msg in reversed(new_messages_for_state):
        if isinstance(msg, AIMessage) and msg.content and "disponibile" in msg.content.lower():
            last_ai_message_content_for_context = msg.content
            break
    
    question = (f"{last_ai_message_content_for_context}\n"
                f"Per completare la prenotazione, le servono accessori specifici (es. proiettore, microfono)? "
                f"Se sì, quali e quanti? Le sedie per le persone indicate saranno incluse se disponibili.")
    new_messages_for_state.append(AIMessage(content=question))
    logger.info(f"ask_details_node: Posta domanda sui dettagli: {question}")
    return {**state, "messages": new_messages_for_state, "details_asked": True, "availability_check_done": True}

# --- Fine Nuovi Nodi ---

def serialize_messages(messages: List[Any]) -> List[Dict[str, Any]]:
    """Serializza i messaggi per logging/debugging."""
    serialized = []
    if not isinstance(messages, list): messages = [messages] # Gestisci caso messaggio singolo
    for msg in messages:
        if isinstance(msg, BaseMessage):
            msg_dict = {"type": msg.type, "content": msg.content}
            # Includi chiamate tool se presenti
            tool_calls = getattr(msg, 'tool_calls', None) or msg.additional_kwargs.get('tool_calls')
            if tool_calls: msg_dict['tool_calls'] = tool_calls
            # Includi tool_call_id per ToolMessages
            if isinstance(msg, ToolMessage) and hasattr(msg, 'tool_call_id'): msg_dict['tool_call_id'] = msg.tool_call_id
            serialized.append(msg_dict)
        elif isinstance(msg, tuple) and len(msg) == 2: # Gestisci tuple semplici se usate
            serialized.append({"type": msg[0], "content": msg[1]})
        else:
            # Fallback per tipi sconosciuti
            try: serialized.append({"type": "unknown", "content": str(msg)})
            except Exception: serialized.append({"type": "unserializable", "content": "Non serializzabile"})
    return serialized

# 🔥 Inizializza LLM e Tools - INVARIATO
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)
tools = [
    parse_date, authenticate_tool, get_resources,
    create_reservation, get_reservation, delete_reservation, get_availability_by_checking_bookings, # Aggiunto nuovo tool
    update_reservation, get_accessories
]
llm_with_tools = llm.bind_tools(tools)

# 🎭 Crea l'agente ReAct - INVARIATO

# Modifica le istruzioni di sistema per l'agente ReAct

system_message = """
Sei un assistente AI per la prenotazione di risorse. Il tuo flusso di lavoro è guidato da una StateGraph.
Utilizza gli strumenti a tua disposizione per aiutare l'utente a prenotare, modificare o cancellare sale meeting.
Segui scrupolosamente le condizioni d'uso di ciascuno strumento.

**REGOLA FONDAMENTALE: SEMPLIFICARE LA PRENOTAZIONE**
Il tuo obiettivo è creare una prenotazione di base il prima possibile, per poi offrire all'utente la possibilità di aggiungere dettagli (come accessori o numero di persone) tramite un aggiornamento.

--- FLUSSO DI PRENOTAZIONE ---

1.  **Autenticazione (se necessaria):** Se non hai un token di sessione valido, il sistema chiamerà `authenticate_tool` per te. Parti dal presupposto di essere autenticato.

2.  **Raccogli Info Essenziali:**
    *   Interpreta la data e l'ora richieste dall'utente con `parse_date`.
    *   Se l'utente non specifica una risorsa, usa `get_resources` per vedere le opzioni.

3.  **Verifica Disponibilità e Crea Subito:**
    *   Usa `get_availability_by_checking_bookings` per trovare una risorsa disponibile all'orario richiesto.
    *   **AZIONE IMMEDIATA:** Appena trovi una risorsa disponibile, **DEVI** chiamare immediatamente `create_reservation`.
    *   **PARAMETRI per `create_reservation`:**
        *   Usa `resourceId`, `startDateTime`, e `endDateTime` (calcolata aggiungendo 1 ora a startDateTime) che hai appena verificato.
        *   Per il `title`, usa "Prenotazione Utente [user_id]".
        *   Per la `description`, puoi lasciare vuoto o inserire un testo generico.
        *   **IMPORTANTE:** Per il campo `accessories`, passa **SEMPRE** una lista vuota `[]` in questa fase iniziale.

4.  **Post-Creazione (Gestito dal sistema):**
    *   Dopo una creazione riuscita, il sistema ti chiederà automaticamente se l'utente vuole aggiungere accessori. La tua responsabilità è gestire la risposta dell'utente nel turno successivo.

--- FLUSSO DI AGGIORNAMENTO (DOPO LA CREAZIONE) ---

*   **SE** hai appena creato una prenotazione e il sistema ha chiesto all'utente se vuole aggiungere accessori (`awaiting_accessories_update: true`), il messaggio corrente dell'utente è la sua risposta.
*   **Se l'utente dice 'no' o nega,** rispondi "Perfetto, la sua prenotazione rimane confermata." e termina.
*   **Se l'utente dice 'sì' e fornisce dettagli** (es. "sì, per 10 persone e un proiettore"):
    1.  Usa il numero di riferimento memorizzato nello stato (`last_created_ref`).
    2.  **DEVI** prima chiamare `get_reservation` con quel numero di riferimento per recuperare i dettagli attuali (specialmente `resourceId`, `startDateTime`, `endDateTime`). Questo è FONDAMENTALE.
    3.  Analizza la richiesta dell'utente per il numero di persone e gli accessori. Se necessario, chiama `get_accessories` per verificare la disponibilità e gli ID.
    4.  Prepara i nuovi parametri per `update_reservation`. Aggiorna la `description` per riflettere le modifiche (es. "Per 10 persone con proiettore").
    5.  Chiama `update_reservation`.
    6.  Informa l'utente dell'esito.

--- ALTRI FLUSSI ---

**Cancellazione Prenotazione:**
1.  Usa `get_reservation` per recuperare i dettagli.
2.  Mostra i dettagli all'utente.
3.  Chiedi conferma ESATTA: 'Vuoi cancellare questa prenotazione? Rispondi "sì" per confermare.'
4.  Se l'utente risponde 'sì', chiama `delete_reservation`.

**Modifica Prenotazione Esistente (non immediatamente dopo la creazione):**
*   Simile al flusso di aggiornamento post-creazione. Chiedi il numero di riferimento, usa `get_reservation` per ottenere i dettagli attuali, raccogli le modifiche desiderate e poi chiama `update_reservation`.
"""

# Crea l'agente ReAct con le istruzioni di sistema modificate
react_agent_executor = create_react_agent(
    llm_with_tools,
    tools=tools
)

# Funzione helper per estrarre numero riferimento - INVARIATO
def extract_reference_number(text: str) -> Optional[str]:
    """Estrae un potenziale numero di riferimento (10+ caratteri alfanumerici/trattini) dal testo."""
    # Regex per trovare sequenze di 10 o più caratteri alfanumerici o trattini
    match = re.search(r'\b([a-zA-Z0-9-]{10,})\b', text)
    if match:
        potential_ref = match.group(1)
        # Controllo di base: evita stringhe troppo lunghe o puramente esadecimali (come i token di sessione)
        if len(potential_ref) < 40 and not all(c in '0123456789abcdef' for c in potential_ref.replace('-', '')):
             logging.debug(f"Helper: Estratto potenziale numero riferimento: {potential_ref}")
             return potential_ref
        else:
             logging.debug(f"Helper: Trovato match '{potential_ref}' ma scartato (troppo lungo o sembra hex?).")
    logging.debug(f"Helper: Nessun numero riferimento trovato in: '{text[:100]}...'")
    return None

# 🚀 Nodo Agente - INVARIATO
def agent_node(state: State) -> State:
    """Esegue l'agente ReAct con lo stato fornito."""
    logging.debug(f"🚀 Agente IN: { {k: v for k, v in state.items() if k != 'messages'} }")
    logging.debug(f"📨 Messaggi IN: {json.dumps(serialize_messages(state['messages']), indent=2, ensure_ascii=False)}")

    try:
        # Invoca l'esecutore dell'agente
        response = react_agent_executor.invoke(state)
        logging.debug(f"📬 Risposta Agente (da invoke): {json.dumps(response, default=str, indent=2)}")
    except Exception as e:
        # Gestisci potenziali errori durante esecuzione agente
        logging.error(f"❌ Errore durante react_agent_executor.invoke: {e}", exc_info=True)
        error_message = AIMessage(content=f"Si è verificato un errore interno: {e}")
        current_messages = state.get("messages", [])
        # Restituisci stato con messaggio errore aggiunto
        return {**state, "messages": current_messages + [error_message]}

    output_messages = response.get("messages", [])

    # --- Aggiorna token sessione/user ID se authenticate_tool è stato chiamato ---
    final_token = state.get("session_token")
    final_user_id = state.get("user_id")
    if output_messages:
        # Itera all'indietro per trovare l'ultimo risultato auth
        for msg in reversed(output_messages):
            if isinstance(msg, ToolMessage) and msg.name == "authenticate_tool":
                try:
                    auth_result = json.loads(msg.content)
                    if isinstance(auth_result, dict) and auth_result.get("session_token") and auth_result.get("user_id"):
                        final_token = auth_result["session_token"]
                        final_user_id = auth_result["user_id"]
                        logging.info(f"Trovate nuove credenziali da authenticate_tool: Token={final_token[:5]}..., UserID={final_user_id}")
                        break # Trovato l'ultimo, interrompi ricerca
                except (json.JSONDecodeError, TypeError):
                    logging.warning(f"Risultato non JSON da authenticate_tool: {msg.content}")
    # --- Fine aggiornamento credenziali ---

    # Prepara lo stato finale da restituire
    final_state_output: State = {
        "session_token": final_token,
        "user_id": final_user_id,
        "messages": serialize_messages(output_messages),  # Serializza i messaggi
        # Resetta campi stato transitori (se usati, ora deprecati)
        "reference_number_to_delete": None,
        "reservation_details_to_confirm": None,
        "confirmation_pending": False,
    }

    logging.debug(f"✅ Agente OUT: {{k: v for k, v in final_state_output.items() if k != 'messages'}}")
    logging.debug(f"📩 Messaggi OUT: {json.dumps(final_state_output['messages'], indent=2, ensure_ascii=False)}")
    return final_state_output

# --- Fine logica prenotazione automatica ---

# --- Nodo Agente ReAct Potenziato ---
def enhanced_react_agent_node(state: State) -> Dict[str, Any]:
    """
    Invoca l'agente ReAct e poi aggiorna campi specifici dello stato
    basati sui risultati dei tool chiamati in questo turno.
    Specificamente, popola `state.available_accessories` e gestisce il post-creazione.
    """
    # --- PRE-PROCESSING: Inietta lo stato nel prompt per guidare l'agente ---
    # Crea una copia dello stato da passare all'agente, potenzialmente modificata
    state_for_agent = state.copy()
    update_payload = {}  # Inizia con un payload vuoto

    if state.get("awaiting_accessories_update"):
        last_ref = state.get("last_created_ref")
        # Questo messaggio di sistema informa l'agente del contesto attuale
        info_message_content = (
            f"NOTA DI SISTEMA: Sei nel flusso di aggiornamento per la prenotazione "
            f"appena creata con riferimento '{last_ref}'. "
            f"Il messaggio dell'utente è una risposta alla tua domanda sugli accessori. "
            f"Segui le istruzioni del 'FLUSSO DI AGGIORNAMENTO' per usare `get_reservation` e `update_reservation`."
        )
        # Inserisci il messaggio di sistema all'inizio della cronologia
        # per dare il massimo contesto all'agente per il turno corrente.
        messages_for_agent = [SystemMessage(content=info_message_content)] + list(state["messages"])
        state_for_agent["messages"] = messages_for_agent
        logging.info("enhanced_react_agent_node: Inserito messaggio di stato per il flusso di aggiornamento.")
        # Resetta il flag per evitare che venga riutilizzato in loop.
        # L'agente dovrebbe ora chiamare update_reservation, che non riattiva questo flag.
        update_payload["awaiting_accessories_update"] = False
        update_payload["last_created_ref"] = None

    # --- AGENT INVOCATION ---
    agent_response_dict = react_agent_executor.invoke(state_for_agent)

    # Controlla i messaggi prodotti in questo turno per il risultato dei tool
    messages_from_current_turn = agent_response_dict.get("messages", [])
    if not isinstance(messages_from_current_turn, list):
        messages_from_current_turn = [messages_from_current_turn]

    for msg in reversed(messages_from_current_turn): # Controlla i messaggi più recenti di questo turno
        if isinstance(msg, ToolMessage):
            # Gestione risultato di create_reservation
            if msg.name == "create_reservation":
                result_message = str(msg.content)
                if "✅" in result_message:  # Se la prenotazione è stata creata con successo
                    ref_match = re.search(r"Numero di riferimento: ([a-zA-Z0-9-]+)", result_message)
                    if ref_match:
                        reference_number = ref_match.group(1)
                        # Imposta i flag per il prossimo turno
                        update_payload["awaiting_accessories_update"] = True
                        update_payload["last_created_ref"] = reference_number

                        # --- MODIFICA: Unisci la domanda al messaggio di conferma ---
                        follow_up_question = "\n\nVuole aggiungere accessori supplementari (es. sedie, proiettore) o modificare il numero di partecipanti?"
                        
                        last_ai_message = None
                        # Cerca l'ultimo messaggio di testo dell'AI nella risposta corrente
                        for i in reversed(range(len(agent_response_dict["messages"]))):
                            message = agent_response_dict["messages"][i]
                            if isinstance(message, AIMessage) and not getattr(message, 'tool_calls', None):
                                last_ai_message = message
                                break
                        
                        if last_ai_message and last_ai_message.content:
                            last_ai_message.content += follow_up_question
                            logging.info("enhanced_react_agent_node: Aggiunta domanda di follow-up al messaggio di conferma esistente.")
                        else:
                            # Fallback se non c'è un messaggio di testo a cui appendersi
                            follow_up_message = AIMessage(content=follow_up_question.strip())
                            agent_response_dict["messages"].append(follow_up_message)
                            logging.warning("enhanced_react_agent_node: Nessun messaggio AI di conferma trovato, creata nuova domanda di follow-up.")
                        # --- FINE MODIFICA ---

                        logging.info(f"enhanced_react_agent_node: Prenotazione creata ({reference_number}). Impostato stato per aggiornamento accessori.")
                    else:
                        logging.warning("enhanced_react_agent_node: Messaggio di successo da create_reservation ma numero di riferimento non trovato.")
                break # Trovata la chiamata a create_reservation, esci dal loop

    return {**agent_response_dict, **update_payload}

# 🛠️ Crea il grafo
# Nodi principali del flusso
INITIAL_PROCESSING_NODE_NAME = "initial_processor"
GET_ACCESSORIES_NODE_NAME = "get_accessories_direct"
MAIN_AGENT_NODE_NAME = "main_agent_flow_node" # Rinominiamo per chiarezza

graph_builder = StateGraph(State)
graph_builder.add_node(INITIAL_PROCESSING_NODE_NAME, initial_processing_node)
graph_builder.add_node(GET_ACCESSORIES_NODE_NAME, get_accessories_node)
graph_builder.add_node(MAIN_AGENT_NODE_NAME, enhanced_react_agent_node) # Il tuo agente ReAct principale

graph_builder.add_edge(START, INITIAL_PROCESSING_NODE_NAME)

# Condizione dopo initial_processor
def check_if_accessories_needed_cond(state: State) -> str:
    if state.get("needs_initial_accessories_check"):
        logger.info("Condizione: needs_initial_accessories_check è TRUE -> get_accessories_direct")
        return "get_accessories_needed"
    logger.info("Condizione: needs_initial_accessories_check è FALSE -> main_agent_flow")
    return "continue_to_main_flow"

graph_builder.add_conditional_edges(
    INITIAL_PROCESSING_NODE_NAME,
    check_if_accessories_needed_cond,
    {
        "get_accessories_needed": GET_ACCESSORIES_NODE_NAME,
        "continue_to_main_flow": MAIN_AGENT_NODE_NAME
    }
)
graph_builder.add_edge(GET_ACCESSORIES_NODE_NAME, MAIN_AGENT_NODE_NAME)
graph_builder.add_edge(MAIN_AGENT_NODE_NAME, END) # Dopo il nodo agente principale, il turno finisce.

graph = graph_builder.compile()

# 🚀 Nodo Agente Principale (chiamato da FastAPI) - MODIFICATO per usare il grafo compilato
def agent_node(state: State) -> State:
    """Esegue il grafo compilato con lo stato fornito."""
    logging.debug(f"🚀 agent_node (via grafo) IN: { {k: v for k, v in state.items() if k != 'messages'} }")
    
    # I messaggi in input da FastAPI sono dizionari JSON.
    # State(messages=...) con add_messages dovrebbe gestire la conversione in oggetti BaseMessage.
    # Per sicurezza, logghiamo i messaggi come vengono ricevuti prima che il grafo li processi.
    if "messages" in state and isinstance(state["messages"], list):
        # Non possiamo usare serialize_messages qui se sono già dict, darebbe errore.
        # Logghiamo una rappresentazione sicura.
        try:
            logging.debug(f"📨 Messaggi IN (per grafo, raw): {json.dumps(state['messages'], indent=2, ensure_ascii=False)}")
        except TypeError:
            logging.debug(f"📨 Messaggi IN (per grafo, raw): {str(state['messages'])}")

    try:
        # Invoca il grafo compilato
        response_from_graph = graph.invoke(state)
        logging.debug(f"📬 Risposta Grafo (da invoke): {json.dumps(response_from_graph, default=str, indent=2, ensure_ascii=False)}")
    except Exception as e:
        logging.error(f"❌ Errore durante graph.invoke in agent_node: {e}", exc_info=True)
        error_message_content = f"Si è verificato un errore interno durante l'elaborazione: {e}"
        current_messages_from_input_state = state.get("messages", [])
        # Assicurati che current_messages_from_input_state sia una lista di BaseMessage o dict
        # Se sono dict, convertili prima di aggiungere AIMessage, o assicurati che add_messages lo faccia.
        # Per semplicità, assumiamo che add_messages gestisca i dict in input allo State.
        updated_messages_list = current_messages_from_input_state + [AIMessage(content=error_message_content)]
        
        error_state_to_return: State = {**state, "messages": serialize_messages(updated_messages_list)}
        return error_state_to_return

    final_messages_from_graph = response_from_graph.get("messages", [])
    serialized_output_messages = serialize_messages(final_messages_from_graph)
    final_state_output: State = {**response_from_graph, "messages": serialized_output_messages}
    if "auto_book_target" in final_state_output: del final_state_output["auto_book_target"]

    logging.debug(f"✅ agent_node (via grafo) OUT: {{k: v for k, v in final_state_output.items() if k != 'messages'}}")
    logging.debug(f"📩 Messaggi OUT (da grafo, serializzati): {json.dumps(final_state_output['messages'], indent=2, ensure_ascii=False)}")
    return final_state_output

# Funzione per eseguire il grafo e stampare output - INVARIATO
def run_graph_interaction(initial_state: State) -> State:
    """Esegue un'interazione completa del grafo e restituisce lo stato finale."""
    logging.debug(f"run_graph_interaction: Stato IN: Token={initial_state.get('session_token', 'N/A')[:5]}..., UserID={initial_state.get('user_id', 'N/A')}, Msgs={len(initial_state.get('messages', []))}")

    # Invoca il grafo compilato
    final_state = graph.invoke(initial_state)

    # Stampa la risposta finale dell'assistente o l'ultimo messaggio tool
    print("Assistant: ", end="", flush=True)
    if final_state and final_state.get("messages"):
        try:
            last_assistant_message_content = None
            last_tool_message = None
            # Trova l'ultimo AIMessage con contenuto, o l'ultimissimo ToolMessage
            for msg in reversed(final_state["messages"]):
                 if isinstance(msg, AIMessage) and msg.content:
                      last_assistant_message_content = msg.content
                      break # Trovata la risposta principale
                 elif isinstance(msg, ToolMessage):
                      if last_tool_message is None: # Tieni traccia dell'ultimo messaggio tool come fallback
                           last_tool_message = msg

            if last_assistant_message_content:
                # Stampa la risposta principale dell'assistente
                print(last_assistant_message_content)
            elif last_tool_message:
                 # Fallback: Stampa il contenuto dell'ultima chiamata tool se non c'è messaggio assistente
                 status_symbol = "✅" if "✅" in str(last_tool_message.content) else ("⚠️" if "⚠️" in str(last_tool_message.content) else ("❌" if "❌" in str(last_tool_message.content) else ""))
                 if status_symbol:
                     # Stampa risultato tool con icona stato
                     print(f"{status_symbol} Risultato op ({last_tool_message.name}): {last_tool_message.content.replace(status_symbol, '').strip()}")
                 else:
                     # Stampa risultato tool generico
                     print(f"Op completata ({last_tool_message.name}). Risultato: {last_tool_message.content}")
            else:
                 # Non dovrebbe succedere se il grafo è stato eseguito, ma gestiscilo
                 logging.warning("Nessun AIMessage con contenuto o ToolMessage finale trovato.")
                 print("Operazione completata (nessun messaggio testuale finale).")

        except Exception as e:
            logging.error(f"Errore stampa messaggio finale: {e}", exc_info=True)
            print("Errore visualizzazione risposta.")
    else:
        # Se il grafo restituisce uno stato vuoto
        print("Nessuna risposta generata o stato finale vuoto.")
    print() # Nuova riga per chiarezza

    return final_state


# Loop esecuzione principale - MODIFICATO CON MESSAGGIO BENVENUTO
def main():
    """Funzione principale per gestire il loop di interazione con l'utente."""
    username, password = "admin", "password" # Credenziali hardcoded
    print("Tentativo di autenticazione...")
    auth_result = authenticate(username, password)
    current_session_token: Optional[str] = None
    current_user_id: Optional[str] = None
    message_history: List[Any] = [] # Memorizza la cronologia conversazione

    if auth_result and auth_result.get("session_token") and  auth_result.get("user_id"):
        # Autenticazione iniziale riuscita
        current_session_token = auth_result["session_token"]
        current_user_id = auth_result["user_id"]
        print(" Autenticazione riuscita!")
        logging.info(f"Token iniziale: {current_session_token[:5]}..., UserID: {current_user_id}")

       

        # Inizia il loop interazione
        while True:
            try:
                user_input = input("User: ")
                if user_input.lower() in ["quit", "exit", "q", "esci"]:
                    print("Arrivederci!"); break
                if not user_input.strip(): # Ignora input vuoto
                    continue

                # Aggiungi messaggio utente alla cronologia
                # --- MODIFICA: Assicurati che la history non contenga il messaggio di benvenuto ---
                # Se è il primo input dell'utente, la history è vuota, altrimenti contiene i messaggi precedenti
                current_messages = list(message_history) # Crea una copia
                current_messages.append(HumanMessage(content=user_input))
                # --- FINE MODIFICA ---


                # Prepara lo stato per il grafo
                current_state = State(
                    session_token=current_session_token,
                    user_id=current_user_id,
                    messages=current_messages, # Usa la copia aggiornata
                    # Assicura che i campi deprecati siano None/False
                    reference_number_to_delete=None,
                    reservation_details_to_confirm=None,
                    confirmation_pending=False
                )

                # Esegui il grafo con lo stato corrente
                final_state = run_graph_interaction(current_state)

                # Aggiorna token, user ID e cronologia messaggi dallo stato finale
                current_session_token = final_state.get("session_token")
                current_user_id = final_state.get("user_id")
                message_history = final_state.get("messages", []) # Ottieni la cronologia aggiornata per il prossimo turno

                # Log stato dopo il turno
                logging.debug(f"--- Fine Turno ---")
                logging.debug(f"Token aggiornato in main: {current_session_token[:5] if current_session_token else 'None'}...")
                logging.debug(f"UserID aggiornato in main: {current_user_id}")
                logging.debug(f"Messaggi totali per prossimo turno: {len(message_history)}")
                logging.debug(f"--------------------")

            except KeyboardInterrupt:
                # Permetti uscita pulita con Ctrl+C
                print("\nArrivederci!"); break
            except Exception as e:
                 # Cattura errori imprevisti nel loop
                 logging.error(f"Errore imprevisto nel loop: {e}", exc_info=True)
                 print("⚠️ Errore imprevisto. Riprova.")
    else:
        # Autenticazione iniziale fallita
        print("❌ Autenticazione iniziale fallita.")

if __name__ == "__main__":
    try:
        # Leggi i dati JSON passati come argomento
        input_data = json.loads(sys.argv[1])
        # ...elabora i dati con l'agente...
        response = agent_node({"messages": input_data})
        # Restituisci la risposta come JSON
        print(json.dumps(response))
        
    except Exception as e:
        logging.error(f"Errore generico: {e}", exc_info=True)
        # Restituisci l'errore come JSON per il frontend
        print(json.dumps({"error": f"Errore interno del server: {str(e)}"}), file=sys.stderr)
        sys.exit(1) # Esci con codice di errore

if __name__ == "__main__":
    # Configura il logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # Imposta un livello più basso per i log di librerie rumorose se necessario
    # logging.getLogger("httpx").setLevel(logging.WARNING) # Commentato per debug più facile
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("langchain_core").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("dateparser").setLevel(logging.WARNING) # dateparser può essere rumoroso
  
  
    # Esegui la funzione principale
    main()
  