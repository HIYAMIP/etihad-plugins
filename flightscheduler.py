from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING

import aiohttp
import discord
from discord.ext import commands, tasks

from core import checks
from core.models import PermissionLevel, getLogger

if TYPE_CHECKING:
    from bot import ModmailBot

logger = getLogger(__name__)


class FlightScheduler(commands.Cog):
    """
    Flight scheduling and event management commands.
    """

    def __init__(self, bot: ModmailBot):
        self.bot: ModmailBot = bot
        # Load config from env or your config management
        self.TOKEN: str = bot.config.get("TOKEN")  # or however your bot config is accessed
        GUILD_ID="1288926604415733854"
        REQUIRED_ROLE_ID="1288926707285495941"
        ANNOUNCEMENT_CHANNEL_ID="1290777608782483640"
        WEBHOOK_URL="https://discord.com/api/webhooks/1290778044948283483/bquY_ka1ndRd7OL7tpZYJUuw5RVQTch0fe_3ddG-uPYTnXOvOZVGZTeY3c9BYAlkuPBD"
        WEBHOOK_MESSAGE_ID="1290778370749104263"
        LOGGING_CHANNEL_ID="1288927464080543806"

        self.update_webhook.start()

    def cog_unload(self) -> None:
        self.update_webhook.cancel()

    @tasks.loop(minutes=5)
    async def update_webhook(self) -> None:
        async with aiohttp.ClientSession() as sess:
            headers = {
                "Authorization": f"Bot {self.TOKEN}",
                "Content-Type": "application/json",
            }
            url = f"https://discord.com/api/v10/guilds/{self.GUILD_ID}/scheduled-events"
            async with sess.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"Failed to fetch scheduled events, status {resp.status}")
                    return
                events = await resp.json()

            upcoming = sorted(
                (
                    e
                    for e in events
                    if datetime.fromisoformat(e["scheduled_start_time"][:-1]) > datetime.utcnow()
                ),
                key=lambda e: e["scheduled_start_time"],
            )

            if not upcoming:
                embed = {
                    "title": "Upcoming Flights",
                    "description": "No flights scheduled.",
                    "color": 0xE5E1DE,
                    "footer": {"text": "Updates every 5 min"},
                }
            else:
                embed = {
                    "title": "Upcoming Flights",
                    "fields": [{"name": e["name"], "value": e.get("description", "")} for e in upcoming[:2]],
                    "color": 0xE5E1DE,
                    "footer": {"text": "Updates every 5 min"},
                }

            patch_url = f"{self.WEBHOOK_URL}/messages/{self.WEBHOOK_MESSAGE_ID}"
            async with sess.patch(patch_url, json={"embeds": [embed]}, headers={"Content-Type": "application/json"}) as resp:
                if resp.status not in (200, 204):
                    logger.warning(f"Failed to update webhook embed, status {resp.status}")

        log_channel = self.bot.get_channel(self.LOGGING_CHANNEL_ID)
        if log_channel:
            await log_channel.send("Updated flight schedule webhook.")

    async def ask(self, ctx: commands.Context, prompt: discord.Embed | str) -> str:
        """Helper method to ask user for input with timeout and cancel support."""
        if isinstance(prompt, discord.Embed):
            await ctx.send(embed=prompt)
        else:
            await ctx.send(prompt)

        def check(m: discord.Message) -> bool:
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=60)
            if msg.content.lower() == "cancel":
                await ctx.send(embed=discord.Embed(title="Flight creation cancelled.", color=0xFF0000))
                raise asyncio.CancelledError()
            return msg.content
        except asyncio.TimeoutError:
            await ctx.send(embed=discord.Embed(title="Timed out. Please try again later.", color=0xFF0000))
            raise

    @commands.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def flight(self, ctx: commands.Context) -> None:
        """Flight scheduling commands."""
        await ctx.send_help(ctx.command)

    @flight.command(name="create")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def flight_create(self, ctx: commands.Context) -> None:
        """Create a new scheduled flight event."""
        try:
            # Check role permission
            if self.REQUIRED_ROLE_ID not in [r.id for r in ctx.author.roles]:
                await ctx.reply("You don't have permission to use this command.")
                return

            flight_number = await self.ask(ctx, discord.Embed(title="Flight Number", description="Enter the flight number (e.g., EA301)."))
            flight_time_raw = await self.ask(ctx, discord.Embed(title="Flight Time", description="Enter the flight time as a Unix timestamp (e.g., 1727780400)."))
            flight_time = int(flight_time_raw)
            start = datetime.utcfromtimestamp(flight_time)
            end = start + timedelta(minutes=45)

            aircraft_type = await self.ask(ctx, discord.Embed(title="Aircraft Type", description="Enter the aircraft type (e.g., A320neo)."))
            departure = await self.ask(ctx, discord.Embed(title="Departure", description="Enter the departure airport (e.g., Edinburgh)."))
            arrival = await self.ask(ctx, discord.Embed(title="Arrival", description="Enter the arrival airport (e.g., Madeira)."))
            roblox_link = await self.ask(ctx, discord.Embed(title="Roblox Link", description="Enter the Roblox game link."))

            payload = {
                "name": f"{flight_number} | {departure} - {arrival}",
                "description": (
                    f'<:Tail:1375059430269517885> **Etihad Airways** cordially invites you to attend Flight **{flight_number}**, '
                    f'operating from **{departure}** to **{arrival}** aboard a **{aircraft_type}**.\n\n'
                    f'<:Star:1375535064141795460> All passengers are requested to review the flight itinerary in `#itinerary` prior to departure to ensure a smooth and professional operation.'
                ),
                "scheduled_start_time": start.isoformat(),
                "scheduled_end_time": end.isoformat(),
                "privacy_level": 2,
                "entity_type": 3,
                "entity_metadata": {"location": roblox_link},
            }

            async with aiohttp.ClientSession() as sess:
                r = await sess.post(
                    f"https://discord.com/api/v10/guilds/{self.GUILD_ID}/scheduled-events",
                    json=payload,
                    headers={"Authorization": f"Bot {self.TOKEN}", "Content-Type": "application/json"},
                )
                if r.status == 201:
                    await ctx.send(embed=discord.Embed(title="✅ Flight created successfully!", color=0x00FF00))
                    log = self.bot.get_channel(self.LOGGING_CHANNEL_ID)
                    if log:
                        await log.send(embed=discord.Embed(title="Logging", color=0xE5E1DE).add_field(name="Create Flight", value=f"{ctx.author} created flight {flight_number}"))
                else:
                    await ctx.send(embed=discord.Embed(title="Failed to create flight", description=f"Status code: {r.status}", color=0xFF0000))

        except asyncio.CancelledError:
            return  # User cancelled
        except Exception as e:
            await ctx.send(embed=discord.Embed(title="Error", description=str(e), color=0xFF0000))

    @flight.command(name="start")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def flight_start(self, ctx: commands.Context, link: Optional[str] = None) -> None:
        """Announce the start of a flight event."""
        if self.REQUIRED_ROLE_ID not in [r.id for r in ctx.author.roles]:
            await ctx.reply("You don't have permission to use this command.")
            return

        if not link:
            await ctx.reply(embed=discord.Embed(title="Error", description="Provide an event link!", color=0xFF0000))
            return

        event_id = link.rstrip("/").split("/")[-1]

        async with aiohttp.ClientSession() as sess:
            r = await sess.get(f"https://discord.com/api/v10/guilds/{self.GUILD_ID}/scheduled-events/{event_id}", headers={"Authorization": f"Bot {self.TOKEN}"})
            if r.status != 200:
                await ctx.reply(embed=discord.Embed(title="Error", description="Invalid link or event!", color=0xFF0000))
                return
            ev = await r.json()

        roblox_link = ev.get("entity_metadata", {}).get("location", "")
        description = ev.get("description", "").strip()

        pattern = (
            r"<:Tail:\d+>\s+\*\*Etihad Airways\*\* cordially invites you to attend Flight\s+\*\*(.+?)\*\*, "
            r"operating from\s+\*\*(.+?)\*\* to\s+\*\*(.+?)\*\* aboard"
        )
        match = re.search(pattern, description, re.DOTALL)
        if not match:
            await ctx.reply(embed=discord.Embed(title="Error", description="Failed to parse event description for flight info.", color=0xFF0000))
            return

        flight_number, departure, arrival = (g.strip() for g in match.groups())

        now = datetime.now(timezone.utc)
        start_time = datetime.fromisoformat(ev["scheduled_start_time"].replace("Z", "+00:00"))

        lock_time = start_time + timedelta(minutes=15)
        minutes_until_lock = max(0, int((lock_time - now).total_seconds() / 60))

        message = (
            f"<:Plane:1379811896106156052> **Check-in Now Open**\n"
            f"-# {departure}\n\n"
            f"<:Dash:1379811908886204567> **-**\n"
            f"> Attention all passengers flying to **{arrival}** on flight **{flight_number}**, check-in is now open and will close in **{minutes_until_lock} minutes**. "
            "If you are in need of any assistance throughout your journey, please reach out to a member of staff! Have a good flight.\n\n"
            f"<:Link:1379811829076856842> {roblox_link}\n\n"
            "|| @everyone @Operations Ping ||"
        )

        chan = self.bot.get_channel(self.ANNOUNCEMENT_CHANNEL_ID)
        if chan is None:
            await ctx.reply(embed=discord.Embed(title="Error", description="Announcement channel not found.", color=0xFF0000))
            return

        msg = await chan.send(message)

        async def send_checkin_closed():
            await asyncio.sleep((lock_time - datetime.now(timezone.utc)).total_seconds())
            try:
                await msg.delete()
            except discord.HTTPException:
                pass
            closed_message = (
                f"<:Lock:1379811903332679830> **Check-in Closed**\n"
                f"-# {departure}\n\n"
                f"<:Dash:1379811908886204567> **-**\n"
                f"> Check-in for flight **{flight_number}** to **{arrival}** has now been closed. If you have missed your flight, please attend the next one!\n\n"
                f"-# <:Tail:1379811826467868804> **ETIHAD OPERATIONS**"
            )
            await chan.send(closed_message)

        asyncio.create_task(send_checkin_closed())

        await ctx.reply(embed=discord.Embed(title="Flight Started", description=f"Flight '{ev['name']}' started.", color=0x00FF00))
        log = self.bot.get_channel(self.LOGGING_CHANNEL_ID)
        if log:
            await log.send(embed=discord.Embed(title="Logging", color=0xE5E1DE).add_field(name="Start Flight", value=f"{ctx.author} started {ev['name']}"))

    @flight.command(name="cancel")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def flight_cancel(self, ctx: commands.Context, flight_id: Optional[str] = None) -> None:
        """Cancel a scheduled flight event by ID."""
        if self.REQUIRED_ROLE_ID not in [r.id for r in ctx.author.roles]:
            await ctx.reply("You don't have permission to use this command.")
            return

        if not flight_id:
            await ctx.reply(embed=discord.Embed(title="Error", description="Provide a flight ID!", color=0xFF0000))
            return

        async with aiohttp.ClientSession() as sess:
            r = await sess.delete(
                f"https://discord.com/api/v10/guilds/{self.GUILD_ID}/scheduled-events/{flight_id}",
                headers={"Authorization": f"Bot {self.TOKEN}"},
            )
            if r.status == 204:
                await ctx.reply(embed=discord.Embed(title="Success", description=f"Flight {flight_id} canceled.", color=0x00FF00))
                log = self.bot.get_channel(self.LOGGING_CHANNEL_ID)
                if log:
                    await log.send(embed=discord.Embed(title="Logging", color=0xE5E1DE).add_field(name="Cancel Flight", value=f"{ctx.author} canceled flight {flight_id}"))
            else:
                await ctx.reply(embed=discord.Embed(title="Error", description=f"Failed (status {r.status})", color=0xFF0000))


async def setup(bot: ModmailBot) -> None:
    await bot.add_cog(FlightScheduler(bot))
