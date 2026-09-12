"""Long-running storage, candidate rotation, and application cleanup regressions."""
import asyncio
from collections import defaultdict
import json
from pathlib import Path
import random
from types import SimpleNamespace

import pytest
import yaml

from bio_arena.arena import Arena
from bio_arena.meme_arena import MemecoinArena

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def recorded_arena(tmp_path):
    for bio in ('worm', 'adult', 'larva'):
        folder = tmp_path / 'data' / 'processed' / bio
        folder.mkdir(parents=True)
        for name in ('manifest.json', 'visual.json'):
            (folder / name).write_text('{}')
    config = yaml.safe_load((ROOT / 'configs/arena.yaml').read_text())
    arena = Arena(tmp_path, config)
    for seq in range(1, 201):
        bio = ('worm', 'adult', 'larva')[seq % 3]
        record = dict(id=str(seq), bio_id=bio, sequence=seq * 4,
                      created_at=seq, action='HOLD', score=0, spikes=1,
                      fill={'status': 'held'})
        arena.db.execute('INSERT INTO decisions VALUES (?,?,?,?,?)',
                         (str(seq), seq, bio, seq, json.dumps(record)))
    arena.sequence = 200
    arena.db.commit()
    try:
        yield arena
    finally:
        arena.db.close()
        arena.market_file.close()


def test_decision_queries_use_indexes_and_preserve_pagination(recorded_arena):
    arena = recorded_arena
    assert [row['id'] for row in arena.decisions(4)] == ['200', '199', '198', '197']
    page = arena.history('worm', limit=3)
    assert [row['event_sequence'] for row in page['items']] == [198, 195, 192]
    assert [row['sequence'] for row in page['items']] == [792, 780, 768]
    following = arena.history('worm', limit=3, before=page['next_before'])
    assert [row['event_sequence'] for row in following['items']] == [189, 186, 183]
    assert arena.history('worm', before=0)['items'] == []
    for sql, parameters in (
        ('SELECT payload FROM decisions ORDER BY seq DESC,bio_id LIMIT ?', (4,)),
        ('SELECT seq,payload FROM decisions WHERE bio_id=? AND seq<? ORDER BY seq DESC LIMIT ?',
         ('worm', 192, 4)),
    ):
        plan = ' '.join(row[3] for row in arena.db.execute('EXPLAIN QUERY PLAN ' + sql, parameters))
        assert 'USING INDEX' in plan
        assert 'TEMP B-TREE' not in plan


def test_rotating_unobserved_candidates_do_not_grow_review_cache():
    arena = MemecoinArena.__new__(MemecoinArena)
    arena.broker = SimpleNamespace(accounts={'worm': SimpleNamespace(positions={'held': object()})})
    arena.learners = {'worm': SimpleNamespace(random=random.Random(17))}
    arena.settings = {'new_candidates_per_check': 2}
    arena.reviewed = {'worm': defaultdict(float, {'reviewed': 100})}
    arena.market = SimpleNamespace(candidates={}, quote_fresh=lambda key: True)
    for rotation in range(50):
        new = [f'new:{rotation}:{n}' for n in range(6)]
        arena.market.candidates = dict.fromkeys(['held', 'reviewed', *new])
        selected = arena.selection_keys('worm')
        assert selected[0] == 'held'
        assert len(selected) == 3
        assert set(selected[1:]).issubset(new)
    assert dict(arena.reviewed['worm']) == {'reviewed': 100}


@pytest.mark.parametrize('fail', [False, True])
def test_lifespan_cleans_up_after_normal_or_exceptional_exit(tmp_path, monkeypatch, fail):
    from bio_arena import api

    events = []

    class FakeArena:
        def __init__(self, root, config):
            pass

        async def start(self):
            events.append('start')

        async def stop(self):
            events.append('stop')

    config = tmp_path / 'config.yaml'
    config.write_text('{}')
    monkeypatch.setenv('BIO_ARENA_CONFIG', str(config))
    monkeypatch.setattr(api, 'Arena', FakeArena)
    monkeypatch.setattr(api, 'arena', None)

    async def exercise():
        async with api.lifespan(api.app):
            assert events == ['start']
            if fail:
                raise RuntimeError('lifespan failure fixture')

    if fail:
        with pytest.raises(RuntimeError, match='lifespan failure fixture'):
            asyncio.run(exercise())
    else:
        asyncio.run(exercise())
    assert events == ['start', 'stop']
