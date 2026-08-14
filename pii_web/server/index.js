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
 *         <id>__input.docx    ← uploaded file (multer saves here)
 *         <id>__output.docx   ← written by Python CLI
 *         <id>__mapping.json  ← written by Python CLI
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

// ── Structured logger ─────────────────────────────────────────────────────────
function log(level, tag, msg, extra = "") {
  const ts = new Date().toISOString();
  const line = `[${ts}] [${level.toUpperCase().padEnd(5)}] [${tag}] ${msg}${extra ? " | " + JSON.stringify(extra) : ""}`;
  if (level === "error") {
    console.error(line);
  } else {
    console.log(line);
  }
}

const logger = {
  info:  (tag, msg, extra) => log("info",  tag, msg, extra),
  warn:  (tag, msg, extra) => log("warn",  tag, msg, extra),
  error: (tag, msg, extra) => log("error", tag, msg, extra),
  debug: (tag, msg, extra) => log("debug", tag, msg, extra),
};

// ── Paths ─────────────────────────────────────────────────────────────────────
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TEMP_DIR  = path.join(__dirname, "temp");

// Ensure temp dir exists at startup
try {
  if (!fs.existsSync(TEMP_DIR)) {
    fs.mkdirSync(TEMP_DIR, { recursive: true });
  }
  logger.info("startup", `Temp directory ready: ${TEMP_DIR}`);
} catch (err) {
  logger.error("startup", "Failed to create temp directory", { error: err.message, path: TEMP_DIR });
  process.exit(1);
}

// ── Auto-cleanup: delete session dirs older than 30 minutes ──────────────────
const CLEANUP_INTERVAL_MS = 5 * 60 * 1000;   // run every 5 min
const SESSION_TTL_MS      = 30 * 60 * 1000;  // delete after 30 min

function scheduleCleanup() {
  setInterval(async () => {
    try {
      const entries = await fsp.readdir(TEMP_DIR, { withFileTypes: true });
      const now = Date.now();
      let cleaned = 0;
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        const dir  = path.join(TEMP_DIR, entry.name);
        const stat = await fsp.stat(dir);
        if (now - stat.mtimeMs > SESSION_TTL_MS) {
          await fsp.rm(dir, { recursive: true, force: true });
          cleaned++;
        }
      }
      if (cleaned > 0) {
        logger.info("cleanup", `Removed ${cleaned} expired session(s)`);
      }
    } catch (err) {
      logger.error("cleanup", "Error during cleanup", { error: err.message });
    }
  }, CLEANUP_INTERVAL_MS);
}

// ── Multer — save uploads to temp/<sessionId>/ ───────────────────────────────
const storage = multer.diskStorage({
  destination(req, file, cb) {
    if (!req.sessionId) req.sessionId = uuidv4();
    const sessionDir = path.join(TEMP_DIR, req.sessionId);
    try {
      fs.mkdirSync(sessionDir, { recursive: true });
      cb(null, sessionDir);
    } catch (err) {
      logger.error("multer", "Failed to create session dir", { error: err.message, sessionDir });
      cb(err);
    }
  },
  filename(req, file, cb) {
    const fileId   = uuidv4();
    const safeName = file.originalname.replace(/[^a-zA-Z0-9._-]/g, "_");
    logger.debug("multer", `Saving upload: ${file.originalname}`, { fileId, safeName });
    cb(null, `${fileId}__${safeName}`);
  },
});

const upload = multer({
  storage,
  fileFilter(req, file, cb) {
    const isDocx = file.mimetype === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
      || file.originalname.toLowerCase().endsWith(".docx");
    if (isDocx) {
      cb(null, true);
    } else {
      logger.warn("multer", `Rejected non-docx file: ${file.originalname}`, { mimetype: file.mimetype });
      cb(new Error(`Only .docx files are accepted. Got: ${file.originalname}`));
    }
  },
  limits: { fileSize: 50 * 1024 * 1024 }, // 50 MB cap
});

// ── Python subprocess invocation ──────────────────────────────────────────────
/**
 * ┌─────────────────────────────────────────────────────────────────────────┐
 * │  ★ THIS IS WHERE THE PYTHON SUBPROCESS IS INVOKED ★                    │
 * │                                                                         │
 * │  Command equivalent:                                                    │
 * │    python3 -m pii_redactor.redactor "<inputPath>"                       │
 * │             --output "<outputPath>"                                     │
 * │             --mapping-output "<mappingPath>"                            │
 * │             --log-level WARNING                                         │
 * │                                                                         │
 * │  Uses execFile (not exec) — each arg is a separate array element,       │
 * │  so filenames with spaces/special chars are safe from shell injection.  │
 * └─────────────────────────────────────────────────────────────────────────┘
 */
async function runPiiRedactor(inputPath, outputPath, mappingPath) {
  // In Docker: __dirname = /app/pii_web/server → CWD = /app (project root)
  // On Windows local: __dirname = ...\pii_web\server → CWD = ...\Scaler\
  const PYTHON_CWD = path.join(__dirname, "..", "..");

  // Binary candidates: try python3 first on Linux (Render/Docker), python first on Windows
  const candidates = process.env.PYTHON_BIN
    ? [process.env.PYTHON_BIN]
    : (process.platform === "win32" ? ["python", "python3"] : ["python3", "python"]);

  const args = [
    "-m", "pii_redactor.redactor",
    inputPath,
    "--output",         outputPath,
    "--mapping-output", mappingPath,
    "--log-level",      "WARNING",
  ];

  logger.info("python", `Starting PII redaction`, {
    cwd: PYTHON_CWD,
    candidates,
    input: path.basename(inputPath),
  });

  let lastError;
  for (const bin of candidates) {
    try {
      logger.debug("python", `Trying binary: ${bin}`);
      const result = await execFileAsync(bin, args, {
        cwd:       PYTHON_CWD,
        timeout:   5 * 60 * 1000,    // 5-minute timeout
        maxBuffer: 10 * 1024 * 1024, // 10 MB buffer
      });

      if (result.stderr) {
        // Log any warnings from Python (non-fatal)
        logger.warn("python", "Python stderr output", { stderr: result.stderr.slice(0, 500) });
      }
      logger.info("python", `Redaction completed successfully using binary: ${bin}`);
      return result;
    } catch (err) {
      lastError = err;
      if (err.code === "ENOENT") {
        logger.warn("python", `Binary not found: ${bin} (ENOENT), trying next...`);
        continue;
      }
      // Python process ran but exited with error
      logger.error("python", `Python process failed`, {
        bin,
        exitCode: err.code,
        stderr:   (err.stderr || "").slice(-800),
        stdout:   (err.stdout || "").slice(-400),
      });
      throw err;
    }
  }

  logger.error("python", `All Python binary candidates failed`, { candidates });
  throw lastError;
}

// ── Parse pii_mapping.json → summary counts per type ─────────────────────────
async function parseMappingCounts(mappingPath) {
  try {
    const raw     = await fsp.readFile(mappingPath, "utf-8");
    const mapping = JSON.parse(raw);
    const counts  = {};
    let total     = 0;

    for (const [piiType, values] of Object.entries(mapping)) {
      const count     = Object.keys(values).length;
      counts[piiType] = count;
      total          += count;
    }

    logger.info("mapping", `Parsed PII mapping`, { types: Object.keys(counts), total });
    return { ...counts, total };
  } catch (err) {
    logger.error("mapping", `Failed to parse mapping file`, { path: mappingPath, error: err.message });
    throw err;
  }
}

// ── Express app ───────────────────────────────────────────────────────────────
const app = express();

// ── CORS ──────────────────────────────────────────────────────────────────────
app.use(cors({
  origin: "*",                     // Allow any origin (tighten in real production)
  methods: ["GET", "POST"],
  allowedHeaders: ["Content-Type"],
}));

app.use(express.json());

// ── Request logger middleware ─────────────────────────────────────────────────
app.use((req, _res, next) => {
  logger.info("http", `${req.method} ${req.path}`, { ip: req.ip });
  next();
});

// ── GET /api/health — health + environment check ──────────────────────────────
app.get("/api/health", (_req, res) => {
  const info = {
    status:   "ok",
    platform: process.platform,
    node:     process.version,
    tempDir:  TEMP_DIR,
    tempExists: fs.existsSync(TEMP_DIR),
    pythonBin:  process.env.PYTHON_BIN || (process.platform === "win32" ? "python" : "python3"),
    clientDist: fs.existsSync(path.join(__dirname, "..", "client", "dist")),
    env:      process.env.NODE_ENV || "development",
  };
  logger.info("health", "Health check requested", info);
  res.json(info);
});

// ── POST /api/redact — upload + process ──────────────────────────────────────
app.post("/api/redact", upload.array("files"), async (req, res) => {
  if (!req.files || req.files.length === 0) {
    logger.warn("redact", "Request with no files received");
    return res.status(400).json({ error: "No .docx files uploaded." });
  }

  const sessionId = req.sessionId;
  logger.info("redact", `Processing ${req.files.length} file(s)`, { sessionId });

  // Process all uploaded files in parallel
  const jobs = req.files.map(async (file) => {
    const fileId      = path.basename(file.filename, path.extname(file.filename)).split("__")[0];
    const outputPath  = path.join(path.dirname(file.path), `${fileId}__output.docx`);
    const mappingPath = path.join(path.dirname(file.path), `${fileId}__mapping.json`);

    logger.info("redact", `Starting job for: ${file.originalname}`, { fileId, size: file.size });

    try {
      const startMs = Date.now();
      await runPiiRedactor(file.path, outputPath, mappingPath);
      const elapsedSec = ((Date.now() - startMs) / 1000).toFixed(1);

      const counts = await parseMappingCounts(mappingPath);
      logger.info("redact", `Job done: ${file.originalname}`, { fileId, elapsedSec, total: counts.total });

      return {
        fileId,
        originalName: file.originalname,
        status:       "done",
        downloadUrl:  `/api/download/${sessionId}/${fileId}`,
        counts,
        elapsedSec,
      };
    } catch (err) {
      const stderr = err.stderr || err.message || "Unknown error";
      logger.error("redact", `Job FAILED: ${file.originalname}`, {
        fileId,
        error: err.message,
        stderr: stderr.slice(-500),
      });
      return {
        fileId,
        originalName: file.originalname,
        status:       "failed",
        error:        stderr.slice(-800),
      };
    }
  });

  const results = await Promise.all(jobs);
  const summary = results.map(r => ({ name: r.originalName, status: r.status }));
  logger.info("redact", `All jobs complete for session ${sessionId}`, { results: summary });

  res.json({ sessionId, results });
});

// ── GET /api/download/:sessionId/:fileId — serve redacted .docx ───────────────
app.get("/api/download/:sessionId/:fileId", async (req, res) => {
  const { sessionId, fileId } = req.params;

  // Path-traversal guard — UUIDs only
  if (!/^[0-9a-f-]+$/i.test(sessionId) || !/^[0-9a-f-]+$/i.test(fileId)) {
    logger.warn("download", "Invalid session/fileId in download request", { sessionId, fileId });
    return res.status(400).json({ error: "Invalid session or file ID." });
  }

  const sessionDir = path.join(TEMP_DIR, sessionId);
  const outputFile = path.join(sessionDir, `${fileId}__output.docx`);

  if (!fs.existsSync(outputFile)) {
    logger.warn("download", "Output file not found", { outputFile });
    return res.status(404).json({ error: "File not found or already cleaned up." });
  }

  // Find original filename for the Content-Disposition header
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

  logger.info("download", `Serving download: ${downloadName}`, { sessionId, fileId });

  res.download(outputFile, downloadName, (err) => {
    if (err && !res.headersSent) {
      logger.error("download", "Error during file download", { error: err.message });
    }
  });
});

// ── Serve React Static Build (must be BEFORE error handler) ──────────────────
const CLIENT_DIST = path.join(__dirname, "..", "client", "dist");
if (fs.existsSync(CLIENT_DIST)) {
  logger.info("startup", `Serving React build from: ${CLIENT_DIST}`);
  app.use(express.static(CLIENT_DIST));
  // Catch-all for SPA routing — must not intercept /api/* routes
  app.get(/^(?!\/api).*/, (_req, res) => {
    res.sendFile(path.join(CLIENT_DIST, "index.html"));
  });
} else {
  logger.warn("startup", `React build not found at ${CLIENT_DIST} — API-only mode`);
}

// ── Global error handler (must be LAST middleware) ────────────────────────────
app.use((err, req, res, _next) => {
  logger.error("express", `Unhandled middleware error: ${err.message}`, {
    path: req.path,
    method: req.method,
  });
  res.status(err.status || 500).json({ error: err.message || "Internal server error" });
});

// ── Process-level crash handlers ──────────────────────────────────────────────
process.on("uncaughtException", (err) => {
  logger.error("process", `UNCAUGHT EXCEPTION — server will exit`, { error: err.message, stack: err.stack });
  process.exit(1);
});

process.on("unhandledRejection", (reason) => {
  logger.error("process", `UNHANDLED PROMISE REJECTION`, { reason: String(reason) });
  // Don't exit on unhandled rejections — log and continue
});

// ── Start ─────────────────────────────────────────────────────────────────────
const PORT = parseInt(process.env.PORT || "4000", 10);
const HOST = "0.0.0.0"; // Must bind to 0.0.0.0 on Render/Docker (not just localhost)

app.listen(PORT, HOST, () => {
  logger.info("startup", `PII Redactor API listening on http://${HOST}:${PORT}`);
  logger.info("startup", `Environment: ${process.env.NODE_ENV || "development"}`);
  logger.info("startup", `Platform: ${process.platform}, Node: ${process.version}`);
  logger.info("startup", `Temp dir: ${TEMP_DIR}`);
  logger.info("startup", `Python binary: ${process.env.PYTHON_BIN || "auto-detect"}`);
  scheduleCleanup();
});
