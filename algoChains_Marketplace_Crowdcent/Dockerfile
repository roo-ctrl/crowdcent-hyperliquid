# algoChains Marketplace CrowdCent bot — scheduler.py runs pipeline.py every N days.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    OUT_DIR=/predictions \
    STATE_DIR=/state

# dependency layer (cached until pyproject/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# code layer
COPY pipeline.py modeling.py allocate.py sendsignal.py scheduler.py ./

VOLUME ["/data", "/predictions", "/state"]
# ENTRYPOINT (not CMD) so `docker compose run crowdcent --dry-run` appends args
# to scheduler.py instead of replacing the command.
ENTRYPOINT ["python", "-u", "scheduler.py"]
