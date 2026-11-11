Category: Builder → Intelligent Contracts

Title: ArchiveLift: Consensus recovery of erasure coded artifacts

Notes / Description:

ArchiveLift recovers public artifacts up to 768 bytes from five web mirrors. Anyone can probe a fixed manifest. The leader and validators independently fetch each URL, decode the shard, verify SHA-256 and require exact agreement on bytes and mirror outcomes. Three valid shards can reconstruct the artifact over GF(256). The contract checks the payload hash, zero padding and all five shard commitments, including missing shards, before storing the recovered bytes onchain. It can then regenerate every shard, even after a mirror outage. A four-round history records observations. GenVM lint and 26 tests passed. Four StudioNet deployments using synthetic fixtures verified 16 finalized receipts covering intact recovery, recovery with missing and corrupt shards, insufficient shards, an inconsistent commitment and stale-round rejection.

Evidence: [Contract source](contracts/archive_lift.py) · [StudioNet recovery instance](https://explorer-studio.genlayer.com/address/0xC42D84BcD7C3153C026B85b0A61933E6c6Cf50A8) · [Onchain proofs](proofs/README.md)
