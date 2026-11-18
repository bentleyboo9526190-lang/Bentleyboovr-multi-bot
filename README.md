# Bentleyboovr Multi Bot

A single Python Discord bot with exactly six modules:
1. Purge
2. Giveaways
3. Leveling
4. YouTube Post Watcher
5. Predictor (8-ball + funny predictions)
6. Welcomer

The separate Helper/Zeppelin bot, AI chatbot, ticket bot, Animal Company Update Bot, and Role Giver are not included.

## Blitz deployment
- Runtime: Python 3.12, or deploy with the included Dockerfile.
- Start command: `python bot.py`.
- Add `DISCORD_TOKEN` in Blitz's environment/secrets settings. Never commit the real token to GitHub.
- Set the optional variables below as needed.
- If Blitz supports persistent storage, mount it at `/app/data` (or set `DATA_DIR` to the mounted path). Without persistent storage, JSON data may be lost when the container is replaced.

## Environment variables
- `DISCORD_TOKEN` (required): bot token.
- `WELCOME_CHANNEL_ID`: channel for join/leave messages.
- `POST_CHANNEL_ID`: channel for YouTube upload announcements.
- `YOUTUBE_CHANNEL_ID`: YouTube channel ID beginning with UC.
- `POST_MENTION`: defaults to @everyone; can be a role mention such as <@&ROLE_ID>.
- `LEVEL_ROLE_REWARDS`: optional comma-separated level-to-role IDs, e.g. `1:ROLE_ID,2:ROLE_ID`.
- `DATA_DIR`: defaults to data.

## Discord Developer Portal
Enable **Server Members Intent** and **Message Content Intent**. Invite with the `bot` and `applications.commands` scopes. Grant the permissions needed: View Channels, Send Messages, Read Message History, Embed Links, Manage Messages (purge), and Manage Roles (only if using level role rewards). Put the bot's role above reward roles.

## Commands
### Purge
- `/purge amount` — deletes 1–100 recent messages; requires Manage Messages.

### Giveaways
- `/giveaway prize duration winners required_role` — duration examples: 30m, 2h, 1d; role optional.
- `/endgiveaway message_id` — end early.
- `/reroll message_id` — choose another winner from the original entrants.
- `/giveaways` — list active giveaways.
- Giveaways automatically end at their saved end time.

### Leveling
- XP is awarded from chat, with a 60-second per-user cooldown.
- `/rank`, `/level`, `/xp`, `/leaderboard`
- `/levelset member new_level`, `/addxp member amount` (Manage Server permission).
- Role rewards are optional via LEVEL_ROLE_REWARDS.

### Post watcher
- Checks the YouTube RSS feed every five minutes.
- This initial merged version watches YouTube only. The old Post Watcher source available for review did not include a working TikTok watcher.

### Predictor
- `/8ball question` — random magic 8-ball response.
- `/predict` — separate random funny prediction list.

### Welcomer
- Join and leave notices are sent to WELCOME_CHANNEL_ID.

## Data
Levels, giveaway entries, and seen YouTube video IDs are stored as JSON under DATA_DIR. Use persistent storage to preserve them across restarts/redeploys.
