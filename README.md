# STAR TeamTalk Bot

Bridges [STAR](https://github.com/samtupy/star) coagulator TTS into a TeamTalk 5
channel. The bot connects to a TeamTalk server, joins a channel, and streams
synthesized speech (from a STAR coagulator over websockets) into that channel.

It only responds to **private messages** sent directly to it (PM-only mode).

## Requirements

- Windows with `TeamTalk5.dll` installed (e.g. at `C:\Program Files\TeamTalk5`).
  The bot adds that directory to the DLL search path automatically.
- `ffmpeg` on PATH (for transcoding synthesized audio to a streamable WAV).
- A running STAR coagulator (websocket) the bot can reach.
- [uv](https://github.com/astral-sh/uv) for the Python environment.

## Run (uv)

```bat
cd star_tt_bot
uv sync
uv run python run.py
```

To run without auto-connecting to a STAR coagulator:

```bat
uv run python run.py --no-star
```

## Commands (send as a private message to the bot)

- `/coag <ws://user:pass@host:port>` — connect to a STAR coagulator.
- `/coagulator <uri>` — alias of `/coag`.
- `/coag stop` — disconnect from the coagulator.
- `/voices` — list available voices.
- `/voice <name>` — select the active voice (e.g. `/voice sam`).
- `/rate <n>` — set speech rate (e.g. `/rate 200`). Injected into the spoken
  text as `[[rate n]]` (usually words/minute for most synths).
- `/pitch <n>` — set speech pitch (e.g. `/pitch 80`). Injected into the spoken
  text as `[[pbas n]]` (a voice-dependent number, per Sam Tupy's STAR spec).
- `/stop` — stop the current streaming speech.
- `/help` — show the command list.

Switching voices resets rate/pitch to defaults (values are per-voice).

**Any PM without a leading slash is spoken aloud**, announced as
`"<nickname> (<username>) said: <message>"`.

> **Rate/pitch mechanism.** Per Sam Tupy (STAR author), rate and pitch are
> inserted as literal tags anywhere in the speech string: `[[rate XXX]]` and
> `[[pbas XXX]]`, where XXX is usually words-per-minute for rate and a
> voice-dependent number for pitch. The bot injects these tags into the text
> before sending (only when you've set them). The server's provider consumes
> them. Some novelty voices speak the brackets literally — that's a voice
> quirk, not a bot bug. Experiment per voice to find good values.

## Configuration

**No secrets are stored in the repo.** Credentials come from environment
variables or an optional, gitignored `config.local.py`. See `config.py` for the
full list of `STAR_TT_*` / `STAR_COAG_*` environment variables.

Defaults (overridable via env):

| Setting        | Default                       |
|----------------|-------------------------------|
| host           | `tt-server.com`               |
| tcp/udp port   | `10443`                       |
| nickname       | `starbot`                     |
| username       | `star`                        |
| channel        | `/hangout area/`              |
| STAR coag URI  | `wss://star.blindsoft.net`    |

Set your real password with the `STAR_TT_PASSWORD` environment variable (or put
`CONFIG = {...}` in a gitignored `config.local.py`).

## TeamTalk SDK note

The Python `teamtalk` package normally tries to download a paywalled SDK from
bearware.dk on first import. This repo vendors the wrapper we already use in
`_tt_vendor/TeamTalkPy` so a fresh `uv sync` works offline. You still need the
native **TeamTalk5.dll** installed on Windows (the bot points at
`C:\Program Files\TeamTalk5` automatically).
