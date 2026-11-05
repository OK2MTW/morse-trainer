# SPDX-License-Identifier: EUPL-1.2
"""Adresy konkrétní instalace (E3) – nejsou v kódu, čtou se z /etc/morse-trainer/site.env (vzor deploy/site.env.example).

Proměnné prostředí mají přednost (testy, vývoj). Soubor není tajný (jen adresy), tajné údaje patří jinam.
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


HOME_URL = _url("MORSE_HOME_URL")      # např. https://192.168.x.y/
PUBLIC_URL = _url("MORSE_PUBLIC_URL")  # např. https://<subdomena>.a.pinggy.link/ (prázdné = jen domácí síť)
PUBLIC_HOSTS = tuple(h for h in (urlsplit(PUBLIC_URL).hostname,) if h)
