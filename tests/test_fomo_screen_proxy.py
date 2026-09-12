import time

import httpx
import pytest
from fastapi.testclient import TestClient

from bio_arena import market_board


@pytest.mark.parametrize('case', ['frame', 'metadata', 'private', 'redirect', 'oversized', 'stale', 'html', 'timeout'])
def test_only_bounded_display_resources_are_forwarded(monkeypatch, case):
    calls = []

    def respond(request):
        calls.append((request.method, str(request.url)))
        if case == 'timeout':
            raise httpx.ReadTimeout('PRIVATE diagnostic', request=request)
        if case == 'private':
            return httpx.Response(503, text='PRIVATE diagnostic')
        if case == 'redirect':
            return httpx.Response(302, headers={'Location': 'https://example.com/private'})
        content = b'{"screens":{}}' if case == 'metadata' else b'\xff\xd8image\xff\xd9'
        if case == 'oversized':
            content = b'\xff\xd8' + b'x' * 500_000
        headers = {'Content-Type': 'application/json' if case == 'metadata' else 'image/jpeg',
                   'X-Frame-Time': str(time.time() - (60 if case == 'stale' else 0)),
                   'X-Frame-Sequence': '7', 'Set-Cookie': 'PRIVATE=session', 'X-Debug': 'PRIVATE'}
        if case == 'html':
            headers['Content-Type'] = 'text/html'
        return httpx.Response(200, content=content, headers=headers)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(market_board.httpx, 'AsyncClient',
                        lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(respond)))
    # No lifespan: the fixture must not start real market polling.
    client = TestClient(market_board.app)
    path = '/api/fomo-screens' + ('' if case == 'metadata' else '/adult/frame')
    response = client.get(path)
    assert calls == [('GET', 'http://127.0.0.1:8144' + path)]
    assert response.status_code == (200 if case in ('frame', 'metadata') else 503)
    assert response.headers['cache-control'] == 'no-store'
    assert 'PRIVATE' not in response.text
    assert 'set-cookie' not in response.headers and 'x-debug' not in response.headers
    if case == 'frame':
        assert response.headers['x-frame-sequence'] == '7'
    assert client.post(path, json={'click': True}).status_code == 405
    assert client.get('/api/fomo-screens/unknown/frame').status_code == 422
    assert client.get('/api/fomo-screens/adult/input').status_code == 404
    assert len(calls) == 1
