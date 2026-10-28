// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev-only: the Python operator UI backend (operator-ui/app.py) default port.
const API_BASE = process.env.VITE_API_BASE || "http://127.0.0.1:8600";

// Backend routes forwarded during `npm run dev`. Keep in sync with operator-ui/app.py.
const BACKEND_ROUTES = ["/servers", "/status", "/autonomy", "/ask", "/health", "/ready"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    // app.py serves this directory in production (no Node.js needed at runtime).
    outDir: "../dist",
    emptyOutDir: true,
  },
  server: {
    proxy: Object.fromEntries(
      BACKEND_ROUTES.map((route) => [route, { target: API_BASE, changeOrigin: false }]),
    ),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
