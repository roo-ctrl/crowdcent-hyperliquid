"""Submit a predictions parquet to the Hyperliquid Ranking challenge.

Usage:
    uv run submit.py                              # predictions/model_1.parquet -> slot 1
    uv run submit.py 2                            # same file -> slot 2
    uv run submit.py 3 predictions/ensemble.parquet   # choose file and slot

Window is 14:00-18:00 UTC daily; outside the window the submission is
queued for the next period automatically. Re-submitting to the same slot
in a period overwrites it.
"""

import sys

from dotenv import load_dotenv
from crowdcent_challenge import ChallengeClient

load_dotenv()

slot = int(sys.argv[1]) if len(sys.argv) > 1 else 1
file_path = sys.argv[2] if len(sys.argv) > 2 else "predictions/model_1.parquet"

client = ChallengeClient(challenge_slug="hyperliquid-ranking")
result = client.submit_predictions(file_path=file_path, slot=slot)
print(result)
