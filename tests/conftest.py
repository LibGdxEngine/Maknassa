"""Session-wide test isolation.

Two env vars are set before any test (or the Streamlit AppTest script) imports
``reactions``:

* ``MAKNASSA_DEV=1``     -- bypass the licence gate so UI/CLI tests don't need a key.
* ``MAKNASSA_DATA_DIR``  -- redirect all per-user data (db, profiles, licence) into
  a throwaway temp dir, so tests never create or touch ``~/.local/share/Maknassa``.

Individual licence tests opt back out by clearing these via ``monkeypatch``.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("MAKNASSA_DEV", "1")
os.environ.setdefault("MAKNASSA_DATA_DIR", tempfile.mkdtemp(prefix="maknassa-tests-"))
