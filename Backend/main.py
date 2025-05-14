from fastapi import FastAPI, Request
from lolll import agent_node, State
import logging

app = FastAPI()
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.info("Test log dal file main.py")

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
        return {"error": str(e)}