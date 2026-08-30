import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    port: 5173,
    proxy: {
      '/intercept': 'http://localhost:8000',
      '/metrics': 'http://localhost:8000',
      '/audit': 'http://localhost:8000',
      '/feedback': 'http://localhost:8000',
    }
  },
  build: {
    outDir: 'dist',
  }
})
