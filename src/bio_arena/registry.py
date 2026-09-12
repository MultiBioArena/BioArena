"""Stable participant identities, independent of the current three display models."""
import hashlib
import re

DEFAULT_BIOS = ('worm', 'adult', 'larva')


def validate_bio_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', value):
        raise ValueError('Bio IDs must be safe lowercase identifiers of at most 32 characters')
    if value in ('all','market'):raise ValueError('Bio ID is reserved for a dashboard control')
    return value


def roster(config=None):
    values = (config or {}).get('competitors', list(DEFAULT_BIOS))
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 16:
        raise ValueError('Configure between one and sixteen competitors')
    keys = [validate_bio_id(value) for value in values]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate competitor ID')
    return keys


def seed_offset(bio, namespace):
    legacy = {'brain': {'worm': 11, 'adult': 23, 'larva': 37},
              'learner': {'worm': 7919, 'adult': 15401, 'larva': 23767}}
    validate_bio_id(bio)
    if bio in legacy.get(namespace, {}):
        return legacy[namespace][bio]
    return int.from_bytes(hashlib.sha256(f'{namespace}:{bio}'.encode()).digest()[:4], 'big')
