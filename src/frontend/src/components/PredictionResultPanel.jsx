// Result panel for prediction mode
// Shows: correct/incorrect, majority option, distribution, total votes

export default function PredictionResultPanel({
  result,
  onNext,
  selectedOptionId,
}) {
  // Expected result shape:
  // {
  //   correct: boolean,
  //   majorityOptionKey: string,
  //   distribution: { [key: string]: number }, // percentages 0-100
  //   totalVotes: number,
  //   usedBaseline: boolean
  // }

  const distribution = result?.distribution || {};

  // Detect ties in the distribution (frontend-only)
  const tieKeys =
    distribution && Object.keys(distribution).length > 0
      ? (() => {
          const entries = Object.entries(distribution);
          if (entries.length < 2) return [];

          // Find the max percentage
          let max = -Infinity;
          for (const [, pct] of entries) {
            const n = typeof pct === "number" ? pct : Number(pct) || 0;
            if (n > max) max = n;
          }

          // Treat values within a tiny epsilon of max as tied
          const EPS = 0.0001;
          const top = entries.filter(([, pct]) => {
            const n = typeof pct === "number" ? pct : Number(pct) || 0;
            return Math.abs(n - max) < EPS;
          });

          return top.length > 1 ? top.map(([key]) => key) : [];
        })()
      : [];

  return (
    <div className="result-panel">
      <p className="result-title">
        {result.correct
          ? "Nice! You matched the majority."
          : "You and the crowd disagree."}
      </p>

      {/* Tie message */}
      {tieKeys.length > 1 && (
        <p className="result-subtitle">
          Close call – options{" "}
          <strong>{tieKeys.join(" & ")}</strong> were tied for the top spot.
        </p>
      )}

      {result.majorityOptionKey && (
        <p className="result-subtitle">
          Majority: option <strong>{result.majorityOptionKey}</strong>
        </p>
      )}

      {typeof result.totalVotes === "number" && (
        <p className="result-meta">
          {result.totalVotes} total answers
          {result.usedBaseline
            ? " (using baseline until enough real answers)"
            : ""}
        </p>
      )}

      {distribution && (
        <div className="distribution">
          {Object.entries(distribution).map(([key, pct]) => (
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

      <button className="secondary-button" onClick={onNext}>
        Next dilemma
      </button>
    </div>
  );
}
