# Two Container Apps deployment: SPA + nginx reverse-proxy to HTTPS backend ingress.
# From repo root:
#   az acr build -r "$ACR" -t orgmind/frontend:latest -f deployment/docker/frontend-acr-two-apps.Dockerfile .

FROM node:20-alpine AS builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM nginx:alpine
COPY deployment/docker/default.confACA.template /default.confACA.template
COPY deployment/docker/nginx-frontend-acr-render.sh /nginx-frontend-acr-render.sh
RUN chmod +x /nginx-frontend-acr-render.sh
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["/nginx-frontend-acr-render.sh"]
