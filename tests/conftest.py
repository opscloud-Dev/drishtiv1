"""
Test setup. These tests run against a REAL Postgres and WIPE it, so you must
point them at a dedicated, disposable database:

    createdb drishti_test
    TEST_DATABASE_URL=postgresql://localhost:5432/drishti_test pytest
"""
import os

import pytest

TEST_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_URL:
    pytest.exit(
        "Set TEST_DATABASE_URL to a dedicated, disposable Postgres database "
        "(its tables get dropped on every test).",
        returncode=2,
    )

# Must be set before the app is imported.
os.environ["DATABASE_URL"] = TEST_URL
os.environ["JWT_SECRET"] = "test-secret-only-never-use-in-production-0123456789"
os.environ["BCRYPT_ROUNDS"] = "4"  # fast hashing for tests only

from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402,F401
from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

if "test" not in (engine.url.database or ""):
    pytest.exit(
        f"Refusing to wipe database '{engine.url.database}': the name must "
        f"contain 'test'.",
        returncode=2,
    )


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
