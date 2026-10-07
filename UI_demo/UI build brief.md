# F.R.I.D.A.Y. Frontpage UI: Build Brief

This is a build brief for the agent who implements the F.R.I.D.A.Y. frontpage, the home screen of `friday-ui`. Read the whole thing before you write any code. Where this brief says **must**, it's a requirement. Where it says **should**, it's the default, and you may change it if you note why in the PR.

---

## 0. Context you need first

- F.R.I.D.A.Y. runs as two processes. **`friday-core`** is a headless asyncio daemon that owns all state, the scheduler, the sensors (mic), the LLM loop, memory and policy. **`friday-ui`** is a **PySide6** client that talks to the core over a local WebSocket on `127.0.0.1`, authenticated with a token file. See `docs/ARCHITECTURE.md`.
- The UI **never executes anything itself.** Every action (tick a to-do, snooze, play/pause, cancel a task) goes to the core as a request. The core's policy engine decides, and anything at tier T2 or higher comes back as a confirmation card. The UI only renders.
- **The core owns the microphone.** `AudioHub` is the only process that opens the mic. The UI must not open its own audio input in normal mode. The HUD ring is fed spectrum frames from the core (section 4.3).
- The code goes in `friday/ui/frontpage/` (tranche 4). The existing floating HUD orb stays. It should reuse the ring renderer from this page at a smaller size.

**Tech choice:** use PySide6 + **Qt Quick (QML)** for the frontpage. Qt Quick gives you GPU compositing, `Behavior`/`NumberAnimation`, states/transitions and list `add`/`remove`/`displaced` transitions, which this design leans on heavily. Write the ring as a Python `QQuickPaintedItem`, or as a `QSGGeometryNode` if profiling shows you need it, and register it into QML.

---

## 1. Layout

The page follows the editorial layout of the reference poster: a cream page, thin black rules, a tall left panel, a vertical divider and a grid of rounded black tiles on the right. The reference image is a **layout and style guide only**. Do not copy its illustrations, its "39 design principles" text, the author name or the "Syntax Stream" mark. Every icon below is original line art.

```
┌───────────────────────────────────────────────────────────────────────────────┐  ← top rule (1px)
│                          │ ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│                          │ │B         │ │C         │ │G  AI TASK│             │
│                          │ │ Calendar │ │ Reminders│ │   QUEUE  │             │
│                          │ └──────────┘ └──────────┘ │          │             │
│       HUD  RING          │ ┌──────────┐ ┌──────────┐ ├──────────┤ ← split    │
│   (mic-reactive EQ)      │ │D         │ │A (accent)│ │H  AI     │             │
│                          │ │ To-do    │ │ Upcoming │ │ COMMANDS │             │
│                          │ └──────────┘ └──────────┘ │          │             │
│                          │ ┌──────────┐ ┌──────────┐ │          │             │
│                          │ │E         │ │F         │ │          │             │
│                          │ │ Alarms   │ │ Music    │ │          │             │
│                          │ └──────────┘ └──────────┘ └──────────┘             │
├──────────────────────────┴────────────────────────────────────────────────────┤  ← bottom rule
│ F.R.I.D.A.Y. · v0.4.0 · core ● connected                  10:42 · Tue 06 Oct  │  ← footer
└───────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 Proportions

These are measured from the reference at 2000×1414 and expressed as fractions, so the layout scales with the window.

|Element|Spec|
|---|---|
|Outer margin (left/right)|2.1% of width|
|Top rule|y = 2.8% of height, 1px, `ink`|
|Bottom rule|y = 94% of height, 1px, `ink`|
|Left panel|x from margin to 34.8% of width|
|Vertical divider|x = 34.8%, 1px, `ink`, runs from top rule to bottom rule|
|Right grid|starts 2% after the divider and ends at the right margin. Same top/bottom inset as the tiles in the reference (about 2.4% of height)|
|Grid|3 columns × 3 rows, gutter ≈ 0.6% of width|
|Column 3|**one merged tile spanning all 3 rows**, split horizontally into **two equal halves** (G top, H bottom) with a 1px `#2A2A2A` inner divider and the same inner padding. Draw it as one rounded rectangle, not two tiles|
|Tile corner radius|1.1% of width (≈22px at 2000px)|
|Tile inner padding|1.6% of width|
|Footer|below the bottom rule, small text, left and right aligned|

The minimum window is 1280×760. Below 1100px wide, stack the left panel above the grid and shrink the ring to 60% of the viewport height. The grid becomes 2 columns, with the merged column below it at full width.

### 1.2 Tile anatomy (all tiles)

- A **letter** in the top-left (B, C, D…), 1.4% of width, regular weight.
- An **icon illustration** in the top-right: white line art, 1.5px stroke, inside a box about 45% of the tile width. Each icon has a subtle idle animation (section 5).
- A **title** in the bottom-left: two lines, 2.1% of width, regular weight, as in the reference ("Calendar", "Reminders", "To-do / List", "Upcoming", "Alarms", "Music").
- A **live glance line** directly above the title: one line of small mono text with that tile's most important live value, such as `Next · Standup 11:00` or `3 open`. This is the only extra text in the compact state.
- Background `tile` (black). Tile A is the accent (`accent` background, black line art and text), exactly like the coral tile in the reference.

### 1.3 Tile allocation

|Slot|Letter|Tool|Reason|
|---|---|---|---|
|r1 c1|B|**Calendar**|top-left is the natural starting point|
|r1 c2|C|**Reminders**||
|r2 c1|D|**To-do list**||
|r2 c2|**A (accent)**|**Upcoming + Notifications**|the centre accent tile is where the eye lands, so the "what's next" feed goes there|
|r3 c1|E|**Alarms**||
|r3 c2|F|**Music (Spotify)**|sits next to the AI column, which keeps the active, noisy tiles together|
|c3 top|G|**AI Task Queue**|queued tasks, routines, running jobs|
|c3 bottom|H|**AI Commands**|recurring and queued commands for the AI itself|

---

## 2. Design tokens

Put these in `friday/ui/frontpage/Theme.qml` as a singleton and nowhere else.

```qml
// colours
readonly property color page:    "#F6F3EE"   // cream background
readonly property color ink:     "#0A0A0A"   // rules, text on page, HUD ring
readonly property color tile:    "#000000"
readonly property color onTile:  "#F5F5F2"   // text/line art on black
readonly property color dimOnTile: "#8C8C88" // secondary text on black
readonly property color hairline:"#2A2A2A"   // dividers inside tiles
readonly property color accent:  "#F96148"   // coral, tile A only (+ confirmation chip)
readonly property color onAccent:"#0A0A0A"
readonly property color danger:  "#F96148"   // reuse accent; never introduce a 2nd hue

// type: bundle the fonts (OFL) in friday/ui/assets/fonts
readonly property string display: "Space Grotesk"   // titles, letters
readonly property string mono:    "JetBrains Mono"  // times, counts, commands, HUD labels

// motion
readonly property int fast: 140
readonly property int base: 240
readonly property int slow: 420
// easings: Easing.OutCubic (enter), Easing.InCubic (exit), Easing.OutBack amplitude 1.2 (pops)
```

Rules:

- There is **one accent hue**, used only on tile A and on confirmation and alert states. Everything else is black, cream or white.
- Dark mode inverts the page: `page` becomes `#0B0B0B`, `ink` becomes `#EDEAE4`, and tiles become `#161616`. The ring stays monochrome in the ink colour. Follow the OS setting and allow an override in settings.

---

## 3. Global animations and interactions

### 3.1 Launch sequence (≈1.2 s total, skippable by any input)

1. **0–300 ms**: the top and bottom rules draw outward from the horizontal centre (scaleX 0→1, OutCubic).
2. **150–450 ms**: the vertical divider grows downward from the top rule.
3. **300–900 ms**: the tiles enter with a stagger in letter order **A, B, C, D, E, F, G, H**, 60 ms apart. Each tile goes from opacity 0→1, scale 0.96→1 and y +12px→0 over `base` with OutCubic. The A-first order mimics the reference's "A sits in the middle" logic: the accent lands first and the rest follow.
4. **400–1200 ms**: the HUD ring "boots". Its bars grow from length 0 in a clockwise sweep starting at 12 o'clock, the tick marks fade in, then it settles into the idle state.

### 3.2 Tiles

- **Hover:** the icon plays its hover variant (section 5), the title nudges 4px right, and the cursor becomes a pointer. There's no shadow and no lift, because the design is flat.
- **Press:** the tile scales to 0.985 over `fast`.
- **Open (expanded view):** clicking a tile, or pressing its number key, morphs that tile into a panel that fills the **right section** (the whole grid area). The morph animates x/y/w/h and radius over `slow` with OutCubic. The other tiles fade to 0 and scale to 0.98. Content inside the panel fades in after 60% of the morph. **Esc**, the back chevron or clicking the letter collapses it with the reverse animation. The HUD ring stays visible and live the whole time.
- **Keyboard:** Tab and the arrow keys move between tiles, with a 2px focus ring in `accent` that is offset 3px outside the tile. Keys `1`–`8` open the tiles in slot order B, C, D, A, E, F, G, H. `Space` held is push-to-talk: it sends `activation.ptt` to the core.
- **Reduced motion** (OS setting or `ui.reduced_motion = true`): replace all movement with 120 ms opacity fades, freeze the icon idle loops, and keep the HUD ring live but turn off its idle rotation.

### 3.3 Live data arriving

- A value change in a glance line uses a vertical "odometer" roll: the old text slides up and out while the new text slides up and in, over `base`.
- New list items enter with height 0→auto plus a fade. Removed items collapse. Reordering uses QML `displaced` transitions (`base`, OutCubic). Lists never jump.

---

## 4. Left panel: the HUD ring

### 4.1 What it is

The ring is a **monochrome (ink) radial equaliser**: a circle built from many thin radial bars, where each bar is one frequency band of the live mic signal. The band pattern **repeats around the circle** to close it. The left panel holds only the ring, centred in the panel with a diameter of `min(panelWidth, panelHeight) × 0.78`. The one exception is a single small mono state caption under the ring (for example `LISTENING`), which you can turn off in settings.

### 4.2 Geometry

|Part|Spec|
|---|---|
|Bands|**B = 32** log-spaced bands from 60 Hz to 7.6 kHz (the mic runs at 16 kHz)|
|Repeat|The 32-band pattern is mirrored so the seams meet cleanly: `low→high` then `high→low`. That mirrored pair is repeated **4×**, giving 32 × 2 × 4 = **256 bars** over 360°. Configurable: `hud.repeats = 2 \| 4 \| 6`|
|Bar|Starts at inner radius `R0 = 0.62 · R`. Length = `Lmin + a · (R − R0 − Lmin)` with `Lmin = 0.025·R`. Width tapers from 0.9·pitch at the base to 0.5·pitch at the tip, with round caps|
|Peak caps|A 2px dot beyond each bar at that band's peak-hold value. It holds for 400 ms, then falls at 0.6·R per second|
|Guides|One thin circle at `0.58·R` (0.75px) and one dashed circle at `1.04·R`. Tick marks every 10° on the outer guide, with longer ticks every 90°|
|Labels|Tiny mono degree labels at 0/90/180/270 (`000`, `090`…) and a frequency legend (`60Hz … 7.6k`) along one quadrant. These give the HUD/instrument feel|
|Centre|A filled ink dot. Its radius is `0.06·R + rms · 0.05·R`, smoothed|

### 4.3 Data feed (core → UI)

The core already holds the mic through `AudioHub` (16 kHz mono, 20 ms frames). Add a lightweight spectrum tap **in the core**, in a new `friday/sensors/spectrum.py`:

- It is a hub subscriber, so it never opens the mic itself. It keeps a 512-sample rolling buffer, applies a Hann window, runs an rfft, and sums the energy into the 32 log bands. It converts to dB, then normalises against an adaptive floor (the same floor-tracking idea as the clap detector) and a ceiling of floor + 48 dB. The output is clamped to 0..1.
- It publishes `audio.spectrum` at **30 Hz** to the UI WebSocket, **only while at least one UI client is subscribed**. When nothing is subscribed it stops computing, which keeps idle CPU near zero.
- **Privacy:** only band magnitudes leave the core. Raw audio never goes over the socket. Quantise each band to a uint8.
- During TTS playback, the core publishes `tts.spectrum` computed from the outgoing audio, so the ring can show F.R.I.D.A.Y. speaking.

```json
{ "type": "audio.spectrum", "ts": 1759740000.123, "bands": [0-255 × 32], "rms": 0-255, "clap": false }
{ "type": "tts.spectrum",   "ts": ..., "bands": [...], "rms": ... }
{ "type": "activation.state", "state": "idle|listening|thinking|speaking|confirm" }
```

### 4.4 Animation model (UI side)

- The ring renders at the display refresh rate (≈60 fps) from the most recent frame. Each band value is smoothed with asymmetric easing: `attack = 0.55`, `release = 0.12` per frame, so bars jump up fast and fall slowly. Interpolate between 30 Hz frames so the motion is never steppy.
- If no frame arrives for 250 ms, ease all bars down to the idle state. Never freeze a stale spectrum.

### 4.5 States

|Core state|Ring behaviour|
|---|---|
|`idle`|"Breathing": every bar sits at about 8–14% length, modulated by slow 2-D noise (period ≈ 6 s). The whole ring rotates clockwise at 0.02 rev/s. The mic spectrum is still mixed in at 35% gain, so loud sounds show faintly|
|`listening`|Full live mic spectrum at 100% gain. Rotation eases to 0. The outer dashed guide rotates counter-clockwise slowly|
|`thinking`|The bars drop to about 10%. A bright "comet" (a 40°-wide window where the bars reach 60% with a smooth falloff) sweeps clockwise at 0.8 rev/s, and the centre dot pulses at 1 Hz|
|`speaking`|Driven by `tts.spectrum` instead of the mic, with a slightly heavier stroke (+0.3px)|
|`confirm`|Bars hold at about 20%. The outer dashed guide blinks (500 ms on, 500 ms off), and a single short **accent** arc at 12 o'clock is the only coloured element on the left panel. Clicking the ring opens the pending confirmation card|
|Clap detected (`clap: true`)|A shockwave: one thin circle expands from `R0` to `1.2·R` and fades out over 450 ms. All bars also get a +30% impulse that decays|
|Core disconnected|Bars freeze at 5%, the ring desaturates to 30% ink, and the caption reads `CORE OFFLINE · retrying`|

### 4.6 Dev/demo mode

`friday-ui --mock` must drive the ring from a synthetic generator: pink noise plus a few moving formant peaks, cycling through every state every 4 s. Add `--mock-mic` to let the **UI** open the mic with `sounddevice` for local visual tuning only. This flag must refuse to start if the core is running, so there are never two mic owners.

---

## 5. Right section: tool specs

For every tile below, **Compact** is the grid state, **Expanded** is the opened panel, and **Data** names the core topic and actions. Icons are white line art on black (black on coral for tile A).

### B: Calendar

- **Icon:** a 7×5 dot grid. Today's dot is a filled circle, and a thin ring around it slowly orbits from dot to dot every 2 s while idle. On hover, the dots ripple outward from today with a staggered scale of 1→1.4→1.
- **Compact:** the glance line shows the next event and its relative time (`Standup · in 18 min`). Above it is a 7-day week strip of small mono day initials, with today underlined and dots under days that have events.
- **Expanded:** month view, with week and day views selectable.
    - **Month change:** the grid slides horizontally (±40px plus a fade). The day cells cascade in on a **diagonal stagger** (delay = (row + col) × 15 ms).
    - **Today:** its circle **draws itself** as a stroke from 0→360° over `slow` when the view opens.
    - **Event dots** pop in with OutBack after the cells land.
    - **Day view:** a "now" line in ink moves in real time, updated once per minute and animated between positions. Event blocks expand on click to show details.
    - **Switching views** (month→week→day): the selected cell morphs into the larger view as a shared element.
- **Data:** subscribe to `calendar.events` with a `{from, to}` window. Actions: `calendar.create`, `calendar.update` and `calendar.delete`. All go through the core's calendar tool and its confirmation tiers. The UI never talks to Google directly.

### C: Reminders

- **Icon:** a bell made of 3 nested ellipses plus a clapper dot. On idle, it does a tiny ±4° swing every 8 s. When a reminder is due it rings with a fast damped swing.
- **Compact:** a count of today's reminders and the next one (`Call lab · 15:30`).
- **Expanded:** a list grouped into Overdue, Today, Later. Each row has the text, a mono time and a snooze menu (5 min, 15 min, 1 h, tomorrow).
- **Due state:** the tile title row inverts (white background, black text) for 1.2 s and the bell rings. A card also appears in tile A.
- **Snooze animation:** the row slides right and fades out, then reappears in its new group.
- **Data:** `reminders` (snapshot + deltas). Actions: `reminder.add`, `reminder.snooze`, `reminder.done`, `reminder.delete`.

### D: To-do list

These are the **user's** to-dos, as distinct from the AI task queue in G.

- **Icon:** three stacked rounded bars with a check circle on each. On idle, the top check slowly fills and empties. On hover, all three checks draw in sequence.
- **Compact:** `3 open · 1 due today`, plus the first open item.
- **Expanded:** a list with inline add (the input sits at the top and Enter adds the item). Items can be dragged to reorder. Each item can have a priority (shown as 1–3 small ticks) and a due date.
    - **Tick:** the checkbox draws its check as a stroke (`fast`), a strike-through line draws left→right across the text (`base`), the text fades to `dimOnTile`, and after 600 ms the row collapses and moves into a "Done" section.
    - **Untick:** the reverse of the above.
    - **Delete:** swipe or press Delete. The row collapses, and an undo toast stays in the tile for 5 s.
- **Data:** `todos`. Actions: `todo.add`, `todo.toggle`, `todo.reorder`, `todo.update`, `todo.delete`.

### A: Upcoming + Notifications (accent tile)

- **Icon** (black on coral): a horizon line with an arc rising above it, plus 3 small dots on the arc. The dots creep along the arc to suggest time passing. When a new notification arrives, the arc "pings" by scaling to 1.06 and back.
- **Compact:** the big centre of attention. It shows **one countdown**, the next item from any source (calendar, reminder or alarm), in large mono (`00:17:42`) with a label (`Standup`). Under it sits an **unread badge** with the notification count.
- **Expanded:** two columns.
    - **Upcoming:** a merged chronological timeline of the next 24 h across calendar, reminders and alarms. Each item has a source glyph. A vertical timeline line runs down the list and the "now" marker slides down it as time passes.
    - **Notifications:** messages from the core, such as Telegram messages, confirmations awaiting you, task results and system notices. New cards **drop in from the top with a spring** (OutBack 1.2). Swipe or click × to dismiss. Confirmation cards show the action, its tier, and **Approve / Deny** buttons. Approve and Deny send `confirm.respond` and the core decides. While a confirmation is pending, this tile shows a slow 2 s "breathing" brightness pulse.
- **Data:** `upcoming` (merged by the core, or by the UI from the three sources: pick one and document it) and `notifications`. Actions: `notification.dismiss`, `notification.read_all`, `confirm.respond`.

### E: Alarms

- **Icon:** a minimal clock face with 12 tick marks and one hand that sweeps continuously, one revolution per 60 s. On hover, the hand spins once quickly.
- **Compact:** the next alarm and a countdown (`07:00 · in 8 h 12 m`).
- **Expanded:** a list of alarms. Each row has a large mono time, a label, a repeat pattern (`M T W T F · ·`) and a **toggle switch** whose thumb slides with OutBack. Turning an alarm off dims its row to 40%.
- **Add:** a time picker made of two vertical scroll wheels for hours and minutes, with inertial snapping.
- **Ringing:** the **whole tile inverts** (white background, black text) and flashes at 1 Hz. The clock hand shakes. Large **Stop** and **Snooze** buttons replace the title. If the frontpage is open when an alarm rings, the HUD ring also shows the `confirm`-style accent arc.
- **Data:** `alarms`. Actions: `alarm.add`, `alarm.toggle`, `alarm.update`, `alarm.delete`, `alarm.stop`, `alarm.snooze`. The persistent scheduler in the core rings alarms even when the UI is closed. The UI only mirrors it.

### F: Music (Spotify on the local computer)

- **Icon:** a vinyl disc drawn as 5 concentric circles plus a label dot and a short tonearm line. **It rotates only while playing** at 33⅓ rpm (0.555 rev/s). On pause it eases to a stop over 800 ms, and on play it spins up over 400 ms. The tonearm lifts 6° on pause.
- **Compact:** the track title, scrolling as a marquee if it overflows (pausing 1.5 s at each end), with the artist in `dimOnTile`. A thin progress arc runs along the bottom edge of the tile. Clicking the icon toggles play/pause without opening the tile.
- **Expanded:** album art converted to **monochrome with a dither** (1-bit ordered dither, so it matches the line-art style), title, artist, a seek bar, prev / play-pause / next, a volume slider, and a shuffle/repeat state. Track change animation: the old art slides left and fades, and the new art slides in from the right.
- **Integration lives in the core**, as a new `media` provider. The UI never calls Spotify directly. Implement two backends:
    
    1. **Windows media session (primary, default).** Use `GlobalSystemMediaTransportControlsSessionManager` via the `winsdk`/`winrt` Python bindings. It reads now-playing info (title, artist, thumbnail, timeline) from the **Spotify desktop app already running on this PC** and sends play/pause/next/prev. It needs no API key and no login, and it works on free accounts. Filter sessions to Spotify's app ID, with a setting that allows any media session. On macOS/Linux, fall back to AppleScript/MPRIS respectively.
    2. **Spotify Web API (optional, adds seek, volume, queue and shuffle).** Use OAuth Authorization Code + PKCE with a loopback redirect on `127.0.0.1` and the token stored in the OS keyring. Target the local desktop app's Connect device ID. Note that the playback-control endpoints require Spotify Premium, and Spotify's developer-mode rules change, so check the current Spotify developer docs before relying on this.
    
    - The policy tier for media control is T0/T1 (no confirmation). Opening the Spotify app if it isn't running is a T1 launch.
- **Data:** `media.now_playing` (pushed on change, plus a position tick every 1 s that the UI interpolates locally). Actions: `media.play_pause`, `media.next`, `media.prev`, `media.seek`, `media.volume`, `media.shuffle`, `media.repeat`.
- **States:** `no_session` shows the disc at rest with the glance line `Spotify not running · Open`. Clicking it sends `media.launch`.

### G (merged column, top half): AI Task Queue

This is what **F.R.I.D.A.Y. itself** is doing or is about to do: agent jobs, routine runs, and multi-step tool sequences.

- **Header:** the letter `G`, the title `Task Queue`, and a mono summary on the right (`1 running · 3 queued`). An icon in the header area shows 3 stacked rounded rectangles that **slide up one slot every 3 s**, like a queue advancing.
- **List rows:** status glyph, title, source chip (`routine` / `you` / `agent`), and a right-aligned ETA or next-run time.
    - **Status glyphs:**
        - Queued: a hollow circle.
        - Running: a circle with a rotating 90° arc.
        - Awaiting confirmation: an **accent** dot that pulses.
        - Done: a check that draws itself.
        - Failed: a cross, with a 3× horizontal shake.
    - **Running row:** a thin **indeterminate shimmer** line runs along the bottom of the row, or a determinate bar if the core reports progress. Expanding the row shows the live tool steps as they stream in, each step fading in, so you can watch it work.
    - **Interactions:**
        - Click: expand or collapse the details (steps, input, result, logs link).
        - Drag a _queued_ row to reorder it: `agent_task.reorder`. Rows displace smoothly.
        - Row hover actions: pause, resume and cancel (`agent_task.pause`, `agent_task.resume`, `agent_task.cancel`). Cancelling a running task asks inline: `Cancel? Yes / No`.
        - Routines appear in a "Routines" sub-section with on/off toggles (`routine.toggle`).
    - **Completion:** the check draws, the row holds for 1.5 s, then it collapses into a "Recent" section capped at 10 items.
- **Data:** `agent.tasks` (snapshot + deltas: `added`, `updated`, `step`, `removed`) and `routines`.

### H (merged column, bottom half): AI Commands

These are **standing instructions to the AI**: recurring and queued commands, such as `08:00 daily → brief me on calendar + GitHub`, `on wake → read today's reminders` or `every 2 h → check the lab inbox`.

- **Header:** the letter `H`, the title `Commands`, and a mono `+ New` button.
- **Rows:**
    - The command text in **mono**, like a terminal line with a `›` prompt glyph.
    - A trigger chip: `cron 0 8 * * *` rendered human-readable as `daily 08:00`, or `on wake` / `on clap` / `on connect` / `once 14:30`.
    - A **countdown ring**: a small circle that empties toward the next fire time.
    - The last result: `ok 2 h ago` or `failed`, in `dimOnTile`.
- **Firing animation:** at fire time the countdown ring completes, the row background flashes to `#1E1E1E`, and a thin **pulse travels left→right** along the row's bottom edge. A matching task row then appears in G, which shows the hand-off from command to task.
- **New command:** the input opens inline at the top. The typed text is mirrored into a preview line with a typewriter cursor, and a parsed-schedule preview shows under it (`→ every weekday at 07:45`). Saving sends `command.create`, and **the core validates it and may return a confirmation card**, because standing commands can trigger tools.
- **Row actions:** run now (`command.run_now`, subject to policy), pause/resume, edit, delete.
- **Data:** `commands`. Actions: `command.create`, `command.update`, `command.delete`, `command.pause`, `command.resume`, `command.run_now`.

---

## 6. WebSocket protocol additions

The base protocol (auth token, envelope and reconnect) is defined by the core in `channels/ui_ws`. The frontpage needs the following:

- **Subscribe:** `{ "type": "subscribe", "topics": ["activation.state", "audio.spectrum", "tts.spectrum", "calendar.events", "reminders", "todos", "alarms", "media.now_playing", "notifications", "upcoming", "agent.tasks", "routines", "commands"] }`
- **Snapshot then deltas:** for every list topic, the core first sends `{type, op:"snapshot", items:[...]}` and then sends `{type, op:"add"|"update"|"remove"|"move", item|id, index?}`. Every item has a stable `id`, which is what lets list transitions animate correctly.
- **Actions:** `{ "type": "action", "id": "<uuid>", "name": "todo.toggle", "args": {...} }`. The core replies `{type:"action.result", id, ok, error?}` or sends a `confirm.request`.
- **Optimistic UI:** cheap, reversible actions (toggle to-do, snooze, play/pause, alarm toggle) update the UI immediately and roll back with a shake if the result is `ok:false`. Any action that can produce a confirmation is **not** optimistic.
- **Reconnect:** use exponential backoff (0.5 s → 8 s). While disconnected, tiles show their last data at 60% opacity with a small `offline` tag, and actions are disabled.
- **Taint:** items the core marks `untrusted` (written on a tainted turn) are rendered as **plain text only**, with no links and no rich text, and they carry a small `⚠ external` tag. This keeps the stored-injection protections intact in the UI.

---

## 7. File layout

```
friday/ui/frontpage/
├── __init__.py
├── app.py                 # registers types, loads Main.qml, wires the WS client
├── ws_client.py           # QObject: connects, subscribes, exposes models + action()
├── models/                # QAbstractListModel per topic (stable ids, delta apply)
│   ├── todos_model.py  reminders_model.py  alarms_model.py  calendar_model.py
│   ├── notifications_model.py  upcoming_model.py  agent_tasks_model.py  commands_model.py
│   └── media_state.py
├── hud/
│   ├── ring_item.py       # QQuickPaintedItem (or QSG node): bars, guides, states
│   └── spectrum_smoother.py
├── mock/
│   └── mock_core.py       # in-process fake core for --mock (all topics + spectrum)
└── qml/
    ├── Main.qml  Theme.qml  Frame.qml (rules, divider, footer)
    ├── HudPanel.qml
    ├── Tile.qml           # shared anatomy + open/close morph
    ├── tiles/ CalendarTile.qml RemindersTile.qml TodoTile.qml UpcomingTile.qml
    │          AlarmsTile.qml MusicTile.qml TaskQueuePane.qml CommandsPane.qml
    ├── icons/ (one QML Shape per icon, each with idle + hover animations)
    └── components/ Odometer.qml Toggle.qml CheckDraw.qml CountdownRing.qml Marquee.qml TimeWheel.qml

friday/sensors/spectrum.py        # core-side spectrum tap (section 4.3)
friday/tools/media/               # core-side media provider (section 5F)
├── base.py  win_smtc.py  spotify_web.py  mpris.py  applescript.py
```

---

## 8. Build order

1. **Frame + theme + mock core.** Get the static layout pixel-matched to section 1 at 1920×1080, 2560×1440 and 1280×800, with `--mock` feeding every topic.
2. **HUD ring** on mock spectrum, with all states and the clap shockwave. Tune the smoothing.
3. **Tile shell**: anatomy, hover, open/close morph, keyboard navigation, reduced motion.
4. **Tiles**, in this order: To-do → Alarms → Reminders → Calendar → Upcoming/Notifications → Task Queue → Commands → Music.
5. **Core side:** the `spectrum.py` tap and the `media` provider (Windows SMTC first), then the WS topics and actions above.
6. **Swap mock for the live core.** Then run the acceptance checklist.

---

## 9. Performance budget

- 60 fps sustained with the ring live and one tile expanded, on an integrated GPU (for example an Intel Iris Xe laptop).
- UI process CPU below 4% idle and below 10% while listening. Core spectrum tap below 1% CPU.
- When the window is minimised or hidden, stop the ring rendering, the icon loops and the spectrum subscription (send `unsubscribe`).
- No per-frame allocations in `ring_item.py`: preallocate the arrays and reuse the `QPainterPath`/geometry objects.

---

## 10. Acceptance checklist

- [ ] The layout matches section 1 proportions at the three test resolutions, and the column-3 tile is **one** rounded rectangle split into two equal halves.
- [ ] Nothing from the reference poster's artwork, text or branding appears. All icons are original line art.
- [ ] The HUD ring is monochrome, has 256 bars from 32 mirrored bands × 4 repeats, reacts to the voice within about 50 ms of perceived latency, and shows all 5 states, the clap shockwave and the offline state.
- [ ] The UI never opens the mic except under `--mock-mic`, and `--mock-mic` refuses to run when the core is up.
- [ ] Every tile has a compact glance line, an expanded view, an idle icon animation and a hover icon animation.
- [ ] The calendar shows the diagonal cascade, the self-drawing today ring and the live now-line. To-do shows the check draw and strike-through. The task queue shows the shimmer, live steps, drag reorder and completion collapse. Commands show the countdown rings and the fire pulse handing off to G.
- [ ] Music shows now-playing from the Spotify desktop app through the Windows media session with no API key. Play/pause, next and prev work, and the disc spins only while playing.
- [ ] Every mutating action goes through the core. Confirmation cards render in tile A, and Approve/Deny round-trip.
- [ ] Untrusted items render as plain text with an `external` tag.
- [ ] The reduced-motion mode, keyboard-only use and dark mode all work.
- [ ] The `--mock` mode exercises every state of every tile within 60 s.
- [ ] The performance budget in section 9 is met, and the measurements are recorded in the PR.