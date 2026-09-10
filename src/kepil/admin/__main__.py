"""python -m kepil.admin [порт]"""

import sys

from .app import serve

serve(int(sys.argv[1]) if len(sys.argv) > 1 else 7317)
