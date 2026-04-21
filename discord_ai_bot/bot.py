"""
Bot Discord con agente AI locale (Ollama/Gemma4).
Avvio: python bot.py
"""
import asyncio
import discord
from discord.ext import commands

from API.config import DISCORD_TOKEN, ALLOWED_ROLES
from agent import analyze_message, should_execute
from decisione.actions import ACTION_MAP
from API.backup import create_backup, list_backups, load_backup, restore_backup


# Intent necessari
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


def has_permission(member: discord.Member, guild: discord.Guild) -> bool:
    """
    Verifica se il membro ha i permessi per dare comandi all'agente.
    L'owner del server ha sempre accesso.
    """
    if guild.owner_id == member.id:
        return True
    if member.guild_permissions.administrator:
        return True
    member_role_names = {r.name.lower() for r in member.roles}
    return bool(member_role_names & {r.lower() for r in ALLOWED_ROLES})


@bot.event
async def on_ready():
    print(f"✅ Bot avviato: {bot.user} (ID: {bot.user.id})")
    print(f"   Server connessi: {len(bot.guilds)}")
    for g in bot.guilds:
        print(f"   - {g.name} ({g.id})")


@bot.event
async def on_message(message: discord.Message):
    # Ignora i messaggi del bot stesso
    if message.author == bot.user:
        return

    # Processa i comandi prefissati (es: !help)
    await bot.process_commands(message)

    # Ignora messaggi senza guild (DM)
    if not message.guild:
        return

    guild = message.guild
    member = guild.get_member(message.author.id)
    if member is None:
        return

    # 1. Verifica permessi
    """if not has_permission(member, guild):
        return  # Ignora silenziosamente"""

    # 2. Analisi con Gemma4
    print(f"📩 Messaggio da {member.display_name} in #{message.channel.name}, in analisi")
    async with message.channel.typing():
        result = await analyze_message(message, guild)
    print(f"   → Analisi completata: is_command={result.get('is_command')}")
    print(f"   → Ragionamento: {result.get('reasoning')}")

    # 3. Non è un comando — ma è rivolto al bot?
    if not result.get("is_command", False):
        if result.get("is_for_me", False):
            reply = result.get("reply", "")
            if reply:
                await message.channel.send(reply)
        return

    # 4. Confidenza troppo bassa
    if not should_execute(result):
        conf = result.get("confidence", 0)
        await message.channel.send(
            f"🤔 Ho capito che vuoi fare qualcosa ma non sono sicuro abbastanza "
            f"(confidenza: {conf:.0%}). Puoi essere più specifico?\n"
            f"> {result.get('reasoning', '')}"
        )
        return

    actions = result.get("actions", [])

    # 5. Gestione speciale: azioni singole non distruttive (list/backup)
    special = {s["action"] for s in actions}

    if special == {"list_backups"}:
        backups = list_backups(guild.id)
        if not backups:
            await message.channel.send("📂 Nessun backup disponibile.")
            return
        lines = ["📂 **Backup disponibili:**"]
        for i, b in enumerate(backups):
            label = "*(più recente)*" if i == 0 else ""
            lines.append(f"  `[{i}]` {b['timestamp']} {label}")
        await message.channel.send("\n".join(lines))
        return

    if special == {"list_channels"}:
        fn = ACTION_MAP["list_channels"]
        await message.channel.send(await fn(guild, {}))
        return

    if special == {"list_roles"}:
        fn = ACTION_MAP["list_roles"]
        await message.channel.send(await fn(guild, {}))
        return

    # 6. Gestione speciale: restore backup (richiede conferma)
    restore_steps = [a for a in actions if a["action"] == "restore_backup"]
    if restore_steps:
        params = restore_steps[0].get("params", {})
        index = int(params.get("index", 0))
        backup_data = load_backup(guild.id, index)
        if backup_data is None:
            await message.channel.send("❌ Nessun backup trovato.")
            return

        confirm_msg = await message.channel.send(
            f"⚠️ **Restore backup `{backup_data['timestamp']}`**\n"
            f"Questo ripristinerà nomi di canali, ruoli e impostazioni del server.\n"
            f"Reagisci con ✅ entro 30 secondi per confermare, ❌ per annullare."
        )
        await confirm_msg.add_reaction("✅")
        await confirm_msg.add_reaction("❌")

        def check(reaction, user):
            return (
                user == message.author
                and str(reaction.emoji) in ["✅", "❌"]
                and reaction.message.id == confirm_msg.id
            )

        try:
            reaction, _ = await bot.wait_for("reaction_add", timeout=30.0, check=check)
            if str(reaction.emoji) == "❌":
                await message.channel.send("🚫 Restore annullato.")
                return
        except asyncio.TimeoutError:
            await message.channel.send("⏱️ Timeout: restore annullato.")
            return

        await message.channel.send("⏳ Restore in corso...")
        logs = await restore_backup(guild, backup_data)
        report = "\n".join(logs[:20])
        await message.channel.send(f"**Restore completato:**\n{report}")
        return

    # 7. Esecuzione multi-azione: backup unico → loop azioni
    reply = result.get("reply", "")
    n = len(actions)
    intro = f"{reply}\n" if reply else ""
    backup_msg = await message.channel.send(
        f"{intro}📋 **Piano: {n} azione{'' if n == 1 else 'i'}**\n"
        f"> {result.get('reasoning', '')}\n"
        f"💾 Creazione backup in corso..."
    )

    try:
        backup_path = await create_backup(guild)
        await backup_msg.edit(content=backup_msg.content.replace(
            "💾 Creazione backup in corso...",
            f"💾 Backup salvato: `{backup_path}`\n⏳ Esecuzione in corso..."
        ))
    except Exception as e:
        await backup_msg.edit(content=backup_msg.content.replace(
            "💾 Creazione backup in corso...",
            f"⚠️ Backup fallito (`{e}`), procedo comunque..."
        ))

    # Esegui ogni azione in sequenza
    results = []
    # Dizionario per tracciare i rinomina: vecchio_nome → nuovo_nome
    renamed_channels = {}
    renamed_categories = {}

    for i, step in enumerate(actions, 1):
        action_name = step.get("action", "")
        params = dict(step.get("params", {}))  # copia per non mutare l'originale

        # Strip del # dai nomi canale (il modello a volte lo include)
        for key in ("name", "new_name", "channel"):
            if key in params and isinstance(params[key], str):
                params[key] = params[key].lstrip("#")

        # Risolvi automaticamente i nomi se sono stati rinominati in precedenza
        if action_name in ("rename_channel", "delete_channel", "set_channel_topic",
                           "set_slowmode", "move_channel"):
            key = "name" if "name" in params else "channel"
            if key in params and params[key] in renamed_channels:
                params[key] = renamed_channels[params[key]]

        if action_name in ("rename_category", "move_channel"):
            if "category" in params and params["category"] in renamed_categories:
                params["category"] = renamed_categories[params["category"]]

        action_fn = ACTION_MAP.get(action_name)

        if action_fn is None:
            results.append(f"`[{i}/{n}]` ❓ `{action_name}` non riconosciuta — saltata")
            continue

        try:
            res = await action_fn(guild, params)
            results.append(f"`[{i}/{n}]` {res}")
            # Aggiorna il dizionario dei rinomina per le azioni successive
            if action_name == "rename_channel":
                renamed_channels[step["params"].get("name", "")] = params.get("new_name", "")
            elif action_name == "rename_category":
                renamed_categories[step["params"].get("name", "")] = params.get("new_name", "")
        except discord.Forbidden:
            results.append(f"`[{i}/{n}]` ❌ `{action_name}` — permessi insufficienti")
        except discord.HTTPException as e:
            results.append(f"`[{i}/{n}]` ❌ `{action_name}` — errore API: {e}")
        except Exception as e:
            results.append(f"`[{i}/{n}]` ❌ `{action_name}` — errore: {e}")

    # Manda il report finale (a blocchi se troppo lungo)
    report = "\n".join(results)
    if len(report) > 1900:
        # Manda in più messaggi
        chunk = []
        for line in results:
            chunk.append(line)
            if len("\n".join(chunk)) > 1600:
                await message.channel.send("\n".join(chunk[:-1]))
                chunk = [line]
        if chunk:
            await message.channel.send("\n".join(chunk))
    else:
        await message.channel.send(f"**✅ Completato ({n} azioni):**\n{report}")


@bot.command(name="backup")
async def cmd_backup(ctx: commands.Context):
    """Crea manualmente un backup del server."""
    if not has_permission(ctx.author, ctx.guild):
        return
    try:
        path = await create_backup(ctx.guild)
        await ctx.send(f"💾 Backup manuale creato: `{path}`")
    except Exception as e:
        await ctx.send(f"❌ Errore backup: {e}")


@bot.command(name="backups")
async def cmd_backups(ctx: commands.Context):
    """Elenca i backup disponibili."""
    if not has_permission(ctx.author, ctx.guild):
        return
    backups = list_backups(ctx.guild.id)
    if not backups:
        await ctx.send("📂 Nessun backup disponibile.")
        return
    lines = ["📂 **Backup disponibili:**"]
    for i, b in enumerate(backups):
        label = "*(più recente)*" if i == 0 else ""
        lines.append(f"  `[{i}]` {b['timestamp']} {label}")
    lines.append("\nUsa `!restore <indice>` o dì all'agente 'ripristina il backup'.")
    await ctx.send("\n".join(lines))


@bot.command(name="restore")
async def cmd_restore(ctx: commands.Context, index: int = 0):
    """Ripristina il server a un backup (default: il più recente)."""
    if not has_permission(ctx.author, ctx.guild):
        return
    backup_data = load_backup(ctx.guild.id, index)
    if backup_data is None:
        await ctx.send(f"❌ Backup `[{index}]` non trovato.")
        return

    confirm = await ctx.send(
        f"⚠️ Ripristinare il backup `{backup_data['timestamp']}`?\n"
        f"Reagisci ✅ per confermare o ❌ per annullare."
    )
    await confirm.add_reaction("✅")
    await confirm.add_reaction("❌")

    def check(r, u):
        return u == ctx.author and str(r.emoji) in ["✅", "❌"] and r.message.id == confirm.id

    try:
        reaction, _ = await bot.wait_for("reaction_add", timeout=30.0, check=check)
        if str(reaction.emoji) == "❌":
            await ctx.send("🚫 Restore annullato.")
            return
    except asyncio.TimeoutError:
        await ctx.send("⏱️ Timeout: restore annullato.")
        return

    await ctx.send("⏳ Restore in corso...")
    logs = await restore_backup(ctx.guild, backup_data)
    report = "\n".join(logs[:20])
    await ctx.send(f"**Restore completato:**\n{report}")


@bot.command(name="aihelp")
async def cmd_aihelp(ctx: commands.Context):
    """Mostra cosa può fare l'agente AI."""
    if not has_permission(ctx.author, ctx.guild):
        return
    help_text = (
        "🤖 **Agente AI — Cosa puoi chiedermi:**\n\n"
        "**Canali:**\n"
        "• crea un canale #nome (testuale/vocale/categoria)\n"
        "• elimina il canale #nome\n"
        "• rinomina #vecchio in #nuovo\n"
        "• imposta il topic di #canale a '...'\n"
        "• sposta #canale nella categoria Nome\n"
        "• imposta slowmode su #canale a 10 secondi\n"
        "• elenca i canali\n\n"
        "**Ruoli:**\n"
        "• crea un ruolo @Nome (con colore #hex opzionale)\n"
        "• elimina il ruolo @Nome\n"
        "• rinomina @VecchioRuolo in @NuovoRuolo\n"
        "• assegna @Ruolo a [utente]\n"
        "• rimuovi @Ruolo da [utente]\n"
        "• elenca i ruoli\n\n"
        "**Moderazione:**\n"
        "• kicka [utente] (motivo opzionale)\n"
        "• banna [utente] (motivo opzionale)\n"
        "• sbanna [utente]\n\n"
        "**Server:**\n"
        "• rinomina il server in 'Nuovo Nome'\n\n"
        "**Backup:**\n"
        "• mostra i backup disponibili\n"
        "• ripristina il backup più recente\n"
        "• ripristina il backup [numero]\n\n"
        "**Comandi diretti:** `!backup`, `!backups`, `!restore [indice]`"
    )
    await ctx.send(help_text)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    print("🚀 Avvio bot...")
    bot.run(DISCORD_TOKEN)