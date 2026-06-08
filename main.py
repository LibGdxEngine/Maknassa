"""Entry point: python main.py {login|scrape|block|unblock|block-url|unblock-url|inspect} ...

Run `python main.py <command> --help` for each command's options.
"""

from __future__ import annotations

import sys

from reactions.cli import main

if __name__ == "__main__":
    sys.exit(main())
