"""Load and check config.toml and the environment secrets (design C1, C3)."""

import os
import stat
import tomllib
from dataclasses import dataclass, field

from .errors import ConfigError

DEFAULT_CONFIG = "/etc/search-kestrel/config.toml"


@dataclass(frozen=True)
class Site:
    name: str
    property: str


@dataclass(frozen=True)
class Config:
    phase: int
    timezone: str
    data_dir: str
    dead_man_url: str
    sites: tuple
    nightly: str
    weekly: str
    pull_pause_seconds: float
    gap_days: int
    expiry_warn_days: int
    backup_max_hours: int
    weekly_max_days: int
    trello_board_id: str
    trello_inbox_list_id: str
    trello_done_list_id: str
    trello_alert_list_id: str
    backup_target: str
    gdrive_folder_id: str
    local_path: str
    keep_daily: int
    keep_monthly: int
    monthly_cap_usd: float = 0.0
    path: str = ""

    @property
    def db_path(self):
        return os.path.join(self.data_dir, "data.sqlite")

    def site(self, name):
        for s in self.sites:
            if s.name == name:
                return s
        raise ConfigError(f"unknown site {name!r}", f"use one of: {', '.join(s.name for s in self.sites)}")


@dataclass(frozen=True)
class Secrets:
    service_account_file: str = ""
    trello_key: str = ""
    trello_token: str = ""
    api_key: str = ""
    mcp_secret: str = ""
    env_file: str = ""
    extra: dict = field(default_factory=dict)


def _get(d, key, typ, default=None, required=False, where=""):
    if key not in d:
        if required:
            raise ConfigError(f"{where}{key} is missing", f"add {where}{key} to config.toml")
        return default
    v = d[key]
    if typ is float and isinstance(v, int):
        v = float(v)
    if not isinstance(v, typ) or (typ is int and isinstance(v, bool)):
        raise ConfigError(f"{where}{key} must be {typ.__name__}", f"fix {where}{key} in config.toml")
    return v


def load_config(path=None):
    path = path or os.environ.get("SK_CONFIG") or DEFAULT_CONFIG
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"config not found: {path}", "copy config.example.toml to that path") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config.toml is not valid TOML: {e}", "fix the syntax error shown") from e

    g = raw.get("general", {})
    sch = raw.get("schedule", {})
    pull = raw.get("pull", {})
    h = raw.get("health", {})
    t = raw.get("trello", {})
    b = raw.get("backup", {})
    p3 = raw.get("phase3", {})

    sites = []
    for i, s in enumerate(raw.get("sites", [])):
        where = f"sites[{i}]."
        name = _get(s, "name", str, required=True, where=where)
        prop = _get(s, "property", str, required=True, where=where)
        if not (prop.startswith("sc-domain:") or prop.startswith("https://") or prop.startswith("http://")):
            raise ConfigError(
                f'{where}property must start with "sc-domain:" or "https://"',
                f"copy the property string from Search Console into {where}property",
            )
        sites.append(Site(name, prop))
    if not sites:
        raise ConfigError("no [[sites]] configured", "add at least one [[sites]] block to config.toml")
    if len({s.name for s in sites}) != len(sites):
        raise ConfigError("site names must be unique", "give each [[sites]] block a different name")

    phase = _get(g, "phase", int, 0, where="general.")
    if phase not in (0, 1):
        raise ConfigError("general.phase must be 0 or 1", "set general.phase = 0 or 1")
    target = _get(b, "target", str, "gdrive", where="backup.")
    if target not in ("gdrive", "local"):
        raise ConfigError('backup.target must be "gdrive" or "local"', 'set backup.target = "gdrive" or "local"')
    tz = _get(g, "timezone", str, "UTC", where="general.")
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz)
    except Exception as e:
        raise ConfigError(f"general.timezone {tz!r} is not a known time zone", "use an IANA name such as Europe/Amsterdam") from e
    for key, val in (("schedule.nightly", sch.get("nightly", "03:30")),):
        _check_hhmm(key, val)
    weekly = _get(sch, "weekly", str, "Mon 07:00", where="schedule.")
    parts = weekly.split()
    if len(parts) != 2 or parts[0] not in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
        raise ConfigError('schedule.weekly must look like "Mon 07:00"', 'set schedule.weekly = "Mon 07:00"')
    _check_hhmm("schedule.weekly", parts[1])

    return Config(
        phase=phase,
        timezone=tz,
        data_dir=_get(g, "data_dir", str, "/var/lib/search-kestrel", where="general."),
        dead_man_url=_get(g, "dead_man_url", str, "", where="general."),
        sites=tuple(sites),
        nightly=_get(sch, "nightly", str, "03:30", where="schedule."),
        weekly=weekly,
        pull_pause_seconds=_get(pull, "pull_pause_seconds", float, 0.5, where="pull."),
        gap_days=_get(h, "gap_days", int, 3, where="health."),
        expiry_warn_days=_get(h, "expiry_warn_days", int, 14, where="health."),
        backup_max_hours=_get(h, "backup_max_hours", int, 48, where="health."),
        weekly_max_days=_get(h, "weekly_max_days", int, 8, where="health."),
        trello_board_id=_get(t, "board_id", str, "", where="trello."),
        trello_inbox_list_id=_get(t, "inbox_list_id", str, "", where="trello."),
        trello_done_list_id=_get(t, "done_list_id", str, "", where="trello."),
        trello_alert_list_id=_get(t, "alert_list_id", str, "", where="trello."),
        backup_target=target,
        gdrive_folder_id=_get(b, "gdrive_folder_id", str, "", where="backup."),
        local_path=_get(b, "local_path", str, "/var/lib/search-kestrel/backups", where="backup."),
        keep_daily=_get(b, "keep_daily", int, 30, where="backup."),
        keep_monthly=_get(b, "keep_monthly", int, 12, where="backup."),
        monthly_cap_usd=_get(p3, "monthly_cap_usd", float, 0.0, where="phase3."),
        path=path,
    )


def _check_hhmm(key, val):
    try:
        hh, mm = val.split(":")
        assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60 and len(mm) == 2
    except Exception as e:
        raise ConfigError(f'{key} must be "HH:MM"', f'set {key} like "03:30"') from e


def _check_private(path, label):
    try:
        st = os.stat(path)
    except FileNotFoundError as e:
        raise ConfigError(f"{label} not found: {path}", f"create {path} (see docs/SETUP.md)") from e
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError(
            f"{label} {path} can be read by group or others (mode {stat.S_IMODE(st.st_mode):o})",
            f"run: chmod 600 {path}",
        )


# Which secrets each entry point needs (design C1).
NEEDS = {
    "jobs": ("service_account", "trello"),
    "alert": ("trello",),
    "render-units": (),
    "server": ("api_key",),
    "mcp": ("api_key",),
}


def load_secrets(entry="jobs", env=None):
    env = os.environ if env is None else env
    need = NEEDS[entry]
    env_file = env.get("SK_ENV_FILE", "")
    if env_file and need:
        _check_private(env_file, "env file")
    sec = Secrets(
        service_account_file=env.get("SK_SERVICE_ACCOUNT_FILE", ""),
        trello_key=env.get("SK_TRELLO_KEY", ""),
        trello_token=env.get("SK_TRELLO_TOKEN", ""),
        api_key=env.get("SK_API_KEY", ""),
        mcp_secret=env.get("SK_MCP_SECRET", ""),
        env_file=env_file,
    )
    if "service_account" in need:
        if not sec.service_account_file:
            raise ConfigError("SK_SERVICE_ACCOUNT_FILE is not set", "set it in /etc/search-kestrel/env")
        _check_private(sec.service_account_file, "service-account key file")
    if "trello" in need and not (sec.trello_key and sec.trello_token):
        raise ConfigError(
            "SK_TRELLO_KEY and SK_TRELLO_TOKEN are required (Phase 0 alerts are Trello cards)",
            "set both in /etc/search-kestrel/env",
        )
    if "api_key" in need and len(sec.api_key) < 24:
        raise ConfigError("SK_API_KEY must be at least 24 characters", "generate one: openssl rand -hex 24")
    if entry == "server" and sec.mcp_secret and len(sec.mcp_secret) < 24:
        raise ConfigError("SK_MCP_SECRET must be at least 24 characters when set", "generate one: openssl rand -hex 24")
    return sec
