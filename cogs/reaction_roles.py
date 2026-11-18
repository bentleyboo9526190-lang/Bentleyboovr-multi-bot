import os
import discord
from discord.ext import commands

PANEL_CHANNEL_ID = int(os.getenv("ROLE_PANEL_CHANNEL_ID", "1553144182393147492"))
REACTION_ROLES = {
    "💵": int(os.getenv("ROLE_GIVEAWAY_ID", "1553141137122926733")),
    "🎮": int(os.getenv("ROLE_ADMIN_GAME_ID", "1553142984273305700")),
    "🧑‍🎨": int(os.getenv("ROLE_ARTWORK_ID", "1552906997270188032")),
    "🗓️": int(os.getenv("ROLE_AC_UPDATES_ID", "1547729517395714178")),
    "🎤": int(os.getenv("ROLE_ANNOUNCEMENTS_ID", "1553143463812272249")),
}

class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        if not PANEL_CHANNEL_ID:
            print("[ROLES] ROLE_PANEL_CHANNEL_ID is not set.")
            return
        channel = self.bot.get_channel(PANEL_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            print(f"[ROLES] Role panel channel {PANEL_CHANNEL_ID} not found.")
            return
        try:
            panel = None
            async for message in channel.history(limit=100):
                if message.author.id == self.bot.user.id and message.embeds and message.embeds[0].title == "🎭 Choose Your Roles!":
                    panel = message
                    break
            if panel is None:
                embed = discord.Embed(
                    title="🎭 Choose Your Roles!",
                    description=(
                        "React below to choose your roles!\n\n"
                        "💵 **Giveaway**\n"
                        "🎮 **Admin Game**\n"
                        "🧑‍🎨 **Artwork**\n"
                        "🗓️ **AC Updates**\n"
                        "🎤 **Announcements**\n\n"
                        "React to get a role.\n"
                        "Remove your reaction to remove the role."
                    ), color=discord.Color.blurple()
                )
                embed.set_footer(text="React to get a role • Remove reaction to remove it")
                panel = await channel.send(embed=embed)
                print("[ROLES] Reaction role panel created.")
            for emoji in REACTION_ROLES:
                if not any(str(reaction.emoji) == emoji for reaction in panel.reactions):
                    await panel.add_reaction(emoji)
            print("[ROLES] Reaction role panel is ready.")
        except discord.Forbidden:
            print("[ROLES] Missing View Channel, Read Message History, Send Messages, or Add Reactions permission.")

    async def apply_role(self, payload, add):
        if self.bot.user is None or payload.user_id == self.bot.user.id:
            return
        if payload.channel_id != PANEL_CHANNEL_ID or payload.guild_id is None:
            return
        role_id = REACTION_ROLES.get(str(payload.emoji))
        if not role_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(role_id)
        if role is None:
            print(f"[ROLES] Configured role {role_id} was not found.")
            return
        try:
            member = await guild.fetch_member(payload.user_id)
            if add:
                await member.add_roles(role, reason="Reaction role selected")
                print(f"[ROLES] Added {role.name} to {member}.")
            else:
                await member.remove_roles(role, reason="Reaction role removed")
                print(f"[ROLES] Removed {role.name} from {member}.")
        except discord.Forbidden:
            print(f"[ROLES] Cannot manage {role.name}. Give the bot Manage Roles and move its role above that role.")
        except discord.HTTPException as error:
            print(f"[ROLES] Discord API error: {error}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self.apply_role(payload, True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self.apply_role(payload, False)

async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
