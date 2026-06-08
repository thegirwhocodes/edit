// Intentionally minimal — the renderer talks to the local Python server
// over plain fetch + SSE. No need to expose Node APIs.
const { contextBridge } = require('electron');
contextBridge.exposeInMainWorld('edit', {
  platform: process.platform,
});
