/**
 * CSRF Protection Utility
 *
 * Provides CSRF token management for the CyberX Event Management System.
 * Automatically extracts CSRF tokens from cookies and includes them in API requests.
 *
 * Usage:
 *   // Option 1: Use csrfFetch() wrapper (recommended)
 *   const response = await csrfFetch('/api/endpoint', {
 *       method: 'POST',
 *       body: JSON.stringify(data)
 *   });
 *
 *   // Option 2: Manually add token to headers
 *   const token = getCSRFToken();
 *   fetch('/api/endpoint', {
 *       method: 'POST',
 *       headers: { 'X-CSRF-Token': token },
 *       body: JSON.stringify(data)
 *   });
 */

/**
 * Extract CSRF token from cookies.
 *
 * @returns {string|null} The CSRF token or null if not found
 */
function getCSRFToken() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrf_token') {
            return value;
        }
    }
    return null;
}

/**
 * Fetch wrapper that automatically includes CSRF token for state-changing requests.
 *
 * This function wraps the native fetch() API and automatically adds the CSRF token
 * to POST, PUT, DELETE, and PATCH requests. GET and HEAD requests are not modified.
 *
 * @param {string} url - The URL to fetch
 * @param {Object} options - Fetch options (method, headers, body, etc.)
 * @returns {Promise<Response>} The fetch response
 *
 * @example
 * // Simple POST request
 * const response = await csrfFetch('/api/admin/events', {
 *     method: 'POST',
 *     body: JSON.stringify({ name: 'New Event' })
 * });
 *
 * @example
 * // PUT request with custom headers
 * const response = await csrfFetch('/api/admin/participants/123', {
 *     method: 'PUT',
 *     headers: { 'Content-Type': 'application/json' },
 *     body: JSON.stringify({ first_name: 'Updated Name' })
 * });
 *
 * @example
 * // FormData upload (CSRF token added, Content-Type auto-detected)
 * const formData = new FormData();
 * formData.append('file', fileInput.files[0]);
 * const response = await csrfFetch('/api/vpn/import', {
 *     method: 'POST',
 *     body: formData
 * });
 */
async function csrfFetch(url, options = {}) {
    // Default options
    const defaultOptions = {
        credentials: 'include',  // Always include cookies
        headers: {}
    };

    // Merge with provided options
    const mergedOptions = { ...defaultOptions, ...options };

    // Ensure headers object exists
    if (!mergedOptions.headers) {
        mergedOptions.headers = {};
    }

    // Add CSRF token for state-changing requests
    const method = (mergedOptions.method || 'GET').toUpperCase();
    const requiresCSRF = ['POST', 'PUT', 'DELETE', 'PATCH'].includes(method);

    let csrfToken = null;
    if (requiresCSRF) {
        csrfToken = getCSRFToken();
        if (csrfToken) {
            mergedOptions.headers['X-CSRF-Token'] = csrfToken;
        } else {
            console.warn('CSRF token not found in cookies. Request may be rejected.');
        }
    }

    // If body is a plain object (not FormData, Blob, etc), stringify it
    // and set Content-Type to application/json
    if (mergedOptions.body && typeof mergedOptions.body === 'object'
        && !(mergedOptions.body instanceof FormData)
        && !(mergedOptions.body instanceof Blob)
        && !(mergedOptions.body instanceof URLSearchParams)) {
        mergedOptions.body = JSON.stringify(mergedOptions.body);
        if (!mergedOptions.headers['Content-Type']) {
            mergedOptions.headers['Content-Type'] = 'application/json';
        }
    }

    // Make the request
    const response = await fetch(url, mergedOptions);

    // Session expired — redirect to login
    if (response.status === 401) {
        window.location.href = '/login';
        return response;
    }

    // Auto-refresh on CSRF 403: the 403 response includes a fresh cookie, so retry once
    if (requiresCSRF && response.status === 403) {
        try {
            const errorBody = await response.clone().json();
            if (errorBody.detail && errorBody.detail.toLowerCase().includes('csrf')) {
                console.warn('CSRF token expired, refreshing...');

                // The 403 response carries a fresh csrf_token cookie
                const freshToken = getCSRFToken();
                if (freshToken && freshToken !== csrfToken) {
                    mergedOptions.headers['X-CSRF-Token'] = freshToken;
                    return fetch(url, mergedOptions);
                }
            }
        } catch (_) {
            // JSON parse failed — not a CSRF error, return original response
        }
    }

    return response;
}

/**
 * Initialize CSRF protection on page load.
 * Verifies that a CSRF token is available.
 */
function initCSRFProtection() {
    const token = getCSRFToken();
    if (!token) {
        console.warn('CSRF token not found. Make a GET request to obtain one.');
    } else {
        console.log('CSRF protection initialized. Token available.');
    }
}

// Auto-initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCSRFProtection);
} else {
    initCSRFProtection();
}

// Export for use in modules (if needed)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { getCSRFToken, csrfFetch };
}
