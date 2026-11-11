from itertools import combinations
import json
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = 'contracts/archive_lift.py'
FIXTURE = json.loads((ROOT / 'fixtures/archive.json').read_text())
SHARDS = [(ROOT / f'shards/{i}.hex').read_bytes() for i in range(5)]
BASE = 'https://raw.githubusercontent.com/gabrieladash123-bit/archive-lift/refs/heads/main/shards/'


def deploy_fixture(deploy, hashes=None, mirrors=None, payload_sha256=None, length=None):
    urls = mirrors or [BASE + str(i) + '.hex' for i in range(5)]
    commitments = hashes or FIXTURE['sha256']
    contract = deploy(CONTRACT, '|'.join(urls), ','.join(commitments),
                      payload_sha256 or FIXTURE['payload_sha256'],
                      FIXTURE['length'] if length is None else length, sdk_version='v0.2.16')
    return contract, urls


def mock_shards(vm, urls, responses):
    vm.clear_mocks()
    for url, response in zip(urls, responses):
        status, body = response if isinstance(response, tuple) else (200, response)
        vm.mock_web(re.escape(url), {'status': status, 'body': body})


@pytest.mark.parametrize('basis', list(combinations(range(5), 3)))
def test_every_three_shards_restore_exact_payload(direct_vm, direct_deploy, basis):
    contract, urls = deploy_fixture(direct_deploy)
    mock_shards(direct_vm, urls, [s if i in basis else (404, b'') for i, s in enumerate(SHARDS)])
    contract.probe(0)
    assert direct_vm.run_validator() is True
    state = contract.get_state()
    assert state['archive_hex'] == FIXTURE['payload_hex']
    assert state['latest']['basis'] == list(basis)
    assert state['latest']['outcome'] == 'RECOVERABLE'
    assert [contract.get_shard(i) for i in range(5)] == [
        {'index': i, 'hex': s.decode().strip(), 'sha256': FIXTURE['sha256'][i]}
        for i, s in enumerate(SHARDS)
    ]


def test_live_observation_changes_before_and_after_materialization(direct_vm, direct_deploy, direct_accounts):
    contract, urls = deploy_fixture(direct_deploy)
    missing = (404, b'not found')
    wrong = (ROOT / 'shards/wrong-b.hex').read_bytes()
    mock_shards(direct_vm, urls, [missing, wrong, SHARDS[2], SHARDS[3], b'malformed'])
    contract.probe(0)
    assert direct_vm.run_validator() is True
    first = contract.get_state()
    assert first['archive_hex'] is None
    assert first['latest'] == {
        'round': 1, 'outcome': 'INSUFFICIENT', 'basis': [2, 3],
        'mirrors': [{'status': 'MISSING'}, {'status': 'WRONG_DIGEST', 'sha256': FIXTURE['wrong_sha256']},
                    {'status': 'VERIFIED', 'sha256': FIXTURE['sha256'][2]},
                    {'status': 'VERIFIED', 'sha256': FIXTURE['sha256'][3]}, {'status': 'MALFORMED'}],
    }
    with direct_vm.expect_revert('Archive unavailable'):
        contract.get_shard(0)
    with direct_vm.expect_revert('Stale round'):
        contract.probe(0)
    assert contract.get_state() == first

    direct_vm.sender = direct_accounts[1]
    mock_shards(direct_vm, urls, [missing, wrong, *SHARDS[2:]])
    contract.probe(1)
    assert direct_vm.run_validator() is True
    assert contract.get_snapshot(1) == first['latest']
    assert contract.get_snapshot(2)['basis'] == [2, 3, 4]

    mock_shards(direct_vm, urls, [missing] * 5)
    for epoch in range(2, 6):
        contract.probe(epoch)
    assert contract.get_state()['latest']['outcome'] == 'INSUFFICIENT'
    assert contract.get_state()['archive_hex'] == FIXTURE['payload_hex']
    assert contract.get_shard(1)['hex'] == SHARDS[1].decode().strip()
    assert contract.get_snapshot(3)['round'] == 3
    with direct_vm.expect_revert('Snapshot not retained'):
        contract.get_snapshot(2)


def test_validator_checks_each_mirror_even_if_archive_result_is_unchanged(direct_vm, direct_deploy):
    contract, urls = deploy_fixture(direct_deploy)
    mock_shards(direct_vm, urls, SHARDS)
    contract.probe(0)
    mock_shards(direct_vm, urls, SHARDS[:4] + [(404, b'')])
    assert direct_vm.run_validator() is False


def test_validator_normalizes_only_representation_differences(direct_vm, direct_deploy):
    contract, urls = deploy_fixture(direct_deploy)
    mock_shards(direct_vm, urls, SHARDS[:4] + [(404, b'')])
    contract.probe(0)
    mock_shards(direct_vm, urls, [s.strip().upper() + b'\r\n' for s in SHARDS[:4]] + [(410, b'gone')])
    assert direct_vm.run_validator() is True


def test_poisoned_missing_commitment_prevents_publication(direct_vm, direct_deploy):
    bad = FIXTURE['sha256'][:4] + [FIXTURE['wrong_sha256']]
    contract, urls = deploy_fixture(direct_deploy, hashes=bad)
    mock_shards(direct_vm, urls, SHARDS[:4] + [(404, b'')])
    contract.probe(0)
    assert direct_vm.run_validator() is True
    state = contract.get_state()
    assert state['latest']['outcome'] == 'INCONSISTENT'
    assert state['archive_hex'] is None


def test_payload_commitment_must_match_even_when_all_shards_match(direct_vm, direct_deploy):
    contract, urls = deploy_fixture(direct_deploy, payload_sha256='0' * 64)
    mock_shards(direct_vm, urls, SHARDS)
    contract.probe(0)
    assert contract.get_state()['latest']['outcome'] == 'INCONSISTENT'
    assert contract.get_state()['archive_hex'] is None


def test_transient_failure_cannot_become_an_absence_observation(direct_vm, direct_deploy):
    contract, urls = deploy_fixture(direct_deploy)
    mock_shards(direct_vm, urls, [(503, b'')] + SHARDS[1:])
    before = contract.get_state()
    with direct_vm.expect_revert('[FETCH] Mirror 0 unavailable'):
        contract.probe(0)
    assert contract.get_state() == before


@pytest.mark.parametrize('invalid', ['duplicate', 'wrong-host', 'wrong-path'])
def test_manifest_restricts_sources(direct_vm, direct_deploy, invalid):
    urls = [BASE + str(i) + '.hex' for i in range(5)]
    urls[4] = {
        'duplicate': urls[0],
        'wrong-host': urls[4].replace('raw.githubusercontent.com', 'example.org'),
        'wrong-path': urls[4].replace('/shards/', '/private/'),
    }[invalid]
    with direct_vm.expect_revert('Five distinct shard URLs required'):
        deploy_fixture(direct_deploy, mirrors=urls)
