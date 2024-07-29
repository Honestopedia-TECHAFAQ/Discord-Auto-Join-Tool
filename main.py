import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import time
import logging
import signal

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord_auto_join_bot')

intents = discord.Intents.default()
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

join_queue = asyncio.Queue()
JOIN_RATE_LIMIT = 5
join_times = []

async def rate_limit_handler():
    global join_times
    current_time = time.time()
    join_times = [t for t in join_times if current_time - t < 10]

    if len(join_times) >= JOIN_RATE_LIMIT:
        wait_time = 10 - (current_time - join_times[0])
        logger.info(f'Rate limit reached, waiting for {wait_time:.2f} seconds...')
        await asyncio.sleep(wait_time)

    join_times.append(time.time())

@bot.command()
async def join(ctx, invite_link: str):
    await join_queue.put((ctx, invite_link))
    await ctx.send(f'Queued join request for {invite_link}')
    logger.info(f'Queued join request for {invite_link}')

async def process_join_queue():
    while True:
        ctx, invite_link = await join_queue.get()
        try:
            await rate_limit_handler()
            invite = await bot.fetch_invite(invite_link)
            await bot.accept_invite(invite)
            await ctx.send(f'Successfully joined the server: {invite.guild.name}')
            logger.info(f'Successfully joined the server: {invite.guild.name}')
        except discord.errors.NotFound:
            await ctx.send(f'Invite link not found: {invite_link}')
            logger.error(f'Invite link not found: {invite_link}')
        except discord.errors.Forbidden:
            await ctx.send(f'Bot lacks permission to join: {invite_link}')
            logger.error(f'Bot lacks permission to join: {invite_link}')
        except discord.HTTPException as e:
            retry_after = e.response.headers.get('Retry-After')
            if retry_after:
                retry_after = float(retry_after)
                logger.warning(f'Rate limited, retrying after {retry_after:.2f} seconds...')
                await asyncio.sleep(retry_after)
                join_queue.put_nowait((ctx, invite_link))
            else:
                await ctx.send(f'Failed to join the server: {e}')
                logger.error(f'Failed to join the server: {e}')
        except Exception as e:
            await ctx.send(f'An unexpected error occurred: {e}')
            logger.error(f'An unexpected error occurred: {e}')

        join_queue.task_done()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f'This command is on cooldown. Try again in {error.retry_after:.2f} seconds.')
        logger.warning(f'Command on cooldown: {error}')
    else:
        await ctx.send(f'An error occurred: {error}')
        logger.error(f'Command error: {error}')

async def shutdown(signal, loop):
    logger.info(f'Received exit signal {signal.name}...')
    logger.info('Closing running tasks...')
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    for task in tasks:
        task.cancel()
    
    logger.info(f'Cancelling {len(tasks)} outstanding tasks...')
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info('Shutdown complete.')
    loop.stop()

@bot.event
async def on_ready():
    logger.info(f'{bot.user.name} is now running!')
    bot.loop.create_task(process_join_queue())

loop = asyncio.get_event_loop()
for sig in (signal.SIGINT, signal.SIGTERM):
    loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s, loop)))

bot.run(TOKEN)
