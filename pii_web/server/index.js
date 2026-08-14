/**
 * PII Redactor — Express Backend
 * ================================
 * Wraps the Python CLI `python -m pii_redactor.redactor` as a black-box subprocess.
 * No Python code lives here — Node just invokes it and reads its output files.
 *
 * Folder layout (relative to this file):
 *   server/
 *     index.js          ← this file
 *     temp/             ← created automatically at startup
 *       <sessionId>/
 *         input.docx    ← uploaded file (multer saves here)
 *         output.docx   ← written by Python CLI
 *         mapping.json  ← written by Python CLI
 */

import express from "express";
import cors from "cors";
import multer from "multer";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { v4 as uuidv4 } from "uuid";

const execFileAsync = promisify(execFile);

// ── Paths ────────────────────────────────────────────────────────────────────
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TEMP_DIR  = path.join(__dirname, "temp");

// Ensure temp dir exists at startup
if (!fs.existsSync(TEMP_DIR)) fs.mkdirSync(TEMP_DIR, { recursive: true });

// ── Auto-cleanup: delete session dirs older than 30 minutes ──────────────────
const CLEANUP_INTERVAL_MS = 5 * 60 * 1000;   // run every 5 min
const SESSION_TTL_MS      = 30 * 60 * 1000;  // delete after 30 min

function scheduleCleanup() {
  setInterval(async () => {
    try {
      const entries = await fsp.readdir(TEMP_DIR, { withFileTypes: true });
      const now = Date.now();
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        const dir  = path.join(TEMP_DIR, entry.name);
        const stat = await fsp.stat(dir);
        if (now - stat.mtimeMs > SESSION_TTL_MS) {
          await fsp.rm(dir, { recursive: true, force: true });
          console.log(`[cleanup] removed session ${entry.name}`);
        }
      }
    } catch (err) {
      console.error("[cleanup] error:", err.message);
    }
  }, CLEANUP_INTERVAL_MS);
}

// ── Multer — save uploads to temp/<sessionId>/ ───────────────────────────────
const storage = multer.diskStorage({
  destination(req, file, cb) {
    // Attach a session ID to the request on first file; reuse for subsequent files
    if (!req.sessionId) req.sessionId = uuidv4();
    const sessionDir = path.join(TEMP_DIR, req.sessionId);
    fs.mkdirSync(sessionDir, { recursive: true });
    cb(null, sessionDir);
  },
  filename(req, file, cb) {
    // Use a unique prefix so multiple files in the same session don't collide
    const fileId   = uuidv4();
    const safeName = file.originalname.replace(/[^a-zA-Z0-9._-]/g, "_");
    cb(null, `${fileId}__${safeName}`);
  },
});

const upload = multer({
  storage,
  fileFilter(req, file, cb) {
    if (file.mimetype === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
      || file.originalname.toLowerCase().endsWith(".docx")) {
      cb(null, true);
    } else {
      cb(new Error(`Only .docx files are accepted. Got: ${file.originalname}`));
    }
  },
  limits: { fileSize: 50 * 1024 * 1024 }, // 50 MB cap
});

// ── Helper: invoke Python CLI for one file ────────────────────────────────────
/**
 * ┌─────────────────────────────────────────────────────────────────────────┐
 * │  ★ THIS IS WHERE THE PYTHON SUBPROCESS IS INVOKED ★                    │
 * │                                                                         │
 * │  Command equivalent:                                                    │
 * │    python -m pii_redactor.redactor "<inputPath>"                        │
 * │             --output "<outputPath>"                                     │
 * │             --mapping-output "<mappingPath>"                            │
 * │             --log-level WARNING                                         │
 * │                                                                         │
 * │  Uses execFile (not exec) so filenames with spaces/special chars        │
 * │  are passed as separate argv elements — no shell interpolation risk.    │
 * └─────────────────────────────────────────────────────────────────────────┘
 *
 * @param {string} inputPath   - absolute path to the uploaded .docx
 * @param {string} outputPath  - absolute path where the CLI should write the redacted .docx
 * @param {string} mappingPath - absolute path where the CLI should write pii_mapping.json
 * @returns {Promise<{ stdout: string, stderr: string }>}
 */
async function runPiiRedactor(inputPath, outputPath, mappingPath) {
  // Change cwd to the project root so `python -m pii_redactor.redactor` can find the package.
  // Adjust PYTHON_CWD if your pii_redactor package is somewhere other than the parent of server/.
  const PYTHON_CWD = path.join(__dirname, "..", "..");  // → Scaler/

  return execFileAsync(
    "python",   // The Python executable; change to "python3" on Linux/macOS if needed
    [
      "-m", "pii_redactor.redactor",  // Module invocation — no shell needed
      inputPath,
      "--output",         outputPath,
      "--mapping-output", mappingPath,
      "--log-level",      "WARNING",   // Suppress INFO noise; stderr still captures errors
    ],
    {
      cwd:     PYTHON_CWD,
      timeout: 5 * 60 * 1000,  // 5-minute timeout per file (spaCy + large docs can be slow)
      maxBuffer: 10 * 1024 * 1024,  // 10 MB stdout buffer
    }
  );
}

// ── Parse pii_mapping.json → summary counts per type ─────────────────────────
/**
 * The mapping JSON has the shape:
 *   { "PERSON": { "real_val": "fake_val", ... }, "EMAIL": { ... }, ... }
 *
 * We convert it to:
 *   { "PERSON": 12, "EMAIL": 5, "PHONE": 3, "total": 20 }
 */
async function parseMappingCounts(mappingPath) {
  const raw     = await fsp.readFile(mappingPath, "utf-8");
  const mapping = JSON.parse(raw);
  const counts  = {};
  let total     = 0;

  for (const [piiType, values] of Object.entries(mapping)) {
    const count     = Object.keys(values).length;
    counts[piiType] = count;
    total          += count;
  }

  return { ...counts, total };
}

// ── Express app ───────────────────────────────────────────────────────────────
const app = express();

app.use(cors());
app.use(express.json());

// ── POST /api/redact — upload + process ──────────────────────────────────────
app.post("/api/redact", upload.array("files"), async (req, res) => {
  if (!req.files || req.files.length === 0) {
    return res.status(400).json({ error: "No .docx files uploaded." });
  }

  const sessionId = req.sessionId;

  // Process all uploaded files in parallel
  const jobs = req.files.map(async (file) => {
    const fileId      = path.basename(file.filename, path.extname(file.filename)).split("__")[0];
    const outputPath  = path.join(path.dirname(file.path), `${fileId}__output.docx`);
    const mappingPath = path.join(path.dirname(file.path), `${fileId}__mapping.json`);

    try {
      await runPiiRedactor(file.path, outputPath, mappingPath);

      // Parse the mapping file for PII counts
      const counts = await parseMappingCounts(mappingPath);

      return {
        fileId,
        originalName: file.originalname,
        status:       "done",
        downloadUrl:  `/api/download/${sessionId}/${fileId}`,
        counts,
      };
    } catch (err) {
      // execFile rejects with an error that has .stderr on it
      const stderr = err.stderr || err.message || "Unknown error";
      console.error(`[redact] FAILED for ${file.originalname}:`, stderr);
      return {
        fileId,
        originalName: file.originalname,
        status:       "failed",
        error:        stderr.slice(-800), // last 800 chars of stderr to the client
      };
    }
  });

  const results = await Promise.all(jobs);
  res.json({ sessionId, results });
});

// ── GET /api/download/:sessionId/:fileId — serve redacted .docx ───────────────
app.get("/api/download/:sessionId/:fileId", async (req, res) => {
  const { sessionId, fileId } = req.params;

  // Basic path-traversal guard — UUIDs only
  if (!/^[0-9a-f-]+$/i.test(sessionId) || !/^[0-9a-f-]+$/i.test(fileId)) {
    return res.status(400).json({ error: "Invalid session or file ID." });
  }

  const sessionDir  = path.join(TEMP_DIR, sessionId);
  const outputFile  = path.join(sessionDir, `${fileId}__output.docx`);

  if (!fs.existsSync(outputFile)) {
    return res.status(404).json({ error: "File not found or already cleaned up." });
  }

  // Find original filename from the input file (for the Content-Disposition header)
  let downloadName = "redacted.docx";
  try {
    const dirEntries = await fsp.readdir(sessionDir);
    const match      = dirEntries.find(
      (f) => f.startsWith(fileId) && !f.includes("output") && !f.includes("mapping")
    );
    if (match) {
      const originalName = match.split("__").slice(1).join("__");
      downloadName       = originalName.replace(/\.docx$/i, "_redacted.docx");
    }
  } catch { /* ignore */ }

  res.download(outputFile, downloadName, (err) => {
    if (err && !res.headersSent) {
      console.error("[download] error:", err.message);
    }
    // Optionally delete the file immediately after download (uncomment if desired):
    // fsp.rm(sessionDir, { recursive: true, force: true }).catch(() => {});
  });
});

// ── GET /api/health — simple health check ─────────────────────────────────────
app.get("/api/health", (_req, res) => {
  res.json({ status: "ok", tempDir: TEMP_DIR });
});

// ── Error handler ─────────────────────────────────────────────────────────────
app.use((err, req, res, _next) => {
  console.error("[express error]", err.message);
  res.status(400).json({ error: err.message });
});

// ── Serve React Static Build (Production) ────────────────────────────────────
const CLIENT_DIST = path.join(__dirname, "..", "client", "dist");
if (fs.existsSync(CLIENT_DIST)) {
  app.use(express.static(CLIENT_DIST));
  app.get("*", (req, res, next) => {
    if (req.path.startsWith("/api")) return next();
    res.sendFile(path.join(CLIENT_DIST, "index.html"));
  });
}

// ── Start ─────────────────────────────────────────────────────────────────────
const PORT = process.env.PORT || 4000;
app.listen(PORT, () => {
  console.log(`\n  PII Redactor API running on http://localhost:${PORT}`);
  console.log(`  Temp directory: ${TEMP_DIR}\n`);
  scheduleCleanup();
});
