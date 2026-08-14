# PII Redactor — Web Interface

A Node/Express + React frontend that wraps the existing `pii_redactor` Python CLI as a black-box subprocess.

## Folder Structure

```
Scaler/
├── pii_redactor/            ← existing Python package (untouched)
│   └── redactor.py
├── pii_web/
│   ├── server/
│   │   ├── index.js         ← Express API server
│   │   ├── package.json
│   │   └── temp/            ← created automatically at runtime
│   │       └── <sessionId>/
│   │           ├── <id>__input.docx
│   │           ├── <id>__output.docx   ← written by Python CLI
│   │           └── <id>__mapping.json  ← written by Python CLI
│   └── client/
│       ├── index.html
│       ├── vite.config.js
│       ├── package.json
│       └── src/
│           ├── main.jsx
│           ├── App.jsx
│           └── index.css
└── website/                 ← static showcase site (separate)
```

## Prerequisites

- **Python 3** with `pii_redactor` installed and runnable as:
  ```bash
  python -m pii_redactor.redactor --help
  ```
  (spaCy `en_core_web_sm` model must be installed too — see pii_redactor/README.md)
- **Node.js ≥ 18** and **npm ≥ 9**

---

## Setup & Run

### 1. Install server dependencies
```bash
cd pii_web/server
npm install
```

### 2. Install client dependencies
```bash
cd pii_web/client
npm install
```

### 3. Start the Express API server (terminal 1)
```bash
cd pii_web/server
npm run dev        # uses node --watch for auto-reload
# or: npm start   # plain node, no auto-reload
```
Server starts on **http://localhost:4000**

### 4. Start the React dev server (terminal 2)
```bash
cd pii_web/client
npm run dev
```
React dev server starts on **http://localhost:5173**
All `/api/*` requests are automatically proxied to `:4000` (configured in `vite.config.js`).

Open **http://localhost:5173** in your browser.

---

## Where the Python subprocess is invoked

In [`server/index.js`](./server/index.js), look for the `runPiiRedactor()` function (around line 70):

```js
// ★ THIS IS WHERE THE PYTHON SUBPROCESS IS INVOKED ★
return execFileAsync(
  "python",
  [
    "-m", "pii_redactor.redactor",   // ← your existing CLI module
    inputPath,
    "--output",         outputPath,
    "--mapping-output", mappingPath,
    "--log-level",      "WARNING",
  ],
  {
    cwd:     PYTHON_CWD,   // set to Scaler/ so the package is importable
    timeout: 5 * 60 * 1000,
  }
);
```

`execFileAsync` is Node's `child_process.execFile` wrapped with `promisify`.
It passes each argument as a **separate array element** (not a shell string),
so filenames with spaces or special characters are safe from shell injection.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/redact` | Upload `.docx` files (field: `files`), run CLI, return results |
| `GET`  | `/api/download/:sessionId/:fileId` | Download the redacted `.docx` |
| `GET`  | `/api/health` | Health check |

### POST /api/redact — response shape
```json
{
  "sessionId": "uuid",
  "results": [
    {
      "fileId": "uuid",
      "originalName": "Red Herring Prospectus.docx",
      "status": "done",
      "downloadUrl": "/api/download/<sessionId>/<fileId>",
      "counts": { "PERSON": 180, "EMAIL": 39, "PHONE": 18, "CIN": 4, "total": 350 }
    }
  ]
}
```

---

## Changing the Python interpreter

If your Python executable is `python3` (Linux/macOS) instead of `python`, edit this line in `server/index.js`:

```js
return execFileAsync(
  "python3",   // ← change here
  ...
```

If you're using a virtual environment:
```js
  "/path/to/venv/bin/python",   // ← use the venv's absolute path
```

---

## Temp file cleanup

Session temp directories under `server/temp/` are automatically deleted after **30 minutes**.
The cleanup interval runs every 5 minutes.
You can tune these in `server/index.js`:
```js
const CLEANUP_INTERVAL_MS = 5 * 60 * 1000;   // every 5 min
const SESSION_TTL_MS      = 30 * 60 * 1000;  // keep for 30 min
```
