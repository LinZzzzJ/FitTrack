import { registerPlugin } from "@capacitor/core";
export const secureStorage = registerPlugin<{
  getOrCreateDatabaseSecret(): Promise<{ secret: string }>;
  get(options: { key: string }): Promise<{ value?: string }>;
  set(options: { key: string; value: string }): Promise<void>;
  remove(options: { key: string }): Promise<void>;
}>("SecureStorage");
