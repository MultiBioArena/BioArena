from pathlib import Path
import json
import shutil
import time
import pytest
from bio_arena.arena import Arena

ROOT=Path(__file__).resolve().parents[1]

def test_continuous_session_has_no_time_expiry_but_timed_round_still_expires():
    arena=Arena.__new__(Arena)
    arena.started_at=1000
    arena.config={'round_seconds':0}
    assert not arena.time_limit_reached(1000+86400)
    arena.config['round_seconds']=3600
    assert not arena.time_limit_reached(4599)
    assert arena.time_limit_reached(4600)
    arena.started_at=None
    assert not arena.time_limit_reached(10000)

@pytest.mark.requires_data
def test_final_rank_and_equity_remain_frozen_after_market_moves(tmp_path):
    shutil.copytree(ROOT/'configs',tmp_path/'configs')
    for key in ['worm','adult','larva']:
        target=tmp_path/'data/processed'/key
        target.mkdir(parents=True)
        for name in ['manifest.json','visual.json']:
            shutil.copy(ROOT/'data/processed'/key/name,target/name)
    arena=Arena(tmp_path)
    try:
        arena.broker.accounts['worm'].cash=9000
        arena.broker.accounts['worm'].quantity=10
        arena.market.latest={'price':110,'received_at':time.time()}
        arena.finish()
        first=arena.state()
        arena.market.latest={'price':50,'received_at':time.time()}
        second=arena.state()
        assert first['status']=='finished'
        assert [b['account'] for b in first['bios']]==[b['account'] for b in second['bios']]
        assert first['bios'][0]['rank']==second['bios'][0]['rank']==1
        result=json.loads((arena.run_dir/'result.json').read_text())
        assert result['accounts']['worm']['equity']==10100
    finally:
        arena.db.close();arena.market_file.close()
