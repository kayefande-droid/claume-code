"""Allow ``python -m claume``."""
from .cli import main
import sys

sys.exit(main())
