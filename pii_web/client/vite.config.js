import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy API calls to the Express backend during dev so there are no CORS issues
    proxy: {
      "/api": {
        target:       "http://localhost:4000",
        changeOrigin: true,
      },
    },
  },
});
