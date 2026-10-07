# Tranche 3 build log: sensors and voice (0.3.0, 2026-10-06)

**Result:** 446 tests pass on Python 3.10 (on the device), 3.11, 3.12, 3.13; ruff clean; all 96 files md5-verified on the device. `friday --version` prints 0.3.0.

## Decisions (yours)

- Models: explicit download only. `friday fetch-models` downloads once; the running core never downloads.
- On wake: greet and listen. Spoken "Yes, Alpha?", a ~20 s listening window, nothing launched. Waking grants no authority.
- TTS: ElevenLabs first (key in the OS keyring, voice id in config), local system voice as fallback; only short fixed phrases cached on disk.
- Voice is OFF by default (`[voice] enabled = false`).

## What was built

`friday/sensors`: audio_hub (single mic owner, reconnect, silent-default fallback), clap (ported, with short-spike rule), vad (energy endpointer, noise adaptation), wakeword (Vosk grammar + worker thread), activation (either/both/clap/wake fusion), stt (faster-whisper, local files only, CPU fallback), tts (ElevenLabs, local SAPI/say/espeak, WAV cache, plausibility check), speaker (async, barge-in, half-duplex flags), speech_text, models (fetch-models), stack (builds it all, degrades with notes), diagnostics (audio-devices, voice-check). `friday/channels/voice.py`: the listening window, spoken replies, spoken reminders, voice approvals, kill-switch handling. CLI: `audio-devices`, `voice-check`, `fetch-models`. Config: `[voice]`. Extra: `pip install .[voice]`.

## Independent adversarial review: findings and fixes

All fixed, each with a regression test (one confirmed to fail on the old code):

1. Voice-owned approvals were decided by "a voice turn is running", so a typed turn's request could be read out and answered by voice. Now each approval carries the origin channel of its turn and only `voice` origin is voice-owned.
2. The spoken readback was passed through the reply summariser (URLs became "a link", long text truncated). Now spoken verbatim; anything that cannot be said in full marks the request incomplete and the broker refuses a spoken approval (approve on screen).
3. A crashing TTS engine or player could escape into a turn or approval; a bad frame could kill a background loop. Now `Exception`-safe, loops log and continue.
4. Truncated or near-empty TTS audio counted as "spoken". Now rejected (falls back to the next engine).
5. Steady loud noise re-triggered the recorder forever; hallucination filter let "thank you" through.
6. fetch-models: leaked temp fd, redirects to http allowed, no overall deadline, half-finished Whisper download counted as installed, `--force` could delete a user-configured folder.
7. Claps and the wake phrase could open a window from FRIDAY's own speech; now ignored while speaking (a clap or "stop" only stops speech).
8. Smaller: regex `$` newline bypass on voice id and format, HTTP exceptions, Stereo Mix chosen as microphone, GPU-stack failure with `stt_device=auto`, espeak streaming WAV header, absolute System32 PowerShell, NaN/inf config values, stale answers (speech that began before the readback ended), reminders coalesced, dead wake engine reported, expired approvals swept while idle. Found later on the device run: a reminder arriving while another was being spoken could be dropped (fixed, test added).

## Not verified (no hardware in the cloud)

Real microphone, PortAudio, Vosk, Whisper, ElevenLabs and Windows SAPI paths are covered by fakes only. Windows CI has not run yet. Run `friday voice-check` after installing.

## Your next steps

1. `pip install ".[voice]"` (Linux: `libportaudio2`; optional `espeak-ng`)
2. `friday fetch-models all` (optionally pin the printed Vosk SHA-256 in `voice.vosk_model_sha256`)
3. `friday set-secret elevenlabs_api_key`, set `voice.elevenlabs_voice_id`
4. `friday audio-devices`, then set `[voice] enabled = true`, then `friday voice-check`, then `friday run`
5. Later: Telegram (tranche 5) needs a new BotFather token and your numeric user ID.

## Next: tranche 4, the desktop UI (PySide6 HUD, control box, approvals dock, tray) over the local WebSocket.