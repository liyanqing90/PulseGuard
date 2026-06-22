import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { fileURLToPath } from "node:url";

const devApiTarget = process.env.VITE_DEV_API_TARGET || "http://127.0.0.1:8787";
const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src")
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          antd: ["antd"],
          monaco: ["@monaco-editor/react", "monaco-editor"]
        }
      }
    }
  },
  server: {
    proxy: {
      "^/api(/|$)": devApiTarget,
      "^/artifacts(/|$)": devApiTarget
    }
  }
});
