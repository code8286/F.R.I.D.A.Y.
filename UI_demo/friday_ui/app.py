# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Entry point of the frontpage demo: registers the Python types, loads Main.qml and wires the mock core."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = "0.4.0"


def parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="friday-ui", description="F.R.I.D.A.Y. frontpage (interactive demo, mock core)")
    p.add_argument("--mock", action="store_true", default=True, help="drive everything from the in-process mock core (the default for the demo)")
    p.add_argument("--mock-mic", action="store_true", help="let the UI open the microphone for visual tuning (refuses if the core is running)")
    p.add_argument("--core-port", type=int, default=int(os.environ.get("FRIDAY_UI_PORT", "8765")), help="port of the core's UI WebSocket (for the --mock-mic check)")
    p.add_argument("--theme", choices=["system", "light", "dark"], default="dark")
    p.add_argument("--reduced-motion", action="store_true")
    p.add_argument("--size", default="", help="window size, e.g. 1920x1080")
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--no-script", action="store_true", help="skip the 60 s demo script (notifications, reminder, alarm, command fire)")
    p.add_argument("--no-cycle", action="store_true", help="do not cycle the HUD through its states every 4 s")
    p.add_argument("--repeats", type=int, choices=[2, 4, 6], default=4, help="HUD ring pattern repeats")
    p.add_argument("--no-hint", action="store_true", help="hide the 'F1: demo controls' hint")
    p.add_argument("--no-caption", action="store_true", help="hide the state caption under the ring")
    p.add_argument("--fetch-fonts", action="store_true", help="download the two OFL fonts (Space Grotesk, JetBrains Mono) into assets/fonts, then start")
    p.add_argument("--open", default="", help=argparse.SUPPRESS)
    p.add_argument("--screenshot", default="", help=argparse.SUPPRESS)
    p.add_argument("--at", type=int, default=2500, help=argparse.SUPPRESS)
    p.add_argument("--script-file", default="", help=argparse.SUPPRESS)
    return p.parse_args(argv)


FONTS = {
    "SpaceGrotesk[wght].ttf": "https://github.com/google/fonts/raw/main/ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf",
    "JetBrainsMono[wght].ttf": "https://github.com/google/fonts/raw/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
    "OFL-SpaceGrotesk.txt": "https://github.com/google/fonts/raw/main/ofl/spacegrotesk/OFL.txt",
    "OFL-JetBrainsMono.txt": "https://github.com/google/fonts/raw/main/ofl/jetbrainsmono/OFL.txt",
}


def fetch_fonts() -> None:
    import urllib.request

    dest = HERE / "assets" / "fonts"
    dest.mkdir(parents=True, exist_ok=True)
    for name, url in FONTS.items():
        target = dest / name
        if target.exists() and target.stat().st_size > 1000:
            continue
        try:
            with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 - fixed https URLs above
                data = r.read(20_000_000)
            target.write_bytes(data)
            print(f"fonts: saved {name} ({len(data) // 1024} KB)")
        except OSError as exc:
            print(f"fonts: could not download {name}: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    if args.fetch_fonts:
        fetch_fonts()
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon
        from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance, qmlRegisterSingletonType, qmlRegisterType
    except ImportError:
        print("PySide6 is not installed. Install it with:\n    python -m pip install PySide6", file=sys.stderr)
        return 2

    from .bridge import Bridge
    from .art import ArtProvider
    from .hud.ring_item import HudRing
    from .mock.mock_core import MockCore

    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("friday-ui")
    app.setOrganizationName("friday")
    icon = HERE / "assets" / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    fams = set()
    for f in sorted((HERE / "assets" / "fonts").glob("*.[ot]tf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            fams.update(QFontDatabase.applicationFontFamilies(fid))

    if not {"Space Grotesk", "JetBrains Mono"} <= fams:
        print("note: Space Grotesk / JetBrains Mono not found, using system fonts. Run once with --fetch-fonts to get them.", file=sys.stderr)

    mic = None
    if args.mock_mic:
        from .hud.mic_tap import MicTap, core_is_running

        if core_is_running(args.core_port):
            print(f"--mock-mic refused: a core is listening on 127.0.0.1:{args.core_port}. The core owns the microphone; "
                  "there must never be two.", file=sys.stderr)
            return 3

    core = MockCore(script=not args.no_script, cycle=not args.no_cycle)
    bridge = Bridge(core)
    if args.mock_mic:
        try:
            mic = MicTap(bridge.feed_external)
            mic.start()
            core.set_external_mic(True)
            core.cycle = False
            core.state = "listening"
        except Exception as exc:  # noqa: BLE001
            print(f"--mock-mic: could not open the microphone ({type(exc).__name__}: {exc}). Needs: pip install sounddevice numpy", file=sys.stderr)
            mic = None

    qmlRegisterType(HudRing, "Friday", 1, 0, "HudRing")
    qmlRegisterSingletonInstance(Bridge, "Friday", 1, 0, "Core", bridge)
    qmlRegisterSingletonType(QUrl.fromLocalFile(str(HERE / "qml" / "theme" / "Theme.qml")), "Friday", 1, 0, "Theme")

    engine = QQmlApplicationEngine()
    engine.addImageProvider("art", ArtProvider())
    w, h = 0, 0
    if "x" in args.size:
        try:
            w, h = (int(x) for x in args.size.lower().split("x", 1))
        except ValueError:
            w, h = 0, 0
    engine.setInitialProperties({
        "startWidth": w, "startHeight": h, "startFullscreen": args.fullscreen, "version": VERSION,
        "themeChoice": args.theme, "reducedMotionFlag": args.reduced_motion, "showHint": not args.no_hint,
        "showCaption": not args.no_caption, "ringRepeats": args.repeats, "openAtStart": args.open.upper(),
        "fontsLoaded": sorted(fams), "testMode": bool(args.screenshot),
    })
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Main.qml")))
    if not engine.rootObjects():
        print("failed to load the UI (see the QML errors above)", file=sys.stderr)
        return 1
    win = engine.rootObjects()[0]

    if mic is not None:
        t = QTimer(app, interval=33, timeout=mic.poll)
        t.start()

    if args.script_file:          # test hook: run a small script of UI actions (used by the build's screenshot checks)
        from .testhook import run_script

        run_script(app, win, bridge, core, args.script_file)
    elif args.screenshot:
        def shot() -> None:
            img = win.grabWindow()
            img.save(args.screenshot)
            app.quit()

        QTimer.singleShot(args.at, shot)

    rc = app.exec()
    if mic is not None:
        mic.stop()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
