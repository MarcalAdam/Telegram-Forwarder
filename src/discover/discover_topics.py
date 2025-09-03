# src/discover/discover_topics.py
from telethon import TelegramClient
from telethon.tl.functions.channels import GetForumTopicsRequest
from telethon.tl.types import Channel
from src import config

client = TelegramClient(config.TG_SESSION_NAME, config.TG_API_ID, config.TG_API_HASH)

async def main():
    await client.start()

    if not config.SOURCE_CHAT:
        print("Defina SOURCE_CHAT no .env com o ID do supergrupo (ex: -100123...) ou @username.")
        return

    # 1) Resolver o entity (aceita int -100..., ou '@nome')
    try:
        entity = await client.get_entity(config.SOURCE_CHAT)
    except Exception as e:
        print(f"Não consegui resolver SOURCE_CHAT ({config.SOURCE_CHAT}). "
              f"Tente abrir o chat no app para ele entrar nos 'Diálogos', "
              f"ou use @username. Erro: {e}")
        return

    # 2) Conferir se é Channel e se tem forum habilitado
    if not isinstance(entity, Channel):
        print(f"O entity resolvido não é um Channel. Tipo: {type(entity).__name__}")
        return

    flags = f"(broadcast={entity.broadcast}, megagroup={entity.megagroup}, forum={getattr(entity, 'forum', False)})"
    print(f"Resolved: {entity.title} | id={entity.id} | {flags}")

    if not getattr(entity, "forum", False):
        print("Este chat NÃO tem 'forum/tópicos' habilitado. "
              "Provavelmente a comunidade agrega VÁRIOS CHATS separados. "
              "Use o discover_chats para encontrar o subchat específico e pegue o chat_id dele.")
        return

    # 3) Listar tópicos
    try:
        res = await client(GetForumTopicsRequest(
            channel=entity,          # pode passar o entity direto
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=200
        ))
    except Exception as e:
        print("Erro ao listar tópicos:", e)
        return

    topics = getattr(res, "topics", []) or []
    if not topics:
        print("Nenhum tópico retornado (forum vazio?).")
        return

    print(f"Tópicos de: {entity.title}")
    for t in topics:
        print(f"- topic_id={t.id} | title={t.title}")

with client:
    client.loop.run_until_complete(main())
