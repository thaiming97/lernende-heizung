"""Test-Setup. Unter Windows (nur Entwicklung) braucht die HA-Testumgebung Sockets für die Event-Loop."""

import sys

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


if sys.platform == "win32":
    import pytest_socket

    # Windows-Event-Loop braucht ein Socket-Paar; Netzwerkzugriffe testen wir hier ohnehin nicht.
    pytest_socket.disable_socket = lambda *a, **k: None


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Eigene Integration in allen Tests laden."""
    yield
