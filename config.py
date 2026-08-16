#!/usr/bin/env python3
"""Configuration for the STAR TeamTalk bot.

NO REAL SECRETS ARE STORED HERE. The example password below is a deliberate
placeholder ("troll") -- never commit a real account password. Override it via
the STAR_TT_PASSWORD environment variable or a gitignored config.local.py.

Environment variables (all optional; sensible placeholders provided):
  STAR_TT_HOST        TeamTalk server hostname        (default: tt-server.com)
  STAR_TT_TCP_PORT    TeamTalk TCP port               (default: 10443)
  STAR_TT_UDP_PORT    TeamTalk UDP port               (default: 10443)
  STAR_TT_NICKNAME    Bot display nickname            (default: starbot)
  STAR_TT_USERNAME    TeamTalk account username       (default: star)
  STAR_TT_PASSWORD    TeamTalk account password       (default: <placeholder>)
  STAR_TT_CHANNEL     Channel path to join            (default: /hangout area/)
  STAR_TT_CHAN_PASS   Channel password                (default: empty)
  STAR_TT_ENCRYPTED   "1"/"true" to use encrypted     (default: false)
  STAR_TT_STATUS      Bot status message             (default: see below)
  STAR_COAG_URI       STAR coagulator websocket URI   (default: wss://star.blindsoft.net)

You may also drop a `config.local.py` next to this file with a `CONFIG = {...}`
dict to override any of the keys below. That file is gitignored.
"""
import os


def _env(name, default=None):
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v


def _bool(name, default=False):
    v = _env(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


DEFAULT_STATUS = (
    "This bot allows you to use STAR (Speech To Audio Relay) made by Sam Tupy. "
    "To see the Star Bot project, go to: https://github.com/averlice/sb"
)

CONFIG = {
    # TeamTalk server connection (non-secret)
    "host": _env("STAR_TT_HOST", "tt-server.com"),
    "tcp_port": int(_env("STAR_TT_TCP_PORT", "10443")),
    "udp_port": int(_env("STAR_TT_UDP_PORT", "10443")),
    "nickname": _env("STAR_TT_NICKNAME", "starbot"),
    "status": _env("STAR_TT_STATUS", DEFAULT_STATUS),

    # Credentials -- username is not secret, but the password MUST come from
    # the environment. The default below is a deliberate placeholder, NOT a
    # real password.
    "username": _env("STAR_TT_USERNAME", "star"),
    "password": _env("STAR_TT_PASSWORD", "i'm_nt_giving_you_my_password"),

    "channel_path": _env("STAR_TT_CHANNEL", "/hangout area/"),
    "channel_password": _env("STAR_TT_CHAN_PASS", ""),
    "encrypted": _bool("STAR_TT_ENCRYPTED", False),

    # STAR coagulator websocket URI.
    "star_uri": _env("STAR_COAG_URI", "wss://star.blindsoft.net"),

    # Only respond to private messages sent directly to the bot.
    "pm_only": True,
}

# Optional local overrides (gitignored). This keeps your real account out of
# version control entirely.
try:
    from . import config_local  # type: ignore
    if hasattr(config_local, "CONFIG"):
        CONFIG.update(config_local.CONFIG)
except Exception:
    pass
