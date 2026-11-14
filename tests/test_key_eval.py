# SPDX-License-Identifier: EUPL-1.2
"""1.1 K1: regression ceilings of decoding a real hand (tools/key_eval.py, tests/stations.py). Fast – one seed, a few
simulated operators and the recordings `klic` from tests/data. Ceilings = baseline 1.0.3 (seed 0) + a reserve; a
better reader (K2, K3) lowers them, a worse one fails here."""
import unittest

from tests import stations as S
from tools import key_eval as K

# station: {metric: ceiling in %}; seed 0 – baseline 1.0.3: norma 0/0, tesny cer 8.5 vo 6.4, zacatecnik cer 19.8 vo 14.8;
# 1.1 K2 (gap model): tesny cer 0.3 vo 0.3, zacatecnik cer 11.3 vo 7.7
CEILINGS = {
    'norma': {'cer': 0.5, 'vo': 0.5, 'chr': 0.5},
    'tesny': {'cer': 2.0, 'vo': 1.5, 'chr': 1.0},
    'zacatecnik': {'cer': 14.0, 'vo': 10.0, 'chr': 1.0},
}
# recordings of the HW key (tests/data/key_recordings_hw.json): cer warm ≤ ceiling; baseline 3.2 / 0.0
HW_WARM_CEIL = 5.0


class KeyEvalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = K.READERS[list(K.READERS)[-1]]
        stations = [st for st in S.STATIONS if st['name'] in CEILINGS]
        cls.rows = K.eval_stations(cls.reader, seeds=1, stations=stations)
        cls.recs = K.eval_recordings(cls.reader, K.file_recordings())

    def test_simulated_operators_within_ceilings(self):
        for name, ceil in CEILINGS.items():
            for metric, top in ceil.items():
                with self.subTest(station=name, metric=metric):
                    self.assertLessEqual(self.rows[name][metric], top)

    def test_hw_recordings_read_warm(self):
        hw = [r for r in self.recs if r['type'] == 'hw']
        self.assertTrue(hw)
        for r in hw:
            with self.subTest(src=r['src']):
                self.assertLessEqual(r['warm']['cer'], HW_WARM_CEIL)

    def test_simulator_truth_is_consistent(self):
        # the perfect station keyed exactly what was meant; every over has tones and gap classes
        over = next(iter(S.session(S.STATIONS[0], 0)))
        self.assertEqual(K.norm(over['keyed']), K.norm(over['meant']))
        self.assertTrue(over['tones'])

    def test_reader_is_k3(self):
        self.assertEqual(list(K.READERS)[-1], '1.1-k3')

    def test_edit_distance(self):
        self.assertEqual(K.edit_distance('QRS', 'QRS'), 0)
        self.assertEqual(K.edit_distance('QR S', 'QRS'), 1)
        self.assertEqual(K.edit_distance('', 'AB'), 2)


if __name__ == '__main__':
    unittest.main()
