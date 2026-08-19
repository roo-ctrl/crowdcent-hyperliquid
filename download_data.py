"""Pull the latest training + current inference data for the Hyperliquid Ranking challenge."""

from pathlib import Path

from dotenv import load_dotenv
from crowdcent_challenge import ChallengeClient

load_dotenv()

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

client = ChallengeClient(challenge_slug="hyperliquid-ranking")

print("Downloading training data (latest)...")
client.download_training_dataset("latest", str(DATA_DIR / "training_data.parquet"))

# "latest" = most recent release (works any time of day).
# "current" only exists during the open window (14:00-18:00 UTC) and polls otherwise.
print("Downloading inference data (latest release)...")
client.download_inference_data("latest", str(DATA_DIR / "inference_data.parquet"))

print("Done. Files in ./data/")
