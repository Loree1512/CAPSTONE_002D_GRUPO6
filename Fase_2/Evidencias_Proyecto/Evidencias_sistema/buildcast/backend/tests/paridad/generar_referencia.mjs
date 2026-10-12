// Genera backend/tests/datos/referencia_motor_ts.json con los datos de fábrica
// del frontend (catálogo, precios referenciales y configuración).
//
// Uso (desde la raíz del repositorio, con frontend/node_modules instalado):
//   node backend/tests/paridad/generar_referencia.mjs
//
// Las pruebas de Python comparan los seeds contra estas entradas.

import { writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const aqui = dirname(fileURLToPath(import.meta.url))
const raiz = resolve(aqui, '../../..')
const frontend = resolve(raiz, 'frontend')
const salida = resolve(aqui, '../datos/referencia_motor_ts.json')

const esbuild = createRequire(resolve(frontend, 'package.json'))('esbuild')

// configuracion.ts lee localStorage: vacío = CONFIGURACION_BASE, igual que un
// navegador que nunca guardó cambios.
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }

const entrada = `
export { CATEGORIAS_BASE, PARTIDAS_BASE } from './src/lib/catalogoBase'
export { PRECIOS_REFERENCIALES } from './src/lib/preciosReferenciales'
export { CONFIGURACION_BASE } from './src/lib/configuracion'
`

const { outputFiles } = await esbuild.build({
  stdin: { contents: entrada, resolveDir: frontend, loader: 'ts' },
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
})

const modulo = await import(
  'data:text/javascript;base64,' + Buffer.from(outputFiles[0].text).toString('base64')
)

const referencia = {
  generado_con: 'backend/tests/paridad/generar_referencia.mjs',
  entradas: {
    categorias: modulo.CATEGORIAS_BASE,
    partidas: modulo.PARTIDAS_BASE,
    precios: modulo.PRECIOS_REFERENCIALES,
    configuracion: modulo.CONFIGURACION_BASE,
  },
}

writeFileSync(salida, JSON.stringify(referencia, null, 2) + '\n', 'utf8')
console.log(`Referencia escrita en ${salida}: ${modulo.PARTIDAS_BASE.length} partidas.`)
