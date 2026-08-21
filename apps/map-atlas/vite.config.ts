import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, ".", ["MAP_ATLAS_BASE"]);
  return {
    plugins: [react()],
    base: environment.MAP_ATLAS_BASE || "./",
    publicDir: "../../build/map-atlas/public",
    build: {
      outDir: "../../build/map-atlas/site",
      emptyOutDir: true,
    },
    test: {
      environment: "node",
      include: ["src/**/*.test.{ts,tsx}"],
    },
  };
});
