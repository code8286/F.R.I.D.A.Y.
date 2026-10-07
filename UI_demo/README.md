# F.R.I.D.A.Y. frontpage: interactive UI demo

A runnable PySide6 + Qt Quick (QML) build of the `friday-ui` home screen from `frontpage-ui-build-brief.md`, laid out to
match `friday-frontpage-mockup.png`. Everything is driven by an in-process **mock core** that speaks the same envelope the
real core will speak over the UI WebSocket, so this folder can be dropped into `friday/ui/frontpage/` in tranche 4 with
the mock swapped for `ws_client.py`.

## Run it (Windows PowerShell)

```powershell
cd "D:\Current User Data\Obsidian\2026-27\Projects\F.R.I.D.A.Y\UI_demo"
python -m pip install -r requirements.txt     # PySide6
python run.py --fetch-fonts                   # first run: downloads Space Grotesk + JetBrains Mono (OFL), then starts
python run.py                                 # later runs
```

Options: `--size 1920x1080`, `--fullscreen`, `--theme light|dark|system`, `--reduced-motion`, `--no-script`
(skip the 60 s demo script), `--no-cycle` (do not cycle the HUD states every 4 s), `--repeats 2|4|6`, `--no-caption`,
`--mock-mic` (the UI opens your microphone for visual tuning; needs `pip install sounddevice numpy`, and refuses to start if a
core is listening on `--core-port`, default 8765, so there are never two microphone owners).

## Play with it

| Input | Does |
|---|---|
| click a tile, or `1`–`8` | open B, C, D, A, E, F, G, H (slot order) as a panel over the right section |
| `Esc`, the letter, or `‹ back` | close it |
| arrows / `Tab`, then `Enter` | keyboard focus (accent ring) and open |
| hold `Space` | push-to-talk: the ring goes to listening, then thinking, then speaking |
| `F1` | demo controls: next HUD state, auto-cycle, clap, Telegram message, T3 confirmation, reminder due, ring an alarm, make the core refuse the next action, offline/online, dark mode, reduced motion (also `Ctrl+S/M/K/N/P/E/R/F/O/D/T`) |
| click the ring while a confirmation waits | opens A |

What to try:
- **D** tick a to-do (check draws, strike-through, it moves to Done), drag `⋮⋮` to reorder, swipe left or × to delete, then Undo.
- **E** toggle alarms, `+ Add alarm` uses the scroll wheels, `Ctrl+R` rings one (the tile inverts and flashes, Stop / Snooze).
- **C** snooze a reminder (it slides out and reappears in its new group); `Ctrl+E` makes one come due and the bell rings.
- **B** month view with the diagonal cascade and self-drawing today ring, `‹ ›` months, week and day views with the live
  now line, add an event, × asks for approval (T2) in A.
- **A** the countdown to the next thing, the merged 24 h timeline, notifications (untrusted ones are plain text with
  `⚠ external`), confirmation cards with Approve / Deny.
- **F** play/pause from the tile or the disc (it only spins while playing), prev/next, seek, volume, shuffle/repeat.
- **G** click a running task to watch its steps stream in, hover for pause/cancel, drag a queued task.
- **H** `+ New`: the typewriter preview and the parsed schedule (`weekdays 18:30` → every weekday at 18:30); saving asks
  for approval in A. Hover a row for run now / pause / edit / delete.

The 60 s demo script (off with `--no-script`): a Telegram message at 8 s, a reminder that comes due at ~28 s, a T3
confirmation at 40 s, the "check lab inbox" command fires at ~52 s and hands a task to G, an alarm rings at 58 s.

## How it is built

```
run.py                       entry point
friday_ui/app.py             registers Python types, loads qml/Main.qml, wires the mock core
friday_ui/bridge.py          the `Core` singleton QML talks to: stores, list models, stats, actions, optimistic UI
friday_ui/models.py          QAbstractListModel with stable ids and minimal diffs (so list transitions animate)
friday_ui/mock/mock_core.py  fake core: demo data, policy (T2 → confirmation card), scheduler, spectrum generator
friday_ui/hud/ring_item.py   the HUD ring (QQuickPaintedItem): 32 bands, mirrored, x4 = 256 bars, all states
friday_ui/hud/spectrum_smoother.py   30 Hz → display-rate interpolation, attack 0.55 / release 0.12
friday_ui/hud/mic_tap.py     --mock-mic analysis (the same maths as the planned friday/sensors/spectrum.py)
friday_ui/art.py             album art as 1-bit ordered dither (image://art/<track>)
friday_ui/qml/               Main, Frame, HudPanel, Tile + the eight tiles, icons, components; theme/Theme.qml holds every token
```

Rules kept from the brief: the UI never executes anything (every change is an action the core decides); confirmation
cards render in A and Approve/Deny round-trip; cheap reversible actions are optimistic and roll back with a shake if the
core refuses (`Ctrl+F` to see it); untrusted items are plain text with an external tag; only band magnitudes reach the
UI, never audio; while minimised the spectrum subscription stops. Upcoming is merged in the UI from calendar, reminders
and alarms.

Not in this demo yet: the stacked layout below 1100 px (the window minimum is 1280×760), the shared-element morph
between calendar views (it cross-fades), real backends (Windows media session, Google Calendar, the WebSocket client),
and the section 9 performance measurements.
