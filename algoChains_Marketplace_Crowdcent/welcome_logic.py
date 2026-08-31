"""Pure welcome-watcher helpers — no DB, Alpaca, or HTTP.

Used by welcome_watcher.py and unit tests so first-run seed vs welcome-existing
behavior can be proven without credentials.
"""
from __future__ import annotations

SUBSCRIBER_SQL = (
    "SELECT username FROM public.user_subscriptions "
    "WHERE bot_name = %s AND api_key IS NOT NULL AND api_secret IS NOT NULL"
)


def decide_welcome_targets(
    known: set[str],
    current: set[str],
    *,
    first_run: bool,
    welcome_existing: bool = False,
    only_user: str | None = None,
) -> tuple[set[str], str]:
    """Return (usernames to welcome, reason).

    first_run + not welcome_existing → seed only (empty targets).
    welcome_existing → welcome current subscribers (or only_user) without
    clearing known_subscribers.txt.
    """
    if only_user:
        user = only_user.strip()
        if not user:
            return set(), "welcome-existing"
        if welcome_existing or user in current:
            return {user}, "welcome-existing"
        return set(), "welcome-existing"
    if welcome_existing:
        return set(current), "welcome-existing"
    new = current - known
    if first_run:
        return set(), "seed"
    return set(new), "new"
