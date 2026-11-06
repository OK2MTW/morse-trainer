# SPDX-License-Identifier: EUPL-1.2
"""Addresses of a particular installation (E3) – not in the code, read from /etc/morse-trainer/site.env (template
deploy/site.env.example).

Environment variables take precedence (tests, development). The file is not secret (addresses only), secrets belong elsewhere.
"""
import os
from urllib.parse import urlsplit

SITE_ENV = os.environ.get("MORSE_SITE_ENV", "/etc/morse-trainer/site.env")


def _load(path):
    vals = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip().strip('"\'')
    except OSError:
        pass
    return vals


_file = _load(SITE_ENV)


def get(name):
    return os.environ.get(name, _file.get(name, ""))


def _url(name):
    u = get(name)
    return u if not u or u.endswith("/") else u + "/"


HOME_URL = _url("MORSE_HOME_URL")      # e.g. https://192.168.x.y/
PUBLIC_URL = _url("MORSE_PUBLIC_URL")  # e.g. https://<subdomain>.a.pinggy.link/ (empty = home network only)
PUBLIC_HOSTS = tuple(h for h in (urlsplit(PUBLIC_URL).hostname,) if h)
