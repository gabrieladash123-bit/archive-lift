const fs = require('node:fs');
const path = require('node:path');
const {root, assert, equal, digest, sourceHash, invoke, read, rpc, receipt, receiptSummary, save} = require('./transport.cjs');
const {decodeReceipt} = require('./receipt-calldata.cjs');

const fixture = require('../fixtures/archive.json');
const good = i => ({status: 'VERIFIED', sha256: fixture.sha256[i]});
const missing = {status: 'MISSING'};
const wrong = {status: 'WRONG_DIGEST', sha256: fixture.wrong_sha256};
const scenarios = {
  intact: {
    files: ['0', '1', '2', '3', '4'], observations: [0, 1, 2, 3, 4].map(good),
    basis: [0, 1, 2], outcome: 'RECOVERABLE',
  },
  degraded: {
    files: ['missing-a', 'wrong-b', '2', '3', '4'], observations: [missing, wrong, good(2), good(3), good(4)],
    basis: [2, 3, 4], outcome: 'RECOVERABLE',
  },
  insufficient: {
    files: ['missing-a', 'wrong-b', '2', '3', 'invalid-e'],
    observations: [missing, wrong, good(2), good(3), {status: 'MALFORMED'}],
    basis: [2, 3], outcome: 'INSUFFICIENT',
  },
  inconsistent: {
    files: ['0', '1', '2', '3', 'missing-e'], observations: [good(0), good(1), good(2), good(3), missing],
    basis: [0, 1, 2], outcome: 'INCONSISTENT', poison: true,
  },
};

async function main() {
  const id = process.env.ARCHIVE_SCENARIO;
  assert(Object.hasOwn(scenarios, id), 'Choose a supported scenario');
  const scenario = scenarios[id];
  const revision = process.env.GITHUB_SHA || process.env.ARCHIVE_FIXTURE_REVISION;
  assert(/^[0-9a-f]{40}$/.test(revision), 'Public fixture commit required');
  const wallets = JSON.parse(process.env.ARCHIVE_ACCOUNTS || '[]');
  assert(wallets.length === 2 && wallets[0].address !== wallets[1].address, 'Two distinct disposable signers required');
  const code = fs.readFileSync(path.join(root, 'contracts/archive_lift.py'));
  const base = 'https://raw.githubusercontent.com/gabrieladash123-bit/archive-lift/' + revision + '/shards/';
  const urls = scenario.files.map(name => base + name + '.hex');
  const sha256 = [...fixture.sha256];
  if (scenario.poison) sha256[4] = fixture.wrong_sha256;
  const manifest = {urls, sha256, payload_sha256: fixture.payload_sha256,
    length: fixture.length, shard_width: Math.ceil(fixture.length / 3)};
  const expected = {manifest, round: 0, latest: null, archive_hex: null};
  const ctor = [urls.join('|'), sha256.join(','), fixture.payload_sha256, fixture.length];
  assert(digest(Buffer.from(fixture.payload_hex, 'hex')) === fixture.payload_sha256, 'Bad local fixture');
  assert(await rpc('eth_chainId', []) === '0xf22f', 'StudioNet only');

  process.env.ARCHIVE_ACCOUNT = wallets[0].name;
  const deployment = await invoke(id + '-deploy', ['deploy', '--contract', 'contracts/archive_lift.py', '--args', ...ctor.map(String)]);
  const deployReceipt = await receipt(id + '-deploy', deployment, true);
  const contract = deployReceipt.to_address || deployReceipt.recipient;
  assert(/^0x[0-9a-f]{40}$/i.test(contract), 'Missing deployed address');
  assert(code.equals(Buffer.from(deployReceipt.data.contract_code, 'base64')), 'Deployed source mismatch');
  const trace = [];
  const report = {id, contract, deployment, revision, source_sha256: sourceHash, trace, repair: []};

  async function verify(label, raw, hash, signer, typed, error = null) {
    const info = receiptSummary(raw);
    assert(info.hash === hash, 'Receipt hash mismatch');
    assert((raw.from_address || raw.sender).toLowerCase() === signer, 'Receipt signer mismatch');
    assert((raw.to_address || raw.recipient).toLowerCase() === contract.toLowerCase(), 'Receipt recipient mismatch');
    assert(equal(await decodeReceipt(raw), typed), 'Signed argument mismatch');
    if (error) {
      const payload = Buffer.from(raw.consensus_data.leader_receipt[0].result, 'base64');
      assert(payload[0] === 1 && payload.subarray(1).toString() === error, 'Wrong revert reason');
    }
    const observed = await read(id + '-' + label + '-state', ['call', contract, 'get_state']);
    if (!equal(observed, expected)) save(id + '-state-mismatch', {label, observed, expected});
    assert(equal(observed, expected), 'Unexpected state after ' + label);
    trace.push({label, ...info, signer, typed, error, state: observed});
    save(id + '-progress', report);
  }

  await verify('deploy', deployReceipt, deployment, wallets[0].address, {args: ctor});
  async function probe(label, actor, round, error) {
    process.env.ARCHIVE_ACCOUNT = wallets[actor].name;
    const hash = await invoke(id + '-' + label, ['write', contract, 'probe', '--args', String(round)]);
    const raw = await receipt(id + '-' + label, hash, !error);
    if (!error) {
      expected.round = round + 1;
      expected.latest = {round: expected.round, outcome: scenario.outcome, basis: scenario.basis,
        mirrors: scenario.observations};
      if (scenario.outcome === 'RECOVERABLE') expected.archive_hex = fixture.payload_hex;
    }
    await verify(label, raw, hash, wallets[actor].address, {method: 'probe', args: [round]}, error);
  }

  await probe('probe-1', 1, 0);
  await probe('stale', 0, 0, 'Stale round');
  await probe('probe-2', 0, 1);
  for (const round of [1, 2]) {
    const snapshot = await read(id + '-snapshot-' + round, ['call', contract, 'get_snapshot', '--args', String(round)]);
    assert(equal(snapshot, {...expected.latest, round}), 'Historical snapshot mismatch');
  }
  if (expected.archive_hex !== null) {
    for (let i = 0; i < 5; i++) {
      const shard = await read(id + '-repair-' + i, ['call', contract, 'get_shard', '--args', String(i)]);
      const hex = fs.readFileSync(path.join(root, 'shards', i + '.hex'), 'utf8').trim();
      assert(equal(shard, {index: i, hex, sha256: fixture.sha256[i]}), 'Rebuilt shard mismatch: ' + i);
      report.repair.push(shard);
    }
  }
  assert(code.equals(Buffer.from(await rpc('gen_getContractCode', [contract]), 'base64')), 'Fresh source read mismatch');
  save(id + '-verified', report);
  console.log(JSON.stringify({id, contract, deployment, receipts: trace.length, repairedShards: report.repair.length}));
}

main().catch(error => { console.error(error.stack); process.exitCode = 1; });
