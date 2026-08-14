import { useState, useRef, useCallback } from "react";

// ── PII type display config ──────────────────────────────────────────────────
const PII_LABELS = {
  PERSON:        { emoji: "👤", label: "Names" },
  EMAIL:         { emoji: "📧", label: "Emails" },
  PHONE:         { emoji: "📱", label: "Phones" },
  ADDRESS:       { emoji: "📍", label: "Addresses" },
  DATE_OF_BIRTH: { emoji: "📅", label: "Dates" },
  CIN:           { emoji: "🏢", label: "CINs" },
  PAN:           { emoji: "🪪", label: "PANs" },
  SSN:           { emoji: "🔒", label: "SSNs" },
  CREDIT_CARD:   { emoji: "💳", label: "Cards" },
  IP_ADDRESS:    { emoji: "🌐", label: "IPs" },
  AADHAAR:       { emoji: "🪪", label: "Aadhaar" },
};

function getPiiLabel(type) {
  return PII_LABELS[type] ?? { emoji: "🔍", label: type };
}

// ── StatusBadge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const configs = {
    queued:     { label: "Queued",     dot: false },
    processing: { label: "Processing", dot: true  },
    done:       { label: "Done",       dot: false },
    failed:     { label: "Failed",     dot: false },
  };
  const cfg = configs[status] ?? { label: status, dot: false };

  return (
    <span className={`status-badge ${status}`}>
      {status === "processing" ? (
        <span className="spinner" />
      ) : (
        <span className={`status-dot${cfg.dot ? " pulse" : ""}`} />
      )}
      {cfg.label}
    </span>
  );
}

// ── PII chips ────────────────────────────────────────────────────────────────
function PiiSummary({ counts }) {
  const { total, ...typeCounts } = counts;
  const entries = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);

  return (
    <div className="pii-summary">
      <p className="pii-total">
        <span>{total}</span> PII items redacted
      </p>
      <div className="pii-chips">
        {entries.map(([type, count]) => {
          const { emoji, label } = getPiiLabel(type);
          return (
            <span key={type} className="pii-chip">
              <span>{emoji}</span>
              <span className="pii-chip-count">{count}</span>
              <span className="pii-chip-label">{label}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ── FileCard ─────────────────────────────────────────────────────────────────
function FileCard({ file }) {
  const { name, size, status, counts, downloadUrl, error } = file;

  const fileSizeKB = size ? `${(size / 1024).toFixed(0)} KB` : "";

  return (
    <div className={`file-card status-${status}`}>
      <div className="file-card-top">
        <span className="file-icon">📄</span>

        <div className="file-info">
          <div className="file-name" title={name}>{name}</div>
          {fileSizeKB && (
            <div className="file-meta">{fileSizeKB}</div>
          )}
          {status === "processing" && (
            <div className="progress-bar-wrap">
              <div className="progress-bar" />
            </div>
          )}
        </div>

        <StatusBadge status={status} />
      </div>

      {/* Done — show download + PII summary */}
      {status === "done" && counts && (
        <>
          <PiiSummary counts={counts} />
          <div className="card-actions">
            <a
              href={downloadUrl}
              download
              className="btn-download"
            >
              ⬇ Download Redacted File
            </a>
          </div>
        </>
      )}

      {/* Failed — show error */}
      {status === "failed" && error && (
        <div className="error-block">{error}</div>
      )}
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────
export default function App() {
  // pending: files chosen but not yet uploaded (File objects)
  const [pending, setPending]   = useState([]);
  // results: processed file cards (each has { id, name, size, status, ... })
  const [results, setResults]   = useState([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging]  = useState(false);
  const inputRef = useRef(null);

  // ── File selection ──────────────────────────────────────────────────────
  const addFiles = useCallback((fileList) => {
    const newFiles = Array.from(fileList).filter(
      (f) => f.name.toLowerCase().endsWith(".docx")
    );
    if (newFiles.length === 0) return;
    setPending((prev) => {
      const existingNames = new Set(prev.map((f) => f.name));
      return [...prev, ...newFiles.filter((f) => !existingNames.has(f.name))];
    });
  }, []);

  const handleInputChange = (e) => addFiles(e.target.files);

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  };

  const handleDragOver = (e) => { e.preventDefault(); setDragging(true); };
  const handleDragLeave = () => setDragging(false);

  const removePending = (name) =>
    setPending((prev) => prev.filter((f) => f.name !== name));

  const clearPending = () => {
    setPending([]);
    if (inputRef.current) inputRef.current.value = "";
  };

  // ── Upload & process ─────────────────────────────────────────────────────
  const handleUpload = async () => {
    if (pending.length === 0 || uploading) return;

    setUploading(true);

    // Add placeholder cards immediately so the user sees progress
    const placeholders = pending.map((file) => ({
      id:     file.name + Date.now(),
      name:   file.name,
      size:   file.size,
      status: "processing",
    }));
    setResults((prev) => [...placeholders, ...prev]);
    setPending([]);
    if (inputRef.current) inputRef.current.value = "";

    // Build multipart form data
    const formData = new FormData();
    pending.forEach((file) => formData.append("files", file));

    try {
      const resp = await fetch("/api/redact", {
        method: "POST",
        body:   formData,
      });

      const data = await resp.json();

      if (!resp.ok) {
        // Whole-request error (e.g., no files, wrong type)
        setResults((prev) =>
          prev.map((card) =>
            placeholders.some((p) => p.id === card.id)
              ? { ...card, status: "failed", error: data.error ?? "Server error" }
              : card
          )
        );
        return;
      }

      // Map each result back to its placeholder by original filename
      const resultByName = {};
      for (const r of data.results) {
        resultByName[r.originalName] = r;
      }

      setResults((prev) =>
        prev.map((card) => {
          if (!placeholders.some((p) => p.id === card.id)) return card;
          const r = resultByName[card.name];
          if (!r) return { ...card, status: "failed", error: "No result returned for this file." };

          if (r.status === "done") {
            return {
              ...card,
              status:      "done",
              downloadUrl: r.downloadUrl,
              counts:      r.counts,
            };
          } else {
            return {
              ...card,
              status: "failed",
              error:  r.error ?? "Unknown error",
            };
          }
        })
      );
    } catch (err) {
      // Network error
      setResults((prev) =>
        prev.map((card) =>
          placeholders.some((p) => p.id === card.id)
            ? { ...card, status: "failed", error: `Network error: ${err.message}` }
            : card
        )
      );
    } finally {
      setUploading(false);
    }
  };

  const clearResults = () => setResults([]);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="app">
      {/* ── Header ── */}
      <header className="header">
        <span className="header-icon">🔒</span>
        <div>
          <h1>PII Redaction Tool</h1>
          <p>Automated PII detection &amp; pseudonymisation for .docx files</p>
        </div>
        <span className="header-badge">Assignment Demo</span>
      </header>

      <main className="main">
        {/* ── Drop Zone ── */}
        <div
          className={`dropzone${dragging ? " dragging" : ""}`}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            multiple
            onChange={handleInputChange}
          />
          <span className="dropzone-icon">📂</span>
          <h2>Drag &amp; drop .docx files here</h2>
          <p>or click anywhere in this box to browse</p>
          <span className="btn-browse">Browse Files</span>
          <p className="dropzone-hint">Only .docx files · Up to 50 MB each · Multiple files supported</p>
        </div>

        {/* ── Pending queue ── */}
        {pending.length > 0 && (
          <>
            <div className="section-title">Ready to process</div>
            <div className="file-list">
              {pending.map((file) => (
                <div key={file.name} className="file-card">
                  <div className="file-card-top">
                    <span className="file-icon">📄</span>
                    <div className="file-info">
                      <div className="file-name">{file.name}</div>
                      <div className="file-meta">{(file.size / 1024).toFixed(0)} KB</div>
                    </div>
                    <StatusBadge status="queued" />
                    <button
                      className="btn-ghost"
                      style={{ marginLeft: 4 }}
                      onClick={() => removePending(file.name)}
                      title="Remove"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="upload-actions">
              <p className="pending-count">
                <strong>{pending.length}</strong>{" "}
                file{pending.length !== 1 ? "s" : ""} selected
              </p>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn-ghost" onClick={clearPending}>
                  Clear
                </button>
                <button
                  className="btn-primary"
                  onClick={handleUpload}
                  disabled={uploading}
                >
                  {uploading ? (
                    <>
                      <span className="spinner" style={{ borderTopColor: "#fff", width: 14, height: 14 }} />
                      Processing…
                    </>
                  ) : (
                    <>🔒 Redact {pending.length > 1 ? `${pending.length} Files` : "File"}</>
                  )}
                </button>
              </div>
            </div>
          </>
        )}

        {/* ── Results ── */}
        {results.length > 0 && (
          <>
            <div className="section-title" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>Results</span>
              <button className="btn-ghost" style={{ fontSize: 12 }} onClick={clearResults}>
                Clear all
              </button>
            </div>
            <div className="file-list">
              {results.map((file) => (
                <FileCard key={file.id} file={file} />
              ))}
            </div>
          </>
        )}

        {results.length === 0 && pending.length === 0 && (
          <div className="empty-state">
            <p>No files processed yet. Upload a .docx file above to get started.</p>
          </div>
        )}
      </main>
    </div>
  );
}
