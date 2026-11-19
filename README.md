# Search Kestrel

A free, self-hosted tool that keeps a permanent copy of your Google Search Console data and tells you when something breaks. It's the search counterpart to [Kestrel](https://github.com/evogr1/kestrel).

**This release is Phase 0 (data capture).** It:

- backfills all the Search Console history Google still has (about 16 months), oldest day first, so nothing expires before it's saved,
- pulls each newly final day every night: site totals, pages, and page + query,
- keeps it in SQLite, append-only, with a frozen 28-day baseline per site,
- backs the database up every night to a Google Shared Drive folder (or a local folder),
- posts a Trello card when a login, quota, pull, gap or backup fails, and pings a dead-man check (such as healthchecks.io) so you get an email if the server itself goes quiet.

Phase 1 (opportunity lists, a weekly Trello brief of fixes, fix tracking, and an HTTP API plus MCP tools) comes next. The full design is in [docs/design.md](docs/design.md).

## Cost

$0 with a Google Workspace account (for the Shared Drive) and free Trello and healthchecks.io accounts. Everything uses free official APIs.

## Quick start

On a Linux VM with Python 3.11+ and systemd:

```bash
sudo git clone https://github.com/<you>/search-kestrel /opt/search-kestrel
sudo /opt/search-kestrel/deploy/install.sh        # creates user, venv, templates; then stops
# fill in /etc/search-kestrel/env, config.toml and sa.json (docs/SETUP.md)
sudo /opt/search-kestrel/deploy/install.sh        # runs the setup check, starts the backfill, enables the nightly timer
```

Commands (run as the `sk` user through systemd):

| Command | What it does |
|---|---|
| `systemctl start sk-setup` | Checks config, secrets, Search Console access, Trello, the backup target and the dead-man URL |
| `systemctl start sk-backfill` | Pulls every missing day still available, then backs up |
| `sk-nightly.timer` | Nightly pull, backup, health checks and dead-man ping |

`sk-jobs` exit codes: 0 ok, 10 a step failed (already alerted), 3 another job is running, 2 config error, any other code (including 1, a crash) fails the unit and posts an alert.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
ruff check sk tests
coverage run -m unittest discover -s tests -t . && coverage report
```

Tests use in-memory fakes for Search Console, Drive and Trello, and never touch the network.

## License

MIT
