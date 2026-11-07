# SPDX-License-Identifier: EUPL-1.2
"""ZB band sound lab: every preset and parameter has its texts (the JS itself is checked by ear by the coach)."""
import json
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


class BandTest(unittest.TestCase):
    def setUp(self):
        self.band = (WEB / "js" / "band.js").read_text()
        self.lab = (WEB / "js" / "bandlab.js").read_text()
        self.langs = {p.stem: json.loads(p.read_text()) for p in (WEB / "i18n").glob("*.json") if p.stem != "languages"}

    def test_presets_translated(self):
        block = re.search(r"export const BAND_PRESETS = \{(.*?)\n\};", self.band, re.S).group(1)
        ids = re.findall(r"^\s+(\w+): \{", block, re.M)
        self.assertGreaterEqual(len(ids), 8)
        for lang, d in self.langs.items():
            for i in ids:
                self.assertIn(f"band.preset.{i}", d, lang)
                self.assertIn(f"band.presetHint.{i}", d, lang)

    def test_params_known_and_translated(self):
        defaults = re.search(r"export const BAND_DEFAULTS = \{(.*?)\n\};", self.band, re.S).group(1)
        known = set(re.findall(r"^\s+(\w+):", defaults, re.M))
        sliders = re.findall(r"\['(\w+)', [0-9.]+, [0-9.]+, [0-9.]+\]", self.lab)
        self.assertGreaterEqual(len(sliders), 8)
        for k in sliders + ["filterBw"]:
            self.assertIn(k, known)
            for lang, d in self.langs.items():
                self.assertIn(f"band.param.{k}", d, lang)

    def test_ladder_bands_exist(self):
        """M9: every band situation of the copy-behind ladder exists in band.js and has a name on the server."""
        from server import coach
        block = re.search(r"export const BAND_LADDER = \{(.*?)\n\};", self.band, re.S).group(1)
        ids = set(re.findall(r"^\s+(\w+): \{", block, re.M))
        self.assertTrue(coach.COPY_BANDS)
        self.assertLessEqual(coach.COPY_BANDS, ids)
        for lang in ("cs", "en"):
            d = json.loads((WEB.parent / "server" / "i18n" / f"{lang}.json").read_text())
            for b in coach.COPY_BANDS:
                self.assertIn(f"coach.band.{b}", d, lang)

    def test_demo_bands_exist(self):
        """0.9.9: the band situations of the demo are lab presets (translated)."""
        demo = (WEB / "js" / "demoband.js").read_text()
        ids = re.findall(r"'(\w+)'", re.search(r"DEMO_BANDS = \[(.*?)\]", demo).group(1))
        block = re.search(r"export const BAND_PRESETS = \{(.*?)\n\};", self.band, re.S).group(1)
        presets = set(re.findall(r"^\s+(\w+): \{", block, re.M))
        self.assertTrue(ids)
        self.assertLessEqual(set(ids), presets)

    def test_band_ends_together(self):
        """#20: noise, static and other stations end together – common fade of the receiver, QRM cut at the end."""
        num = lambda name: float(re.search(rf"const {name} = ([0-9.]+);", self.band).group(1))
        self.assertGreater(num("NOISE_TAIL"), num("BAND_FADE"))  # the main station's last tone is never faded
        self.assertGreater(num("BAND_FADE"), 0.2)                # a smooth fade, not a click
        self.assertNotRegex(self.band, r"to - 3\b")              # the old start condition of QRM messages
        self.assertRegex(self.band, r"_station\(rx, \{ text: msg,[^}]*until: to")
        for fn in ("play(text, p", "playStream(items, p"):
            body = self.band.split(fn, 1)[1].split("\n  }\n", 1)[0]
            self.assertIn("this._fadeOut(end + NOISE_TAIL)", body, fn)
        self.assertIn("bandEnd", (WEB / "js" / "demoband.js").read_text())


if __name__ == "__main__":
    unittest.main()


class MaskTest(unittest.TestCase):
    """M9 part 2: characters masked by the band (tests/band.py = port of maskChars in band.js)."""
    FLAT = {'base': 1.0, 'lfo': []}

    def env(self, **kw):
        e = {'noise': 0.3, 'filterBw': 500, 'freq': 600, 'sampleRate': 48000, 'main': self.FLAT, 'qrm': [], 'qrn': []}
        e.update(kw)
        return e

    def test_js_shape(self):
        from tests import band as B
        for name in ('MASK_SNR', 'MASK_QRM_HZ', 'MASK_QRM_RATIO', 'MASK_QRN_RATIO'):
            self.assertIn(f'export const {name} = ', B.BAND_JS)
        self.assertIn('export function maskChars(', B.BAND_JS)
        self.assertIn('mask: mask[k]', B.BAND_JS)

    def test_clean_and_noise(self):
        from tests import band as B
        self.assertEqual(B.mask_chars([(0, 0.3)], self.env()), [None])
        self.assertEqual(B.mask_chars([(0, 0.3)], self.env(noise=0)), [None])
        # noise above the signal in the filter (SNR < 0 dB)
        self.assertEqual(B.mask_chars([(0, 0.3)], self.env(noise=1.2)), ['f'])
        # a wider filter lets in more noise
        self.assertEqual(B.mask_chars([(0, 0.3)], self.env(noise=0.8)), [None])
        self.assertEqual(B.mask_chars([(0, 0.3)], self.env(noise=0.8, filterBw=2400)), ['f'])

    def test_fading(self):
        from tests import band as B
        # deep fade: 1 - 0.9 + 0.9·sin → minimum 0.1 at t = 0.75 s with rate 1 Hz
        f = {'base': 0.55, 'lfo': [{'rate': 1, 'amp': 0.45, 'start': 0}]}
        self.assertAlmostEqual(B.fade_at(f, 0.75), 0.1)
        res = B.mask_chars([(0.2, 0.3), (0.7, 0.8)], self.env(main=f))
        self.assertEqual(res, [None, 'f'])

    def test_qrm(self):
        from tests import band as B
        st = {'off': 150, 'level': 0.5, 'keys': [[0.1, 0.2]], 'fade': self.FLAT}
        self.assertEqual(B.mask_chars([(0, 0.3), (0.3, 0.6)], self.env(qrm=[st])), ['m', None])  # overlap only
        self.assertEqual(B.mask_chars([(0, 0.3)], self.env(qrm=[{**st, 'off': -320}])), [None])  # outside the band
        self.assertEqual(B.mask_chars([(0, 0.3)], self.env(qrm=[{**st, 'level': 0.15}])), [None])  # weak
        self.assertLess(B.bandpass_gain(280, 600, 500), B.bandpass_gain(150, 600, 500))
        self.assertAlmostEqual(B.bandpass_gain(0, 600, 500), 1)

    def test_qrn(self):
        from tests import band as B
        self.assertEqual(B.mask_chars([(0, 0.3)], self.env(qrn=[[0.1, 7, 0.25]])), ['n'])  # strong crash
        self.assertEqual(B.mask_chars([(0, 0.3)], self.env(qrn=[[0.1, 2, 0.25]])), [None])  # below the signal
        self.assertEqual(B.mask_chars([(0, 0.3)], self.env(qrn=[[0.35, 7, 0.25]])), [None])  # after the character
        self.assertEqual(B.mask_chars([(0.3, 0.6)], self.env(qrn=[[0.0, 7, 0.06]])), [None])  # decayed before


class FreshContextTest(unittest.TestCase):
    """#25: nothing may be scheduled before context time 0 (a fresh AudioContext right after the page load)."""

    def test_lfo_start_clamped(self):
        band = (WEB / "js" / "band.js").read_text()
        self.assertIn("const ls = Math.max(ctx.currentTime, t0 - rng() * 5);", band)
        self.assertNotIn("lfo.start(t0 -", band)

    def test_error_carries_version(self):
        trace = (WEB / "js" / "trace.js").read_text()
        sw = (WEB / "sw.js").read_text()
        self.assertIn("ver: appVer", trace)
        self.assertIn("const CACHE = `morse-v${VERSION}-${ASSETS_HASH}`;", sw)  # the version is read from this name
