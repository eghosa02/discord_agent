"""
Agente AI: invia il messaggio a Ollama/Gemma4,
interpreta la risposta e decide se/cosa eseguire.
"""
import json
import httpx
import discord
from API.config import OLLAMA_URL, OLLAMA_MODEL, CONFIDENCE_THRESHOLD


SYSTEM_PROMPT = """Sei un agente AI che gestisce un server Discord.
Il tuo compito è analizzare i messaggi e decidere se sono comandi destinati a te.

Contesto del server disponibile: canali, ruoli, membri (ti verranno forniti nel messaggio).

REGOLE:
1. Rispondi SEMPRE e SOLO con JSON valido, nient'altro.
2. Se il messaggio non è un comando per te (es: conversazione normale, saluti tra utenti), metti is_command: false.
3. Se è un comando, estrai l'azione e i parametri.
4. Sii conservativo: se non sei sicuro, metti is_command: false.

SCHEMA RISPOSTA:
{
  "is_command": true | false,
  "confidence": 0.0-1.0,
  "reasoning": "breve spiegazione",
  "action": "nome_azione o null",
  "params": { ... } o {},
  "reply": "messaggio da mostrare all'utente (in italiano)"
}

AZIONI DISPONIBILI:
- create_channel: params: {name, type (text/voice/category), category?, topic?}
- delete_channel: params: {name}
- rename_channel: params: {name, new_name}
- set_channel_topic: params: {name, topic}
- create_role: params: {name, color? (#hex), mentionable?, hoist?}
- delete_role: params: {name}
- rename_role: params: {name, new_name}
- assign_role: params: {member, role}
- remove_role: params: {member, role}
- kick_member: params: {member, reason?}
- ban_member: params: {member, reason?, delete_message_days?}
- unban_member: params: {member}
- rename_server: params: {name}
- set_slowmode: params: {channel, seconds}
- create_category: params: {name}
- move_channel: params: {channel, category}
- list_channels: params: {}
- list_roles: params: {}
- restore_backup: params: {index?} — ripristina il server al backup (index=0 = più recente)
- list_backups: params: {} — mostra i backup disponibili

ESEMPI di messaggi che NON sono comandi: "ciao gigo", "come stai?", "gg ragazzi", "lol", qualsiasi conversazione tra utenti.
ESEMPI di comandi: "agente IA crea un canale #gaming", "bot, rinomina il canale generale in lobby", "AI rinomina il ruolo admin in staff"."""


def _build_context(guild: discord.Guild) -> str:
    """Crea un riassunto del server per il contesto del modello."""
    channels = ", ".join(f"#{c.name}" for c in guild.text_channels[:20])
    roles = ", ".join(f"@{r.name}" for r in guild.roles if r.name != "@everyone")[:300]
    categories = ", ".join(cat.name for cat in guild.categories[:10])
    return (
        f"Server: {guild.name} | "
        f"Canali testuali: {channels} | "
        f"Categorie: {categories} | "
        f"Ruoli: {roles}"
    )


async def analyze_message(
    message: discord.Message,
    guild: discord.Guild,
) -> dict:
    """
    Invia il messaggio a Gemma4 via Ollama.
    Restituisce il dict parsed dalla risposta JSON del modello.
    """
    context = _build_context(guild)
    user_prompt = (
        f"CONTESTO SERVER: {context}\n\n"
        f"AUTORE: {message.author.display_name} (ruoli: "
        f"{', '.join(r.name for r in getattr(message.author, 'roles', [])[1:][:5])})\n"
        f"CANALE: #{message.channel.name}\n"
        f"MESSAGGIO: {message.content}"
    )

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,   # bassa temperatura per risposte più deterministiche
            "top_p": 0.9,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw = data["message"]["content"].strip()

            # Pulizia nel caso il modello aggiunga markdown fence
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip().rstrip("```").strip()

            result = json.loads(raw)
            return result

    except httpx.ConnectError:
        return {
            "is_command": False,
            "confidence": 0.0,
            "reasoning": "Ollama non raggiungibile",
            "action": None,
            "params": {},
            "reply": "❌ Impossibile connettersi a Ollama. Assicurati che sia in esecuzione su localhost:11434",
        }
    except json.JSONDecodeError as e:
        return {
            "is_command": False,
            "confidence": 0.0,
            "reasoning": f"JSON non valido dalla risposta: {e}",
            "action": None,
            "params": {},
            "reply": "❌ Il modello ha restituito una risposta non valida.",
        }
    except Exception as e:
        return {
            "is_command": False,
            "confidence": 0.0,
            "reasoning": str(e),
            "action": None,
            "params": {},
            "reply": f"❌ Errore durante l'analisi: {e}",
        }


def should_execute(result: dict) -> bool:
    """Decide se eseguire il comando in base alla confidenza."""
    return (
        result.get("is_command", False)
        and result.get("confidence", 0.0) >= CONFIDENCE_THRESHOLD
        and result.get("action") is not None
    )