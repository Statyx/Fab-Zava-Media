/**
 * Entra (MSAL) token acquisition for the three back-end planes this console reads.
 *
 * Why this exists at all: Rayfin's Fabric auth returns an *opaque Rayfin session*, not an Entra
 * token ("Session objects are opaque. Gate UI logic on isAuthenticated." — Rayfin docs). That
 * session authorizes the app's own services and nothing else, so it cannot call the Fabric API,
 * the Eventhouse, or the embed service — which is all this app does. Hence our own MSAL.
 *
 * Three audiences, therefore three token requests; one token cannot span them:
 *
 *   https://api.fabric.microsoft.com        Fabric REST, Data Agent, and the RTI dashboard embed
 *   https://analysis.windows.net/powerbi/api  Power BI REST (executeQueries / DAX)
 *   Kusto (see kustoScopes)                 Eventhouse data plane and the embedded tiles
 *
 * The first two resolve to the *same* service principal (Power BI Service, 00000009-…) yet are
 * still separate audiences — a token minted for one is rejected by the other.
 *
 * `.default` asks for everything already consented on the registration, which is what the embed
 * SDK needs: its tiles request scopes we never name explicitly.
 */
import {
  PublicClientApplication,
  InteractionRequiredAuthError,
  type AccountInfo,
  type Configuration,
} from '@azure/msal-browser';

/** Fabric REST + Data Agent + Fabric Embed (carries Fabric.Embed and KQLDashboard.Read.All). */
export const FABRIC_SCOPES = ['https://api.fabric.microsoft.com/.default'];

/** Power BI REST. `executeQueries` takes one query per request — it is not a batch endpoint. */
export const POWERBI_SCOPES = ['https://analysis.windows.net/powerbi/api/.default'];

/**
 * Azure AI Foundry data plane — the supervisor and, through it, the contract corpus.
 *
 * The audience is `https://ai.azure.com`, which does not announce itself: in Entra that
 * resource is the service principal named **Azure Machine Learning Services**
 * (`18a66f5f-dbdf-4c17-9dd7-1634712a9cbe`), a name that predates Foundry and survives it.
 * Searching the tenant for "Foundry" or "AI Services" finds nothing.
 *
 * The near-miss worth recording: `https://cognitiveservices.azure.com` is the obvious guess,
 * the account really is a `Microsoft.CognitiveServices/accounts` resource, and a token minted
 * for it is rejected 401 by this endpoint. The two are separate audiences.
 */
export const FOUNDRY_SCOPES = ['https://ai.azure.com/.default'];

/**
 * Kusto data-plane scopes, most specific first.
 *
 * A Fabric Eventhouse accepts a token minted for its own cluster URI, but that is not
 * guaranteed to be grantable to a third-party registration, so `kusto.kusto.windows.net` (the
 * Azure Data Explorer resource, `2746ea77-…`) is the dependable fallback. Callers try them in
 * order and keep the first that works.
 *
 * Without one of these the embedded tiles fail with the singularly unhelpful
 * `Cannot read properties of null (reading 'token')`.
 */
export function kustoScopes(clusterUri?: string): string[] {
  const scopes: string[] = [];
  if (clusterUri) scopes.push(`${clusterUri.replace(/\/+$/, '')}/user_impersonation`);
  scopes.push('https://kusto.kusto.windows.net/user_impersonation');
  return scopes;
}

const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID;
const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID;

export const msalConfigured = Boolean(clientId && tenantId);

/**
 * Both the sign-in popup and the silent-renewal iframe land here.
 *
 * It must NOT be the app root: coming back to '/' boots the whole SPA inside the popup, the
 * router immediately navigates away, and that navigation discards the response fragment MSAL is
 * waiting on — observed as `BrowserAuthError: timed_out` with the popup sitting on the app's own
 * sign-in screen. `blank.html` is a real build entry (see vite.config.ts), not a static file.
 */
const redirectUri = `${window.location.origin}/blank.html`;

const config: Configuration = {
  auth: {
    clientId: clientId ?? '',
    authority: `https://login.microsoftonline.com/${tenantId ?? 'common'}`,
    redirectUri,
  },
  cache: { cacheLocation: 'sessionStorage' },
};

export const msal = new PublicClientApplication(config);

let ready: Promise<void> | null = null;

/** MSAL v3+ requires an explicit initialize() before any other call. */
export function ensureMsalReady(): Promise<void> {
  if (!ready) {
    ready = msal.initialize().then(async () => {
      await msal.handleRedirectPromise();
      const [first] = msal.getAllAccounts();
      if (first && !msal.getActiveAccount()) msal.setActiveAccount(first);
    });
  }
  return ready;
}

export function activeAccount(): AccountInfo | null {
  return msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
}

/**
 * Silent-first token acquisition, falling back to a popup.
 *
 * `allowPopup: false` is used by the startup path and by the embed SDK's token callback, where a
 * popup would either be blocked (no user gesture behind it) or hijack the page.
 */
export async function getToken(scopes: string[], allowPopup = true): Promise<string> {
  await ensureMsalReady();
  const account = activeAccount();

  if (account) {
    try {
      const r = await msal.acquireTokenSilent({ scopes, account });
      return r.accessToken;
    } catch (err) {
      if (!(err instanceof InteractionRequiredAuthError) || !allowPopup) throw err;
    }
  } else if (!allowPopup) {
    throw new Error('No signed-in account and interaction is not allowed here.');
  }

  const r = await msal.acquireTokenPopup({ scopes });
  if (r.account) msal.setActiveAccount(r.account);
  return r.accessToken;
}

/**
 * Decode a JWT payload for display only.
 *
 * This never validates the signature and must never gate behaviour — it exists so the
 * diagnostics screen can show which audience and scopes were actually granted, which is the
 * difference between "a token came back" and "the right token came back".
 */
export function decodeJwt(token: string): Record<string, unknown> | null {
  try {
    const payload = token.split('.')[1];
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(decodeURIComponent(escape(json)));
  } catch {
    return null;
  }
}
