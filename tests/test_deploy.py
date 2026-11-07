# SPDX-License-Identifier: EUPL-1.2
"""E2: checks of the deployment files for public access (Pinggy) – nothing may listen outside, no secrets in git."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NGINX = (ROOT / 'deploy/nginx-morse-trainer.conf').read_text(encoding='utf-8')
UNIT = (ROOT / 'deploy/morse-pinggy.service').read_text(encoding='utf-8')


class TestPinggyDeploy(unittest.TestCase):
    def public_block(self):
        i = NGINX.index('E2/E3: public access via Pinggy')
        return NGINX[i:]

    def test_public_listener_localhost_only(self):
        listens = re.findall(r'^\s*listen\s+([^;]+);', self.public_block(), re.M)
        self.assertEqual(listens, ['127.0.0.1:8090'])

    def test_public_listener_guards(self):
        b = self.public_block()
        for must in ('set_real_ip_from 127.0.0.1;', 'real_ip_recursive off;', 'return 444;',
                     'location = /ca.crt { return 404; }', 'zone=morse_pub_auth'):
            self.assertIn(must, b)
        self.assertIn('X-Forwarded-For $remote_addr;', (ROOT / 'deploy/pinggy-proxy.conf').read_text())

    def test_tunnel_targets_only_public_listener(self):
        self.assertIn('-R0:127.0.0.1:8090', UNIT)
        self.assertEqual(len(re.findall(r'-R\S+', UNIT)), 1)
        self.assertIn('EnvironmentFile=/etc/morse-trainer/pinggy.env', UNIT)
        self.assertIn('${PINGGY_TOKEN}@', UNIT)   # the token only from the env file
        self.assertNotIn('b:', UNIT)               # no password on Pinggy (Chrome would not send it when installing the PWA)
        self.assertIn(' x:https', UNIT)           # only HTTPS on the Pinggy side
        self.assertIn('User=@USER@', UNIT)        # filled in by deploy/common.sh on installation

    def test_no_shared_password(self):
        # E3: login is protected only by the app accounts (no shared password, no exceptions)
        b = self.public_block()
        self.assertNotIn('auth_basic', b)
        self.assertIn('include /etc/morse-trainer/pinggy-host.map;', b)   # the name from the configuration, not from git
        self.assertIn('zone=morse_pub_auth_all', b)                      # a cap on logins from all IPs
        self.assertIn('limit_conn morse_pub_conn_all', b)
        proxy = (ROOT / 'deploy/pinggy-proxy.conf').read_text()
        self.assertIn('proxy_set_header X-Morse-Entry public;', proxy)
        lan = NGINX[:NGINX.index('E2/E3: public access')]
        self.assertEqual(lan.count('proxy_pass'), lan.count('proxy_set_header X-Morse-Entry "";'))

    def test_install_ships_proxy_headers(self):
        self.assertIn('pinggy-proxy.conf', (ROOT / 'deploy/install.sh').read_text(encoding='utf-8'))


    def test_app_never_returns_401(self):
        # 0.8.1: a 401 makes the browser ask for a password for the domain – not logged in = 403 + auth
        for f in (ROOT / 'server').glob('*.py'):
            self.assertNotRegex(f.read_text(encoding='utf-8'), r'(,|=)\s*401\b', f.name)

if __name__ == '__main__':
    unittest.main()


class TrainerUnitTest(unittest.TestCase):
    """#26: the service keeps large (argon2) allocations out of the per-thread heaps."""

    def test_mmap_threshold(self):
        unit = (ROOT / 'deploy/morse-trainer.service').read_text(encoding='utf-8')
        self.assertIn('Environment=MALLOC_MMAP_THRESHOLD_=131072', unit)
        self.assertIn('MemoryMax=120M', unit)
