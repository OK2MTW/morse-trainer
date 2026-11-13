# SPDX-License-Identifier: EUPL-1.2
"""Production run via waitress (behind the nginx reverse proxy)."""
from waitress import serve

from server import firmware
from server.app import app

if __name__ == "__main__":
    firmware.start_background()  # 0.15.0: daily check of the HW key firmware releases
    # Localhost only – the outside world goes exclusively through nginx (TLS).
    serve(app, host="127.0.0.1", port=8080, threads=4, trusted_proxy="127.0.0.1",
          trusted_proxy_headers="x-forwarded-proto x-forwarded-for", ident=None)
