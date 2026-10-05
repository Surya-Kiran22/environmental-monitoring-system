"""Required system test scenarios TC-01 … TC-08 (see docs/TEST_RESULTS.md for the documented run)."""
import pytest

from tests.scenarios import ALL


@pytest.mark.parametrize("scenario", ALL, ids=[f.__name__.upper().replace("TC", "TC-") for f in ALL])
def test_scenario(client, scenario):
    rec = scenario(client)
    assert rec["passed"], rec
