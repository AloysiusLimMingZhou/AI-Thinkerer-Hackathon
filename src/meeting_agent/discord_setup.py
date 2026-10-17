"""Explicit guild registration. Importing this module performs no I/O."""
import asyncio,os,re
from pathlib import Path
from .config import Settings

async def register(settings,*,factory=asyncio.create_subprocess_exec):
    if not re.fullmatch(r'[0-9]{15,22}',settings.discord_guild_id or '') or not settings.discord_bot_token:
        raise ValueError('Set DISCORD_GUILD_ID and DISCORD_BOT_TOKEN')
    allowed={'PATH','PATHEXT','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA'}
    env={k:v for k,v in os.environ.items() if k.upper() in allowed}
    env.update(DISCORD_BOT_TOKEN=settings.discord_bot_token,DISCORD_GUILD_ID=settings.discord_guild_id)
    script=Path(__file__).resolve().parents[2]/'apps/discord-voice/src/register.mjs'
    process=await factory(settings.discord_node_executable,str(script),'--guild',settings.discord_guild_id,env=env)
    if await process.wait():raise RuntimeError('Guild command registration failed')
def main():
    try:asyncio.run(register(Settings.from_env()))
    except (ValueError,RuntimeError,OSError) as error:raise SystemExit(str(error)) from None
if __name__=='__main__':main()
