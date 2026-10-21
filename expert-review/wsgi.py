"""Single trusted reverse proxy; Gunicorn must bind only to loopback."""
import os
import re
from werkzeug.middleware.proxy_fix import ProxyFix
from app import create_app


def server_app():
    public_host = os.environ.get('REVIEW_PUBLIC_HOST', '').strip().lower()
    if public_host and not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', public_host):
        raise ValueError('REVIEW_PUBLIC_HOST must be a hostname without scheme, path or port')
    directory = os.environ['REVIEW_DATA_DIR']
    if not os.path.isabs(directory):
        raise ValueError('REVIEW_DATA_DIR must be an absolute persistent directory')
    app = create_app({
        'DATA_DIR': directory,
        'TRUSTED_HOSTS': ['localhost', '127.0.0.1'] + ([public_host] if public_host else []),
        'ENABLE_DEMO': os.environ.get('REVIEW_ENABLE_DEMO', '0') == '1',
    })
    # Caddy overwrites forwarded IP/proto. Do not trust a forwarded Host header.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0, x_prefix=0)
    return app
