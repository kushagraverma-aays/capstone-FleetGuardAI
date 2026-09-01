# Build the static bundle, then serve it from nginx. The runtime image carries
# no Node and no source - it is 40MB of nginx and a dist/ directory.
FROM node:22-alpine AS build

WORKDIR /app

# Dependencies first: this layer is rebuilt only when the lockfile changes,
# which turns a source-only edit into a ~5 second image build.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# nginx's own image starts it in the foreground already; stated explicitly so
# a reader does not have to know that.
CMD ["nginx", "-g", "daemon off;"]
