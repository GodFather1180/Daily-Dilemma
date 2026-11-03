// Welcome page - entry point with Log In / Sign Up options

export default function Welcome({ onSelectLogin, onSelectSignUp, onContinueAsGuest }) {
  return (
    <div className="welcome-container">
      <div className="welcome-box">
        <h1 className="welcome-title">Welcome to Daily Dilemma</h1>
        
        <div className="welcome-actions">
          <button
            type="button"
            onClick={onSelectLogin}
            className="welcome-button welcome-button--primary"
          >
            Log In
          </button>
          
          <button
            type="button"
            onClick={onSelectSignUp}
            className="welcome-button welcome-button--secondary"
          >
            Sign Up
          </button>
          
          <button
            type="button"
            onClick={onContinueAsGuest}
            className="welcome-guest-link"
          >
            Continue as guest
          </button>
        </div>
      </div>

      {/* Seesaw animation outside the box */}
      <div className="welcome-seesaw-container">
        <div className="seesaw">
          <div className="seesaw-base"></div>
          <div className="seesaw-board">
            <div className="seesaw-ball"></div>
          </div>
        </div>
      </div>
    </div>
  );
}

