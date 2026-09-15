# Hermes Agent v0.21.3 / v2026.9.14 — stable tagged runtime
# v0.21.3 includes upstream gateway-liveness fixes after v0.21.1.
FROM nousresearch/hermes-agent:v2026.9.14

# Work around the upstream s6 gateway supervision SIGTERM loop in Docker.
# Keep gateway as the container foreground process; Coolify/Docker handles container restarts.
ENV HERMES_GATEWAY_NO_SUPERVISE=1

CMD ["gateway", "run"]
