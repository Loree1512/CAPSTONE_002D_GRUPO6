# 🏗️ BuildCast

**Sistema web de estimación preliminar de costo y plazo de construcción**

BuildCast es una plataforma web desarrollada para **RAM Arquitectura y Construcción**, orientada a facilitar la generación de estimaciones preliminares de costo y plazo para proyectos de construcción.

El sistema busca reemplazar parte del proceso manual basado en planillas y experiencia individual por una solución más rápida, reproducible y trazable.

> Proyecto desarrollado como Actividad Práctica de Titulación de Ingeniería en Informática — Duoc UC, sede Viña del Mar.

---

## 📌 Objetivo

Desarrollar una plataforma que permita ingresar las principales características de una obra y obtener:

* Costo preliminar estimado.
* Desglose de costos por componentes.
* Costo estimado por metro cuadrado.
* Plazo estimado de construcción.
* Intervalo esperado del plazo.
* Trazabilidad de los valores utilizados.
* Documento de estimación descargable.

BuildCast está diseñado como una herramienta de **estimación preliminar y referencial** y no reemplaza un presupuesto contractual ni una cubicación detallada de obra.

---

## 🧠 Enfoque de la solución

BuildCast utiliza una arquitectura híbrida.

### Estimación de costo

El costo se calcula mediante un motor determinista basado en:

* Partidas del proyecto con su cantidad (propuestas por una plantilla según tipo de obra y materialidad).
* Banco de precios unitarios versionado, o un precio particular por proyecto.
* Factores opcionales de comuna y número de pisos.
* Gastos generales y utilidad, ambos sobre el costo directo.
* Parámetros configurables.

El objetivo es que cada componente del resultado pueda ser explicado y auditado.

### Estimación de plazo

El plazo de construcción será estimado mediante un modelo de Machine Learning entrenado utilizando información histórica proporcionada por RAM Arquitectura y Construcción.

El modelo entregará:

* Plazo estimado.
* Intervalo esperado.
* Versión del modelo utilizada.

---

## 🏛️ Arquitectura

```text
┌────────────────────────────┐
│          Frontend          │
│     TypeScript + Vite      │
└─────────────┬──────────────┘
              │
              │ REST / JSON
              ▼
┌────────────────────────────┐
│          FastAPI           │
│         Backend API        │
└─────────────┬──────────────┘
              │
       ┌──────┼─────────────┐
       │      │             │
       ▼      ▼             ▼
  Supabase   Motor de      Modelo
 PostgreSQL   costos         ML
    Auth                   Python
   Storage              scikit-learn
```

---

## 🛠️ Tecnologías

### Frontend

* TypeScript
* Vite
* HTML
* CSS
* Chart.js

### Backend

* Python
* FastAPI
* Pydantic

### Base de datos y servicios

* Supabase
* PostgreSQL
* Supabase Auth
* Supabase Storage

### Machine Learning

* Python
* pandas
* scikit-learn

### Desarrollo y colaboración

* Git
* GitHub
* Scrum

---

## 📁 Estructura inicial

```text
buildcast/
│
├── frontend/
│   └── Aplicación web desarrollada con TypeScript + Vite
│
├── backend/
│   └── API, reglas de negocio e integraciones con FastAPI
│
├── ml/
│   └── Preparación de datos, entrenamiento y evaluación del modelo
│
├── docs/
│   └── Arquitectura, decisiones técnicas y documentación del proyecto
│
├── .gitignore
├── README.md
└── LICENSE
```

La estructura podrá evolucionar durante el desarrollo del proyecto.

---

## 🚧 Estado del proyecto

**En desarrollo**

Etapa inicial:

* [ ] Configuración del repositorio
* [ ] Prototipo UX/UI de BuildCast
* [ ] Configuración inicial de TypeScript + Vite
* [ ] Configuración inicial de FastAPI
* [ ] Creación del proyecto Supabase
* [ ] Diseño e implementación inicial de la base de datos
* [ ] Integración Frontend → FastAPI → Supabase

Posteriormente:

* [ ] Gestión de proyectos
* [ ] Banco de precios
* [ ] Motor de estimación de costos
* [ ] Modelo predictivo de plazo
* [ ] Integración del modelo con FastAPI
* [ ] Generación de documentos
* [ ] Trazabilidad de estimaciones
* [ ] Pruebas y despliegue

---

## 👥 Equipo

Proyecto desarrollado por:

* **Loreto Bravo**
* **Ángel González**
* **Camila Aceituno**

Cliente:

**RAM Arquitectura y Construcción**

Docente guía:

**Mauricio Figueroa**

---

## 🔐 Variables de entorno

Las credenciales y claves privadas no deben almacenarse directamente en el repositorio.

Cada aplicación utilizará variables de entorno locales.

Ejemplo:

```env
SUPABASE_URL=
SUPABASE_KEY=
```

Los archivos `.env` reales deben estar incluidos en `.gitignore`.

Cuando corresponda, se proporcionarán archivos `.env.example` sin credenciales.

---

## 🌿 Flujo de trabajo Git

El desarrollo se realizará utilizando ramas para evitar modificaciones directas sobre la versión estable.

Ejemplo:

```text
main
│
├── develop
│
├── feature/frontend-dashboard
├── feature/backend-projects
├── feature/database-schema
└── feature/ml-duration-model
```

Las nuevas funcionalidades deberán integrarse mediante Pull Request después de ser revisadas.

---

## 📄 Alcance

BuildCast está orientado a entregar estimaciones preliminares.

El proyecto no contempla:

* Cubicación automática desde planos.
* Gestión de ejecución de obras.
* Presupuestos contractuales.
* Documentos con valor contractual.

Los resultados generados por el sistema deben considerarse referenciales.

---

## 📚 Proyecto académico

BuildCast corresponde al Proyecto APT de la carrera de **Ingeniería en Informática de Duoc UC**, desarrollado durante 2026 en conjunto con RAM Arquitectura y Construcción.
