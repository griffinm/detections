import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const JSON_HEADERS = { "Content-Type": "application/json" };

export interface SettingItem {
  key: string;
  value: number | boolean;
  default: number | boolean;
  type: "number" | "integer" | "boolean";
}

export function useSettings() {
  return useQuery<SettingItem[]>({
    queryKey: ["settings"],
    queryFn: async () => {
      const res = await fetch("/api/settings");
      if (!res.ok) throw new Error("Failed to fetch settings");
      return res.json() as Promise<SettingItem[]>;
    },
  });
}

export function useUpdateSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      key,
      value,
    }: {
      key: string;
      value: number | boolean;
    }): Promise<SettingItem> => {
      const res = await fetch(`/api/settings/${key}`, {
        method: "PUT",
        headers: JSON_HEADERS,
        body: JSON.stringify({ value }),
      });
      if (!res.ok) throw new Error("Failed to update setting");
      return res.json() as Promise<SettingItem>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useResetSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (key: string): Promise<SettingItem> => {
      const res = await fetch(`/api/settings/${key}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to reset setting");
      return res.json() as Promise<SettingItem>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}
