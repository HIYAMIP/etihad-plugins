import discord

main_color = 12559471
error_color = 6113881

def flighterrorembed(msg):
    return discord.Embed(
        title="<:Warning:1375535050397061211> Error",
        description=msg,
        color=error_color
    )

def flightsuccessembed(msg):
    return discord.Embed(
        title="<:Tick:1375535083351572530> Success",
        description=msg,
        color=main_color
    )

def flightstepembed(msg):
    embed = discord.Embed(
        title="Creating a flight",
        description=msg,
        color=main_color
    )
    embed.set_footer(text="Reply with 'Cancel' to cancel flight creation.")
    return embed
