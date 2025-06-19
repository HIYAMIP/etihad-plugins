import os
import discord
import asyncio
import aiohttp
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import re

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))
REQUIRED_ROLE_ID = int(os.getenv('REQUIRED_ROLE_ID'))
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
WEBHOOK_MESSAGE_ID = os.getenv('WEBHOOK_MESSAGE_ID')
LOGGING_CHANNEL_ID = int(os.getenv('LOGGING_CHANNEL_ID'))
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv('ANNOUNCEMENT_CHANNEL_ID'))

from embeds import (
    flighterrorembed,
    flightsuccessembed,
    flightstepembed,
)

class FlightScheduler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_webhook.start()

    def cog_unload(self):
        self.update_webhook.cancel()

    @tasks.loop(minutes=5)
    async def update_webhook(self):
        async with aiohttp.ClientSession() as sess:
            headers = {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}
            r = await sess.get(f"https://discord.com/api/v10/guilds/{GUILD_ID}/scheduled-events", headers=headers)
            events = await r.json()
            upcoming = sorted(
                [e for e in events if datetime.fromisoformat(e['scheduled_start_time'][:-1]) > datetime.utcnow()],
                key=lambda e: e['scheduled_start_time']
            )
            if not upcoming:
                embed = {
                    "title": "Upcoming Flights",
                    "description": "No flights scheduled.",
                    "color": 0xE5E1DE,
                    "footer": {"text": "Updates every 5 min"}
                }
            else:
                embed = {
                    "title": "Upcoming Flights",
                    "fields": [{"name": e["name"], "value": e.get("description", "")} for e in upcoming[:2]],
                    "color": 0xE5E1DE,
                    "footer": {"text": "Updates every 5 min"}
                }

            await sess.patch(
                f"{WEBHOOK_URL}/messages/{WEBHOOK_MESSAGE_ID}",
                json={"embeds": [embed]},
                headers={"Content-Type": "application/json"}
            )

            ch = self.bot.get_channel(LOGGING_CHANNEL_ID)
            if ch:
                await ch.send("Updated webhook.")

    async def ask(self, ctx, prompt):
        if isinstance(prompt, discord.Embed):
            await ctx.send(embed=prompt)
        else:
            await ctx.send(prompt)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60)
            if msg.content.lower() == 'cancel':
                await ctx.send(embed=flighterrorembed("Flight creation cancelled."))
                raise asyncio.CancelledError
            return msg.content
        except asyncio.TimeoutError:
            await ctx.send(embed=flighterrorembed("Timed out. Please try again later."))
            raise

    @commands.command()
    async def createflight(self, ctx):
        if REQUIRED_ROLE_ID not in [r.id for r in ctx.author.roles]:
            await ctx.reply("You don't have permission to use this command.")
            return

        try:
            flight_number = await self.ask(ctx, flightstepembed("Enter the flight number (e.g., EA301)."))
            flight_time_raw = await self.ask(ctx, flightstepembed("Enter the flight time as a Unix timestamp (e.g., 1727780400)."))
            flight_time = int(flight_time_raw)
            start = datetime.utcfromtimestamp(flight_time)
            end = start + timedelta(minutes=45)

            aircraft_type = await self.ask(ctx, flightstepembed("Enter the aircraft type (e.g., A320neo)."))
            departure = await self.ask(ctx, flightstepembed("Enter the departure airport (e.g., Edinburgh)."))
            arrival = await self.ask(ctx, flightstepembed("Enter the arrival airport (e.g., Madeira)."))
            roblox_link = await self.ask(ctx, flightstepembed("Enter the Roblox game link.."))

            payload = {
                "name": f"{flight_number} | {departure} - {arrival}",
                "description": (f'<:Tail:1375059430269517885> **Etihad Airways** cordially invites you to attend Flight **{flight_number}**, operating from **{departure}** to **{arrival}** aboard a **{aircraft_type}**.\n\n'
                                f'<:Star:1375535064141795460> All passengers are requested to review the flight itinerary in `#itinerary` prior to departure to ensure a smooth and professional operation. '),
                "scheduled_start_time": start.isoformat(),
                "scheduled_end_time": end.isoformat(),
                "privacy_level": 2,
                "entity_type": 3,
                "entity_metadata": {"location": roblox_link}
            }

            async with aiohttp.ClientSession() as sess:
                r = await sess.post(
                    f"https://discord.com/api/v10/guilds/{GUILD_ID}/scheduled-events",
                    json=payload,
                    headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}
                )
                if r.status == 201:
                    await ctx.send(embed=flightsuccessembed("✅ Flight created successfully!"))
                    log = self.bot.get_channel(LOGGING_CHANNEL_ID)
                    if log:
                        await log.send(embed=discord.Embed(
                            title="Logging",
                            color=0xE5E1DE
                        ).add_field(name="Create Flight", value=f"{ctx.author} created flight {flight_number}"))
                else:
                    await ctx.send(embed=flighterrorembed(f"Failed to create flight (status {r.status})."))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await ctx.send(embed=flighterrorembed(f"❌ Error: {e}"))

    @commands.command()
    async def startflight(self, ctx, link=None):
        if REQUIRED_ROLE_ID not in [r.id for r in ctx.author.roles]:
            await ctx.reply("You don't have permission to use this command.")
            return
        if not link:
            await ctx.reply(embed=flighterrorembed("Provide an event link!"))
            return

        event_id = link.rstrip('/').split('/')[-1]

        async with aiohttp.ClientSession() as sess:
            r = await sess.get(f"https://discord.com/api/v10/guilds/{GUILD_ID}/scheduled-events/{event_id}",
                            headers={"Authorization": f"Bot {TOKEN}"})
            if r.status != 200:
                await ctx.reply(embed=flighterrorembed("Invalid link or event!"))
                return
            ev = await r.json()

        roblox_link = ev.get('entity_metadata', {}).get('location', '')
        description = ev.get('description', '').strip()

        pattern = (
            r"<:Tail:\d+>\s+\*\*Etihad Airways\*\* cordially invites you to attend Flight\s+\*\*(.+?)\*\*, "
            r"operating from\s+\*\*(.+?)\*\* to\s+\*\*(.+?)\*\* aboard"
        )

        match = re.search(pattern, description, re.DOTALL)
        if not match:
            return await ctx.reply(embed=flighterrorembed("Failed to parse event description for flight info."))

        flight_number = match.group(1).strip()
        departure = match.group(2).strip()
        arrival = match.group(3).strip()

        now = datetime.now(timezone.utc)
        start_time = datetime.fromisoformat(ev['scheduled_start_time'].replace('Z', '+00:00'))

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

        chan = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if not chan:
            await ctx.reply(embed=flighterrorembed("Announcement channel not found."))
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

        await ctx.reply(embed=flightsuccessembed(f"Flight '{ev['name']}' started."))
        log = self.bot.get_channel(LOGGING_CHANNEL_ID)
        if log:
            await log.send(embed=discord.Embed(title="Logging", color=0xE5E1DE).add_field(name="Start Flight", value=f"{ctx.author} started {ev['name']}"))


    @commands.command()
    async def cancelflight(self, ctx, flight_id=None):
        if REQUIRED_ROLE_ID not in [r.id for r in ctx.author.roles]:
            await ctx.reply("You don't have permission to use this command.")
            return
        if not flight_id:
            await ctx.reply(embed=flighterrorembed("Provide a flight ID!"))
            return
        async with aiohttp.ClientSession() as sess:
            r = await sess.delete(f"https://discord.com/api/v10/guilds/{GUILD_ID}/scheduled-events/{flight_id}",
                                 headers={"Authorization": f"Bot {TOKEN}"})
            if r.status == 204:
                await ctx.reply(embed=flightsuccessembed(f"Flight {flight_id} canceled."))
                log = self.bot.get_channel(LOGGING_CHANNEL_ID)
                if log:
                    await log.send(embed=discord.Embed(title="Logging", color=0xE5E1DE).add_field(name="Cancel Flight", value=f"{ctx.author} canceled flight {flight_id}"))
            else:
                await ctx.reply(embed=flighterrorembed(f"Failed (status {r.status})"))


async def setup(bot):
    await bot.add_cog(FlightScheduler(bot))
