# Stage 0, based on Bun, to build and compile the frontend
FROM oven/bun:1 AS build-stage

WORKDIR /app

COPY package.json bun.lock /app/
COPY frontend/package.json /app/frontend/

WORKDIR /app/frontend
RUN bun install

COPY ./frontend /app/frontend
ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}
RUN bun run build && sed -i 's|<div id="root"></div>|<div id="root"></div><noscript>Login to your account requires JavaScript.</noscript>|' dist/index.html

# Stage 1, based on Nginx, to have only the compiled app, ready for production with Nginx
FROM nginx:1

COPY --from=build-stage /app/frontend/dist/ /usr/share/nginx/html
COPY ./frontend/nginx.conf /etc/nginx/conf.d/default.conf
