// Router setup for navigation between pages
// Temporary state-based navigation until react-router-dom is installed

import { useState, useMemo, useEffect } from "react";

import Welcome from "./components/Welcome";
import Login from "./components/Login";
import SignUp from "./components/SignUp";
import ModePicker from "./components/ModePicker";
import PredictionGame from "./components/PredictionGame";
import OpinionGame from "./components/OpinionGame";
import Profile from "./pages/Profile";
import Analytics from "./pages/Analytics";
import PartyMode from "./pages/PartyMode";

const PLAYER_ID_STORAGE_KEY = "daily_dilemma_player_id";
const JWT_STORAGE_KEY = "daily_dilemma_jwt";

function getOrCreatePlayerId() {
  if (typeof window === "undefined") return null;
  let existing = window.localStorage.getItem(PLAYER_ID_STORAGE_KEY);
  if (existing) return existing;
  const fresh = String(Math.floor(100000 + Math.random() * 900000));
  window.localStorage.setItem(PLAYER_ID_STORAGE_KEY, fresh);
  return fresh;
}

function getStoredJWT() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(JWT_STORAGE_KEY);
}

export default function AppRouter() {
  const [authState, setAuthState] = useState("welcome"); // "welcome" | "login" | "signup" | "authenticated"
  const [jwtToken, setJwtToken] = useState(null);
  const [page, setPage] = useState("home"); // "home" | "prediction" | "opinion" | "profile" | "analytics" | "party"
  const playerId = useMemo(() => getOrCreatePlayerId(), []);

  // Check for stored JWT on mount
  useEffect(() => {
    const storedJWT = getStoredJWT();
    if (storedJWT) {
      setJwtToken(storedJWT);
      setAuthState("authenticated");
    }
  }, []);

  function handleLoginSuccess(token) {
    setJwtToken(token);
    setAuthState("authenticated");
  }

  function handleSignUpSuccess(token) {
    setJwtToken(token);
    setAuthState("authenticated");
  }

  function handleContinueAsGuest() {
    setAuthState("authenticated");
  }

  function handleLogout() {
    // Clear JWT token from localStorage
    localStorage.removeItem(JWT_STORAGE_KEY);
    // Reset state
    setJwtToken(null);
    setAuthState("welcome");
    setPage("home");
  }

  // Show welcome/login/signup screens if not authenticated
  if (authState === "welcome") {
    return (
      <Welcome
        onSelectLogin={() => setAuthState("login")}
        onSelectSignUp={() => setAuthState("signup")}
        onContinueAsGuest={handleContinueAsGuest}
      />
    );
  }

  if (authState === "login") {
    return (
      <Login
        onLoginSuccess={handleLoginSuccess}
        onContinueAsGuest={handleContinueAsGuest}
        onBack={() => setAuthState("welcome")}
      />
    );
  }

  if (authState === "signup") {
    return (
      <SignUp
        onSignUpSuccess={handleSignUpSuccess}
        onBack={() => setAuthState("welcome")}
      />
    );
  }

  const headerSubtitle =
    page === "opinion"
      ? "What would you do? See how others answered."
      : page === "prediction"
        ? "Guess what most people would do."
        : "Pick a mode to start playing.";

  // Shared frame for the *non-party* pages
  function renderShell(children) {
    return (
      <div className="page">
        <header className="header">
          <h1 className="title">Daily Dilemma</h1>
          <p className="subtitle">{headerSubtitle}</p>

          {/* simple nav */}
          <div className="top-nav-row">
            <button
              type="button"
              className={
                "top-nav-link" + (page === "home" ? " top-nav-link--active" : "")
              }
              onClick={() => setPage("home")}
            >
              Home
            </button>
            <button
              type="button"
              className={
                "top-nav-link" +
                (page === "profile" ? " top-nav-link--active" : "")
              }
              onClick={() => setPage("profile")}
            >
              Profile
            </button>
            <button
              type="button"
              className={
                "top-nav-link" +
                (page === "analytics" ? " top-nav-link--active" : "")
              }
              onClick={() => setPage("analytics")}
            >
              Analytics
            </button>
            <button
              type="button"
              className={
                "top-nav-link" +
                (page === "party" ? " top-nav-link--active" : "")
              }
              onClick={() => setPage("party")}
            >
              Party mode
            </button>
            <button
              type="button"
              className="top-nav-link top-nav-link--logout"
              onClick={handleLogout}
            >
              Log Out
            </button>
          </div>
        </header>

        <main className="main">{children}</main>
      </div>
    );
  }

  // ====== ROUTES ======

  if (page === "home") {
    return renderShell(
      <ModePicker
        onSelectMode={(selectedMode) => setPage(selectedMode)}
        playerId={playerId}
      />,
    );
  }

  if (page === "prediction") {
    return renderShell(
      <PredictionGame
        playerId={playerId}
        onBack={() => setPage("home")}
      />,
    );
  }

  if (page === "opinion") {
    return renderShell(
      <OpinionGame
        playerId={playerId}
        onBack={() => setPage("home")}
      />,
    );
  }

  if (page === "profile") {
    return renderShell(<Profile />);
  }

  if (page === "analytics") {
    return renderShell(<Analytics />);
  }

  if (page === "party") {
    // IMPORTANT: PartyMode already renders its own .page + header
    // so DO NOT wrap it in renderShell, or you'll get double headings.
    return <PartyMode onBack={() => setPage("home")} />;
  }

  return null;
}
