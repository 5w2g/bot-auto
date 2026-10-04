import asyncio
import base64
import json
import os
import urllib.error
import urllib.request

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError(
        "DISCORD_TOKEN manquant. Cree un fichier .env avec DISCORD_TOKEN=ton_token"
    )

DEFAULT_KEYWORD = "/éphémère"
CONFIG_FILE = "config.json"
GITHUB_REPO = os.getenv("GH_REPO")
GITHUB_TOKEN = os.getenv("GH_TOKEN")
GITHUB_BRANCH = os.getenv("GH_BRANCH", "main")
WORKFLOW_FILE = os.getenv("WORKFLOW_FILE", "bot.yml")


def load_configs() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}


def commit_config_to_github() -> bool:
    if not (GITHUB_REPO and GITHUB_TOKEN):
        print("[config] GH_REPO ou GH_TOKEN manquant, skip commit")
        return False
    try:
        owner, repo_name = GITHUB_REPO.split("/", 1)
    except ValueError:
        print("[config] GH_REPO invalide, skip commit")
        return False

    url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{CONFIG_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "discord-bot",
    }

    sha = None
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            sha = data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"[config] GET error: {e}")
            return False

    new_content = json.dumps(configs, indent=2, ensure_ascii=False)
    payload = {
        "message": "bot: update config",
        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="PUT",
        headers={**headers, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[config] commit OK ({resp.status})")
            return True
    except Exception as e:
        print(f"[config] PUT error: {e}")
        return False


def pull_config_from_github() -> bool:
    """Recupere la derniere config depuis GitHub et la charge en memoire."""
    if not (GITHUB_REPO and GITHUB_TOKEN):
        return False
    try:
        owner, repo_name = GITHUB_REPO.split("/", 1)
    except ValueError:
        return False

    url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{CONFIG_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "discord-bot",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            content = base64.b64decode(data["content"]).decode("utf-8")
            remote_configs = json.loads(content)
            configs.clear()
            configs.update(remote_configs)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(configs, f, indent=2, ensure_ascii=False)
            print(
                f"[config] pull OK ({len(configs)} serveur(s))"
            )
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("[config] pas de config distante, conserve le local")
        else:
            print(f"[config] pull GET error: {e}")
    except Exception as e:
        print(f"[config] pull error: {e}")
    return False


def save_configs() -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(configs, f, indent=2, ensure_ascii=False)
    commit_config_to_github()


configs: dict = load_configs()
print(f"[config] {len(configs)} serveur(s) charges au demarrage")


def get_config(guild_id: int) -> dict:
    gid = str(guild_id)
    if gid not in configs:
        configs[gid] = {
            "channel_id": None,
            "role_id": None,
            "keyword": DEFAULT_KEYWORD,
            "welcome_enabled": True,
            "check_guild_tag": True,
        }
    cfg = configs[gid]
    cfg.setdefault("channel_id", None)
    cfg.setdefault("role_id", None)
    cfg.setdefault("keyword", DEFAULT_KEYWORD)
    cfg.setdefault("welcome_enabled", True)
    cfg.setdefault("check_guild_tag", True)
    return cfg


def has_keyword_in_status(member: discord.Member, keyword: str) -> bool:
    kw = keyword.lower()
    activities = member.activities or ()
    for activity in activities:
        is_custom = (
            isinstance(activity, discord.CustomActivity)
            or getattr(activity, "type", None) == discord.ActivityType.custom
        )
        if not is_custom:
            continue
        name = getattr(activity, "name", None) or ""
        if name and kw in name.lower():
            return True
    return False


def has_server_guild_tag(member: discord.Member) -> bool:
    """Verifie si le membre affiche le guild tag du serveur sur son profil."""
    pg = getattr(member, "primary_guild", None)
    if pg is None:
        return False
    if not getattr(pg, "identity_enabled", False):
        return False
    return getattr(pg, "identity_guild_id", None) == member.guild.id


def should_have_role(
    member: discord.Member, keyword: str, check_tag: bool
) -> bool:
    """Le membre doit avoir le role si statut contient le mot-cle OU s'il a le tag du serveur."""
    if has_keyword_in_status(member, keyword):
        return True
    if check_tag and has_server_guild_tag(member):
        return True
    return False


async def apply_role(member: discord.Member) -> None:
    if member.bot:
        return
    config = get_config(member.guild.id)
    role_id = config.get("role_id")
    if not role_id:
        return
    role = member.guild.get_role(role_id)
    if not role:
        return
    keyword = config.get("keyword", DEFAULT_KEYWORD)
    check_tag = config.get("check_guild_tag", True)

    if should_have_role(member, keyword, check_tag):
        reason_parts = []
        if has_keyword_in_status(member, keyword):
            reason_parts.append(f"statut '{keyword}'")
        if check_tag and has_server_guild_tag(member):
            reason_parts.append("guild tag serveur")
        reason = " / ".join(reason_parts) or "auto-role"
        if role not in member.roles:
            try:
                await member.add_roles(role, reason=reason)
                print(
                    f"[{member.guild.name}] {member}: role ajoute "
                    f"({reason}, presence: {member.status})"
                )
            except discord.Forbidden:
                print(
                    f"[{member.guild.name}] {member}: PERMISSION REFUSEE "
                    f"- verifie la hierarchie des roles"
                )
            except discord.HTTPException as e:
                print(f"[{member.guild.name}] {member}: erreur {e}")
        else:
            print(
                f"[{member.guild.name}] {member}: deja le role "
                f"(presence: {member.status})"
            )
    else:
        if role in member.roles:
            try:
                await member.remove_roles(
                    role, reason=f"Plus de statut '{keyword}' ni de guild tag"
                )
                print(
                    f"[{member.guild.name}] {member}: role retire "
                    f"(presence: {member.status})"
                )
            except discord.Forbidden:
                pass


async def initial_scan(guild: discord.Guild) -> tuple[int, int]:
    config = get_config(guild.id)
    role_id = config.get("role_id")
    if not role_id:
        return (0, 0)
    role = guild.get_role(role_id)
    if not role:
        return (0, 0)
    keyword = config.get("keyword", DEFAULT_KEYWORD)
    check_tag = config.get("check_guild_tag", True)
    added = 0
    removed = 0
    for member in guild.members:
        if member.bot:
            continue
        if should_have_role(member, keyword, check_tag):
            if role not in member.roles:
                try:
                    await member.add_roles(role)
                    added += 1
                except discord.Forbidden:
                    pass
        else:
            if role in member.roles:
                try:
                    await member.remove_roles(role)
                    removed += 1
                except discord.Forbidden:
                    pass
    return (added, removed)


intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@tasks.loop(minutes=240)
async def keep_alive() -> None:
    """Declenche un nouveau run du workflow avant le timeout GitHub Actions."""
    if not (GITHUB_REPO and GITHUB_TOKEN):
        keep_alive.stop()
        return
    url = (
        f"https://api.github.com/repos/{GITHUB_REPO}"
        f"/actions/workflows/{WORKFLOW_FILE}/dispatches"
    )
    data = json.dumps({"ref": GITHUB_BRANCH}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "discord-bot",
        },
    )
    for attempt in range(3):
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=15)
            )
            print(f"[keep_alive] Prochain workflow declenche (tentative {attempt+1})")
            return
        except Exception as e:
            print(f"[keep_alive] tentative {attempt+1} echouee: {e}")
            await asyncio.sleep(30)


@keep_alive.before_loop
async def before_keep_alive() -> None:
    await bot.wait_until_ready()


import signal
import sys


def _trigger_next_workflow_sync() -> None:
    """Declenche le prochain workflow de maniere synchrone (pour SIGTERM)."""
    if not (GITHUB_REPO and GITHUB_TOKEN):
        return
    url = (
        f"https://api.github.com/repos/{GITHUB_REPO}"
        f"/actions/workflows/{WORKFLOW_FILE}/dispatches"
    )
    data = json.dumps({"ref": GITHUB_BRANCH}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "discord-bot",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print("[sigterm] Prochain workflow declenche")
    except Exception as e:
        print(f"[sigterm] Erreur: {e}")


def _signal_handler(signum, frame):
    print(f"[sigterm] Recu, declenchement du prochain workflow")
    _trigger_next_workflow_sync()
    sys.exit(0)


if os.name != "nt":
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


@bot.event
async def on_ready():
    print(f"Connecte en tant que {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} commande(s) slash synchronisee(s)")
    except Exception as e:
        print(f"Erreur de sync: {e}")

    pull_config_from_github()

    await bot.change_presence(
        activity=discord.CustomActivity(name="/éphémère")
    )

    if not keep_alive.is_running():
        keep_alive.start()

    for guild in bot.guilds:
        try:
            if not guild.chunked:
                await guild.chunk()
        except Exception as e:
            print(f"[{guild.name}] Chunk impossible: {e}")
        added, removed = await initial_scan(guild)
        print(f"[{guild.name}] Scan initial: +{added} -{removed}")
    print("Bot pret.")


@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    config = get_config(member.guild.id)
    if not config.get("welcome_enabled", True):
        return

    channel = None
    channel_id = config.get("channel_id")
    if channel_id:
        channel = member.guild.get_channel(channel_id)
    if not channel:
        channel = member.guild.system_channel
    if not channel:
        for ch in member.guild.text_channels:
            if ch.permissions_for(member.guild.me).send_messages:
                channel = ch
                break
    if channel:
        try:
            await channel.send(f"{member.mention} a pose son cul ici")
        except discord.Forbidden:
            pass


@bot.event
async def on_presence_update(
    before: discord.Member, after: discord.Member
):
    if after.bot:
        return
    await apply_role(after)


@bot.event
async def on_member_update(
    before: discord.Member, after: discord.Member
):
    """Detecte les changements de guild tag / profil."""
    if after.bot:
        return
    if before.primary_guild != after.primary_guild:
        await apply_role(after)


setup_group = app_commands.Group(
    name="setup", description="Configurer le bot d'auto-role"
)


@setup_group.command(
    name="channel", description="Definir le salon de bienvenue"
)
@app_commands.describe(channel="Le salon ou envoyer le message de bienvenue")
@app_commands.checks.has_permissions(administrator=True)
async def setup_channel(
    interaction: discord.Interaction, channel: discord.TextChannel
):
    config = get_config(interaction.guild.id)
    config["channel_id"] = channel.id
    save_configs()
    await interaction.response.send_message(
        f"Salon de bienvenue defini sur {channel.mention}", ephemeral=True
    )


@setup_group.command(
    name="role", description="Definir le role a attribuer automatiquement"
)
@app_commands.describe(role="Le role a donner aux membres avec le bon statut")
@app_commands.checks.has_permissions(administrator=True)
async def setup_role(
    interaction: discord.Interaction, role: discord.Role
):
    config = get_config(interaction.guild.id)
    config["role_id"] = role.id
    save_configs()
    await interaction.response.send_message(
        f"Role defini sur {role.mention}", ephemeral=True
    )


@setup_group.command(
    name="keyword",
    description="Definir le mot-cle a detecter dans le statut custom",
)
@app_commands.describe(
    keyword="Le mot-cle (par defaut: /ephemere). Detecte meme avec du texte avant."
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_keyword(interaction: discord.Interaction, keyword: str):
    config = get_config(interaction.guild.id)
    config["keyword"] = keyword
    save_configs()
    await interaction.response.send_message(
        f"Mot-cle defini sur `{keyword}`", ephemeral=True
    )


@setup_group.command(
    name="welcome", description="Activer ou desactiver le message de bienvenue"
)
@app_commands.describe(active="Activer ou desactiver le message de bienvenue")
@app_commands.checks.has_permissions(administrator=True)
async def setup_welcome(
    interaction: discord.Interaction, active: bool
):
    config = get_config(interaction.guild.id)
    config["welcome_enabled"] = active
    save_configs()
    state = "active" if active else "desactive"
    await interaction.response.send_message(
        f"Message de bienvenue {state}.", ephemeral=True
    )


@setup_group.command(
    name="view", description="Voir la configuration actuelle du bot"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_view(interaction: discord.Interaction):
    config = get_config(interaction.guild.id)
    role_id = config.get("role_id")
    channel_id = config.get("channel_id")
    keyword = config.get("keyword", DEFAULT_KEYWORD)
    welcome = config.get("welcome_enabled", True)
    check_tag = config.get("check_guild_tag", True)

    role = interaction.guild.get_role(role_id) if role_id else None
    channel = interaction.guild.get_channel(channel_id) if channel_id else None

    lines = [
        f"**Salon de bienvenue**: {channel.mention if channel else '`non configure`'}",
        f"**Role**: {role.mention if role else '`non configure`'}",
        f"**Mot-cle statut**: `{keyword}`",
        f"**Verifie guild tag**: {'oui' if check_tag else 'non'}",
        f"**Bienvenue**: {'activee' if welcome else 'desactivee'}",
    ]
    await interaction.response.send_message(
        "\n".join(lines), ephemeral=True
    )


@setup_group.command(
    name="reset", description="Reinitialiser la configuration du serveur"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_reset(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    configs[gid] = {
        "channel_id": None,
        "role_id": None,
        "keyword": DEFAULT_KEYWORD,
        "welcome_enabled": True,
        "check_guild_tag": True,
    }
    save_configs()
    await interaction.response.send_message(
        "Configuration reinitialisee.", ephemeral=True
    )


@setup_group.command(
    name="pull",
    description="Forcer le telechargement de la config depuis GitHub",
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_pull(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    ok = pull_config_from_github()
    if ok:
        await interaction.followup.send(
            f"Config mise a jour depuis GitHub ({len(configs)} serveur(s)).",
            ephemeral=True,
        )
    else:
        await interaction.followup.send(
            "Pas de config distante (ou erreur). La config locale est conservee.",
            ephemeral=True,
        )


@setup_group.command(
    name="tag",
    description="Activer/desactiver la verification du guild tag du serveur",
)
@app_commands.describe(active="Activer la verification du guild tag")
@app_commands.checks.has_permissions(administrator=True)
async def setup_tag(interaction: discord.Interaction, active: bool):
    config = get_config(interaction.guild.id)
    config["check_guild_tag"] = active
    save_configs()
    state = "activee" if active else "desactivee"
    await interaction.response.send_message(
        f"Verification du guild tag {state}.", ephemeral=True
    )


bot.tree.add_command(setup_group)


@bot.tree.command(
    name="check",
    description="Verifier ce que le bot voit pour un membre (debug)",
)
@app_commands.describe(member="Le membre a verifier (laisse vide pour toi)")
@app_commands.checks.has_permissions(administrator=True)
async def check(
    interaction: discord.Interaction, member: discord.Member = None
):
    target = member or interaction.user
    config = get_config(interaction.guild.id)
    role_id = config.get("role_id")
    keyword = config.get("keyword", DEFAULT_KEYWORD)
    role = interaction.guild.get_role(role_id) if role_id else None
    has_role = role in target.roles if role else False

    activities_text = []
    for activity in target.activities or []:
        is_custom = (
            isinstance(activity, discord.CustomActivity)
            or getattr(activity, "type", None)
            == discord.ActivityType.custom
        )
        activities_text.append(
            f"- `{activity.type}` "
            f"{'(custom)' if is_custom else ''} "
            f"name=`{getattr(activity, 'name', None)}` "
            f"state=`{getattr(activity, 'state', None)}`"
        )

    detection = has_keyword_in_status(target, keyword)
    has_tag = has_server_guild_tag(target)
    check_tag = config.get("check_guild_tag", True)
    should = should_have_role(target, keyword, check_tag)
    pg = getattr(target, "primary_guild", None)
    tag_info = "aucun"
    if pg is not None:
        tag_info = (
            f"`{getattr(pg, 'tag', None)}` "
            f"(serveur: {getattr(pg, 'identity_guild_id', None) == interaction.guild.id}, "
            f"affiche: {getattr(pg, 'identity_enabled', False)})"
        )

    lines = [
        f"**Membre**: {target.mention}",
        f"**Statut**: `{target.status}`",
        f"**Activites** ({len(target.activities or [])}):",
        "\n".join(activities_text) if activities_text else "_aucune_",
        f"**Mot-cle statut**: `{keyword}` (detecte: `{detection}`)",
        f"**Guild tag**: {tag_info}",
        f"**Verif tag activee**: `{check_tag}`",
        f"**Devrait avoir le role**: `{should}`",
        f"**Role config**: {role.mention if role else '`non configure`'}",
        f"**Possede deja le role**: `{has_role}`",
    ]
    await interaction.response.send_message(
        "\n".join(lines), ephemeral=True
    )


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "Permission insuffisante (admin requis)."
    else:
        msg = f"Erreur: {error}"
        print(f"App command error: {error}")
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
    except Exception:
        pass


if __name__ == "__main__":
    bot.run(TOKEN)