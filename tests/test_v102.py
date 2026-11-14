# SPDX-License-Identifier: EUPL-1.2
"""1.0.2 (Martin 2026-11-14): Sending in the main menu with own characters and tempo, Settings as collapsible topics,
appearance light / dark / system / day and night (per device), automatic key recording for the decoder (debug only)."""
import math
import re
import unittest
from datetime import date
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / 'web'
HTML = (WEB / 'index.html').read_text(encoding='utf-8')
MAIN = (WEB / 'js/main.js').read_text(encoding='utf-8')
THEME = (WEB / 'js/theme.js').read_text(encoding='utf-8')
AUTO = (WEB / 'js/keyauto.js').read_text(encoding='utf-8')
CSS = (WEB / 'css/app.css').read_text(encoding='utf-8')


def settings_section():
    a = HTML.index('<section id="view-settings"')
    return HTML[a:HTML.index('</section>', a)]


def sun_times(d, tz_off_min, std_off_min, lat=50):
    """Port of theme.js sunTimes (minutes after local midnight)."""
    lon = -std_off_min / 4
    day = (d - date(d.year, 1, 1)).days + 1
    g = 2 * math.pi / 365 * (day - 1)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    cos_h = math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)
    ha = math.degrees(math.acos(max(-1, min(1, cos_h))))
    noon = 720 - 4 * lon - eqt - tz_off_min
    return noon - 4 * ha, noon + 4 * ha


class SendingTest(unittest.TestCase):
    def test_menu_entry_and_no_settings_card(self):
        self.assertIn('<button type="button" data-go="key" class="keylab-only" hidden data-i18n="nav.send">', HTML)
        self.assertNotIn('data-go="key"', settings_section())

    def test_own_characters_and_tempo(self):
        self.assertIn('data-key="sendChars"', HTML)
        self.assertIn('data-key="sendWpm"', HTML)
        self.assertIn("getChars: () => charsForLevel(sendLvl())", MAIN)
        self.assertIn("if (!settings.sendWpm) { settings.sendWpm = settings.wpm; changed = true; }", MAIN)
        self.assertNotIn('SEND_MIN_CHARS, lvl()', MAIN)


class SettingsTest(unittest.TestCase):
    def test_collapsible_topics(self):
        sec = settings_section()
        self.assertNotIn('<div class="card', sec)
        n = sec.count('<details name="settings" class="card set-sec')
        self.assertEqual(n, sec.count('<summary><h2 '))
        self.assertGreaterEqual(n, 6)
        self.assertIn('settings.look', sec)


class ThemeTest(unittest.TestCase):
    def test_modes_and_css(self):
        self.assertIn("var MODES = ['system', 'light', 'dark', 'sun'];", THEME)
        self.assertIn('<script src="/js/theme.js"></script>', HTML)
        self.assertEqual(CSS.count('prefers-color-scheme'), 2)
        self.assertEqual(CSS.count(':root:not([data-theme="light"])'), 2)
        self.assertEqual(CSS.count(':root[data-theme="dark"] {'), 3)   # palette, heat map, color-scheme

    def test_sun_times_prague(self):
        r, s = sun_times(date(2026, 11, 14), -60, -60)
        self.assertLess(abs(r - (7 * 60 + 8)), 10)
        self.assertLess(abs(s - (16 * 60 + 18)), 10)
        r, s = sun_times(date(2026, 6, 21), -120, -60)
        self.assertLess(abs(r - (4 * 60 + 52)), 10)
        self.assertLess(abs(s - (21 * 60 + 14)), 10)


class KeyAutoTest(unittest.TestCase):
    def test_debug_only_and_limits(self):
        self.assertIn("if (!traceOn()) return;", AUTO)
        self.assertIn("tracePush('klic'", AUTO)
        consts = dict(re.findall(r'export const (AUTO_\w+) = (\d+);', AUTO))
        self.assertEqual(consts, {'AUTO_IDLE_MS': '20000', 'AUTO_MAX_TONES': '1500', 'AUTO_MIN_TONES': '12',
                                  'AUTO_MAX_ITEMS': '40'})
        # 1500 elements à ~35 bytes + 40 items stay well below the server limit
        self.assertLess(1500 * 40 + 40 * 2000, 200_000)


if __name__ == '__main__':
    unittest.main()
