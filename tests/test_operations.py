import json
from pathlib import Path
import tarfile

import pytest

from bio_arena.archival import archive
from bio_arena.watchdog import HealthWatch


def state(status='running',seq=1,fresh=True,paused=False):
    return {'run_id':'run','sequence':seq,'status':status,'market_fresh':fresh,'paused':paused,'bios':[{'account':{'alive':True}}]}


def test_watchdog_detects_stall_and_http_loss_but_respects_pause_and_market_outage():
    watch=HealthWatch(0,timeout=180,unreachable=30)
    assert watch.check(state(),0) is None
    assert watch.check(state(seq=2),170) is None
    assert watch.check(state(seq=2),351)=='decision_stalled'
    assert watch.check(state(seq=2,paused=True),400) is None
    assert watch.check(state(seq=2,fresh=False),900) is None
    assert watch.check(state(seq=2),1000) is None
    assert watch.check(None,1031)=='http_unreachable'
    assert watch.check(state(status='error'),1032)=='engine_error'


def test_archive_protects_lineage_and_verifies_before_pruning(tmp_path):
    runs=tmp_path/'runs';runs.mkdir()
    (runs/'active-run.json').write_text(json.dumps({'run_id':'current'}))
    for key in ['current','parent','cold']:
        folder=runs/key;folder.mkdir();(folder/'stopped_state.json').write_text('{}')
        (folder/'manifest.json').write_text(json.dumps({'recovery':{'source_run':'parent'}} if key=='current' else {}))
        (folder/'events.jsonl').write_text('preserved\n'*500)
    for key in ['current','parent']:
        with pytest.raises(ValueError,match='Active'):archive(tmp_path,key,0,True)
    result=archive(tmp_path,'cold',0,True)
    assert result['verified'] and not (runs/'cold').exists()
    with tarfile.open(tmp_path/'archives/cold.tar.gz') as tar:
        assert tar.extractfile('cold/events.jsonl').read()==b'preserved\n'*500
    assert (runs/'current').exists() and (runs/'parent').exists()


def test_unstopped_or_symlinked_run_is_not_archived(tmp_path):
    runs=tmp_path/'runs';runs.mkdir();(runs/'active-run.json').write_text('{"run_id":"current"}')
    folder=runs/'unknown';folder.mkdir()
    with pytest.raises(ValueError,match='explicitly stopped'):archive(tmp_path,'unknown',0,True)
    (folder/'stopped_state.json').write_text('{}');(folder/'link').symlink_to(tmp_path)
    with pytest.raises(ValueError,match='symbolic'):archive(tmp_path,'unknown',0,True)


def test_archive_keeps_source_when_durable_write_fails(tmp_path,monkeypatch):
    runs=tmp_path/'runs';runs.mkdir();(runs/'active-run.json').write_text('{"run_id":"current"}')
    folder=runs/'cold';folder.mkdir();(folder/'stopped_state.json').write_text('{}')
    def fail(_):raise OSError('disk write failure')
    monkeypatch.setattr('bio_arena.archival.os.fsync',fail)
    with pytest.raises(OSError,match='disk write'):archive(tmp_path,'cold',0,True)
    assert (folder/'stopped_state.json').read_text()=='{}'
