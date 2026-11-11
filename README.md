# ArchiveLift

ArchiveLift lets a contract recover a small public artifact from five web mirrors.
It is intended for recovery pointers, compact configuration records and other
public payloads from 1 to 768 bytes.

Deploy one instance per artifact. The constructor fixes five shard URLs, five
SHA-256 digests of decoded shard bytes, the payload SHA-256 and the payload
length. Anyone can call `probe(expected_round)`. The transaction carries a round
number. The contract acquires the shard bytes itself.

The leader and validators fetch all five mirrors independently. They compare
the complete normalized observation: verified bytes and digest, wrong digest,
malformed response, or HTTP 404/410. Hex case and a trailing LF or CRLF are
normalized. Other HTTP failures abort the round. If validators see different
observations, they reject the leader's result even if both could recover the
payload. This is an exact equivalence rule for external observations.
See the [GenLayer equivalence principle](https://docs.genlayer.com/developers/intelligent-contracts/equivalence-principle).

For three or more verified shards, the contract picks the first three in slot
order and inverts their generator rows over GF(256). The three systematic shards
hold the zero padded payload. The two parity rows are `[1,1,1]` and `[1,2,4]`.
All ten three-row subsets are invertible with reduction polynomial `0x11D`.
The contract verifies the zero padding and payload hash, then re-encodes and
checks **all five** committed shards before publishing the recovered bytes.
The field convention follows [RFC 5510 §8.1](https://www.rfc-editor.org/rfc/rfc5510.html#section-8.1).
ArchiveLift defines its own fixed generator rows and hex format.

| Round result | Effect |
|---|---|
| `RECOVERABLE` | Store the payload onchain. `get_shard(index)` regenerates any of its five shards. |
| `INSUFFICIENT` | Record the observed mirrors and the slots that verified. |
| `INCONSISTENT` | Record the decode basis and withhold publication. |

`get_state()` shows the manifest, latest observation and any published bytes.
`get_snapshot(round)` retains four recent probes. Once published, the artifact
remains available through the contract after later mirror outages. Round
preconditions prevent two callers from updating the same observation slot.

The URL grammar supports raw GitHub files under `shards/` at a commit or a
named branch. Branch probes can see publication and removal over time. URLs can
share infrastructure, so a probe establishes what validators observed on those
paths at execution time. Consumers must choose the artifact digest they trust.
Anyone can read a published artifact or regenerated shard.

The StudioNet workflow uses synthetic fixtures and fresh disposable test
accounts. It compares full state after each finalized call and checks every
regenerated shard against an independently generated fixture. The degraded case
reconstructs from one systematic shard and both parity shards. The inconsistent
case supplies four valid shards but poisons the commitment for the absent fifth.

[StudioNet receipts and contract addresses](proofs/README.md) · [Submission text](SUBMISSION.md)

```sh
pip install -r requirements-dev.txt
genvm-lint download --version v0.2.16
genvm-lint check contracts/archive_lift.py
python -m pytest tests/direct -q
node --test tests/rpc-preflight.test.cjs
```

`python scripts/fixture_data.py` regenerates the fixtures. Generic CLI transport
and signing helpers are reused under MIT from [ClockMesh](https://github.com/gabrieladash123-bit/clock-mesh).
