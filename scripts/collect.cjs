const fs = require('node:fs');
const path = require('node:path');
const {root, assert, digest, equal, sourceHash, receiptSummary, save} = require('./transport.cjs');

const runs = process.argv.slice(2);
const cases = [
  ['intact', 'RECOVERABLE', [0, 1, 2]],
  ['degraded', 'RECOVERABLE', [2, 3, 4]],
  ['insufficient', 'INSUFFICIENT', [2, 3]],
  ['inconsistent', 'INCONSISTENT', [0, 1, 2]],
];
assert(runs.length === 4 && runs.every(id => /^\d+$/.test(id)) && new Set(runs).size === 4,
  'Pass four completed run IDs in intact, degraded, insufficient, inconsistent order');
const fixture = require('../fixtures/archive.json');
const explorer = 'https://explorer-studio.genlayer.com/';
const repo = 'https://github.com/gabrieladash123-bit/archive-lift';
const index = [];
const files = [];
let revision, dissent = 0;

for (const [i, [id, outcome, basis]] of cases.entries()) {
  const folder = path.join(root, '.proof-journal', 'run-' + runs[i]);
  const read = name => JSON.parse(fs.readFileSync(path.join(folder, name + '.json')));
  const report = read(id + '-verified');
  revision ??= report.revision;
  assert(report.id === id && report.source_sha256 === sourceHash && report.revision === revision,
    'Proof must match local contract source and shared fixture revision');
  assert(equal(report.trace.map(step => step.label), ['deploy', 'probe-1', 'stale', 'probe-2']),
    'Proof must include both probes and the stale-round rejection');
  assert(report.trace[0].signer !== report.trace[1].signer, 'Independent first prober');
  const archive = outcome === 'RECOVERABLE' ? fixture.payload_hex : null;
  let prior;
  for (const step of report.trace) {
    const label = id + '-' + step.label + '-receipt';
    const raw = read(label);
    const info = receiptSummary(raw);
    assert(info.hash === step.hash && info.status === 'FINALIZED' && info.result === 'MAJORITY_AGREE'
      && info.agree > (info.agree + info.disagree + info.idle) / 2, 'Finalized strict majority');
    assert((raw.from_address || raw.sender).toLowerCase() === step.signer
      && (raw.to_address || raw.recipient).toLowerCase() === report.contract.toLowerCase(), 'Signer and recipient');
    dissent += info.disagree;
    if (step.label === 'deploy') {
      assert(info.hash === report.deployment && step.state.round === 0 && step.state.archive_hex === null,
        'Deployment record mismatch');
      assert(digest(Buffer.from(raw.data.contract_code, 'base64')) === sourceHash, 'Deployed source mismatch');
    }
    if (step.label === 'stale') {
      const result = Buffer.from(raw.consensus_data.leader_receipt[0].result, 'base64');
      assert(info.execution === 'ERROR' && result[0] === 1 && result.subarray(1).toString() === 'Stale round'
        && equal(prior, step.state), 'Stale round rejection and rollback');
    } else {
      assert(['SUCCESS', 'FINISHED_WITH_RETURN'].includes(info.execution), 'Expected successful execution');
    }
    if (step.label.startsWith('probe-')) {
      const round = Number(step.label.at(-1));
      assert(step.state.round === round && step.state.latest.round === round
        && step.state.latest.outcome === outcome && equal(step.state.latest.basis, basis)
        && step.state.archive_hex === archive, 'Unexpected consensus result');
    }
    assert(step.state.manifest.urls.every(url => url.includes('/' + revision + '/shards/')), 'Fixture revision mismatch');
    prior = step.state;
    files.push([label, raw]);
  }
  assert(report.repair.length === (archive === null ? 0 : 5), 'Missing repaired shards');
  for (const [i, shard] of report.repair.entries()) {
    assert(shard.index === i && digest(Buffer.from(shard.hex, 'hex')) === fixture.sha256[i]
      && shard.sha256 === fixture.sha256[i], 'Unexpected repaired shard');
  }
  const [first, second] = [report.trace[1].hash, report.trace[3].hash];
  const workflow = repo + '/actions/runs/' + runs[i];
  index.push({id, outcome, basis, contract: report.contract, deployment: report.deployment, first, second, workflow});
  files.push([id + '-verified', report]);
}

for (const [name, file] of files) save(name, file);
save('index', {source_sha256: sourceHash, fixture_revision: revision, successes: 12, rejections: 4, dissent, instances: index});
const rows = index.map(x => [
  x.id, x.outcome, x.basis.join(', '), `[Contract](${explorer}address/${x.contract})`,
  `[Deploy](${explorer}tx/${x.deployment})`, `[Probe 1](${explorer}tx/${x.first})`,
  `[Probe 2](${explorer}tx/${x.second})`, `[Run](${x.workflow})`,
]);
fs.writeFileSync(path.join(root, 'proofs/README.md'), [
  '# ArchiveLift StudioNet proofs', '',
  `Verified 16 finalized receipts, including 12 successful calls and four expected stale-round rejections. Raw receipts record ${dissent} dissenting votes.`, '',
  '| Scenario | Outcome | Decode basis | Address | Deployment | First probe | Second probe | Workflow |',
  '|---|---|---|---|---|---|---|---|',
  ...rows.map(row => '| ' + row.join(' | ') + ' |'), '',
  'Each trace records full onchain state after every transaction. Both recoverable instances also returned all five regenerated shards.',
  `Source SHA-256: \`${sourceHash}\`.`,
  `Fixture commit: \`${revision}\`.`, '',
].join('\n'));
console.log(JSON.stringify({revision, sourceHash, dissent, instances: index}, null, 2));
