const fs = require("fs");

function patchFile(path, needle, replacement) {
  const original = fs.readFileSync(path, "utf8");
  if (original.includes(replacement)) {
    console.log(`already patched ${path}`);
    return;
  }
  if (!original.includes(needle)) {
    throw new Error(`Patch target not found: ${path}`);
  }
  fs.writeFileSync(path, original.replace(needle, replacement));
  console.log(`patched ${path}`);
}

patchFile(
  "/evolution/node_modules/baileys/lib/Utils/process-message.js",
  "                    const data = await downloadAndProcessHistorySyncNotification(histNotification, options);\n                    ev.emit('messaging-history.set', {",
  "                    const data = await downloadAndProcessHistorySyncNotification(histNotification, options);\n                    const tcTokensFromHistory = {};\n                    for (const historyChat of data.chats || []) {\n                        const historyToken = historyChat.tcToken;\n                        if (!historyToken)\n                            continue;\n                        const normalizedToken = Buffer.isBuffer(historyToken) ? historyToken : Buffer.from(historyToken);\n                        const tokenTimestamp = historyChat.tcTokenTimestamp ? String(toNumber(historyChat.tcTokenTimestamp)) : String(Math.floor(Date.now() / 1000));\n                        const tokenEntry = {\n                            token: normalizedToken,\n                            timestamp: tokenTimestamp,\n                            senderTimestamp: historyChat.tcTokenSenderTimestamp ? toNumber(historyChat.tcTokenSenderTimestamp) : Math.floor(Date.now() / 1000)\n                        };\n                        const tokenJids = [historyChat.lidJid, historyChat.id, historyChat.pnJid]\n                            .filter(Boolean)\n                            .map(jid => jidNormalizedUser(jid));\n                        for (const tokenJid of new Set(tokenJids)) {\n                            tcTokensFromHistory[tokenJid] = tokenEntry;\n                        }\n                    }\n                    if (Object.keys(tcTokensFromHistory).length) {\n                        await keyStore.set({ tctoken: tcTokensFromHistory });\n                        logger?.info({ count: Object.keys(tcTokensFromHistory).length }, 'stored trusted contact tokens from history');\n                    }\n                    ev.emit('messaging-history.set', {"
);

patchFile(
  "/evolution/node_modules/baileys/lib/Socket/messages-send.js",
  "            const contactTcTokenData = !isGroup && !isRetryResend && !isStatus ? await authState.keys.get('tctoken', [destinationJid]) : {};\n            const tcTokenBuffer = contactTcTokenData[destinationJid]?.token;\n            if (tcTokenBuffer) {",
  "            let tcTokenBuffer;\n            if (!isGroup && !isRetryResend && !isStatus) {\n                const tcTokenLookupJids = [destinationJid];\n                const decodedDestination = jidDecode(destinationJid);\n                if (decodedDestination?.server === 's.whatsapp.net') {\n                    const lidMapping = await authState.keys.get('lid-mapping', [decodedDestination.user]);\n                    const mappedLid = lidMapping?.[decodedDestination.user];\n                    const mappedLidUser = typeof mappedLid === 'string' ? mappedLid.replace(/\\\"/g, '') : mappedLid?.user || mappedLid?.lid || mappedLid;\n                    if (mappedLidUser)\n                        tcTokenLookupJids.push(mappedLidUser.includes('@') ? mappedLidUser : `${mappedLidUser}@lid`);\n                }\n                const uniqueTcTokenLookupJids = [...new Set(tcTokenLookupJids.filter(Boolean).map(jid => jidNormalizedUser(jid)))];\n                const contactTcTokenData = await authState.keys.get('tctoken', uniqueTcTokenLookupJids);\n                for (const tcTokenLookupJid of uniqueTcTokenLookupJids) {\n                    tcTokenBuffer = contactTcTokenData[tcTokenLookupJid]?.token;\n                    if (tcTokenBuffer) {\n                        logger.debug({ jid: tcTokenLookupJid }, 'adding trusted contact token');\n                        break;\n                    }\n                }\n            }\n            if (tcTokenBuffer) {"
);
