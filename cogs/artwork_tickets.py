import os
import asyncio
import discord
from discord.ext import commands

PANEL_CHANNEL_ID = int(os.getenv("ARTWORK_PANEL_CHANNEL_ID", "1552900451731505222"))
OWNER_ID = int(os.getenv("TICKET_OWNER_ID", "1365367440778989578"))
CATEGORY_NAME = "Artwork Requests"
TOPIC_PREFIX = "artwork-owner:"

def ticket_owner(channel):
    topic = channel.topic or ""
    if not topic.startswith(TOPIC_PREFIX):
        return None
    try:
        return int(topic.split("|", 1)[0].replace(TOPIC_PREFIX, "", 1))
    except ValueError:
        return None

def is_ticket(channel):
    return isinstance(channel, discord.TextChannel) and ticket_owner(channel) is not None

class CloseArtworkTicket(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="artwork:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        owner_id = ticket_owner(channel) if channel else None
        if owner_id is None:
            await interaction.response.send_message("❌ This is not an artwork ticket.", ephemeral=True)
            return
        if interaction.user.id not in (owner_id, OWNER_ID) and not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Only the ticket owner or server staff can close this ticket.", ephemeral=True)
            return
        await interaction.response.send_message("🔒 This artwork request will close in 5 seconds.")
        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Artwork ticket closed by {interaction.user}")
        except discord.HTTPException:
            pass

class ArtworkPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Artwork Request", emoji="🎨", style=discord.ButtonStyle.primary, custom_id="artwork:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild, user = interaction.guild, interaction.user
        if guild is None:
            await interaction.response.send_message("Use this button in a server.", ephemeral=True)
            return
        existing = next((c for c in guild.text_channels if ticket_owner(c) == user.id), None)
        if existing:
            await interaction.response.send_message(f"❌ You already have an open artwork request: {existing.mention}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        owner = guild.get_member(OWNER_ID)
        if owner is None:
            try:
                owner = await guild.fetch_member(OWNER_ID)
            except discord.HTTPException:
                owner = None
        if owner is None:
            await interaction.followup.send("❌ The configured ticket owner is not in this server. Check TICKET_OWNER_ID.", ephemeral=True)
            return
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if category is None:
            category = await guild.create_category(CATEGORY_NAME, reason="Artwork request tickets")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
            owner: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True, manage_channels=True, manage_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True, manage_channels=True, manage_messages=True),
        }
        channel = await guild.create_text_channel(
            name=f"artwork-{user.id}", category=category, overwrites=overwrites,
            topic=f"{TOPIC_PREFIX}{user.id}|type:artwork",
            reason=f"Artwork request from {user}"
        )
        embed = discord.Embed(
            title="🎨 Artwork Request",
            description=(
                f"Welcome {user.mention}! 🎨\n\n"
                "Please send the following:\n\n"
                "**1. 🖼️ Avatar Picture**\nGive a picture of the avatar you want artwork for.\n\n"
                "**2. 🔗 YouTube / TikTok**\nGive your YouTube channel link or TikTok link if you have one.\n\n"
                "**3. ⏳ Be Patient**\nBentleyboovr will come answer it soon.\n\n"
                "Once you have sent everything, please wait for a response."
            ), color=discord.Color.blurple()
        )
        embed.set_footer(text="🎨 Artwork Request")
        await channel.send(f"{user.mention} <@{OWNER_ID}>", embed=embed, view=CloseArtworkTicket())
        await interaction.followup.send(f"🎨 Your artwork request has been created!\n{channel.mention}", ephemeral=True)

class ArtworkTickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(ArtworkPanel())
        bot.add_view(CloseArtworkTicket())

    @commands.Cog.listener()
    async def on_ready(self):
        if not PANEL_CHANNEL_ID:
            print("[TICKETS] ARTWORK_PANEL_CHANNEL_ID is not set.")
            return
        channel = self.bot.get_channel(PANEL_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            print(f"[TICKETS] Artwork panel channel {PANEL_CHANNEL_ID} not found.")
            return
        try:
            async for message in channel.history(limit=100):
                if message.author.id == self.bot.user.id and message.embeds and message.embeds[0].title == "🎨 ARTWORK REQUESTS":
                    await message.edit(view=ArtworkPanel())
                    print("[TICKETS] Existing artwork panel restored.")
                    return
            embed = discord.Embed(
                title="🎨 ARTWORK REQUESTS",
                description=(
                    "**Want artwork made for your avatar?** 🎨\n\n"
                    "Click the button below to create a private artwork request.\n\n"
                    "🖼️ **Send a picture of your avatar**\n"
                    "🔗 **Send your YouTube or TikTok link** if you have one\n"
                    "⏳ **Wait patiently for Bentleyboovr to respond**\n\n"
                    "🔒 Your request is private and can only be seen by you, Bentleyboovr, and the bot."
                ), color=discord.Color.blurple()
            )
            embed.set_footer(text="🎨 Artwork Requests")
            await channel.send(embed=embed, view=ArtworkPanel())
            print("[TICKETS] Artwork panel created.")
        except discord.Forbidden:
            print("[TICKETS] Missing permission to read history or post in artwork panel channel.")

async def setup(bot):
    await bot.add_cog(ArtworkTickets(bot))
