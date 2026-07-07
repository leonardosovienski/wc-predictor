"""predictor_core.measurement (L1) — a RÉGUA estatística.

stats (financeira: Sharpe/Sortino/MDD/PSR/Spearman), metrics (probabilística:
Brier/log-loss/RPS/calibração/Diebold-Mariano), bootstrap (família unificada de IC
não-paramétrico), trials (registro de tentativas + DSR), replay (anti-lookahead
estrutural). É a camada mais valiosa e a mais testada — os vereditos dos três
domínios se apoiam nela. Depende só de kernel; internamente stats → bootstrap
(spearman_block_ci e os wrappers depreciados)."""
