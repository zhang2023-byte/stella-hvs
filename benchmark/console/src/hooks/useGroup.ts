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
    let refreshTimer: number | undefined;
    const scheduleRefresh = (delay = 150) => {
      if (refreshTimer !== undefined) return;
      refreshTimer = window.setTimeout(() => {
        refreshTimer = undefined;
        void refresh();
      }, delay);
    };
    source.addEventListener("group", () => scheduleRefresh());
    source.onerror = () => scheduleRefresh(1000);
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => {
      source.close();
      window.clearInterval(timer);
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
    };
  }, [groupId, refresh]);
  return { group, error, refresh };
}
