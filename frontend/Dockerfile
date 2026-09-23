# Dev-oriented image: the source is bind-mounted in by docker-compose. Not a
# production build — the service only ever listens on localhost (spec §9).
FROM node:24-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install

COPY . .

CMD ["npm", "run", "dev"]
