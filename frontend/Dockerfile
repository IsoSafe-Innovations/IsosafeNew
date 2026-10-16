FROM node:22-alpine AS build
WORKDIR /app

# VITE_DEMO_MODE=1 bakes the Phase-1a demo UI (DEMO-FR-40) into the bundle.
ARG VITE_DEMO_MODE=""
ENV VITE_DEMO_MODE=${VITE_DEMO_MODE}

COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx-spa.conf /etc/nginx/conf.d/default.conf
