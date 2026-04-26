"""Allow `python -m codeatlas` invocation."""
import sys
from codeatlas.cli import main

if __name__ == "__main__":
    sys.exit(main())
