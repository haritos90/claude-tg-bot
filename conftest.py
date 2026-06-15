"""Pytest config: its mere presence at the repo root puts the root on sys.path,
so tests can `import markup`, `import db`, etc. (the bot's modules are top-level,
not a package)."""
