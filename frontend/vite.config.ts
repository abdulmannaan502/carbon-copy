import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Read VITE_* variables from the shared .env at the repository root.
  envDir: "..",
  server: { port: 5173, strictPort: true },
});
