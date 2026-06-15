export interface StandaloneConfig {
  deploymentUrl: string;
  assistantId: string;
  langsmithApiKey?: string;
}

const CONFIG_KEY = "deep-agent-config";

export function getConfig(): StandaloneConfig | null {
  if (typeof window === "undefined") return null;

  const environmentConfig =
    process.env.NEXT_PUBLIC_DEPLOYMENT_URL &&
    process.env.NEXT_PUBLIC_ASSISTANT_ID
      ? {
          deploymentUrl: process.env.NEXT_PUBLIC_DEPLOYMENT_URL,
          assistantId: process.env.NEXT_PUBLIC_ASSISTANT_ID,
        }
      : null;

  const stored = localStorage.getItem(CONFIG_KEY);
  if (!stored) return environmentConfig;

  try {
    return JSON.parse(stored);
  } catch {
    return environmentConfig;
  }
}

export function saveConfig(config: StandaloneConfig): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
}
