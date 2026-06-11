FROM evoapicloud/evolution-api:v2.3.7

COPY deploy/evolution/patch-baileys-tctoken.js /tmp/patch-baileys-tctoken.js
RUN node /tmp/patch-baileys-tctoken.js && rm /tmp/patch-baileys-tctoken.js
