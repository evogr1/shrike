# Operations

## Reading alert cards

Each card is titled `[Shrike] <kind>: <subject>` and ends with a one-line fix.

| Kind | Meaning |
|---|---|
| `auth` | Google or Trello refused the credentials. Follow the fix line. |
| `quota` | Rate limit after retries. Usually clears by the next night. |
| `step_failed` | A step failed for another reason. Check `journalctl -u shrike-nightly -n 100`. |
| `gap` | Days older than 3 days are still missing. Usually follows another alert. |
| `expiry_warning` | A missing day expires from Search Console within 14 days. Run the backfill now. |
| `expired` | A day expired before it was saved. Can't be recovered. Sent once. |
| `truncated` | A day hit the API's 50,000-row cap; long-tail rows are missing. Sent once. |
| `backup_stale` | No successful backup in 48 hours. |
| `unit_failed` | A job crashed, was killed (including at its runtime limit), or had a config error. |

Same condition, same day: one card. If Trello itself fails, the alert goes to the journal and the dead-man ping is skipped, so healthchecks.io emails you.

## Common commands

```bash
systemctl start shrike-setup && journalctl -u shrike-setup -n 40 -o cat   # re-run the setup check
systemctl start shrike-backfill                                       # fill missing days now
systemctl list-timers 'shrike-*'
journalctl -u shrike-nightly -n 100
```

Exit codes: 0 ok, 10 a step failed (already alerted), 3 another job is running (nightly still pings in that case), 2 config error. Codes 0, 10 and 3 count as success for systemd; anything else, including 1 from a crash, fails the unit and triggers `shrike-alert@`.

A config error can't post its own alert, because `shrike-alert@` reads the same broken config. The dead-man check covers that case: the nightly ping stops and healthchecks.io emails you.

Time limits (`TimeoutStartSec=`, since the jobs are oneshot units): backfill 12 h, nightly and setup 2 h. A job killed at its limit fails with result `timeout`, releases the lock and posts a `unit_failed` card.

## Changing the schedule

Edit `[schedule]` or `general.timezone` in `config.toml`, then:

```bash
sudo -u shrike SHRIKE_CONFIG=/etc/shrike/config.toml /opt/shrike/venv/bin/shrike render-units --out /tmp/shrike-units
sudo cp /tmp/shrike-units/*.timer /etc/systemd/system/ && sudo systemctl daemon-reload
```

(or just re-run `install.sh`).

## Restoring from a backup

1. `sudo systemctl stop shrike-nightly.timer`
2. Download the newest `shrike-YYYYMMDDTHHMMZ.sqlite.gz` from the Shared Drive folder.
3. `gunzip -c shrike-....sqlite.gz > /tmp/data.sqlite && sqlite3 /tmp/data.sqlite 'PRAGMA integrity_check'`
4. `sudo install -o shrike -g shrike -m 600 /tmp/data.sqlite /var/lib/shrike/data.sqlite && sudo rm -f /var/lib/shrike/data.sqlite-wal /var/lib/shrike/data.sqlite-shm`
5. `sudo systemctl start shrike-setup shrike-backfill` (the backfill re-pulls anything newer than the backup that Google still has)
6. `sudo systemctl start shrike-nightly.timer`

## Upgrading and rolling back

`git -C /opt/shrike pull && sudo /opt/shrike/deploy/install.sh`. The first job after an upgrade takes a `pre-migrate-<version>.sqlite` snapshot in the data directory before migrating (the 3 newest are kept). To roll back: check out the previous release, re-run `install.sh`, and restore that snapshot as above.

## Keeping an Oracle Always Free VM

Oracle may reclaim an Always Free instance that is idle for 7 days (95th-percentile CPU, network and, on A1 shapes, memory all under 20%). This tool is light, so either upgrade the account to Pay As You Go (Always Free resources stay free and aren't reclaimed for idleness) or run it on the same VM as other daily work, such as Kestrel.
