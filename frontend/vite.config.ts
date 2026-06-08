import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const devApiTarget = process.env.VITE_DEV_API_TARGET || "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react()],
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
