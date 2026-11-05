# SPDX-License-Identifier: EUPL-1.2
"""Produkční spuštění přes waitress (za nginx reverzní proxy)."""
from waitress import serve

from server.app import app

if __name__ == "__main__":
    # Jen localhost – ven se jde výhradně přes nginx (TLS).
    serve(app, host="127.0.0.1", port=8080, threads=4, trusted_proxy="127.0.0.1",
          trusted_proxy_headers="x-forwarded-proto x-forwarded-for", ident=None)
