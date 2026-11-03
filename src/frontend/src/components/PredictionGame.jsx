// Prediction game component
import { useEffect, useState } from "react";
import {
  getNextScenario,
  submitPrediction,
  getPredictionResult,
} from "../api";
import PredictionResultPanel from "./PredictionResultPanel";

export default function PredictionGame({ playerId, onBack }) {
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
    correct: 0,
  });

  // Load first scenario when we have a player id
  useEffect(() => {
    if (!playerId) return;
    fetchNextScenario();
  }, [playerId]);

  async function fetchNextScenario() {
    if (!playerId) return;

    setLoading(true);
    setError(null);
    setResult(null);
    setSelectedOptionId(null);

    try {
      const data = await getNextScenario(playerId);
      setScenario(data);
      setFinished(false);
      setFinishedMessage("");
    } catch (err) {
      console.error(err);

      // No more dilemmas for this player
      if (err.status === 404) {
        setScenario(null);
        setFinished(true);
        setFinishedMessage(
          err.message || "All dilemmas answered — that's all for now.",
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

  // End session early from the header link
  function endSessionEarly() {
    setScenario(null);
    setFinished(true);
    setFinishedMessage("Session ended.");
  }

  // Go back to mode selection
  function handleBack() {
    setSummaryStats({ answered: 0, correct: 0 });
    setFinished(false);
    setFinishedMessage("");
    if (onBack) onBack();
  }

  async function handleSubmit() {
    if (!scenario || !selectedOptionId || !playerId) return;

    setSubmitting(true);
    setError(null);

    try {
      // 1) submit the prediction
      await submitPrediction(scenario.id, selectedOptionId, playerId);

      // 2) fetch aggregated result for that scenario
      const resultJson = await getPredictionResult(scenario.id);
      const options = resultJson.options || [];

      const majority = options.find((o) => o.is_majority);
      const selected = options.find((o) => o.id === selectedOptionId);
      const correct =
        majority && selected ? majority.id === selected.id : false;

      // Update per-session stats
      setSummaryStats((prev) => ({
        answered: prev.answered + 1,
        correct: prev.correct + (correct ? 1 : 0),
      }));

      // Convert shares (0–1) to percentages 0–100
      const distribution = options.reduce((acc, o) => {
        acc[o.key] = typeof o.share === "number" ? o.share * 100 : 0;
        return acc;
      }, {});

      setResult({
        correct,
        majorityOptionKey: majority?.key ?? null,
        distribution,
        totalVotes: resultJson.total_votes ?? 0,
        usedBaseline: !!resultJson.used_baseline,
      });
    } catch (err) {
      console.error(err);
      setError("Could not submit your answer. Check the game endpoints.");
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit = !!scenario && !!selectedOptionId && !submitting;

  // ---------- FINISHED SCREEN (session summary) ----------
  if (finished && !scenario) {
    const hasStats = summaryStats.answered > 0;

    function handleStartFresh() {
      localStorage.removeItem("daily_dilemma_player_id");
      window.location.reload();
    }

    return (
      <div className="card card--centered">
        {hasStats && (
          <p className="finished-text">
            You matched the majority on{" "}
            <strong>{summaryStats.correct}</strong> /{" "}
            <strong>{summaryStats.answered}</strong> dilemmas.
          </p>
        )}

        <p className="finished-text">
          {finishedMessage || "All dilemmas answered — that's all for now."}
        </p>

        <div
          style={{
            display: "flex",
            gap: "12px",
            flexDirection: "column",
            width: "100%",
          }}
        >
          <button className="primary-button" onClick={handleStartFresh}>
            Start Fresh (New Player ID)
          </button>

          <button className="secondary-button" onClick={handleBack}>
            Back to mode selection
          </button>
        </div>
      </div>
    );
  }

  // ---------- NORMAL GAMEPLAY ----------
  if (!finished && scenario) {
    return (
      <div className="card">
        <div className="card-header-row">
          <p className="scenario-label">Today's dilemma</p>

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
                // If we have a result, show percentages
                let pct = null;
                if (result && result.distribution) {
                  const raw = result.distribution[opt.key];
                  if (typeof raw === "number") pct = raw;
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
                      if (result) return; // lock options after reveal
                      setSelectedOptionId(opt.id);
                    }}
                    disabled={!!result}
                  >
                    {pct != null && (
                      <span
                        className="option-fill"
                        style={{ width: `${pct}%` }}
                      />
                    )}

                    <span className="option-main">
                      <span className="option-key">{opt.key}.</span>
                      <span>{opt.text}</span>
                    </span>

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
                {submitting ? "Checking..." : "Lock in prediction"}
              </button>
            )}

            {result && (
              <PredictionResultPanel
                result={result}
                onNext={fetchNextScenario}
                selectedOptionId={selectedOptionId}
              />
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

  // Error state without a loaded scenario
  if (!finished && !scenario && !loading && error) {
    return <p className="error-text">{error}</p>;
  }

  // Initial / fallback state
  return null;
}
