# Conversational Agent – Backend

This Python backend exposes APIs for a conversational virtual assistant, supporting:
- Speech recognition (SpeechRecognition, gTTS, pydub)
- AI chat (FastAPI, langchain, langgraph, OpenAI)
- Date parsing and booking management

## Requirements
- Python 3.10+
- Virtual environment (recommended)
- All dependencies are listed in `requirements.txt`

## Installation
```powershell
# From this folder
python -m venv .venv
.venv\Scripts\Activate
pip install -r requirements.txt
```

## Start the server
```powershell
uvicorn main:app --reload
```

## Main features
- FastAPI endpoints for chat and TTS
- Integration with OpenAI models via langchain/langgraph
- Speech recognition and synthesis support

## File structure
- `main.py` – FastAPI entrypoint
- `lolll.py` – agent logic, AI, conversation management
- `requirements.txt` – Python dependencies

## Notes
- Set your OpenAI API keys via environment variables or a config file.
- For the frontend, see the `Frontend/` folder.

---

© 2025 – Internship Project
