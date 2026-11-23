import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  build: {
    outDir: "dist/client",
  },
  optimizeDeps: {
    include: ["react", "react-dom/client"],
  },
  server: {
    watch: { ignored: ["**/videos/**", "**/verification/**", "**/dist/**"] },
    proxy: { "/api/copilot": process.env.COPILOT_API || "http://127.0.0.1:8766" },
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
    warmup: {
      clientFiles: ["./src/main.jsx"],
    },
  },
  plugins: [react()],
});
