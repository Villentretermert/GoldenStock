import pytest
from pydantic import ValidationError
from goldenstock.config import Settings


@pytest.mark.parametrize("origin,secure", [("https://pilot.example",False), ("http://127.0.0.1:8081",True)])
def test_inconsistent_transport_credentials_rejected(origin,secure):
    with pytest.raises(ValidationError, match="HTTPS origins require Secure cookies"):
        Settings(_env_file=None,public_url=origin,secure_cookie=secure)
