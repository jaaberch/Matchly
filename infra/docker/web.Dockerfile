# Matchly web image (development: hot reload).
FROM node:22-alpine

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm install

COPY apps/web ./

EXPOSE 3000
CMD ["npm", "run", "dev"]
