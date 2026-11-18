import os, json, random, re, time, logging, asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("multi-bot")
DATA = Path(os.getenv("DATA_DIR", "data"))
DATA.mkdir(exist_ok=True)
def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
def save(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    tmp.replace(path)
def envint(key):
    try: return int(os.getenv(key, "0"))
    except ValueError: return 0

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# PURGE
@bot.tree.command(name="purge", description="Delete recent messages in this channel.")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Deleted {len(deleted)} messages.", ephemeral=True)

@purge.error
async def purge_error(interaction, error):
    message = "You need Manage Messages permission." if isinstance(error, app_commands.MissingPermissions) else "I could not delete those messages. Check my permissions."
    if interaction.response.is_done(): await interaction.followup.send(message, ephemeral=True)
    else: await interaction.response.send_message(message, ephemeral=True)

# PREDICTOR - intentionally separate answer pools
EIGHT_BALL = ["It is certain.", "Without a doubt.", "Yes, definitely.", "You can count on it.", "Signs point to yes.", "Most likely.", "Ask again later.", "Cannot predict that now.", "Don't count on it.", "My sources say no.", "Very doubtful.", "Absolutely not."]
FUNNY = ["A pigeon with a tiny briefcase will bring you important news.", "You will become famous for something you did by accident.", "A snack will solve a problem that looked impossible.", "Your next side quest involves finding a missing charger.", "An NPC will give you life advice, then walk into a wall.", "You will say one more game and lose track of time.", "A mysterious notification will appear at the worst moment.", "Your future contains an unreasonable amount of cheese.", "You will win an argument against a microwave.", "A tiny inconvenience will become your villain origin story."]
@bot.tree.command(name="8ball", description="Ask the magic 8-ball a question.")
async def eightball(interaction: discord.Interaction, question: str):
    await interaction.response.send_message(f"🎱 **{discord.utils.escape_markdown(question)}**\n{random.choice(EIGHT_BALL)}")
@bot.tree.command(name="predict", description="Get a funny random prediction.")
async def predict(interaction: discord.Interaction):
    await interaction.response.send_message("🔮 " + random.choice(FUNNY))

# LEVELING
LEVEL_FILE = DATA / "levels.json"
levels = load(LEVEL_FILE, {})
xp_cooldowns = {}
level_lock = asyncio.Lock()
def need(level): return 100 + level * 50
def member_data(guild_id, user_id):
    return levels.setdefault(str(guild_id), {}).setdefault(str(user_id), {"xp": 0, "level": 0})
def rewards():
    result = {}
    for pair in os.getenv("LEVEL_ROLE_REWARDS", "").split(","):
        if ":" in pair:
            try:
                a, b = pair.split(":", 1); result[int(a)] = int(b)
            except ValueError: pass
    return result
async def give_level_role(member, level):
    role_id = rewards().get(level)
    role = member.guild.get_role(role_id) if role_id else None
    if role and role not in member.roles:
        try: await member.add_roles(role, reason=f"Reached level {level}")
        except discord.Forbidden: log.warning("Cannot assign configured level role.")
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    key = (message.guild.id, message.author.id)
    now = time.monotonic()
    if now - xp_cooldowns.get(key, 0) >= 60:
        xp_cooldowns[key] = now
        async with level_lock:
            data = member_data(message.guild.id, message.author.id)
            data["xp"] += random.randint(15, 25)
            old = int(data["level"])
            while data["xp"] >= need(int(data["level"])):
                data["xp"] -= need(int(data["level"]))
                data["level"] += 1
            save(LEVEL_FILE, levels)
            if data["level"] > old:
                await message.channel.send(f"🎉 {message.author.mention} reached **level {data['level']}**!")
                await give_level_role(message.author, int(data["level"]))
    await bot.process_commands(message)
def admin_check(): return app_commands.checks.has_permissions(manage_guild=True)
@bot.tree.command(name="rank", description="Show a member's rank.")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    who = member or interaction.user
    d = member_data(interaction.guild.id, who.id)
    lv = int(d["level"])
    embed = discord.Embed(title=f"{who.display_name}'s Rank", color=discord.Color.blurple())
    embed.add_field(name="Level", value=str(lv))
    embed.add_field(name="XP", value=f"{d['xp']} / {need(lv)}")
    await interaction.response.send_message(embed=embed)
@bot.tree.command(name="level", description="Show a member's level.")
async def level(interaction: discord.Interaction, member: discord.Member = None):
    who = member or interaction.user
    d = member_data(interaction.guild.id, who.id)
    await interaction.response.send_message(f"{who.mention} is level **{d['level']}**.")
@bot.tree.command(name="xp", description="Show a member's XP.")
async def xp(interaction: discord.Interaction, member: discord.Member = None):
    who = member or interaction.user
    d = member_data(interaction.guild.id, who.id)
    await interaction.response.send_message(f"{who.mention} has **{d['xp']} / {need(int(d['level']))} XP**.")
@bot.tree.command(name="leaderboard", description="Show the top 10 members.")
async def leaderboard(interaction: discord.Interaction):
    rows = sorted(levels.get(str(interaction.guild.id), {}).items(), key=lambda x: (int(x[1]["level"]), int(x[1]["xp"])), reverse=True)[:10]
    lines = []
    for i, (uid, d) in enumerate(rows, 1):
        m = interaction.guild.get_member(int(uid))
        lines.append(f"**{i}.** {m.display_name if m else 'Former member'} — Level {d['level']} ({d['xp']} XP)")
    await interaction.response.send_message("\n".join(lines) if lines else "No XP recorded yet.")
@bot.tree.command(name="levelset", description="Set a member's level (Manage Server required).")
@admin_check()
async def levelset(interaction: discord.Interaction, member: discord.Member, new_level: app_commands.Range[int, 0, 500]):
    d = member_data(interaction.guild.id, member.id); d.update(level=new_level, xp=0); save(LEVEL_FILE, levels)
    await interaction.response.send_message(f"Set {member.mention} to level {new_level}.")
@bot.tree.command(name="addxp", description="Add XP to a member (Manage Server required).")
@admin_check()
async def addxp(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 100000]):
    d = member_data(interaction.guild.id, member.id); d["xp"] += amount
    while d["xp"] >= need(int(d["level"])):
        d["xp"] -= need(int(d["level"])); d["level"] += 1
    save(LEVEL_FILE, levels)
    await interaction.response.send_message(f"Added {amount} XP to {member.mention}. Level: {d['level']}.")

# GIVEAWAYS - entries and active giveaways are saved to JSON
GIVEAWAY_FILE = DATA / "giveaways.json"
giveaways = load(GIVEAWAY_FILE, {})
giveaway_lock = asyncio.Lock()
def save_giveaways(): save(GIVEAWAY_FILE, giveaways)
def duration_seconds(value):
    match = re.fullmatch(r"(\d+)([smhd])", value.lower().strip())
    if not match: raise ValueError("Use a duration like 30m, 2h, or 1d.")
    n, unit = int(match.group(1)), match.group(2)
    seconds = n * {"s":1, "m":60, "h":3600, "d":86400}[unit]
    if seconds < 60 or seconds > 30*86400: raise ValueError("Duration must be 1 minute to 30 days.")
    return seconds
class GiveawayView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Enter Giveaway", style=discord.ButtonStyle.success, emoji="🎉", custom_id="multi_giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with giveaway_lock:
            item = giveaways.get(str(interaction.message.id))
            if not item or item["ended"]:
                await interaction.response.send_message("This giveaway has ended.", ephemeral=True); return
            role_id = int(item.get("required_role", 0))
            if role_id and not any(r.id == role_id for r in getattr(interaction.user, "roles", [])):
                await interaction.response.send_message("You do not have the required role.", ephemeral=True); return
            entries = item.setdefault("entrants", [])
            if interaction.user.id in entries:
                entries.remove(interaction.user.id); answer = "Your entry was removed."
            else:
                entries.append(interaction.user.id); answer = "You are entered. Good luck!"
            save_giveaways()
        await interaction.response.send_message(answer, ephemeral=True)
async def end_giveaway(gid, reroll=False):
    item = giveaways.get(str(gid))
    if not item: return "Giveaway not found."
    channel = bot.get_channel(int(item["channel_id"]))
    entrants = list(dict.fromkeys(item.get("entrants", [])))
    count = min(int(item["winners"]), len(entrants))
    chosen = random.sample(entrants, count) if count else []
    item["ended"] = True; save_giveaways()
    if channel:
        try:
            msg = await channel.fetch_message(int(item["message_id"]))
            await msg.edit(view=None)
        except (discord.NotFound, discord.Forbidden): pass
        if chosen:
            await channel.send(f"🎉 {'Reroll' if reroll else 'Giveaway ended'}! **{item['prize']}** — " + ", ".join(f"<@{u}>" for u in chosen))
        elif not reroll:
            await channel.send(f"Giveaway for **{item['prize']}** ended with no entries.")
    return "Giveaway finished."
@bot.tree.command(name="giveaway", description="Start a giveaway. Durations: 30m, 2h, 1d.")
@admin_check()
async def giveaway(interaction: discord.Interaction, prize: str, duration: str, winners: app_commands.Range[int, 1, 20] = 1, required_role: discord.Role = None):
    try: seconds = duration_seconds(duration)
    except ValueError as e:
        await interaction.response.send_message(str(e), ephemeral=True); return
    end = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).timestamp()
    embed = discord.Embed(title="🎉 GIVEAWAY 🎉", description=f"**Prize:** {prize}\n**Winners:** {winners}\n**Ends:** <t:{int(end)}:R>\n\nClick below to enter!", color=discord.Color.gold())
    if required_role: embed.add_field(name="Required role", value=required_role.mention)
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    giveaways[str(msg.id)] = {"message_id":msg.id,"channel_id":interaction.channel_id,"guild_id":interaction.guild_id,"prize":prize,"winners":winners,"required_role":required_role.id if required_role else 0,"end_at":end,"entrants":[],"ended":False}
    save_giveaways(); await msg.edit(view=GiveawayView())
@bot.tree.command(name="endgiveaway", description="End a giveaway early using its message ID.")
@admin_check()
async def endgiveaway(interaction: discord.Interaction, message_id: str):
    await interaction.response.send_message(await end_giveaway(message_id), ephemeral=True)
@bot.tree.command(name="reroll", description="Pick a new winner from an ended giveaway.")
@admin_check()
async def reroll(interaction: discord.Interaction, message_id: str):
    item = giveaways.get(str(message_id))
    if not item or not item["ended"]:
        await interaction.response.send_message("Giveaway not found or not ended.", ephemeral=True); return
    entrants = item.get("entrants", [])
    if not entrants:
        await interaction.response.send_message("There were no entrants.", ephemeral=True); return
    winner = random.choice(entrants); channel = bot.get_channel(int(item["channel_id"]))
    if channel: await channel.send(f"🎉 Reroll winner for **{item['prize']}**: <@{winner}>!")
    await interaction.response.send_message("Rerolled.", ephemeral=True)
@bot.tree.command(name="giveaways", description="List active giveaways.")
async def giveaways_command(interaction: discord.Interaction):
    active = [f"• {g['prize']} — message ID {gid}" for gid,g in giveaways.items() if int(g.get("guild_id",0)) == interaction.guild_id and not g["ended"]]
    await interaction.response.send_message("\n".join(active) if active else "No active giveaways.", ephemeral=True)

# POST WATCHER - YouTube RSS feed
YOUTUBE_ID = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
POST_CHANNEL = envint("POST_CHANNEL_ID")
POST_MENTION = os.getenv("POST_MENTION", "@everyone")
SEEN_FILE = DATA / "seen_videos.json"
seen = set(load(SEEN_FILE, []))
@tasks.loop(minutes=5)
async def youtube_check():
    if not YOUTUBE_ID or not POST_CHANNEL: return
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + YOUTUBE_ID
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status != 200: return
                xml = await response.text()
        channel = bot.get_channel(POST_CHANNEL)
        if not channel: return
        entries = re.findall(r"<entry>(.*?)</entry>", xml, re.S)
        for entry in reversed(entries):
            vid = re.search(r"<yt:videoId>(.*?)</yt:videoId>", entry)
            title = re.search(r"<title>(.*?)</title>", entry, re.S)
            if not vid or vid.group(1) in seen: continue
            video_id = vid.group(1)
            url_match = re.search(r'<link rel="alternate" href="([^"]+)"', entry)
            video_url = url_match.group(1) if url_match else "https://www.youtube.com/watch?v=" + video_id
            video_title = title.group(1) if title else "New video"
            await channel.send(f"{POST_MENTION} Bentleyboovr has posted! Go watch it! 🚨🚨🚨 🔥🔥🔥\n**{video_title}**\n{video_url}")
            seen.add(video_id); save(SEEN_FILE, sorted(seen))
    except Exception: log.exception("YouTube watcher error")
@youtube_check.before_loop
async def before_youtube(): await bot.wait_until_ready()

# WELCOMER
WELCOME_CHANNEL = envint("WELCOME_CHANNEL_ID")
@bot.event
async def on_member_join(member):
    channel = member.guild.get_channel(WELCOME_CHANNEL)
    if channel: await channel.send(f"👋 Welcome to **{member.guild.name}**, {member.mention}! Enjoy your stay.")
@bot.event
async def on_member_remove(member):
    channel = member.guild.get_channel(WELCOME_CHANNEL)
    if channel: await channel.send(f"👋 **{discord.utils.escape_markdown(member.display_name)}** left the server.")

# STARTUP
@bot.event
async def on_ready():
    if not getattr(bot, "_commands_synced", False):
        try:
            synced = await bot.tree.sync()
            log.info("Synced %s slash commands", len(synced))
            bot._commands_synced = True
        except Exception: log.exception("Could not sync slash commands")
    bot.add_view(GiveawayView())
    if not youtube_check.is_running(): youtube_check.start()
    log.info("Online as %s", bot.user)
token = os.getenv("DISCORD_TOKEN")
if not token: raise RuntimeError("DISCORD_TOKEN is missing. Add it in Blitz environment variables.")
bot.run(token)
