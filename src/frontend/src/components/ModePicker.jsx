// Mode picker component - landing screen to choose game mode

export default function ModePicker({ onSelectMode, playerId }) {
  return (
    <div className="mode-card">
      <p className="mode-intro">Choose how you want to play today.</p>
      <div className="mode-grid">
        <button
          className="mode-option mode-option--primary"
          onClick={() => onSelectMode("prediction")}
        >
          <h2>Daily Dilemma</h2>
          <p>
            You see a scenario and try to guess what the majority of players
            chose.
          </p>
          <span className="mode-pill">Guess the crowd</span>
        </button>
        <button
          className="mode-option"
          onClick={() => onSelectMode("opinion")}
        >
          <h2>Personal Mode</h2>
          <p>
            Answer with what <strong>you</strong> would do and see how your
            choice compares to everyone else.
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
  );
}

