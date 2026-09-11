"""Public configuration module for HumanLLM.

The concrete environment-backed settings live in ``config_settings.py``.
This module remains the stable import location for ``from app.config import
settings`` used throughout the application.
"""
from app.config_settings import Settings, settings

__all__ = ["Settings", "settings"]
