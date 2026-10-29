"""
Servidor del agente para el panel de chat del dashboard.

Uso (desde la carpeta raíz del proyecto):
    1. Copiar agent/.env.example a agent/.env y poner la API key de OpenRouter
    2. python agent/server.py
    3. Abrir visualization/dashboard.html en el navegador

El agente usa LangChain con un modelo gratuito de OpenRouter. No decide la
prioridad: las reglas y el puntaje vienen del SQL; el agente los consulta con
herramientas y los explica.
"""
import json
import os
from pathlib import Path
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from tools import TOOLS, get_connection

load_dotenv(Path(__file__).resolve().parent / ".env")

API_KEY = os.getenv("OPENROUTER_API_KEY")
# Los modelos gratuitos de OpenRouter cambian seguido; si uno falla se prueba el siguiente
MODELS = [m.strip() for m in os.getenv(
    "OPENROUTER_MODELS",
    "nvidia/nemotron-3.5-super-vl:free,google/gemma-4-31b-it:free,google/gemma-4-26b-a4b-it:free",
).split(",") if m.strip()]

# Contexto de negocio, diccionario de tablas, métricas y reglas de respuesta.
# Está en un archivo aparte para poder ajustarlo sin tocar el código.
SYSTEM_PROMPT = (Path(__file__).resolve().parent / "context.md").read_text(encoding="utf-8")

prompt = ChatPromptTemplate.from_messages([
    # Se pasa como mensaje y no como plantilla para que las llaves del texto no se lean como variables
    SystemMessage(SYSTEM_PROMPT),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])

_executors = {}


def get_executor(model):
    if model not in _executors:
        llm = ChatOpenAI(
            model=model,
            api_key=API_KEY,
            base_url="https://openrouter.ai/api/v1",
            temperature=0.2,
            timeout=90,
            max_retries=1,
        )
        agent = create_tool_calling_agent(llm, TOOLS, prompt)
        _executors[model] = AgentExecutor(
            agent=agent,
            tools=TOOLS,
            max_iterations=6,
            return_intermediate_steps=True,
            handle_parsing_errors=True,
        )
    return _executors[model]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    context: Optional[dict] = None


app = FastAPI(title="Ads Campaign Agent")
# El dashboard se abre como archivo local (origen "null"), por eso se permite cualquier origen
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok", "models": MODELS, "api_key_loaded": bool(API_KEY)}


@app.post("/chat")
def chat(request: ChatRequest):
    if not API_KEY:
        raise HTTPException(500, "Falta OPENROUTER_API_KEY en agent/.env")

    user_input = request.message
    if request.context:
        user_input += "\n\n[Filtros activos en el dashboard]\n" + json.dumps(request.context, ensure_ascii=False)

    chat_history = [
        HumanMessage(m.content) if m.role == "user" else AIMessage(m.content)
        for m in request.history
    ]

    errors = []
    for model in MODELS:
        try:
            result = get_executor(model).invoke({"input": user_input, "chat_history": chat_history})
        except Exception as error:  # modelo caído, sin cupo o sin soporte de herramientas
            errors.append(f"{model}: {str(error)[:200]}")
            print(f"[agente] falló {model}: {error}")
            continue

        answer = (result.get("output") or "").strip()
        if not answer:
            errors.append(f"{model}: respuesta vacía")
            continue
        tools_used = list(dict.fromkeys(step[0].tool for step in result.get("intermediate_steps", [])))
        return {"answer": answer, "tools_used": tools_used, "model": model}

    raise HTTPException(502, "Ningún modelo respondió. " + " | ".join(errors))


if __name__ == "__main__":
    get_connection()  # falla al arrancar si faltan los CSV de outputs/
    if not API_KEY:
        print("Aviso: falta OPENROUTER_API_KEY en agent/.env; el chat no va a responder.")
    # Dentro de Docker se usa AGENT_HOST=0.0.0.0 para poder llegar desde el navegador del equipo
    uvicorn.run(app, host=os.getenv("AGENT_HOST", "127.0.0.1"), port=8000)
