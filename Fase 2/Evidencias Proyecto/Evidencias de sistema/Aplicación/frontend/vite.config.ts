import { defineConfig } from 'vite'
import { resolve } from 'node:path'

export default defineConfig({
  server: { port: 5173 },
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        landing: resolve(__dirname, 'index.html'),
        acceso: resolve(__dirname, 'acceso.html'),
        proyectos: resolve(__dirname, 'proyectos.html'),
        proyecto: resolve(__dirname, 'proyecto.html'),
        precios: resolve(__dirname, 'precios.html'),
        plantillas: resolve(__dirname, 'plantillas.html'),
        estimacion: resolve(__dirname, 'estimacion.html'),
        panel: resolve(__dirname, 'panel.html'),
        documento: resolve(__dirname, 'documento.html'),
        configuracion: resolve(__dirname, 'configuracion.html'),
        administracion: resolve(__dirname, 'administracion.html'),
      },
    },
  },
})
