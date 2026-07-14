import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ExperimentGroup } from "../types";

export function useGroup(groupId: string) {
  const [group, setGroup] = useState<ExperimentGroup | null>(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try {
      setGroup(await api.group(groupId));
      setError("");
    } catch (reason) {
      setError((reason as Error).message);
    }
  }, [groupId]);

  useEffect(() => {
    void refresh();
    const source = new EventSource(`/api/experiment-groups/${encodeURIComponent(groupId)}/events`);
    source.addEventListener("group", () => void refresh());
    source.onerror = () => window.setTimeout(() => void refresh(), 1000);
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { source.close(); window.clearInterval(timer); };
  }, [groupId, refresh]);
  return { group, error, refresh };
}
