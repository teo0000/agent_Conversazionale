# Copilot Instructions for agent_Conversazionale

## Architettura generale
- Il progetto è un assistente conversazionale full-stack:
  - **Backend** (`Backend/`): Python/FastAPI, gestisce AI, riconoscimento vocale, sintesi vocale, parsing date, gestione prenotazioni. Espone API REST.
  - **Frontend** (`Frontend/`): React/Next.js, interfaccia chat e voce, UI moderna e accessibile.
- I componenti comunicano tramite chiamate HTTP tra frontend e backend.

## Flussi di lavoro principali
- **Avvio Backend**:
  - Da `Backend/`: `uvicorn main:app --reload`
  - Dipendenze in `requirements.txt`. Usa ambiente virtuale Python (`python -m venv .venv; .venv\Scripts\Activate; pip install -r requirements.txt`).
- **Avvio Frontend**:
  - Da `Frontend/`: `npm install` poi `npm run dev`
- **Configurazione API**:
  - Aggiorna endpoint API nel frontend se il backend gira su host/porta diversi.

## Convenzioni e pattern
- **Backend**:
  - Entrypoint: `main.py` (FastAPI)
  - Logica agente: `agent.py` (gestione conversazione, AI)
  - Speech: usa SpeechRecognition, gTTS, pydub
  - Integrazione AI: langchain/langgraph, OpenAI
  - Chiavi API: da variabili ambiente/config file
- **Frontend**:
  - Directory `app/`: routing Next.js, pagine, API
  - Directory `components/assistant-ui/`: UI chat, voce, markdown
  - Directory `components/ui/`: elementi UI condivisi
  - UI: React + Tailwind CSS, TypeScript
  - Voice chat: supporto registrazione e TTS

## Dipendenze e integrazioni
- **Backend**: OpenAI, langchain, langgraph, SpeechRecognition, gTTS, pydub
- **Frontend**: Next.js, React, Tailwind CSS

## Esempi di pattern
- Chiamata API dal frontend:
  ```ts
  fetch('http://localhost:8001/api/chat', { method: 'POST', body: ... })
  ```
- Componente UI personalizzato:
  ```tsx
  // components/assistant-ui/AnimatedAvatar.tsx
  export default function AnimatedAvatar() { ... }
  ```

## Note
- Segui la struttura delle directory e i file principali per estendere funzionalità.
- Consulta i README in `Backend/` e `Frontend/` per dettagli su installazione e avvio.
- Aggiorna questa guida se cambi flussi o convenzioni.
