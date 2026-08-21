# syntax=docker/dockerfile:1
# ============================================================
# FRONTEND — build estático Vite + nginx
# Build : node:22-alpine (npm ci + vite build → dist/)
# Runtime: nginx:alpine sirviendo dist/ como estático
#          + proxy /api/ → backend:8000 (mismo origen → sin CORS).
# ============================================================

# ---- Stage 1: build ----
FROM node:22-alpine AS build
WORKDIR /app

# package-lock primero: capa cacheable de node_modules.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# VITE_API_URL se resuelve por path relativo ('' = mismo origen): el navegador
# llama a /api/v1/... y nginx proxea al backend. Nada de localhost ni dominios.
RUN npm run build

# ---- Stage 2: runtime nginx ----
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
