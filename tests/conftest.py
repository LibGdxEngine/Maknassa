"""Session-wide test isolation.

Sets ``MAKNASSA_DATA_DIR`` before any test (or the Streamlit AppTest script)
imports ``reactions``, redirecting all per-user data (db, profiles) into a
throwaway temp dir so tests never create or touch ``~/.local/share/Maknassa``.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("MAKNASSA_DATA_DIR", tempfile.mkdtemp(prefix="maknassa-tests-"))
