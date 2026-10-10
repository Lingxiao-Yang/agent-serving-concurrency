FROM python:3.12-slim

WORKDIR /workspace
COPY pyproject.toml README.md LICENSE THIRD_PARTY.md ./
COPY src ./src
COPY workloads ./workloads
COPY configs ./configs
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
CMD ["agentcc", "agent-service", "--config", "configs/cpu_smoke.yaml", "--host", "0.0.0.0"]
