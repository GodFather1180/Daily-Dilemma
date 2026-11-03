// Opinion game component
// Uses: getNextOpinionScenario, submitOpinion
// Optionally calls: getOpinionResult later for distribution

import { useState, useEffect } from "react";
import {
  getNextOpinionScenario,
  submitOpinion,
  getOpinionResult,
} from "../api";

export default function OpinionGame({ playerId, onBack }) {
  const [scenario, setScenario] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedOptionId, setSelectedOptionId] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [finished, setFinished] = useState(false);
  const [finishedMessage, setFinishedMessage] = useState("");

  const [summaryStats, setSummaryStats] = useState({
    answered: 0,
    matched: 0,
  });

  // Load first scenario when playerId is ready
  useEffect(() => {
    if (!playerId) return;
    fetchNextScenario();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerId]);

  async function fetchNextScenario() {
    if (!playerId) return;

    setLoading(true);
    setError(null);
    setResult(null);
    setSelectedOptionId(null);

    try {
      const data = await getNextOpinionScenario(playerId);
      setScenario(data);
      setFinished(false);
      setFinishedMessage("");
    } catch (err) {
      console.error(err);
      if (err.status === 404) {
        // No more personal dilemmas -> show final summary
        setScenario(null);
        setFinished(true);
        setFinishedMessage(
          err.message ||
            "You've answered all the personal dilemmas for now.",
        );
        setError(null);
      } else {
        setError(
          "Could not load a new dilemma. Check that the backend is running and reachable.",
        );
        setScenario(null);
      }
    } finally {
      setLoading(false);
    }
  }

  function handleBack() {
    setSummaryStats({ answered: 0, matched: 0 });
    setFinished(false);
    setFinishedMessage("");
    if (onBack) onBack();
  }

  // NEW: allow user to end session early
  function endSessionEarly() {
    setScenario(null);
    setFinished(true);
    setFinishedMessage("Session ended.");
    // note: we do NOT reset summaryStats so they see
    // how many dilemmas they answered this session
  }

  async function handleSubmit() {
    if (!scenario || !selectedOptionId || !playerId) return;
    setSubmitting(true);
    setError(null);

    try {
      // Submit opinion
      await submitOpinion(scenario.id, selectedOptionId, playerId);

      // Get result distribution
      const resultJson = await getOpinionResult(scenario.id);
      const options = resultJson.options || [];

      const distribution = options.reduce((acc, o) => {
        // backend gives share 0–1, convert to percentage
        const pct = typeof o.share === "number" ? o.share * 100 : 0;
        acc[o.key] = pct;
        return acc;
      }, {});

      let majorityKey = null;
      let bestShare = -Infinity;
      for (const o of options) {
        if (typeof o.share === "number" && o.share > bestShare) {
          bestShare = o.share;
          majorityKey = o.key;
        }
      }

      const selectedOpt = (scenario.options || []).find(
        (o) => o.id === selectedOptionId,
      );

      setSummaryStats((prev) => {
        const answered = prev.answered + 1;
        let matched = prev.matched;
        if (selectedOpt && majorityKey && selectedOpt.key === majorityKey) {
          matched += 1;
        }
        return { answered, matched };
      });

      setResult({
        distribution,
        totalVotes: resultJson.total_votes ?? 0,
      });
    } catch (err) {
      console.error(err);
      setError(
        "Could not submit your answer. Check the game endpoints for errors.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit = !!scenario && !!selectedOptionId && !submitting;

  // Finished state: show summary + message
  if (finished && !scenario) {
    const hasStats = summaryStats.answered > 0;

    return (
      <div className="card card--centered">
        {hasStats && (
          <p className="finished-text">
            You matched the majority on{" "}
            <strong>{summaryStats.matched}</strong> /{" "}
            <strong>{summaryStats.answered}</strong> dilemmas.
          </p>
        )}

        <p className="finished-text">
          {finishedMessage ||
            "You've answered all the personal dilemmas for now."}
        </p>

        <button className="secondary-button" onClick={handleBack}>
          Back to mode selection
        </button>
      </div>
    );
  }

  // Normal card only when we actually have a scenario
  if (!finished && scenario) {
    return (
      <div className="card">
        <div className="card-header-row">
          <p className="scenario-label">Personal dilemma</p>
          <div style={{ display: "flex", gap: "12px" }}>
            <button className="link-button" onClick={endSessionEarly}>
              End session
            </button>
            <button className="link-button" onClick={handleBack}>
              Switch mode
            </button>
          </div>
        </div>

        {loading && <p className="status-text">Loading dilemma…</p>}

        {!loading && (
          <>
            <p className="scenario-text">{scenario.text}</p>

            <div className="options">
              {(scenario.options || []).map((opt) => {
                // If we have a result, pull percentage for this option key
                let pct = null;
                if (result && result.distribution) {
                  const raw = result.distribution[opt.key];
                  if (typeof raw === "number") {
                    pct = raw; // 0–100
                  }
                }

                const pctLabel =
                  pct != null ? `${Number(pct).toFixed(0)}%` : null;

                return (
                  <button
                    key={opt.id}
                    className={
                      "option-button" +
                      (selectedOptionId === opt.id
                        ? " option-button--selected"
                        : "") +
                      (result ? " option-button--locked" : "")
                    }
                    onClick={() => {
                      if (result) return; // lock after reveal
                      setSelectedOptionId(opt.id);
                    }}
                    disabled={!!result}
                  >
                    {/* background fill based on percentage (only after result) */}
                    {pct != null && (
                      <span
                        className="option-fill"
                        aria-hidden="true"
                        style={{ width: `${pct}%` }}
                      />
                    )}

                    <span className="option-main">
                      <span className="option-key">{opt.key}.</span>
                      <span>{opt.text}</span>
                    </span>

                    {/* Percentage on right side of button after result */}
                    {pctLabel && (
                      <span className="option-pct">{pctLabel}</span>
                    )}
                  </button>
                );
              })}
            </div>

            {!result && (
              <button
                className="primary-button"
                onClick={handleSubmit}
                disabled={!canSubmit}
              >
                {submitting ? "Checking..." : "Lock in your answer"}
              </button>
            )}

            {result && (
              <div className="result-panel">
                <p className="result-title">Here's how everyone answered.</p>

                {typeof result.totalVotes === "number" && (
                  <p className="result-meta">
                    {result.totalVotes} total answers
                  </p>
                )}

                {result.distribution && (
                  <div className="distribution">
                    {Object.entries(result.distribution).map(([key, pct]) => (
                      <div key={key} className="distribution-row">
                        <span className="distribution-label">{key}</span>
                        <div className="distribution-bar-wrap">
                          <div
                            className="distribution-bar"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="distribution-pct">
                          {Number(pct).toFixed(0)}%
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                <button
                  className="secondary-button"
                  onClick={fetchNextScenario}
                >
                  Next dilemma
                </button>
              </div>
            )}
          </>
        )}

        {error && <p className="error-text">{error}</p>}

        {playerId && (
          <p className="player-id-helper">
            Your player id for this browser: <code>{playerId}</code>
          </p>
        )}
      </div>
    );
  }

  // If not finished and no scenario at all (and not currently loading)
  if (!finished && !scenario && !loading && error) {
    return <p className="error-text">{error}</p>;
  }

  return null;
}
