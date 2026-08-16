#!/usr/bin/env python3
"""STAR coagulator client (websocket).

Protocol derived from the samtupy/star source (github.com/samtupy/star):
  - Client sends {"user": <revision>} on connect.
  - Server pushes {"voices": [...]} (list of voice name dicts).
  - Client sends {"user": <rev>, "request": "<voice><r=.. p=..>: text", "id": "<id>"}.
    IMPORTANT: the coagulator REWRITES the id to "<clientid>_<id>_<seq>" before
    handing the request to the voice provider, and the provider echoes that
    rewritten id back in the binary frame. So we cannot correlate the
    response by our original id -- we treat the next binary frame we receive
    after sending a request as that request's audio.
  - Server replies with binary frames:
        len(2 bytes, little) + json-meta + audio-bytes
    where audio-bytes is WAV/PCM.
  - If a voice needs extra params, the server sends a JSON {"status": "400 ...", "abort": true}
    instead of audio, and no binary frame arrives.

Speech requests are serialized (one at a time) so a simple FIFO queue of
received audio frames is sufficient for correlation.
"""
import os
import json
import threading
import queue
import websockets.sync.client

STAR_USER_REVISION = 4  # matches STAR.py USER_REVISION


class StarCoagulator:
    def __init__(self):
        self.ws = None
        self.uri = None
        self.voices = []
        self._lock = threading.Lock()
        self._audio_q = queue.Queue()           # ("audio", bytes, resp_id) items
        self._thread = None
        self._abort = threading.Event()
        self._synth_lock = threading.Lock()     # one synthesis at a time

    @property
    def connected(self):
        return self.ws is not None

    def connect(self, uri):
        with self._lock:
            if self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass
            ws = websockets.sync.client.connect(uri, max_size=None)
            ws.send(json.dumps({"user": STAR_USER_REVISION}))
            self.ws = ws
            self.uri = uri
        self._abort.clear()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        return True

    def _pump(self):
        ws = self.ws
        while not self._abort.wait(0.005):
            try:
                message = ws.recv(30)
            except TimeoutError:
                try:
                    ws.ping()
                except Exception:
                    break
                continue
            except Exception:
                break
            if ws is not self.ws:
                break
            if isinstance(message, bytes):
                self._on_binary(message)
            else:
                try:
                    self._on_json(json.loads(message))
                except json.JSONDecodeError:
                    pass

    def _on_json(self, event):
        if "voices" in event:
            self.voices = event["voices"]
        elif "error" in event:
            # fatal-ish protocol error (e.g. revision mismatch)
            self._audio_q.put(("error", event["error"], ""))
        elif "status" in event and ("abort" in event or "id" in event):
            # provider status/abort (e.g. "400 this voice requires a model name")
            self._audio_q.put(("error", event.get("status", "provider error"), ""))

    def _on_binary(self, message):
        if len(message) < 4:
            return
        meta_len = int.from_bytes(message[:2], "little")
        meta_raw = message[2 : meta_len + 2].decode("utf-8", "replace")
        audio = message[meta_len + 2 :]
        # Parse meta JSON to extract the request ID for correlation
        try:
            meta = json.loads(meta_raw)
            resp_id = meta.get("id", "")
        except json.JSONDecodeError:
            resp_id = ""
        self._audio_q.put(("audio", audio, resp_id))

    def list_voices(self):
        with self._lock:
            return list(self.voices)

    def synthesize(self, textline, timeout=30):
        if not self.ws:
            raise RuntimeError("Not connected to a coagulator")
        with self._synth_lock:
            req_id = f"ttbot_{os.urandom(3).hex()}"
            self.ws.send(json.dumps({"user": STAR_USER_REVISION, "request": textline, "id": req_id}))
            # wait for the response frame matching our request ID
            # The server rewrites ID to "<clientid>_<id>_<seq>", so match our ID + underscore
            match_pattern = f"{req_id}_"
            try:
                while True:
                    kind, payload, resp_id = self._audio_q.get(timeout=timeout)
                    if kind == "error":
                        raise RuntimeError(payload)
                    if match_pattern in resp_id:
                        return payload
                    # stale frame from previous request; ignore and continue
            except queue.Empty:
                raise TimeoutError("STAR synthesis timed out")

    def disconnect(self):
        self._abort.set()
        with self._lock:
            ws = self.ws
            self.ws = None
        if ws:
            try:
                ws.close()
            except Exception:
                pass