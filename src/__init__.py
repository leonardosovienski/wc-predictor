"""Em redes corporativas com inspeção TLS (proxy que troca o certificado),
o truststore faz o Python confiar no mesmo cofre de certificados do SO —
sem desabilitar verificação. Carrega aqui, antes de qualquer entrypoint.
"""
import pathlib
import sys

# Consumidor do predictor_core via vendoring (telemetria JSONL etc.) — Shadow v2.
_vendor = pathlib.Path(__file__).resolve().parent.parent / "vendor"
if _vendor.is_dir() and str(_vendor) not in sys.path:
    sys.path.insert(0, str(_vendor))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
