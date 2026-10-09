"""Backwards-compatible launcher: ``pythonw live_captions.py`` still starts the app.

The code now lives in ``src/livecaptions``; prefer the ``livecaptions`` command.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from livecaptions.app import main  # noqa: E402

if __name__ == "__main__":
    main()
