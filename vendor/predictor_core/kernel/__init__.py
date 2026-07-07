"""predictor_core.kernel (L0) — zero dependências externas, zero I/O de rede.

infra (SQLite/migrações/config_hash), obs (telemetria JSONL), settings (trava de
credenciais), net (transporte HTTP), meta (fingerprint de artefatos). A API pública
é exposta pelo predictor_core/__init__.py de topo; os módulos daqui não se importam
entre si, salvo meta → infra (config_hash)."""
