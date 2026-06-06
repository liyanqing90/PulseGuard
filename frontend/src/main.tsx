import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "antd/dist/reset.css";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#1f8a5b",
          colorSuccess: "#1f8a5b",
          colorError: "#c23a32",
          colorWarning: "#b7791f",
          colorInfo: "#276aa7",
          borderRadius: 6,
          fontFamily: '"Noto Sans SC", "Microsoft YaHei UI", "Segoe UI", sans-serif'
        },
        components: {
          Table: {
            headerBg: "#eef3ed",
            rowHoverBg: "#f5f8f4"
          },
          Card: {
            colorBgContainer: "#fbfcf8"
          }
        }
      }}
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>
);
