import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({ plugins: [react(), tailwindcss()], resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } }, server: { proxy: { '/api': { target: process.env.HAYBOT_DEV_API || 'http://127.0.0.1:8000', ws: true } } } })
