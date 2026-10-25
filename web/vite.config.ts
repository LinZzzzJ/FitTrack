import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";
export default defineConfig(({ mode }) => ({
  plugins: [svelte()],
  build: {
    outDir: mode === "mobile" ? "mobile-dist" : "../src/fittrack/static",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: (id: string) => {
          if (id.includes("/node_modules/zrender/")) return "chart-renderer";
          if (id.includes("/node_modules/echarts/")) return "charts";
          return undefined;
        },
      },
    },
  },
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8788", changeOrigin: true } },
  },
}));
