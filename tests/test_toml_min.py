# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""The fallback TOML parser must agree with tomllib on everything FRIDAY's config uses."""

import unittest

from friday.core import _toml_min as tm
from friday.core.config import DEFAULT_CONFIG_TOML

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None

SAMPLES = [
    DEFAULT_CONFIG_TOML,
    'a = 1\nb = -2.5\nc = true\nd = "x # not a comment" # real comment\ne = \'C:\\\\raw\\\\path\'\nf = [1, 2, 3,]\ng = ["a", "b#c"]\n[t.u]\nk = "v\\n\\u00e9\\"q\\""\n',
    '[s]\nids = []\nn = 1_000\nx = 1e3\n',
]


class MinTomlTests(unittest.TestCase):
    @unittest.skipIf(tomllib is None, "tomllib not available")
    def test_matches_tomllib(self):
        for text in SAMPLES:
            self.assertEqual(tm.loads(text), tomllib.loads(text), text[:40])

    def test_default_config_values(self):
        d = tm.loads(DEFAULT_CONFIG_TOML)
        self.assertIs(d["memory"]["enabled"], True)
        self.assertEqual(d["security"]["allowed_telegram_ids"], [])
        self.assertEqual(d["security"]["confirm_ttl_s"], 60)
        self.assertIs(d["security"]["voice_t3_requires_challenge"], True)

    def test_rejects_unsupported_instead_of_misreading(self):
        for bad in ['a = """multi\nline"""', 'a = [1,\n2]', '[[arr]]\nx=1', 'a = 1\na = 2', 'a = nope', 'just text',
                    'a = "unterminated', '[t\nx=1', 'a = "bad \\q escape"', 'a = 2024-01-01']:
            with self.assertRaises(tm.TOMLDecodeError, msg=bad):
                tm.loads(bad)

    def test_windows_path_in_literal_string(self):
        d = tm.loads("[tools]\nexe = 'C:\\Users\\me\\app.exe'\n")
        self.assertEqual(d["tools"]["exe"], "C:\\Users\\me\\app.exe")


if __name__ == "__main__":
    unittest.main()
