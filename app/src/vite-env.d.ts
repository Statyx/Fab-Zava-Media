/// <reference types="vite/client" />

/**
 * Every variable the console reads, declared once so a typo is a build error rather than an
 * `undefined` discovered on stage.
 *
 * All of these are inlined into the bundle at build time and are therefore public. IDs and
 * tenant GUIDs are fine here; a secret never is.
 *
 * Note the absence of a mode switch. The network-operations console this shell came from
 * shipped an embedded dataset and could fall back to it, so it needed a flag to choose. Zava
 * has no seed: every figure on every screen is a DAX result. There is nothing to switch to,
 * so the only question is whether the model is reachable — which `VITE_SEMANTIC_MODEL_ID`
 * already answers.
 */
interface ImportMetaEnv {
  /** Entra app registration used for the interactive sign-in. */
  readonly VITE_ENTRA_CLIENT_ID?: string;
  readonly VITE_ENTRA_TENANT_ID?: string;

  /**
   * The Power BI semantic model every KPI is read from. Absent, the app renders its
   * structure and no numbers — which is the honest failure, not a broken one.
   */
  readonly VITE_SEMANTIC_MODEL_ID?: string;

  /** Fabric workspace and data agent backing the assistant rail. */
  readonly VITE_ZAVA_WORKSPACE_ID?: string;
  readonly VITE_ZAVA_DATA_AGENT_ID?: string;

  /** Rayfin-hosted auth, used when the app runs outside a Fabric item. */
  readonly VITE_RAYFIN_API_URL?: string;
  readonly VITE_RAYFIN_PUBLISHABLE_KEY?: string;

  /** Fabric-hosted auth, used when the app runs as a Fabric item. */
  readonly VITE_FABRIC_WORKSPACE_ID?: string;
  readonly VITE_FABRIC_ITEM_ID?: string;
  readonly VITE_FABRIC_PORTAL_URL?: string;

  /** Dev-server port, assigned per project by Rayfin. */
  readonly VITE_PORT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}