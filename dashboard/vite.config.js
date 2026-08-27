import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/metrics': 'http://localhost:8000',
      '/intercept': 'http://localhost:8000',
      '/audit': 'http://localhost:8000'
    }
  }
})
