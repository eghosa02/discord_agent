"""
Agente AI: invia il messaggio a Ollama/Gemma4,
interpreta la risposta e decide se/cosa eseguire.
"""
import json
import httpx
import discord
from API.config import OLLAMA_URL, OLLAMA_MODEL, CONFIDENCE_THRESHOLD
import traceback


SYSTEM_PROMPT = """Sei un agente AI che gestisce un server Discord e può rispondere a domande.
Il tuo compito è analizzare i messaggi e decidere cosa fare.

Contesto del server disponibile: canali, ruoli, membri (ti verranno forniti nel messaggio).

REGOLE:
1. Rispondi SEMPRE e SOLO con JSON valido, nient'altro.
2. Se il messaggio è una conversazione tra utenti (es: "ciao gigo", "gg ragazzi") metti is_command: false e is_for_me: false.
3. Se il messaggio è rivolto a te (domanda, richiesta di info, saluto al bot) metti is_command: false e is_for_me: true, e compila reply.
4. Se è un comando di gestione server, metti is_command: true e compila actions con UNA O PIÙ azioni in sequenza.
5. Per richieste creative o generiche ("abbellisci il server", "organizza meglio i canali") pianifica autonomamente tutte le azioni necessarie.
6. Sii conservativo: se non sei sicuro che sia un comando, metti is_command: false.

SCHEMA RISPOSTA:
{
  "is_command": true | false,
  "is_for_me": true | false,
  "confidence": 0.0-1.0,
  "reasoning": "breve spiegazione del piano",
  "actions": [
    {"action": "nome_azione", "params": { ... }},
    {"action": "nome_azione", "params": { ... }}
  ],
  "reply": "messaggio introduttivo da mostrare prima di eseguire (in italiano)"
}

NOTA: actions può contenere una sola azione o molte. Se is_command è false, actions deve essere [].

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
- rename_category: params: {name, new_name}
- move_channel: params: {channel, category}
- list_channels: params: {}
- list_roles: params: {}
- restore_backup: params: {index?}
- list_backups: params: {}

ESEMPIO risposta per "abbellisci il server":
{
  "is_command": true,
  "is_for_me": true,
  "confidence": 0.95,
  "reasoning": "Aggiungo emoji ai nomi dei canali e creo categorie ordinate",
  "actions": [
    {"action": "rename_channel", "params": {"name": "generale", "new_name": "💬・generale"}},
    {"action": "set_channel_topic", "params": {"name": "💬・generale", "topic": "Canale principale"}},
    {"action": "create_role", "params": {"name": "Membro", "color": "#5865F2", "hoist": true}}
  ],
  "reply": "Perfetto! Inizio subito a sistemare il server 🎨"
}

REGOLA CRITICA sulle azioni sequenziali: se rinomini un canale o una categoria in un'azione,
tutte le azioni successive che lo riferiscono DEVONO usare il NUOVO nome, non quello vecchio.
Esempio corretto: rename_channel "gen" → "💬・generale", poi set_channel_topic su "💬・generale".
Esempio SBAGLIATO: rename_channel "gen" → "💬・generale", poi set_channel_topic su "gen".

REGOLA CRITICA sull'ordine: se vuoi agire su un canale che non esiste ancora, devi prima crearlo.
Esempio corretto: create_channel "benvenuto", poi set_channel_topic su "benvenuto".
Esempio SBAGLIATO: set_channel_topic su "benvenuto" senza averlo creato prima.

REGOLA sui nomi canale: scrivi sempre i nomi dei canali SENZA il simbolo #.
Esempio corretto: "name": "generale"
Esempio SBAGLIATO: "name": "#generale"
"""

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
        async with httpx.AsyncClient(timeout=200.0) as client:
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
        traceback.print_exc()
        return {
            "is_command": False,
            "confidence": 0.0,
            "reasoning": str(e) if e is not None else "timeout",
            "action": None,
            "params": {},
            "reply": f"❌ Errore durante l'analisi: {e}",
        }


def should_execute(result: dict) -> bool:
    """Decide se eseguire il comando in base alla confidenza."""
    return (
        result.get("is_command", False)
        and result.get("confidence", 0.0) >= CONFIDENCE_THRESHOLD
        and bool(result.get("actions"))
    )