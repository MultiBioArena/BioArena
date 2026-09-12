"""Address-only EVM voting eligibility. No wallet connection or transaction methods."""
from dataclasses import dataclass
import os
import re
import time

import httpx


def evm_address(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', value.strip()):
        raise ValueError('Enter a 0x EVM address with 40 hexadecimal characters')
    address = value.strip().lower()
    if address == '0x' + '0' * 40:
        raise ValueError('The zero address cannot vote')
    return address


@dataclass(frozen=True)
class VoteSettings:
    mode: str = 'disabled'
    chain_id: int = 0
    token: str = ''
    rpc_url: str = ''
    minimum_raw: int = 1
    confirmations: int = 3

    def __post_init__(self):
        if self.mode not in ('disabled', 'paper_test', 'token_holder'):
            raise ValueError('VOTE_MODE must be disabled, paper_test or token_holder')
        if not 0 < self.minimum_raw < 2 ** 256 or not 0 <= self.confirmations <= 1000:
            raise ValueError('Invalid voting balance threshold or confirmation count')
        if self.mode == 'token_holder':
            if self.chain_id <= 0 or not self.rpc_url.startswith(('https://', 'http://')):
                raise ValueError('Token voting needs an explicit EVM chain ID and RPC URL')
            object.__setattr__(self, 'token', evm_address(self.token))

    @classmethod
    def from_env(cls):
        return cls(mode=os.getenv('BIO_VOTE_MODE', 'disabled'),
                   chain_id=int(os.getenv('BIO_VOTE_CHAIN_ID', '0'), 0),
                   token=os.getenv('BIO_VOTE_TOKEN', ''), rpc_url=os.getenv('BIO_VOTE_RPC_URL', ''),
                   minimum_raw=int(os.getenv('BIO_VOTE_MINIMUM_RAW', '1')),
                   confirmations=int(os.getenv('BIO_VOTE_CONFIRMATIONS', '3')))

    def public(self):
        return {'enabled': self.mode != 'disabled', 'mode': self.mode, 'chain_id': self.chain_id or None,
                'token': self.token or None, 'minimum_raw': str(self.minimum_raw),
                'confirmations': self.confirmations, 'ownership_verified': False}


class HoldingUnavailable(Exception):
    pass


class EvmEligibility:
    def __init__(self, settings, client):
        self.settings, self.client = settings, client

    async def rpc(self, method, params):
        # Fixed read-only method set; neither the URL nor contract comes from a visitor.
        if method not in ('eth_chainId', 'eth_blockNumber', 'eth_getBlockByNumber', 'eth_getCode', 'eth_call'):
            raise HoldingUnavailable('Unsupported RPC method')
        try:
            response = await self.client.post(self.settings.rpc_url,
                                             json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
            response.raise_for_status()
            payload = response.json()
            if payload.get('error') or 'result' not in payload:
                raise ValueError('Invalid RPC response')
            return payload['result']
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            # Provider URLs may contain secrets; return only a generic public error.
            raise HoldingUnavailable('Holding lookup unavailable; no vote was recorded') from exc

    async def check(self, address):
        address = evm_address(address)
        config = self.settings
        if config.mode == 'disabled':
            raise HoldingUnavailable('Voting is not enabled')
        if config.mode == 'paper_test':
            return {'address': address, 'eligible': True, 'kind': 'paper_address_test',
                    'token': None, 'chain_id': None, 'checked_at': time.time(),
                    'holdings_verified': False, 'ownership_verified': False}
        try:
            if int(await self.rpc('eth_chainId', []), 16) != config.chain_id:
                raise HoldingUnavailable('RPC chain does not match the configured voting network')
            height = int(await self.rpc('eth_blockNumber', []), 16) - config.confirmations
            if height < 0:
                raise ValueError('Insufficient chain history')
            block_tag = hex(height)
            block = await self.rpc('eth_getBlockByNumber', [block_tag, False])
            if (int(block['number'], 16) != height or not re.fullmatch(r'0x[0-9a-fA-F]{64}', block['hash'])
                    or not -5 <= time.time() - int(block['timestamp'], 16) <= 300):
                raise ValueError('Stale or invalid block')
            code = await self.rpc('eth_getCode', [config.token, block_tag])
            if not isinstance(code, str) or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})+', code):
                raise ValueError('No token contract at this address')
            raw = await self.rpc('eth_call', [{'to': config.token, 'data': '0x70a08231' + address[2:].rjust(64, '0')}, block_tag])
            if not isinstance(raw, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', raw):
                raise ValueError('Invalid ERC-20 balance response')
            after = await self.rpc('eth_getBlockByNumber', [block_tag, False])
            if after['hash'] != block['hash']:
                raise ValueError('Block changed during lookup')
            amount = int(raw, 16)
            return {'address': address, 'eligible': amount >= config.minimum_raw, 'kind': 'erc20_balance',
                    'chain_id': config.chain_id, 'token': config.token, 'balance_raw': str(amount),
                    'minimum_raw': str(config.minimum_raw), 'block_number': height, 'block_hash': block['hash'],
                    'checked_at': time.time(), 'holdings_verified': True, 'ownership_verified': False}
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise HoldingUnavailable('Could not verify token holdings; no vote was recorded') from exc
