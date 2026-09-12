"""Capture the current tape for a new scheduled, independent-seed comparison."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    output=root/'output/comparisons'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    subprocess.run([sys.executable,str(root/'scripts/compare_policies.py'),'active','--observations','1000','--output',str(output)],check=True)
