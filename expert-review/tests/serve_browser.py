"""Disposable server: never uses the real study database."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app

with tempfile.TemporaryDirectory(prefix='competence-browser-') as directory:
    app = create_app({'DATA_DIR': directory, 'ADMIN_KEY': 'browser-test-only'})
    app.run(host='127.0.0.1', port=8767)
