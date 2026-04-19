"""
Bot Discord con agente AI locale (Ollama/Gemma4).
Avvio: python bot.py
"""
import asyncio
import discord
from discord.ext import commands

from API.config import DISCORD_TOKEN, ALLOWED_ROLES
from .agent import analyze_message, should_execute
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
    if not has_permission(member, guild):
        return  # Ignora silenziosamente

    # 2. Analisi con Gemma4
    async with message.channel.typing():
        result = await analyze_message(message, guild)

    # 3. Se non è un comando, ignora (nessuna risposta)
    if not result.get("is_command", False):
        # DEBUG: decommenta per vedere cosa analizza il modello
        # print(f"[IGNORED] {message.author}: {message.content[:60]} | {result.get('reasoning','')}")
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

    action_name = result.get("action", "")
    params = result.get("params", {})

    # 5. Gestione speciale: lista backup
    if action_name == "list_backups":
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

    # 6. Gestione speciale: restore backup
    if action_name == "restore_backup":
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

    # 7. Esecuzione normale: backup → azione
    action_fn = ACTION_MAP.get(action_name)
    if action_fn is None:
        await message.channel.send(
            f"❓ Azione `{action_name}` non riconosciuta.\n"
            f"> Ragionamento: {result.get('reasoning', '')}"
        )
        return

    # Backup automatico prima di modificare
    backup_msg = await message.channel.send(
        f"🔄 Sto eseguendo: **{action_name}**\n"
        f"> {result.get('reasoning', '')}\n"
        f"⏳ Creazione backup in corso..."
    )

    try:
        backup_path = await create_backup(guild)
        await backup_msg.edit(
            content=(
                f"🔄 Esecuzione: **{action_name}**\n"
                f"💾 Backup salvato: `{backup_path}`\n"
                f"⏳ Esecuzione azione..."
            )
        )
    except Exception as e:
        await backup_msg.edit(
            content=f"⚠️ Backup fallito (`{e}`), procedo comunque..."
        )

    # Esecuzione azione
    try:
        action_result = await action_fn(guild, params)
        await message.channel.send(action_result)
    except discord.Forbidden:
        await message.channel.send(
            "❌ Il bot non ha i permessi necessari per questa azione.\n"
            "Assicurati che il ruolo del bot sia sopra i ruoli che vuole gestire."
        )
    except discord.HTTPException as e:
        await message.channel.send(f"❌ Errore Discord API: {e}")
    except Exception as e:
        await message.channel.send(f"❌ Errore inaspettato: {e}")


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