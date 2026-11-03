// Party Mode page - local group play on one device

import { useState } from "react";

// Same API base logic as the rest of the app
const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "") ||
  "http://localhost:8000";

export default function PartyMode({ onBack }) {
  const [step, setStep] = useState("setup"); // "setup" | "playing" | "roundResult" | "finished"
  const [partyId, setPartyId] = useState(null);
  const [playerCount, setPlayerCount] = useState(3);

  const [scenario, setScenario] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [currentPlayer, setCurrentPlayer] = useState(1);
  const [selectedOptionId, setSelectedOptionId] = useState(null);
  const [roundAnswers, setRoundAnswers] = useState([]); // index = playerNumber - 1

  const [roundResult, setRoundResult] = useState(null);
  const [finishedMessage, setFinishedMessage] = useState("");
  const [showPerPlayer, setShowPerPlayer] = useState(false);

  // -------------------------
  // Helpers
  // -------------------------

  function resetAll() {
    setStep("setup");
    setPartyId(null);
    setPlayerCount(3);
    setScenario(null);
    setCurrentPlayer(1);
    setSelectedOptionId(null);
    setRoundAnswers([]);
    setRoundResult(null);
    setFinishedMessage("");
    setShowPerPlayer(false);
    setError(null);
  }

  async function startParty() {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/game/party/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ player_count: playerCount }),
      });

      if (!res.ok) {
        let detail = "";
        try {
          const j = await res.json();
          detail = JSON.stringify(j);
        } catch {
          /* ignore */
        }
        throw new Error(
          `Failed to start party: ${res.status} ${res.statusText} ${detail}`,
        );
      }

      const data = await res.json();
      const newPartyId = data.party_id;

      setPartyId(newPartyId);
      setCurrentPlayer(1);
      setRoundAnswers(new Array(playerCount).fill(null));
      setSelectedOptionId(null);
      setRoundResult(null);
      setShowPerPlayer(false);
      setStep("playing");

      await fetchNextScenario(newPartyId);
    } catch (err) {
      console.error(err);
      setError(
        "Could not start party mode. Check that the backend is running.",
      );
      setStep("setup");
    } finally {
      setLoading(false);
    }
  }

  async function fetchNextScenario(pId = partyId) {
    if (!pId) return;
    setLoading(true);
    setError(null);
    setRoundResult(null);
    setSelectedOptionId(null);
    setCurrentPlayer(1);
    setRoundAnswers(new Array(playerCount).fill(null));
    setShowPerPlayer(false);

    try {
      const res = await fetch(
        `${API_BASE}/game/party/sessions/${encodeURIComponent(pId)}/next`,
      );

      if (res.status === 404) {
        // No more scenarios for this party
        let msg = "No more dilemmas available for this party.";
        try {
          const j = await res.json();
          if (
            j &&
            typeof j.detail === "object" &&
            typeof j.detail.message === "string"
          ) {
            msg = j.detail.message;
          }
        } catch {
          /* ignore */
        }
        setScenario(null);
        setFinishedMessage(msg);
        setStep("finished");
        return;
      }

      if (!res.ok) {
        throw new Error(
          `Failed to load next party scenario: ${res.status} ${res.statusText}`,
        );
      }

      const data = await res.json();
      setScenario(data);
      setStep("playing");
    } catch (err) {
      console.error(err);
      setError(
        "Could not load a party dilemma. Check the backend /game/party endpoints.",
      );
      setScenario(null);
    } finally {
      setLoading(false);
    }
  }

  function handleLockForCurrentPlayer() {
    if (!scenario || !selectedOptionId) return;

    // Make a fresh copy of the answers array and fill in this player's answer
    const updatedAnswers = [...roundAnswers];
    updatedAnswers[currentPlayer - 1] = selectedOptionId;

    // Push updated answers into state (for UI / player chips)
    setRoundAnswers(updatedAnswers);

    // If there are more players, move to the next one
    if (currentPlayer < playerCount) {
      setCurrentPlayer(currentPlayer + 1);
      setSelectedOptionId(null);
    } else {
      // Everyone answered -> finalize using the UPDATED answers
      finalizeRound(updatedAnswers);
    }
  }

  async function finalizeRound(effectiveAnswers) {
    if (!scenario || !partyId) return;

    const answers = effectiveAnswers ?? roundAnswers;

    setLoading(true);
    setError(null);

    try {
      // 1) Optional: send per-player answers for analytics if backend supports it
      const answersPayload = {
        answers: answers.map((optId, index) => ({
          player_number: index + 1,
          option_id: optId,
        })),
      };

      try {
        await fetch(
          `${API_BASE}/game/party/sessions/${encodeURIComponent(
            partyId,
          )}/scenarios/${scenario.id}/answers`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(answersPayload),
          },
        );
      } catch (err) {
        // This endpoint is optional; ignore failures.
        console.warn("Sending party answers failed (non-fatal):", err);
      }

      // 2) Compute group majority & POST /complete
      const countsByOptionId = {};
      for (const optId of answers) {
        if (optId == null) continue;
        countsByOptionId[optId] = (countsByOptionId[optId] || 0) + 1;
      }

      let partyMajorityOptionId = null;
      let maxCount = -1;
      for (const [optIdStr, count] of Object.entries(countsByOptionId)) {
        const optIdNum = Number(optIdStr);
        if (count > maxCount) {
          maxCount = count;
          partyMajorityOptionId = optIdNum;
        }
      }

      if (partyMajorityOptionId != null) {
        try {
          await fetch(
            `${API_BASE}/game/party/sessions/${encodeURIComponent(
              partyId,
            )}/scenarios/${scenario.id}/complete`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ option_id: partyMajorityOptionId }),
            },
          );
        } catch (err) {
          console.warn("party /complete failed (non-fatal):", err);
        }
      }

      // 3) Get global majority distribution
      const resResult = await fetch(
        `${API_BASE}/game/scenarios/${scenario.id}/result`,
      );
      if (!resResult.ok) {
        throw new Error(
          `Failed to load global result: ${resResult.status} ${resResult.statusText}`,
        );
      }

      const resultJson = await resResult.json();
      const options = resultJson.options || [];

      const majority = options.find((o) => o.is_majority);
      const globalMajorityKey = majority?.key ?? null;

      const globalDistribution = options.reduce((acc, o) => {
        const pct = typeof o.share === "number" ? o.share * 100 : 0;
        acc[o.key] = pct;
        return acc;
      }, {});

      // Map option_id -> key (A/B/C/...) for this scenario
      const keyById = {};
      (scenario.options || []).forEach((opt) => {
        keyById[opt.id] = opt.key;
      });

      // Group counts by option key for "Your group"
      const groupCounts = {};
      answers.forEach((optId) => {
        const key = keyById[optId];
        if (!key) return;
        groupCounts[key] = (groupCounts[key] || 0) + 1;
      });

      // Per-player breakdown for the toggle
      const perPlayer = answers.map((optId, index) => {
        const key = keyById[optId];
        return {
          player: index + 1,
          key: key ?? "?",
        };
      });

      setRoundResult({
        groupCounts,
        globalMajorityKey,
        globalDistribution,
        totalVotes: resultJson.total_votes ?? 0,
        usedBaseline: !!resultJson.used_baseline,
        perPlayer,
      });
      setStep("roundResult");
    } catch (err) {
      console.error(err);
      setError(
        "Round finished but we could not load results. Check the /game/scenarios/{id}/result endpoint.",
      );
    } finally {
      setLoading(false);
      setSelectedOptionId(null);
    }
  }

  // -------------------------
  // Render helpers
  // -------------------------

  function renderPlayerChips() {
    if (!playerCount) return null;
    const answers = roundAnswers || [];
    return (
      <div className="party-pill-row">
        {Array.from({ length: playerCount }, (_, i) => {
          const num = i + 1;
          const answered = answers[i] != null;
          const isActive = step === "playing" && currentPlayer === num;
          const className =
            "party-pill" +
            (isActive ? " party-pill--active" : "") +
            (answered ? " party-pill--done" : "");
          return (
            <span key={num} className={className}>
              P{num}
            </span>
          );
        })}
      </div>
    );
  }

  const showCard = step !== "setup";

  return (
    <div className="page">
      <header className="header">
        <h1 className="title">Party Mode</h1>
        <p className="subtitle">
          Local group play – take turns, then see how your group compares to
          the crowd.
        </p>
        {onBack && (
          <div style={{ marginTop: "12px" }}>
            <button
              type="button"
              className="secondary-button"
              onClick={onBack}
              style={{ fontSize: "0.9rem" }}
            >
              ← Leave Party Mode
            </button>
          </div>
        )}
      </header>

      <main className="main">
        {/* SETUP */}
        {step === "setup" && (
          <div className="card">
            <h2>Start a new party</h2>
            <p className="mode-intro">
              Choose how many people are playing on this device.
            </p>

            <div className="party-player-count-row">
              <span className="party-player-count-label">
                Number of players:
              </span>
              <div className="party-player-count-buttons">
                {Array.from({ length: 6 }, (_, i) => i + 3).map((n) => (
                  <button
                    key={n}
                    type="button"
                    className={
                      "party-count-button" +
                      (playerCount === n ? " party-count-button--active" : "")
                    }
                    onClick={() => setPlayerCount(n)}
                    disabled={loading}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>

            <button
              className="primary-button"
              onClick={startParty}
              disabled={loading}
            >
              {loading ? "Starting..." : "Start party"}
            </button>

            {error && <p className="error-text">{error}</p>}
          </div>
        )}

        {/* MAIN PARTY CARD */}
        {showCard && step !== "setup" && (
          <div className="card">
            <div className="card-header-row">
              <div>
                <p className="scenario-label">Party dilemma</p>
                {step === "playing" && scenario && (
                  <p className="party-current-player">
                    Now answering: <strong>Player {currentPlayer}</strong>
                  </p>
                )}
                {step === "roundResult" && (
                  <p className="party-current-player">
                    Round finished – here’s how your group answered.
                  </p>
                )}
                {step === "finished" && (
                  <p className="party-current-player">
                    No more dilemmas for this party.
                  </p>
                )}
              </div>

              {renderPlayerChips()}
            </div>

            {loading && <p className="status-text">Loading…</p>}

            {!loading && step === "playing" && scenario && (
              <>
                <p className="scenario-text">{scenario.text}</p>

                <div className="options">
                  {(scenario.options || []).map((opt) => (
                    <button
                      key={opt.id}
                      className={
                        "option-button" +
                        (selectedOptionId === opt.id
                          ? " option-button--selected"
                          : "")
                      }
                      onClick={() => setSelectedOptionId(opt.id)}
                    >
                      <span className="option-main">
                        <span className="option-key">{opt.key}.</span>
                        <span>{opt.text}</span>
                      </span>
                    </button>
                  ))}
                </div>

                <button
                  className="primary-button"
                  onClick={handleLockForCurrentPlayer}
                  disabled={!selectedOptionId || loading}
                >
                  {currentPlayer < playerCount
                    ? `Lock in Player ${currentPlayer}`
                    : "Finish round"}
                </button>
              </>
            )}

            {!loading && step === "roundResult" && scenario && roundResult && (
              <>
                <p className="scenario-text">{scenario.text}</p>

                <div className="party-results-grid">
                  <div className="party-results-column">
                    <h3 className="party-results-title">Your group</h3>
                    <ul className="no-bullets">
                      {(scenario.options || []).map((opt) => {
                        const count = roundResult.groupCounts[opt.key] || 0;
                        return (
                          <li key={opt.id} className="party-results-row">
                            <span className="party-results-option-label">
                              {opt.key}.
                            </span>
                            <span className="party-results-text">
                              {opt.text}
                            </span>
                            <span className="party-results-count">
                              {count}
                            </span>
                          </li>
                        );
                      })}
                    </ul>

                    {/* Toggle for per-player breakdown */}
                    <button
                      className="link-button"
                      type="button"
                      onClick={() => setShowPerPlayer((v) => !v)}
                      style={{ marginTop: "12px" }}
                    >
                      {showPerPlayer
                        ? "Hide who picked what"
                        : "Show who picked what"}
                    </button>

                    {/* Per-player breakdown list */}
                    {showPerPlayer && roundResult.perPlayer && (
                      <ul
                        className="no-bullets"
                        style={{ marginTop: "8px" }}
                      >
                        {roundResult.perPlayer.map((row) => (
                          <li
                            key={row.player}
                            className="party-per-player-row"
                          >
                            <span className="party-pill">
                              P{row.player}
                            </span>
                            <span style={{ marginLeft: "8px" }}>
                              → option <strong>{row.key}</strong>
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="party-results-column">
                    <h3 className="party-results-title">Global majority</h3>
                    {roundResult.globalMajorityKey ? (
                      <p className="party-global-summary">
                        Most common global choice:{" "}
                        <strong>{roundResult.globalMajorityKey}</strong>
                      </p>
                    ) : (
                      <p className="party-global-summary">
                        Not enough global answers yet to pick a clear
                        majority.
                      </p>
                    )}

                    {typeof roundResult.totalVotes === "number" && (
                      <p className="result-meta">
                        {roundResult.totalVotes} total answers
                        {roundResult.usedBaseline
                          ? " (using baseline until enough real answers)"
                          : ""}
                      </p>
                    )}
                  </div>
                </div>

                <div className="party-actions-row">
                  <button
                    className="primary-button"
                    onClick={() => fetchNextScenario()}
                  >
                    Next dilemma
                  </button>
                  <button
                    className="secondary-button"
                    onClick={resetAll}
                  >
                    End party
                  </button>
                </div>
              </>
            )}

            {!loading && step === "finished" && (
              <>
                <p className="finished-text">
                  {finishedMessage ||
                    "No more party dilemmas available for this session."}
                </p>
                <div className="party-actions-row">
                  <button
                    className="secondary-button"
                    onClick={resetAll}
                  >
                    Start a new party
                  </button>
                </div>
              </>
            )}

            {error && <p className="error-text">{error}</p>}
          </div>
        )}
      </main>
    </div>
  );
}
