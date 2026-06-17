"""predictor-core.settings — validação rigorosa de credenciais (trava P0).

Se uma chave exigida estiver AUSENTE, vazia, com placeholder ('dummy', 'changeme'...)
ou curta demais, a aplicação dá crash IMEDIATO — antes de qualquer modelo inicializar.

Usa pydantic quando disponível (rigor de tipagem + ValidationError por campo); cai num
equivalente stdlib em contexto sem pydantic (stocks é stdlib-first). A trava é
UNIVERSAL, não pydantic-only. `import os` é a única dependência de carga; pydantic é
importado LAZY dentro de require_secrets.
"""
import os

# Valores que denunciam uma chave de mentira.
PLACEHOLDERS = {
    "dummy", "test", "testing", "changeme", "change-me", "your_key_here",
    "your-api-key", "yourapikey", "xxx", "xxxx", "none", "null", "todo",
    "placeholder", "fake", "secret", "<your_key>", "sk-...", "api_key",
}
MIN_LEN = 16


class MissingCredentialsError(RuntimeError):
    """Credencial exigida ausente ou falsa — crash de governança no segundo zero."""


def is_fake_secret(value) -> bool:
    """True se `value` é ausente, vazio, placeholder conhecido, ou curto demais."""
    s = (value or "").strip()
    return (not s) or s.lower() in PLACEHOLDERS or len(s) < MIN_LEN


def _fail_msg(bad) -> str:
    return (f"credenciais ausentes ou FALSAS (vazias, placeholder, ou < {MIN_LEN} chars): "
            f"{sorted(bad)}. Crash imediato — nenhum modelo deve inicializar com chave "
            f"inválida. Preencha o .env com chaves reais.")


def require_secrets(*names: str, env=None) -> dict:
    """Exige que cada var em `names` exista no ambiente e NÃO seja falsa.

    pydantic disponível => valida via field_validator (ValidationError por campo,
    agregada). Sem pydantic => mesma regra em stdlib. Em ambos, levanta
    MissingCredentialsError listando TODAS as inválidas de uma vez. Retorna o dict válido.
    """
    src = env if env is not None else os.environ
    values = {n: src.get(n, "") for n in names}
    try:
        from pydantic import BaseModel, field_validator, ValidationError

        class _Secret(BaseModel):
            value: str

            @field_validator("value")
            @classmethod
            def _not_fake(cls, v):
                if is_fake_secret(v):
                    raise ValueError("ausente, placeholder ou curta demais")
                return v

        bad = []
        for n, v in values.items():
            try:
                _Secret(value=v)
            except ValidationError:
                bad.append(n)
    except ImportError:
        bad = [n for n, v in values.items() if is_fake_secret(v)]

    if bad:
        raise MissingCredentialsError(_fail_msg(bad))
    return values
