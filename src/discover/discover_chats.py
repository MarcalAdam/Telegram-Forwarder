from telethon import TelegramClient
from src import config

SEARCH_TERM = "Mack"  

client = TelegramClient(config.TG_SESSION_NAME, config.TG_API_ID, config.TG_API_HASH)

async def main():
    await client.start()
    async for dialog in client.iter_dialogs():
        if SEARCH_TERM.lower() in dialog.name.lower():
            print(f"Nome: {dialog.name} | ID: {dialog.id}")

with client:
    client.loop.run_until_complete(main())
