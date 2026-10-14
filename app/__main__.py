"""Entrypoint for `python -m app`; runs `app.bot.main()` under asyncio."""
import asyncio

from app.bot import main

if __name__ == "__main__":
    asyncio.run(main())
