import { useQuery } from "@tanstack/react-query";

// Runtime configuration served by nginx (/config.json, from the container environment):
// the same build works on the laptop and in the lab. In development it falls back to the
// local defaults.
export type RuntimeConfig = {
  supersetUrl: string;
  grafanaUrl: string;
  showPlatformHealth: boolean;
};

const DEFAULTS: RuntimeConfig = {
  supersetUrl: "http://localhost:8088",
  grafanaUrl: "http://localhost:3000",
  showPlatformHealth: true,
};

export function useConfig(): RuntimeConfig {
  const { data } = useQuery({
    queryKey: ["config"],
    staleTime: Infinity,
    queryFn: async () => {
      const response = await fetch("/config.json");
      if (!response.ok || !response.headers.get("content-type")?.includes("json")) return DEFAULTS;
      return { ...DEFAULTS, ...(await response.json()) } as RuntimeConfig;
    },
  });
  return data ?? { ...DEFAULTS, showPlatformHealth: false };
}
