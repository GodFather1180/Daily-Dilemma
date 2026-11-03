// Analytics page - shows global scenario stats and disagreement metrics

import { useEffect, useState } from "react";
import { getAnalytics } from "../api";

export default function Analytics() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [medianSessionLength, setMedianSessionLength] = useState(null);
  const [scenarios, setScenarios] = useState([]);

  async function loadAnalytics() {
    setLoading(true);
    setError("");
    try {
      const data = await getAnalytics();
      setMedianSessionLength(
        typeof data.medianSessionLength === "number"
          ? data.medianSessionLength
          : null
      );
      setScenarios(Array.isArray(data.scenarios) ? data.scenarios : []);
    } catch (err) {
      setError(err.message || "Could not load analytics. Check backend availability.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAnalytics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function formatPercentage(value) {
    if (value == null) return "N/A";
    return `${Number(value).toFixed(1)}%`;
  }

  return (
    <div className="page">
      <header className="header">
        <h1 className="title">Analytics</h1>
      </header>
      <main className="main">
        <div className="card">
          <div className="card-header-row">
            <h2>Global Stats</h2>
            <button
              className="link-button"
              onClick={loadAnalytics}
              disabled={loading}
            >
              Refresh
            </button>
          </div>

          {loading && <p className="status-text">Loading…</p>}
          {!loading && error && <p className="error-text">{error}</p>}

          {!loading && !error && (
            <p className="stat-line">
              Median session length (last 7 days):{" "}
              <strong>
                {medianSessionLength != null
                  ? `${Number(medianSessionLength).toFixed(1)} minutes`
                  : "Not available yet"}
              </strong>
            </p>
          )}
        </div>

        <div className="card">
          <div className="card-header-row">
            <h2>Scenario Analytics</h2>
            <p className="helper-text">
              Sorted by most disagreed-on dilemmas (highest disagreement first)
            </p>
          </div>

          {loading && <p className="status-text">Loading…</p>}
          {!loading && error && <p className="error-text">{error}</p>}
          {!loading && !error && scenarios.length === 0 && (
            <p className="status-text">No scenario data available yet.</p>
          )}

          {!loading && !error && scenarios.length > 0 && (
            <div className="analytics-scenarios-list">
              {scenarios.map((scenario) => {
                const optionKeys = Object.keys(
                  scenario.optionPercentages || {}
                ).sort();
                const hasOpinionData =
                  scenario.totalOpinions > 0 &&
                  Object.keys(scenario.opinionOptionPercentages || {}).length > 0;

                return (
                  <div key={scenario.scenarioId} className="analytics-scenario-item">
                    <div className="analytics-scenario-header">
                      <h3 className="analytics-scenario-title">
                        Scenario #{scenario.scenarioId}
                      </h3>
                      <div className="analytics-scenario-meta">
                        {scenario.disagreementScore != null && (
                          <span className="disagreement-badge">
                            Disagreement: {Number(scenario.disagreementScore).toFixed(1)}%
                          </span>
                        )}
                        {scenario.globalCorrectnessRate != null && (
                          <span className="correctness-badge">
                            Correctness: {formatPercentage(scenario.globalCorrectnessRate)}
                          </span>
                        )}
                      </div>
                    </div>

                    <p className="analytics-scenario-text">{scenario.scenarioText}</p>

                    <div className="analytics-stats-row">
                      <div className="analytics-stat">
                        <strong>{scenario.totalPredictions || 0}</strong> predictions
                      </div>
                      {hasOpinionData && (
                        <div className="analytics-stat">
                          <strong>{scenario.totalOpinions}</strong> opinions
                        </div>
                      )}
                    </div>

                    {optionKeys.length > 0 && (
                      <div className="analytics-options">
                        <h4>Prediction Distribution:</h4>
                        <div className="analytics-percentages">
                          {optionKeys.map((key) => (
                            <div key={key} className="analytics-option-row">
                              <span className="analytics-option-key">{key}.</span>
                              <div className="analytics-option-bar">
                                <div
                                  className="analytics-option-fill"
                                  style={{
                                    width: `${scenario.optionPercentages[key] || 0}%`,
                                  }}
                                ></div>
                              </div>
                              <span className="analytics-option-pct">
                                {formatPercentage(scenario.optionPercentages[key])}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {hasOpinionData && (
                      <div className="analytics-options">
                        <h4>Opinion Distribution:</h4>
                        <div className="analytics-percentages">
                          {Object.keys(scenario.opinionOptionPercentages)
                            .sort()
                            .map((key) => (
                              <div key={key} className="analytics-option-row">
                                <span className="analytics-option-key">{key}.</span>
                                <div className="analytics-option-bar">
                                  <div
                                    className="analytics-option-fill"
                                    style={{
                                      width: `${
                                        scenario.opinionOptionPercentages[key] || 0
                                      }%`,
                                    }}
                                  ></div>
                                </div>
                                <span className="analytics-option-pct">
                                  {formatPercentage(
                                    scenario.opinionOptionPercentages[key]
                                  )}
                                </span>
                              </div>
                            ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

