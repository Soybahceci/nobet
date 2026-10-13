import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false },
  server: {
    // Geliştirme sunucusu: API çağrıları backend'e yönlenir.
    // Üretimde SPA'yı FastAPI servis ettiği için proxy'ye gerek yok.
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: true },
    },
  },
});
