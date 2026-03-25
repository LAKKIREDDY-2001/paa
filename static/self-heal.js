(function () {
    'use strict';

    var CONFIG = {
        healthUrl: '/health',
        reportUrl: '/api/self-heal/report',
        intervalMs: 45000,
        retryDelayMs: 700,
        maxBannerMs: 8000
    };

    function pathStarts(prefix) {
        try {
            return (window.location.pathname || '').startsWith(prefix);
        } catch (e) {
            return false;
        }
    }

    function isDashboard() { return pathStarts('/dashboard'); }
    function isLogin() { return pathStarts('/login'); }
    function isSignup() { return pathStarts('/signup'); }

    function delay(ms) {
        return new Promise(function (resolve) { setTimeout(resolve, ms); });
    }

    function showBanner(message) {
        try {
            var id = 'self-heal-banner';
            var existing = document.getElementById(id);
            if (existing) existing.remove();
            var banner = document.createElement('div');
            banner.id = id;
            banner.style.cssText = [
                'position:fixed',
                'left:16px',
                'right:16px',
                'bottom:16px',
                'z-index:99999',
                'padding:12px 14px',
                'background:#0f172a',
                'color:#fff',
                'border-radius:10px',
                'font:500 13px/1.4 system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
                'box-shadow:0 10px 28px rgba(2,6,23,.35)'
            ].join(';');
            banner.textContent = message;
            document.body.appendChild(banner);
            setTimeout(function () {
                var el = document.getElementById(id);
                if (el) el.remove();
            }, CONFIG.maxBannerMs);
        } catch (e) {
            // no-op
        }
    }

    function cleanCorruptedClientState() {
        var keys = ['settings', 'currency', 'trackersBackup'];
        keys.forEach(function (k) {
            try {
                var v = localStorage.getItem(k);
                if (v && (v.trim().startsWith('{') || v.trim().startsWith('['))) {
                    JSON.parse(v);
                }
            } catch (e) {
                localStorage.removeItem(k);
                report('state_cleanup', 'Removed corrupted localStorage value', { key: k });
            }
        });
    }

    function report(type, message, meta) {
        try {
            var payload = {
                type: String(type || 'unknown'),
                message: String(message || ''),
                page: window.location.pathname,
                meta: meta || {}
            };
            fetch(CONFIG.reportUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                keepalive: true,
                body: JSON.stringify(payload)
            }).catch(function () {});
        } catch (e) {
            // no-op
        }
    }

    async function healthPing() {
        try {
            var res = await fetch(CONFIG.healthUrl, { cache: 'no-store', credentials: 'include' });
            return res.ok;
        } catch (e) {
            return false;
        }
    }

    async function autoRecoverForms() {
        try {
            if (!(isLogin() || isSignup())) return;
            var btnId = isLogin() ? 'login-btn' : 'signup-btn';
            var btn = document.getElementById(btnId);
            if (btn && btn.disabled) {
                // Recover stuck auth button state after transient JS/runtime issues.
                btn.disabled = false;
                report('ui_recovery', 'Recovered disabled auth button', { button: btnId });
            }
        } catch (e) {
            report('ui_recovery_error', e.message || String(e), { section: 'forms' });
        }
    }

    async function autoRecoverDashboard() {
        try {
            if (!isDashboard()) return;
            if (typeof window.loadTrackers === 'function') {
                window.loadTrackers();
            }
            if (typeof window.updateStats === 'function') {
                window.updateStats();
            }
        } catch (e) {
            report('ui_recovery_error', e.message || String(e), { section: 'dashboard' });
        }
    }

    // Retry failed API calls once for known auth/dashboard APIs.
    var nativeFetch = (typeof window.fetch === 'function') ? window.fetch.bind(window) : null;
    if (nativeFetch) {
        window.fetch = async function (input, init) {
            var url = '';
            try {
                url = typeof input === 'string' ? input : (input && input.url ? input.url : '');
            } catch (e) {
                url = '';
            }

            var shouldRetry = /\/api\/(trackers|user|forgot-password|reset-password|check-email|direct-reset-password)|\/get-price/.test(url);
            try {
                return await nativeFetch(input, init);
            } catch (err) {
                if (!shouldRetry) throw err;
                await delay(CONFIG.retryDelayMs);
                try {
                    return await nativeFetch(input, init);
                } catch (err2) {
                    report('fetch_failure', err2.message || String(err2), { url: url || 'unknown' });
                    throw err2;
                }
            }
        };
    }

    function runtimeErrorHandler(message, stack, source) {
        var msg = String(message || 'runtime error');
        report('runtime_error', msg, {
            source: source || 'window',
            stack: String(stack || '').slice(0, 500)
        });

        var lower = msg.toLowerCase();
        if (lower.includes('unexpected token') || lower.includes('json')) {
            cleanCorruptedClientState();
        }

        if (lower.includes('failed to fetch') || lower.includes('networkerror')) {
            showBanner('Temporary network issue detected. Auto-retry is active.');
        }
    }

    window.addEventListener('error', function (event) {
        runtimeErrorHandler(event.message, event.error && event.error.stack, 'error_event');
    });

    window.addEventListener('unhandledrejection', function (event) {
        var reason = event.reason;
        var message = (reason && reason.message) ? reason.message : String(reason || 'Unhandled promise rejection');
        var stack = reason && reason.stack ? reason.stack : '';
        runtimeErrorHandler(message, stack, 'unhandledrejection');
    });

    async function runSelfHealCycle() {
        var healthy = await healthPing();
        if (!healthy) {
            showBanner('Server connection unstable. Self-heal checks are retrying...');
            report('health_unstable', 'Health check failed', {});
        }
        await autoRecoverForms();
        await autoRecoverDashboard();
    }

    // Initial pass after app scripts settle.
    setTimeout(function () {
        cleanCorruptedClientState();
        runSelfHealCycle().catch(function () {});
    }, 3000);

    setInterval(function () {
        runSelfHealCycle().catch(function () {});
    }, CONFIG.intervalMs);
})();
