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

## Project layout

Everything lives in **one folder** (the cloned repo). No nested `src/` maze:

```
star_tt_bot/                  <- the clone (your "1 thingy")
├── run.py                    <- entry point (run this)
├── bot.py                    <- the bot logic
├── config.py                 <- defaults + env-var overrides
├── star_client.py            <- STAR coagulator websocket client
├── config.local.py.example   <- copy to config.local.py, fill in creds
├── _tt_vendor/TeamTalkPy/    <- vendored SDK wrapper (offline)
├── pyproject.toml / uv.lock
├── README.md / LICENSE / .gitignore
```

After `uv sync` you may also have a gitignored `config.local.py` here (your
real credentials — never committed).

## Setup

```bat
cd star_tt_bot
uv sync
uv run python run.py --set        # interactive: enter your account details
uv run python run.py              # run it
```

`--set` writes a gitignored `src/star_tt_bot/config.local.py` so your
credentials never leave your machine. Re-run with `--force` to overwrite.

To run without auto-connecting to a STAR coagulator:

```bat
uv run python run.py --no-star
```

## Commands (send as a private message to the bot)

- `/coag <ws://user:pass@host:port>` — connect to a STAR coagulator **for this
  session only** (does not change your saved default).
- `/coagulator <uri>` — alias of `/coag`.
- `/coag stop` — disconnect from the coagulator.
- `/voices` — list available voices, one per line.
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
variables, a gitignored `config.local.py` (made via `--set`), or both. See
`src/star_tt_bot/config.py` for the full list of `STAR_TT_*` / `STAR_COAG_*`
environment variables.

Defaults (overridable via env or `config.local.py`):

| Setting        | Default                       |
|----------------|-------------------------------|
| host           | `tunmi13.com`                 |
| tcp/udp port   | `9483`                        |
| nickname       | `starbot`                     |
| username       | `star`                        |
| channel        | `/hangout area/`              |
| STAR coag URI  | `wss://star.blindsoft.net`    |

Set your real password with the `STAR_TT_PASSWORD` environment variable or via
`uv run python run.py --set`.

## TeamTalk SDK note

The Python `teamtalk` package normally tries to download a paywalled SDK from
bearware.dk on first import. This repo vendors the wrapper we already use in
`src/star_tt_bot/_tt_vendor/TeamTalkPy` so a fresh `uv sync` works offline.
You still need the native **TeamTalk5.dll** installed on Windows (the bot points
at `C:\Program Files\TeamTalk5` automatically).
