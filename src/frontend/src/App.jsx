import { useEffect, useMemo, useState } from "react";

// You can override this in .env as VITE_API_BASE_URL
const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "") ||
  "http://localhost:8000";

const PLAYER_ID_STORAGE_KEY = "daily_dilemma_player_id";

function getOrCreatePlayerId() {
  if (typeof window === "undefined") return null;

  let existing = window.localStorage.getItem(PLAYER_ID_STORAGE_KEY);
  if (existing) return existing;

  // Generate a random 6-digit numeric id (backend expects string/int)
  const fresh = String(Math.floor(100000 + Math.random() * 900000));
  window.localStorage.setItem(PLAYER_ID_STORAGE_KEY, fresh);
  return fresh;
}

export default function App() {
  const [mode, setMode] = useState(null); // "prediction" | "opinion" | null

  const [scenario, setScenario] = useState(null);
  const [loadingScenario, setLoadingScenario] = useState(false);

  const [selectedOptionId, setSelectedOptionId] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const [finished, setFinished] = useState(false);
  const [finishedMessage, setFinishedMessage] = useState("");

  // compute playerId once in browser
  const playerId = useMemo(() => getOrCreatePlayerId(), []);

  // Load first scenario when playerId AND mode are ready
  useEffect(() => {
    if (!playerId || !mode) return;
    fetchNextScenario(mode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerId, mode]);

  function resetToModeSelect() {
    setMode(null);
    setScenario(null);
    setResult(null);
    setSelectedOptionId(null);
    setFinished(false);
    setFinishedMessage("");
    setError(null);
  }

  async function fetchNextScenario(currentMode = mode) {
    if (!playerId || !currentMode) return;

    setLoadingScenario(true);
    setError(null);
    setResult(null);
    setSelectedOptionId(null);

    try {
      const path =
        currentMode === "opinion" ? "/game/opinion/next" : "/game/next";

      const res = await fetch(
        `${API_BASE}${path}?player_id=${encodeURIComponent(playerId)}`,
        {
          credentials: "include",
        },
      );

      // No more scenarios for this player in this mode
      if (res.status === 404) {
        let msg =
          currentMode === "opinion"
            ? "You’ve answered all the personal dilemmas for now."
            : "All dilemmas answered — that's all for now.";
        try {
          const data = await res.json();
          if (
            data &&
            typeof data.detail === "object" &&
            typeof data.detail.message === "string"
          ) {
            msg = data.detail.message;
          }
        } catch {
          // ignore JSON parse errors, keep default message
        }

        setScenario(null);
        setFinished(true);
        setFinishedMessage(msg);
        setError(null);
        return;
      }

      if (!res.ok) {
        throw new Error(
          `Failed to load scenario: ${res.status} ${res.statusText}`,
        );
      }

      const data = await res.json();
      // backend returns { id, slug, text, options, answered_count, ... }
      setScenario(data);
      setFinished(false);
      setFinishedMessage("");
    } catch (err) {
      console.error(err);
      setError(
        "Could not load a new dilemma. Check that the backend is running and reachable.",
      );
      setScenario(null);
    } finally {
      setLoadingScenario(false);
    }
  }

  async function submitChoice() {
    if (!scenario || !selectedOptionId || !playerId || !mode) return;
    setSubmitting(true);
    setError(null);

    try {
      // 1) POST choice
      const predictOrOpinionPath =
        mode === "opinion"
          ? `/game/scenarios/${scenario.id}/opinion`
          : `/game/scenarios/${scenario.id}/predict`;

      const resPost = await fetch(
        `${API_BASE}${predictOrOpinionPath}?player_id=${encodeURIComponent(
          playerId,
        )}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          credentials: "include",
          body: JSON.stringify({
            option_id: selectedOptionId,
          }),
        },
      );

      if (!resPost.ok) {
        let detail = "";
        try {
          const errJson = await resPost.json();
          detail = JSON.stringify(errJson);
        } catch {
          /* ignore */
        }
        throw new Error(
          `Failed to submit choice: ${resPost.status} ${resPost.statusText} ${detail}`,
        );
      }

      // 2) GET aggregated result
      const resultPath =
        mode === "opinion"
          ? `/game/scenarios/${scenario.id}/opinion-result`
          : `/game/scenarios/${scenario.id}/result`;

      const resResult = await fetch(`${API_BASE}${resultPath}`, {
        credentials: "include",
      });

      if (!resResult.ok) {
        let detail = "";
        try {
          const errJson = await resResult.json();
          detail = JSON.stringify(errJson);
        } catch {
          /* ignore */
        }
        throw new Error(
          `Failed to load result: ${resResult.status} ${resResult.statusText} ${detail}`,
        );
      }

      const resultJson = await resResult.json();
      const options = resultJson.options || [];

      let majority = null;
      let usedBaseline = false;
      let correct = null;

      if (mode === "prediction") {
        majority = options.find((o) => o.is_majority);
        const selected = options.find((o) => o.id === selectedOptionId);
        correct =
          majority && selected ? majority.id === selected.id : false;
        usedBaseline = !!resultJson.used_baseline;
      }

      const distribution = options.reduce((acc, o) => {
        // backend gives share 0–1, convert to percentage
        const pct = typeof o.share === "number" ? o.share * 100 : 0;
        acc[o.key] = pct;
        return acc;
      }, {});

      setResult({
        mode,
        correct,
        majorityOptionKey: majority?.key ?? null,
        distribution,
        totalVotes: resultJson.total_votes ?? 0,
        usedBaseline,
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

  const headerSubtitle =
    mode === "opinion"
      ? "What would you do? See how others answered."
      : mode === "prediction"
        ? "Guess what most people would do."
        : "Pick a mode to start playing.";

  return (
    <div className="page">
      <header className="header">
        <h1 className="title">Daily Dilemma</h1>
        <p className="subtitle">{headerSubtitle}</p>
      </header>

      <main className="main">
        {/* MODE PICKER SCREEN */}
        {!mode && (
          <div className="mode-card">
            <p className="mode-intro">
              Choose how you want to play today.
            </p>

            <div className="mode-grid">
              <button
                className="mode-option mode-option--primary"
                onClick={() => setMode("prediction")}
              >
                <h2>Daily Dilemma</h2>
                <p>
                  You see a scenario and try to guess what the majority
                  of players chose.
                </p>
                <span className="mode-pill">Guess the crowd</span>
              </button>

              <button
                className="mode-option"
                onClick={() => setMode("opinion")}
              >
                <h2>Personal Mode</h2>
                <p>
                  Answer with what <strong>you</strong> would do and see
                  how your choice compares to everyone else.
                </p>
                <span className="mode-pill">What would you do?</span>
              </button>
            </div>

            {playerId && (
              <p className="player-id-helper mode-player-id">
                Your player id for this browser: <code>{playerId}</code>
              </p>
            )}
          </div>
        )}

        {/* GAME CARD / RESULT SCREEN */}
        {mode && (
          <>
            {/* Finished state: no card, just text */}
            {finished && !scenario && (
              <div className="card card--centered">
                <p className="finished-text">
                  {finishedMessage ||
                    "All dilemmas answered — that's all for now."}
                </p>
                <button
                  className="secondary-button"
                  onClick={resetToModeSelect}
                >
                  Back to mode selection
                </button>
              </div>
            )}

            {/* Normal card only when we actually have a scenario */}
            {!finished && scenario && (
              <div className="card">
                <div className="card-header-row">
                  <p className="scenario-label">
                    {mode === "opinion"
                      ? "Personal dilemma"
                      : "Today’s dilemma"}
                  </p>
                  <button
                    className="link-button"
                    onClick={resetToModeSelect}
                  >
                    Switch mode
                  </button>
                </div>

                {loadingScenario && (
                  <p className="status-text">Loading dilemma…</p>
                )}

                {!loadingScenario && (
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
                              <span className="option-key">
                                {opt.key}.
                              </span>
                              <span>{opt.text}</span>
                            </span>

                            {/* Percentage on right side of button after result */}
                            {pctLabel && (
                              <span className="option-pct">
                                {pctLabel}
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>

                    {!result && (
                      <button
                        className="primary-button"
                        onClick={submitChoice}
                        disabled={!canSubmit}
                      >
                        {submitting
                          ? "Checking..."
                          : mode === "opinion"
                            ? "Lock in your answer"
                            : "Lock in prediction"}
                      </button>
                    )}

                    {result && (
                      <div className="result-panel">
                        <p className="result-title">
                          {mode === "prediction" ? (
                            result.correct ? (
                              "Nice! You matched the majority."
                            ) : (
                              "You and the crowd disagree."
                            )
                          ) : (
                            "Here’s how everyone answered."
                          )}
                        </p>

                        {mode === "prediction" &&
                          result.majorityOptionKey && (
                            <p className="result-subtitle">
                              Majority: option{" "}
                              <strong>
                                {result.majorityOptionKey}
                              </strong>
                            </p>
                          )}

                        {typeof result.totalVotes === "number" && (
                          <p className="result-meta">
                            {result.totalVotes} total answers
                            {mode === "prediction" && result.usedBaseline
                              ? " (using baseline until enough real answers)"
                              : ""}
                          </p>
                        )}

                        {result.distribution && (
                          <div className="distribution">
                            {Object.entries(
                              result.distribution,
                            ).map(([key, pct]) => (
                              <div
                                key={key}
                                className="distribution-row"
                              >
                                <span className="distribution-label">
                                  {key}
                                </span>
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
                          onClick={() => fetchNextScenario(mode)}
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
                    Your player id for this browser:{" "}
                    <code>{playerId}</code>
                  </p>
                )}
              </div>
            )}

            {/* If not finished and no scenario at all (and not currently loading) */}
            {!finished && !scenario && !loadingScenario && error && (
              <p className="error-text">{error}</p>
            )}
          </>
        )}
      </main>
    </div>
  );
}
