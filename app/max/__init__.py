"""MAX (max.ru) messenger transport (#434).

A second messaging platform behind the SAME aiogram handler layer. The package has no
handlers of its own: ``poller`` turns MAX Platform API updates into synthetic aiogram
``Update`` objects and feeds them to the one ``Dispatcher``; ``bridge.MaxSession`` is an
aiogram ``BaseSession`` that translates every outgoing Bot API method for a MAX chat into
MAX API calls; ``bridge.RoutingSession`` picks Telegram or MAX per call by the chat id.
MAX identities live in their own numeric namespace (``ids``), so nothing a Telegram user
owns is reachable from MAX and vice versa.
"""
