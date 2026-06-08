// Ed.it desktop shell.
// Spawns the local Python `edit-web` server as a subprocess on a random
// free port, then opens a BrowserWindow pointed at it.

const { app, BrowserWindow, dialog, shell, Menu } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');
const os = require('os');

let mainWindow = null;
let pyProcess = null;
let pyPort = null;
let serverReady = false;
const startupLog = [];

// ---------- Helpers ----------

function logLine(line) {
  startupLog.push(line);
  if (startupLog.length > 400) startupLog.shift();
  process.stdout.write(`[ed.it] ${line}\n`);
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function waitForServer(port, timeoutMs = 60000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const resp = await fetch(`http://127.0.0.1:${port}/health`);
        if (resp.ok) return resolve();
      } catch (_) {}
      if (Date.now() - start > timeoutMs) {
        return reject(new Error('server did not start in time'));
      }
      setTimeout(tick, 400);
    };
    tick();
  });
}

function projectRoot() {
  // Prefer ~/Movies/Ed.it Projects, fall back to ~/Documents/Ed.it Projects.
  const home = os.homedir();
  const movies = path.join(home, 'Movies', 'Ed.it Projects');
  const docs = path.join(home, 'Documents', 'Ed.it Projects');
  const target = fs.existsSync(path.join(home, 'Movies')) ? movies : docs;
  fs.mkdirSync(target, { recursive: true });
  return target;
}

function devRepoRoot() {
  // electron/ lives inside Ed.it/, so the repo root is one level up.
  return path.resolve(__dirname, '..');
}

function pythonExecutable() {
  // Prefer the project's venv, then a system python.
  const candidates = [
    path.join(devRepoRoot(), '.venv', 'bin', 'python3'),
    path.join(devRepoRoot(), '.venv', 'bin', 'python'),
    '/opt/homebrew/bin/python3.12',
    '/opt/homebrew/bin/python3.11',
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    'python3',
  ];
  for (const p of candidates) {
    try {
      if (p.startsWith('/') && fs.existsSync(p)) return p;
      if (!p.startsWith('/')) return p;
    } catch (_) {}
  }
  return 'python3';
}

function loadEnv() {
  // Hand Python the keys we already have on disk.
  const envFile = path.join(devRepoRoot(), '.env');
  const env = { ...process.env };
  if (fs.existsSync(envFile)) {
    for (const line of fs.readFileSync(envFile, 'utf-8').split('\n')) {
      const m = line.match(/^([A-Z_][A-Z0-9_]*)=(.*)$/);
      if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, '');
    }
  }
  return env;
}

async function startPython() {
  pyPort = await findFreePort();
  const py = pythonExecutable();
  const env = loadEnv();
  env.EDIT_PROJECT_ROOT = projectRoot();
  env.PYTHONUNBUFFERED = '1';

  logLine(`spawning ${py} -m edit.server --port ${pyPort}`);
  pyProcess = spawn(py, ['-m', 'edit.server', '--port', String(pyPort), '--host', '127.0.0.1'], {
    cwd: devRepoRoot(),
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  pyProcess.stdout.on('data', d => logLine(`py: ${d.toString().trim()}`));
  pyProcess.stderr.on('data', d => logLine(`py-err: ${d.toString().trim()}`));
  pyProcess.on('exit', code => {
    logLine(`python exited code=${code}`);
    serverReady = false;
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send && mainWindow.webContents.send('server-down');
    }
  });

  try {
    await waitForServer(pyPort);
    serverReady = true;
    logLine(`server ready on :${pyPort}`);
  } catch (e) {
    logLine(`server failed: ${e.message}`);
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 720,
    minHeight: 540,
    title: 'Ed.it',
    backgroundColor: '#0a0a0b',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 16 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Show splash first; the renderer will redirect to the server once ready.
  mainWindow.loadFile(path.join(__dirname, 'splash.html'));

  if (serverReady) {
    mainWindow.loadURL(`http://127.0.0.1:${pyPort}/`);
  } else {
    const poll = setInterval(() => {
      if (serverReady && mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.loadURL(`http://127.0.0.1:${pyPort}/`);
        clearInterval(poll);
      }
    }, 500);
    setTimeout(() => clearInterval(poll), 90000);
  }

  // External links open in the user's default browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

function buildMenu() {
  const isMac = process.platform === 'darwin';
  const template = [
    ...(isMac ? [{ role: 'appMenu' }] : []),
    {
      label: 'File',
      submenu: [
        {
          label: 'Open Project Folder',
          accelerator: 'CmdOrCtrl+O',
          click: () => shell.openPath(projectRoot()),
        },
        { type: 'separator' },
        isMac ? { role: 'close' } : { role: 'quit' },
      ],
    },
    { role: 'editMenu' },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
      ],
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'GitHub Repo',
          click: () => shell.openExternal('https://github.com/thegirwhocodes/edit'),
        },
        {
          label: 'Show Startup Log',
          click: () => {
            dialog.showMessageBox({
              type: 'info',
              title: 'Ed.it startup log',
              message: `Python: ${pythonExecutable()}\nPort: ${pyPort}\nReady: ${serverReady}`,
              detail: startupLog.slice(-40).join('\n'),
            });
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ---------- Lifecycle ----------

app.whenReady().then(async () => {
  buildMenu();
  startPython();           // fire and forget; window polls
  createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

app.on('before-quit', () => {
  if (pyProcess && !pyProcess.killed) {
    try { pyProcess.kill('SIGTERM'); } catch (_) {}
  }
});
