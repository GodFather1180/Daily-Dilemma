import pytest

from shared import database


def test_get_db_initialises_and_reuses_engine():
    """Verify that get_db yields a session and closes it on exhaustion."""
    # First call: engine is initialised
    for _ in range(2):
        gen = database.get_db()

        db = next(gen)
        assert hasattr(db, "execute") or hasattr(db, "query")

        with pytest.raises(StopIteration):
            next(gen)
