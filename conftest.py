"""Pytest config: its presence at the repo root (together with ``pythonpath = ["."]``
in pyproject.toml) puts the repo root on sys.path, so tests import the bot's modules
from the ``app`` package — e.g. ``from app.telegram import markup``, ``from app.storage
import db`` (#302: the previously flat top-level modules were grouped into ``app``)."""
