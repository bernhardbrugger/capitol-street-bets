import { defineConfig } from "vite";

// GitHub project pages live at /capitol-street-bets/. Local and other hosts use /.
export default defineConfig({
  base: process.env.VITE_BASE || "/",
  server: {
    port: 4731,
    strictPort: true,
    host: "127.0.0.1",
  },
  preview: {
    port: 4731,
    strictPort: true,
    host: "127.0.0.1",
  },
});
