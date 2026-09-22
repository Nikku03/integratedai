import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API base URL is read at build/dev time from VITE_API_BASE (see README).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: true },
  build: { sourcemap: false, target: 'es2020' },
})
