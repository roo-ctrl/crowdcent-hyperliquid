"""Unit tests for welcome targeting and attributed client_order_ids. No live APIs."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("BOT_NAME", "CrowdCent-Model-Roo")

from sendsignal import (  # noqa: E402
    ALPACA_CLIENT_ORDER_ID_MAX,
    attributed_client_order_id,
    listing_slug,
    send_signal,
)
from welcome_logic import SUBSCRIBER_SQL, decide_welcome_targets  # noqa: E402


class ListingSlugTests(unittest.TestCase):
    def test_crowdcent_listing_slug(self):
        self.assertEqual(listing_slug("CrowdCent-Model-Roo"), "crowdcent-model-roo")

    def test_underscores_become_hyphens(self):
        self.assertEqual(listing_slug("CrowdCent_Hyperliquid_Top40"), "crowdcent-hyperliquid-top40")


class AttributedClientOrderIdTests(unittest.TestCase):
    def test_contains_listing_slug(self):
        cid = attributed_client_order_id("w", "ronaldo", "BTC/USD", bot_name="CrowdCent-Model-Roo")
        self.assertIn("crowdcent-model-roo", cid)
        self.assertTrue(cid.startswith("ac-crowdcent-model-roo-w-"))
        self.assertLessEqual(len(cid), ALPACA_CLIENT_ORDER_ID_MAX)

    def test_long_tail_stays_within_alpaca_limit(self):
        cid = attributed_client_order_id(
            "w",
            "a-very-long-username-that-would-overflow",
            "SUPERLONGCOINUSD",
            bot_name="CrowdCent-Model-Roo",
        )
        self.assertIn("crowdcent-model-roo", cid)
        self.assertLessEqual(len(cid), ALPACA_CLIENT_ORDER_ID_MAX)


class SubscriberSqlTests(unittest.TestCase):
    def test_sql_filters_bot_name_and_credentials(self):
        self.assertIn("user_subscriptions", SUBSCRIBER_SQL)
        self.assertIn("bot_name = %s", SUBSCRIBER_SQL)
        self.assertIn("api_key IS NOT NULL", SUBSCRIBER_SQL)
        self.assertIn("api_secret IS NOT NULL", SUBSCRIBER_SQL)


class DecideWelcomeTargetsTests(unittest.TestCase):
    def test_first_run_seeds_without_welcome(self):
        targets, reason = decide_welcome_targets(set(), {"ronaldo"}, first_run=True)
        self.assertEqual(targets, set())
        self.assertEqual(reason, "seed")

    def test_later_run_welcomes_new_user(self):
        targets, reason = decide_welcome_targets({"alice"}, {"alice", "ronaldo"}, first_run=False)
        self.assertEqual(targets, {"ronaldo"})
        self.assertEqual(reason, "new")

    def test_welcome_existing_does_not_require_new(self):
        targets, reason = decide_welcome_targets(
            {"ronaldo"},
            {"ronaldo"},
            first_run=False,
            welcome_existing=True,
        )
        self.assertEqual(targets, {"ronaldo"})
        self.assertEqual(reason, "welcome-existing")

    def test_welcome_existing_only_user(self):
        targets, reason = decide_welcome_targets(
            {"alice", "ronaldo"},
            {"alice", "ronaldo"},
            first_run=True,
            welcome_existing=True,
            only_user="ronaldo",
        )
        self.assertEqual(targets, {"ronaldo"})
        self.assertEqual(reason, "welcome-existing")


class SendSignalPayloadTests(unittest.TestCase):
    def test_welcome_payload_has_target_and_attributed_id(self):
        cid = attributed_client_order_id("w", "ronaldo", "AAVE/USD")
        with patch.dict(os.environ, {"ALGOCHAINS_API_KEY": ""}):
            result = send_signal(
                "BUY",
                "AAVE/USD",
                1.5,
                client_order_id=cid,
                target_usernames=["ronaldo"],
                dry_run=True,
            )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["target_usernames"], ["ronaldo"])
        self.assertEqual(result["strategy_name"], "CrowdCent-Model-Roo")
        self.assertIn("crowdcent-model-roo", result["client_order_id"])
        self.assertNotIn("welcome-ronaldo", result["client_order_id"])


if __name__ == "__main__":
    unittest.main()
