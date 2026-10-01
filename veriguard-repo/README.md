# VeriGuard Repository (Milestone 1 sample)
Synthetic data only. Used by Azure Bicep automation (storage upload, index create, knowledge source/base, evaluation).

- data/<container>/*.md   -> blob containers: policies, regulatory-digests, audit-reports, kyc-procedures
- data/metadata.json      -> per-document metadata (doc_type, version, effective_date, classification, access_group, status)
- search/index-definition.json
- foundry-iq/knowledge-source.json, knowledge-base.json
- evaluation/golden-dataset.jsonl (30 seed + 20 additional + 5 unanswerable + 5 superseded traps), eval-config.json
