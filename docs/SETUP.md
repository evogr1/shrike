# Setup

Takes about 20 minutes. You need: a Linux VM (Oracle Always Free works), a Google Cloud project, a Google Workspace Shared Drive, a Trello board and a free healthchecks.io account.

## 1. Google service account

1. In Google Cloud console, create a project (or reuse one) and enable the **Google Search Console API** and the **Google Drive API**.
2. IAM & Admin → Service Accounts → Create. No roles are needed.
3. Keys → Add key → JSON. Copy the file to the VM:

   ```bash
   sudo install -o shrike -g shrike -m 600 key.json /etc/shrike/sa.json
   ```

   If key creation is blocked with "Service account key creation is disabled", your Workspace org enforces `iam.disableServiceAccountKeyCreation`. Either ask an org admin to make an exception for this project, or create the project under a personal Google account (outside the Workspace org) and use that service account. Invites in steps 2 and 3 work by email either way.

## 2. Search Console access

For each site: Search Console → Settings → Users and permissions → Add user → the service account's email (`...@....iam.gserviceaccount.com`) → **Restricted**. Copy the property string into `config.toml`: `sc-domain:example.com` for a domain property, or the full `https://example.com/` for a URL-prefix property.

## 3. Backup folder

Create a folder in a **Shared Drive** (a plain "My Drive" folder will not work: service accounts have no storage of their own). Share it with the service account as **Content Manager**, not Manager, so it can't permanently delete backups. Copy the folder id from its URL into `backup.gdrive_folder_id`.

**Already have rclone with a Google Drive remote on the server?** You can skip the Shared Drive. Set `backup.target = "local"` (backups go to `/var/lib/shrike/backups`), add your sync user to the `shrike` group (`sudo usermod -aG shrike ubuntu`), edit `deploy/systemd/shrike-drive-sync.service` for your user and Drive folder, then copy and enable it with its timer:

```bash
sudo install -m 644 /opt/shrike/deploy/systemd/shrike-drive-sync.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now shrike-drive-sync.timer
```

It copies the backups to Drive every morning and verifies them with `rclone check`. The setup check still shows "G1 not met" for local mode, because it can't see the rclone copy; check the Drive folder once by hand.

No Workspace and no rclone? Set `backup.target = "local"`. Backups then stay on the VM, which doesn't protect you if the VM is lost (the setup check and alerts say "G1 not met"). Copy `/var/lib/shrike/backups` elsewhere yourself.

## 4. Trello

1. Create a board with a list for alerts (for example "Shrike alerts").
2. Get an API key and token: https://trello.com/power-ups/admin → create a Power-Up → API key → generate a token.
3. Find the list id: open any card in the list, add `.json` to its URL, and copy `idList`.

## 5. Dead-man check

Create a free check at https://healthchecks.io with a **period of 1 day and a grace of 2 hours** (26 h total). Copy its ping URL into `general.dead_man_url`. If the nightly run stops, or Trello alerts can't be delivered, you get an email.

## 6. Fill in config and secrets

`/etc/shrike/env` (owner root, mode 600):

```
SHRIKE_SERVICE_ACCOUNT_FILE=/etc/shrike/sa.json
SHRIKE_TRELLO_KEY=...
SHRIKE_TRELLO_TOKEN=...
```

`/etc/shrike/config.toml`: sites, time zone, `trello.alert_list_id`, `backup.gdrive_folder_id` and `general.dead_man_url`. Keep `general.phase = 0`.

## 7. Run the installer again

```bash
sudo /opt/shrike/deploy/install.sh
```

It renders the timers from your schedule, runs the setup check (every line should say `ok`; warnings are allowed), starts the backfill once, and enables the nightly timer. Follow the backfill with `journalctl -fu shrike-backfill`.
