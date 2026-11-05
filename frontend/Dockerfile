FROM node:22-alpine AS build
WORKDIR /app

# Phase 1a UI by default; override with --build-arg VITE_DEMO_MODE=0 for full v1 nav.
ARG VITE_DEMO_MODE=1
ENV VITE_DEMO_MODE=${VITE_DEMO_MODE}

COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx-spa.conf /etc/nginx/conf.d/default.conf
