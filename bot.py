#!/usr/bin/env python3
"""STAR coagulator -> TeamTalk streaming bot.

PM-only: only responds to private messages sent directly to the bot.

Commands (private message to the bot):
  /coag <ws://user:pass@host:port>   Connect to a STAR coagulator over websockets.
  /coagulator <uri>                   Alias of /coag.
  /coag stop                          Disconnect from the coagulator.
  /voices                             List voices available on the connected coagulator.
  /voice <name>                       Select the active voice (e.g. /voice sam).
  /rate <n>                           Set speech rate (e.g. /rate 200; injected as [[rate n]]).
  /pitch <n>                          Set speech pitch (e.g. /pitch 80; injected as [[pbas n]]).
  /stop                               Stop the current streaming speech.
  /help                               Show this command list.

Switching voices resets rate/pitch to defaults (values are per-voice).

Any private message that does NOT start with a slash is spoken aloud in the
channel, announced as "<nickname> (<username>) said: <message>".
For example, PMing the bot "hello there" makes it speak:
  "you're a sussy baka (averlice) said: hello there".
"""
import os
import logging
import subprocess
import tempfile
import sys

# --- Make the locally installed TeamTalk5.dll loadable on Windows ---
_TT_DLL_DIR = r"C:\Program Files\TeamTalk5"
if os.name == "nt" and os.path.isdir(_TT_DLL_DIR):
    os.add_dll_directory(_TT_DLL_DIR)
    os.environ["PATH"] = _TT_DLL_DIR + os.pathsep + os.environ.get("PATH", "")

# --- Vendored TeamTalk SDK wrapper -------------------------------------
# The upstream `teamtalk` PyPI package tries to auto-download a paywalled SDK
# from bearware.dk on import (when its bundled wrapper is missing). We ship the
# wrapper we already have in `_tt_vendor/TeamTalkPy` and register it in
# sys.modules BEFORE importing `teamtalk`, so the import succeeds offline and
# never triggers the download. (The native TeamTalk5.dll still must be installed
# separately -- see README.)
_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR_TT = os.path.join(_HERE, "_tt_vendor", "TeamTalkPy")

# Only pre-register if the upstream wrapper is NOT already present in the
# installed teamtalk package (i.e. a fresh `uv sync` without the SDK download).
try:
    import importlib.util as _ilu
    _tt_spec = _ilu.find_spec("teamtalk")
    _has_upstream = False
    if _tt_spec and _tt_spec.submodule_search_locations:
        _upstream_impl = os.path.join(
            _tt_spec.submodule_search_locations[0],
            "implementation", "TeamTalkPy", "__init__.py",
        )
        _has_upstream = os.path.isfile(_upstream_impl)
except Exception:
    _has_upstream = False

if not _has_upstream and os.path.isfile(os.path.join(_VENDOR_TT, "__init__.py")):
    _spec = _ilu.spec_from_file_location(
        "teamtalk.implementation.TeamTalkPy",
        os.path.join(_VENDOR_TT, "__init__.py"),
    )
    _mod = _ilu.module_from_spec(_spec)
    sys.modules["teamtalk.implementation.TeamTalkPy"] = _mod
    _spec.loader.exec_module(_mod)
    log_init = logging.getLogger("star_tt_bot")
    log_init.info("Using vendored TeamTalk SDK wrapper (offline).")

import teamtalk
from teamtalk.enums import UserStatusMode
from teamtalk.implementation.TeamTalkPy import TeamTalk5 as sdk
import star_client as _sc
StarCoagulator = _sc.StarCoagulator

log = logging.getLogger("star_tt_bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Message types
MSGTYPE_USER = int(sdk.TextMsgType.MSGTYPE_USER)      # private message
MSGTYPE_CHANNEL = int(sdk.TextMsgType.MSGTYPE_CHANNEL)

# "No video track" codec value for audio-only streaming
NOVIDEOFORMAT = 0

# Client event constants
CLIENTEVENT_CMD_MYSELF_LOGGEDIN = int(sdk.ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDIN)
CLIENTEVENT_CMD_USER_TEXTMSG = int(sdk.ClientEvent.CLIENTEVENT_CMD_USER_TEXTMSG)
CLIENTEVENT_CON_LOST = int(sdk.ClientEvent.CLIENTEVENT_CON_LOST)


class StarTeamTalkBot:
    def __init__(self, host, tcp_port, udp_port, nickname, username, password,
                 channel_path, channel_password="", encrypted=False,
                 client_name="STAR-TT-Bot", pm_only=True, status=""):
        self.host = host
        self.tcp_port = int(tcp_port)
        self.udp_port = int(udp_port)
        self.nickname = nickname
        self.username = username
        self.password = password
        self.channel_path = channel_path
        self.channel_password = channel_password
        self.encrypted = encrypted
        self.client_name = client_name
        self.pm_only = pm_only
        self.status = status

        self.tt = sdk.TeamTalk()
        self.coag = StarCoagulator()

        self.active_voice = None
        self.rate = 0.0    # 0 = unset; when set, injected as [[rate N]]
        self.pitch = 0.0   # 0 = unset; when set, injected as [[pbas N]]

        self._stream_lock = threading.Lock() if False else __import__("threading").Lock()
        self._streaming = False
        self._temp_files = []
        self.running = True

    # ---- lifecycle -------------------------------------------------------
    def connect(self):
        log.info("Connecting to TeamTalk server %s:%d (udp %d, encrypted=%s)",
                 self.host, self.tcp_port, self.udp_port, self.encrypted)
        ok = self.tt.connect(self.host, self.tcp_port, self.udp_port,
                             nLocalTcpPort=0, nLocalUdpPort=0, bEncrypted=self.encrypted)
        if not ok:
            err = self._safe_last_error()
            raise RuntimeError(f"TeamTalk connect() failed for {self.host}:{self.tcp_port}"
                               + (f" (server error {err})" if err else ""))
        log.info("TCP/UDP connection established. Logging in as nickname=%r username=%r",
                 self.nickname, self.username)
        self._login_and_sync()
        log.info("Logged in (%d channels visible). Joining '%s'",
                 len(self._channel_tree), self.channel_path)
        self._join_channel()
        if self.tt.getMyChannelID() > 0:
            log.info("Joined channel id=%d. Bot is live (PM-only=%s).",
                     self.tt.getMyChannelID(), self.pm_only)
        else:
            log.warning("Could not join '%s'; staying unjoined. Commands still work via PM.",
                        self.channel_path)

    def _safe_last_error(self):
        """Best-effort fetch of the SDK's last error string, for diagnostics."""
        try:
            code = self.tt.getLastError()
            if code:
                return f"{code}: {getattr(self.tt, 'getErrorMessage', lambda c: '') (code)}"
        except Exception:
            pass
        return ""

    def _login_and_sync(self, timeout=20):
        """Log in and pump events until we are logged in AND have the channel
        tree. The server pushes the channel list as CMD_CHANNEL_NEW events that
        arrive right around the login event, so we must keep pumping (not stop
        at the first login event) or the channel tree is lost and
        getChannelIDFromPath() finds nothing.

        If the account is already logged in elsewhere the server rejects with
        CMDERR_ALREADY_LOGGEDIN (3001); we retry with backoff so the bot
        self-heals once the other session logs out. Any OTHER login error
        (bad account, not authorized, banned, etc.) is reported immediately
        with the server's actual error code instead of a generic timeout.
        """
        import time
        self._channel_tree = {}
        deadline = time.time() + timeout
        logged_in = False
        do_login_calls = 0
        do_login_rejected = 0
        last_error = None          # most recent non-zero CMD_ERROR (code, msg)
        seen_events = []           # diagnostic trail of event codes
        con_lost = False

        def _note(ev, extra=""):
            seen_events.append((ev, extra))
            if len(seen_events) > 40:
                seen_events.pop(0)

        while time.time() < deadline:
            do_login_calls += 1
            if not self.tt.doLogin(self.nickname, self.username, self.password, self.client_name):
                do_login_rejected += 1
                log.warning("doLogin() returned False (attempt %d)", do_login_calls)
                # doLogin returned False -> find out why from the server
                err = self._wait_login_error(3)
                if err is not None:
                    code, msg = err
                    last_error = (code, msg)
                    if code == 3001:  # CMDERR_ALREADY_LOGGEDIN
                        log.warning("Account already logged in elsewhere (code 3001); retrying in 5s...")
                        _note(3001, msg)
                        time.sleep(5)
                        continue
                    log.error("Login REJECTED by server: code %s (%s). Check username/password/account.",
                              code, msg)
                    raise RuntimeError(
                        f"Login rejected by server (code {code}: {msg}). "
                        f"Check username/password and server account status.")
                # no explicit error event; treat as transient and retry
                _note(-1, "doLogin False, no error event")
                log.warning("doLogin False but no server error event within 3s; retrying...")
                time.sleep(3)
                continue
            log.info("doLogin() accepted (attempt %d); pumping for confirmation...", do_login_calls)
            _note(0, "doLogin accepted")
            # login command accepted; pump until confirmed + channel tree received
            end = time.time() + 12
            while time.time() < end:
                m = self.tt.getMessage(200)
                if not m:
                    continue
                ev = m.nClientEvent
                if ev == CLIENTEVENT_CMD_MYSELF_LOGGEDIN:
                    logged_in = True
                    _note(ev, "MYSELF_LOGGEDIN")
                    log.info("Received MYSELF_LOGGEDIN event.")
                    if self.status:
                        try:
                            self.tt.doChangeStatus(UserStatusMode.ONLINE, self.status)
                            log.info("Set bot status message.")
                        except Exception as e:
                            log.warning("Could not set status message: %s", e)
                elif ev == int(sdk.ClientEvent.CLIENTEVENT_CMD_CHANNEL_NEW) and m.channel:
                    ch = m.channel
                    self._channel_tree[ch.nChannelID] = (sdk.ttstr(ch.szName), ch.nParentID)
                    _note(ev, sdk.ttstr(ch.szName))
                elif ev == CLIENTEVENT_CON_LOST:
                    con_lost = True
                    _note(ev, "CON_LOST")
                    raise RuntimeError("Connection lost during login")
                elif ev == int(sdk.ClientEvent.CLIENTEVENT_CMD_ERROR):
                    code = getattr(m, "nError", 0)
                    # TeamTalk error code 0 == CMDERR_SUCCESS == no error.
                    # The server routinely sends this as a routine ACK during
                    # login; only non-zero codes are real failures.
                    if code != 0:
                        msg = sdk.getErrorMessage(code) if hasattr(sdk, "getErrorMessage") else ""
                        last_error = (code, msg)
                        _note(ev, f"code {code}: {msg}")
                        log.error("Server error during login: code %s (%s)", code, msg)
                    else:
                        _note(ev, "code 0 (success ACK)")
                        log.debug("Server login ACK (code 0 = success).")
                if logged_in and (self.tt.getRootChannelID() > 0 or len(self._channel_tree) >= 1):
                    grace_end = time.time() + 1.5
                    while time.time() < grace_end:
                        m2 = self.tt.getMessage(150)
                        if m2 and m2.nClientEvent == int(sdk.ClientEvent.CLIENTEVENT_CMD_CHANNEL_NEW) and m2.channel:
                            ch = m2.channel
                            self._channel_tree[ch.nChannelID] = (sdk.ttstr(ch.szName), ch.nParentID)
                    return
            if logged_in:
                return
            _note(-2, "doLogin accepted but no confirmation in 12s")
            # login command accepted but no confirmation; loop will retry
        # ---- timeout: emit a full diagnostic so the failure is never silent ----
        diag = (
            f"LOGIN TIMEOUT after {timeout}s. Summary:\n"
            f"  doLogin calls: {do_login_calls}, rejected: {do_login_rejected}\n"
            f"  ever logged in: {logged_in}\n"
            f"  connection lost: {con_lost}\n"
            f"  last server error: {last_error}\n"
            f"  connection state (getMyUserID): {self._safe_get_my_userid()}\n"
            f"  root channel id: {self._safe_root_channel()}\n"
            f"  last {len(seen_events)} events seen: "
            + ", ".join(f"{e[0]}({e[1]})" for e in seen_events)
        )
        log.error(diag)
        raise RuntimeError(
            "Never received login confirmation from server. "
            + (f"Last server error code {last_error[0]}: {last_error[1]}. " if last_error else "")
            + "See log above for the full event trail.")

    def _safe_get_my_userid(self):
        try:
            return self.tt.getMyUserID()
        except Exception as e:
            return f"<error: {e}>"

    def _safe_root_channel(self):
        try:
            return self.tt.getRootChannelID()
        except Exception as e:
            return f"<error: {e}>"

    def _wait_login_error(self, wait_s):
        """Pump briefly for a real login failure (CLIENTEVENT_CMD_ERROR with a
        non-zero error code) and return (code, msg) or None.

        TeamTalk error code 0 == CMDERR_SUCCESS, so a code-0 CMD_ERROR is a
        routine success ACK, NOT a failure -- we ignore it and keep looking
        (or return None if nothing else arrives).
        """
        import time
        end = time.time() + wait_s
        while time.time() < end:
            m = self.tt.getMessage(200)
            if not m:
                continue
            if m.nClientEvent == CLIENTEVENT_CON_LOST:
                raise RuntimeError("Connection lost during login")
            if m.nClientEvent == int(sdk.ClientEvent.CLIENTEVENT_CMD_ERROR):
                code = getattr(m, "nError", 0)
                if code == 0:
                    # success ACK, not an error -- ignore and keep pumping
                    continue
                msg = ""
                try:
                    msg = sdk.getErrorMessage(code)
                except Exception:
                    pass
                return (code, msg)
        return None

    def _join_channel(self):
        chan_id = self.tt.getChannelIDFromPath(self.channel_path)
        if chan_id <= 0:
            chan_id = self.tt.getRootChannelID()
        if chan_id <= 0:
            log.warning("Channel '%s' not found and no root channel visible.",
                        self.channel_path)
            return
        log.info("Joining channel id=%d ('%s')", chan_id, self.channel_path)
        self.tt.doJoinChannelByID(chan_id, self.channel_password)
        # wait until we are actually in a channel (best-effort)
        for _ in range(60):
            if self.tt.getMyChannelID() == chan_id:
                return
            self.tt.getMessage(100)

    def run(self):
        log.info("Event loop started. Listening for commands (PM-only)...")
        while self.running:
            msg = self.tt.getMessage(500)
            if not msg:
                continue
            ev = msg.nClientEvent
            if ev == CLIENTEVENT_CMD_USER_TEXTMSG:
                self._on_text_message(msg.textmessage)
            elif ev == CLIENTEVENT_CON_LOST:
                log.warning("Connection to server lost.")
                self.running = False

    def disconnect(self):
        self.running = False
        try:
            self.coag.disconnect()
        except Exception:
            pass
        try:
            self.tt.stopStreamingMediaFileToChannel()
        except Exception:
            pass
        try:
            self.tt.disconnect()
        except Exception:
            pass
        try:
            self.tt.closeTeamTalk()
        except Exception:
            pass

    # ---- command handling -----------------------------------------------
    def _sender_label(self, tm):
        """Build 'Nickname (username)' for the message sender."""
        username = sdk.ttstr(tm.szFromUsername)
        nickname = ""
        try:
            user = self.tt.getUser(int(tm.nFromUserID))
            if user:
                nickname = sdk.ttstr(user.szNickname)
        except Exception:
            pass
        if nickname and nickname != username:
            return f"{nickname} ({username})"
        return username or nickname or "unknown"

    def _on_text_message(self, tm):
        msg_type = int(tm.nMsgType)
        if self.pm_only and msg_type != MSGTYPE_USER:
            return  # ignore channel/broadcast messages
        text = sdk.ttstr(tm.szMessage).strip()
        if not text:
            return
        if text.startswith("/"):
            # command mode
            parts = text.split(None, 1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""
            handler = self.COMMANDS.get(cmd)
            if not handler:
                self.send_pm(tm.nFromUserID, f"Unknown command: {cmd}. Try /help.")
                return
            try:
                handler(self, arg, tm)
            except Exception as e:
                log.exception("Command %s failed", cmd)
                self.send_pm(tm.nFromUserID, f"Error running {cmd}: {e}")
            return
        # no slash -> treat the whole message as speech, announced by sender
        self.cmd_speak(text, tm, announce_from=tm)

    def cmd_help(self, arg, tm):
        self.send_pm(tm.nFromUserID,
            "Commands: /coag <ws uri> (session-only), /coagulator <uri>, /coag stop, "
            "/voices (lists one per line), /voice <name>, /rate <n>, /pitch <n>, "
            "/stop, /help. Any PM without a leading slash is spoken aloud "
            "(e.g. just type 'hello').")

    def cmd_coag(self, arg, tm):
        if arg.lower() == "stop":
            self.coag.disconnect()
            self.send_pm(tm.nFromUserID, "Disconnected from coagulator.")
            return
        if not arg:
            self.send_pm(tm.nFromUserID, "Usage: /coag <ws://user:pass@host:port>")
            return
        self.coag.connect(arg)
        self.send_pm(tm.nFromUserID,
            f"Connected to coagulator ({len(self.coag.list_voices())} voices). Use /voices.")

    def cmd_coagulator(self, arg, tm):
        self.cmd_coag(arg, tm)

    def cmd_voices(self, arg, tm):
        if not self.coag.connected:
            self.send_pm(tm.nFromUserID, "Not connected to a coagulator. Use /coag <uri> first.")
            return
        voices = self.coag.list_voices()
        if not voices:
            self.send_pm(tm.nFromUserID, "No voices listed yet (server may still be syncing). Try again in a moment.")
            return
        names = [v["name"] if isinstance(v, dict) else str(v) for v in voices]
        # One voice per line so screen readers / chat clients list them cleanly.
        self.send_pm(tm.nFromUserID, f"{len(names)} voices:")
        listing = "\n".join(names)
        self.send_pm(tm.nFromUserID, listing)

    # ---- voice capability / tag injection -------------------------------
    # Per Sam Tupy (STAR author): rate/pitch are inserted as literal tags
    # anywhere in the speech string -- [[rate XXX]] and [[pbas XXX]] -- where
    # XXX is usually words-per-minute for rate and a voice-dependent number
    # for pitch. The server's provider consumes these. This is the canonical
    # STAR mechanism (more reliable than the higher-level <r= p=> meta, which
    # only some providers honor). We inject the tags into the text ourselves;
    # the server does the per-voice conversion.
    _ENGINE_MAP = {
        "google": "google",
        "polly": "polly",
        "apple": "apple",
        "macsay": "apple",
        "sapi4": "sapi4",
        "sapi": "sapi",
        "eleven": "eleven",
        "openai": "openai",
        "balcony": "balcony",
        "b32": "b32",
        "nvgt": "nvgt",
        "sammy": "sammy",
        "ding": "ding",
        "android": "android",
    }

    def _voice_engine(self, voice):
        v = (voice or "").lower()
        for key, eng in self._ENGINE_MAP.items():
            if key in v:
                return eng
        return "unknown"

    def _voice_hint(self, voice):
        """Human-readable hint about how rate/pitch behave for this engine."""
        eng = self._voice_engine(voice)
        if eng == "apple":
            return ("Apple: rate is words/minute (try 150-250), pitch is a "
                    "voice-dependent number (try 30-120).")
        if eng in ("google", "polly", "eleven", "openai"):
            return ("Cloud engine: rate is usually words/minute, pitch is a "
                    "voice-dependent number. Experiment to taste.")
        if eng == "sapi4":
            return "SAPI4: rate/pitch are engine-specific numbers."
        return "Rate/pitch: numbers vary by voice -- try and listen."

    def cmd_voice(self, arg, tm):
        if not arg:
            self.send_pm(tm.nFromUserID, f"Current voice: {self.active_voice or '(none)'}.")
            return
        if self.active_voice and self.active_voice.lower() == arg.lower():
            self.send_pm(tm.nFromUserID,
                f"Voice already: {arg}. {self._voice_hint(arg)}")
            return
        # Switching voices: reset rate/pitch to defaults. Rate/pitch values are
        # tuned per-voice (e.g. Mac words/minute vs other engines' scales), so
        # carrying an old voice's numbers into a new voice produces wrong speech.
        self.active_voice = arg
        self.rate = 0.0
        self.pitch = 0.0
        self.send_pm(tm.nFromUserID,
            f"Voice set to: {arg}. Rate/pitch reset to defaults — set them again "
            f"for this voice. {self._voice_hint(arg)}")

    def cmd_rate(self, arg, tm):
        try:
            self.rate = float(arg)
        except ValueError:
            self.send_pm(tm.nFromUserID,
                "Rate must be a number, e.g. /rate 200 (words/minute for most synths).")
            return
        self.send_pm(tm.nFromUserID,
            f"Rate set to {self.rate} (injected as [[rate {self.rate}]]).")

    def cmd_pitch(self, arg, tm):
        try:
            self.pitch = float(arg)
        except ValueError:
            self.send_pm(tm.nFromUserID,
                "Pitch must be a number, e.g. /pitch 80 (voice-dependent).")
            return
        self.send_pm(tm.nFromUserID,
            f"Pitch set to {self.pitch} (injected as [[pbas {self.pitch}]]).")

    def _build_speech_line(self, text):
        """Build the STAR speech line: 'Voice: [[rate X]] [[pbas Y]] <text>'.
        Tags are only injected when the user changed them from the default
        (rate 0 / pitch 0 = unset)."""
        parts = []
        if self.rate:
            parts.append(f"[[rate {self.rate}]]")
        if self.pitch:
            parts.append(f"[[pbas {self.pitch}]]")
        tagged = " ".join(parts)
        if tagged:
            spoken = f"{tagged} {text}"
        else:
            spoken = text
        return f"{self.active_voice}: {spoken}"

    def cmd_speak(self, arg, tm, announce_from=None):
        if not arg:
            self.send_pm(tm.nFromUserID, "Usage: /speak <text>")
            return
        if not self.coag.connected:
            self.send_pm(tm.nFromUserID, "Not connected to a coagulator. Use /coag <uri> first.")
            return
        if not self.active_voice:
            self.send_pm(tm.nFromUserID, "No voice selected. Use /voice <name> first (see /voices).")
            return
        # When triggered by a plain (non-slash) PM, announce who said it.
        if announce_from is not None:
            arg = f"{self._sender_label(announce_from)} said: {arg}"
        textline = self._build_speech_line(arg)
        self.send_pm(tm.nFromUserID, f"Synthesizing with {self.active_voice}...")
        try:
            audio = self.coag.synthesize(textline, timeout=30)
        except Exception as e:
            self.send_pm(tm.nFromUserID, f"Synthesis failed: {e}")
            return
        self._stream_audio(audio)

    def cmd_stop(self, arg, tm):
        with self._stream_lock:
            if self._streaming:
                try:
                    self.tt.stopStreamingMediaFileToChannel()
                except Exception:
                    pass
                self._streaming = False
                self._cleanup_temp()
                self.send_pm(tm.nFromUserID, "Stopped streaming.")
            else:
                self.send_pm(tm.nFromUserID, "Nothing is currently streaming.")

    COMMANDS = {
        "/help": cmd_help,
        "/coag": cmd_coag,
        "/coagulator": cmd_coagulator,
        "/voices": cmd_voices,
        "/voice": cmd_voice,
        "/rate": cmd_rate,
        "/pitch": cmd_pitch,
        "/stop": cmd_stop,
    }

    # ---- audio streaming -------------------------------------------------
    def _stream_audio(self, audio_bytes):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav", dir=tempfile.gettempdir())
        tmp.write(audio_bytes)
        tmp.close()
        wav_path = tmp.name
        out_path = wav_path + ".stream.wav"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", wav_path, "-ac", "1", "-ar", "44100", out_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            log.warning("ffmpeg transcode failed (%s); streaming original", e)
            out_path = wav_path

        with self._stream_lock:
            self._cleanup_temp()
            self._temp_files = [wav_path, out_path]
            vc = sdk.VideoCodec()
            vc.nCodec = NOVIDEOFORMAT
            ok = self.tt.startStreamingMediaFileToChannel(out_path, vc)
            if not ok:
                self.send_pm(self._last_from or 0,
                    "Failed to start streaming (missing USERRIGHT_TRANSMIT_MEDIAFILE_AUDIO?).")
                self._cleanup_temp()
                return
            self._streaming = True
        log.info("Streaming %d-byte audio to channel.", len(audio_bytes))

    def _cleanup_temp(self):
        for f in self._temp_files:
            try:
                os.remove(f)
            except OSError:
                pass
        self._temp_files = []

    # ---- outbound messaging ---------------------------------------------
    def send_pm(self, to_user_id, text):
        self._last_from = to_user_id
        for m in sdk.buildTextMessage(text, MSGTYPE_USER, nToUserID=to_user_id):
            self.tt.doTextMessage(m)

    def send_channel(self, text):
        for m in sdk.buildTextMessage(text, MSGTYPE_CHANNEL, nChannelID=self.tt.getMyChannelID()):
            self.tt.doTextMessage(m)


def build_bot_from_config(cfg):
    return StarTeamTalkBot(
        host=cfg.get("host", "127.0.0.1"),
        tcp_port=cfg.get("tcp_port", "10333"),
        udp_port=cfg.get("udp_port", "10333"),
        nickname=cfg.get("nickname", "STAR Bot"),
        username=cfg.get("username", ""),
        password=cfg.get("password", ""),
        channel_path=cfg.get("channel_path", "Default"),
        channel_password=cfg.get("channel_password", ""),
        encrypted=cfg.get("encrypted", False),
        pm_only=cfg.get("pm_only", True),
        status=cfg.get("status", ""),
    )
