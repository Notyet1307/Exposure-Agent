from collections.abc import Generator

import pytest


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[None]:
    """Domain-only tests do not require the integration-test database."""
    yield
