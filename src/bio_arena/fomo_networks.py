"""FOMO page slugs, token-balance networks and Relay route networks."""
import json
from pathlib import Path
import re

NETWORKS = json.loads(Path(__file__).with_suffix('.json').read_text())


def valid_token_path(path):
    if not isinstance(path, str):
        return False
    match = re.fullmatch(r'/tokens/([a-z]+)/([a-zA-Z0-9]+)', path)
    if not match or match[1] not in NETWORKS:
        return False
    pattern = r'[1-9A-HJ-NP-Za-km-z]{32,44}' if match[1] == 'solana' else r'0x[0-9a-fA-F]{40}'
    return re.fullmatch(pattern, match[2]) is not None
