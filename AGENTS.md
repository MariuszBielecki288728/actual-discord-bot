# Production debugging on the Lenovo

## Scope and deployment boundary

This repository owns the Discord bot source, tests, container image, and releases.
It does **not** own production activation. The Lenovo ThinkCentre M710q is declared
and deployed from `/root/my-nixos-configuration` using its transactional
`nix run .#deploy` workflow.

For project structure, coding conventions, and local test commands, also read
[`.github/instructions/general.instructions.md`](.github/instructions/general.instructions.md).
Those instructions defer to this file for production log access, privacy, and the
deployment boundary.

When diagnosing a production issue, agents may use the read-only SSH commands below
to inspect the deployed bot. Do not run `docker compose up`, `docker restart`,
`systemctl restart`, `nixos-rebuild`, `nix run .#deploy`, or any other command that
changes the Lenovo's state from this repository. Prepare and test a source fix here;
release it; then hand the deployment request to the NixOS configuration repository.

## Production access

The production host and bot container are:

```text
SSH host:       admin@think-centre.home
SSH identity:   /root/.ssh/mini_pc_provision_ed25519
systemd unit:   mini-pc-discord-bot.service
container:      mini-pc-actual-actual-discord-bot-1
```

Use key-only, non-interactive SSH with a connection timeout. The `admin` account has
the narrowly required passwordless sudo access for operational inspection:

```bash
ssh -i /root/.ssh/mini_pc_provision_ed25519 \
  -o BatchMode=yes -o ConnectTimeout=15 \
  admin@think-centre.home \
  'sudo systemctl status --no-pager mini-pc-discord-bot'
```

Never print, copy, modify, or commit the private identity, runtime environment files,
Docker environment variables, Discord tokens, Actual credentials, backups, or user
financial data. Receipt OCR, bank notifications, and exception context in logs can
contain sensitive data: treat command output as private diagnostic material and
redact it before including it in an issue, PR, or chat response.

## Read-only investigation workflow

Start with current state and the deployed immutable image:

```bash
ssh -i /root/.ssh/mini_pc_provision_ed25519 \
  -o BatchMode=yes -o ConnectTimeout=15 \
  admin@think-centre.home \
  'sudo docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"'
```

Inspect the service-launcher events; this unit starts Compose, so it is useful for
restart, image-load, and health-gate failures but does not contain the bot's normal
application output:

```bash
ssh -i /root/.ssh/mini_pc_provision_ed25519 \
  -o BatchMode=yes -o ConnectTimeout=15 \
  admin@think-centre.home \
  'sudo journalctl -u mini-pc-discord-bot --since "6 hours ago" --no-pager -n 200'
```

For bot exceptions and receipt-processing diagnostics, inspect the container logs.
Use a bounded time range and tail; do not follow the stream indefinitely unless the
user explicitly asks for live monitoring:

```bash
ssh -i /root/.ssh/mini_pc_provision_ed25519 \
  -o BatchMode=yes -o ConnectTimeout=15 \
  admin@think-centre.home \
  'sudo docker logs --timestamps --since 6h --tail 300 mini-pc-actual-actual-discord-bot-1'
```

For an initial low-volume error scan, use the same command with a narrow pattern,
then retrieve only the necessary surrounding lines after identifying a timestamp:

```bash
ssh -i /root/.ssh/mini_pc_provision_ed25519 \
  -o BatchMode=yes -o ConnectTimeout=15 \
  admin@think-centre.home \
  'sudo docker logs --timestamps --since 24h --tail 1000 mini-pc-actual-actual-discord-bot-1 2>&1 | grep -Ei "traceback|exception|error|failed" || true'
```

Confirm container health without revealing configuration values:

```bash
ssh -i /root/.ssh/mini_pc_provision_ed25519 \
  -o BatchMode=yes -o ConnectTimeout=15 \
  admin@think-centre.home \
  'sudo docker inspect --format "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}" mini-pc-actual-actual-discord-bot-1'
```

If the expected container is absent, rerun `docker ps --format ...` and use the
reported name. Do not guess a Compose project name or alter production to make the
name match this document.

## Reporting and fixing

Report the deployed image reference, relevant timestamps in Europe/Warsaw, container
health, the exception type and redacted stack frames, and whether the issue reproduces
locally. Do not report raw receipt text, transaction amounts, account names, Discord
message IDs, or secrets.

For a code change, add a focused regression test and run the repository's normal
formatting, lint, and test commands. A release alone does not change the Lenovo. State
clearly in the PR or handoff that deployment must be requested in
`/root/my-nixos-configuration`, where the image digest is pinned and activation is
transactional with health-check rollback.
