"""Em redes corporativas com inspeção TLS (proxy que troca o certificado),
o truststore faz o Python confiar no mesmo cofre de certificados do SO —
sem desabilitar verificação. Carrega aqui, antes de qualquer entrypoint.
"""
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
