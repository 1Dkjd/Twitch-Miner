import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type Lists } from "./api/client";

/** Priority / Never / Favourites, shared by Overview (Priority n, Never mine) and Priorities. */
export function useLists() {
  const [lists, setLists] = useState<Lists | null>(null);
  const reload = useCallback(async () => {
    try { setLists(await api.get<Lists>("/lists")); } catch { /* shown as empty */ }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  /** Optimistic save; on failure the previous lists come back and the message is returned. */
  const save = useCallback(async (next: Lists): Promise<string | null> => {
    const before = lists;
    setLists(next);
    try {
      setLists(await api.put<Lists>("/lists", next));
      return null;
    } catch (e) {
      setLists(before);
      return e instanceof ApiError ? e.message : "Couldn't save. Check the miner is running.";
    }
  }, [lists]);
  return { lists, setLists, save, reload };
}
