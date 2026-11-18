import os
import re
import json
import html
import hashlib
import asyncio
from pathlib import Path
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import discord
from discord.ext import commands, tasks

UPDATE_CHANNEL_ID = int(os.getenv("UPDATE_CHANNEL_ID", "0"))
UPDATE_ROLE_ID = int(os.getenv("UPDATE_ROLE_ID", "0"))
CHECK_INTERVAL_SECONDS = 300
REQUIRED_CONFIRMATIONS = 2

# These are the three exact sources requested for Animal Company updates.
META_STORE_URL = "https://www.meta.com/experiences/animal-company/7190422614401072/"
STEAMDB_PATCHNOTES_URL = "https://steamdb.info/app/4551040/patchnotes/"
STEAM_ANNOUNCEMENT_URL = "https://steamcommunity.com/games/4551040/announcements/detail/671759636714487921"

# Also use Steam's public news feed so newly published announcements can be
# detected even though the specific Steam Community URL above is one fixed post.
STEAM_NEWS_API_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=4551040&count=20&maxlength=0"

SOURCES = {
    "Meta Store": META_STORE_URL,
    "SteamDB Patch Notes": STEAMDB_PATCHNOTES_URL,
    "Steam Community Announcement": STEAM_ANNOUNCEMENT_URL,
}

DATA = Path(os.getenv("DATA_DIR", "data"))
DATA.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA / "animal_update_data.json"


class VisibleTextParser(HTMLParser):
    """Extract visible page text while ignoring scripts, styles, and navigation."""
    IGNORED = {"script", "style", "noscript", "svg", "header", "nav", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.IGNORED:
            self.ignored_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.IGNORED and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data):
        if not self.ignored_depth and data.strip():
            self.parts.append(data.strip())


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
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; BentleyboovrAnimalCompanyWatcher/2.0)",
            "Accept": "text/html,application/json,*/*",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        print(f"[ANIMAL] Could not check {url}: {error}")
        return 0, ""


def visible_text(page):
    page = html.unescape(page)
    parser = VisibleTextParser()
    try:
        parser.feed(page)
        text = " ".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", page)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def page_fingerprint(page_text):
    # Ignore tiny page changes that are likely timestamps or rotating UI labels.
    return hashlib.sha256(page_text.encode("utf-8", errors="ignore")).hexdigest()


def extract_versions(text):
    return list(dict.fromkeys(re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", text)))


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
        summary = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()
        version_match = re.search(r"\b\d+\.\d+\.\d+\.\d+\b", title + " " + summary)
        return {
            "id": str(item["gid"]),
            "title": title[:250],
            "summary": (summary[:897] + "...") if len(summary) > 900 else (summary or "A new Animal Company announcement was published."),
            "url": str(item.get("url") or STEAM_ANNOUNCEMENT_URL),
            "version": version_match.group(0) if version_match else None,
            "date": int(item.get("date", 0) or 0),
        }
    except (ValueError, TypeError, AttributeError) as error:
        print(f"[ANIMAL] Steam news feed parse error: {error}")
        return None


class AnimalUpdates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def post_update(self, source, url, summary, title="Animal Company Update", version=None):
        channel = self.bot.get_channel(UPDATE_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(UPDATE_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                print(f"[ANIMAL] Update channel {UPDATE_CHANNEL_ID} could not be found or accessed.")
                return False

        embed = discord.Embed(
            title=("🦍 " + title)[:256],
            description=(summary or "The monitored update page has changed.")[:4000],
            color=discord.Color.orange(),
            url=url,
        )
        embed.add_field(name="📡 Update source", value=source, inline=True)
        if version:
            embed.add_field(name="📦 Version detected", value=f"`{version}`", inline=True)
        embed.add_field(name="🔗 Source page", value=f"[Open {source}]({url})", inline=False)
        embed.set_footer(text="Animal Company Update Watcher • Checks all 3 requested websites")
        content = f"<@&{UPDATE_ROLE_ID}>" if UPDATE_ROLE_ID else None
        allowed = discord.AllowedMentions(roles=bool(UPDATE_ROLE_ID), users=False, everyone=False)
        try:
            await channel.send(content=content, embed=embed, allowed_mentions=allowed)
            print(f"[ANIMAL] Posted an update detected from {source}.")
            return True
        except discord.HTTPException as error:
            print(f"[ANIMAL] Could not post update from {source}: {error}")
            return False

    async def check_website_sources(self):
        state = load_state()
        source_state = state.setdefault("website_sources", {})
        changed = False

        for source, url in SOURCES.items():
            status, page = await asyncio.to_thread(fetch_page, url)
            if status != 200 or not page:
                print(f"[ANIMAL] {source} check did not return a usable page (HTTP {status}).")
                continue

            text = visible_text(page)
            if len(text) < 80:
                print(f"[ANIMAL] {source} returned too little readable text; will retry next check.")
                continue

            fingerprint = page_fingerprint(text)
            previous = source_state.get(source, {}).get("fingerprint")

            # First successful run saves a baseline instead of announcing old content.
            if not previous:
                source_state[source] = {"fingerprint": fingerprint, "pending": None, "confirmations": 0}
                changed = True
                print(f"[ANIMAL] Saved first baseline for {source}.")
                continue

            if fingerprint == previous:
                current = source_state.get(source, {})
                if current.get("pending"):
                    current["pending"] = None
                    current["confirmations"] = 0
                    changed = True
                continue

            current = source_state.setdefault(source, {})
            if current.get("pending") == fingerprint:
                current["confirmations"] = int(current.get("confirmations", 0)) + 1
            else:
                current["pending"] = fingerprint
                current["confirmations"] = 1
            changed = True

            if current["confirmations"] >= REQUIRED_CONFIRMATIONS:
                versions = extract_versions(text)
                version = versions[-1] if versions else None
                summary = text[:1200]
                sent = await self.post_update(
                    source=source,
                    url=url,
                    summary=summary,
                    title=f"New change detected — {source}",
                    version=version,
                )
                if sent:
                    current["fingerprint"] = fingerprint
                    current["pending"] = None
                    current["confirmations"] = 0
                    changed = True

        if changed:
            state["website_sources"] = source_state
            save_state(state)

    async def check_steam_news_feed(self):
        item = await asyncio.to_thread(get_latest_steam_announcement)
        if not item:
            return

        state = load_state()
        last_id = str(state.get("last_steam_news_id") or "")
        pending_id = str(state.get("pending_steam_news_id") or "")
        confirmations = int(state.get("steam_news_confirmations", 0) or 0)

        # On first run, record the current latest post without replaying old news.
        if not last_id:
            state["last_steam_news_id"] = item["id"]
            save_state(state)
            return
        if item["id"] == last_id:
            if pending_id:
                state["pending_steam_news_id"] = None
                state["steam_news_confirmations"] = 0
                save_state(state)
            return

        confirmations = confirmations + 1 if item["id"] == pending_id else 1
        state["pending_steam_news_id"] = item["id"]
        state["steam_news_confirmations"] = confirmations
        save_state(state)

        if confirmations >= REQUIRED_CONFIRMATIONS:
            sent = await self.post_update(
                source="Steam Community — Latest Announcements",
                url=item["url"],
                summary=item["summary"],
                title=item["title"],
                version=item["version"],
            )
            if sent:
                state["last_steam_news_id"] = item["id"]
                state["pending_steam_news_id"] = None
                state["steam_news_confirmations"] = 0
                save_state(state)

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def update_checker(self):
        if not UPDATE_CHANNEL_ID:
            print("[ANIMAL] UPDATE_CHANNEL_ID is not configured.")
            return
        try:
            await self.check_website_sources()
            await self.check_steam_news_feed()
        except Exception as error:
            print(f"[ANIMAL] Update checker error: {error}")

    @update_checker.before_loop
    async def before_update_checker(self):
        await self.bot.wait_until_ready()

    @commands.command(name="checkversion")
    async def checkversion(self, ctx):
        await ctx.send("🔎 Checking the three configured Animal Company update websites...")
        results = []
        for source, url in SOURCES.items():
            status, page = await asyncio.to_thread(fetch_page, url)
            if status == 200 and page:
                text = visible_text(page)
                versions = extract_versions(text)
                results.append(f"✅ **{source}:** reachable" + (f" • Version: `{versions[-1]}`" if versions else " • No version number shown"))
            else:
                results.append(f"⚠️ **{source}:** could not be read (HTTP {status})")
        feed = await asyncio.to_thread(get_latest_steam_announcement)
        results.append("✅ **Steam latest-announcement feed:** reachable" if feed else "⚠️ **Steam latest-announcement feed:** unavailable")
        await ctx.send("\n".join(results))

    @commands.command(name="checkstate")
    async def checkstate(self, ctx):
        state = load_state()
        source_state = state.get("website_sources", {})
        lines = ["📊 **Animal Company Update Watcher**"]
        for source in SOURCES:
            status = "Baseline saved" if source_state.get(source, {}).get("fingerprint") else "Waiting for first successful check"
            lines.append(f"• **{source}:** {status}")
        lines.append(f"• **Steam latest news ID:** `{state.get('last_steam_news_id', 'Not checked yet')}`")
        await ctx.send("\n".join(lines))

    @commands.command(name="testupdate")
    @commands.has_permissions(administrator=True)
    async def testupdate(self, ctx):
        sent = await self.post_update(
            source="Test",
            url=META_STORE_URL,
            summary="This is a test announcement to confirm the Animal Company update channel is configured correctly.",
            title="Test Animal Company Update",
        )
        await ctx.send("✅ Test update announcement sent." if sent else "❌ Could not send the test announcement. Check UPDATE_CHANNEL_ID and bot permissions.")

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
            print("[ANIMAL] Update checker started; monitoring Meta Store, SteamDB, and Steam Community every 5 minutes.")


async def setup(bot):
    await bot.add_cog(AnimalUpdates(bot))
