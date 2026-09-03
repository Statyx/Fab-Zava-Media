import { useState } from 'react';

import { liveAvailable } from '@/data/mode';
import { statusChip } from '@/domain/severity';
import { isFramed } from '@/services/authStartup';
import {
  activeAccount,
  decodeJwt,
  ensureMsalReady,
  FABRIC_SCOPES,
  getToken,
  msalConfigured,
  POWERBI_SCOPES,
} from '@/services/msal';
import { executeDax, semanticModelId } from '@/services/powerbi';

/**
 * One screen that checks each link in the chain and names the one that broke.
 *
 * Deliberately mounted **outside the auth guard**: the single most likely thing to be broken
 * is sign-in itself, and a diagnostic that requires sign-in to say "sign-in is broken" is
 * worthless. It is also absent from the nav manifest — reachable by URL only.
 *
 * The last probe evaluates a real measure rather than pinging an endpoint. Reaching the
 * service proves nothing about this app: the failure that matters is a model that answers but
 * does not carry `Total Campaigns`, and only evaluating it finds that.
 */
type State = 'pending' | 'ok' | 'warn' | 'fail' | 'skip';

interface Check {
  id: string;
  label: string;
  state: State;
  detail: string;
}

const STATE_STYLE: Record<State, { chip: string; text: string }> = {
  pending: { chip: statusChip('neutral'), text: 'En cours' },
  ok: { chip: statusChip('ok'), text: 'OK' },
  warn: { chip: statusChip('warn'), text: 'Dégradé' },
  fail: { chip: statusChip('fail'), text: 'Échec' },
  skip: { chip: statusChip('neutral'), text: 'Ignoré' },
};

const ENV_KEYS = [
  'VITE_ENTRA_CLIENT_ID',
  'VITE_ENTRA_TENANT_ID',
  'VITE_SEMANTIC_MODEL_ID',
  'VITE_ZAVA_WORKSPACE_ID',
  'VITE_ZAVA_DATA_AGENT_ID',
] as const;

/** Audience and granted scopes — the difference between "a token came back" and "the right token came back". */
function describeToken(token: string): string {
  const claims = decodeJwt(token);
  if (!claims) return 'jeton non décodable';
  const aud = String(claims.aud ?? '?');
  const scp = String(claims.scp ?? claims.roles ?? '-');
  const exp = typeof claims.exp === 'number' ? new Date(claims.exp * 1000) : null;
  const expires = exp ? ` — expire à ${exp.toLocaleTimeString('fr-FR')}` : '';
  return `aud ${aud} — scp ${scp}${expires}`;
}

export function DiagnosticPage() {
  const [checks, setChecks] = useState<Check[]>([]);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    const out: Check[] = [];
    const push = (c: Check) => {
      out.push(c);
      setChecks([...out]);
    };

    const missing = ENV_KEYS.filter((k) => !import.meta.env[k]);
    push({
      id: 'config',
      label: 'Configuration du bundle',
      state: missing.length === 0 ? 'ok' : 'fail',
      detail:
        missing.length === 0
          ? `${ENV_KEYS.length} variables présentes`
          : `Manquantes : ${missing.join(', ')}`,
    });

    push({
      id: 'frame',
      label: 'Contexte d’exécution',
      state: isFramed() ? 'warn' : 'ok',
      detail: isFramed()
        ? 'Exécution dans une iframe (portail Fabric). La fenêtre de connexion peut être bloquée — ouvrir l’URL d’hébergement dans un onglet.'
        : 'Onglet autonome. Connexion interactive disponible.',
    });

    if (!msalConfigured) {
      push({
        id: 'msal',
        label: 'Identité',
        state: 'fail',
        detail: 'Client ou locataire Entra absent : aucune acquisition de jeton n’est possible.',
      });
      setRunning(false);
      return;
    }

    try {
      await ensureMsalReady();
      const acct = activeAccount();
      push({
        id: 'msal',
        label: 'Identité initialisée',
        state: acct ? 'ok' : 'warn',
        detail: acct
          ? `Compte actif : ${acct.username}`
          : 'Initialisée, mais aucun compte connecté. Les acquisitions silencieuses échoueront.',
      });
    } catch (err) {
      push({
        id: 'msal',
        label: 'Identité initialisée',
        state: 'fail',
        detail: err instanceof Error ? err.message : String(err),
      });
      setRunning(false);
      return;
    }

    const planes: { id: string; label: string; scopes: string[] }[] = [
      { id: 'tok-fabric', label: 'Jeton Fabric (agent de données)', scopes: FABRIC_SCOPES },
      { id: 'tok-pbi', label: 'Jeton Power BI (évaluation des mesures)', scopes: POWERBI_SCOPES },
    ];

    for (const plane of planes) {
      let lastErr = '';
      let done = false;
      for (const scope of plane.scopes) {
        try {
          const token = await getToken([scope], false);
          push({
            id: plane.id,
            label: plane.label,
            state: 'ok',
            detail: `${scope} → ${describeToken(token)}`,
          });
          done = true;
          break;
        } catch (err) {
          lastErr = err instanceof Error ? err.message : String(err);
        }
      }
      if (!done) {
        push({
          id: plane.id,
          label: plane.label,
          state: 'fail',
          detail: `Aucune portée accordée silencieusement. Dernière erreur : ${lastErr}`,
        });
      }
    }

    if (!semanticModelId) {
      push({
        id: 'model',
        label: 'Modèle sémantique interrogeable',
        state: 'skip',
        detail: 'Identifiant du modèle sémantique absent de la configuration.',
      });
    } else {
      try {
        // A real measure, not a ping: an unknown measure name comes back as an empty cell
        // rather than an error, so only evaluating one proves the model is the right one.
        const rows = await executeDax(
          'EVALUATE ROW("probe", [Total Campaigns])',
        );
        const value = rows[0]?.['[probe]'] ?? rows[0]?.probe;
        push({
          id: 'model',
          label: 'Modèle sémantique interrogeable',
          state: value === null || value === undefined ? 'warn' : 'ok',
          detail:
            value === null || value === undefined
              ? 'Le modèle a répondu, mais la mesure est revenue vide — vérifier qu’il s’agit bien du modèle attendu.'
              : `Mesure Total Campaigns évaluée → ${String(value)}`,
        });
      } catch (err) {
        push({
          id: 'model',
          label: 'Modèle sémantique interrogeable',
          state: 'fail',
          detail: err instanceof Error ? err.message : String(err),
        });
      }
    }

    setRunning(false);
  };

  return (
    <div
      className="min-h-screen p-8"
      style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}
    >
      <div className="mx-auto max-w-4xl">
        <h1 className="text-2xl font-semibold tracking-tight">Diagnostic</h1>
        <p className="mt-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
          Vérifie chaque maillon entre le navigateur et les données Fabric, et nomme celui qui a
          cédé. Cette page est volontairement accessible sans être connecté.
        </p>

        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={() => void run()}
            disabled={running}
            className="rounded-md px-3 py-2 text-sm font-medium text-white transition-all hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            style={{ background: 'var(--accent)' }}
          >
            {running ? 'Vérification…' : 'Lancer le diagnostic'}
          </button>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            Mode direct {liveAvailable() ? 'configuré' : 'non configuré'}
          </span>
        </div>

        <ul className="mt-6 space-y-2">
          {checks.map((c) => (
            <li key={c.id} className="glass rounded-xl p-4">
              <div className="flex items-center gap-3">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-medium ring-1 ${STATE_STYLE[c.state].chip}`}
                >
                  {STATE_STYLE[c.state].text}
                </span>
                <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                  {c.label}
                </span>
              </div>
              <p
                className="mt-2 break-words font-mono text-xs"
                style={{ color: 'var(--text-muted)' }}
              >
                {c.detail}
              </p>
            </li>
          ))}
        </ul>

        {checks.length === 0 && !running ? (
          <p className="mt-6 text-sm" style={{ color: 'var(--text-muted)' }}>
            Aucun résultat pour l’instant.
          </p>
        ) : null}
      </div>
    </div>
  );
}
