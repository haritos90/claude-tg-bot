"""Entrypoint: ``python -m app`` (replaces ``python bot.py``, #302).

Keeps the bootstrap logic in ``app.bot.main()``; this module only runs it under
asyncio. The systemd unit (``deploy/tg-bot.service``) invokes this.
"""
import asyncio

from app.bot import main

if __name__ == "__main__":
    asyncio.run(main())
