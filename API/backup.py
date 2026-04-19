import discord
import json
import os
import glob
from datetime import datetime
from API.config import BACKUP_DIR, MAX_BACKUPS_PER_GUILD


def _backup_path(guild_id: int, timestamp: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    return os.path.join(BACKUP_DIR, f"{guild_id}_{timestamp}.json")


async def create_backup(guild: discord.Guild) -> str:
    """
    Crea uno snapshot completo del server e lo salva su disco.
    Restituisce il percorso del file di backup.
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Snapshot canali
    channels_data = []
    for ch in guild.channels:
        ch_info = {
            "id": ch.id,
            "name": ch.name,
            "type": str(ch.type),
            "position": ch.position,
            "category_id": ch.category_id,
        }
        if isinstance(ch, discord.TextChannel):
            ch_info["topic"] = ch.topic
            ch_info["slowmode_delay"] = ch.slowmode_delay
            ch_info["nsfw"] = ch.nsfw
        elif isinstance(ch, discord.VoiceChannel):
            ch_info["bitrate"] = ch.bitrate
            ch_info["user_limit"] = ch.user_limit
        channels_data.append(ch_info)

    # Snapshot ruoli
    roles_data = []
    for role in guild.roles:
        roles_data.append({
            "id": role.id,
            "name": role.name,
            "color": role.color.value,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
            "permissions": role.permissions.value,
            "position": role.position,
        })

    # Snapshot categorie
    categories_data = []
    for cat in guild.categories:
        categories_data.append({
            "id": cat.id,
            "name": cat.name,
            "position": cat.position,
        })

    # Info generali del server
    guild_info = {
        "id": guild.id,
        "name": guild.name,
        "description": guild.description,
        "afk_timeout": guild.afk_timeout,
        "verification_level": str(guild.verification_level),
        "default_notifications": str(guild.default_notifications),
        "explicit_content_filter": str(guild.explicit_content_filter),
        "mfa_level": guild.mfa_level,
    }

    backup = {
        "timestamp": timestamp,
        "guild": guild_info,
        "channels": channels_data,
        "roles": roles_data,
        "categories": categories_data,
    }

    path = _backup_path(guild.id, timestamp)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2)

    # Pulizia backup vecchi
    _cleanup_old_backups(guild.id)

    return path


def _cleanup_old_backups(guild_id: int):
    """Mantiene solo gli ultimi MAX_BACKUPS_PER_GUILD backup."""
    pattern = os.path.join(BACKUP_DIR, f"{guild_id}_*.json")
    files = sorted(glob.glob(pattern))
    while len(files) > MAX_BACKUPS_PER_GUILD:
        os.remove(files.pop(0))


def list_backups(guild_id: int) -> list[dict]:
    """Restituisce la lista dei backup disponibili per un server."""
    pattern = os.path.join(BACKUP_DIR, f"{guild_id}_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    result = []
    for f in files:
        fname = os.path.basename(f)
        ts = fname.replace(f"{guild_id}_", "").replace(".json", "")
        result.append({"file": f, "timestamp": ts})
    return result


def load_backup(guild_id: int, index: int = 0) -> dict | None:
    """
    Carica un backup. index=0 è il più recente.
    """
    backups = list_backups(guild_id)
    if not backups:
        return None
    if index >= len(backups):
        return None
    with open(backups[index]["file"], encoding="utf-8") as f:
        return json.load(f)


async def restore_backup(guild: discord.Guild, backup: dict) -> list[str]:
    """
    Tenta di ripristinare il server allo stato del backup.
    Restituisce una lista di log delle operazioni.
    """
    logs = []

    # Ripristina il nome del server
    try:
        if guild.name != backup["guild"]["name"]:
            await guild.edit(name=backup["guild"]["name"])
            logs.append(f"✅ Nome server ripristinato: {backup['guild']['name']}")
    except Exception as e:
        logs.append(f"⚠️ Impossibile ripristinare nome server: {e}")

    # Ripristina i nomi dei canali
    for ch_data in backup["channels"]:
        ch = guild.get_channel(ch_data["id"])
        if ch is None:
            logs.append(f"⚠️ Canale #{ch_data['name']} non trovato (ID {ch_data['id']}), non ripristinato")
            continue
        try:
            edits = {}
            if ch.name != ch_data["name"]:
                edits["name"] = ch_data["name"]
            if isinstance(ch, discord.TextChannel):
                if ch.topic != ch_data.get("topic"):
                    edits["topic"] = ch_data.get("topic") or ""
                if ch.slowmode_delay != ch_data.get("slowmode_delay", 0):
                    edits["slowmode_delay"] = ch_data.get("slowmode_delay", 0)
            if edits:
                await ch.edit(**edits)
                logs.append(f"✅ Canale #{ch_data['name']} ripristinato")
        except Exception as e:
            logs.append(f"⚠️ Errore ripristino canale #{ch_data['name']}: {e}")

    # Ripristina i ruoli (solo nome e colore, i permessi sono delicati)
    for role_data in backup["roles"]:
        role = guild.get_role(role_data["id"])
        if role is None or role.name == "@everyone":
            continue
        try:
            edits = {}
            if role.name != role_data["name"]:
                edits["name"] = role_data["name"]
            if role.color.value != role_data["color"]:
                edits["color"] = discord.Color(role_data["color"])
            if edits:
                await role.edit(**edits)
                logs.append(f"✅ Ruolo @{role_data['name']} ripristinato")
        except Exception as e:
            logs.append(f"⚠️ Errore ripristino ruolo @{role_data['name']}: {e}")

    return logs