# Frontpage UI demo (UI_demo) build log, 2026-10-06

Status: code complete, NOT yet run. Qt could not be installed in the cloud workspace or the linked PC shell (pypi.org and github.com blocked by the org egress policy), so nothing has been checked against friday-frontpage-mockup.png on screen yet. An independent review pass found 21 issues by reading the code (load-breaking FINAL-property clashes, the Theme singleton shadowing, a launch that never started under reduced motion, among others). All are fixed.

Run (Windows): `python -m pip install -r requirements.txt`, then `python run.py --fetch-fonts` the first time and `python run.py` after that. F1 shows the demo controls.

What it is: PySide6 + Qt Quick, laid out from the mockup's measurements (2000x1414 reference, fractional layout, u = min(W/2000, H/1414)). All eight tiles have compact and expanded interactive views. The HUD ring is 256 bars (32 mirrored bands x4) with every state, the clap shockwave and the offline mode. An in-process mock core speaks the brief's protocol: snapshot and deltas, actions, confirm cards for T2/T3, optimistic updates with rollback. A 60 s demo script runs at start.

Decisions: Upcoming is merged in the UI. The window minimum is 1280x760 (the stacked layout below 1100 px is deferred). Moving between calendar views cross-fades instead of a shared-element morph. The Theme singleton lives in qml/theme/. Fonts are fetched once with --fetch-fonts, because the cloud can't download them.

Next: run on the PC, compare with the mockup, fix what shows up, then port into friday/ui/frontpage/ with ws_client.py replacing the mock (tranche 4).
