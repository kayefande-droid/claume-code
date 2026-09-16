/**
 * claume bot — Electron main process (v3.2).
 *
 * Boots the Python voice/chat bridge (claume/claumebot_server.py, which
 * reuses claume's LLM chain + STT + neural TTS + vision), then opens a
 * frameless dark window loading the glassmorphic UI with the Three.js
 * point-cloud humanoid avatar.
 */
const { app, BrowserWindow, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

let win = null;
let py = null;
let quitting = false;

const PY_CANDIDATES = [
  // installed claume venv first, then any python on PATH
  path.join(process.env.USERPROFILE || process.env.HOME || '', '.claume', 'venv', 'Scripts', 'python.exe'),
  path.join(process.env.USERPROFILE || process.env.HOME || '', '.claume', 'venv', 'bin', 'python'),
  'python',
  'python3',
];

function firstPython() {
  const fs = require('fs');
  for (const c of PY_CANDIDATES) {
    try { if (fs.existsSync(c)) return c; } catch (_) {}
  }
  return 'python';
}

function pyPort() {
  const p = parseInt(process.env.CLAUMEBOT_PORT || '', 10);
  return Number.isFinite(p) && p > 0 ? p : 8765;
}

function startBridge() {
  const exe = firstPython();
  const script = path.join(__dirname, 'claumebot_server.py');
  py = spawn(exe, [script, '--port', String(pyPort())], {
    cwd: __dirname,
    windowsHide: true,
    env: { ...process.env, PYTHONUNBUFFERED: '1', CLAUMEBOT_PORT: String(pyPort()) },
  });
  py.stdout.on('data', (d) => process.stdout.write(`[bridge] ${d}`));
  py.stderr.on('data', (d) => process.stderr.write(`[bridge] ${d}`));
  py.on('exit', (code) => {
    py = null;
    if (!quitting) {
      setTimeout(() => {
        if (!quitting) startBridge();
  }, 1500);
      }
    });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 940,
    minHeight: 640,
    backgroundColor: '#030712',
    frame: false,
    titleBarStyle: 'hidden',
    icon: path.join(__dirname, 'assets', 'jarvis.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });
  win.loadFile('index.html');
  win.on('closed', () => { win = null; });
}

ipcMain.handle('pyPort', () => pyPort());

ipcMain.on('win', (_e, action) => {
  if (!win) return;
  if (action === 'minimize') win.minimize();
  else if (action === 'maximize') win.isMaximized() ? win.unmaximize() : win.maximize();
  else if (action === 'close') win.close();
});

app.whenReady().then(() => {
  startBridge();
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('before-quit', () => { quitting = true; if (py) { try { py.kill(); } catch (_) {} } });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
