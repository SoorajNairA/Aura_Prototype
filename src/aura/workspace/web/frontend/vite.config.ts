import { cpSync } from "node:fs";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Integration validation can redirect build artifacts so feature/ui never has to
// overwrite the representation runtime owned by feature/3d.
const outputDirectory = process.env.AURA_FRONTEND_OUT_DIR
  ? resolve(process.env.AURA_FRONTEND_OUT_DIR)
  : resolve(__dirname, "../representation");

export default defineConfig({
  base: "/assets/representation/",
  server: process.env.AURA_BACKEND_PROXY_TARGET ? {
    proxy: {
      "/api": {target: process.env.AURA_BACKEND_PROXY_TARGET, ws: true},
      "/health": {target: process.env.AURA_BACKEND_PROXY_TARGET},
    },
  } : undefined,
  plugins: [
    react(),
    {
      name: "copy-cascade-runtime",
      closeBundle() {
        cpSync(
          resolve(
            __dirname,
            "node_modules/cascade-core/dist/cascade-worker.js",
          ),
          resolve(outputDirectory, "cascade-worker.js"),
        );
        cpSync(
          resolve(
            __dirname,
            "node_modules/cascade-core/dist/cascadestudio.wasm",
          ),
          resolve(outputDirectory, "cascadestudio.wasm"),
        );
      },
    },
  ],
  resolve: {
    dedupe: ["react", "react-dom"],
    alias: {
      react: resolve(__dirname, "node_modules/react"),
      "react-dom": resolve(__dirname, "node_modules/react-dom"),
    },
  },
  build: {
    outDir: outputDirectory,
    emptyOutDir: true,
    chunkSizeWarningLimit: 1800,
  },
});
