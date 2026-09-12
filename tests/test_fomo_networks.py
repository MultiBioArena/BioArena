from dataclasses import asdict
import json

import pytest

from bio_arena.auto_execution import ExecutionLimits, ExecutionStore
from bio_arena.execution_service import load_config
from bio_arena.execution_telemetry import asset, public_snapshot
from bio_arena.fomo_networks import NETWORKS, valid_token_path


@pytest.mark.parametrize('chain', NETWORKS)
def test_supported_asset_preserves_contract_identity_in_public_live_holding(tmp_path, chain):
    address = 'So11111111111111111111111111111111111111112' if chain == 'solana' else '0x'+'a'*40
    identity = chain+':'+address
    assert valid_token_path('/tokens/'+chain+'/'+address)
    assert asset(identity) == {'asset_id': identity, 'chain': chain, 'address': address}
    store = ExecutionStore(tmp_path/'live.sqlite', 'live', {'adult': 'private-account'}, ExecutionLimits())
    intent = {'id': 'fixture', 'bio_id': 'adult', 'account_ref': 'private-account',
              'created_at': 100, 'action': 'BUY', 'asset_id': identity, 'amount_usd': '2'}
    store.claim(intent, 100)
    store.finish(intent, {'status': 'filled', 'clicked': True, 'asset_id': identity, 'action': 'BUY',
                         'account_ref': 'private-account', 'route_id': 'fixture', 'relay_status': 'SUCCESS',
                         'balances_verified': True, 'observed_at': 101, 'cash_delta_usd': -2,
                         'position_after': {'asset_id': identity, 'raw_quantity': '2000', 'decimals': 3}})
    report = {'mode': 'live', 'process_running': True, 'live_enabled': True, 'updated_at': 101,
              'accounts': {'adult': {}}, 'limits': asdict(store.limits)}
    (tmp_path/'live-status.json').write_text(json.dumps(report))
    snapshot = public_snapshot(tmp_path, 102)
    holding = next(b for b in snapshot['bios'] if b['bio_id'] == 'adult')['holding']
    assert holding['asset_id'] == identity and holding['quantity_raw'] == '2000'
    assert snapshot['orders'][0]['asset']['asset_id'] == identity
    assert 'private-account' not in json.dumps(snapshot)
    store.close()


@pytest.mark.parametrize('path', ['/profile/private', '/tokens/unknown/0x'+'1'*40,
                                 '/tokens/solana/0x'+'1'*40, '/tokens/base/'+'1'*32,
                                 '/tokens/bnb/0x'+'1'*40+'?private=1'])
def test_unknown_or_malformed_page_is_not_a_public_asset(path):
    assert not valid_token_path(path)


def test_new_config_is_multichain_and_legacy_chain_is_metadata_only(tmp_path):
    account = {'enabled': False, 'account_ref': 'fixture', 'session': 'fixture',
               'browser_directory': str(tmp_path), 'profile': 'fixture', 'user_id': 'fixture',
               'cash_wallet': '1'*32, 'token_wallet': '0x'+'2'*40}
    config = {'enabled': False, 'source_url': 'http://localhost', 'accounts': {'adult': account}}
    path = tmp_path/'config.json'
    path.write_text(json.dumps(config))
    loaded,_ = load_config(path)
    assert 'chain' not in loaded['accounts']['adult']
    account.update(chain='robinhood', chain_id=4663)
    path.write_text(json.dumps(config));load_config(path)
    account['chain_id'] = 1
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match='legacy'):
        load_config(path)


@pytest.mark.parametrize('change', [{}, {'commitment': 'processed'}, {'owner_balances_verified': False},
                                   {'cash_delta_raw': '-1'}, {'token_delta_raw': '1'}, {'signature': 'bad'}])
def test_native_fill_requires_confirmed_matching_chain_and_cash_proof(change):
    identity = 'solana:So11111111111111111111111111111111111111112'
    intent = {'chain': 'solana', 'action': 'BUY', 'asset_id': identity,
              'account_ref': 'fixture', 'created_at': 100}
    evidence = {'clicked': True, 'settlement_provider': 'solana', 'relay_status': None,
                'route_id': '3'*88, 'account_ref': 'fixture', 'asset_id': identity,
                'action': 'BUY', 'observed_at': 101, 'balances_verified': True, 'cash_delta_usd': -2,
                'position_after': {'asset_id': identity, 'raw_quantity': '2000', 'decimals': 3},
                'solana_evidence': {'signature': '3'*88, 'slot': 7, 'commitment': 'confirmed',
                                    'owner_balances_verified': True, 'cash_delta_raw': '-2000000',
                                    'token_delta_raw': '2000', **change}}
    assert ExecutionStore._valid_fill(intent, evidence) is (not change)
    assert not ExecutionStore._valid_fill({**intent, 'chain': 'bnb'}, evidence)
    if change:
        # A stale Relay field cannot validate a failed native proof.
        assert not ExecutionStore._valid_fill(intent, {**evidence, 'relay_status': 'SUCCESS'})
