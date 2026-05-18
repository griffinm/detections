# Build the Vite SPA, then serve the static bundle from nginx.
FROM node:22-slim AS build

# Pin pnpm 9 explicitly. corepack pulls pnpm 11.x, which ignores the
# onlyBuiltDependencies setting and hard-fails non-interactive installs with
# ERR_PNPM_IGNORED_BUILDS; pnpm 9 reads the v9.0 lockfile natively and builds
# dependency scripts without an approval gate.
RUN npm install -g pnpm@9.15.9

WORKDIR /repo

# Workspace manifests first for dependency-layer caching.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY libs/ts/api-client/package.json libs/ts/api-client/
COPY libs/ts/ui/package.json libs/ts/ui/
COPY libs/ts/theme/package.json libs/ts/theme/

RUN pnpm install --frozen-lockfile

COPY apps/web apps/web
COPY libs/ts libs/ts

# vite build only — the `build` script also runs `tsc -b`, but the deploy
# image needs the bundle, not the type check (that is a CI gate).
RUN pnpm --filter web exec vite build

FROM nginx:1.27-alpine
COPY docker/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
