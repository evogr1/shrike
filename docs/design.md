# Shrike: free, self-hosted SEO, GEO and AEO tool

*   **Author:** Harshil Rekhi
*   **Status:** Reviewed (EGM Stages 5-9, 2026-11-19). The round-2 fixes are applied but weren't re-audited. Phase 0 is blocked on Q3.
*   **Date:** 2026-11-19

SEO is search engine optimization. GEO (generative engine optimization) and AEO (answer engine optimization) cover how a site shows up and gets cited in AI answers, such as Google AI Overviews, Copilot, Gemini, Perplexity and ChatGPT.

--------------------------------------------------------------------------------

## Overview

Shrike is a self-hosted tool. It reads search data for the author's two sites, solodac and evogr, and turns it into a short weekly list of fixes.

It follows the shape of Kestrel, the author's free vidIQ replacement for YouTube and Instagram (public repo `evogr1/kestrel`):

*   an HTTP API under `/v1/...`,
*   an MCP connector so Claude can call it,
*   free API keys, with small capped paid calls where needed,
*   a scheduled job,
*   a brief pushed to Trello.

It is a separate project, not a Kestrel module. It will be released free on GitHub, and each self-hoster brings their own keys.

The tool does four things, in this order of priority:

1.  **(Phase 0)** Keeps a permanent copy of Google Search Console data, which Google deletes after 16 months.
2.  **(Phase 1)** Finds fix opportunities in that data, and sends a weekly brief of 5 to 10 items to Trello.
3.  **(Phase 1)** Tracks which fixes shipped, and measures whether each one helped.
4.  **(Phases 2 and 3)** Later adds page audits, Bing data, competitor tracking and AI citation tracking.

### Phases

| Phase | Contents | Starts when |
|---|---|---|
| 0 | Search Console backfill, nightly pull, frozen baseline, off-host backups, run tracking, alerts, dead-man check, setup check | First |
| 1 | Opportunity rules, weekly Trello brief, fix tracking and measurement, HTTP API and 7 MCP tools | After Phase 0 has run cleanly for 7 nights |
| 2 | Single-URL audit, Bing Webmaster data, IndexNow, competitor sitemap and title diffs | Once G2 is met and G3's 8-week average is met |
| 3 | AI citation tracking (Bing CSV import, Gemini grounding, capped paid engines) | After Phase 2, and only once Q5 and Q8 are answered |

In this document, **the core** means Phases 0 and 1.

All 7 HTTP routes are exposed as MCP tools in Phase 1, since they share one route table. The author chose this on 2026-11-19, over the 2 to 3 tools in the [concepts brief](../../concepts_brief.md).

## The Problem

The author manages Search Console fully by hand for both sites. That causes four problems:

*   **History is being lost.** Search Console keeps 16 months of performance data and drops the oldest day every day. Nothing is being saved, so year-over-year comparisons and long-term trends disappear one day at a time.
*   **Opportunities are found only when someone looks.** No routine pass finds three kinds of opportunity: queries a site almost ranks for, pages people see in results but don't click, and pages slowly losing traffic. Finding them by hand takes time, so it happens rarely.
*   **There is no record of what was fixed or whether it helped.** Without a log of changes and a before-and-after comparison, there's no way to tell which kinds of fixes are worth repeating.
*   **AI answers are a blind spot.** Search Console mixes AI Overview traffic into normal web results and doesn't split it out. Copilot, Gemini, Perplexity and ChatGPT citations aren't visible anywhere the author looks today. Only Bing publishes first-party citation data, through a dashboard report with a CSV export and no API.

Paid tools solve parts of this. The OpenSEO connector in the author's setup covers Search Console and AI visibility, but it's credit-billed and keeps no history the author controls.

The proposed solution is a single scheduled job. It:

*   pulls Search Console data into a local database the author owns, with off-host backups,
*   ranks opportunities from that data,
*   pushes them to Trello as fix cards,
*   reads card status back so it can measure each shipped fix against pages nobody touched.

Everything beyond Search Console is added in Phases 2 and 3, gated as shown in the Phases table.

## Goals

*   **G1. Permanent history.**
    *   All available Search Console history (up to 16 months) for both sites is backfilled, oldest day first. From then on, no day of data is lost.
    *   Each night the job pulls every date that has become final since the last run, plus any missing dates. Search Console data becomes final about 2 to 3 days after the day. The tool stores final data only, so Google's late revisions to recent days never reach it.
    *   The database is backed up to a different machine every night.
    *   A restore is tested at least once before Phase 1 ships.
    *   G1 is met only with an off-host backup target. In `local` mode the setup check and every brief header warn that it isn't met.
*   **G2. No manual Search Console work.** The author goes 4 weeks in a row without opening Search Console to find opportunities. The weekly brief and MCP tools cover that need.
*   **G3. A brief that leads to shipped fixes.** Each weekly Trello brief has 5 to 10 ranked items, each with the page, the query, the reason and a suggested fix. At least 3 items ship per week on average over the first 8 weeks.
*   **G4. Measured results.**
    *   For every shipped fix, the tool reports the page's clicks and impressions for the 28 final days after the ship date against the 28 final days before.
    *   It also reports the change for a group of comparable untouched pages over the same period.
    *   Each fix's effect is given in extra clicks per 28 days (defined under Fix measurement), and the effects add up to a running total.
    *   This total replaces the author's original target of "100k visits a month" as the measure of whether the tool works, since the tool can't count visits (see Non-Goals).
*   **G5. Failures are visible.**
    *   While the VM and Trello are reachable, any failed login, expired key, quota error or failed step creates a Trello card within 24 hours.
    *   If the VM is down, the nightly job never runs, or Trello is unreachable, the required dead-man check emails the self-hoster within 26 hours.
*   **G6. $0 core.**
    *   Phases 0 to 2 use only free-tier APIs (Google and Trello).
    *   $0 assumes either an existing Google Workspace account for Shared Drive backups, or another off-host target the self-hoster already has.
    *   Optional paid AI checks (Phase 3) stay off by default. When turned on, a cost ledger enforces a hard monthly cap that the self-hoster sets.
*   **G7. Ready to publish.** Sites, keys and schedules live in config, and the repo holds no secrets or site-specific code. Publishing it on GitHub means writing docs, not rewriting code.

## Non-Goals

*   **Scraping AI chat sites** (chatgpt.com, perplexity.ai, gemini.google.com). It breaks their terms and doesn't belong in a public repo.
*   **Browser automation in the core.** No logged-in browser reading of the Bing dashboard or any other site. The Bing AI Performance report comes in through its CSV export.
*   **A daily feed.** The weekly brief is the only scheduled output. Daily data is collected but not pushed.
*   **`llms.txt` scoring, or audit checks promising FAQ rich results.** No engine has confirmed it uses `llms.txt`, and Google has restricted FAQ rich results since 2023.
*   **A hosted, multi-user service.** Each person runs their own copy.
*   **Merging into Kestrel or depending on it at runtime.** Code may be copied across. The two tools run separately.
*   **Visit counts or analytics.** The tool reports Search Console clicks and impressions, not site visits. Plugging in analytics is a possible later improvement.
*   **Writing or publishing content.** The tool suggests fixes. It doesn't edit the sites.

## Open Questions

*   **Q1. Resolved: tool name.** Shrike (chosen 2026-11-19).
*   **Q2. Resolved: language and stack.** Python 3.11 with pinned libraries. See the Technical Plan, and Alternatives G and H.
*   **Q3. Service-account access.**
    *   Can a Google service account be added as a user on both sites' Search Console properties, whether they're domain or URL-prefix properties?
    *   Does the Workspace org policy `iam.disableServiceAccountKeyCreation` block creating its key? If it does, the fallback is a personal Google Cloud project outside the Workspace org, with the service account invited into the Shared Drive by email.
*   **Q4. Baselines.** What are the current monthly clicks and impressions for solodac and evogr? How many query rows per day does each return? The answers decide whether the API's row limits matter, and replace the size and runtime estimates.
*   **Q5. Gemini grounding terms.** Do they allow storing grounded answers and citations? Is the free grounding quota available without turning on billing? This blocks Phase 3 only.
*   **Q6. Bing Webmaster API history.** How many days of query and page data does it return? This decides whether Bing gets a backfill.
*   **Q7. IndexNow.** Do the sites' CDN or CMS already send IndexNow pings? If so, the tool doesn't need to.
*   **Q8. Paid AI pricing.** What do Perplexity Sonar and OpenAI web search currently charge per call and per search? This sets the default cap. It blocks Phase 3 only.
*   **Q9. Host and exposure.**
    *   Does the author's copy run on the same Oracle Free VM as Kestrel, or a separate one?
    *   Is Kestrel's hop from Cloudflare to the box a `cloudflared` tunnel, or proxied DNS into Caddy or nginx? Check with `systemctl status cloudflared` and `ss -tlnp` on the server. The design defaults to a Cloudflare Tunnel, which is what Kestrel's public README recommends. If the author's Kestrel uses proxied DNS, the author's copy can do the same, using the documented alternative.

## Critical User Journeys (CUJs)

### CUJ 1: First run and backfill

*   **Given**: A fresh install. It has a config file listing both sites, a service-account key file, a Trello key, board and lists, an off-host backup target and a dead-man URL.
*   **When**: The self-hoster runs the setup check, then the backfill command.
*   **Then**:
    *   The setup check reports each part as working or broken, with one fix step for each broken part.
    *   The backfill loads all available Search Console days for both sites, oldest first. It records which dates are final, and can resume where it stopped if interrupted.
    *   The backfill's last step is a backup.

### CUJ 2: The weekly brief

*   **Given**: The nightly pulls have run for at least 7 days since the backfill.
*   **When**: The weekly job runs (default Monday morning, in the configured time zone).
*   **Then**:
    *   Trello gets one summary card, with a data-health header (last final date, any gaps, any failed runs, backup age, comparison with the baseline), and 5 to 10 fix cards.
    *   Each opportunity has a stable ID, so it's never sent again while its card is open.

### CUJ 3: A fix ships and gets measured

*   **Given**: The author moves a fix card to the configured Done list after changing the page.
*   **When**: The nightly job reads the board.
*   **Then**:
    *   The fix is recorded with its ship date. That's the date of the move, unless the card description has a `shipped: YYYY-MM-DD` line.
    *   Once 28 final days after the ship date exist, the next brief reports the page's change in clicks and impressions, the comparison group's change, and the effect in extra clicks.
    *   The running total is updated.

### CUJ 4: Something breaks

*   **Given**: The service-account key is revoked, a nightly step fails, or the VM is down.
*   **When**: The next scheduled job runs, or the dead-man check's deadline passes.
*   **Then**:
    *   A Trello card names what failed, when, and the one step to fix it.
    *   If the VM is down or Trello is unreachable, the dead-man service sends an email instead.
    *   The missing dates are backfilled automatically after the fix.

### CUJ 5: Asking from Claude

*   **Given**: The MCP connector is installed in Claude.
*   **When**: The author asks something like "which evogr pages lost clicks this month?"
*   **Then**: Claude calls the matching MCP tool and gets pages, numbers and dates from the local database. Nobody has to open Search Console.

## Technical Plan (Architecture)

### Stack and shape

The tool is written in Python 3.11 or later, with a short pinned dependency list:

*   `google-auth` for service-account login and token refresh,
*   `google-api-python-client` for the Search Console and Drive APIs,
*   `requests` for Trello and the later Bing and AI APIs.

Everything else uses the standard library. `tomllib` reads the config file, and `sqlite3` holds the data.

The HTTP server and MCP layers copy Kestrel's pattern:

*   a `ThreadingHTTPServer` with one route table,
*   a local stdio MCP connector that forwards each tool call to an HTTP route,
*   a remote MCP endpoint at `/mcp/<secret>`, served by the same server process,
*   jobs run by systemd timers.

It runs on one Linux VM. The author's own host is Open Question Q9.

The names in the diagram (`shrike_gsc`, `shrike_opps` and so on) are logical components. Each one is a module in the `shrike/` package (`shrike/gsc.py`, `shrike/opps.py`, ...).

```text
                 systemd timers
        nightly 03:30 ─┐      ┌─ weekly Mon 07:00
                       v      v
  Google Search ──> shrike_gsc ──> SQLite (final rows append-only) ──> shrike_opps ──> shrike_brief ──> Trello
  Console API         │            │      ^                                       ^          │
  (service acct)      │            │      │                                       │          │
                      │            │      └──── shrike_fixes <──── card status ───────┴──────────┘
                      │            v
                      │       shrike_backup ──> Google Shared Drive (or other off-host target)
                      v
                  shrike_health ──> Trello "alert" card ; dead-man ping ──> email if pings stop

  Claude ──local MCP (stdio)──HTTP──> shrike_server (/v1/... and /mcp/<secret>) ──> SQLite (read only)
  claude.ai ──Cloudflare Tunnel──> /mcp/<secret> only
```

### Configuration and secrets

*   **`config.toml`** (committed as `config.example.toml`) holds the things the self-hoster chooses:
    *   the sites, each with its Search Console property string (such as `sc-domain:evogr.net` or `https://solodac.com/`),
    *   the time zone,
    *   the schedules,
    *   the opportunity thresholds,
    *   the Trello board and list IDs: `inbox_list_id` for new brief cards, `done_list_id` for shipped fixes and `alert_list_id` for alerts,
    *   the backup target,
    *   the dead-man URL,
    *   the Phase 3 cost cap.
*   **Secrets never go in the repo or in `config.toml`.** They live in an env file (`/etc/shrike/env`) and in the key file it points to (paths and modes in C1):
    *   the service-account key file path,
    *   the Trello key and token,
    *   the API key for `/v1/*`,
    *   the remote MCP secret (at least 24 characters, as in Kestrel),
    *   later, the Bing, Gemini, Perplexity and OpenAI keys.

    The server and the jobs refuse to start if the env file or the key file can be read by group or others.
*   **The service account** is added as a "Restricted" user on each Search Console property, which is read-only. It needs no OAuth consent screen, so it has no 7-day refresh-token expiry. Org key-expiry policies and revocation still apply, and the setup check reports them as auth errors.

### Data model (SQLite)

The tool stores only final Search Console data, meaning data Google has stopped revising. Stored rows are append-only: they're never edited or deleted. The 2 to 3 newest days, which aren't final yet, aren't stored. The weekly brief and fix measurement only use final days anyway.

| Table | Purpose |
|---|---|
| `schema_version` | One row with the current schema number. Migrations in `migrations/NNN_*.sql` run in order at startup, each inside a transaction. Migrations may only add tables, columns or indexes to the raw tables. They never drop or rewrite raw data. |
| `pulls` | One row per API pull: id, site, date, dimension set, data state (`final` or `all`), row count, whether the last page was full (`truncated`), started and finished time, and status. |
| `gsc_page_query` | Final rows keyed by `site, date, page, query, pull_id`: clicks, impressions, CTR, position. Web search type only in the core. |
| `gsc_page` | Final rows keyed by `site, date, page, pull_id`. Pulled separately because page-and-query rows drop the queries Google hides for privacy, so page totals are higher and must come from their own pull. |
| `gsc_site` | Final daily site totals keyed by `site, date, pull_id`. |
| `site_range` | Per site: the fixed first date (set once at the first backfill) and the newest final date (updated by every backfill and nightly run). See C2. |
| `meta` | Small key-value table; holds `phase1_seen_at` (C2). |
| `v_coverage` | A view that generates every date from `site_range.first_date` to `last_final_date`, crosses it with the three dimension sets, and joins `pulls`. That way, a date that was never pulled shows as `missing` (C2). The state is `final` (a successful final pull exists), `truncated` (the pull hit the daily row cap) or `missing`. A successful pull that returns 0 rows counts as final. This is how gaps are found. A date with any dimension set missing isn't complete. |
| `opportunities` | Stable ID, type, first seen, last seen, consecutive weeks not detected, score, status (`new`, `sent`, `done`, `dismissed` or `expired`), and Trello card id. |
| `fixes` | Opportunity id, page, ship date, and the measurement result once 28 final days after the ship date exist. |
| `baselines` | One frozen row per site, labeled `initial` and written once when the backfill first completes. It holds the 28 final days ending at the newest final date: clicks, impressions, CTR, average position and the date range. Never updated. |
| `runs` | Every job run: name, step, start, end, status, error text. |
| `events` | Every alert, keyed by kind and subject (for example `truncated:evogr:2026-03-02`), with its delivery status. It stops repeats: an ongoing failure alerts at most once a day, and a permanent condition alerts once. |

The rest of the code reads the three tables through views called `v_gsc_*`. These hide `pull_id`, which is kept to show where each row came from. Each date and dimension set is pulled successfully once, under a single writer lock, so there's only one copy to pick.

**When a date counts as final:** a pull with `dataState=final` for that date returns successfully. Google only returns final data for dates before the `firstIncompleteDate` in the response metadata of a `dataState=all` query, so that field decides when a final pull is tried. Final dates are not pulled again. A date older than the oldest date Search Console still has, that was never pulled, counts as expired: it's recorded and alerted once.

**Size check:** suppose a site averages 5,000 page-and-query rows a day. Keeping one final copy per date comes to about 2.5 million rows over 16 months, or roughly 300 to 500 MB per site with indexes. For two sites over 24 months that's about 0.9 to 1.5 GB. Gzip shrinks the database about 5 to 8 times, so 42 retained backups come to roughly 5 to 12 GB. Q4 replaces these estimates with real row counts.

### Jobs

Every job that writes (`backfill`, `nightly`, `weekly` and `setup`) takes one shared exclusive lock, an `flock` on `<data_dir>/writer.lock`, before it starts. Any second writer exits at once with "already running". Only `alert` skips the lock: it writes one `events` row and relies on SQLite's busy timeout.

Only job processes write to SQLite, which runs in WAL mode. The HTTP server opens it read-only.

**Backfill** (`shrike backfill`): for each site, sets `site_range` (C2), then walks forward day by day from the oldest date Search Console still has to the newest final date. That way, the days about to expire are saved first.

*   Each day is three pulls: site totals, pages, and page plus query.
*   Each pull pages through all result rows (see `shrike/gsc.py`).
*   If the API's daily row cap for a property cuts a day off, the day is marked `truncated`, and an alert is raised once.
*   It skips any date and dimension set `v_coverage` already marks as final or truncated, so a stopped backfill resumes where it left off.
*   When a site's coverage first reaches the newest final date with no gaps, it writes that site's `initial` row in `baselines`.
*   It stays under Search Console's per-site rate limit by pausing between calls and backing off on HTTP 429.
*   If coverage is still incomplete when the oldest missing date is within 14 days of expiring, it raises an alert.

**Nightly** (`shrike nightly`, 03:30 local time): each step runs on its own. A failure in one step is recorded and alerted, and the remaining steps still run.

1.  Refresh `site_range` (C2), then pull every date, up to the newest final date, that lacks a successful final pull for any of the three dimension sets. This covers the newly final days and any gaps.
2.  Back up:
    *   take a consistent snapshot with SQLite's online backup API,
    *   gzip it and upload it to the backup target,
    *   delete copies outside the retention rule (30 daily plus 12 monthly).
3.  Read the Trello board:
    *   cards moved to the Done list create `fixes` rows,
    *   a card closed before reaching Done marks its opportunity `dismissed`.
4.  Run the health checks.
5.  Ping the dead-man URL, if the job reached this step and no alert in this run went undelivered. A failed step that was alerted through Trello doesn't stop the ping, since the alert card is the notice. A broken Trello, a dead VM or a run that never started all stop it.

**Weekly** (`shrike weekly`, Monday 07:00 local time):

1.  Run the opportunity rules on the last 28 final days.
2.  Measure any fixes that now have 28 final days after their ship date.
3.  Build and send the brief.
4.  Once a month, check the backup:
    *   restore the latest backup to a temporary file,
    *   run SQLite's integrity check on it,
    *   compare its per-site `v_coverage` counts with the live database.

    If any of these fail, raise an alert.

**Setup** (`shrike setup`): runs the full setup check, including the checks that write to Trello and Drive. It saves the report to `<data_dir>/setup_report.json`.

**Alert** (`shrike alert --unit NAME`, started by systemd when a job process crashes; optional, since the dead-man check also catches crashes): posts an alert card naming the failed systemd unit, with the fix step "run `journalctl -u NAME` and see docs/OPERATIONS.md".

### Opportunity rules (`shrike_opps`)

All thresholds live in `config.toml`. Definitions used by the rules:

*   **Position** is the impression-weighted average position over the window.
*   **Position bands** are 1, 2, 3, 4-5, 6-10 and 11-20 (configurable).
*   **Expected CTR** for a band is the site's own median CTR in that band, over the last 90 final days.

The rules and their defaults:

*   **Striking distance:** queries with position 5 to 20 and at least 100 impressions in 28 days. Score = impressions × (expected CTR at position 3 − the query's current CTR).
*   **Low CTR:** pages with at least 500 impressions whose CTR is below half the expected CTR for their band. Score = impressions × (expected CTR − actual CTR), that is, missed clicks.
*   **Decaying:** pages whose clicks fell at least 30% over the last 28 days compared with the 28 days before, with at least 50 clicks in the earlier window. Score = clicks lost.

**Stable ID:** the SHA-256 of site, type, page and query, cut to 16 hex characters. Page-level types use an empty query.

**Lifecycle:**

*   A detected opportunity starts as `new`, and becomes `sent` when its card is posted. An open card is updated, not re-sent.
*   A card moved to Done marks the opportunity `done`. That's final: archiving the card later changes nothing.
*   A card closed before Done marks it `dismissed`.
*   A `sent` opportunity that isn't detected for 3 weekly runs in a row has its card closed and is marked `expired`.
*   A `dismissed` or `expired` opportunity can be sent again if it's detected again 8 or more weeks later.

Each brief takes at most `max_per_type` (default 4) of each type, so one type can't fill the brief. The top 5 to 10 by score are sent.

### The brief (`shrike_brief`)

Each weekly run posts:

*   **One summary card,** with:
    *   the data-health header (last final date per site, gaps, failed runs this week, backup age, and a warning if the backup target is `local`),
    *   each site's last 28 final days compared with its frozen baseline (clicks and impressions, as numbers and percent),
    *   the count of new opportunities,
    *   the results of fixes measured this week, and the running total.
*   **One card per opportunity,** with the page, query, the numbers behind it, why it was picked, and a suggested fix. The suggested fix comes from a template per opportunity type, not AI-written text.

The card ID is stored, so the nightly job can track the card's status.

### Fix measurement (`shrike_fixes`)

For each fix, the tool compares the page's clicks and impressions in the 28 final days after the ship date with the 28 final days before.

The comparison group is the same site's pages that:

*   had no fix shipped between 56 days before the ship date and the end of the 28-day after window, which is fully known when the fix is measured, and
*   are in the same impression quartile among the site's pages, ranked by total impressions in the 28 final days before the ship date.

The **effect** is measured in extra clicks per 28 days:

> effect = clicks before × (page's growth rate − comparison group's median growth rate)

Here, growth rate = (clicks after − clicks before) / clicks before. For example, a page with 400 clicks before that grew 25%, against a group median of 5%, has an effect of 400 × 0.20 = 80 extra clicks.

A result is measured and reported but left out of the running total when:

*   the comparison group has fewer than 10 pages ("too few comparison pages"),
*   the page had fewer than 100 impressions or 0 clicks in the before window ("too little data").

The **running total** is the sum of included effects, in extra clicks per 28 days.

### Health and alerts (`shrike_health`)

Every job step writes a `runs` record. These raise a Trello card in the alert list:

*   a failed step,
*   an auth error (HTTP 401 or 403),
*   a quota error that persists after retries,
*   a gap older than 3 days,
*   a truncated or expired day (alerted once, when first found),
*   a backup older than 48 hours,
*   no successful weekly run in 8 days,
*   a backfill falling behind the expiry date.

Each alert names the failure and the one step that fixes it. `events` stops repeats: ongoing failures alert at most once a day, and permanent conditions alert once.

**When Trello alerts can't reach anyone:** a self-check can't report a VM that is down, a nightly job that never started, or a Trello token that has stopped working. The **dead-man URL** covers those cases, and is required for G5.

*   The nightly job pings it only if the run reached its last step and no alert went undelivered. A Trello failure therefore also stops the pings.
*   A nightly run skipped because another writer holds the lock (exit 3) still pings. Every writer unit has a `TimeoutStartSec=` limit, so a hung writer is killed, fires `OnFailure` and releases the lock. It can't keep the pings going indefinitely (C14).
*   The service on the other end, for example a free healthchecks.io check with a 26-hour window, emails the self-hoster when pings stop.
*   `shrike setup` warns if no dead-man URL is set. It also tests the alert path end to end, by posting a test card and deleting it.

### HTTP API and MCP (`shrike_server`, `shrike_mcp`, `shrike_remote_mcp`)

The server listens on `127.0.0.1:8899` by default.

*   Routes under `/v1/` need the API key, sent as an `X-API-Key` header or as `Authorization: Bearer <key>`.
*   `/mcp/<secret>` needs only the secret in its path, as in Kestrel, because claude.ai connectors can't send custom headers. The request log replaces the path with `/mcp/***`, so the secret never reaches a log.
*   Both checks compare in constant time.
*   The server opens SQLite read-only.

| Route | What it returns |
|---|---|
| `GET /v1/setup` | The last report saved by `shrike setup`, plus read-only checks run on each call (config, file permissions, the dead-man URL, and the last runs). Each broken part comes with one fix step. The route never writes to Trello, Drive or SQLite. Same role as Kestrel's `kestrel_setup` (see `evogr1/kestrel`, `scout_mcp.py`, since 1.4.1). |
| `GET /v1/sites` | The configured sites, with coverage ranges and each site's last 28 days compared with its frozen baseline. |
| `GET /v1/performance` | Clicks, impressions, CTR and position for a site, page or query, with any date range or comparison. Paged with `limit` (default 50, max 1,000) and `offset`. Dates are Search Console dates, in US Pacific time. |
| `GET /v1/opportunities` | Current opportunities, filtered by site and type. |
| `GET /v1/fixes` | Fixes with their measurement status and results, plus the running total. |
| `GET /v1/health` | Recent runs, gaps, backup age and open alerts. |
| `POST /v1/jobs` (param `job`: `nightly`, `weekly` or `backfill`) | Runs `systemctl start --no-block shrike-<job>.service`, through a narrow polkit rule, and returns 202 with the unit name. If a writer unit is already running (`ActiveState` is `activating`, `active` or `deactivating`), it returns 409 "already running". The job runs in its own unit, with its own sandbox, journal and `OnFailure` alert. Its progress shows in `GET /v1/health`. |

The MCP tool names map one to one onto these routes (`shrike_setup`, `shrike_sites`, `shrike_performance`, `shrike_opportunities`, `shrike_fixes`, `shrike_health` and `shrike_run_job`). The local stdio connector serves all seven. The remote endpoint serves the same tools except `shrike_run_job`.

**Remote access:**

*   The default exposure path is a Cloudflare Tunnel (`cloudflared`). It forwards only `/mcp/` to `127.0.0.1:8899`, and never `/v1/`.
*   As in Kestrel, the path secret is the only gate on `/mcp/`. Cloudflare Access isn't put in front of that path, because claude.ai connectors can't complete an Access login. 
*   The secret is part of the URL, so Cloudflare's edge can see it. That's accepted, the same as for Kestrel.
*   Proxied DNS into Caddy or nginx is the documented alternative (Q9).

### Backups (`shrike_backup`)

The default target is a Google Shared Drive folder. The service account is a member of the folder with the Content Manager role.

*   A plain "My Drive" folder won't work, because service accounts have no Drive storage of their own.
*   In a Shared Drive, a Content Manager can move files to the trash but can't permanently delete them; only a Manager can. The 30-day trash therefore protects the backups, as long as the service account isn't given the Manager role.
*   The setup check confirms the role by trying a permanent delete on a test file and expecting it to fail.

Self-hosters without Google Workspace set `backup.target = "local"` and a path, then copy that folder off the machine their own way. In that mode G1 counts as not met, and the setup check and every brief header say so. The setup check reports which mode is active and whether a test upload worked.

### Later phases (shape only, detailed in their own plan revisions)

*   **Phase 2:**
    *   `shrike_audit`: an on-demand single-URL audit using the free PageSpeed Insights API plus an HTML fetch. It checks:
        *   the title, meta, headings, schema, canonical tag and internal links,
        *   whether robots.txt allows the crawlers that power AI search (OAI-SearchBot, PerplexityBot, Googlebot and Bingbot).

        Training-only bots are reported separately.
    *   `shrike_bing`: the Bing Webmaster API, stored in the same final-rows pattern.
    *   IndexNow submission, only if Q7 finds that nothing already sends it.
    *   Competitor sitemap and title diffs.
*   **Phase 3:**
    *   `shrike_ai`: imports the Bing AI Performance CSV from a watched folder.
    *   Gemini grounding, if Q5 allows storing its results.
    *   Perplexity and OpenAI, off by default. Each paid call first reserves its maximum cost in a `ledger` table, and is refused if that would pass the monthly cap. Retries count against the cap.
    *   Prompts are versioned and each runs at least 3 times per engine. Raw answers are stored, and every figure is labeled a proxy.

## Risks & Mitigations

| # | Risk | Impact | Mitigation or acceptance | Linked |
|---|---|---|---|---|
| 1 | Oracle reclaims an idle Always Free VM | Lose up to 24 h of data and the service until restored | Nightly off-host backups limit the loss to at most 24 h. The dead-man check reports the outage. docs/OPERATIONS.md has the restore steps. | Q9 |
| 2 | Two writer jobs run at once | Duplicate pulls and cards, "database is locked" errors, double quota use | One shared `writer.lock` for every writing job. Only job processes write. The API starts jobs as their own systemd units. | Jobs |
| 3 | The per-property daily row cap is hit | Some page-and-query rows for that day are missing | The day is marked `truncated`, an alert is raised, and page and site totals are still pulled separately. | Q4 |
| 4 | Trello API rate limits | Brief cards fail to post | About 15 cards a week, far under Trello's limits. A failed card leaves its opportunity `new` for the next run. Accepted. | |
| 5 | The backup credential is misused or leaks | Backups deleted | The Content Manager role can't permanently delete, so trashed backups stay for 30 days. The setup check confirms the role. Open in `local` mode. | Backups |
| 6 | Google holds both the source data and the backup | A Workspace account suspension blocks both | Accepted by the author when choosing Drive backups on 2026-11-19 (Alternative I). | |
| 7 | Days expire before the backfill saves them | Permanent gaps in the oldest history | Backfill oldest-first, plus an alert when a missing date is within 14 days of expiring. | Jobs |
| 8 | Gemini terms forbid storing grounded results | No stored Gemini citation history | Blocks Phase 3 only. Decided once Q5 is answered. | Q5 |
| 9 | The Bing AI Performance report stays manual (CSV) | Bing citation data lags until someone exports it | Accepted until Microsoft ships an API. | |
| 10 | Shipping many fixes (G3) shrinks the comparison pool (G4) | Fewer fixes count toward the running total | Results with fewer than 10 comparison pages are reported but left out of the total. Accepted. | G3, G4 |

## Alternatives Considered

### Alternative A: Build it as a module inside Kestrel

*   **Pros**: One server, one MCP connector and one deploy. Search and video research could share config, alerts and the Trello push.
*   **Cons**:
    *   Kestrel's data and jobs are about YouTube, Instagram and X, not search.
    *   A failure in one tool's daily job, or a quota problem, would affect the other.
    *   Each tool would be harder to release on GitHub separately.
*   **Reason for Rejection**: Rejected by author: search should ship and be released on GitHub as its own tool, like Kestrel. A side effect is that failures stay apart: a quota error or crashed job in one tool can't stop the other.

### Alternative B: Use the OpenSEO connector instead of building

*   **Pros**: It already exists in the author's setup, and covers Search Console, AI visibility and rank tracking. No code to write or maintain.
*   **Cons**: It's credit-billed, and keeps no history the author controls (as used in the author's setup). Fixes aren't tracked or measured.
*   **Reason for Rejection**: Rejected by author: the tool must cost $0 to run, keep a permanent history the author owns, and be releasable free on GitHub.
    *   The [concepts brief](../../concepts_brief.md) also weighed a 2-week OpenSEO trial before building. The author declined it on 2026-11-19, because it would add nothing to this launch.
    *   An OpenSEO audit of a specific site can still run as a separate task.

### Alternative C: Scrape chatgpt.com and other AI chat sites through a browser

*   **Pros**: Free, and it would show what real users see in ChatGPT, not what the API returns.
*   **Cons**: It breaks those sites' terms and breaks whenever their pages change. It also needs a logged-in browser, which can't run on a headless VM.
*   **Reason for Rejection**: Rejected by author: the terms-of-service risk isn't acceptable in a public GitHub release. The paid APIs, capped by the cost ledger, replace it.

### Alternative D: Read Bing's AI Performance report through a logged-in browser

*   **Pros**: Fully automatic, with no manual CSV step. That matters because the report has no API (checked 2026-11-19).
*   **Cons**: It needs a browser session on a headless VM, breaks when the dashboard changes, and may break Bing's terms.
*   **Reason for Rejection**: Rejected by author for the public core: the CSV export, dropped into a watched folder, carries the report's data with no terms risk. If Microsoft ships the API that's on its backlog, it replaces the CSV step.

### Alternative E: Google OAuth user login instead of a service account

*   **Pros**: Works without adding a new user to each Search Console property. Access is the same as the author's own.
*   **Cons**:
    *   An OAuth app left in "Testing" mode issues refresh tokens that expire after 7 days, so jobs quietly stop.
    *   Publishing the app to avoid that needs Google's verification review for the Search Console scope.
*   **Reason for Rejection**: Rejected by author: a service account added as a read-only user has no 7-day refresh-token expiry, and needs no consent screen or verification.

### Alternative F: Share code with Kestrel as a library now

*   **Pros**: One copy of the HTTP server, MCP layer and Trello code. Fixes in one tool reach both.
*   **Cons**: It ties the two release cycles together, and creates a third package to version before anyone knows how much code really overlaps.
*   **Reason for Rejection**: Rejected by author: copy what's needed for v1, and note in the code where it came from. Pull out a shared library only if both tools keep needing the same changes.

### Alternative G: Python standard library only, same as Kestrel

*   **Pros**: Nothing to install, and Kestrel's code can be copied as is.
*   **Cons**:
    *   Python's standard library can't sign the RSA token a service account needs, so it would have to shell out to `openssl`.
    *   Token refresh and the Drive upload would also be hand-written.
*   **Reason for Rejection**: Rejected by author in favor of Python with a few pinned libraries. Google's own `google-auth` and `google-api-python-client` handle login, refresh and paging. The cost is a `pip install` step.

### Alternative H: TypeScript on Cloudflare Workers with D1

*   **Pros**: No VM for Oracle to reclaim, and built-in point-in-time restore. Same stack as `evogr-ops`, the author's Cloudflare Workers project.
*   **Cons**:
    *   Little Kestrel code carries over.
    *   A large backfill has to be split into chunks to fit per-run CPU limits and D1's free read and write caps.
    *   Self-hosters need a Cloudflare account.
*   **Reason for Rejection**: Rejected by author: on 2026-11-19 the author chose Python with pinned libraries over this.
    *   The trade-off: D1 free caps, CPU limits that force a chunked backfill, a Cloudflare account for every self-hoster, and almost no Kestrel reuse, against VM reclaim risk.
    *   The VM risk is covered in Risks & Mitigations, row 1.

### Alternative I: Back up to Cloudflare R2 or Oracle Object Storage

*   **Pros**:
    *   R2 is with a different provider from the VM, so one account problem can't take both copies.
    *   Oracle storage needs no new signup and gives 20 GB free.
*   **Cons**: Both need extra keys. Oracle storage shares a single point of failure with the VM: the Oracle account itself.
*   **Reason for Rejection**: Rejected by author in favor of a Google Shared Drive, reached through the same service account. The trade-off is accepted: Google holds both the source data and the backup (Risks & Mitigations, row 6). Self-hosters without Workspace get a local-folder option.

### Alternative J: A daily feed, like Kestrel's

*   **Pros**: The same morning habit as Kestrel.
*   **Cons**: Search Console data arrives 2 to 3 days late and changes slowly. A daily push would mostly repeat itself and train the reader to ignore it.
*   **Reason for Rejection**: Rejected by author, adopting a finding recorded in the [concepts brief](../../concepts_brief.md): data is collected nightly, but only the weekly brief is pushed.

### Alternative K: Hand backups to restic or rclone

*   **Pros**:
    *   Upload, retention and restore checks come ready-made.
    *   restic's deduplication would store close to one copy of an append-only database, not 42 full snapshots.
    *   Both tools support Shared Drives with a service account.
*   **Cons**: It adds a second tool to install and update for every self-hoster. restic also adds a repository password to keep safe. The Drive code it replaces is small: upload, list, trash, download.
*   **Reason for Rejection**: Rejected by author for v1, keeping the Google Shared Drive choice made on 2026-11-19 with no extra tools. Revisit it if backups pass 10 GB, or once Q4's real numbers are known (see Future Improvements).

--------------------------------------------------------------------------------

## Non-Functional Requirements

*   **Security & Privacy**:
    *   The service account has Restricted (read-only) access to Search Console, and Content Manager access to one Shared Drive folder only.
    *   Secrets live only in the env file and the key file. Both must be mode 600 or stricter, and the server and jobs refuse to start if either can be read by group or others.
    *   The HTTP server binds to `127.0.0.1`. Remote access goes only through the tunnel to `/mcp/<secret>`.
    *   The request log masks the secret path. Logs never contain keys, tokens or the secret.
*   **Performance & Footprint**:
    *   A normal nightly run pulls 1 newly final date × 3 dimension sets × 2 sites = 6 queries plus paging, and more only when it fills gaps.
    *   The backfill makes about 482 dates × 3 pulls per site plus paging, with a 0.5 s pause between calls.
    *   Exact runtimes are measured in Phase 0 and depend on Q4.
    *   Database size follows the size check in the Data model section.
*   **Rollout & Rollback**:
    *   On upgrade, the first job to run (`shrike setup`, by `install.sh`) takes an explicit snapshot before running any migration. Each migration runs inside a transaction. The server never migrates; it refuses to serve data routes until the schema is current.
    *   Rolling back means restoring that snapshot and running the previous release.
    *   Final raw rows are append-only by rule: no code path updates or deletes them, and migrations may only add. A bad release can still corrupt derived data.
    *   Opportunity scores are recomputed from raw rows by every weekly run. Fix records, opportunity statuses and card links can't be rebuilt; they come back only from a backup.

### Additional Resources

*   [Concepts brief](../../concepts_brief.md), the brainstorm output this design was drafted from.
*   EGM review reports, each in the session folder:
    *   [Stage 5 zoom-out](../../zoom_out_report.md)
    *   [Stage 6 comprehension](../../comprehension_report.md)
    *   [Stage 7 critic](../../critic_report.md), resolved in [goldfish_review_report.md](../../goldfish_review_report.md)
    *   [Stage 8 zoom-out](../../intermediate_zoom_out_report.md)
    *   [Stage 9 readiness, round 1](../../implementation_readiness_report.md) and [round 2](../../implementation_readiness_report_r2.md)
*   The Stage 9 re-audit cap (one re-audit) was reached. All round-2 Blockers and Majors were fixed in this document afterwards, but no third review was run on those fixes.
*   The reviewed Kestrel reference sources are an older copy. The live code is at `evogr1/kestrel`.

### Future Improvements

*   **Analytics hookup**: Import GA4 or Cloudflare Web Analytics visits, so fix results can be stated in visits and not only in clicks.
*   **Shared library with Kestrel**: Pull out a shared library if both tools keep changing the same server, MCP or Trello code.
*   **Bing AI Performance API**: Replace the CSV import once Microsoft ships the API.
*   **Deduplicated backups**: Move upload and retention to restic if backup size passes 10 GB (Alternative K).
*   **AI-written fix suggestions**: Replace the template fix text with model-written suggestions, after the template version proves which fix types ship.

--------------------------------------------------------------------------------

## Detailed Implementation Plan

This plan covers **Phase 0 and Phase 1** in full. Files tagged **[P0]** are needed to start capturing data, and ship first. Files tagged **[P1]** complete the core. Phases 2 and 3 each get their own revision of this section before they're built. They depend on open questions (Q5 to Q8) and on whether Phase 1 meets G2 and G3.

The repo and Python package are both `shrike`. It targets Python 3.11 or later. Tests use the standard `unittest` module. Where code is copied from Kestrel, a comment at the top of the file names the Kestrel file and commit it came from (Alternative F).

### Contracts

This section fixes the schema, interfaces and edge rules that the file list below refers to. When a file entry and this section disagree, this section wins.

#### C1. Paths, users and secrets

| Item | Value |
|---|---|
| Code checkout | `/opt/shrike` (git clone of the repo) |
| Virtualenv | `/opt/shrike/venv`, with the package installed via `pip install /opt/shrike` (non-editable) |
| Config directory | `/etc/shrike/`, owner `root:shrike`, mode 750 |
| Config | `/etc/shrike/config.toml`, owner `root:shrike`, mode 640. `SHRIKE_CONFIG` overrides the path. |
| Env file | `/etc/shrike/env`, owner `root:root`, mode 600. systemd reads it through `EnvironmentFile=`. Each unit also sets `Environment=SHRIKE_ENV_FILE=/etc/shrike/env`, so the code can check the file's mode. |
| Service-account key | `/etc/shrike/sa.json`, owner `shrike:shrike`, mode 600. `SHRIKE_SERVICE_ACCOUNT_FILE` points to it. |
| Data directory | `/var/lib/shrike` (`StateDirectory=shrike` with `StateDirectoryMode=0700`, owner `shrike`). `install.sh` also creates it, as `shrike:shrike` mode 700, so it exists before any unit runs. It holds `data.sqlite`, `writer.lock`, `setup_report.json`, `tmp/` and, in local backup mode, the default `backups/`. |
| Migrations | `shrike/migrations/NNN_*.sql`, shipped inside the package and read with `importlib.resources` |

Which entry point needs which secret:

| Entry point | Requires |
|---|---|
| `shrike` (all subcommands except `alert` and `render-units`) | `SHRIKE_SERVICE_ACCOUNT_FILE`. `SHRIKE_TRELLO_KEY` and `SHRIKE_TRELLO_TOKEN`, which are required in every phase, because Phase 0 alerts are Trello cards (G5). |
| `shrike render-units` | none (it reads only `config.toml`) |
| `shrike alert` | `SHRIKE_TRELLO_KEY` and `SHRIKE_TRELLO_TOKEN` |
| `shrike-server` | `SHRIKE_API_KEY`, at least 24 characters, as in Kestrel. `SHRIKE_MCP_SECRET` is optional: when it's empty, `/mcp/` returns 404. When set, it must be at least 24 characters. |
| `shrike-mcp` (stdio) | `SHRIKE_URL` (default `http://127.0.0.1:8899`) and `SHRIKE_API_KEY` |

`load_secrets(entry)` checks only what its entry point needs. It checks that the files named by `SHRIKE_ENV_FILE` (when set) and `SHRIKE_SERVICE_ACCOUNT_FILE` have no group or other permission bits.

`shrike-mcp` runs on the author's laptop, reaching the VM through an SSH port forward: `ssh -N -L 8899:127.0.0.1:8899 vm`. `SHRIKE_URL` and `SHRIKE_API_KEY` are set in the laptop's MCP client config. This is the only supported way to use the local MCP.

The server uses port 8899, so it doesn't clash with Kestrel's 8799 on a shared VM.

#### C2. Schema (`shrike/migrations/001_init.sql`)

All dates are `TEXT 'YYYY-MM-DD'`, in Search Console dates (US Pacific). All timestamps are `TEXT`, in ISO 8601 UTC.

| Table | Columns | Keys and constraints |
|---|---|---|
| `schema_version` | `version INTEGER NOT NULL` | Exactly one row |
| `site_range` | `site TEXT`, `first_date TEXT`, `last_final_date TEXT`, `updated_at TEXT` | PK `site`. `first_date` is set once, at the first backfill, to `available_range().oldest`, and is never moved. `last_final_date` is updated every nightly run. |
| `pulls` | `id INTEGER PK`, `site`, `date`, `dims TEXT CHECK IN ('site','page','page_query')`, `data_state TEXT CHECK = 'final'`, `status TEXT CHECK IN ('ok','error')`, `row_count INTEGER`, `truncated INTEGER CHECK IN (0,1)`, `error TEXT`, `started_at`, `finished_at` | Unique partial index on `(site, date, dims) WHERE status = 'ok'`. Failed pulls write `status = 'error'` rows. The `firstIncompleteDate` probe isn't recorded. |
| `gsc_site` | `site`, `date`, `clicks INTEGER`, `impressions INTEGER`, `ctr REAL`, `position REAL`, `pull_id INTEGER REFERENCES pulls` | PK `(site, date)` |
| `gsc_page` | the `gsc_site` columns plus `page TEXT` | PK `(site, date, page)` |
| `gsc_page_query` | the `gsc_page` columns plus `query TEXT` | PK `(site, date, page, query)` |
| `baselines` | `site`, `label TEXT`, `start_date`, `end_date`, `clicks`, `impressions`, `ctr`, `position`, `created_at` | PK `(site, label)`. Only `initial` is used. |
| `opportunities` | `id TEXT PK`, `site`, `type TEXT CHECK IN ('striking_distance','low_ctr','decaying')`, `page`, `query TEXT DEFAULT ''`, `score REAL`, `metrics TEXT` (JSON: `impressions`, `clicks`, `ctr`, `position`, `expected_ctr`, `clicks_prev`, `window_end`), `status TEXT CHECK IN ('new','sent','done','dismissed','expired')`, `status_changed_at`, `first_seen`, `last_seen`, `last_detected_run INTEGER`, `weeks_missing INTEGER DEFAULT 0`, `card_id TEXT` | Index on `status` |
| `fixes` | `id INTEGER PK`, `opportunity_id TEXT UNIQUE REFERENCES opportunities`, `site`, `page`, `ship_date`, `ship_date_source TEXT CHECK IN ('trello_move','card_line')`, `before_start`, `before_end`, `after_start`, `after_end`, `clicks_before`, `clicks_after`, `impr_before`, `impr_after`, `group_size INTEGER`, `group_median_growth REAL`, `effect_clicks REAL`, `included INTEGER`, `exclusion_reason TEXT`, `measured_at` | The measurement columns stay NULL until measured. |
| `runs` | `id INTEGER PK`, `job TEXT`, `step TEXT` (NULL on the job-level row), `parent_id INTEGER`, `status TEXT CHECK IN ('running','ok','error')`, `started_at`, `finished_at`, `error TEXT`, `undelivered_alerts INTEGER DEFAULT 0` | Index on `(job, started_at)` |
| `events` | `id INTEGER PK`, `kind TEXT`, `subject TEXT`, `day TEXT` (the date in `general.timezone`, or `'once'`), `message TEXT`, `delivered INTEGER`, `card_id TEXT`, `created_at` | Unique on `(kind, subject, day)` |
| `meta` | `key TEXT PK`, `value TEXT` | Holds `phase1_seen_at`, which nightly writes the first time it runs with `general.phase >= 1` |

Views:

*   **`v_gsc_site`, `v_gsc_page` and `v_gsc_page_query`** return the table columns without `pull_id`.
*   **`v_coverage`** is a recursive CTE. It generates every date from `site_range.first_date` to `site_range.last_final_date` for each site, crosses it with the three `dims` values, and left-joins the `ok` final pulls. The state comes out as:
    *   `final` (an `ok` pull with `truncated = 0`),
    *   `truncated` (an `ok` pull with `truncated = 1`),
    *   `missing` (no `ok` pull).

Triggers abort `UPDATE` and `DELETE` on the three `gsc_*` tables. Application code therefore can't change final rows. A future migration could still drop the triggers, which is why migrations are limited to additions by review.

#### C3. Dataclasses

| Name | Fields |
|---|---|
| `Config`, `Secrets` | One field per key in `config.example.toml` and per environment variable in C1 |
| `JobContext` | `conn`, `cfg`, `secrets`, `trello` (always a `Trello`), `gsc` (a Search Console client, or `None` for `alert`), `job_run_id` |
| `ServerContext` | `db_path`, `cfg`, `secrets`, `data_dir` |
| `FetchResult` | `rows: list[dict]`, `truncated: bool` |
| `Opportunity` | the `opportunities` columns, with `metrics` as a dict |
| `Result` | the `fixes` measurement columns |
| `Comparison` | `site`, `baseline` (clicks, impressions, start, end), `current` (the same fields), `clicks_pct`, `impressions_pct` |
| `Check` | `name`, `ok: bool`, `detail`, `fix_step`, `checked_at` |
| `Problem` | `kind`, `subject`, `message`, `fix_step`, `once: bool` |
| `Brief` | `header: list[str]`, `comparisons: list[Comparison]`, `opportunities: list[Opportunity]`, `measured: list[Result]`, `running_total: float`, `note: str` |

#### C4. Pull rules (`shrike/gsc.py`)

*   **Retention window.** `oldest = newest_final - 482 days`. Google keeps about 16 months, about 486 days. The 4-day margin stops the backfill from requesting a date that expires while the run is still going. The plain day arithmetic avoids month math, which the standard library doesn't provide.
*   **Pacing.** There's a pause of `pull_pause_seconds` (default 0.5) between API calls. Retries are as described in item 14.
*   **Final-but-empty guard.** If a final site-totals pull for a date returns 0 rows, the `dataState=all` probe is checked for that date. If the probe shows impressions there, the pull is recorded as `status = 'error'` with "final data not ready", so it's retried the next night. Only a final pull that agrees with the probe, or a date the probe also shows as empty, counts as a zero-row final day.
*   **Error classification.** For 403 responses, the code reads `error.errors[0].reason`. The reasons `rateLimitExceeded`, `userRateLimitExceeded`, `quotaExceeded` and `dailyLimitExceeded` are retried like 429, and then raise `QuotaError`. Any other 401 or 403 raises `AuthError`, with an API-specific fix step: for Search Console, "add <sa email> as a Restricted user on <property>"; for Drive, "add <sa email> as Content Manager on the backup folder".
*   **Truncation.** A day is `truncated` when a `page` or `page_query` pull returns 50,000 rows or more. That's the API's documented per-day, per-search-type cap. An exact multiple of 25,000 below the cap is not treated as truncated.

#### C5. Opportunity rules (`shrike/opps.py`)

*   **Position bands.** Position is rounded half-up to an integer, then mapped to a band. A position of 20.5 or more has no band, so the page is skipped by `low_ctr`. The striking-distance bounds (5 to 20) apply to the rounded position.
*   **Expected CTR.** Built from `v_gsc_page_query`, aggregated per `(page, query)` over the last `expected_ctr_days` (default 90) final days.
    *   Only pairs with at least `expected_ctr_min_impr` impressions count (default 10, in config).
    *   For each pair, CTR = clicks / impressions.
    *   The expected CTR is the median per band.
*   **Striking distance** is evaluated per `(page, query)` pair, so the opportunity ID uses that page.
*   **Thresholds.** All bounds are inclusive (`>=` and `<=`).
*   **Brief selection.** `select_for_brief` takes only `new` opportunities with `last_detected_run` equal to the current run.
    *   If fewer than `brief_min` qualify, it sends what there is, and the summary card says how many.
    *   If none qualify, it sends only the summary card.
*   **Resend.** A detected `dismissed` or `expired` opportunity returns to `new` when `status_changed_at` is at least `resend_after_weeks` old. `last_seen` doesn't affect this.
*   **Open cards.** For a `sent` opportunity detected again, the weekly job calls `trello.update_card(card_id, name, desc)`, so the title's numbers are refreshed too.
*   **Card titles:** `[site] Striking distance: "<query>" (pos 7.3)`, `[site] Low CTR: <path> (0.8% vs 2.1%)` and `[site] Decaying: <path> (−42% clicks)`. The summary title is `[Shrike] Week of YYYY-MM-DD`.
*   **Templates.** Each template has the fields `why` and `fix`. No template may contain "FAQ rich result" or "llms.txt", and this is checked by `test_brief.py`.

#### C6. Fix measurement rules (`shrike/fixes.py`)

*   **Ship date.** The Trello move timestamp is converted from UTC to a US Pacific date. A `shipped: YYYY-MM-DD` line in the card description is taken as a Pacific date.
*   **Windows.** The before window is `ship_date − window_days` to `ship_date − 1`. The after window is `ship_date + 1` to `ship_date + window_days`. The ship date itself is in neither.
*   **Exclusion window.** Comparison pages may have no fix shipped from `ship_date − exclusion_before_days` to `ship_date + window_days`.
*   **Population.** The site's pages with at least 1 impression and at least 1 click in the before window, not counting the fixed page.
*   **Small populations.** If the population has fewer than `min_comparison_pages` pages, the fix is stored with `exclusion_reason = 'too few comparison pages'`, and `statistics.quantiles` isn't called.
*   **Quartile rule.**
    *   The boundaries are `statistics.quantiles(before_impressions, n=4, method='inclusive')`.
    *   The fixed page falls in the first quartile whose upper boundary is at least its before impressions. The fourth quartile has no upper bound.
    *   Comparison pages are the population pages in that same quartile.
*   **Zero clicks.** A fixed page with 0 clicks before is never measured as growth. It's stored with `exclusion_reason = 'too little data'`.

#### C7. Routes and MCP tools (`shrike/routes.py`)

Each route entry is `Route(method, path, handler, tool, description, params, remote)`. Each item in `params` is `Param(name, type, required, default, enum, description)`. The MCP `inputSchema` is generated from `params`.

Handlers have the signature `handler(ctx: ServerContext, conn, **params) -> dict`. The server opens a fresh read-only connection (`db.connect_ro`) for each request, and closes it afterwards. No connection is shared between threads. Using one table for both the HTTP routes and the MCP tools is a change from Kestrel, which keeps `ROUTES` and `TOOLS` separately.

| Method and path | Tool | Params | Response (JSON) |
|---|---|---|---|
| `GET /v1/setup` | `shrike_setup` | none | `{checks: [Check], report_saved_at}` |
| `GET /v1/sites` | `shrike_sites` | none | `{sites: [{name, property, first_date, last_final_date, missing_days, comparison: Comparison}]}` |
| `GET /v1/performance` | `shrike_performance` | `site` (str, required), `page` (str), `query` (str), `start` and `end` (date; defaults to the 28 days ending at `last_final_date`), `compare` (enum `prev_period`, `prev_year`), `group_by` (enum `date`, `page`, `query`; default none), `limit` (int, default 50, max 1,000), `offset` (int, default 0) | `{site, start, end, totals: {clicks, impressions, ctr, position}, compare_totals?, rows: [{key, clicks, impressions, ctr, position, compare?: {...}}], next_offset?}` |
| `GET /v1/opportunities` | `shrike_opportunities` | `site` (str), `type` (enum of the three types), `status` (list of the five statuses; default `new,sent`), `limit` (default 50) | `{opportunities: [Opportunity]}` |
| `GET /v1/fixes` | `shrike_fixes` | `site` (str), `measured` (bool) | `{fixes: [Result plus page and ship_date], running_total}` |
| `GET /v1/health` | `shrike_health` | none | `{db: "ok" or "not initialized" or "schema old", runs: [last 20 job rows with their steps], missing_days, truncated_days, backup_age_hours, open_alerts: [events from the last 7 days]}`. `backup_age_hours` comes from the last `ok` `backup` step in `runs`, so the server makes no Drive call. With no database, only `db` is returned. |
| `POST /v1/jobs` | `shrike_run_job` | `job` (enum `nightly`, `weekly`, `backfill`; required) | `202 {unit}` or `409 {error: "already running"}` |
| `GET /health` | none | none | `{ok: true}`, with no key needed (as in Kestrel) |

`/v1/performance` uses `v_gsc_site` when neither `page` nor `query` is given and `group_by` isn't `page` or `query`. It uses `v_gsc_page` when `page` is given without `query` and `group_by` isn't `query`. Otherwise it uses `v_gsc_page_query`.

Rows are sorted by date ascending for `group_by=date`, and by clicks descending otherwise. CTR is total clicks divided by total impressions. Position is impression-weighted.

**`/v1/performance` details:**

*   **`compare`:** `prev_period` is the same number of days, ending the day before `start`. `prev_year` is the same dates shifted back 364 days, which keeps weekdays aligned. Comparison dates before `first_date` give `compare_totals: null`.
*   **No `group_by`:** `rows` is empty and only `totals` is returned.
*   **Row keys:** `key` is the date for `group_by=date`, the page URL for `page`, and the query text for `query`.
*   **Filters:** `page` and `query` are exact matches.
*   **Dates:** `start > end`, or a range outside `first_date` to `last_final_date`, returns 400 naming the bad parameter.

**Parameter parsing** (query string):

*   `date` must be `YYYY-MM-DD`.
*   `int` is base 10, and is checked against its bounds.
*   `bool` accepts `1`, `true`, `yes` and `on`, or `0`, `false`, `no` and `off` (any case), as in Kestrel.
*   List params are comma-separated.
*   `POST /v1/jobs` takes a JSON body.

Only `POST /v1/jobs` is `remote = false`.

#### C8. HTTP server behavior (`shrike/server.py`)

*   **Auth.** `/v1/` routes accept `X-API-Key: <key>` or `Authorization: Bearer <key>`, compared in constant time.
*   **Errors.** Every error body is `{"error": str, "fix_step": str | null}`.

| Case | Response |
|---|---|
| Missing or wrong API key on `/v1/` | 401. This is checked before the route lookup, so unauthenticated callers never see the route list. |
| Unknown path | 404, plus `{routes: [...]}` |
| Wrong method | 405 |
| Unknown parameter, or a parameter that fails its type, enum or bounds check | 400, naming the parameter |
| Missing required parameter | 400 |
| Body over 4 MiB | 413 |
| `SkError` | its own status |
| Any other exception | 500 with `{"error": "internal error"}`. The log gets only `repr(exc)`, never a traceback with request data. |

*   **Database state.** The server checks the database on each request, caching the result for 5 seconds, so a later setup or migration is picked up without a restart.
    *   If `data.sqlite` is missing, only `/health`, `/v1/setup` and `/v1/health` answer. They report "database not initialized; run `shrike setup`".
    *   If the schema version is older than the code's, all other routes return 503, "run `shrike setup` to migrate".
    *   The server never migrates.
*   **Read-only access to a WAL database.** The server unit has `ReadWritePaths=/var/lib/shrike`, so SQLite can create the `-wal` and `-shm` files when no writer is running. The connection itself stays `mode=ro`, so the server still can't write data.
*   **Log masking.** `log_message` and `log_error` apply `re.sub(r"/mcp/[^\s/?]+", "/mcp/***", ...)` to the fully formatted message, including the request line passed in `args`.

#### C9. Remote MCP behavior (`shrike/mcp_remote.py`), following `scout_remote_mcp.py`

*   **Signature:** `handle(ctx, routes, msg) -> dict | None`.
*   **Batches:** a JSON array is handled item by item.
*   **Notifications:** a message with no `id` returns `None`. If every item returns `None`, the server answers 202 with an empty body.
*   **Methods:**
    *   `initialize` returns `protocolVersion`, `capabilities: {tools: {}}` and `serverInfo: {name: "shrike", version}`. The supported versions are `2024-11-05`, `2025-03-26` and `2025-06-18`. The client's version is used if supported, otherwise `2025-06-18`.
    *   `ping` returns `{}`.
    *   `tools/list` returns the remote tools.
    *   `tools/call` runs the handler. Its result is `{content: [{type: "text", text: json}]}`, with `isError: true` on a handler error.
*   **Error codes:** -32600 for an invalid request, -32601 for an unknown method, and -32602 for an unknown tool or bad arguments (as in Kestrel).
*   **Output cap:** tool output over `MAX_CHARS = 60000` is truncated, with a note saying so.
*   **HTTP limits:** non-POST requests get 405. Bodies over 4 MiB get 413. A body that isn't JSON gets 400.

#### C10. Local MCP behavior (`shrike/mcp_stdio.py`), following `scout_mcp.py`

*   It reads `SHRIKE_URL` and `SHRIKE_API_KEY`.
*   Messages without an `id` (notifications) get no reply. Lines that aren't valid JSON are skipped.
*   `initialize` negotiates the protocol version the same way as C9.
*   It handles `initialize`, `ping` and `tools/list`. `tools/call` is a request to the route's method and path: GET parameters go in the query string, and POST parameters in a JSON body.
*   Each request has a 300 s timeout.
*   An HTTP error from the server comes back as `isError: true`, with the error body.
*   Output is truncated at `MAX_CHARS`.
*   An unknown method returns -32601, and an unknown tool returns -32602.

#### C11. Health checks and alerts (`shrike/health.py`)

Usage: `with health.step(ctx, job, name) as s: ...`. After the block, `s.ok` tells whether the step succeeded.

*   The context manager records the step row, catches the exception and calls `health.alert(ctx, kind="step_failed", subject=f"{job}:{name}", ...)`.
*   `alert` increments `runs.undelivered_alerts` on the job row when Trello delivery fails.
*   `ping_dead_man` is skipped when that counter is above 0.
*   An `AuthError` or `QuotaError` raised inside a step alerts under `auth` or `quota`, not under `step_failed`, so one failure creates one card.
*   In this table, "today's `oldest`" means `last_final_date − 482 days` (C4). The checks need no Search Console call.

| Kind | Subject | Source | Threshold (config `[health]`) | Repeat |
|---|---|---|---|---|
| `step_failed` | `job:step` | `health.step` | none | daily |
| `auth` | `service:site` | `AuthError` | none | daily |
| `quota` | `site` | `QuotaError` after retries | none | daily |
| `gap` | `site` | `v_coverage` `missing` dates older than `last_final_date − gap_days` | `gap_days = 3` | daily |
| `truncated` | `site:date` | `v_coverage` | none | once |
| `expired` | `site:date` | `missing` dates before today's `oldest` | none | once |
| `expiry_warning` | `site` | the oldest `missing` date within `expiry_warn_days` of today's `oldest` | `expiry_warn_days = 14` | daily |
| `backup_stale` | `target` | the finish time of the last `ok` `backup` step in `runs` | `backup_max_hours = 48` | daily |
| `weekly_missing` | `weekly` | `now − max(last ok weekly job, meta.phase1_seen_at)` | `weekly_max_days = 8`, checked only when `general.phase >= 1` | daily |

#### C12. Trello client (`shrike/trello.py`)

Written fresh against Trello REST API v1. It doesn't copy Kestrel, whose Trello code wasn't reviewed for this plan.

`Trello(key, token, timeout=30)` has these methods:

| Method | Endpoint |
|---|---|
| `get_list(list_id)` | `GET /1/lists/{id}` |
| `create_card(list_id, name, desc) -> id` | `POST /1/cards` |
| `update_card(card_id, name, desc)` | `PUT /1/cards/{id}` |
| `get_card(card_id) -> {id, idList, closed, desc}` | `GET /1/cards/{id}` |
| `last_move_date(card_id, to_list_id) -> datetime` | `GET /1/cards/{id}/actions?filter=updateCard:idList` |
| `close_card(card_id)` | `PUT closed=true` |
| `delete_card(card_id)` | `DELETE` |

*   **Credentials.** The key and token are sent in the header `Authorization: OAuth oauth_consumer_key="<key>", oauth_token="<token>"`, never in the URL. Error text stored in `runs.error`, written to the journal or put on a card has any `key=` or `token=` value replaced with `***`.
*   **Errors.**
    *   401 raises `AuthError`.
    *   429 waits for `Retry-After` (default 10 s), up to 3 times.
    *   404 on a card means it was deleted. `sync_from_trello` treats that like a card closed before Done.
    *   A Done card with no `updateCard:idList` action uses the card's `dateLastActivity` as the move time.
*   `FakeTrello` has the same methods.

#### C13. Backups (`shrike/backup.py`)

*   The snapshot is written to `<data_dir>/tmp/`.
*   The file name is `shrike-YYYYMMDDTHHMMZ.sqlite.gz`, in UTC. The backup time used everywhere is parsed from this name.
*   Drive uploads use `MediaFileUpload(resumable=True, chunksize=8 MiB)`.
*   **Retention.** Keep the newest file of each of the last `keep_daily` UTC days, plus the newest file of each of the last `keep_monthly` UTC months. A file can satisfy both rules, so the kept set is the union of the two.
*   **Drive calls.** Every Drive call passes `supportsAllDrives=True`. Listing uses `files.list(q="'<folder_id>' in parents and trashed = false and name contains 'shrike-'", corpora="drive", driveId=<shared drive id>, includeItemsFromAllDrives=True, supportsAllDrives=True, fields="files(id,name)")`. The shared drive id is read once from `files.get(folder_id, fields="driveId")`.
*   **Prune.** In `gdrive` mode, prune moves files to the trash with `files.update(trashed=True)`, because a Content Manager can't permanently delete. In `local` mode it unlinks them.
*   **`verify_latest`.** For each site, it counts `final` and `truncated` rows in the backup's `v_coverage`. It passes when that count is at least the live count minus the number of `ok` pulls with `finished_at` after the backup's UTC time.

#### C14. Exit codes and systemd

*   **Exit codes:** 0 for OK, 10 for one or more steps failed and were alerted, 2 for a config error, and 3 for already running. A Python traceback exits 1, which isn't in `SuccessExitStatus`, so crashes always alert. `TimeoutStartSec=` is used, not `RuntimeMaxSec=`, because `RuntimeMaxSec=` has no effect on `Type=oneshot` units.
*   **Job units.**
    *   All job units set `SuccessExitStatus=10 3`, so `OnFailure=shrike-alert@%n.service` fires only for crashes, kills and exit 2.
    *   A nightly run skipped with exit 3 writes no `runs` row, but still pings the dead-man URL. The VM is alive and a writer is running, so a long backfill doesn't trigger a false email.
    *   If two starts race, `flock` decides. The loser exits 3 and logs "already running" to its journal, while the API has already answered 202.
    *   Because `shrike setup` also holds the writer lock, a job started during setup can exit 3 in the same way.
    *   **Hung writers.** `TimeoutStartSec=` is `12h` on `shrike-backfill.service` and `2h` on `shrike-nightly.service`, `shrike-weekly.service` and `shrike-setup.service`. A unit killed at the limit fails, so `OnFailure=shrike-alert@` fires and the lock is released. Without this, exit-3 pings could hide a stuck backfill for days.
*   **Unit sections.** Every timer has `[Install] WantedBy=timers.target`. `shrike.service` has `[Install] WantedBy=multi-user.target`.
*   **Timers.** `shrike render-units` writes `/etc/systemd/system/shrike-nightly.timer` and `/etc/systemd/system/shrike-weekly.timer` from `[schedule]` and `general.timezone`, for example `OnCalendar=*-*-* 03:30 Europe/Amsterdam`. These timer files aren't in the repo. `install.sh` runs it, and docs/OPERATIONS.md says to run it again (then `systemctl daemon-reload`) after changing the schedule.

### Target Files to Create/Modify

#### 1. `README.md` (Create) [P0]

*   **Type / Scope**: Documentation
*   **Proposed Changes**: Says what the tool does and doesn't do, using the Goals and Non-Goals above. Covers the quick start (install, config, env file, setup check, backfill, enable timers) and the route and MCP tool table. Links to `docs/SETUP.md` and `docs/OPERATIONS.md`, and states that the core costs $0 under the conditions in G6.

#### 2. `LICENSE` (Create) [P0]

*   **Type / Scope**: Legal
*   **Proposed Changes**: The MIT License, with copyright "Harshil Rekhi". This is decided here so the implementer doesn't have to choose.

#### 3. `requirements.txt` (Create) [P0]

*   **Type / Scope**: Dependencies
*   **Proposed Changes**: Only `google-auth`, `google-api-python-client` and `requests`. Each is pinned with `==` to its latest release on the day Phase 0 starts, and a comment says why it's there. It's installed into `/opt/shrike/venv`.

#### 3a. `requirements-dev.txt` (Create) [P0]

*   **Type / Scope**: Dev dependencies
*   **Proposed Changes**: Pinned `ruff` and `coverage`, for CI and local checks only.

#### 4. `pyproject.toml` (Create) [P0]

*   **Type / Scope**: Build configuration
*   **Proposed Changes**: The package metadata, `requires-python = ">=3.11"`, and the `shrike` package. It defines console scripts: `shrike` runs `shrike.jobs:main`, `shrike-server` runs `shrike.server:main`, and `shrike-mcp` runs `shrike.mcp_stdio:main`. It includes `shrike/migrations/*.sql` as package data. It also holds the `ruff` lint settings.

#### 5. `config.example.toml` (Create) [P0]

*   **Type / Scope**: Configuration template
*   **Proposed Changes**: Every setting, each with a comment and a default:
    *   `[general]`: `phase = 0` (set to 1 once Phase 1 is installed; this turns on the Trello sync, the weekly job and the weekly-missing check), `timezone`, `data_dir = "/var/lib/shrike"`, and `dead_man_url` (required for G5; the setup check warns if it's empty).
    *   `[pull]`: `pull_pause_seconds = 0.5`.
    *   `[health]`: `gap_days = 3`, `expiry_warn_days = 14`, `backup_max_hours = 48` and `weekly_max_days = 8`.
    *   `[[sites]]`: `name` (used in MCP calls and card titles) and `property`. There are two example entries.
    *   `[schedule]`: `nightly = "03:30"` and `weekly = "Mon 07:00"`.
    *   `[opportunities]`:
        *   the thresholds from the Technical Plan: `sd_min_pos = 5`, `sd_max_pos = 20`, `sd_min_impr = 100`, `lowctr_min_impr = 500`, `lowctr_ratio = 0.5`, `decay_drop = 0.30` and `decay_min_clicks = 50`,
        *   `bands = [[1,1],[2,2],[3,3],[4,5],[6,10],[11,20]]`, `expected_ctr_days = 90` and `expected_ctr_min_impr = 10`,
        *   `max_per_type = 4`, `brief_min = 5`, `brief_max = 10`, `expire_after_weeks = 3` and `resend_after_weeks = 8`.
    *   `[fixes]`: `window_days = 28`, `exclusion_before_days = 56`, `min_comparison_pages = 10` and `min_before_impressions = 100`.
    *   `[phase3]`: `monthly_cap_usd = 0`, which turns paid engines off. It's not used until Phase 3.
    *   `[trello]`: `board_id`, `inbox_list_id`, `done_list_id`, `alert_list_id`.
    *   `[backup]`: `target = "gdrive" | "local"`, `gdrive_folder_id`, `local_path`, `keep_daily = 30`, `keep_monthly = 12`.
    *   `[server]`: `host = "127.0.0.1"`, `port = 8899`.

#### 6. `.env.example` (Create) [P0]

*   **Type / Scope**: Secrets template
*   **Proposed Changes**: Placeholder names only: `SHRIKE_SERVICE_ACCOUNT_FILE`, `SHRIKE_TRELLO_KEY`, `SHRIKE_TRELLO_TOKEN`, `SHRIKE_API_KEY` (at least 24 characters), `SHRIKE_MCP_SECRET` (optional; at least 24 characters when set), `SHRIKE_CONFIG` and `SHRIKE_URL` (for `shrike-mcp`). C1 says which entry point needs which.

#### 7. `.gitignore` (Create) [P0]

*   **Type / Scope**: Repo hygiene
*   **Proposed Changes**: Ignores `config.toml`, `.env`, `*.json` key files, `*.sqlite*`, `venv/`, `__pycache__/` and backup files. This keeps real sites and secrets out of the public repo (G7).

#### 8. `shrike/__init__.py` (Create) [P0]

*   **Type / Scope**: Python package
*   **Proposed Changes**: Holds `__version__` and nothing else.

#### 9. `shrike/config.py` (Create) [P0]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `load_config(path) -> Config`: reads TOML with `tomllib`, applies defaults, and checks the values. Every error names the bad key and the expected form, for example `sites[1].property must start with "sc-domain:" or "https://"`.
    *   `load_secrets(entry) -> Secrets`: reads the variables that entry point needs (C1). It checks the modes of `SHRIKE_ENV_FILE` and the key file, and the length rules for `SHRIKE_API_KEY` and `SHRIKE_MCP_SECRET`. On failure it raises `ConfigError` with a fix step.
    *   Both results are immutable dataclasses.

#### 10. `shrike/errors.py` (Create) [P0]

*   **Type / Scope**: Python module
*   **Proposed Changes**: Defines `SkError(msg, status, fix_step)`, with subclasses `ConfigError`, `AuthError`, `QuotaError` and `UpstreamError`. Every error carries a `fix_step` string, which both the alerts and the setup check show.

#### 11. `shrike/migrations/001_init.sql` (Create) [P0]

*   **Type / Scope**: Database schema
*   **Proposed Changes**:
    *   Creates every table, view, index and trigger in C2, exactly as listed there.
    *   Indexes:
        *   `(site, date)` on every `gsc_*` table,
        *   `(site, page, date)` on the page tables,
        *   `(status)` on `opportunities`.
    *   `v_coverage` is the recursive-CTE view from C2, so dates that were never pulled show as `missing`.
    *   The triggers stop application code from updating or deleting final rows.

#### 12. `shrike/db.py` (Create) [P0]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `connect(path) -> sqlite3.Connection`: turns on WAL mode, foreign keys and `busy_timeout = 10000`.
    *   `connect_ro(path)`: opens the database with `mode=ro`, for the server.
    *   `migrate(conn)`: reads the migrations from `importlib.resources.files("shrike.migrations")`. If any `NNN_*.sql` is newer than `schema_version`, it first writes `snapshot(conn, <data_dir>/pre-migrate-<version>.sqlite)`, then runs the migrations in order, one transaction each. The 3 newest pre-migrate snapshots are kept.
    *   `store_final(conn, pull, rows)`: in one transaction, it inserts the `pulls` row (with `truncated`) and the rows into the matching table.
    *   `record_failed_pull(conn, pull, error)`: inserts a `status = 'error'` row.
    *   `set_range(conn, site, first_date=None, last_final_date=None)`: writes `site_range`. `first_date` is written only if it's empty.
    *   `snapshot(conn, dest_path)`: uses `sqlite3.Connection.backup`.

#### 13. `shrike/google_auth.py` (Create) [P0]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `credentials(secrets, scopes)`: builds service-account credentials with `google.oauth2.service_account`.
    *   `searchconsole(creds)` and `drive(creds)`: return API clients from `googleapiclient.discovery.build`, with `cache_discovery=False`.
    *   Scopes: `webmasters.readonly` and `drive`. `drive` is used because `drive.file` covers only files the app created, and the backup folder is created by a person. Access is limited by sharing the service account into that one folder only.
    *   It maps HTTP 401 and 403 to `AuthError`, with the fix step "add <service account email> as a Restricted user on <property>".

#### 14. `shrike/gsc.py` (Create) [P0]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `fetch_day(client, property, date, dimensions, data_state) -> FetchResult(rows, truncated)`:
        *   pages with `rowLimit = 25000` and `startRow`,
        *   stops when a page has fewer than 25,000 rows,
        *   sets `truncated` by the 50,000-row rule in C4.
    *   `dimensions` is one of `[]`, `["page"]` or `["page","query"]`. `type = "web"`, and `dataState` is `final` or `all`.
    *   Retries HTTP 429, the rate-limit 403s in C4, and 5xx up to 5 times, with exponential backoff (2, 4, 8, 16 and 32 s plus jitter). After that it raises `QuotaError` or `UpstreamError`. Other 401 and 403 responses raise `AuthError` (C4).
    *   The final-but-empty guard in C4.
    *   `first_incomplete_date(client, property) -> date`: runs one `dataState=all` query over the last 10 days, grouped by date, and reads `metadata.firstIncompleteDate` from the response. If the field is missing, it falls back to today minus 3 days, in US Pacific time.
    *   `available_range(client, property) -> (oldest, newest_final)`: `newest_final` is the day before `first_incomplete_date`, and `oldest` is `newest_final - 482 days` (C4). A zero-row day at that edge counts as complete, so low-traffic sites need no probing.
    *   Truncation and pacing follow C4.
    *   All dates are Search Console dates (US Pacific).

#### 15. `shrike/coverage.py` (Create) [P0]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `todo(conn, site, oldest) -> list[(date, dims)]`: every row in `v_coverage` for the site with state `missing` and date at or after today's `oldest`, oldest first. Both the backfill and nightly use it.
    *   `expired(conn, site, oldest) -> list[date]`: `v_coverage` `missing` rows with date before today's `oldest`. These can never be pulled now. The range starts at `site_range.first_date`, the fixed lower bound.
    *   `oldest_missing(conn, site) -> date | None`: used for the expiry alert.

#### 16. `shrike/opps.py` (Create) [P1]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `expected_ctr(rows_90d, bands, min_impr) -> dict[band, ctr]`: as defined in C5.
    *   `find(conn, site, cfg, end_date) -> list[Opportunity]`: runs the three rules (`striking_distance`, `low_ctr`, `decaying`) on the views, over 28 final days ending at `end_date`. Position is impression-weighted, and the score formulas are as in the Technical Plan.
    *   `opportunity_id(site, type, page, query)`: the SHA-256 of `site|type|page|query` (with an empty query for page-level types), cut to 16 hex characters.
    *   `upsert(conn, cfg, opps, trello, run_id)`:
        *   For detected IDs: updates `last_seen` and `score`, and resets `weeks_missing` to 0.
        *   A detected `dismissed` or `expired` ID becomes `new` again only if `status_changed_at` is at least `resend_after_weeks` old. Otherwise it stays as is.
        *   New IDs are inserted as `new`.
        *   For each `sent` ID not detected: `weeks_missing` goes up by 1. At `expire_after_weeks` it closes the card and sets the opportunity to `expired`.
    *   `select_for_brief(conn, cfg, run_id) -> list[Opportunity]`: the selection rule in C5.
    *   `refresh_open_cards(conn, trello, run_id)`: updates the card text of each `sent` opportunity detected in this run.
    *   Status changes always set `status_changed_at`. The resend rule in C5 uses that field, not `last_seen`.
    *   Each rule is a pure function of plain rows, so it can be tested without a database.

#### 17. `shrike/trello.py` (Create) [P0]

*   **Type / Scope**: Python module, written fresh (C12)
*   **Proposed Changes**:
    *   The `Trello` class, exactly as specified in C12: its methods, credential header, error scrubbing and error handling. It uses `requests`.

#### 18. `shrike/brief.py` (Create) [P1]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `build(conn, cfg) -> Brief`:
        *   the data-health header: last final date per site, gaps, truncated days, failed runs in 7 days, backup age, and a "Backups are on this machine; G1 not met" line when `backup.target = "local"`,
        *   `baseline.compare` for each site,
        *   the selected opportunities,
        *   the fixes measured this week, with the running total.
    *   `render_summary(brief) -> (title, markdown)` and `render_card(opp) -> (title, markdown)`.
    *   The fix text comes from one template per opportunity type, held in `shrike/templates.py`.
    *   `send(conn, brief, trello)`: creates the cards and stores each card ID on its opportunity, setting the status to `sent`. A card that fails to send leaves its opportunity `new` for the next run.

#### 19. `shrike/templates.py` (Create) [P1]

*   **Type / Scope**: Python module
*   **Proposed Changes**: Holds the `why` and `fix` templates for `striking_distance`, `low_ctr` and `decaying`, with named placeholders for the numbers, plus the card title formats in C5. They use no AI, and they follow the word ban in C5.

#### 20. `shrike/fixes.py` (Create) [P1]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `sync_from_trello(conn, trello, cfg)`: for each `sent` opportunity:
        *   **Card in `done_list_id`:** creates a `fixes` row and marks the opportunity `done`, which is final. The ship date is the `shipped: YYYY-MM-DD` line in the card description if there is one, otherwise `trello.last_move_date`.
        *   **Card closed and not in Done:** marks the opportunity `dismissed`.
        *   **`done` opportunities** are never read again, so archiving their cards changes nothing.
    *   `measure_due(conn, cfg, last_final_date) -> list[Result]`: measures unmeasured fixes where `ship_date + window_days <= last_final_date`.
    *   Each `Result` holds:
        *   the page's clicks and impressions in the before and after windows,
        *   the comparison group's size and median growth rate,
        *   `effect_clicks = clicks_before × (page_growth − group_median_growth)`,
        *   `included`, which is false when the group has fewer than `min_comparison_pages`, or the page had fewer than `min_before_impressions` or 0 clicks before. The reason is stored with it.
    *   Comparison group, windows, time zone, quartiles and zero-click handling: exactly as in C6.
    *   `running_total(conn) -> float`: the sum of `effect_clicks` over included results, in extra clicks per 28 days.

#### 21. `shrike/backup.py` (Create) [P0]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `run(conn, cfg, secrets)`: takes a snapshot to `<data_dir>/tmp/`, gzips it, then uploads it to the Shared Drive folder or copies it to `local_path`. The file name, upload and Drive call rules are in C13.
    *   `prune(cfg, secrets)`: the retention rule in C13 (trash in Drive mode, unlink in local mode).
    *   `verify_latest(cfg, secrets, conn)`:
        1.  Downloads the newest copy and unzips it to a temp file.
        2.  Runs `PRAGMA integrity_check`.
        3.  Runs the `v_coverage` count check in C13.
        4.  Deletes the temp file.
    *   `latest(cfg, secrets) -> datetime | None`: the newest backup's UTC time, parsed from its file name. `verify_latest` uses it. The `backup_stale` check uses `runs` instead (C11).
    *   Upload, retention and prune details follow C13. Prune moves files to the trash in Drive mode.
    *   `test_target(cfg, secrets) -> list[Check]`: used by the setup check.
        1.  Uploads a 1-byte file.
        2.  In `gdrive` mode, tries a permanent `files.delete(supportsAllDrives=True)` on it. It catches the expected 403 itself (reason `insufficientFilePermissions` or similar), which confirms the service account is a Content Manager, not a Manager.
        3.  Moves the file to the trash.
        4.  Reports `local` mode as "G1 not met".

#### 22. `shrike/health.py` (Create) [P0]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `step(ctx, job, name)`: the context manager in C11. It's used as `with health.step(ctx, job, name) as s:`, and `s.ok` reads the result afterwards.
    *   `alert(ctx, kind, subject, message, fix_step, once=False)`:
        *   Skips the alert if `events` already has the same `kind` and `subject`, either today or ever when `once=True`.
        *   Otherwise it creates a card in `alert_list_id`.
        *   If Trello itself fails, it writes the alert to stderr (the systemd journal) and records it with `delivered = 0`. It then increments `runs.undelivered_alerts` on the job row, which stops the dead-man ping.
    *   `checks(ctx) -> list[Problem]`: every row of the C11 table, with its kind, subject, source and threshold.
    *   `ping_dead_man(cfg)`: a GET to `dead_man_url`. It's called at the end of nightly, unless the run has an undelivered alert. A failed ping is logged and doesn't count as a job failure.

#### 22a. `shrike/baseline.py` (Create) [P0]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `freeze(conn, site, label="initial")`: it refuses (logs and returns) unless `v_gsc_site` has all 28 final days of the window. Otherwise, if no row exists for `site` and `label`, it sums the 28 final days ending at the newest final date from `v_gsc_site`, and inserts one `baselines` row. It never updates an existing row. The unique index makes a second insert fail.
    *   `compare(conn, site, end_date) -> Comparison`: returns the last 28 final days against the `initial` baseline, as numbers and percent, for the brief header and `/v1/sites`.

#### 23. `shrike/jobs.py` (Create) [P0]

*   **Type / Scope**: Python module and CLI entry point
*   **Proposed Changes**:
    *   For `backfill`, `nightly`, `weekly` and `setup`, `main()` takes `fcntl.flock(LOCK_EX | LOCK_NB)` on `<data_dir>/writer.lock` before any work. If the lock is held, it exits with code 3 and the message "already running".
    *   Each of those jobs runs `db.migrate` first.
    *   Subcommands, with each step wrapped in `health.step`:
        *   `backfill [--site NAME]`:
            1.  Calls `gsc.available_range` and `db.set_range(site, first_date=oldest, last_final_date=newest_final)` for each site. `first_date` is write-once, so only the first run sets it.
            2.  For each `(date, dims)` in `coverage.todo`, does one final pull through `db.store_final`, or `db.record_failed_pull` if it fails.
            3.  When `todo` is empty for a site, calls `baseline.freeze`.
            4.  Runs `backup.run` as its final step.
        *   `nightly`, in order:
            1.  Call `db.set_range` exactly as backfill step 1 does (so nightly also works on a fresh database), write `meta.phase1_seen_at` if `general.phase >= 1` and it's not set yet, then pull with `coverage.todo`.
            2.  Back up.
            3.  Sync Trello. This step runs only when `general.phase >= 1`. It's the only Phase 1 code nightly calls.
            4.  Run the health checks.
            5.  Ping the dead-man URL, unless `undelivered_alerts > 0`.
        *   `weekly` (Phase 1; exits with code 2 and "Phase 1 not enabled" when `general.phase = 0`), in order:
            1.  `opps.find` for each site.
            2.  `opps.upsert`.
            3.  `opps.refresh_open_cards`.
            4.  `fixes.measure_due`.
            5.  `opps.select_for_brief`.
            6.  `brief.build(conn, cfg, selected, measured)`.
            7.  `brief.send`.

            When the run date's day of month is 7 or less, in the configured time zone, it also runs `backup.verify_latest`.
        *   `render-units`: writes the two timer files from config (C14).
        *   `setup`: runs `setup_check.full_report`, prints it and saves it to `<data_dir>/setup_report.json`.
        *   `alert --unit NAME`: posts an alert card naming the failed systemd unit, with the fix step "run `journalctl -u NAME` and see docs/OPERATIONS.md". It takes no lock.
    *   Exit codes:
        *   0: OK,
        *   10: one or more steps failed and were alerted (1 is left to Python tracebacks, so crashes alert),
        *   2: config error,
        *   3: already running.

#### 24. `shrike/setup_check.py` (Create) [P0]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   `readonly_report(cfg, secrets, conn_ro) -> list[Check]`, used by `GET /v1/setup`. It reads the saved `setup_report.json` and adds the config, file-mode, secret length, dead-man URL and last-run checks. It writes nothing.
    *   `full_report(cfg, secrets, conn) -> list[Check]`, used only by `shrike setup`. Each `Check` follows C3. It checks:
    *   the config parses,
    *   the modes of the env file and key file,
    *   the MCP secret's length,
        *   that the service account can query each property, with a one-day site-totals query. A 403 fix step names the service-account email. A missing or unreadable key file points to docs/SETUP.md, which covers the `iam.disableServiceAccountKeyCreation` fallback.
    *   Trello can read each configured list, and the alert path works (it posts a test card to `alert_list_id`, then deletes it),
    *   `backup.test_target`,
    *   `dead_man_url` is set (a warning if not; G5 isn't met without it),
    *   the database migrates,
    *   when the last nightly and weekly runs happened.

    It plays the role of Kestrel's `kestrel_setup` (`evogr1/kestrel`, `scout_mcp.py`, since 1.4.1; the reference copy reviewed for this plan is older and doesn't have it).

#### 25. `shrike/routes.py` (Create) [P1]

*   **Type / Scope**: Python module
*   **Proposed Changes**:
    *   The `Route` and `Param` table from C7. Both the HTTP server and the MCP layers read it, so the HTTP API and the MCP tools can't drift apart.
    *   The routes, parameters and responses are exactly those in C7.
    *   `/v1/performance` parameters:
        *   `site` (required), `page`, `query`, `start` and `end` (Search Console dates, US Pacific),
        *   `compare` (`prev_period` or `prev_year`),
        *   `group_by` (`date`, `page` or `query`),
        *   `limit` (default 50, max 1,000) and `offset`.
    *   Each route entry has a `remote` flag. `POST /v1/jobs` (MCP tool `shrike_run_job`) has `remote = false`.

#### 26. `shrike/server.py` (Create) [P1]

*   **Type / Scope**: Python module (pattern copied from Kestrel's `scout_server.py`)
*   **Proposed Changes**:
    *   `make_server(cfg, api_key, mcp_secret)`: a `ThreadingHTTPServer` on the configured host and port.
    *   Auth, error handling, startup behavior and log masking follow C8.
    *   `POST /v1/jobs` with `job` set to `nightly`, `weekly` or `backfill`:
        1.  Reads `systemctl show -p ActiveState --value` for the three writer units, `shrike-nightly`, `shrike-weekly` and `shrike-backfill`. If any is `activating`, `active` or `deactivating`, it returns 409.
        2.  Otherwise it runs `systemctl start --no-block shrike-<job>.service` and returns 202 `{unit}`.
        3.  A race between the check and the start is settled by `flock` (C14).

        The polkit rule in `deploy/polkit/50-shrike.rules` allows the `shrike` user to start only those three units.
    *   `POST /mcp/<secret>`: compares the path secret with `hmac.compare_digest`, then passes the request to `mcp_remote.handle`. A wrong secret, or an empty `SHRIKE_MCP_SECRET`, returns 404. The HTTP limits are in C9.
    *   The database is opened through `db.connect_ro`. The server never writes to it.

#### 27. `shrike/mcp_stdio.py` (Create) [P1]

*   **Type / Scope**: Python module (pattern copied from Kestrel's `scout_mcp.py`)
*   **Proposed Changes**: A stdio JSON-RPC MCP server that behaves as described in C10. `tools/list` is built from `routes.py`, and `tools/call` forwards to `SHRIKE_URL` with `SHRIKE_API_KEY`. Tool names: `shrike_setup`, `shrike_sites`, `shrike_performance`, `shrike_opportunities`, `shrike_fixes`, `shrike_health` and `shrike_run_job`.

#### 28. `shrike/mcp_remote.py` (Create) [P1]

*   **Type / Scope**: Python module (pattern copied from Kestrel's `scout_remote_mcp.py`)
*   **Proposed Changes**: `handle(ctx, routes, msg)` implements C9 for requests that have already passed the server's path-secret check. `tools/list` and `tools/call` only include routes with `remote = true`, so `shrike_run_job` is never available remotely.

#### 29. `deploy/systemd/shrike.service` (Create) [P1]

*   **Type / Scope**: Deployment
*   **Proposed Changes**:
    *   Runs `/opt/shrike/venv/bin/shrike-server` with `User=shrike`, `EnvironmentFile=/etc/shrike/env`, `Environment=SHRIKE_ENV_FILE=/etc/shrike/env` and `Restart=on-failure`.
    *   Locked down with `ProtectSystem=strict`, `ReadWritePaths=/var/lib/shrike` (needed for SQLite's WAL side files, see C8) and `NoNewPrivileges=yes`.
    *   It's enabled by `install.sh --phase 1`.

#### 30. `deploy/systemd/shrike-nightly.service` and `deploy/systemd/shrike-nightly.timer` (Create) [P0]

*   **Type / Scope**: Deployment
*   **Proposed Changes**: The repo holds only the `.service` file. The `.timer` is generated (C14).
    *   The service is a oneshot running `/opt/shrike/venv/bin/shrike nightly`, with:
        *   `User=shrike`, `EnvironmentFile=/etc/shrike/env` and `Environment=SHRIKE_ENV_FILE=/etc/shrike/env`,
        *   `StateDirectory=shrike`, `StateDirectoryMode=0700`, `ProtectSystem=strict` and `NoNewPrivileges=yes`,
        *   `SuccessExitStatus=10 3`, `OnFailure=shrike-alert@%n.service` and `TimeoutStartSec=2h` (C14).
    *   The timer is generated by `shrike render-units` (C14), with `Persistent=true` (so a missed run happens at boot) and `RandomizedDelaySec=300`.

#### 31. `deploy/systemd/shrike-weekly.service` and `deploy/systemd/shrike-weekly.timer` (Create) [P1]

*   **Type / Scope**: Deployment
*   **Proposed Changes**: The repo holds only the `.service` file, with the same directives as the nightly service, word for word, running `shrike weekly`. The timer is generated from `[schedule].weekly` (C14).

#### 31c. `deploy/systemd/shrike-setup.service` (Create) [P0]

*   **Type / Scope**: Deployment
*   **Proposed Changes**: A oneshot running `shrike setup`, with the same directives as the nightly service, but no `OnFailure=`. `install.sh` starts it, so setup runs as `shrike` with the env file and the state directory. Files it creates are therefore owned by `shrike`.

#### 31a. `deploy/systemd/shrike-backfill.service` (Create) [P0]

*   **Type / Scope**: Deployment
*   **Proposed Changes**: A oneshot running `shrike backfill`, with the same directives as the nightly service except `TimeoutStartSec=12h`, and no timer. It's started by hand or through `POST /v1/jobs` with `job=backfill`, so a long backfill survives server restarts.

#### 31b. `deploy/polkit/50-shrike.rules` (Create) [P1]

*   **Type / Scope**: Deployment
*   **Proposed Changes**: A polkit rule that lets the `shrike` user run `systemctl start` on `shrike-nightly.service`, `shrike-weekly.service` and `shrike-backfill.service` only.

#### 32. `deploy/systemd/shrike-alert@.service` (Create) [P0]

*   **Type / Scope**: Deployment
*   **Proposed Changes**: A oneshot running `shrike alert --unit %i`, with the same `User`, `EnvironmentFile` and sandbox directives as the nightly service. It posts a Trello alert card when a job process crashed or was killed, or exited with code 2.

#### 33. `deploy/install.sh` (Create) [P0]

*   **Type / Scope**: Deployment script
*   **Proposed Changes**:
    Takes `--phase 0` or `--phase 1`. It's idempotent, and is run twice on a new install.

    **Every run:**

    1.  Creates the `shrike` user if missing, `/etc/shrike/` (`root:shrike` 750) and `/var/lib/shrike` (`shrike:shrike` 700). It expects the repo to be cloned at `/opt/shrike`.
    2.  Creates or updates the venv, then runs `pip install -r requirements.txt` and `pip install /opt/shrike`.
    3.  If they're missing, copies `config.example.toml` to `config.toml` (`root:shrike` 640) and creates an empty `env` (`root:root` 600). It never overwrites either.
    4.  Copies `shrike-nightly.service`, `shrike-backfill.service`, `shrike-setup.service` and `shrike-alert@.service`.
        *   With `--phase 1`, it also copies `shrike-weekly.service`, `shrike.service` and the polkit rule. It doesn't edit `config.toml`. If `general.phase` there isn't `1`, it prints "set general.phase = 1 in config.toml" and stops.
    5.  If `env` is still empty, prints "fill in /etc/shrike/env and config.toml, then run install.sh again" and stops.

    **Once `env` is filled in:**

    6.  Runs `shrike render-units` and `systemctl daemon-reload`.
    7.  Runs `systemctl start --wait shrike-setup.service`. If setup reports failures, it prints them and stops.
    8.  On the first successful run, starts `shrike-backfill.service`.
    9.  Enables the timers. Nightly runs that start during the backfill exit 3 and still ping.
    10. With `--phase 1`, enables and starts `shrike.service`.

#### 34. `docs/SETUP.md` (Create) [P0]

*   **Type / Scope**: Documentation
*   **Proposed Changes**: Step-by-step setup:
    1.  Create a Google Cloud project, turn on the Search Console and Drive APIs, and create a service account and key.
    2.  Add the service account as a Restricted user on each property.
        *   If the Workspace org policy `iam.disableServiceAccountKeyCreation` blocks the key, use a Google Cloud project under a personal Google account instead.
        *   Then invite that service account's email into the Shared Drive folder and the Search Console properties.
    3.  Create a Shared Drive folder, add the service account as **Content Manager** (not Manager), and copy the folder ID. There's also a "no Workspace" path, using `backup.target = "local"`, which is marked as not meeting G1.
    4.  Create the Trello key and token, and find the board and the three list IDs.
    5.  Create a free dead-man check (for example healthchecks.io, with a 26-hour period) and copy its ping URL.
    6.  Fill in the config and env file, run setup, run the backfill, and enable the timers.
    7.  Optional, for the remote MCP:
        *   Create a Cloudflare Tunnel with `cloudflared`, and route only the `/mcp/` path to `http://127.0.0.1:8899`.
        *   Don't put Cloudflare Access in front of `/mcp/`, because claude.ai connectors can't complete a Cloudflare Access login. The path secret is the gate.
        *   Proxied DNS into Caddy or nginx is the alternative.

#### 35. `docs/OPERATIONS.md` (Create) [P0]

*   **Type / Scope**: Documentation
*   **Proposed Changes**:
    *   How to restore from a backup (stop the server and timers, download, unzip, swap the database file, run `shrike setup`).
    *   How to roll back a release, and how to read alert cards.
    *   What each exit code means.
    *   How to keep an Oracle Always Free VM from being reclaimed.
        *   Oracle may reclaim an Always Free instance when, over 7 days, its 95th-percentile CPU, network and (on A1 shapes) memory use all stay under 20%.
        *   Two ways to avoid it: upgrade the account to Pay As You Go, which keeps Always Free resources free and isn't subject to idle reclamation, or host the tool on the same VM as Kestrel's daily jobs.
    *   How to re-run `shrike render-units` and `systemctl daemon-reload` after a schedule change.

#### 36. `tests/fakes.py` (Create) [P0]

*   **Type / Scope**: Test support
*   **Proposed Changes**:
    *   `FakeSearchConsole`: serves rows from fixture files, supports `startRow` paging, and can be set to return 429, 401 or a partial page.
    *   `FakeTrello`: an in-memory set of lists and cards, with move and close.
    *   `FakeDrive`: an in-memory file store.

    No test calls a real API.

#### 37. `tests/fixtures/` (Create) [P0]

*   **Type / Scope**: Test data
*   **Proposed Changes**: Small JSON files of Search Console responses for two fake sites over 120 days. The data is built so each opportunity rule fires a known number of times, and there are pages with and without a fix.

#### 38. `tests/test_config.py` (Create) [P0]

*   **Type / Scope**: Unit tests
*   **Proposed Changes**:
    *   A valid example config loads.
    *   Each bad key gives an error that names it.
    *   A key file with mode 644 is refused, with its fix step.

#### 39. `tests/test_db.py` (Create) [P0]

*   **Type / Scope**: Unit tests
*   **Proposed Changes**:
    *   Migrations run in order on an empty database and are skipped when already applied.
    *   A failing migration leaves the schema version unchanged, and a pre-migrate snapshot exists.
    *   `v_coverage` reports `missing` for a date that was never pulled, and `final` and `truncated` per dimension set.
    *   A zero-row successful pull reports `final`.
    *   An `UPDATE` or `DELETE` on a final `gsc_*` table fails because of the trigger.

#### 40. `tests/test_gsc.py` (Create) [P0]

*   **Type / Scope**: Unit tests
*   **Proposed Changes**:
    *   Paging stops on a short page.
    *   429 is retried and then raises `QuotaError`.
    *   401 raises `AuthError`, with the service-account fix step.
    *   A pull of 50,000 rows sets `truncated`, and a pull of exactly 25,000 doesn't (C4).
    *   `first_incomplete_date` reads the metadata field, and falls back when the field is missing.

#### 41. `tests/test_jobs.py` (Create) [P0]

*   **Type / Scope**: Integration tests with fakes
*   **Proposed Changes**:
    *   The backfill pulls the oldest date first.
    *   A backfill stopped halfway resumes without re-pulling final days.
    *   A zero-row day counts as complete.
    *   A completed backfill writes exactly one `initial` baseline per site, and running it again doesn't change that row.
    *   Nightly pulls exactly the dates `v_coverage` marks `missing` (the newly final date plus an injected gap), never re-pulls a final date, and writes `runs` rows per step.
    *   All three dimension sets are pulled for each new date.
    *   With `general.phase = 0`, nightly skips the Trello sync, and no weekly-missing alert fires.
    *   The backfill ends with a backup.
    *   On a fresh database, the backfill sets both `first_date` and `last_final_date`, pulls every date, and freezes a baseline only once 28 final days exist.
    *   A final site-totals pull that returns 0 rows while the probe shows impressions is recorded as an error and retried the next night.
    *   A nightly run skipped with exit 3 still pings.
    *   A writer that exceeds `TimeoutStartSec` (simulated by a fake unit-runner timeout) releases `writer.lock`, and the next nightly run proceeds normally.
    *   `weekly_missing` uses `meta.phase1_seen_at` before the first weekly run.
    *   A Trello failure in nightly still lets the backup step run, and stops the dead-man ping.
    *   A failure in nightly creates one alert card and only one, even if run twice the same day.
    *   While `nightly` holds `writer.lock`, a `weekly` or `backfill` start exits with code 3.
    *   An interrupted backfill that has stored only 1 of a date's 3 dimension sets pulls the other 2 on resume.
    *   A truncated day alerts once across repeated nightly runs, and doesn't stop the dead-man ping.
    *   `shrike alert --unit X` posts one card naming X.

#### 42. `tests/test_opps.py` (Create) [P1]

*   **Type / Scope**: Unit tests
*   **Proposed Changes**:
    *   Each rule fires on its fixture rows and not on rows just outside the thresholds.
    *   IDs are stable across runs.
    *   Open-card opportunities aren't re-selected.
    *   `max_per_type` is respected.
    *   A `sent` opportunity missing for 3 weekly runs has its card closed and is marked expired.
    *   A `dismissed` or `expired` opportunity is re-sent only after 8 weeks.
    *   Expected CTR per band matches a hand-computed fixture.

#### 43. `tests/test_brief.py` (Create) [P1]

*   **Type / Scope**: Unit tests
*   **Proposed Changes**:
    *   The summary card has the data-health header with the correct last final date and gaps.
    *   A card that fails to send leaves its opportunity `new`.
    *   No card text contains "FAQ rich result" or "llms.txt".

#### 44. `tests/test_fixes.py` (Create) [P1]

*   **Type / Scope**: Unit tests
*   **Proposed Changes**:
    *   A card moved to Done creates a fix with the move date, or with the `shipped:` date when one is present.
    *   A `done` card later archived stays `done`.
    *   Measurement waits until 28 final days after the ship date exist.
    *   The comparison group excludes pages with a fix from 56 days before the ship date to the end of the after window, and uses impression quartiles.
    *   `effect_clicks` matches the worked example (400 clicks before, +25% against +5% gives 80).
    *   A group with fewer than 10 pages, or a page with fewer than 100 impressions or 0 clicks before, is marked not included.
    *   The running total sums only included results.

#### 45. `tests/test_backup.py` (Create) [P0]

*   **Type / Scope**: Unit tests
*   **Proposed Changes**:
    *   A snapshot taken while writes are happening restores to an intact database.
    *   Pruning a simulated 400-day history with one backup a day keeps exactly the union of the last 30 days' files and the newest file of each of the last 12 months: 30 + 11 = 41 files (the current month's newest file is already among the 30).
    *   Every Drive call made through the fake carries `supportsAllDrives=True`.
    *   `verify_latest` raises an alert on a corrupted file, or on a file whose coverage counts are behind by more than the dates added since it was taken.
    *   The local target works without Google credentials, and is reported as "G1 not met".
    *   `test_target` reports a failure when the fake Drive allows a permanent delete.

#### 46. `tests/test_server.py` (Create) [P1]

*   **Type / Scope**: Integration tests
*   **Proposed Changes**:
    *   A missing or wrong API key returns 401.
    *   Each route returns the documented fields from a fixture database.
    *   A job POST calls `systemctl start --no-block` (mocked) for the right unit. It returns 409 when the mocked `systemctl show -p ActiveState` reports `activating` for a writer unit.
    *   With no `-wal` or `-shm` file present, a request opens the database read-only and succeeds.
    *   Two concurrent requests each get their own connection.
    *   A missing API key returns 401 before any 404.
    *   `GET /v1/setup` makes no Trello, Drive or SQLite writes.
    *   The local MCP `tools/list` matches `routes.py`.
    *   Remote MCP returns 404 for a wrong secret, and never lists `shrike_run_job`.
    *   The request log never contains the MCP secret.
    *   A write attempted through the server's database connection fails.

#### 46a. `tests/test_support.py` (Create) [P0]

*   **Type / Scope**: Unit tests for the smaller modules
*   **Proposed Changes**:
    *   **health:** alert dedupe (daily and once), and an undelivered alert blocking the dead-man ping. Every C11 kind fires on its fixture.
    *   **baseline:** `compare` numbers and percentages.
    *   **setup_check:** `readonly_report` makes no writes (it uses a read-only connection, plus fake Trello and fake Drive with call counters).
    *   **trello:** 401 raises `AuthError`, and 429 retries after `Retry-After`. The key and token go in the `Authorization` header. A failing call's stored error contains neither.
    *   **gsc:** a 403 with `rateLimitExceeded` is retried, while a 403 with another reason raises `AuthError`.
    *   **mcp_stdio:** a notification gets no reply, and an unknown tool returns -32602.
    *   **mcp_remote:** `initialize` version negotiation, a notification returning `None`, a batch, `ping`, and the -32601 and -32602 errors.
    *   **config:** the secret length rules for each entry point.
    *   **coverage:** the expired-date alert fires once, and the expiry warning fires 14 days before.

#### 47. `.github/workflows/test.yml` (Create) [P0]

*   **Type / Scope**: CI configuration
*   **Proposed Changes**: On every push and pull request, on Python 3.11 and 3.13, it:
    *   installs `requirements.txt` and `requirements-dev.txt`,
    *   runs `ruff check shrike tests`,
    *   runs `coverage run -m unittest discover -s tests`,
    *   runs `coverage report --fail-under=85 --include=shrike/opps.py,shrike/fixes.py,shrike/gsc.py,shrike/coverage.py,shrike/backup.py`.

    It has no secrets and makes no network calls.

### Verification Plan

*   **Compilation/Build**: `pip install -r requirements.txt && pip install -e .`, then `shrike --help`, `shrike-server --help` and `shrike-mcp --help` all start without errors.
*   **Unit Tests**: `python -m unittest discover -s tests`. All tests pass with no network access.
*   **Static Analysis & Linting**: `ruff check shrike tests` reports no errors.
*   **Test Coverage Requirement**: 85% or more line coverage on `shrike/opps.py`, `shrike/fixes.py`, `shrike/gsc.py`, `shrike/coverage.py` and `shrike/backup.py`, measured with `coverage run -m unittest` in CI. These modules hold the logic that could quietly lose data or report wrong results.
*   **E2E/Integration (live, run once by the author before Phase 1 is accepted)**:
    1.  `shrike setup` reports every check OK for both sites.
    2.  `shrike-backfill.service` finishes. `GET /v1/sites` then shows `missing_days = 0` for both sites.
    3.  A manual `shrike nightly` uploads a backup. `backup.verify_latest` then passes on it, and a manual restore to a second path opens with matching row counts.
    4.  A manual `shrike weekly` posts a summary card and 5 to 10 fix cards to the Trello board.
    5.  Two failure tests:
        *   Revoke the Trello token and run nightly. The backup step still runs, the failure is written to the journal, no dead-man ping is sent, and the dead-man service emails within its window.
        *   Revoke the service account's Search Console access. With Trello working, this produces an alert card.
    6.  Through the local stdio MCP, `shrike_performance` for evogr, over the 28 days ending at `last_final_date`, returns a click total within 1% or 5 clicks (whichever is larger) of the Search Console web interface for the same dates.
    7.  Add the remote connector in claude.ai (the tunnel URL with `/mcp/<secret>`), and call `shrike_health`. It answers, and `shrike_run_job` isn't listed.
*   **Success metrics (tracked after launch)**:
    *   G2: 4 weeks in a row without opening Search Console by hand.
    *   G3: an average of 3 or more Done cards per week over the first 8 weeks.
    *   G4: the running total of measured gains, reported in every brief.

--------------------------------------------------------------------------------

*Drafted with EGM*
