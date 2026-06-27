"""Cliente fino da API interna (não-documentada) do Sofascore.

Usa curl_cffi com impersonate do Chrome para passar pelo Cloudflare sem browser
headless. É API não-oficial: pode tomar 403, mudar sem aviso, e há o ToS deles —
trate como fonte best-effort, não estável. Roda fora do sandbox (a rede aqui
bloqueia o Sofascore).

SSL atrás de proxy corporativo: o curl_cffi roda sobre o libcurl, que tem cofre
de certificados próprio e não enxerga o do Windows. Em redes com inspeção TLS
(ex. proxy corporativo), exportamos os CAs do Windows num PEM e apontamos o
verify pra ele — sem desabilitar verificação.
"""
import atexit
import json
import os
import ssl
import sys
import tempfile
import time
from pathlib import Path

from curl_cffi import requests as creq

from .net import retry

# A API pública (api.sofascore.com) responde 403 {"reason":"challenge"} a
# qualquer cliente HTTP. O frontend do site bate no MESMO host (www) via
# /api/v1 (same-origin) e passa só por causa do header `x-requested-with`
# (ver _HEADERS). Usar o host www + esse header é o que destrava a coleta.
BASE = "https://www.sofascore.com/api/v1"


def _windows_ca_bundle():
    if sys.platform != "win32":
        return None
    pems = []
    for store in ("ROOT", "CA"):
        try:
            for cert, _enc, _trust in ssl.enum_certificates(store):
                pems.append(ssl.DER_cert_to_PEM_cert(cert))
        except Exception:
            pass
    if not pems:
        return None
    tmp = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
    tmp.write("\n".join(pems))
    tmp.close()
    atexit.register(lambda: Path(tmp.name).unlink(missing_ok=True))
    return tmp.name


# `x-requested-with` é o que separa um 200 de um 403 "challenge": o Sofascore
# só checa a PRESENÇA do header (o valor é livre — testado: token real e
# string inventada passam igual). Os sec-fetch-* completam o disfarce de
# chamada same-origin feita pelo próprio frontend.
_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.sofascore.com/",
    "x-requested-with": "wc-predictor",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}


class Sofascore:
    def __init__(self, rate_limit: float = 1.5, cache_dir: str | None = None,
                 impersonate: str = "chrome146"):
        self.rate = rate_limit
        self.session = creq.Session(impersonate=impersonate)
        self.session.headers.update(_HEADERS)
        self.cache = Path(cache_dir) if cache_dir else None
        if self.cache:
            self.cache.mkdir(parents=True, exist_ok=True)
        # SOFASCORE_INSECURE=1 desabilita verificação — só para diagnóstico
        if os.environ.get("SOFASCORE_INSECURE") == "1":
            self.verify = False
        else:
            self.verify = _windows_ca_bundle() or True

    @retry(attempts=4, base_delay=2.0)
    def _fetch(self, path: str):
        r = self.session.get(f"{BASE}/{path}", timeout=30, verify=self.verify)
        time.sleep(self.rate)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def _get(self, path: str, cache: bool = True):
        """cache=False pula leitura E escrita do cache local. Odds são dado
        TEMPORAL: cachear odd de fixture futuro congela o preço de dias atrás e
        mata a coleta em dois tempos (abertura/fechamento). Só o que é imutável
        pós-jogo (statistics, lineups, odds de jogo encerrado) pode ir pro disco."""
        if cache and self.cache:
            f = self.cache / (path.replace("/", "_") + ".json")
            if f.exists():
                return json.loads(f.read_text())
        data = self._fetch(path)
        if cache and self.cache and data is not None:
            f = self.cache / (path.replace("/", "_") + ".json")
            f.write_text(json.dumps(data))
        return data

    def list_seasons(self, ut_id: int):
        d = self._get(f"unique-tournament/{ut_id}/seasons")
        return [(s["id"], s.get("year")) for s in (d or {}).get("seasons", [])]

    def season_events(self, ut_id: int, season_id: int, upcoming: bool = False):
        events = []
        for kind in (["last", "next"] if upcoming else ["last"]):
            page = 0
            while page <= 20:
                d = self._get(f"unique-tournament/{ut_id}/season/{season_id}/events/{kind}/{page}")
                batch = (d or {}).get("events", [])
                if not batch:
                    break
                events.extend(batch)
                page += 1
        return events

    def event_odds(self, event_id: int, finished: bool = False):
        # jogo encerrado: linha congelada, cachear é seguro. Fixture: sempre rede.
        return self._get(f"event/{event_id}/odds/1/all", cache=finished)

    def event_statistics(self, event_id: int):
        return self._get(f"event/{event_id}/statistics")

    def event_lineups(self, event_id: int):
        return self._get(f"event/{event_id}/lineups")
