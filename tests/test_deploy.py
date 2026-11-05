# SPDX-License-Identifier: EUPL-1.2
"""E2: kontrola nasazovacích souborů veřejného přístupu (Pinggy) – nic nesmí poslouchat ven, žádná tajemství v gitu."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NGINX = (ROOT / 'deploy/nginx-morse-trainer.conf').read_text(encoding='utf-8')
UNIT = (ROOT / 'deploy/morse-pinggy.service').read_text(encoding='utf-8')


class TestPinggyDeploy(unittest.TestCase):
    def public_block(self):
        i = NGINX.index('E2/E3: veřejný přístup přes Pinggy')
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
        self.assertIn('${PINGGY_TOKEN}@', UNIT)   # token jen z env souboru
        self.assertNotIn('b:', UNIT)               # žádné heslo na Pinggy (Chrome by ho při instalaci PWA neposlal)
        self.assertIn(' x:https', UNIT)           # jen HTTPS na straně Pinggy
        self.assertIn('User=@USER@', UNIT)        # doplní deploy/common.sh při instalaci

    def test_no_shared_password(self):
        # E3: přihlášení chrání jen účty aplikace (žádné sdílené heslo, žádné výjimky)
        b = self.public_block()
        self.assertNotIn('auth_basic', b)
        self.assertIn('include /etc/morse-trainer/pinggy-host.map;', b)   # jméno z konfigurace, ne z gitu
        self.assertIn('zone=morse_pub_auth_all', b)                      # strop přihlášení ze všech IP
        self.assertIn('limit_conn morse_pub_conn_all', b)
        proxy = (ROOT / 'deploy/pinggy-proxy.conf').read_text()
        self.assertIn('proxy_set_header X-Morse-Entry public;', proxy)
        lan = NGINX[:NGINX.index('E2/E3: veřejný přístup')]
        self.assertEqual(lan.count('proxy_pass'), lan.count('proxy_set_header X-Morse-Entry "";'))

    def test_install_ships_proxy_headers(self):
        self.assertIn('pinggy-proxy.conf', (ROOT / 'deploy/install.sh').read_text(encoding='utf-8'))


    def test_app_never_returns_401(self):
        # 0.8.1: 401 vyvolá v prohlížeči dotaz na heslo k doméně – nepřihlášen = 403 + auth
        for f in (ROOT / 'server').glob('*.py'):
            self.assertNotRegex(f.read_text(encoding='utf-8'), r'(,|=)\s*401\b', f.name)

if __name__ == '__main__':
    unittest.main()
