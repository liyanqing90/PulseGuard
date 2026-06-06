import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

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
      "^/api(/|$)": "http://127.0.0.1:8787",
      "^/artifacts(/|$)": "http://127.0.0.1:8787"
    }
  }
});
