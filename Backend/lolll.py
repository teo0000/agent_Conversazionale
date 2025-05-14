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
from langgraph.prebuilt import create_react_agent
import dateparser
import json
import logging
import datetime
import pprint
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
# Configura il logging
logging.basicConfig(level=logging.DEBUG)  # Cambiato a INFO per meno verbosità, DEBUG se necessario
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

        # Impostazioni per il parsing delle date
        settings = {
            'PREFER_DATES_FROM': 'future',
            'TIMEZONE': 'Europe/Rome',
            'RETURN_AS_TIMEZONE_AWARE': True,
            # 'DATE_ORDER': 'DMY' # Verrà impostato condizionatamente
        }
        languages = ['it', 'en']

        # Controlla se processed_input (ciò che vedrà dateparser) assomiglia a una data ISO.
        # Regex per YYYY-MM-DD[Tt]HH:MM:SS (con opzionali frazioni di secondo e timezone)
        iso_datetime_pattern = r'^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[\+\-]\d{2}:\d{2})?$'
        # Regex per YYYY-MM-DD
        iso_date_pattern = r'^\d{4}-\d{2}-\d{2}$'

        if not (re.match(iso_datetime_pattern, processed_input) or re.match(iso_date_pattern, processed_input)):
            # Se non è una data/datetime ISO stretta, potrebbe essere "DD/MM/YYYY" o linguaggio naturale.
            # In questi casi, specialmente per l'italiano "DD/MM/YYYY", DMY è preferito.
            settings['DATE_ORDER'] = 'DMY'
            logger.debug(f"parse_date: Input '{processed_input}' non è ISO stretto. Usando DATE_ORDER: DMY.")
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

        # Restituisci il risultato in formato JSON
        iso_string = target_date.isoformat()
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

# --- Tool: get_availability (VERSIONE CORRETTA) ---
class GetAvailabilityArgs(BaseModel):
    session_token: str = Field(..., description="The valid session token obtained from authentication.")
    user_id: str = Field(..., description="The valid user ID obtained from authentication.")
    resource_id: str = Field(..., description="The **specific** ID of the resource (obtained from `get_resources` or the conversation) to check availability for.")
    dateTime: str = Field(..., description="The **EXACT ISO 8601 date/time WITH TIME SPECIFIED** to check availability for (obtained from `parse_date` where `time_specified` is `true`).")
@tool(args_schema=GetAvailabilityArgs)
def get_availability(session_token: str, user_id: str, resource_id: str, dateTime: str) -> str:
    """
    Checks the availability of **A SINGLE** specific resource for **A SINGLE** precise ISO 8601 date/time **(with time)**.

    **MANDATORY USAGE CONDITIONS:**
    1.  **CALL `parse_date` FIRST:** You must have the ISO 8601 string from `parse_date`.
    2.  **CHECK `time_specified`:** Call this tool **ONLY IF** `parse_date` returned `time_specified: true`. If it's `false`, **DO NOT CALL THIS TOOL**, but ask the user to specify a time.
    3.  **CHECK `resource_id`:** Call this tool **ONLY IF** you have a specific `resource_id`.
        *   If the user specified a resource, use that ID.
        *   If the user did NOT specify a resource, **DO NOT CALL THIS TOOL DIRECTLY FOR ALL RESOURCES**. Instead:
            a) Call `get_resources` to get the list [ {resourceId: '1', name: 'Room A'}, ... ].
            b) **Call THIS TOOL (`get_availability`) REPEATEDLY**, once for each `resourceId` in the list, always using the same precise `dateTime`.
            c) Collect all results and present them in a summary to the user.

    **OUTPUT:**
    - Returns a string indicating if the resource is available (✅) or not (❌) for the requested time.
    - If NOT available (❌), the string will include the next availability time (`availableAt`) for THAT resource, if provided by the API.

    **HOW TO USE THE OUTPUT (IN THE FINAL SUMMARY TO THE USER):**
    - If available (✅): Indicate "Available".
    - If NOT available (❌) with next availability: Indicate "Not available (next avail. [Date/Time])".
    - If NOT available (❌) without next availability: Indicate "Not available".
    """
    if not all([session_token, user_id, resource_id, dateTime]):
        return "❌ Error: Missing token, user ID, resource ID, or date/time for verification."

    # --- Input validation ---
    if not resource_id.isdigit():
        logging.error(f"get_availability: Invalid resource_id '{resource_id}'. Must be a digit.")
        return f"❌ Error: Invalid resource ID '{resource_id}'. It must be a number."
    try:
        # Basic check if dateTime looks like ISO 8601
        datetime.datetime.fromisoformat(dateTime.replace('Z', '+00:00'))
    except ValueError:
        logging.error(f"get_availability: Invalid dateTime format '{dateTime}'. Must be ISO 8601.")
        return f"❌ Error: Invalid date/time format '{dateTime}'. Expected ISO 8601."
    # --- End Input validation ---


    try:
        # Check if called for midnight, might indicate missing time specification logic
        dt_obj = dateparser.parse(dateTime)
        if dt_obj and dt_obj.hour == 0 and dt_obj.minute == 0 and dt_obj.second == 0 and dt_obj.microsecond == 0:
             logging.warning(f"get_availability called for midnight ({dateTime}). Verify if time was specified by user and parse_date logic is correct.")
    except Exception:
        pass # Ignore parsing errors here, main call handles it

    headers = {"X-Booked-SessionToken": session_token, "X-Booked-UserId": user_id}
    availability_url = f"{LIBREBOOKING_API_URL}/Resources/{resource_id}/Availability"
    params: Dict[str, str] = {"dateTime": dateTime}

    logging.debug(f"--- DEBUG get_availability (Documented Endpoint) ---")
    logging.debug(f"Calling URL: {availability_url}")
    logging.debug(f"Headers Sent: {headers}")
    logging.debug(f"Parameters Sent (Query String): {params}")

    try:
        response = requests.get(availability_url, headers=headers, params=params)

        logging.debug(f"Response Received (Status Code): {response.status_code}")
        try:
            raw_response_text = response.text
            logging.debug(f"Response Received (Raw Text): {raw_response_text[:1000]}")
        except Exception as e:
            logging.debug(f"Could not read raw response text: {e}")

        response.raise_for_status()
        availability_data = response.json()

        logging.debug(f"Response Received (Parsed JSON):\n{pprint.pformat(availability_data)}")

        is_available = False
        next_available_str = None
        resource_name = f"Resource {resource_id}" # Default name
        slot_info = None # Initialize slot_info

        # --- MODIFICA: Gestisci la lista interna inattesa ---
        if isinstance(availability_data, dict) and "resources" in availability_data and \
           isinstance(availability_data["resources"], list) and len(availability_data["resources"]) > 0 and \
           isinstance(availability_data["resources"][0], list): # Controlla se il primo elemento è una LISTA

            # Itera sulla lista interna per trovare la risorsa corretta
            inner_resource_list = availability_data["resources"][0]
            for resource_data in inner_resource_list:
                if isinstance(resource_data, dict):
                    # Controlla se 'resource' esiste ed è un dizionario
                    res_details = resource_data.get("resource")
                    if isinstance(res_details, dict) and res_details.get("resourceId") == resource_id:
                        slot_info = resource_data # Trovata la risorsa corretta!
                        logging.debug(f"Found matching resource data for ID {resource_id}: {slot_info}")
                        break # Esci dal loop una volta trovata
            if slot_info is None:
                 logging.warning(f"Resource ID {resource_id} not found within the inner list returned by API.")
        # --- FINE MODIFICA ---
        else:
            logging.warning(f"Unexpected API response structure (expected 'resources' -> list -> list): {availability_data}")

        # --- Ora processa slot_info SE è stato trovato ---
        if isinstance(slot_info, dict):
            is_available = slot_info.get("available", False)
            actual_availability_verified = False # Nuovo flag per la verifica dettagliata

            # Estrai nome risorsa se presente
            resource_details = slot_info.get("resource")
            if isinstance(resource_details, dict):
                resource_name = resource_details.get("name", resource_name)

            # --- Logica CORRETTA per controllare la disponibilità effettiva ---
            if is_available: # Se l'API dice che è generalmente disponibile...
                available_until_iso = slot_info.get("availableUntil") # Campo chiave dall'API
                if available_until_iso:
                    try:
                        dt_requested = dateparser.parse(dateTime)
                        dt_available_until = dateparser.parse(available_until_iso)

                        if dt_requested and dt_available_until:
                            # La risorsa è disponibile se l'ora richiesta è STRETTAMENTE PRIMA di availableUntil.
                            # Si assume che una prenotazione duri almeno un certo tempo (es. 1 ora).
                            # Se la richiesta è per le 16:00 e availableUntil è 16:00, non è disponibile.
                            if dt_requested < dt_available_until:
                                actual_availability_verified = True
                                logging.debug(f"VERIFIED: Resource {resource_name} ({resource_id}) available at {dateTime} (requested) as it's before availableUntil ({available_until_iso}).")
                            else:
                                logging.debug(f"NOT AVAILABLE: Resource {resource_name} ({resource_id}) marked available by API, but requested time {dateTime} is NOT strictly before availableUntil ({available_until_iso}).")
                        else:
                            logging.warning(f"Could not parse requested dateTime ({dateTime}) or availableUntil ({available_until_iso}) for comparison. Assuming not available for safety.")
                            actual_availability_verified = False
                    except Exception as parse_err:
                        logging.warning(f"Error comparing requested time with availableUntil ({available_until_iso}): {parse_err}. Assuming not available.")
                        actual_availability_verified = False
                else:
                    # Se 'available' è true ma 'availableUntil' manca, è un dato API incompleto.
                    # Per sicurezza, consideriamolo non verificabile o non disponibile per l'ora specifica.
                    logging.warning(f"Resource {resource_name} ({resource_id}) marked available by API, but 'availableUntil' is missing. Cannot confirm specific time slot availability.")
                    actual_availability_verified = False # O True se si vuole essere ottimisti, ma è rischioso
            
            is_available = actual_availability_verified # Aggiorna is_available con la verifica effettiva

            # Se non disponibile (dopo tutti i controlli), cerca prossima disponibilità
            if not is_available:
                available_at_iso = slot_info.get("availableAt")
                if available_at_iso:
                    try:
                        dt_available = dateparser.parse(available_at_iso)
                        if dt_available:
                            next_available_str = dt_available.strftime('%d/%m/%Y at %H:%M') # Formato italiano
                    except Exception as parse_err:
                        logging.warning(f"Error parsing 'availableAt' ({available_at_iso}): {parse_err}")
        # --- Fine processamento slot_info ---

        # --- Formatta la stringa di ritorno per l'agente ---
        requested_dt_str = ""
        try:
            parsed_req_dt = dateparser.parse(dateTime)
            if parsed_req_dt:
                requested_dt_str = f" on {parsed_req_dt.strftime('%d/%m')} at {parsed_req_dt.strftime('%H:%M')}" # Formato italiano
        except Exception:
            requested_dt_str = f" for {dateTime}"

        if is_available:
            return f"✅ {resource_name}: Available{requested_dt_str}."
        elif next_available_str:
            return f"❌ {resource_name}: Not available{requested_dt_str} (next avail: {next_available_str})."
        else:
            return f"❌ {resource_name}: Not available{requested_dt_str}."

    # --- Gestione eccezioni ---
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401: return "❌ Authentication Error: Invalid/expired token."
        if e.response.status_code == 404: return f"❌ Error: Resource '{resource_id}' not found or availability endpoint incorrect ({availability_url})."
        logging.error(f"❌ HTTP error get_availability {resource_id}: {e}", exc_info=True)
        return f"❌ HTTP Error ({e.response.status_code}) retrieving availability for {resource_id}."
    except requests.RequestException as e:
        logging.error(f"❌ Generic error get_availability {resource_id}: {e}", exc_info=True)
        return f"❌ Network/server error retrieving availability for {resource_id}."
    except json.JSONDecodeError as e:
        logging.error(f"❌ Error parsing JSON get_availability {resource_id}: {e}", exc_info=True)
        return f"❌ Error parsing availability response for {resource_id}."
    except Exception as e: # Catch other unexpected errors (e.g., date parsing)
        logging.error(f"❌ Unexpected error in get_availability for {resource_id}: {e}", exc_info=True)
        return f"❌ Internal error during availability check for {resource_id}."
    finally:
        logging.debug(f"--- END DEBUG get_availability for resource {resource_id} ---")


# --- Tool: create_reservation ---
class CreateReservationArgs(BaseModel):
    session_token: str = Field(..., description="The valid session token obtained from authentication.")
    user_id: str = Field(..., description="The valid user ID obtained from authentication.")
    title: str = Field(default="", description="Reservation title (optional).")
    description: str = Field(default="", description="Reservation description (optional).")
    startDateTime: str = Field(..., description='ISO 8601 start date/time (from parse_date).')
    endDateTime: str = Field(..., description='ISO 8601 end date/time (calculated or from parse_date).')
    resourceId: str = Field(..., description="Specific resource ID (from get_resources).")

@tool(args_schema=CreateReservationArgs)
def create_reservation(session_token: str, user_id: str, startDateTime: str, endDateTime: str, resourceId: str, title: str = "", description: str = "") -> str:
    """
    Crea una prenotazione per una risorsa specifica in un intervallo di tempo.
    """
    if not all([session_token, user_id, startDateTime, endDateTime, resourceId]):
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
        "allowParticipation": False
    }

    logger.debug(f"create_reservation: Corpo della richiesta: {json.dumps(body)}")

    try:
        response = requests.post(f"{LIBREBOOKING_API_URL}/Reservations/", json=body, headers=headers)
        logger.debug(f"create_reservation: Risposta API: Status={response.status_code}, Body={response.text[:500]}")
        response.raise_for_status()

        response_data = response.json()
        ref_num = response_data.get("referenceNumber")
        message = response_data.get("message", "Prenotazione creata.")

        if ref_num:
            logger.info(f"create_reservation: Prenotazione creata con successo. Numero di riferimento: {ref_num}")
            start_dt_parsed = dateparser.parse(startDateTime)
            start_formatted = start_dt_parsed.strftime('%d/%m/%Y alle %H:%M') if start_dt_parsed else startDateTime
            return (f"✅ {message}\n"
                    f"Prenotazione per la risorsa {resourceId} il {start_formatted}.\n"
                    f"**Numero di riferimento:** **{ref_num}**")
        else:
            logger.warning("create_reservation: Prenotazione creata ma il numero di riferimento è vuoto.")
            return f"⚠️ {message} (Attenzione: numero di riferimento non ricevuto)."

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
    updateScope: Optional[str] = None
) -> str:
    """
    Updates an existing reservation identified by its reference number.
    Requires the exact reference number and the new reservation details (at least dates and a valid resource ID).
    The agent should use this tool when the user explicitly asks to modify a reservation.
    It might be necessary to call `get_reservation` first to confirm current details, including the `resourceId`.
    If `get_reservation` does not return a valid resource ID, the agent MUST ask the user which resource to use.
    Returns a success or error message.
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


# Funzione di serializzazione - INVARIATO
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
    parse_date, authenticate_tool, get_availability, get_resources,
    create_reservation, get_reservation, delete_reservation,
    update_reservation
]
llm_with_tools = llm.bind_tools(tools)

# 🎭 Crea l'agente ReAct - INVARIATO
react_agent_executor = create_react_agent(llm_with_tools, tools=tools)

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


# 🛠️ Crea il grafo - INVARIATO
graph_builder = StateGraph(State)
graph_builder.add_node("agent", agent_node)
graph_builder.add_edge(START, "agent") # Inizia sempre con l'agente
graph_builder.add_edge("agent", END) # L'agente decide quando terminare
graph = graph_builder.compile()

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
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
