"""
Tutte le azioni che l'agente può eseguire sul server Discord.
Ogni funzione riceve il guild e i parametri estratti da Gemma4.
"""
import discord
from typing import Any


async def create_channel(guild: discord.Guild, params: dict) -> str:
    name = params.get("name", "nuovo-canale")
    ch_type = params.get("type", "text").lower()
    category_name = params.get("category")
    topic = params.get("topic", "")

    category = None
    if category_name:
        category = discord.utils.get(guild.categories, name=category_name)

    if ch_type == "voice":
        ch = await guild.create_voice_channel(name, category=category)
    elif ch_type == "category":
        ch = await guild.create_category(name)
    else:
        ch = await guild.create_text_channel(name, category=category, topic=topic)

    return f"✅ Canale `#{ch.name}` creato (tipo: {ch_type})"


async def delete_channel(guild: discord.Guild, params: dict) -> str:
    name = params.get("name", "")
    ch = discord.utils.get(guild.channels, name=name)
    if ch is None:
        return f"❌ Canale `#{name}` non trovato"
    await ch.delete()
    return f"✅ Canale `#{name}` eliminato"


async def rename_channel(guild: discord.Guild, params: dict) -> str:
    old_name = params.get("name", "")
    new_name = params.get("new_name", "")
    ch = discord.utils.get(guild.channels, name=old_name)
    if ch is None:
        return f"❌ Canale `#{old_name}` non trovato"
    await ch.edit(name=new_name)
    return f"✅ Canale rinominato da `#{old_name}` a `#{new_name}`"


async def set_channel_topic(guild: discord.Guild, params: dict) -> str:
    name = params.get("name", "")
    topic = params.get("topic", "")
    ch = discord.utils.get(guild.text_channels, name=name)
    if ch is None:
        return f"❌ Canale testuale `#{name}` non trovato"
    await ch.edit(topic=topic)
    return f"✅ Topic di `#{name}` impostato"


async def create_role(guild: discord.Guild, params: dict) -> str:
    name = params.get("name", "nuovo-ruolo")
    color_hex = params.get("color", "#99aab5")
    mentionable = params.get("mentionable", False)
    hoist = params.get("hoist", False)

    try:
        color = discord.Color(int(color_hex.lstrip("#"), 16))
    except Exception:
        color = discord.Color.default()

    role = await guild.create_role(
        name=name,
        color=color,
        mentionable=mentionable,
        hoist=hoist,
    )
    return f"✅ Ruolo `@{role.name}` creato"


async def delete_role(guild: discord.Guild, params: dict) -> str:
    name = params.get("name", "")
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        return f"❌ Ruolo `@{name}` non trovato"
    await role.delete()
    return f"✅ Ruolo `@{name}` eliminato"


async def rename_role(guild: discord.Guild, params: dict) -> str:
    old_name = params.get("name", "")
    new_name = params.get("new_name", "")
    role = discord.utils.get(guild.roles, name=old_name)
    if role is None:
        return f"❌ Ruolo `@{old_name}` non trovato"
    await role.edit(name=new_name)
    return f"✅ Ruolo rinominato da `@{old_name}` a `@{new_name}`"


async def assign_role(guild: discord.Guild, params: dict) -> str:
    member_name = params.get("member", "")
    role_name = params.get("role", "")

    member = discord.utils.find(
        lambda m: m.name.lower() == member_name.lower() or m.display_name.lower() == member_name.lower(),
        guild.members,
    )
    if member is None:
        return f"❌ Membro `{member_name}` non trovato"

    role = discord.utils.get(guild.roles, name=role_name)
    if role is None:
        return f"❌ Ruolo `@{role_name}` non trovato"

    await member.add_roles(role)
    return f"✅ Ruolo `@{role_name}` assegnato a `{member.display_name}`"


async def remove_role(guild: discord.Guild, params: dict) -> str:
    member_name = params.get("member", "")
    role_name = params.get("role", "")

    member = discord.utils.find(
        lambda m: m.name.lower() == member_name.lower() or m.display_name.lower() == member_name.lower(),
        guild.members,
    )
    if member is None:
        return f"❌ Membro `{member_name}` non trovato"

    role = discord.utils.get(guild.roles, name=role_name)
    if role is None:
        return f"❌ Ruolo `@{role_name}` non trovato"

    await member.remove_roles(role)
    return f"✅ Ruolo `@{role_name}` rimosso da `{member.display_name}`"


async def kick_member(guild: discord.Guild, params: dict) -> str:
    member_name = params.get("member", "")
    reason = params.get("reason", "Nessun motivo specificato")

    member = discord.utils.find(
        lambda m: m.name.lower() == member_name.lower() or m.display_name.lower() == member_name.lower(),
        guild.members,
    )
    if member is None:
        return f"❌ Membro `{member_name}` non trovato"

    await member.kick(reason=reason)
    return f"✅ `{member.display_name}` kickato. Motivo: {reason}"


async def ban_member(guild: discord.Guild, params: dict) -> str:
    member_name = params.get("member", "")
    reason = params.get("reason", "Nessun motivo specificato")
    delete_days = params.get("delete_message_days", 0)

    member = discord.utils.find(
        lambda m: m.name.lower() == member_name.lower() or m.display_name.lower() == member_name.lower(),
        guild.members,
    )
    if member is None:
        return f"❌ Membro `{member_name}` non trovato"

    await guild.ban(member, reason=reason, delete_message_days=delete_days)
    return f"✅ `{member.display_name}` bannato. Motivo: {reason}"


async def unban_member(guild: discord.Guild, params: dict) -> str:
    username = params.get("member", "")
    bans = [entry async for entry in guild.bans()]
    entry = discord.utils.find(lambda e: e.user.name.lower() == username.lower(), bans)
    if entry is None:
        return f"❌ Nessun ban trovato per `{username}`"
    await guild.unban(entry.user)
    return f"✅ `{entry.user.name}` sbannato"


async def rename_server(guild: discord.Guild, params: dict) -> str:
    new_name = params.get("name", "")
    if not new_name:
        return "❌ Nome mancante"
    old = guild.name
    await guild.edit(name=new_name)
    return f"✅ Server rinominato da `{old}` a `{new_name}`"


async def set_slowmode(guild: discord.Guild, params: dict) -> str:
    ch_name = params.get("channel", "")
    seconds = int(params.get("seconds", 0))

    ch = discord.utils.get(guild.text_channels, name=ch_name)
    if ch is None:
        return f"❌ Canale `#{ch_name}` non trovato"
    await ch.edit(slowmode_delay=seconds)
    label = f"{seconds}s" if seconds > 0 else "disattivato"
    return f"✅ Slowmode su `#{ch_name}` impostato a {label}"


async def create_category(guild: discord.Guild, params: dict) -> str:
    name = params.get("name", "nuova-categoria")
    cat = await guild.create_category(name)
    return f"✅ Categoria `{cat.name}` creata"


async def move_channel(guild: discord.Guild, params: dict) -> str:
    ch_name = params.get("channel", "")
    cat_name = params.get("category", "")

    ch = discord.utils.get(guild.channels, name=ch_name)
    cat = discord.utils.get(guild.categories, name=cat_name)

    if ch is None:
        return f"❌ Canale `#{ch_name}` non trovato"
    if cat is None:
        return f"❌ Categoria `{cat_name}` non trovata"

    await ch.edit(category=cat)
    return f"✅ Canale `#{ch_name}` spostato in `{cat_name}`"


async def list_channels(guild: discord.Guild, params: dict) -> str:
    lines = ["📋 **Canali del server:**"]
    for cat in guild.categories:
        lines.append(f"\n**{cat.name}**")
        for ch in cat.channels:
            icon = "🔊" if isinstance(ch, discord.VoiceChannel) else "💬"
            lines.append(f"  {icon} #{ch.name}")
    # Canali senza categoria
    uncategorized = [c for c in guild.channels if c.category is None and not isinstance(c, discord.CategoryChannel)]
    if uncategorized:
        lines.append("\n**Senza categoria**")
        for ch in uncategorized:
            icon = "🔊" if isinstance(ch, discord.VoiceChannel) else "💬"
            lines.append(f"  {icon} #{ch.name}")
    return "\n".join(lines)


async def list_roles(guild: discord.Guild, params: dict) -> str:
    roles = [r for r in reversed(guild.roles) if r.name != "@everyone"]
    lines = ["🎭 **Ruoli del server:**"]
    for r in roles:
        color = f"#{r.color.value:06x}" if r.color.value else "nessun colore"
        lines.append(f"  • @{r.name} ({color})")
    return "\n".join(lines)


# Mappa nome azione → funzione
ACTION_MAP: dict[str, Any] = {
    "create_channel": create_channel,
    "delete_channel": delete_channel,
    "rename_channel": rename_channel,
    "set_channel_topic": set_channel_topic,
    "create_role": create_role,
    "delete_role": delete_role,
    "rename_role": rename_role,
    "assign_role": assign_role,
    "remove_role": remove_role,
    "kick_member": kick_member,
    "ban_member": ban_member,
    "unban_member": unban_member,
    "rename_server": rename_server,
    "set_slowmode": set_slowmode,
    "create_category": create_category,
    "move_channel": move_channel,
    "list_channels": list_channels,
    "list_roles": list_roles,
}