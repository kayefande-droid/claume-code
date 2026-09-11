"""Console entry shim so ``claume`` works from PATH."""
import sys

from claume.cli import main

if __name__ == "__main__":
    sys.exit(main())
