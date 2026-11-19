"""Error types. Every error carries a one-line fix step for alerts and the setup check."""


class SkError(Exception):
    status = 500

    def __init__(self, msg, fix_step=None, status=None):
        super().__init__(msg)
        self.fix_step = fix_step
        if status is not None:
            self.status = status


class ConfigError(SkError):
    status = 400


class AuthError(SkError):
    status = 502


class QuotaError(SkError):
    status = 503


class UpstreamError(SkError):
    status = 502
