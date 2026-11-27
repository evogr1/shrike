# Shrike

A free, self-hosted tool that keeps a permanent copy of your Google Search Console data and tells you when something breaks. It's the search counterpart to [Kestrel](https://github.com/evogr1/kestrel).

**It does:**

- keeps a permanent, backed-up copy of your Search Console data (backfill, nightly pull, frozen baseline, alerts),
- posts a weekly Trello brief of fixes: queries you almost rank for, pages with low click-through, and pages losing clicks,
- measures each fix you move to Done against similar untouched pages, in extra clicks per 28 days,
- serves a read-only HTTP API and MCP tools, so you can ask Claude about your traffic.

Phase 0 is capture only; Phase 1 (brief, fix tracking, API, MCP) is turned on with `install.sh --phase 1`. Page audits, Bing data and AI citation tracking are not built yet.

## Cost

$0 with a Google Workspace account (for the Shared Drive) and free Trello and healthchecks.io accounts. Everything uses free official APIs.

## Quick start

On a Linux VM with Python 3.11+ and systemd:

```bash
sudo git clone https://github.com/<you>/shrike /opt/shrike
sudo /opt/shrike/deploy/install.sh        # creates user, venv, templates; then stops
# fill in /etc/shrike/env, config.toml and sa.json (docs/SETUP.md)
sudo /opt/shrike/deploy/install.sh        # runs the setup check, starts the backfill, enables the nightly timer
```

Commands (run as the `shrike` user through systemd):

| Command | What it does |
|---|---|
| `systemctl start shrike-setup` | Checks config, secrets, Search Console access, Trello, the backup target and the dead-man URL |
| `systemctl start shrike-backfill` | Pulls every missing day still available, then backs up |
| `shrike-nightly.timer` | Nightly pull, backup, health checks and dead-man ping |

`shrike` exit codes: 0 ok, 10 a step failed (already alerted), 3 another job is running, 2 config error, any other code (including 1, a crash) fails the unit and posts an alert.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
ruff check shrike tests
coverage run -m unittest discover -s tests -t . && coverage report
```

Tests use in-memory fakes for Search Console, Drive and Trello, and never touch the network.

## License

MIT
