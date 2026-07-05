# src/event_models.py
"""Modelos para eventos não-gols (cartões, escanteios, finalizações).
API genérica com suporte a Poisson e Binomial Negativa.
"""

import warnings

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson, nbinom

def fit_event_model(
    history,
    event_name,
    distribution="poisson",
    overdispersion=True,
    features=None
):
    """
    Ajusta modelo para um evento contábil (ex: corners, cards, shots).

    Parâmetros:
        history: list[dict] com chaves:
            home_team, away_team, home_elo, away_elo,
            home_event, away_event  (valores inteiros)
        event_name: string para logging
        distribution: "poisson" ou "nbinom"
        overdispersion: bool (se True, usa NB, senão Poisson)
        features: lista de nomes de features do feature_builder
                  (ex: ['Ball possession', 'Total shots'])

    Retorna:
        dict com parâmetros:
            a, b (intercepto e coeficiente de Elo)
            alpha (se NB) ou None
            theta_feature (dict com coeficientes para cada feature)
            distribution: string
            n_matches: int
    """
    # 1. Montar arrays
    n = len(history)
    home_events = np.array([h['home_event'] for h in history], dtype=float)
    away_events = np.array([h['away_event'] for h in history], dtype=float)
    # diff em unidades de 400 pontos de Elo (mesma escala do model.py):
    # com Elo bruto (~centenas), exp(0.1*diff) estourava no chute inicial e o
    # L-BFGS-B devolvia o proprio x0 (b=0.1) sem convergir — silenciosamente.
    elo_diff = np.array([(h['home_elo'] - h['away_elo']) / 400.0
                         for h in history], dtype=float)
    
    # 2. Features (se houver)
    if features:
        # Exemplo: cada feature é uma média móvel já calculada pelo feature_builder
        # Vamos assumir que history já contém as features sob chaves como 'home_ball_possession', etc.
        feat_matrix = []
        for f in features:
            home_vals = np.array([h.get(f'home_{f}', 0.0) for h in history], dtype=float)
            away_vals = np.array([h.get(f'away_{f}', 0.0) for h in history], dtype=float)
            # Diferença (home - away) – pode ser ajustado
            feat_matrix.append(home_vals - away_vals)
        X = np.column_stack([np.ones(n), elo_diff] + feat_matrix)
    else:
        X = np.column_stack([np.ones(n), elo_diff])

    # Link ASSIMÉTRICO (auditoria P8): o time mais forte produz mais eventos e o
    # mais fraco menos — home usa +b·diff, away usa −b·diff (mesma forma do
    # model.py). A versão anterior aplicava o MESMO λ aos dois lados, forçando
    # b→0 (colapso para intercepto). O intercepto não troca de sinal; os termos
    # de diff (Elo e features home−away) trocam.
    sign = np.ones(X.shape[1])
    sign[1:] = -1.0
    X_away = X * sign

    # 3. Função de log-verossimilhança para Poisson
    def neg_log_lik_poisson(params):
        # params: [intercept, elo_coef, *feature_coefs]
        log_lambda_home = X @ params
        log_lambda_away = X_away @ params
        # Esperamos que home_events e away_events sigam Poisson com lambda exp(log_lambda)
        ll = np.sum(poisson.logpmf(home_events, np.exp(log_lambda_home)))
        ll += np.sum(poisson.logpmf(away_events, np.exp(log_lambda_away)))
        return -ll

    # 4. Para NB: parametrização Var = μ + α μ²
    def neg_log_lik_nbinom(params):
        # params: [intercept, elo_coef, *feature_coefs, alpha]
        alpha = params[-1]
        if alpha < 0:
            return 1e10  # penaliza alpha negativo
        beta = params[:-1]
        log_lambda_home = X @ beta
        log_lambda_away = X_away @ beta
        mu_home = np.exp(log_lambda_home)
        mu_away = np.exp(log_lambda_away)
        # Para NB, parâmetros: n = 1/alpha, p = n/(n + mu) — média = n*(1-p)/p = mu.
        # FIX: a fórmula anterior usava p = mu/(mu+n) (papel de p e 1-p invertido),
        # uma verossimilhança DIFERENTE da que predict_event() usa pra gerar as
        # probabilidades (lá, corretamente, p = n_val/(n_val+mu) — linha ~222).
        # O fit otimizava uma coisa e o predict lia como se fosse outra: (a,b)
        # saíam sem relação com a média real dos dados (chute a gol > chute
        # total, cartão médio na casa dos milhões antes do fix de bounds).
        n_val = 1.0 / alpha if alpha > 1e-6 else 1e6
        ll = np.sum(nbinom.logpmf(home_events, n_val, n_val/(n_val + mu_home)))
        ll += np.sum(nbinom.logpmf(away_events, n_val, n_val/(n_val + mu_away)))
        return -ll

    # 5. Otimização — chute inicial informativo: intercepto = log da media de
    # eventos (garante ponto de partida com verossimilhanca finita), demais 0.
    #
    # BOUNDS OBRIGATÓRIOS (fix): a verossimilhança da NB degenera quando o dado
    # não é overdisperso (var/mean <= 1, ex.: cartões amarelos, var/mean~0.93) —
    # o otimizador "converge" (res.success=True) com o intercepto fugindo pro
    # infinito (visto na prática: a=14.7 -> λ≈2.5 MILHÕES de cartões por jogo)
    # e alpha->0 simultaneamente, sem nenhum sinal de erro. Mesma patologia que
    # o model.py (gols) já blinda com bounds explícitos — replicada aqui.
    n_params = X.shape[1]
    mean_events = max(float(np.r_[home_events, away_events].mean()), 1e-3)
    beta0 = np.zeros(n_params)
    beta0[0] = np.log(mean_events)
    # intercepto: cobre médias de ~0.05 a ~65 eventos/jogo (folga generosa acima
    # do maior valor observado em qualquer stat, ex. chutes ~37). coef. de
    # diff/feature: (-2, 2) — direção informa o sinal, magnitude fica contida.
    beta_bounds = [(-3.0, 4.2)] + [(-2.0, 2.0)] * (n_params - 1)

    def _check_bounds_and_warn(res, bounds, names):
        if not res.success:
            warnings.warn(f"fit_event_model: otimização não convergiu ({res.message})",
                          RuntimeWarning, stacklevel=3)
        for name, val, (lo, hi) in zip(names, res.x, bounds):
            if min(abs(val - lo), abs(val - hi)) < 1e-6:
                warnings.warn(
                    f"fit_event_model: parâmetro {name}={val:.4f} cravado no bound "
                    f"[{lo}, {hi}] — resultado suspeito, confira o histórico de entrada",
                    RuntimeWarning, stacklevel=3)

    try:
        if distribution == "nbinom" and overdispersion:
            # fix: inicializar a NB direto de beta0=zeros deixa o L-BFGS-B travar
            # num ponto pior que o trivial (visto na prática: negll 4318 vs 2279
            # no ponto ingênuo, mesmo dentro dos bounds e com res.success=True —
            # convergência "local" não quer dizer bom ajuste). Ajusta Poisson
            # primeiro (superfície mais simples, sem alpha) e usa esse (a, b)
            # como partida da NB — no mesmo dado, isso achou negll=2250 (melhor
            # que os dois pontos anteriores) com a/b no valor correto.
            res_p = minimize(neg_log_lik_poisson, beta0, method='L-BFGS-B', bounds=beta_bounds)
            beta0_nb = res_p.x if res_p.success else beta0

            bounds = beta_bounds + [(1e-6, 5.0)]
            initial = np.r_[beta0_nb, 0.1]
            res = minimize(neg_log_lik_nbinom, initial, method='L-BFGS-B', bounds=bounds)
            _check_bounds_and_warn(res, bounds,
                                  [f"beta{i}" for i in range(n_params)] + ["alpha"])
            if res.success:
                beta = res.x[:-1]
                alpha = res.x[-1]
            else:
                # fallback para Poisson (com os mesmos bounds no intercepto/coefs)
                distribution = "poisson"
                res = minimize(neg_log_lik_poisson, beta0, method='L-BFGS-B',
                              bounds=beta_bounds)
                beta = res.x if res.success else beta0
                alpha = None
        else:
            res = minimize(neg_log_lik_poisson, beta0, method='L-BFGS-B', bounds=beta_bounds)
            _check_bounds_and_warn(res, beta_bounds, [f"beta{i}" for i in range(n_params)])
            beta = res.x if res.success else beta0
            alpha = None
    except Exception:
        # dado mal-formado ou otimizador instável: fallback conservador —
        # intercepto na média observada, sem efeito de Elo/feature, sem overdispersão.
        beta = beta0
        alpha = None
        distribution = "poisson"

    # 6. Montar resultado
    params = {
        'a': beta[0],
        'b': beta[1] if n_params > 1 else 0.0,
        'alpha': alpha,
        'distribution': distribution,
        'n_matches': n,
        'features': features or [],
        'theta_feature': {f: coef for f, coef in zip(features or [], beta[2:])} if features else {}
    }
    return params


def predict_event(elo_a, elo_b, params, features=None):
    """
    Gera previsões para um evento.

    Retorna:
        lambda_home, lambda_away (float)
        probs: dict com probabilidades para linhas 0.5, 1.5, 2.5, ..., 9.5
               (Over/Under)
    """
    a = params['a']
    b = params['b']
    theta = params.get('theta_feature', {})
    dist = params['distribution']
    
    # Calcular lambda — link assimétrico (auditoria P8): espelha o fit.
    # diff na MESMA escala do fit (unidades de 400 pontos de Elo).
    drift = b * (elo_a - elo_b) / 400.0
    if features:
        for f, coef in theta.items():
            drift += coef * features.get(f, 0.0)

    lambda_home = np.exp(a + drift)
    lambda_away = np.exp(a - drift)
    
    # Probabilidades Over/Under para linhas 0.5 a 9.5
    probs = {}
    for line in [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5]:
        # P(total > line) = 1 - P(total <= line)
        # Para Poisson: soma das PMFs
        if dist == 'poisson':
            cdf = poisson.cdf(line, lambda_home + lambda_away)
        else:
            # NB com alpha
            alpha = params.get('alpha', 0.1)
            if alpha < 1e-6:
                alpha = 1e-6
            n_val = 1.0 / alpha
            mu = lambda_home + lambda_away
            # A NB é definida para número de falhas antes de r sucessos.
            # Usamos a parametrização mean = r*(1-p)/p. Precisamos de p.
            # p = r / (r + mu)  (derivado de mean = r*(1-p)/p)
            p = n_val / (n_val + mu)
            cdf = nbinom.cdf(line, n_val, p)
        probs[f'over_{line}'] = 1 - cdf
        probs[f'under_{line}'] = cdf

    return lambda_home, lambda_away, probs