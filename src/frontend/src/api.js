// API helpers for /game/... endpoints

const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "") ||
  "http://localhost:8000";

const JWT_STORAGE_KEY = "daily_dilemma_jwt";

/**
 * Get JWT token from localStorage
 */
function getJWT() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(JWT_STORAGE_KEY);
}

/**
 * Create headers with JWT token if available
 */
function getHeaders(includeJWT = true) {
  const headers = {
    "Content-Type": "application/json",
  };
  if (includeJWT) {
    const jwt = getJWT();
    if (jwt) {
      headers["Authorization"] = `Bearer ${jwt}`;
    }
  }
  return headers;
}

/**
 * Get next scenario for prediction mode
 * @param {string} playerId - Player identifier
 * @returns {Promise<Object>} Scenario object with id, text, options, etc.
 * @throws {Error} If request fails or no more scenarios (404)
 */
export async function getNextScenario(playerId) {
  const headers = getHeaders();
  const res = await fetch(
    `${API_BASE}/game/next?player_id=${encodeURIComponent(playerId)}`,
    {
      headers,
      credentials: "include",
    },
  );

  if (res.status === 404) {
    const error = new Error("No more scenarios");
    error.status = 404;
    try {
      const data = await res.json();
      if (
        data &&
        typeof data.detail === "object" &&
        typeof data.detail.message === "string"
      ) {
        error.message = data.detail.message;
      }
    } catch {
      // ignore JSON parse errors
    }
    throw error;
  }

  if (!res.ok) {
    throw new Error(
      `Failed to load scenario: ${res.status} ${res.statusText}`,
    );
  }

  return await res.json();
}

/**
 * Submit a prediction for a scenario
 * @param {number} scenarioId - Scenario ID
 * @param {number} optionId - Selected option ID
 * @param {string} playerId - Player identifier
 * @returns {Promise<Object>} Response from backend
 */
export async function submitPrediction(scenarioId, optionId, playerId) {
  const res = await fetch(
    `${API_BASE}/game/scenarios/${scenarioId}/predict?player_id=${encodeURIComponent(
      playerId,
    )}`,
    {
      method: "POST",
      headers: getHeaders(),
      credentials: "include",
      body: JSON.stringify({
        option_id: optionId,
      }),
    },
  );

  if (!res.ok) {
    let detail = "";
    try {
      const errJson = await res.json();
      detail = JSON.stringify(errJson);
    } catch {
      /* ignore */
    }
    throw new Error(
      `Failed to submit prediction: ${res.status} ${res.statusText} ${detail}`,
    );
  }

  return await res.json();
}

/**
 * Get prediction result for a scenario
 * @param {number} scenarioId - Scenario ID
 * @returns {Promise<Object>} Result with options, distribution, majority, etc.
 */
export async function getPredictionResult(scenarioId) {
  const res = await fetch(`${API_BASE}/game/scenarios/${scenarioId}/result`, {
    headers: getHeaders(),
    credentials: "include",
  });

  if (!res.ok) {
    let detail = "";
    try {
      const errJson = await res.json();
      detail = JSON.stringify(errJson);
    } catch {
      /* ignore */
    }
    throw new Error(
      `Failed to load result: ${res.status} ${res.statusText} ${detail}`,
    );
  }

  return await res.json();
}

/**
 * Get next scenario for opinion mode
 * @param {string} playerId - Player identifier
 * @returns {Promise<Object>} Scenario object with id, text, options, etc.
 * @throws {Error} If request fails or no more scenarios (404)
 */
export async function getNextOpinionScenario(playerId) {
  const res = await fetch(
    `${API_BASE}/game/opinion/next?player_id=${encodeURIComponent(playerId)}`,
    {
      headers: getHeaders(),
      credentials: "include",
    },
  );

  if (res.status === 404) {
    const error = new Error("No more scenarios");
    error.status = 404;
    try {
      const data = await res.json();
      if (
        data &&
        typeof data.detail === "object" &&
        typeof data.detail.message === "string"
      ) {
        error.message = data.detail.message;
      }
    } catch {
      // ignore JSON parse errors
    }
    throw error;
  }

  if (!res.ok) {
    throw new Error(
      `Failed to load scenario: ${res.status} ${res.statusText}`,
    );
  }

  return await res.json();
}

/**
 * Submit an opinion for a scenario
 * @param {number} scenarioId - Scenario ID
 * @param {number} optionId - Selected option ID
 * @param {string} playerId - Player identifier
 * @returns {Promise<Object>} Response from backend
 */
export async function submitOpinion(scenarioId, optionId, playerId) {
  const res = await fetch(
    `${API_BASE}/game/scenarios/${scenarioId}/opinion?player_id=${encodeURIComponent(
      playerId,
    )}`,
    {
      method: "POST",
      headers: getHeaders(),
      credentials: "include",
      body: JSON.stringify({
        option_id: optionId,
      }),
    },
  );

  if (!res.ok) {
    let detail = "";
    try {
      const errJson = await res.json();
      detail = JSON.stringify(errJson);
    } catch {
      /* ignore */
    }
    throw new Error(
      `Failed to submit opinion: ${res.status} ${res.statusText} ${detail}`,
    );
  }

  return await res.json();
}

/**
 * Get opinion result/distribution for a scenario
 * @param {number} scenarioId - Scenario ID
 * @returns {Promise<Object>} Result with option distribution
 */
export async function getOpinionResult(scenarioId) {
  const res = await fetch(
    `${API_BASE}/game/scenarios/${scenarioId}/opinion-result`,
    {
      headers: getHeaders(),
      credentials: "include",
    },
  );

  if (!res.ok) {
    let detail = "";
    try {
      const errJson = await res.json();
      detail = JSON.stringify(errJson);
    } catch {
      /* ignore */
    }
    throw new Error(
      `Failed to load result: ${res.status} ${res.statusText} ${detail}`,
    );
  }

  return await res.json();
}

export async function getProfile(playerId, { limit = 10, offset = 0 } = {}) {
  const res = await fetch(
    `${API_BASE}/game/me?player_id=${encodeURIComponent(playerId)}&limit=${limit}&offset=${offset}`,
    {
      headers: getHeaders(),
      credentials: "include",
    },
  );
  if (!res.ok) {
    throw new Error(`Failed to load profile: ${res.status} ${res.statusText}`);
  }
  return await res.json();
}

/**
 * Get analytics dashboard data
 * @returns {Promise<Object>} Analytics data with scenarios and median session length
 */
export async function getAnalytics() {
  const res = await fetch(`${API_BASE}/game/analytics`, {
    headers: getHeaders(),
    credentials: "include",
  });

  if (!res.ok) {
    let detail = "";
    try {
      const errJson = await res.json();
      detail = errJson.detail || "Failed to load analytics";
    } catch {
      detail = "Failed to load analytics";
    }
    throw new Error(detail);
  }

  return await res.json();
}

/**
 * Login with username and password
 * @param {string} name - Username
 * @param {string} password - Password
 * @param {string} expiry - Expiry datetime string in "YYYY-MM-DD HH:MM:SS" format
 * @returns {Promise<Object>} Response with JWT token
 */
export async function login(name, password, expiry) {
  const res = await fetch(`${API_BASE}/v2/authentications/`, {
    method: "POST",
    headers: getHeaders(false), // Don't include JWT for login
    credentials: "include",
    body: JSON.stringify({
      name,
      password,
      expiry,
    }),
  });

  if (!res.ok) {
    let detail = "";
    try {
      const errJson = await res.json();
      detail = errJson.detail || "Invalid credentials";
    } catch {
      detail = "Invalid credentials";
    }
    throw new Error(detail);
  }

  return await res.json();
}

/**
 * Create a new user account
 * @param {string} name - Username
 * @param {string} email - Email address
 * @param {string} password - Password
 * @returns {Promise<Object>} Created user object
 */
export async function signup(name, email, password) {
  const res = await fetch(`${API_BASE}/users/`, {
    method: "POST",
    headers: getHeaders(false), // Don't include JWT for signup
    credentials: "include",
    body: JSON.stringify({
      name,
      email,
      password,
    }),
  });

  if (!res.ok) {
    let detail = "";
    try {
      const errJson = await res.json();
      if (errJson.detail) {
        detail = errJson.detail;
      } else if (res.status === 409) {
        detail = "Item already exists";
      } else {
        detail = "Failed to create account";
      }
    } catch {
      detail = "Failed to create account";
    }
    throw new Error(detail);
  }

  return await res.json();
}
