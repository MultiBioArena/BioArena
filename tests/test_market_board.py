import pytest
from bio_arena.market_board import MarketBoard, parse_crypto, parse_stock, number


def test_crypto_source_time_and_identity():
    row = {'symbol': 'BTCUSDT', 'lastPrice': '77,123.4', 'closeTime': 1000_000, 'priceChangePercent': '-1.2'}
    q = parse_crypto(row, 1000)
    assert q['price'] == 77123.4 and q['quote_time'] == 1000
    with pytest.raises(ValueError):
        parse_crypto({**row, 'symbol': 'FAKEUSDT'}, 1000)
    with pytest.raises(ValueError):
        parse_crypto(row, 1300)
    for v in ['NaN', 'Infinity', 'N/A', None, True]:
        with pytest.raises(ValueError):
            number(v)


def test_stock_date_is_not_a_live_timestamp():
    payload = {'data': {'symbol': 'NVDA', 'marketStatus': 'Closed', 'primaryData': {
        'lastSalePrice': '$218.36', 'percentageChange': '-2.26%', 'lastTradeTimestamp': 'Sep 10, 2026', 'isRealTime': False}}}
    q = parse_stock(payload, 'NVDA', 1789114000)
    assert q['quote_time'] is None and q['delayed'] and q['market_state'] == 'Closed'
    payload['data']['primaryData']['lastTradeTimestamp'] = 'Sep 10, 2026 7:59 PM ET'
    q = parse_stock(payload, 'NVDA', 1789114000)
    assert q['quote_time'] == 1789084740  # ET is UTC-4 on this date.
    with pytest.raises(ValueError):
        parse_stock(payload, 'AAPL', 1789114000)


def test_feed_failure_keeps_original_receipt_and_marks_stale():
    board = MarketBoard()
    board.quotes['BTC'] = {'symbol': 'BTC', 'price': 100, 'received_at': 1000, 'history': []}
    board.unavailable('BTC')
    q = board.snapshot()['quotes'][0]
    assert q['received_at'] == 1000 and q['price'] == 100 and not q['fresh']
    assert q['error'] == 'Feed unavailable'
    assert len(board.snapshot()['quotes']) == 5
