"""Allow `python -m mercator` invocation."""
import sys
from mercator.cli import main

if __name__ == "__main__":
    sys.exit(main())
