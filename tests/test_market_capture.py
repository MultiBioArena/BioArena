"""Check portable capture configuration and atomic snapshot failure handling."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/capture_fomo_market.py'


def load_capture(monkeypatch, tmp_path):
    monkeypatch.setenv('BIO_ARENA_BROWSER_DIR', str(tmp_path / 'browser workspace'))
    monkeypatch.setenv('BIO_ARENA_BROWSER_SESSION', 'research-session')
    monkeypatch.setenv('BIO_ARENA_PLAYWRIGHT_COMMAND', 'custom-cli --profile "research profile"')
    spec = importlib.util.spec_from_file_location('market_capture', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capture_uses_selected_cli_session_and_directory(monkeypatch, tmp_path):
    capture = load_capture(monkeypatch, tmp_path)
    output = tmp_path / 'snapshot.json'
    monkeypatch.setattr('sys.argv', ['capture', '--output', str(output)])
    payload = {
        'schema': 'bio_arena.fomo_market_snapshot.v2',
        'observed_at': '2026-09-11T00:00:00Z',
        'candidates': [{'chain': 'solana', 'symbol': 'TEST'}],
        'quotes': [],
    }

    def run(command, **kwargs):
        assert command[:5] == ['custom-cli', '--profile', 'research profile',
                               '-s=research-session', 'run-code']
        assert command[5] == capture.BROWSER_CODE
        assert kwargs['cwd'] == (tmp_path / 'browser workspace').resolve()
        assert kwargs['timeout'] == 35
        return SimpleNamespace(returncode=0, stdout='### Result\n' + json.dumps(payload))

    monkeypatch.setattr(capture.subprocess, 'run', run)
    capture.main()
    saved = json.loads(output.read_text())
    assert saved['candidates'] == payload['candidates']
    assert saved['observed_at'] == payload['observed_at']
    assert 'saved_at' in saved


@pytest.mark.parametrize('returncode,stdout', [
    (1, 'private page diagnostic'),
    (0, '### Result\n{"schema":"unexpected","candidates":[]}'),
])
def test_capture_failure_preserves_last_snapshot(monkeypatch, tmp_path, returncode, stdout):
    capture = load_capture(monkeypatch, tmp_path)
    output = tmp_path / 'snapshot.json'
    output.write_text('{"previous":"retained"}')
    monkeypatch.setattr('sys.argv', ['capture', '--output', str(output)])
    monkeypatch.setattr(capture.subprocess, 'run',
                        lambda *args, **kwargs: SimpleNamespace(returncode=returncode, stdout=stdout))
    with pytest.raises(RuntimeError) as error:
        capture.main()
    assert 'private page diagnostic' not in str(error.value)
    assert output.read_text() == '{"previous":"retained"}'
