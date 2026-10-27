"""ASGI entry point: uvicorn goldenstock.main:app."""
from goldenstock.api import create_app
from goldenstock.ui import mount_ui

app = create_app()
mount_ui(app)
