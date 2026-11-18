import os
import re
import json
import html
import asyncio
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import discord
from discord.ext import commands, tasks

UPDATE_CHANNEL_ID = int(os.getenv("UPDATE_CHANNEL_ID", "0"))
UPDATE_ROLE_ID = int(os.getenv("UPDATE_ROLE_ID", "0"))
KNOWN_GOOD_VERSION = "1.91.1.3570"
REQUIRED_CONFIRMATIONS = 2

META_STORE_URL = "https://www.meta.com/experiences/7190422614401072/"
STEAMDB_PATCHNOTES_URL = "https://steamdb.info/app/4551040/patchnotes/"
STEAM_ANNOUNCEMENT_URL = "https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/1848664643356749"
STEAM_NEWS_API_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=4551040&count=10&maxlength=0"
VRDB_URL = "https://vrdb.app/game/animal-company/7190422614401072"
QUEST_STORE_DB_URL = "https://queststoredb.com/game/animal-company-7190422614401072/"

DATA = Path(os.getenv("DATA_DIR", "data"))
DATA.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA / "animal_update_data.json"

def load_state():
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)

def fetch_page(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; BentleyboovrUpdateBot/1.0)"})
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        print(f"[ANIMAL] Fetch error for {url}: {error}")
        return 0, ""

def version_tuple(version):
    return tuple(int(part) for part in version.split("."))

def extract_versions(text):
    return list(dict.fromkeys(re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", text)))

def get_meta_artwork():
    status, page = fetch_page(META_STORE_URL)
    if status != 200:
        return None
    page = html.unescape(page)
    for pattern in (r'https://[^"\']+oculuscdn\.com[^"\']+', r'https://scontent[^"\']+'):
        match = re.search(pattern, page)
        if match:
            return match.group(0).replace("\\u0026", "&").replace("\\/", "/")
    return None

def get_meta_version():
    status, page = fetch_page(META_STORE_URL)
    if status != 200:
        return None
    patterns = (
        r'"version"\s*:\s*"(\d+\.\d+\.\d+\.\d+)"',
        r'"latestVersion"\s*:\s*"(\d+\.\d+\.\d+\.\d+)"',
        r'"latest_version"\s*:\s*"(\d+\.\d+\.\d+\.\d+)"',
        r'"versionName"\s*:\s*"(\d+\.\d+\.\d+\.\d+)"',
    )
    for pattern in patterns:
        match = re.search(pattern, page, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def get_page_version(url, source):
    status, page = fetch_page(url)
    if status != 200:
        return None
    versions = extract_versions(page)
    return max(versions, key=version_tuple) if versions else None

def get_best_version():
    meta = get_meta_version()
    vrdb = get_page_version(VRDB_URL, "VRDB")
    quest = get_page_version(QUEST_STORE_DB_URL, "Quest Store DB")
    if meta and version_tuple(meta) >= version_tuple(KNOWN_GOOD_VERSION):
        return meta, "Meta Store"
    candidates = [(v, name) for v, name in ((vrdb, "VRDB"), (quest, "Quest Store DB")) if v and version_tuple(v) >= version_tuple(KNOWN_GOOD_VERSION)]
    return max(candidates, key=lambda item: version_tuple(item[0])) if candidates else (KNOWN_GOOD_VERSION, "Known Good")

def get_latest_steam_announcement():
    status, body = fetch_page(STEAM_NEWS_API_URL)
    if status != 200:
        return None
    try:
        items = json.loads(body).get("appnews", {}).get("newsitems", [])
        valid = [item for item in items if isinstance(item, dict) and item.get("gid")]
        if not valid:
            return None
        item = max(valid, key=lambda entry: int(entry.get("date", 0) or 0))
        title = html.unescape(str(item.get("title", "New Animal Company announcement")))
        raw = html.unescape(str(item.get("contents", "")))
        summary = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"\[/?[a-zA-Z*]+(?:=[^\]]*)?\]", " ", raw))).strip()
        version_match = re.search(r"\b\d+\.\d+\.\d+\.\d+\b", title + " " + summary)
        return {"id": str(item["gid"]), "title": title[:250], "summary": (summary[:897] + "...") if len(summary) > 900 else (summary or "A new Animal Company announcement was published."), "url": str(item.get("url") or STEAM_ANNOUNCEMENT_URL), "version": version_match.group(0) if version_match else None}
    except (ValueError, TypeError, AttributeError) as error:
        print(f"[ANIMAL] Steam feed parse error: {error}")
        return None

class AnimalUpdates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def send_steam_announcement(self, item):
        channel = self.bot.get_channel(UPDATE_CHANNEL_ID)
        if channel is None:
            print(f"[ANIMAL] Update channel {UPDATE_CHANNEL_ID} not found.")
            return False
        embed = discord.Embed(title=("🦍 Animal Company — " + item["title"])[:256], description=item["summary"][:4000], color=discord.Color.orange(), url=item["url"])
        embed.add_field(name="📡 Detected source", value="Steam Community announcements", inline=True)
        embed.add_field(name="📦 Version", value=f'`{item["version"]}`' if item["version"] else "Not listed — new announcement detected by post ID.", inline=True)
        embed.add_field(name="🔗 Monitor pages", value=f"[Meta Store]({META_STORE_URL}) • [SteamDB patch notes]({STEAMDB_PATCHNOTES_URL}) • [Steam announcement]({STEAM_ANNOUNCEMENT_URL})", inline=False)
        embed.set_footer(text="Animal Company Update Watcher")
        content = f"<@&{UPDATE_ROLE_ID}>" if UPDATE_ROLE_ID else None
        allowed = discord.AllowedMentions(roles=bool(UPDATE_ROLE_ID), users=False, everyone=False)
        try:
            await channel.send(content=content, embed=embed, allowed_mentions=allowed)
            return True
        except discord.HTTPException as error:
            print(f"[ANIMAL] Could not post Steam announcement: {error}")
            return False

    async def send_version_update(self, old_version, new_version, source, test=False):
        channel = self.bot.get_channel(UPDATE_CHANNEL_ID)
        if channel is None:
            return False
        artwork = await asyncio.to_thread(get_meta_artwork)
        embed = discord.Embed(title="🦍 Animal Company", description="🧪 **TEST — New Animal Company Update!**" if test else "📦 **New Animal Company Update!**", color=discord.Color.orange())
        embed.add_field(name="⬅️ Previous Version", value=f'`{old_version}`', inline=True)
        embed.add_field(name="📦 New Version", value=f'`{new_version}`', inline=True)
        embed.add_field(name="🔢 Version Code", value=f'`{new_version.split(".")[-1]}`', inline=True)
        embed.add_field(name="📡 Source", value=f"`{source}`", inline=True)
        embed.add_field(name="🔗 Meta Store", value=f"[Open Animal Company page]({META_STORE_URL})", inline=True)
        if artwork:
            embed.set_image(url=artwork)
        embed.set_footer(text=f"Detected from {source}")
        content = f"<@&{UPDATE_ROLE_ID}>" if UPDATE_ROLE_ID else None
        allowed = discord.AllowedMentions(roles=bool(UPDATE_ROLE_ID), users=False, everyone=False)
        try:
            await channel.send(content=content, embed=embed, allowed_mentions=allowed)
            return True
        except discord.HTTPException as error:
            print(f"[ANIMAL] Could not post version update: {error}")
            return False

    @tasks.loop(seconds=20)
    async def update_checker(self):
        if not UPDATE_CHANNEL_ID:
            return
        try:
            state = load_state()
            # Steam announcements are monitored independently of version strings.
            item = await asyncio.to_thread(get_latest_steam_announcement)
            if item:
                last_id = str(state.get("last_steam_news_id") or "")
                pending_id = str(state.get("pending_steam_news_id") or "")
                confirmations = int(state.get("steam_news_confirmations", 0) or 0)
                if not last_id:
                    state.update(last_steam_news_id=item["id"], pending_steam_news_id=None, steam_news_confirmations=0)
                    save_state(state)
                elif item["id"] == last_id:
                    if pending_id:
                        state.update(pending_steam_news_id=None, steam_news_confirmations=0)
                        save_state(state)
                else:
                    confirmations = confirmations + 1 if item["id"] == pending_id else 1
                    state.update(pending_steam_news_id=item["id"], steam_news_confirmations=confirmations)
                    save_state(state)
                    if confirmations >= REQUIRED_CONFIRMATIONS and await self.send_steam_announcement(item):
                        state.update(last_steam_news_id=item["id"], pending_steam_news_id=None, steam_news_confirmations=0)
                        save_state(state)

            version, source = await asyncio.to_thread(get_best_version)
            state = load_state()
            saved = state.get("current_version")
            pending = state.get("pending_version")
            confirmations = int(state.get("confirmations", 0) or 0)
            if not saved:
                state.update(current_version=version, pending_version=None, confirmations=0)
                save_state(state)
                return
            if version == saved or version_tuple(version) < version_tuple(saved):
                if pending:
                    state.update(pending_version=None, confirmations=0)
                    save_state(state)
                return
            confirmations = confirmations + 1 if pending == version else 1
            state.update(pending_version=version, confirmations=confirmations)
            save_state(state)
            if confirmations >= REQUIRED_CONFIRMATIONS and await self.send_version_update(saved, version, source):
                state.update(current_version=version, pending_version=None, confirmations=0)
                save_state(state)
        except Exception as error:
            print(f"[ANIMAL] Update checker error: {error}")

    @update_checker.before_loop
    async def before_update_checker(self):
        await self.bot.wait_until_ready()

    @commands.command(name="checkversion")
    async def checkversion(self, ctx):
        await ctx.send("🔎 Checking Animal Company version...")
        try:
            version, source = await asyncio.to_thread(get_best_version)
            artwork = await asyncio.to_thread(get_meta_artwork)
            embed = discord.Embed(title="🦍 Animal Company", description="🔎 **Animal Company Version Check**", color=discord.Color.orange())
            embed.add_field(name="📦 Version", value=f"`{version}`", inline=False)
            embed.add_field(name="🔢 Version Code", value=f"`{version.split('.')[-1]}`", inline=True)
            embed.add_field(name="📡 Source", value=f"`{source}`", inline=True)
            embed.add_field(name="🔗 Meta Store", value=f"[Open Animal Company page]({META_STORE_URL})", inline=False)
            if artwork:
                embed.set_image(url=artwork)
            embed.set_footer(text=f"Detected from {source}")
            await ctx.send(embed=embed)
        except Exception as error:
            await ctx.send(f"❌ Version check failed: `{error}`")

    @commands.command(name="checkstate")
    async def checkstate(self, ctx):
        state = load_state()
        await ctx.send(
            "📊 **Update Checker State**\n"
            f"📦 Current: `{state.get('current_version', 'None')}`\n"
            f"⏳ Pending: `{state.get('pending_version', 'None')}`\n"
            f"🔢 Confirmations: `{state.get('confirmations', 0)}/{REQUIRED_CONFIRMATIONS}`"
        )

    @commands.command(name="testupdate")
    @commands.has_permissions(administrator=True)
    async def testupdate(self, ctx):
        sent = await self.send_version_update(KNOWN_GOOD_VERSION, "1.91.2.9999", "TEST", test=True)
        await ctx.send("✅ Test update announcement sent." if sent else "❌ Update channel not found.")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need administrator permissions to use that command.")
        elif not isinstance(error, commands.CommandNotFound):
            print(f"[ANIMAL] Command error: {error}")

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.update_checker.is_running():
            self.update_checker.start()
            print("[ANIMAL] Update checker started.")

async def setup(bot):
    await bot.add_cog(AnimalUpdates(bot))
