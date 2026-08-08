"""Loop compartido por toda la suite: el pool asyncpg global queda atado al
loop donde se crea; reusar UN loop evita 'attached to a different loop'."""
import asyncio

_KOS_LOOP = asyncio.new_event_loop()