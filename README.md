# Bot Discord - Auto-role éphémère fidèle

## Fonctionnalités
- **Bienvenue** : quand quelqu'un rejoint, le bot envoie `@pseudo a posé son cul ici` (sans embed).
- **Auto-rôle** : détecte si un membre en ligne a soit `/éphémère` dans son statut custom, soit le **guild tag du serveur** affiché sur son profil, et lui donne automatiquement le rôle configuré.
- Le rôle est retiré si le membre passe hors ligne ou enlève le mot-clé.
- **Hébergement 24/7** sur GitHub Actions avec auto-restart.

---

## Installation locale (test)

1. Installe Python 3.10+.
2. `pip install -r requirements.txt`
3. Copie `.env.example` → `.env` et colle ton token.
4. Active les Privileged Intents sur https://discord.com/developers/applications :
   - Presence Intent, Server Members Intent, Message Content Intent
6. `python bot.py`

Commandes :
- `/setup channel #salon` - salon de bienvenue
- `/setup role @rôle` - rôle à donner
- `/setup keyword /ephemere` - mot-clé à détecter
- `/setup welcome True/False`
- `/setup tag True/False` - activer/désactiver la vérif du guild tag
- `/setup view` / `/setup reset`
- `/check @user` - debug

---

## Hébergement 24/7 sur GitHub Actions

### 1. Crée le repo
Pousse le dossier du bot sur un nouveau repo GitHub (public ou privé).

### 2. Active les permissions d'écriture
Dans le repo → **Settings → Actions → General → Workflow permissions** :
- ✅ **Read and write permissions**
- ✅ **Allow to create and approve pull requests** (optionnel)

### 3. Ajoute le secret du bot
Dans le repo → **Settings → Secrets and variables → Actions → New repository secret** :
- Name : `DISCORD_TOKEN`
- Value : ton token de bot

### 4. Lance le bot
Va dans l'onglet **Actions** → sélectionne le workflow **Bot** → **Run workflow**.

### Comment ça marche
- Le bot tourne **jusqu'à 5h** par run (limite GitHub Actions).
- Une tâche `keep_alive` déclenche un **nouveau run toutes les ~4h40min** via l'API.
- `concurrency: cancel-in-progress: true` : un seul bot à la fois.
- Un cron toutes les **5h** sert de backup si le bot crashe.
- La config (`config.json`) est **automatiquement commitée** sur le repo à chaque `/setup`.

### Notes
- Le bot a besoin que son rôle soit au-dessus de `/éphémembre fidèle` dans la hiérarchie du serveur.
- Les commits `bot: update config` apparaissent dans l'historique à chaque modif de config.
- Limite GitHub Actions gratuit : ~2000 min/mois (largement suffisant).