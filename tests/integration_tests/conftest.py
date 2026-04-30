import os

import pytest
from actual import Actual
from actual.queries import create_account

ACTUAL_TEST_URL = os.environ.get("ACTUAL_TEST_URL", "http://localhost:12012")


@pytest.fixture
def actual():
    with Actual(
        base_url=ACTUAL_TEST_URL,
        password="test",
        bootstrap=True,
    ) as actual:
        actual.create_budget("TestBudget")
        actual.upload_budget()
        acc = create_account(actual.session, "TestAccount")
        actual.commit()
        yield actual
        acc.delete()
        actual.delete_budget()
        actual.commit()
