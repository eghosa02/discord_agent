import os
from dotenv import load_dotenv

load_dotenv()

# Token del bot Discord (da https://discord.com/developers/applications)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "IL_TUO_TOKEN_QUI")

# URL Ollama locale
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")

# Soglia di confidenza per decidere se è un comando AI (0.0 - 1.0)
CONFIDENCE_THRESHOLD = 0.65

# Ruoli che possono dare comandi all'agente
# L'owner del server ha sempre accesso
ALLOWED_ROLES = {
    "owner",      # owner del server (automatico)
    "admin",
    "administrator",
    "moderator",
    "mod",
    "staff",
    # aggiungi qui altri nomi di ruolo del tuo server
}

# Cartella dove salvare i backup
BACKUP_DIR = "./backups"

# Numero massimo di backup da tenere per server
MAX_BACKUPS_PER_GUILD = 20