# SPDX-License-Identifier: EUPL-1.2
"""Z-18c: tools.deployed – deployed files vs. deploy/ and the manifest of the last installation (temporary /etc)."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tools import deployed as D

ROOT = Path(__file__).resolve().parent.parent


class DeployedTest(unittest.TestCase):
    def setUp(self):
        self.etc = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.etc)
        for d in ('systemd/system', 'nginx/sites-available', 'nginx/sites-enabled', 'morse-trainer'):
            (self.etc / d).mkdir(parents=True)
        (self.etc / 'morse-trainer/site.env').write_text('MORSE_HOME_URL=https://10.0.0.2/\nMORSE_PUBLIC_URL=https://x.example.net:443/a\n')
        for path, expected, _opt in D.targets(ROOT, self.etc):   # a fresh installation
            path.write_bytes(expected)
        os.symlink(self.etc / 'nginx/sites-available/morse-trainer', self.etc / 'nginx/sites-enabled/morse-trainer')

    def states(self):
        return dict(D.check(ROOT, self.etc)[1])

    def write_manifest(self):
        (self.etc / D.MANIFEST).write_text(json.dumps(D.record(ROOT, self.etc)))

    def test_public_host(self):
        self.assertEqual(D.public_host('MORSE_PUBLIC_URL=https://x.example.net:443/a\n'), 'x.example.net')
        self.assertEqual(D.public_host('MORSE_LAN=10.0.0.0/24\n'), '')
        self.assertEqual((self.etc / 'morse-trainer/pinggy-host.map').read_text(), 'x.example.net 1;\n')

    def test_unit_rendered_like_install_unit(self):
        unit = (self.etc / 'systemd/system/morse-trainer.service').read_text()
        self.assertNotIn('@', unit.split('[Service]')[1].split('#')[0])
        self.assertIn(f'WorkingDirectory={ROOT}', unit)

    def test_fresh_install_ok(self):
        self.write_manifest()
        self.assertEqual(set(self.states().values()), {'ok'})

    def test_outdated_vs_edited(self):
        unit = self.etc / 'systemd/system/morse-trainer.service'
        unit.write_text(unit.read_text() + '# older version\n')
        self.write_manifest()                      # installed like this → deploy/ is newer
        self.assertEqual(self.states()[str(unit)], 'outdated')
        nginx = self.etc / 'nginx/sites-available/morse-trainer'
        nginx.write_text(nginx.read_text() + '# by hand\n')   # changed after the installation
        self.assertEqual(self.states()[str(nginx)], 'edited')

    def test_without_manifest_and_missing(self):
        unit = self.etc / 'systemd/system/morse-trainer.service'
        unit.write_text('x')
        (self.etc / 'systemd/system/morse-pinggy.service').unlink()
        (self.etc / 'morse-trainer/pinggy-proxy.conf').unlink()
        st = self.states()
        self.assertEqual(st[str(unit)], 'differs')
        self.assertEqual(st[str(self.etc / 'systemd/system/morse-pinggy.service')], 'missing-optional')
        self.assertEqual(st[str(self.etc / 'morse-trainer/pinggy-proxy.conf')], 'missing')

    def test_nginx_links(self):
        (self.etc / 'nginx/sites-enabled/morse-trainer').unlink()
        os.symlink('/nowhere', self.etc / 'nginx/sites-enabled/default')
        st = self.states()
        self.assertEqual(st[str(self.etc / 'nginx/sites-enabled/morse-trainer')], 'not-linked')
        self.assertEqual(st[str(self.etc / 'nginx/sites-enabled/default')], 'present')

    def test_record_has_no_secrets(self):
        rec = D.record(ROOT, self.etc)
        self.assertTrue(all(len(v) == 64 for v in rec['files'].values()))   # only hashes
        self.assertFalse(any('pki' in k or 'pinggy.env' in k for k in rec['files']))


if __name__ == '__main__':
    unittest.main()
