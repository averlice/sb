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
├── config.py                 <- loads config.json (no more env-var maze)
├── star_client.py            <- STAR coagulator websocket client
├── config.json               <- your settings (edit this directly)
├── config.local.py.example   <- optional local override (gitignored)
├── _tt_vendor/TeamTalkPy/    <- vendored SDK wrapper (offline)
├── pyproject.toml / uv.lock
├── README.md / LICENSE / .gitignore
```

## Setup

```bat
cd star_tt_bot
uv sync
# Edit config.json with your TeamTalk credentials and channel
uv run python run.py          # run it
```

To run without auto-connecting to a STAR coagulator:

```bat
uv run python run.py --no-star
```

## Configuration

Edit `star_tt_bot/config.json` directly — **single file, no secrets in repo**:

```json
{
  "host": "your-server.com",
  "tcp_port": 9483,
  "udp_port": 9483,
  "nickname": "your-bot-name",
  "username": "your-account",
  "password": "your-password",
  "channel_path": "/your/channel/path/",
  "channel_password": "",
  "encrypted": false,
  "star_uri": "wss://star.blindsoft.net",
  "pm_only": true,
  "status": "Bot status message"
}
```

Optional: create `config.local.py` (gitignored) to override specific keys — never committed.

| Setting        | Description                    |
|----------------|--------------------------------|
| host           | TeamTalk server hostname       |
| tcp/udp port   | TeamTalk ports (usually 9483)  |
| nickname       | Bot display nickname           |
| username       | TeamTalk account username      |
| password       | TeamTalk account password      |
| channel_path   | Channel to join (e.g. `/hangout area/`) |
| encrypted      | Use TLS (`true`/`false`)       |
| star_uri       | STAR coagulator websocket URI  |

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

## TeamTalk SDK note

The Python `teamtalk` package normally tries to download a paywalled SDK from
bearware.dk on first import. This repo vendors the wrapper we already use in
`star_tt_bot/_tt_vendor/TeamTalkPy` so a fresh `uv sync` works offline.
You still need the native **TeamTalk5.dll** installed on Windows (the bot points
at `C:\Program Files\TeamTalk5` automatically).

## Known quirks / troubleshooting

- **Channel not found**: The bot logs all discovered channels on startup.
  Match the `channel_path` exactly (case-sensitive, leading slash).
- **Login succeeds but no channels**: The server sends the channel tree *after*
  login. The bot now waits 3s for `CLIENTEVENT_CMD_CHANNEL_NEW` events.
- **Synthesis timeout**: If a voice requires extra params, the server returns
  a JSON error (e.g. "400 this voice requires a model name"). Try a different voice.
- **No audio heard**: Ensure you have `USERRIGHT_TRANSMIT_MEDIAFILE_AUDIO` on
  the server, and `ffmpeg` is on PATH.