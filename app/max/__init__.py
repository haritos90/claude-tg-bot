"""MAX messenger transport behind the same aiogram handler layer.

- `poller` turns MAX updates into synthetic aiogram updates
- `bridge.MaxSession` translates outgoing calls to MAX API
- `bridge.RoutingSession` picks the platform by chat id
- MAX identities live in their own numeric namespace
"""
