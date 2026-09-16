const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('claumebot', {
  pyPort: () => ipcRenderer.invoke('pyPort'),
  win: (action) => ipcRenderer.send('win', action),
});
