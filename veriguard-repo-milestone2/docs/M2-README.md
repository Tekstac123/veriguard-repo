# VeriGuard Milestone 2 additions
Synthetic data only. KYC profiles are generated at deployment time by `scripts/generate_kyc.py` and are never committed.

- data/transactions/schema.sql, transactions.csv   -> Azure SQL `veriguard-txn-db` (5,000 rows, planted typologies)
- data/watchlist/watchlist.csv                     -> blob container `watchlist`
- scripts/generate_*.py                            -> deterministic generators
- mcp/<txn-db|kyc-service|watchlist-screening>     -> MCP servers (Dockerfile + server.py)
- orchestrator/                                    -> supervisor workflow, memory, approval, retry/fallback (Dockerfile)
- agents/*.json                                    -> agent definitions and output schemas
- evaluation/m2-test-alerts.json                   -> the 3 Milestone 2 test alerts and expected outcomes
