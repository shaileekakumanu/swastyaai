
import React, { useMemo, useRef, useState } from "react";
import axios from "axios";
import "./App.css";

const API_URL = "http://127.0.0.1:8000/upload";

const STATUS = {
  Normal: "normal",
  High: "high",
  Low: "low",
  Borderline: "borderline",
  Abnormal: "abnormal",
  Critical: "critical",
  Unknown: "unknown",
};

function getStatus(value, range, fallback = "Unknown") {
  const match = String(range ?? "").match(
    /^\s*(-?\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(-?\d+(?:\.\d+)?)\s*$/i
  );
  const number = Number(value);

  if (
    value === "" ||
    !Number.isFinite(number) ||
    !match ||
    Number(match[1]) > Number(match[2])
  ) {
    return fallback;
  }

  if (number < Number(match[1])) return "Low";
  if (number > Number(match[2])) return "High";
  return "Normal";
}

function normalizeStatus(status) {
  const value = String(status || "").toLowerCase();

  if (value.includes("critical")) return "Critical";
  if (value.includes("border")) return "Borderline";
  if (value.includes("high")) return "High";
  if (value.includes("low")) return "Low";
  if (value.includes("abnormal")) return "Abnormal";
  if (value.includes("normal")) return "Normal";

  return "Unknown";
}

function toArray(value) {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (value == null || value === "") return [];
  return [value];
}

function StatCard({ title, value, detail, icon, color }) {
  return (
    <article className={`stat-card ${color}`}>
      <div className="stat-top">
        <span>{title}</span>
        <span className="stat-icon">{icon}</span>
      </div>
      <div className="stat-value">{value}</div>
      <div className="stat-detail">{detail}</div>
    </article>
  );
}

function StatusBadge({ status }) {
  const safeStatus = STATUS[status] ? status : "Unknown";

  return (
    <span className={`status-badge ${STATUS[safeStatus]}`}>
      {safeStatus}
    </span>
  );
}

function InsightList({ title, items }) {
  const list = toArray(items);

  if (!list.length) return null;

  return (
    <div className="insight-list">
      <h4>{title}</h4>
      <ul>
        {list.map((item, index) => (
          <li key={`${title}-${index}`}>{String(item)}</li>
        ))}
      </ul>
    </div>
  );
}

function SeverityBadge({ severity }) {
  const value = String(severity || "not assessed")
    .trim()
    .toLowerCase();

  const label = {
    routine: "Routine review",
    prompt: "Prompt medical review",
    urgent: "Urgent medical review",
  }[value] || "Severity not confirmed";

  return (
    <div className="next-steps">
      <h4>Follow-up priority</h4>
      <p><strong>{label}</strong></p>
    </div>
  );
}

export default function App() {
  const fileRef = useRef(null);

  const [file, setFile] = useState(null);
  const [tests, setTests] = useState([]);
  const [reportName, setReportName] = useState("");
  const [ai, setAi] = useState(null);
  const [qualitative, setQualitative] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("All");

  const stats = useMemo(() => {
    const result = {
      total: tests.length,
      normal: 0,
      high: 0,
      low: 0,
      other: 0,
    };

    tests.forEach((test) => {
      const status = normalizeStatus(test.status);

      if (status === "Normal") result.normal++;
      else if (status === "High") result.high++;
      else if (status === "Low") result.low++;
      else if (status !== "Unknown") result.other++;
    });

    return result;
  }, [tests]);

  const visibleTests = useMemo(() => {
    return tests.filter((test) => {
      const matchesSearch = [
        test.name,
        test.value,
        test.range,
        test.unit,
      ].some((value) =>
        String(value ?? "").toLowerCase().includes(search.toLowerCase())
      );

      const matchesFilter =
        filter === "All" || normalizeStatus(test.status) === filter;

      return matchesSearch && matchesFilter;
    });
  }, [tests, search, filter]);

  function selectFile(selected) {
    if (!selected) return;

    if (!/\.(pdf|png|jpe?g|webp|bmp|tif?f)$/i.test(selected.name)) {
      setError("Choose a PDF or supported image file.");
      return;
    }

    setFile(selected);
    setError("");
    setMessage("");
  }

  async function uploadReport(event) {
    event.preventDefault();

    if (!file) {
      setError("Please choose a report first.");
      return;
    }

    setLoading(true);
    setError("");
    setMessage("");
    setTests([]);
    setAi(null);
    setQualitative([]);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await axios.post(API_URL, formData, {
        timeout: 180000,
      });

      const body = response.data || {};
      const data = body.data || body;
      const rawTests = Array.isArray(data.tests) ? data.tests : [];

      setTests(
        rawTests.map((test, index) => {
          const value = String(test.value ?? test.result ?? "");
          const range = String(test.range ?? test.reference_range ?? "");
          const suppliedStatus = normalizeStatus(test.status);
          const status =
            suppliedStatus === "Unknown"
              ? getStatus(value, range)
              : suppliedStatus;

          return {
            id: `${index}-${test.name || test.test || "test"}`,
            name: String(test.name ?? test.test ?? "Unnamed test"),
            value,
            range,
            unit: String(test.unit ?? ""),
            status,
          };
        })
      );

      setReportName(body.filename || file.name);

      // Supports both the current backend and alternate response shapes.
      setAi(
        body.ai_summary ??
        body.aiSummary ??
        data.ai_summary ??
        data.aiSummary ??
        null
      );

      setQualitative(
        toArray(data.qualitative_findings ?? body.qualitative_findings)
      );

      setMessage(
        rawTests.length
          ? "Your report has been processed."
          : "Upload completed, but no structured test results were detected."
      );
    } catch (err) {
      const detail =
        err.response?.data?.detail || err.response?.data?.message;

      setError(
        detail
          ? String(detail)
          : err.code === "ECONNABORTED"
            ? "Processing timed out. Check that FastAPI and Ollama are running."
            : "Cannot connect to FastAPI. Start your backend and try again."
      );
    } finally {
      setLoading(false);
    }
  }

  function editTest(id, field, value) {
    setTests((current) =>
      current.map((test) => {
        if (test.id !== id) return test;

        const updated = { ...test, [field]: value };

        if (field === "value" || field === "range") {
          updated.status = getStatus(
            updated.value,
            updated.range,
            test.status
          );
        }

        return updated;
      })
    );

    setMessage(
      "Edits are local. The AI explanation has not been regenerated."
    );
  }

  function exportCsv() {
    if (!tests.length) {
      setError("Upload a report before exporting.");
      return;
    }

    const rows = [
      ["Test", "Value", "Reference Range", "Unit", "Status"],
      ...tests.map((test) => [
        test.name,
        test.value,
        test.range,
        test.unit,
        test.status,
      ]),
    ];

    const csv = rows
      .map((row) =>
        row
          .map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`)
          .join(",")
      )
      .join("\r\n");

    const blob = new Blob(["\uFEFF", csv], {
      type: "text/csv;charset=utf-8;",
    });

    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = `${
      (reportName || "swasthya-report")
        .replace(/\.[^.]+$/, "")
        .replace(/[^\w-]+/g, "_")
    }-results.csv`;

    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function resetReport() {
    setFile(null);
    setTests([]);
    setReportName("");
    setAi(null);
    setQualitative([]);
    setError("");
    setMessage("");
    setSearch("");
    setFilter("All");

    if (fileRef.current) fileRef.current.value = "";
  }

  // IMPORTANT: the Python backend returns entries under ai.items.
  const aiItems = toArray(
    ai?.items ?? ai?.insights ?? ai?.results ?? ai?.findings
  );

  const aiSummary = ai?.summary ?? ai?.overall_summary ?? "";

  const disclaimer =
    ai?.disclaimer ||
    "This tool provides educational information only. It does not diagnose medical conditions or prescribe treatment. Consult a qualified healthcare professional about your results.";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#overview">
          <span className="brand-logo">✚</span>
          <span>
            <strong>Swasthya<span>AI</span></strong>
            <small>Understand your health</small>
          </span>
        </a>

        <p className="nav-heading">WORKSPACE</p>

        <nav className="side-nav">
          <a className="nav-link active" href="#overview">▦ <span>Overview</span></a>
          <a className="nav-link" href="#results">☷ <span>Lab results</span></a>
          <a className="nav-link" href="#insights">✧ <span>AI insights</span></a>
        </nav>

        <div className="sidebar-note">
          <span className="note-symbol">♡</span>
          <strong>Your health, made clearer.</strong>
          <p>Understand your report and prepare questions for your clinician.</p>
        </div>

        <div className="sidebar-footer">
          <span className="online-dot" />
          Local AI workflow
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="mobile-brand">
            <span className="brand-logo">✚</span>
            <strong>Swasthya<span>AI</span></strong>
          </div>

          <div className="breadcrumb">
            Workspace <span>/</span> <strong>Health overview</strong>
          </div>

          <span className="private-pill">● Private workspace</span>
        </header>

        <div className="page-content">
          <section className="welcome-row" id="overview">
            <div>
              <p className="eyebrow">YOUR PERSONAL REPORT COMPANION</p>
              <h1>Health overview</h1>
              <p className="subtitle">
                Make your lab results easier to understand, one report at a time.
              </p>
            </div>

            {tests.length > 0 && (
              <button className="btn btn-light" onClick={resetReport}>
                + New report
              </button>
            )}
          </section>

          <section className="upload-card">
            <div className="upload-description">
              <div className="upload-icon">↑</div>
              <div>
                <h2>Upload a lab report</h2>
                <p>Extract test results and get a plain-language AI explanation.</p>
                <div className="file-types">
                  <span>PDF</span><span>JPG</span><span>PNG</span><span>WEBP</span>
                  <small>Supported formats</small>
                </div>
              </div>
            </div>

            <form className="upload-controls" onSubmit={uploadReport}>
              <input
                ref={fileRef}
                className="hidden-input"
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,application/pdf,image/*"
                onChange={(event) => selectFile(event.target.files?.[0])}
              />

              <button
                type="button"
                className="btn btn-light"
                onClick={() => fileRef.current?.click()}
              >
                Choose file
              </button>

              <button
                type="submit"
                className="btn btn-primary"
                disabled={!file || loading}
              >
                {loading ? "Processing…" : "Analyze report"}
              </button>

              {file && (
                <div className="selected-file">
                  <span>▤</span>
                  <span title={file.name}>{file.name}</span>
                  <button
                    type="button"
                    aria-label="Remove selected file"
                    onClick={() => {
                      setFile(null);
                      if (fileRef.current) fileRef.current.value = "";
                    }}
                  >
                    ×
                  </button>
                </div>
              )}
            </form>

            <div className="upload-footnote">
              ⌑ Your report is sent to your configured FastAPI service.
            </div>
          </section>

          {error && (
            <div className="notice error" role="alert">
              <strong>Something needs attention</strong>
              <p>{error}</p>
              <button onClick={() => setError("")}>×</button>
            </div>
          )}

          {message && !error && (
            <div className="notice success" role="status">
              <p>{message}</p>
              <button onClick={() => setMessage("")}>×</button>
            </div>
          )}

          {loading && (
            <div className="loading-card">
              <span className="loader" />
              <div>
                <strong>Analyzing your report</strong>
                <p>Extracting report text and preparing your AI summary.</p>
              </div>
            </div>
          )}

          <section className="stats-grid">
            <StatCard title="Tests detected" value={stats.total} detail="Results extracted" icon="▤" color="blue" />
            <StatCard title="In reference range" value={stats.normal} detail="Marked normal" icon="✓" color="green" />
            <StatCard title="High results" value={stats.high} detail="Above reference range" icon="↗" color="orange" />
            <StatCard title="Low results" value={stats.low} detail="Below reference range" icon="↘" color="purple" />
            <StatCard title="Other flags" value={stats.other} detail="Review the details" icon="!" color="red" />
          </section>

          <section className="section" id="results">
            <div className="section-heading">
              <div>
                <p className="eyebrow">EXTRACTED DATA</p>
                <h2>Laboratory results</h2>
                <p className="section-subtitle">
                  {reportName ? <>Report: <strong>{reportName}</strong></> : "Upload a report to view its extracted results."}
                </p>
              </div>

              <button
                className="btn btn-light"
                onClick={exportCsv}
                disabled={!tests.length}
              >
                ↓ Export CSV
              </button>
            </div>

            {tests.length ? (
              <div className="table-card">
                <div className="table-toolbar">
                  <span>{visibleTests.length} of {tests.length} tests</span>

                  <div className="table-tools">
                    <input
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Search tests…"
                      aria-label="Search tests"
                    />

                    <select
                      value={filter}
                      onChange={(event) => setFilter(event.target.value)}
                      aria-label="Filter results by status"
                    >
                      {["All", "Normal", "High", "Low", "Borderline", "Abnormal", "Critical", "Unknown"].map((status) => (
                        <option key={status} value={status}>
                          {status === "All" ? "All statuses" : status}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>TEST NAME</th>
                        <th>RESULT</th>
                        <th>REFERENCE RANGE</th>
                        <th>UNIT</th>
                        <th>STATUS</th>
                      </tr>
                    </thead>

                    <tbody>
                      {visibleTests.map((test) => (
                        <tr key={test.id}>
                          <td>
                            <input
                              aria-label="Test name"
                              className="cell-input name-input"
                              value={test.name}
                              onChange={(event) => editTest(test.id, "name", event.target.value)}
                            />
                          </td>
                          <td>
                            <input
                              aria-label="Result value"
                              className="cell-input value-input"
                              value={test.value}
                              onChange={(event) => editTest(test.id, "value", event.target.value)}
                            />
                          </td>
                          <td>
                            <input
                              aria-label="Reference range"
                              className="cell-input range-input"
                              value={test.range}
                              onChange={(event) => editTest(test.id, "range", event.target.value)}
                            />
                          </td>
                          <td>
                            <input
                              aria-label="Result unit"
                              className="cell-input unit-input"
                              value={test.unit}
                              onChange={(event) => editTest(test.id, "unit", event.target.value)}
                            />
                          </td>
                          <td><StatusBadge status={test.status} /></td>
                        </tr>
                      ))}

                      {!visibleTests.length && (
                        <tr><td colSpan="5" className="empty-row">No matching results.</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="table-footer">
                  ✎ Edits stay on this page. AI insights are not automatically regenerated.
                </div>
              </div>
            ) : (
              <div className="empty-state">
                <div className="empty-icon">▤</div>
                <h3>Your report results will appear here</h3>
                <p>Upload a report to extract values, review reference ranges, and explore AI-generated explanations.</p>
              </div>
            )}
          </section>

          {qualitative.length > 0 && (
            <section className="section">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">REPORT NOTES</p>
                  <h2>Qualitative findings</h2>
                </div>
              </div>

              <div className="findings-grid">
                {qualitative.map((finding, index) => {
                  const item = typeof finding === "string"
                    ? { name: `Finding ${index + 1}`, value: finding }
                    : finding;

                  return (
                    <article className="finding-card" key={index}>
                      <span>✓</span>
                      <div>
                        <strong>{item.name || item.test || "Finding"}</strong>
                        <p>{item.value || item.result || item.description || JSON.stringify(item)}</p>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          )}

          <section className="section" id="insights">
            <div className="section-heading">
              <div>
                <p className="eyebrow">PLAIN-LANGUAGE EXPLANATION</p>
                <h2>AI health insights</h2>
                <p className="section-subtitle">
                  Educational context to help you prepare questions for your healthcare professional.
                </p>
              </div>
              <span className="ai-pill">✧ AI-assisted</span>
            </div>

            {ai ? (
              <div className="insights-wrap">
                {aiSummary && (
                  <article className="summary-card">
                    <span className="summary-icon">✧</span>
                    <div>
                      <h3>Report overview</h3>
                      <p>{typeof aiSummary === "string" ? aiSummary : JSON.stringify(aiSummary)}</p>
                    </div>
                  </article>
                )}

                {aiItems.length > 0 && (
                  <div className="insights-grid">
                    {aiItems.map((rawItem, index) => {
                      const item = typeof rawItem === "string"
                        ? { test: `Insight ${index + 1}`, possible_meaning: rawItem }
                        : rawItem;

                      const doctorAdvice =
                        item.doctor_advice || item.next_steps;

                      return (
                        <article className="insight-card" key={index}>
                          <div className="insight-heading">
                            <span>✧</span>
                            <div>
                              <h3>{item.test || item.name || `Insight ${index + 1}`}</h3>
                              {item.result && <small>Reported result: {item.result}</small>}
                            </div>
                          </div>

                          {item.possible_meaning && (
                            <div className="meaning">
                              <h4>What it may mean</h4>
                              <p>{item.possible_meaning}</p>
                            </div>
                          )}

                          <InsightList
                            title="Symptoms to watch for"
                            items={item.symptoms_to_watch}
                          />

                          <InsightList
                            title="Foods to eat"
                            items={item.foods_to_eat}
                          />

                          <InsightList
                            title="Lifestyle recommendations"
                            items={
                              item.lifestyle_recommendations?.length
                                ? item.lifestyle_recommendations
                                : item.diet_and_lifestyle
                            }
                          />

                          <InsightList
                            title="Precautions"
                            items={item.precautions}
                          />

                          {item.severity && (
                            <SeverityBadge severity={item.severity} />
                          )}

                          {doctorAdvice && (
                            <div className="next-steps">
                              <h4>Doctor consultation advice</h4>
                              <p>{doctorAdvice}</p>
                            </div>
                          )}

                          {item.next_steps && item.doctor_advice && (
                            <div className="next-steps">
                              <h4>Suggested next steps</h4>
                              <p>{item.next_steps}</p>
                            </div>
                          )}

                          <InsightList
                            title="Warning signs"
                            items={item.warning_signs}
                          />
                        </article>
                      );
                    })}
                  </div>
                )}

                {!aiSummary && !aiItems.length && (
                  <div className="empty-state">
                    <h3>No structured AI insights returned</h3>
                    <p>Test values may still have been extracted. Check the backend response if you expected an explanation.</p>
                  </div>
                )}

                <div className="disclaimer">
                  <span>ⓘ</span>
                  <div>
                    <strong>Important medical disclaimer</strong>
                    <p>{disclaimer}</p>
                    <p>Reference ranges vary by laboratory and individual. Do not start, stop, or change medication based on this summary. Discuss your results with a qualified healthcare professional.</p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="empty-state">
                <div className="empty-icon sparkle">✧</div>
                <h3>Your AI explanation will appear here</h3>
                <p>After a report is processed, this section can show plain-language context, practical precautions, and suggested questions for your clinician.</p>
                <small>⌑ Uses your configured local AI service</small>
              </div>
            )}
          </section>

          <footer className="footer">
            <strong>Swasthya<span>AI</span></strong>
            <p>Health information made easier to understand — not a replacement for clinical care.</p>
          </footer>
        </div>
      </main>
    </div>
  );
}
