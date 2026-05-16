import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@vd/api-client": path.resolve(__dirname, "../../libs/ts/api-client/src/index.ts"),
      "@vd/ui": path.resolve(__dirname, "../../libs/ts/ui/src/index.ts"),
      "@vd/theme": path.resolve(__dirname, "../../libs/ts/theme/src/index.ts"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/files": "http://localhost:8000",
    },
  },
});
