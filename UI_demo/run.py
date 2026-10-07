#!/usr/bin/env python3
# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0
"""Start the F.R.I.D.A.Y. frontpage demo:  python run.py   (python run.py --help for options)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from friday_ui.app import main  # noqa: E402

raise SystemExit(main())
