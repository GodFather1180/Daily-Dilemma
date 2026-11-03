// Profile page - shows user alignment stats and prediction history
// Expected data shape:
// {
//   alignmentPercentage: number, // 0-100
//   history: [
//     {
//       scenarioId: number,
//       scenarioText: string, // short summary
//       predictedOption: string, // option key
//       status: "waiting" | "revealed-correct" | "revealed-incorrect"
//     }
//   ]
// }

import { useEffect, useMemo, useState } from "react";
import { getProfile } from "../api";

const PLAYER_ID_STORAGE_KEY = "daily_dilemma_player_id";

function getOrCreatePlayerId() {
  if (typeof window === "undefined") return null;
  let existing = window.localStorage.getItem(PLAYER_ID_STORAGE_KEY);
  if (existing) return existing;
  const fresh = String(Math.floor(100000 + Math.random() * 900000));
  window.localStorage.setItem(PLAYER_ID_STORAGE_KEY, fresh);
  return fresh;
}

export default function Profile() {
  const playerId = useMemo(() => getOrCreatePlayerId(), []);
  const [loading, setLoading] = useState(false);
  const [alignment, setAlignment] = useState(null);
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");

  async function loadProfile() {
    if (!playerId) return;
    setLoading(true);
    setError("");
    try {
      const data = await getProfile(playerId);
      setAlignment(
        typeof data.alignment_percent === "number" ? data.alignment_percent : null
      );
      setMessage(typeof data.message === "string" ? data.message : "");
      setHistory(Array.isArray(data.history) ? data.history : []);
    } catch {
      setError("Could not load profile. Check backend availability.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerId]);

  return (
    <div className="page">
      <header className="header">
        <h1 className="title">Your Profile</h1>
      </header>

      <main className="main">
        <div className="card">
          <div className="card-header-row">
            <h2>Alignment Stats</h2>
            <button className="link-button" onClick={loadProfile} disabled={loading}>
              Refresh
            </button>
          </div>

          {loading && <p className="status-text">Loading…</p>}
          {!loading && error && <p className="error-text">{error}</p>}

          {!loading && !error && (
            <>
              {alignment != null ? (
                <p className="stat-line">
                  How often your predictions matched the revealed majority:{" "}
                  <strong>{Number(alignment).toFixed(1)}%</strong>
                </p>
              ) : (
                <p className="status-text">
                  {message || "No revealed results yet."}
                </p>
              )}

              {playerId && (
                <p className="player-id-helper">
                  Your player id for this browser: <code>{playerId}</code>
                </p>
              )}
            </>
          )}
        </div>

        <div className="card">
          <h2>Prediction History</h2>

          {loading && <p className="status-text">Loading…</p>}
          {!loading && !error && history.length === 0 && (
            <p className="status-text">No recent predictions yet.</p>
          )}

          {!loading && !error && history.length > 0 && (
            <ul className="history-list no-bullets">
              {history.map((h) => {
                const label =
                  h.status === "revealed-correct"
                    ? "revealed correct"
                    : h.status === "revealed-incorrect"
                    ? "revealed incorrect"
                    : "waiting";
                return (
                  <li
                    key={`${h.scenario_id}-${h.predicted_option_id}`}
                    className="history-item"
                  >
                    <div className="history-row">
                      <div className="history-main">
                        <div className="history-text">{h.scenario_text}</div>
                        <div className="history-meta-line">
                          You picked <strong>{h.predicted_option_key}</strong> — {label}
                        </div>
                      </div>
                      <span
                        className={
                          "status-pill " +
                          (h.status === "revealed-correct"
                            ? "status-pill--good"
                            : h.status === "revealed-incorrect"
                            ? "status-pill--bad"
                            : "status-pill--waiting")
                        }
                      >
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </main>
    </div>
  );
}