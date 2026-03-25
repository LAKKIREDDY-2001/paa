// Dashboard JavaScript - Main app functionality with celebration
let trackers = [];
let currentFilter = 'all';
let currentTracker = null;
let celebrationTracker = null;
let isTrackerActionInProgress = false;
let appInitialized = false;
let dashboardUser = { username: 'User' };
let recentActivity = [];
let notificationItems = [];
let recentlyViewedItems = [];
let currentTrendPeriod = 30;
let dashboardServiceWorker = null;
let priceChartInstance = null;
let expandedTrackerIds = new Set();

// Safe API_BASE_URL - fallback to empty string if window.location is not available
const getApiBaseUrl = () => {
    try {
        return window.location && window.location.origin ? window.location.origin : '';
    } catch (e) {
        console.error('Error getting API base URL:', e);
        return '';
    }
};
const API_BASE_URL = getApiBaseUrl();

const nativeWindowOpen = (window && typeof window.open === 'function')
    ? window.open.bind(window)
    : null;

// Also add safe location wrapper
const navigateTo = function(url) {
    try {
        if (!url || typeof url !== 'string') {
            console.error('Invalid navigation URL:', url);
            return;
        }
        
        const trimmed = url.trim().toLowerCase();
        
        // Block invalid URLs
        if (trimmed === 'about:blank' || trimmed === 'null' || trimmed === 'undefined' || trimmed === '') {
            console.error('Blocked navigation to invalid URL:', url);
            return;
        }
        
        window.location.href = url;
    } catch (e) {
        console.error('Error navigating:', e);
    }
};

async function fetchJsonWithTimeout(url, options = {}, timeoutMs = 15000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await fetch(url, { ...options, signal: controller.signal });
        const rawText = await response.text();
        let data = {};
        try {
            data = rawText ? JSON.parse(rawText) : {};
        } catch (e) {
            data = { error: rawText || 'Unexpected server response' };
        }
        return { response, data };
    } finally {
        clearTimeout(timeoutId);
    }
}

function getApiErrorMessage(data, fallback) {
    if (!data) return fallback;
    if (data.error && data.suggestedUrl) {
        return `${data.error} Suggested URL: ${data.suggestedUrl}`;
    }
    return data.error || fallback;
}

// Celebration Configuration
const celebrationColors = [
    '#ff6b6b', '#feca57', '#48dbfb', '#ff9ff3', 
    '#54a0ff', '#5f27cd', '#00d2d3', '#ff9f0a'
];

const COMPANY_LOGOS = {
    amazon: '/static/logos/amazon.svg?v=20260228',
    flipkart: '/static/logos/flipkart.svg?v=20260228',
    myntra: '/static/logos/myntra.svg?v=20260228',
    ajio: '/static/logos/ajio.svg?v=20260228',
    meesho: '/static/logos/meesho.svg?v=20260228',
    snapdeal: '/static/logos/snapdeal.svg?v=20260228',
    tatacliq: '/static/logos/tatacliq.svg?v=20260228',
    reliance: '/static/logos/reliance.svg?v=20260228'
};

function initDashboardApp() {
    if (appInitialized) return;
    appInitialized = true;
    loadTrackers();
    setupNavigation();
    loadUserData();
    loadNotificationPreferences();
    loadNotifications();
    loadRecentlyViewed();
    loadWhatsAppStatus();
    initTilt();
    initCelebration();
    startAutoRefresh();
    addManualRefreshButton();
    initAiAssistant();
    initCommandPalette();
    registerServiceWorker();
    refreshAIInsights();
}

function handleLogout() {
    const doRedirect = () => {
        const ts = Date.now();
        window.location.assign('/logout?t=' + ts);
    };

    // Try API call first so cookies/session are cleared even in strict browsers.
    fetch('/logout', { method: 'GET', credentials: 'include', cache: 'no-store' })
        .catch(() => {})
        .finally(doRedirect);
}

function openSafeUrl(url, newTab = true) {
    // Validate input
    if (!url || typeof url !== 'string') {
        console.error('Invalid URL: not a string or empty');
        showToast('error', 'Invalid product URL');
        return;
    }

    const trimmed = url.trim();
    
    // Comprehensive validation to prevent about:blank and other invalid URLs
    const invalidPatterns = [
        'about:blank',
        'about:',
        'javascript:',
        'null',
        'undefined',
        'chrome:',
        'chrome-extension:',
        'moz-extension:',
        'edge:',
        'data:',
        'vbscript:'
    ];
    
    // Check for invalid patterns
    for (const pattern of invalidPatterns) {
        if (trimmed.toLowerCase().startsWith(pattern.toLowerCase())) {
            console.error('Invalid URL: blocked pattern:', pattern);
            showToast('error', 'Invalid product URL');
            return;
        }
    }
    
    // Additional length check
    if (trimmed.length < 5) {
        console.error('Invalid URL: too short:', trimmed);
        showToast('error', 'Invalid product URL');
        return;
    }

    // Check for valid URL patterns
    if (trimmed.startsWith('/')) {
        // Internal route - navigate normally
        window.location.href = trimmed;
        return;
    }

    // Check for valid URL protocols
    const isHttps = /^https:\/\//i.test(trimmed);
    const isHttp = /^http:\/\//i.test(trimmed);
    const isTel = /^tel:/i.test(trimmed);
    const isMailto = /^mailto:/i.test(trimmed);
    
    if (!isHttps && !isHttp && !isTel && !isMailto) {
        console.error('Invalid URL: no valid protocol:', trimmed);
        showToast('error', 'Invalid product URL');
        return;
    }

    // Only open if it's a valid complete URL
    if (newTab) {
        const validUrl = isHttps || isHttp || isTel || isMailto;
        if (validUrl && (trimmed.startsWith('http') || trimmed.startsWith('tel') || trimmed.startsWith('mailto'))) {
            try {
                const openedWindow = nativeWindowOpen ? nativeWindowOpen(trimmed, '_blank', 'noopener,noreferrer') : null;
                // Check if window was blocked by popup blocker
                if (!openedWindow || openedWindow === null || openedWindow === undefined) {
                    console.error('Popup was blocked');
                    showToast('error', 'Popup blocked. Please allow popups for this site.');
                    // Fallback to same window
                    window.location.href = trimmed;
                }
            } catch (e) {
                console.error('Error opening URL:', e);
                showToast('error', 'Could not open link');
            }
        }
    } else {
        window.location.href = trimmed;
    }
}

// ==================== CELEBRATION FUNCTIONS ====================

function initCelebration() {
    // Close modal on outside click
    const modal = document.getElementById('celebration-modal');
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeCelebration();
            }
        });
    }
}

function showCelebration(tracker, options = {}) {
    const modal = document.getElementById('celebration-modal');
    const productNameEl = document.getElementById('celeb-product-name');
    const savingsEl = document.getElementById('celeb-savings');
    const titleEl = document.querySelector('.celebration-title');
    const priceDropEl = document.querySelector('.price-drop');
    const savingsLabelEl = document.querySelector('.savings-label');
    const primaryBtn = document.querySelector('.celebration-btn.primary');
    const secondaryBtn = document.querySelector('.celebration-btn.secondary');
    const ribbonEl = document.querySelector('.trophy-ribbon span');
    const trophyIconEl = document.querySelector('.trophy-icon');
    const mode = options.mode || 'reached';
    
    // Store the tracker globally so buyNowFromCelebration can access it
    celebrationTracker = tracker;
    
    if (modal && tracker) {
        modal.classList.remove('mode-created', 'mode-reached');
        modal.classList.add(mode === 'created' ? 'mode-created' : 'mode-reached');
        productNameEl.textContent = tracker.productName || 'Product';

        if (mode === 'created') {
            if (titleEl) {
                titleEl.innerHTML = '<span class="title-word">✨</span><span class="title-word">ALERT</span><span class="title-word highlight">CREATED!</span><span class="title-word">✨</span>';
            }
            if (priceDropEl) priceDropEl.textContent = 'TRACKING STARTED';
            if (savingsLabelEl) savingsLabelEl.textContent = 'Target Price';
            if (savingsEl) savingsEl.textContent = `${tracker.currencySymbol || '$'}${Number(tracker.targetPrice || 0).toFixed(2)}`;
            if (primaryBtn) {
                primaryBtn.innerHTML = '<i class="fa fa-chart-line"></i> View Trends';
                primaryBtn.onclick = () => {
                    closeCelebration();
                    viewTrends(tracker.id);
                };
            }
            if (secondaryBtn) secondaryBtn.innerHTML = '<i class="fa fa-check"></i> Nice!';
            if (ribbonEl) ribbonEl.textContent = 'TRACKING ON';
            if (trophyIconEl) trophyIconEl.textContent = '🎯';
        } else {
            if (titleEl) {
                titleEl.innerHTML = '<span class="title-word">🎉</span><span class="title-word">TARGET</span><span class="title-word highlight">REACHED!</span><span class="title-word">🎉</span>';
            }
            if (priceDropEl) priceDropEl.textContent = '⬇️ PRICE DROP!';
            if (savingsLabelEl) savingsLabelEl.textContent = 'You Save';
            const saved = Number(tracker.currentPrice || 0) - Number(tracker.targetPrice || 0);
            if (savingsEl) savingsEl.textContent = `${tracker.currencySymbol || '$'}${Math.abs(saved).toFixed(2)}`;
            if (primaryBtn) {
                primaryBtn.innerHTML = '<i class="fa fa-shopping-cart"></i> Buy Now';
                primaryBtn.onclick = () => buyNowFromCelebration();
            }
            if (secondaryBtn) secondaryBtn.innerHTML = '<i class="fa fa-check"></i> Awesome!';
            if (ribbonEl) ribbonEl.textContent = 'YOU DID IT!';
            if (trophyIconEl) trophyIconEl.textContent = '🏆';
        }
        
        modal.classList.add('active');
        createConfetti(mode === 'created' ? 110 : 170);
        
        // Play sound effect (optional - browsers may block this)
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();
            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);
            oscillator.type = 'sine';
            if (mode === 'created') {
                oscillator.frequency.setValueAtTime(493.88, audioContext.currentTime);
                oscillator.frequency.setValueAtTime(659.25, audioContext.currentTime + 0.08);
                oscillator.frequency.setValueAtTime(739.99, audioContext.currentTime + 0.16);
            } else {
                oscillator.frequency.setValueAtTime(523.25, audioContext.currentTime);
                oscillator.frequency.setValueAtTime(659.25, audioContext.currentTime + 0.1);
                oscillator.frequency.setValueAtTime(783.99, audioContext.currentTime + 0.2);
            }
            gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3);
            oscillator.start(audioContext.currentTime);
            oscillator.stop(audioContext.currentTime + 0.3);
        } catch (e) {
            console.log('Audio playback blocked');
        }
    }
}

function closeCelebration() {
    const modal = document.getElementById('celebration-modal');
    if (modal) {
        modal.classList.remove('active');
        // Clear confetti
        const container = document.getElementById('confetti-container');
        if (container) {
            container.innerHTML = '';
        }
    }
}

function createConfetti(amount = 150) {
    const container = document.getElementById('confetti-container');
    if (!container) return;
    
    container.innerHTML = '';
    
    for (let i = 0; i < amount; i++) {
        const confetti = document.createElement('div');
        confetti.className = 'confetti';
        confetti.style.left = Math.random() * 100 + '%';
        confetti.style.backgroundColor = celebrationColors[Math.floor(Math.random() * celebrationColors.length)];
        confetti.style.animationDelay = Math.random() * 2 + 's';
        confetti.style.animationDuration = (Math.random() * 2 + 2) + 's';
        confetti.style.setProperty('--confetti-color', celebrationColors[Math.floor(Math.random() * celebrationColors.length)]);
        container.appendChild(confetti);
    }
}

function buyNowFromCelebration() {
    // Validate celebrationTracker before using
    if (!celebrationTracker) {
        showToast('error', 'No product selected');
        return;
    }
    
    const url = celebrationTracker.url;
    
    // Validate the URL in the tracker - more rigorous validation
    if (!url || typeof url !== 'string') {
        showToast('error', 'Invalid product URL');
        return;
    }
    
    const trimmedUrl = url.trim();
    
    // Check for empty or invalid URLs
    if (!trimmedUrl || trimmedUrl.length < 10) {
        showToast('error', 'Invalid product URL');
        return;
    }
    
    // Check for valid URL format (must start with http or https)
    if (!/^https?:\/\//i.test(trimmedUrl)) {
        showToast('error', 'Invalid product URL format');
        return;
    }
    
    // All validations passed - use safe URL opening
    openSafeUrl(trimmedUrl, true);
}

function checkPriceReached(tracker) {
    return tracker && tracker.currentPrice <= tracker.targetPrice;
}

function formatCurrency(symbol, value) {
    const amount = Number(value || 0);
    return `${symbol || '$'}${amount.toFixed(2)}`;
}

function formatDateLabel(iso) {
    try {
        return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch (e) {
        return '--';
    }
}

function safeProductImage(url) {
    const value = String(url || '').trim();
    return /^https?:\/\//i.test(value) ? value : '';
}

// ==================== TILT EFFECT ====================

function initTilt() {
    // Completely disable tilt on dashboard to prevent cursor flicker/shiver on clickable controls.
    // Remove any tilt-related event listeners and CSS transforms
    const tiltRoots = document.querySelectorAll('.tilt-root');
    tiltRoots.forEach((root) => {
        // Remove tilt-active class
        root.classList.remove('tilt-active');
        // Reset CSS custom properties
        root.style.removeProperty('--tilt-x');
        root.style.removeProperty('--tilt-y');
        // Remove the transform that causes the issue
        root.style.transform = 'none';
        root.style.perspective = 'none';
    });
    
    // Remove any existing tilt mouse event listeners
    document.querySelectorAll('.tilt-root').forEach(root => {
        const newRoot = root.cloneNode(true);
        root.parentNode.replaceChild(newRoot, root);
    });
}

// ==================== USER & NAVIGATION ====================

async function loadUserData() {
    try {
        const response = await fetch(API_BASE_URL + '/api/user');
        if (response.ok) {
            const user = await response.json();
            if (user.username) {
                document.getElementById('user-greeting').textContent = 'Welcome, ' + user.username;
                dashboardUser = user;
            }
        }
    } catch (error) {
        console.log('User not logged in');
    }
}

function setupNavigation() {
    console.log('Setting up navigation...');
    const navItems = document.querySelectorAll('.nav-item');
    console.log('Found nav items:', navItems.length);
    
    navItems.forEach(item => {
        // Remove any existing click listeners by cloning the element
        const newItem = item.cloneNode(true);
        item.parentNode.replaceChild(newItem, item);
        
        // Add new click listener using getAttribute to get the view name
        newItem.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const view = this.getAttribute('data-view');
            console.log('Nav item clicked:', view);
            switchView(view);
        });
    });
    
    console.log('Navigation setup complete');
}

function switchView(viewName) {
    console.log('switchView called with:', viewName);
    
    // Validate view name
    if (!viewName || typeof viewName !== 'string') {
        console.error('Invalid view name:', viewName);
        return;
    }
    
    // Remove active class from all nav items
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });
    
    // Add active class to the clicked nav item
    const activeNavItem = document.querySelector(`.nav-item[data-view="${viewName}"]`);
    if (activeNavItem) {
        activeNavItem.classList.add('active');
    } else {
        console.error('Nav item not found for view:', viewName);
    }
    
    // Hide all views
    document.querySelectorAll('.view').forEach(view => {
        view.classList.remove('active');
    });
    
    // Show the selected view
    const targetView = document.getElementById('view-' + viewName);
    if (targetView) {
        targetView.classList.add('active');
        console.log('View switched to:', viewName);
    } else {
        console.error('View element not found: view-' + viewName);
    }
}

// ==================== PRICE TRACKING ====================

async function handleFlow() {
    if (isTrackerActionInProgress) {
        return;
    }

    const urlInput = document.getElementById('urlInput');
    const priceStep = document.getElementById('priceStep');
    const mainBtn = document.getElementById('mainBtn');
    
    if (!urlInput) {
        showToast('error', 'URL input element not found');
        return;
    }
    
    let url = urlInput.value.trim();
    
    if (!url) {
        showToast('error', 'Please enter a URL');
        return;
    }
    
    if (!url.startsWith('http://') && !url.startsWith('https://') && !url.toLowerCase().startsWith('test://')) {
        if (url.startsWith('www.')) {
            url = 'https://' + url;
        } else if (url.includes('.')) {
            url = 'https://' + url;
        } else {
            showToast('error', 'Invalid URL format');
            return;
        }
        urlInput.value = url;
    }
    
    if (priceStep.style.display === 'none') {
        isTrackerActionInProgress = true;
        setLoadingState(true, 'Fetching price...');
        
        try {
            const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/get-price', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url })
            });

            if (response.ok) {
                priceStep.style.display = 'block';
                priceStep.innerHTML = '<p><strong>Current Price: ' + (data.currency_symbol || '$') + data.price + '</strong></p>' +
                    '<input type="number" id="targetPrice" class="product-input" style="width: 150px;" placeholder="Set target price" value="' + (data.price * 0.95).toFixed(2) + '">';
                mainBtn.disabled = false;
                mainBtn.innerHTML = 'Create Tracker';
                
                priceStep.dataset.productName = data.productName || 'Product';
                priceStep.dataset.currentPrice = data.price;
                priceStep.dataset.currency = data.currency;
                priceStep.dataset.currencySymbol = data.currency_symbol;
                priceStep.dataset.productImage = data.productImage || '';
                if (data.knownStore === false || data.site === 'generic') {
                    showToast('success', 'Global mode enabled for this site. For best results, use a direct product page with a visible price.');
                }
            } else {
                mainBtn.disabled = false;
                mainBtn.innerHTML = 'Start AI Tracking';
                showToast('error', getApiErrorMessage(data, 'Failed to fetch price'));
            }
        } catch (error) {
            mainBtn.disabled = false;
            mainBtn.innerHTML = 'Start AI Tracking';
            if (error.name === 'AbortError') {
                showToast('error', 'Request timed out. Please try again.');
            } else {
                showToast('error', 'Failed to connect to server');
            }
        } finally {
            isTrackerActionInProgress = false;
        }
    } else {
        const targetPrice = document.getElementById('targetPrice').value;
        if (!targetPrice) {
            showToast('error', 'Please set a target price');
            return;
        }
        
        const currentPrice = parseFloat(priceStep.dataset.currentPrice || 0);
        const productName = priceStep.dataset.productName || 'Product';
        const currency = priceStep.dataset.currency || 'USD';
        const currencySymbol = priceStep.dataset.currencySymbol || '$';
        const productImage = priceStep.dataset.productImage || '';
        
        await createTracker(url, targetPrice, currentPrice, productName, currency, currencySymbol, productImage);
    }
}

function setLoadingState(loading, message) {
    const mainBtn = document.getElementById('mainBtn');
    if (!mainBtn) return;
    
    if (loading) {
        mainBtn.disabled = true;
        mainBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> ' + (message || 'Loading...');
    } else {
        mainBtn.disabled = false;
        mainBtn.innerHTML = 'Start AI Tracking';
    }
}

async function createTracker(url, targetPrice, currentPrice, productName, currency, currencySymbol, productImage) {
    const urlInput = document.getElementById('urlInput');
    const mainBtn = document.getElementById('mainBtn');
    const priceStep = document.getElementById('priceStep');
    
    if (isTrackerActionInProgress) {
        return;
    }
    isTrackerActionInProgress = true;

    setLoadingState(true, 'Creating tracker...');
    
    try {
        const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/api/trackers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                currentPrice: currentPrice,
                targetPrice: parseFloat(targetPrice),
                currency: currency,
                currencySymbol: currencySymbol,
                productName: productName,
                productImage: productImage,
                alertRules: [
                    { type: 'target_price', value: parseFloat(targetPrice) }
                ]
            })
        });
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to create tracker');
        }
        
        const newTracker = data.tracker || {
            id: data.id,
            url: url,
            productName: productName,
            productImage: productImage,
            currentPrice: currentPrice,
            targetPrice: parseFloat(targetPrice),
            currency: currency,
            currencySymbol: currencySymbol,
            createdAt: new Date().toISOString(),
            alertRules: [{ type: 'target_price', value: parseFloat(targetPrice) }]
        };
        
        trackers.push(newTracker);
        logActivity('Tracker created', productName + ' target set at ' + currencySymbol + targetPrice);
        
        showToast('success', 'Tracker created successfully!');
        setTimeout(() => {
            showCelebration(newTracker, { mode: 'created' });
        }, 180);
        triggerBrowserNotification(newTracker, {
            title: 'Tracker created',
            body: (productName || 'Tracked product') + ' is now being monitored at target ' + formatCurrency(currencySymbol, parseFloat(targetPrice))
        });
        
        urlInput.value = '';
        priceStep.style.display = 'none';
        mainBtn.disabled = false;
        mainBtn.innerHTML = 'Start AI Tracking';
        
        renderTrackers();
        updateStats();
        switchView('my-trackers');
    } catch (error) {
        showToast('error', error.message);
        mainBtn.disabled = false;
        mainBtn.innerHTML = 'Create Tracker';
    } finally {
        isTrackerActionInProgress = false;
    }
}

// ==================== TRACKERS DISPLAY ====================

async function loadTrackers() {
    try {
        const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/api/trackers', {
            method: 'GET'
        });
        if (!response.ok) {
            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }
            throw new Error(data.error || 'Failed to load trackers');
        }
        trackers = Array.isArray(data) ? data : [];
    } catch (error) {
        trackers = [];
        showToast('error', 'Could not load your trackers');
    } finally {
        renderTrackers();
        updateStats();
    }
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, '&#96;');
}

function openTrackerUrlFromElement(element) {
    const card = element?.closest('.tracker-card');
    const url = card?.dataset?.url;
    openSafeUrl(url, true);
}

function toggleTrackerDetails(trackerId) {
    if (expandedTrackerIds.has(trackerId)) {
        expandedTrackerIds.delete(trackerId);
    } else {
        expandedTrackerIds.add(trackerId);
    }
    renderTrackers();
}

function attachTrackerCardClickHandlers() {
    const cards = document.querySelectorAll('.tracker-card');
    cards.forEach((card) => {
        card.addEventListener('click', (event) => {
            if (event.target.closest('.tracker-action, .tracker-checkbox, .tracker-url-link')) {
                return;
            }
            const url = card.dataset?.url;
            openSafeUrl(url, true);
        });

        card.addEventListener('keydown', (event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            if (event.target.closest('.tracker-action, .tracker-checkbox, .tracker-url-link')) {
                return;
            }
            event.preventDefault();
            const url = card.dataset?.url;
            openSafeUrl(url, true);
        });
    });
}

function renderTrackers() {
    const container = document.getElementById('trackers-list');
    if (trackers.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon"><i class="fa fa-rocket"></i></div><h3>No trackers yet!</h3><p>Create your first price alert to start saving money</p><button class="action-btn" onclick="switchView(\'new-alert\')"><span class="btn-text">Create Tracker</span><span class="btn-icon"><i class="fa fa-plus"></i></span></button></div>';
        return;
    }
    
    let filteredTrackers = trackers;
    if (currentFilter !== 'all') {
        filteredTrackers = trackers.filter(t => {
            if (currentFilter === 'active') return t.currentPrice > t.targetPrice;
            if (currentFilter === 'reached') return t.currentPrice <= t.targetPrice;
            return true;
        });
    }
    
    // Function to get company logo based on URL
    function getCompanyLogo(url) {
        if (!url) return '<i class="fa fa-shopping-bag"></i>';
        const urlLower = url.toLowerCase();
        if (urlLower.includes('amazon')) return '<img src="' + COMPANY_LOGOS.amazon + '" alt="Amazon" class="company-logo">';
        if (urlLower.includes('flipkart')) return '<img src="' + COMPANY_LOGOS.flipkart + '" alt="Flipkart" class="company-logo">';
        if (urlLower.includes('myntra')) return '<img src="' + COMPANY_LOGOS.myntra + '" alt="Myntra" class="company-logo">';
        if (urlLower.includes('ajio')) return '<img src="' + COMPANY_LOGOS.ajio + '" alt="Ajio" class="company-logo">';
        if (urlLower.includes('meesho')) return '<img src="' + COMPANY_LOGOS.meesho + '" alt="Meesho" class="company-logo">';
        if (urlLower.includes('snapdeal')) return '<img src="' + COMPANY_LOGOS.snapdeal + '" alt="Snapdeal" class="company-logo">';
        if (urlLower.includes('tatacliq') || urlLower.includes('tata')) return '<img src="' + COMPANY_LOGOS.tatacliq + '" alt="Tata CLiQ" class="company-logo">';
        if (urlLower.includes('reliance') || urlLower.includes('reliancedigital')) return '<img src="' + COMPANY_LOGOS.reliance + '" alt="Reliance Digital" class="company-logo">';
        if (urlLower.includes('ebay')) return '<i class="fa fa-shopping-bag"></i>';
        return '<i class="fa fa-shopping-bag"></i>';
    }

    function getStoreTone(url) {
        const value = String(url || '').toLowerCase();
        if (value.includes('amazon')) return 'amazon';
        if (value.includes('flipkart')) return 'flipkart';
        if (value.includes('myntra')) return 'myntra';
        if (value.includes('ajio')) return 'ajio';
        if (value.includes('meesho')) return 'meesho';
        if (value.includes('snapdeal')) return 'snapdeal';
        if (value.includes('tatacliq') || value.includes('tata')) return 'tatacliq';
        if (value.includes('reliance')) return 'reliance';
        return 'generic';
    }

    function getStoreLabel(url) {
        const tone = getStoreTone(url);
        const labels = {
            amazon: 'Amazon',
            flipkart: 'Flipkart',
            myntra: 'Myntra',
            ajio: 'Ajio',
            meesho: 'Meesho',
            snapdeal: 'Snapdeal',
            tatacliq: 'Tata CLiQ',
            reliance: 'Reliance Digital',
            generic: 'Online Store'
        };
        return labels[tone] || 'Online Store';
    }
    
    container.innerHTML = filteredTrackers.map((tracker, index) => {
        const status = tracker.currentPrice <= tracker.targetPrice ? 'reached' : 'active';
        const statusClass = status === 'reached' ? 'status-reached' : 'status-active';
        const statusText = status === 'reached' ? 'Target Reached!' : 'Active';
        const storeTone = getStoreTone(tracker.url);
        const trackerUrl = tracker.url || '';
        const safeUrlAttr = escapeAttr(trackerUrl);
        const safeName = escapeHtml(tracker.productName || 'Product');
        const safeUrlText = escapeHtml(trackerUrl);
        const imageUrl = safeProductImage(tracker.productImage);
        const imageMarkup = imageUrl
            ? '<div class="tracker-media"><img src="' + escapeAttr(imageUrl) + '" alt="' + safeName + '" loading="lazy"></div>'
            : '<div class="tracker-media">' + getCompanyLogo(tracker.url) + '</div>';
        const insight = tracker.bestTimeToBuy && typeof tracker.bestTimeToBuy === 'object' ? tracker.bestTimeToBuy : null;
        const insightLabel = escapeHtml((tracker.bestTimeToBuy && tracker.bestTimeToBuy.label) || 'Watching');
        const insightSummary = escapeHtml((insight && insight.summary) || 'We are actively tracking this product for your next price move.');
        const lastChecked = tracker.lastCheckedAt ? formatRelativeTime(tracker.lastCheckedAt) : 'Not checked yet';
        const lastCheckedFull = tracker.lastCheckedAt ? new Date(tracker.lastCheckedAt).toLocaleString() : 'Pending first check';
        const createdOn = tracker.createdAt ? new Date(tracker.createdAt).toLocaleString() : 'Recently added';
        const storeLabel = getStoreLabel(tracker.url);
        const alertRules = Array.isArray(tracker.alertRules) ? tracker.alertRules : [];
        const alertSummary = alertRules.length
            ? alertRules.map((rule) => {
                if (rule.type === 'target_price') {
                    return 'Target ' + formatCurrency(tracker.currencySymbol, rule.value);
                }
                if (rule.type === 'percentage_drop') {
                    return Math.round(Number(rule.value) || 0) + '% drop';
                }
                return escapeHtml(String(rule.type || 'Rule'));
            }).join(' • ')
            : 'Default target alert';
        const trackerError = tracker.lastCheckError ? '<div class="tracker-error"><i class="fa fa-triangle-exclamation"></i> ' + escapeHtml(tracker.lastCheckError) + '</div>' : '';
        const animationDelay = Math.min(index * 70, 560);
        const isExpanded = expandedTrackerIds.has(tracker.id);
        const detailsSection = '<div class="tracker-details ' + (isExpanded ? 'expanded' : '') + '">' +
            '<div class="tracker-details-grid">' +
                '<div class="tracker-detail-item"><span class="tracker-detail-label">Store</span><strong>' + escapeHtml(storeLabel) + '</strong></div>' +
                '<div class="tracker-detail-item"><span class="tracker-detail-label">Created</span><strong>' + escapeHtml(createdOn) + '</strong></div>' +
                '<div class="tracker-detail-item"><span class="tracker-detail-label">Last checked</span><strong>' + escapeHtml(lastCheckedFull) + '</strong></div>' +
                '<div class="tracker-detail-item"><span class="tracker-detail-label">Alert rules</span><strong>' + alertSummary + '</strong></div>' +
            '</div>' +
            '<div class="tracker-detail-note"><i class="fa fa-sparkles"></i> ' + insightSummary + '</div>' +
        '</div>';

        return '<div class="tracker-card tilt-3d tracker-card-' + status + ' tracker-store-' + storeTone + '" style="animation-delay:' + animationDelay + 'ms" data-id="' + tracker.id + '" data-url="' + safeUrlAttr + '" tabindex="0" role="button" aria-label="Open tracker link">' +
            '<div class="tracker-header"><div class="tracker-info">' + imageMarkup + '<div class="tracker-title-block"><h4 class="tracker-name">' + safeName + '</h4><div class="tracker-meta-row"><span class="meta-pill"><i class="fa fa-lightbulb"></i> ' + insightLabel + '</span><span class="meta-pill"><i class="fa fa-clock"></i> ' + escapeHtml(lastChecked) + '</span></div></div></div><div class="tracker-checkbox" onclick="event.stopPropagation(); toggleSelect(' + tracker.id + ')"><i class="fa fa-check" style="display: none;"></i></div></div>' +
            '<button type="button" class="tracker-url tracker-url-link" onclick="event.stopPropagation(); openTrackerUrlFromElement(this)">' + safeUrlText + '</button>' +
            '<div class="tracker-prices"><div class="price-info current"><span class="price-label">Current</span><span class="price-amount">' + formatCurrency(tracker.currencySymbol, tracker.currentPrice) + '</span></div><div class="price-info target"><span class="price-label">Target</span><span class="price-amount">' + formatCurrency(tracker.currencySymbol, tracker.targetPrice) + '</span></div><div class="price-status ' + statusClass + '">' + statusText + '</div></div>' +
            trackerError +
            detailsSection +
            '<div class="tracker-actions"><button type="button" class="tracker-action" onclick="event.stopPropagation(); toggleTrackerDetails(' + tracker.id + ')"><i class="fa fa-chevron-' + (isExpanded ? 'up' : 'down') + '"></i> ' + (isExpanded ? 'Less' : 'Details') + '</button><button type="button" class="tracker-action" onclick="event.stopPropagation(); viewTrends(' + tracker.id + ')"><i class="fa fa-chart-line"></i> Trends</button><button type="button" class="tracker-action" onclick="event.stopPropagation(); refreshPrice(' + tracker.id + ')"><i class="fa fa-refresh"></i> Refresh</button><button type="button" class="tracker-action delete" onclick="event.stopPropagation(); deleteTracker(' + tracker.id + ')"><i class="fa fa-trash"></i></button></div>';
    }).join('');
    
    attachTrackerCardClickHandlers();
    initTracker3D();
    updateCounts();
    refreshAIInsights();
    renderActivityFeed();
}

function updateStats() {
    document.getElementById('sidebar-active-trackers').textContent = trackers.length;
    document.getElementById('sidebar-deals').textContent = trackers.filter(t => t.currentPrice <= t.targetPrice).length;
    document.getElementById('total-trackers').textContent = trackers.length;
    document.getElementById('active-deals').textContent = trackers.filter(t => t.currentPrice <= t.targetPrice).length;
    
    if (trackers.length > 0) {
        const totalSavings = trackers
            .filter(t => t.currentPrice <= t.targetPrice)
            .reduce((sum, t) => sum + (t.targetPrice - t.currentPrice), 0);
        const avgSavings = trackers.length > 0 ? Math.round((totalSavings / trackers.length) * 10) / 10 : 0;
        document.getElementById('avg-savings').textContent = avgSavings + '%';
    }
    refreshAIInsights();
}

function updateCounts() {
    document.getElementById('count-all').textContent = trackers.length;
    document.getElementById('count-active').textContent = trackers.filter(t => t.currentPrice > t.targetPrice).length;
    document.getElementById('count-reached').textContent = trackers.filter(t => t.currentPrice <= t.targetPrice).length;
}

function setFilter(filter) {
    currentFilter = filter;
    document.querySelectorAll('.filter-tab').forEach(tab => {
        tab.classList.remove('active');
        if (tab.dataset.filter === filter) tab.classList.add('active');
    });
    renderTrackers();
}

function filterTrackers() {
    const search = document.getElementById('tracker-search').value.toLowerCase();
    const cards = document.querySelectorAll('.tracker-card');
    cards.forEach(card => {
        card.style.display = card.textContent.toLowerCase().includes(search) ? 'block' : 'none';
    });
}

function sortTrackers() {
    const sortBy = document.getElementById('sort-trackers').value;
    trackers.sort((a, b) => {
        if (sortBy === 'date') return new Date(b.createdAt) - new Date(a.createdAt);
        if (sortBy === 'name') return (a.productName || '').localeCompare(b.productName || '');
        if (sortBy === 'price') return a.currentPrice - b.currentPrice;
        return 0;
    });
    renderTrackers();
}

async function syncTrackerUpdate(tracker) {
    if (!tracker || !tracker.id) return;
    await fetchJsonWithTimeout(API_BASE_URL + '/api/trackers', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            id: tracker.id,
            currentPrice: tracker.currentPrice,
            targetPrice: tracker.targetPrice,
            productName: tracker.productName,
            currency: tracker.currency,
            currencySymbol: tracker.currencySymbol
        })
    });
}

// ==================== PRICE REFRESH ====================

async function refreshPrice(trackerId) {
    const tracker = trackers.find(t => t.id === trackerId);
    if (!tracker) return;
    
    const card = document.querySelector('.tracker-card[data-id="' + trackerId + '"]');
    const refreshBtn = card?.querySelector('.tracker-action[onclick*="refreshPrice"]');
    
    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i>';
    }
    
    try {
        const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/get-price', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: tracker.url })
        });
        
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.innerHTML = '<i class="fa fa-refresh"></i> Refresh';
        }
        
        if (response.ok) {
            const oldPrice = tracker.currentPrice;
            tracker.currentPrice = data.price;
            tracker.productName = data.productName || tracker.productName;
            tracker.currency = data.currency || tracker.currency;
            tracker.currencySymbol = data.currency_symbol || tracker.currencySymbol;
            tracker.productImage = data.productImage || tracker.productImage;
            
            // Check if target just reached
            if (checkPriceReached(tracker) && oldPrice > tracker.targetPrice) {
                celebrationTracker = tracker;
                setTimeout(() => {
                    showCelebration(tracker, { mode: 'reached' });
                }, 500);
                triggerBrowserNotification(tracker);
            }
            await syncTrackerUpdate(tracker);
            logActivity('Price refreshed', (tracker.productName || 'Product') + ' now at ' + (data.currency_symbol || '$') + data.price);
            showToast('success', 'Price updated: ' + (data.currency_symbol || '$') + data.price);
            renderTrackers();
            updateStats();
            if (currentTracker && currentTracker.id === tracker.id) {
                currentTracker = tracker;
                generateChart(tracker);
            }
            loadNotifications();
        } else {
            showToast('error', getApiErrorMessage(data, 'Failed to refresh price'));
        }
    } catch (error) {
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.innerHTML = '<i class="fa fa-refresh"></i> Refresh';
        }
        showToast('error', 'Failed to connect to server');
    }
}

async function deleteTracker(trackerId) {
    if (!confirm('Are you sure you want to delete this tracker?')) return;
    try {
        const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/api/trackers', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: trackerId })
        });
        if (!response.ok) {
            throw new Error(data.error || 'Failed to delete tracker');
        }
        trackers = trackers.filter(t => t.id !== trackerId);
        logActivity('Tracker deleted', 'Removed tracker #' + trackerId);
        renderTrackers();
        updateStats();
        showToast('success', 'Tracker deleted');
    } catch (error) {
        showToast('error', error.message || 'Failed to delete tracker');
    }
}

function toggleSelect(trackerId) {
    const checkbox = document.querySelector('.tracker-card[data-id="' + trackerId + '"] .tracker-checkbox');
    checkbox.classList.toggle('checked');
    const icon = checkbox.querySelector('i');
    icon.style.display = checkbox.classList.contains('checked') ? 'block' : 'none';
}

// ==================== PRICE TRENDS ====================

async function viewTrends(trackerId) {
    const tracker = trackers.find(t => t.id === trackerId);
    if (!tracker) return;
    currentTracker = tracker;
    switchView('price-trends');

    const trendImage = document.getElementById('trend-product-image');
    const trendIcon = document.getElementById('trend-product-icon');
    document.querySelector('.product-details h3').textContent = tracker.productName || 'Product';
    document.querySelector('.product-details p').textContent = tracker.url;
    document.getElementById('current-price').textContent = formatCurrency(tracker.currencySymbol, tracker.currentPrice);
    const imageUrl = safeProductImage(tracker.productImage);
    if (trendImage && trendIcon) {
        if (imageUrl) {
            trendImage.src = imageUrl;
            trendImage.style.display = 'block';
            trendIcon.style.display = 'none';
        } else {
            trendImage.style.display = 'none';
            trendIcon.style.display = 'block';
        }
    }
    await generateChart(tracker);
}

async function generateChart(tracker) {
    const chartContainer = document.querySelector('.chart-main');
    if (!chartContainer) return;
    chartContainer.innerHTML = '<div class="chart-shell"><div class="skeleton-line" style="height:220px;"></div><div class="skeleton-line"></div></div>';
    let history = [];
    let insight = { label: 'Watch closely', confidence: 65, summary: 'Tracking is active.' };
    try {
        const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/api/trackers/' + tracker.id + '/history?days=' + currentTrendPeriod, { method: 'GET' });
        if (response.ok) {
            history = Array.isArray(data.history) ? data.history : [];
            insight = data.insight || insight;
        }
    } catch (error) {
        history = [];
    }

    let dataPoints = history
        .map((point) => ({
            price: Number(point.price),
            recordedAt: point.recordedAt || tracker.createdAt || new Date().toISOString()
        }))
        .filter((point) => Number.isFinite(point.price));

    if (!dataPoints.length) {
        const fallbackTimestamp = tracker.createdAt || new Date().toISOString();
        dataPoints = [
            { price: Number(tracker.currentPrice || 0), recordedAt: fallbackTimestamp }
        ];
    }

    if (dataPoints.length === 1) {
        dataPoints = [
            {
                price: dataPoints[0].price,
                recordedAt: tracker.createdAt || new Date(Date.now() - 86400000).toISOString()
            },
            {
                price: dataPoints[0].price,
                recordedAt: dataPoints[0].recordedAt || new Date().toISOString()
            }
        ];
    }

    const prices = dataPoints.map((point) => Number(point.price || 0));
    const labels = dataPoints.map((point) => formatDateLabel(point.recordedAt));
    const maxPrice = Math.max(...prices, 1);
    const minPrice = Math.min(...prices, 0);

    const renderSvgFallback = () => {
        const width = 560;
        const height = 180;
        const points = prices.map((price, index) => {
            const x = dataPoints.length === 1 ? width / 2 : (index / (dataPoints.length - 1)) * width;
            const y = height - (((price - minPrice) / Math.max(maxPrice - minPrice || 1, 1)) * (height - 24)) - 12;
            return `${x},${y}`;
        }).join(' ');

        chartContainer.innerHTML = '<div class="chart-shell"><svg class="chart-svg" viewBox="0 0 560 180" preserveAspectRatio="none"><polyline fill="none" stroke="#16a7c6" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="' + points + '"></polyline>' +
            prices.map((price, index) => {
                const x = dataPoints.length === 1 ? width / 2 : (index / (dataPoints.length - 1)) * width;
                const y = height - (((price - minPrice) / Math.max(maxPrice - minPrice || 1, 1)) * (height - 24)) - 12;
                return '<circle cx="' + x + '" cy="' + y + '" r="4" fill="#ff9f0a"></circle>';
            }).join('') +
            '</svg><div class="chart-axis-labels">' + labels.map((label) => '<span>' + escapeHtml(label) + '</span>').join('') + '</div></div>';
    };

    if (window.Chart) {
        try {
            chartContainer.innerHTML = '<div class="chart-shell"><canvas id="price-history-canvas"></canvas></div>';
            const canvas = document.getElementById('price-history-canvas');
            if (!canvas) {
                renderSvgFallback();
            } else {
                const ctx = canvas.getContext('2d');
                const gradient = ctx.createLinearGradient(0, 0, 0, 240);
                gradient.addColorStop(0, 'rgba(22, 167, 198, 0.30)');
                gradient.addColorStop(0.65, 'rgba(22, 167, 198, 0.10)');
                gradient.addColorStop(1, 'rgba(22, 167, 198, 0.02)');

                if (priceChartInstance) {
                    priceChartInstance.destroy();
                }

                priceChartInstance = new window.Chart(ctx, {
                    type: 'line',
                    data: {
                        labels,
                        datasets: [{
                            label: 'Price',
                            data: prices,
                            borderColor: '#16a7c6',
                            backgroundColor: gradient,
                            fill: true,
                            tension: 0.35,
                            borderWidth: 3,
                            pointRadius: 3,
                            pointHoverRadius: 6,
                            pointBackgroundColor: '#ff9f0a',
                            pointBorderColor: '#ffffff',
                            pointBorderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: {
                            mode: 'index',
                            intersect: false
                        },
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                backgroundColor: 'rgba(15, 23, 42, 0.92)',
                                padding: 12,
                                displayColors: false,
                                callbacks: {
                                    label: (context) => formatCurrency(tracker.currencySymbol, context.raw)
                                }
                            },
                            zoom: window.ChartZoom ? {
                                pan: { enabled: true, mode: 'x' },
                                zoom: {
                                    wheel: { enabled: true },
                                    pinch: { enabled: true },
                                    mode: 'x'
                                }
                            } : undefined
                        },
                        scales: {
                            x: {
                                grid: { display: false },
                                ticks: { color: '#667085' }
                            },
                            y: {
                                grid: { color: 'rgba(15, 23, 42, 0.06)' },
                                ticks: {
                                    color: '#667085',
                                    callback: (value) => formatCurrency(tracker.currencySymbol, value)
                                }
                            }
                        }
                    }
                });
            }
        } catch (error) {
            console.error('Chart.js render failed, using SVG fallback', error);
            renderSvgFallback();
        }
    } else {
        renderSvgFallback();
    }

    document.getElementById('original-price').textContent = formatCurrency(tracker.currencySymbol, prices[0] || tracker.currentPrice);
    document.getElementById('current-price').textContent = formatCurrency(tracker.currencySymbol, tracker.currentPrice);
    const savings = Number((prices[0] || tracker.currentPrice) - tracker.currentPrice);
    document.getElementById('savings-amount').textContent = formatCurrency(tracker.currencySymbol, Math.max(savings, 0));
    document.getElementById('trend-lowest').textContent = formatCurrency(tracker.currencySymbol, Math.min(...prices));
    document.getElementById('trend-highest').textContent = formatCurrency(tracker.currencySymbol, Math.max(...prices));
    document.getElementById('trend-since').textContent = new Date(tracker.createdAt).toLocaleDateString();
    document.getElementById('prediction-text').textContent = insight.summary || 'Tracking is active.';
    document.getElementById('confidence').textContent = (insight.confidence || 65) + '%';
    
    // Only show buy now button if tracker has valid URL
    const buyNowBtn = document.getElementById('buy-now-btn');
    if (buyNowBtn) {
        // More rigorous URL validation
        const hasValidUrl = tracker.url && 
                           typeof tracker.url === 'string' && 
                           tracker.url.trim().length >= 10 &&
                           /^https?:\/\//i.test(tracker.url.trim());
        buyNowBtn.style.display = (tracker.currentPrice <= tracker.targetPrice && hasValidUrl) ? 'flex' : 'none';
        if (hasValidUrl) {
            buyNowBtn.onclick = () => openSafeUrl(tracker.url.trim(), true);
        }
    }
}

function setTimePeriod(period) {
    document.querySelectorAll('.time-btn').forEach(btn => {
        btn.classList.remove('active');
        const text = btn.textContent.toLowerCase();
        const expected = period === '7d' ? '7' : period === '30d' ? '30' : '90';
        if (text.includes(expected)) btn.classList.add('active');
    });
    currentTrendPeriod = period === '7d' ? 7 : period === '30d' ? 30 : 90;
    if (currentTracker) generateChart(currentTracker);
}

// ==================== TOAST NOTIFICATIONS ====================

function showToast(type, message) {
    if (typeof type === 'string' && typeof message === 'undefined') {
        message = type;
        type = 'success';
    }
    
    const existingToast = document.querySelector('.toast-notification');
    if (existingToast) {
        existingToast.remove();
    }
    
    const toast = document.createElement('div');
    toast.className = 'toast-notification';
    toast.innerHTML = `
        <div class="toast-icon ${type}">
            <i class="fa fa-${type === 'success' ? 'check' : 'times'}"></i>
        </div>
        <div class="toast-content">
            <strong>${type === 'success' ? 'Success!' : 'Error!'}</strong>
            <span>${message}</span>
        </div>
    `;
    
    // Add styles if not exists
    if (!document.getElementById('toast-styles')) {
        const styles = document.createElement('style');
        styles.id = 'toast-styles';
        styles.textContent = `
            .toast-notification {
                position: fixed;
                top: 24px;
                right: 24px;
                background: #1d1d1f;
                color: white;
                padding: 16px 24px;
                border-radius: 14px;
                display: flex;
                align-items: center;
                gap: 16px;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
                transform: translateX(120%);
                transition: transform 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                z-index: 1000;
            }
            .toast-notification.active { transform: translateX(0); }
            .toast-icon {
                width: 44px;
                height: 44px;
                border-radius: 12px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 20px;
            }
            .toast-icon.success { background: linear-gradient(135deg, #11998e, #38ef7d); }
            .toast-icon.error { background: linear-gradient(135deg, #cb2d3e, #ef473a); }
            .toast-content { display: flex; flex-direction: column; }
            .toast-content strong { margin-bottom: 2px; }
            .toast-content span { font-size: 0.9rem; opacity: 0.9; }
        `;
        document.head.appendChild(styles);
    }
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('active');
    }, 10);
    
    setTimeout(() => {
        toast.classList.remove('active');
        setTimeout(() => {
            toast.remove();
        }, 400);
    }, 4000);
}

// ==================== SETTINGS ====================

function saveSettings() {
    localStorage.setItem('settings', JSON.stringify({
        pushNotifications: document.getElementById('push-notifications').checked,
        desktopNotifications: document.getElementById('desktop-notifications')?.checked,
        emailAlerts: document.getElementById('email-alerts').checked,
        phoneAlerts: document.getElementById('phone-alerts')?.checked,
        darkMode: document.getElementById('dark-mode').checked,
        compactView: document.getElementById('compact-view').checked,
        refreshInterval: document.getElementById('refresh-interval').value,
        autoDelete: document.getElementById('auto-delete').value,
        dropPercentage: document.getElementById('drop-percentage').value
    }));
    saveNotificationPreferences();
    showToast('success', 'Settings saved');
}

function saveCurrencyPreference() {
    localStorage.setItem('currency', document.getElementById('currency-select').value);
    showToast('success', 'Currency preference saved');
}

function toggleTheme() {
    document.body.classList.toggle('dark-mode');
    saveSettings();
}

function loadSettings() {
    const settings = JSON.parse(localStorage.getItem('settings') || '{}');
    if (settings.pushNotifications !== undefined) document.getElementById('push-notifications').checked = settings.pushNotifications;
    if (document.getElementById('desktop-notifications')) {
        if (settings.desktopNotifications !== undefined) {
            document.getElementById('desktop-notifications').checked = settings.desktopNotifications;
        } else {
            document.getElementById('desktop-notifications').checked = ('Notification' in window) && Notification.permission === 'granted';
        }
    }
    if (settings.emailAlerts !== undefined) document.getElementById('email-alerts').checked = settings.emailAlerts;
    if (settings.phoneAlerts !== undefined && document.getElementById('phone-alerts')) document.getElementById('phone-alerts').checked = settings.phoneAlerts;
    if (settings.darkMode !== undefined) document.getElementById('dark-mode').checked = settings.darkMode;
    if (settings.compactView !== undefined) document.getElementById('compact-view').checked = settings.compactView;
    if (settings.refreshInterval !== undefined) {
        document.getElementById('refresh-interval').value = settings.refreshInterval;
    } else {
        document.getElementById('refresh-interval').value = '900';
    }
    if (settings.autoDelete !== undefined) document.getElementById('auto-delete').value = settings.autoDelete;
    if (settings.dropPercentage !== undefined) document.getElementById('drop-percentage').value = settings.dropPercentage;
    const currency = localStorage.getItem('currency');
    if (currency) document.getElementById('currency-select').value = currency;
}

async function loadNotificationPreferences() {
    try {
        const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/api/notification-preferences', { method: 'GET' });
        if (!response.ok) return;
        if (document.getElementById('push-notifications')) document.getElementById('push-notifications').checked = !!data.pushEnabled;
        if (document.getElementById('email-alerts')) document.getElementById('email-alerts').checked = !!data.emailEnabled;
        if (document.getElementById('phone-alerts')) document.getElementById('phone-alerts').checked = !!data.phoneEnabled;
        const drop = document.getElementById('drop-percentage');
        if (drop && data.alertDropPercentage) {
            drop.value = String(Math.round(data.alertDropPercentage));
        }
    } catch (error) {
        console.error('Failed to load notification preferences', error);
    }
}

async function saveNotificationPreferences() {
    try {
        await fetchJsonWithTimeout(API_BASE_URL + '/api/notification-preferences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pushEnabled: document.getElementById('push-notifications')?.checked,
                emailEnabled: document.getElementById('email-alerts')?.checked,
                phoneEnabled: document.getElementById('phone-alerts')?.checked,
                inAppEnabled: true,
                alertDropPercentage: Number(document.getElementById('drop-percentage')?.value || 10)
            })
        });
    } catch (error) {
        console.error('Failed to save notification preferences', error);
    }
}

async function loadNotifications() {
    const feed = document.getElementById('notification-feed');
    if (!feed) return;
    feed.innerHTML = '<div class="activity-item"><div class="skeleton-line"></div></div>';
    try {
        const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/api/notifications', { method: 'GET' });
        if (!response.ok) throw new Error('Failed to load notifications');
        notificationItems = Array.isArray(data) ? data : [];
    } catch (error) {
        notificationItems = [];
    }
    renderNotifications();
}

async function loadWhatsAppStatus() {
    const titleEl = document.getElementById('whatsapp-status-title');
    const textEl = document.getElementById('whatsapp-status-text');
    const actionBtn = document.getElementById('whatsapp-status-action');
    if (!titleEl || !textEl || !actionBtn) return;

    titleEl.textContent = 'Checking WhatsApp connection...';
    textEl.textContent = 'We are loading your channel status.';
    actionBtn.textContent = 'Refresh';
    actionBtn.disabled = true;

    try {
        const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/api/connect-whatsapp', { method: 'GET' });
        if (!response.ok) {
            throw new Error('Failed to load WhatsApp status');
        }

        const isConnected = !!data.connected;
        const phoneEnabled = !!data.phoneEnabled;
        if (isConnected) {
            titleEl.textContent = 'WhatsApp connected';
            textEl.textContent = (data.phone || 'Phone saved') + (phoneEnabled ? ' is ready to receive price alerts.' : ' is saved, but phone alerts are currently off.');
            actionBtn.textContent = 'Update';
            actionBtn.disabled = false;
            actionBtn.onclick = () => connectWhatsApp();
        } else {
            titleEl.textContent = 'WhatsApp not connected';
            textEl.textContent = 'Connect your WhatsApp number to receive instant price alerts.';
            actionBtn.textContent = 'Connect';
            actionBtn.disabled = false;
            actionBtn.onclick = () => connectWhatsApp();
        }
    } catch (error) {
        titleEl.textContent = 'WhatsApp status unavailable';
        textEl.textContent = 'We could not load your WhatsApp status right now.';
        actionBtn.textContent = 'Retry';
        actionBtn.disabled = false;
        actionBtn.onclick = () => loadWhatsAppStatus();
    }
}

function renderNotifications() {
    const feed = document.getElementById('notification-feed');
    if (!feed) return;
    if (!notificationItems.length) {
        feed.innerHTML = '<div class="activity-item">No notifications yet.</div>';
        return;
    }
    const channelLabels = {
        whatsapp: 'WhatsApp',
        in_app: 'In-App',
        system: 'System',
        email: 'Email',
        push: 'Push'
    };
    feed.innerHTML = notificationItems.slice(0, 8).map((item) => (
        '<div class="notification-card ' + (!item.isRead ? 'unread' : '') + '" onclick="markNotificationRead(' + item.id + ')">' +
            '<div><strong>' + escapeHtml(item.title) + '</strong><span>' + escapeHtml(item.message) + '</span><div class="notification-meta"><span class="channel-badge channel-' + escapeAttr(item.channel || 'system') + '">' + escapeHtml(channelLabels[item.channel] || 'Channel') + '</span></div></div>' +
            '<div class="activity-time">' + formatRelativeTime(item.createdAt) + '</div>' +
        '</div>'
    )).join('');
}

async function markNotificationRead(notificationId) {
    try {
        await fetchJsonWithTimeout(API_BASE_URL + '/api/notifications/' + notificationId + '/read', { method: 'POST' });
        notificationItems = notificationItems.map((item) => item.id === notificationId ? { ...item, isRead: true } : item);
        renderNotifications();
    } catch (error) {
        console.error('Failed to mark notification read', error);
    }
}

async function loadRecentlyViewed() {
    const list = document.getElementById('recently-viewed-list');
    if (!list) return;
    list.innerHTML = '<div class="activity-item"><div class="skeleton-line"></div></div>';
    try {
        const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/api/recently-viewed', { method: 'GET' });
        if (!response.ok) throw new Error('Failed to load recently viewed');
        recentlyViewedItems = Array.isArray(data) ? data : [];
    } catch (error) {
        recentlyViewedItems = [];
    }
    renderRecentlyViewed();
}

function renderRecentlyViewed() {
    const list = document.getElementById('recently-viewed-list');
    if (!list) return;
    if (!recentlyViewedItems.length) {
        list.innerHTML = '<div class="activity-item">Your recently viewed products will appear here.</div>';
        return;
    }
    list.innerHTML = recentlyViewedItems.map((item) => {
        const imageUrl = safeProductImage(item.productImage);
        return '<div class="recent-card" onclick="openSafeUrl(\'' + escapeAttr(item.url) + '\', true)">' +
            '<div class="recent-card-image">' + (imageUrl ? '<img src="' + escapeAttr(imageUrl) + '" alt="' + escapeAttr(item.productName) + '" loading="lazy">' : '<i class="fa fa-box"></i>') + '</div>' +
            '<div class="recent-card-info"><strong>' + escapeHtml(item.productName || 'Product') + '</strong><span>' + formatCurrency(item.currencySymbol, item.currentPrice) + '</span><span>' + escapeHtml(formatRelativeTime(item.viewedAt)) + '</span></div>' +
        '</div>';
    }).join('');
}

async function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    try {
        dashboardServiceWorker = await navigator.serviceWorker.register('/service-worker.js');
    } catch (error) {
        console.error('Service worker registration failed', error);
    }
}

async function togglePushNotifications() {
    const checkbox = document.getElementById('push-notifications');
    if (!checkbox) return;
    if (!checkbox.checked) {
        await saveNotificationPreferences();
        showToast('success', 'Push notifications disabled');
        return;
    }

    if (!('Notification' in window)) {
        checkbox.checked = false;
        showToast('error', 'This browser does not support notifications');
        return;
    }

    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
        checkbox.checked = false;
        showToast('error', 'Notification permission was not granted');
        await saveNotificationPreferences();
        return;
    }

    await subscribeForPush();
    await saveNotificationPreferences();
    showToast('success', 'Push notifications enabled');
}

async function subscribeForPush() {
    if (!dashboardServiceWorker) {
        await registerServiceWorker();
    }
    if (!dashboardServiceWorker || !dashboardServiceWorker.pushManager) return;
    try {
        const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/api/push-config', { method: 'GET' });
        const publicKey = response.ok ? (data.publicKey || '') : '';
        let subscription = await dashboardServiceWorker.pushManager.getSubscription();
        if (!subscription && publicKey) {
            subscription = await dashboardServiceWorker.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(publicKey)
            });
        }
        if (!subscription) return;
        await fetchJsonWithTimeout(API_BASE_URL + '/api/push-subscriptions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subscription: subscription.toJSON() })
        });
    } catch (error) {
        console.error('Push subscription failed', error);
    }
}

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
}

// ==================== DATA IMPORT/EXPORT ====================

function exportData() {
    const data = JSON.stringify(trackers, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'price-tracker-backup.json';
    a.click();
    URL.revokeObjectURL(url);
    showToast('success', 'Data exported');
}

function importData(input) {
    const file = input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const imported = JSON.parse(e.target.result);
            if (Array.isArray(imported)) {
                Promise.all(imported.map((item) => fetchJsonWithTimeout(API_BASE_URL + '/api/trackers', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        url: item.url,
                        currentPrice: item.currentPrice,
                        targetPrice: item.targetPrice,
                        currency: item.currency || 'USD',
                        currencySymbol: item.currencySymbol || '$',
                        productName: item.productName || 'Product'
                    })
                }))).then(() => {
                    loadTrackers();
                    showToast('success', 'Data imported successfully');
                }).catch(() => {
                    showToast('error', 'Import failed');
                });
            }
        } catch (error) {
            showToast('error', 'Invalid file format');
        }
    };
    reader.readAsText(file);
}

async function clearAllData() {
    if (!confirm('Are you sure you want to delete all trackers? This cannot be undone.')) return;
    await Promise.all(trackers.map((tracker) => fetchJsonWithTimeout(API_BASE_URL + '/api/trackers', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: tracker.id })
    })));
    trackers = [];
    renderTrackers();
    updateStats();
    showToast('success', 'All data cleared');
}

function exportTrackers() { exportData(); }

async function deleteSelected() {
    const selected = document.querySelectorAll('.tracker-checkbox.checked');
    if (selected.length === 0) {
        showToast('error', 'No trackers selected');
        return;
    }
    if (!confirm('Delete ' + selected.length + ' tracker(s)?')) return;
    const idsToDelete = [];
    selected.forEach(checkbox => {
        const card = checkbox.closest('.tracker-card');
        const id = parseInt(card.dataset.id);
        idsToDelete.push(id);
        trackers = trackers.filter(t => t.id !== id);
    });
    await Promise.all(idsToDelete.map((id) => fetchJsonWithTimeout(API_BASE_URL + '/api/trackers', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
    })));
    renderTrackers();
    updateStats();
    document.getElementById('bulk-actions').style.display = 'none';
    showToast('success', 'Selected trackers deleted');
}

// ==================== MODALS ====================

function connectTelegram() {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'telegram-modal';
    modal.innerHTML = `
        <div class="modal">
            <div class="modal-header">
                <h3><span class="modal-title-brand"><img src="/static/logos/telegram.svg" alt="Telegram logo" class="modal-brand-logo"> Connect Telegram</span></h3>
                <button type="button" class="modal-close" onclick="closeModal('telegram-modal')">&times;</button>
            </div>
            <div class="modal-body">
                <div class="modal-icon telegram-icon">
                    <img src="/static/logos/telegram.svg" alt="Telegram logo" class="modal-channel-logo">
                </div>
                <p>Get instant price drop alerts on Telegram!</p>
                <button type="button" class="action-btn" onclick="openSafeUrl('https://t.me/AI_Price_Alert_Bot', true)">
                    <img src="/static/logos/telegram.svg" alt="" class="inline-channel-logo"> Open Telegram Bot
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    setTimeout(() => modal.classList.add('active'), 10);
}

function connectWhatsApp() {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'whatsapp-modal';
    modal.innerHTML = `
        <div class="modal">
            <div class="modal-header">
                <h3><span class="modal-title-brand"><img src="/static/logos/whatsapp.svg" alt="WhatsApp logo" class="modal-brand-logo"> Connect WhatsApp</span></h3>
                <button type="button" class="modal-close" onclick="closeModal('whatsapp-modal')">&times;</button>
            </div>
            <div class="modal-body">
                <div class="modal-icon whatsapp-icon">
                    <img src="/static/logos/whatsapp.svg" alt="WhatsApp logo" class="modal-channel-logo">
                </div>
                <p>Get price drop alerts on WhatsApp!</p>
                <input type="tel" id="whatsapp-number" class="product-input" placeholder="+1234567890" style="width: 100%; margin-bottom: 12px;">
                <button type="button" class="action-btn" onclick="saveWhatsAppNumber()">
                    <img src="/static/logos/whatsapp.svg" alt="" class="inline-channel-logo"> Connect
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    setTimeout(() => modal.classList.add('active'), 10);
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        setTimeout(() => modal.remove(), 300);
    }
}

async function saveWhatsAppNumber() {
    const phoneInput = document.getElementById('whatsapp-number');
    const connectButton = document.querySelector('#whatsapp-modal .action-btn');
    const rawPhone = (phoneInput?.value || '').trim();

    if (!rawPhone) {
        showToast('error', 'Please enter your WhatsApp number with country code');
        return;
    }

    if (connectButton) {
        connectButton.disabled = true;
        connectButton.dataset.originalText = connectButton.innerHTML;
        connectButton.textContent = 'Connecting...';
    }

    try {
        const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/api/connect-whatsapp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone: rawPhone })
        }, 20000);

        if (!response.ok) {
            throw new Error(getApiErrorMessage(data, 'Failed to connect WhatsApp'));
        }

        dashboardUser.phone = data.phone;
        if (document.getElementById('phone-alerts')) {
            document.getElementById('phone-alerts').checked = true;
        }
        localStorage.setItem('settings', JSON.stringify({
            ...(JSON.parse(localStorage.getItem('settings') || '{}')),
            phoneAlerts: true
        }));

        if (data.whatsappSent) {
            showToast('success', 'WhatsApp connected. Welcome message sent.');
        } else {
            showToast('success', data.message || 'WhatsApp connected successfully.');
        }

        closeModal('whatsapp-modal');
        loadNotifications();
        loadWhatsAppStatus();
    } catch (error) {
        showToast('error', error.message || 'Failed to connect WhatsApp');
    } finally {
        if (connectButton) {
            connectButton.disabled = false;
            if (connectButton.dataset.originalText) {
                connectButton.innerHTML = connectButton.dataset.originalText;
            }
        }
    }
}

// Initialize settings on load
loadSettings();

// ==================== AUTO-REFRESH ALERTER ====================

let autoRefreshInterval = null;
let lastRefreshTime = null;
let autoRefreshInProgress = false;

function startAutoRefresh() {
    const settings = JSON.parse(localStorage.getItem('settings') || '{}');
    const intervalSeconds = parseInt(settings.refreshInterval || '900');
    const intervalMs = intervalSeconds * 1000;
    
    // Clear any existing interval
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
    }
    
    // Start new interval
    autoRefreshInterval = setInterval(() => {
        autoRefreshAllPrices();
    }, intervalMs);
    
    // Update UI to show auto-refresh is active
    updateAutoRefreshUI(intervalSeconds);
    console.log(`Auto-refresh started: every ${intervalSeconds} seconds`);
}

function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
    console.log('Auto-refresh stopped');
}

async function autoRefreshAllPrices() {
    if (trackers.length === 0 || autoRefreshInProgress) return;
    autoRefreshInProgress = true;
    
    console.log('Auto-refreshing all prices...');
    lastRefreshTime = new Date();
    
    let updatedCount = 0;
    try {
        for (const tracker of trackers) {
            try {
                const { response, data } = await fetchJsonWithTimeout(API_BASE_URL + '/get-price', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: tracker.url })
                });
                
                if (response.ok) {
                    const oldPrice = tracker.currentPrice;
                    tracker.currentPrice = data.price;
                    tracker.productName = data.productName || tracker.productName;
                    tracker.currency = data.currency || tracker.currency;
                    tracker.currencySymbol = data.currency_symbol || tracker.currencySymbol;
                    tracker.productImage = data.productImage || tracker.productImage;
                    await syncTrackerUpdate(tracker);
                    
                    // Check if target just reached
                    if (checkPriceReached(tracker) && oldPrice > tracker.targetPrice) {
                        celebrationTracker = tracker;
                        showCelebration(tracker, { mode: 'reached' });
                        triggerBrowserNotification(tracker);
                    }
                    updatedCount++;
                }
            } catch (error) {
                console.error(`Failed to refresh price for ${tracker.url}:`, error);
            }
        }

        // Update UI
        renderTrackers();
        updateStats();
        if (currentTracker) {
            const freshCurrentTracker = trackers.find((item) => item.id === currentTracker.id);
            if (freshCurrentTracker) {
                currentTracker = freshCurrentTracker;
                generateChart(freshCurrentTracker);
            }
        }
        loadNotifications();
        
        // Show notification
        if (updatedCount > 0) {
            logActivity('Auto-refresh complete', 'Updated ' + updatedCount + ' tracker(s)');
            showToast('success', `Auto-refreshed ${updatedCount} tracker(s)`);
        }
    } finally {
        autoRefreshInProgress = false;
    }
}

function updateAutoRefreshUI(intervalSeconds) {
    // Add auto-refresh indicator to the sidebar
    const sidebarStats = document.querySelector('.sidebar-stats');
    if (sidebarStats) {
        let refreshIndicator = document.getElementById('auto-refresh-indicator');
        if (!refreshIndicator) {
            refreshIndicator = document.createElement('div');
            refreshIndicator.id = 'auto-refresh-indicator';
            refreshIndicator.className = 'stat-item';
            refreshIndicator.innerHTML = `
                <span class="stat-value" id="refresh-timer"><i class="fa fa-sync fa-spin"></i></span>
                <span class="stat-label">Auto-refresh</span>
            `;
            sidebarStats.appendChild(refreshIndicator);
        }
    }
    
    // Update refresh timer display
    const refreshTimer = document.getElementById('refresh-timer');
    if (refreshTimer) {
        let secondsRemaining = intervalSeconds;
        refreshTimer.innerHTML = `<i class="fa fa-sync fa-spin"></i> ${formatTime(secondsRemaining)}`;
        
        // Update timer every second
        if (window.refreshTimerInterval) {
            clearInterval(window.refreshTimerInterval);
        }
        window.refreshTimerInterval = setInterval(() => {
            secondsRemaining--;
            if (secondsRemaining <= 0) {
                secondsRemaining = intervalSeconds;
            }
            const timerEl = document.getElementById('refresh-timer');
            if (timerEl) {
                timerEl.innerHTML = `<i class="fa fa-sync fa-spin"></i> ${formatTime(secondsRemaining)}`;
            }
        }, 1000);
    }
}

function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// Add manual refresh button to the UI
function addManualRefreshButton() {
    const mainBtn = document.getElementById('mainBtn');
    if (mainBtn) {
        let refreshAllBtn = document.getElementById('refresh-all-btn');
        if (!refreshAllBtn) {
            refreshAllBtn = document.createElement('button');
            refreshAllBtn.id = 'refresh-all-btn';
            refreshAllBtn.className = 'action-btn secondary';
            refreshAllBtn.style.marginLeft = '10px';
            refreshAllBtn.innerHTML = '<i class="fa fa-refresh"></i> Refresh All';
            refreshAllBtn.onclick = () => {
                refreshAllBtn.disabled = true;
                refreshAllBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Refreshing...';
                autoRefreshAllPrices().then(() => {
                    refreshAllBtn.disabled = false;
                    refreshAllBtn.innerHTML = '<i class="fa fa-refresh"></i> Refresh All';
                });
            };
            // Insert after main button
            mainBtn.parentNode.insertBefore(refreshAllBtn, mainBtn.nextSibling);
        }
    }
}

// Start auto-refresh on page load
document.addEventListener('DOMContentLoaded', () => {
    initDashboardApp();
});

// Stop auto-refresh when leaving the page
window.addEventListener('beforeunload', () => {
    stopAutoRefresh();
});

// ==================== NEW SETTINGS FUNCTIONS ====================

function toggleAutoRefresh() {
    const enabled = document.getElementById('auto-refresh-enabled').checked;
    if (enabled) {
        startAutoRefresh();
        showToast('success', 'Auto-refresh enabled');
    } else {
        stopAutoRefresh();
        showToast('success', 'Auto-refresh disabled');
    }
}

function restartAutoRefresh() {
    if (document.getElementById('auto-refresh-enabled')?.checked) {
        startAutoRefresh();
    }
}

function requestNotificationPermission() {
    const desktopToggle = document.getElementById('desktop-notifications');
    if (!('Notification' in window)) {
        if (desktopToggle) desktopToggle.checked = false;
        showToast('error', 'This browser does not support desktop notifications');
        return;
    }
    
    if (Notification.permission === 'granted') {
        if (desktopToggle) desktopToggle.checked = true;
        saveSettings();
        showToast('success', 'Desktop notifications already enabled');
    } else if (Notification.permission !== 'denied') {
        Notification.requestPermission().then(permission => {
            if (permission === 'granted') {
                if (desktopToggle) desktopToggle.checked = true;
                saveSettings();
                showToast('success', 'Desktop notifications enabled');
                new Notification('AI Price Alert', {
                    body: 'Notifications enabled successfully!',
                    icon: '/static/og-image.svg'
                });
            } else {
                if (desktopToggle) desktopToggle.checked = false;
                saveSettings();
                showToast('error', 'Desktop notifications denied');
            }
        });
    } else {
        if (desktopToggle) desktopToggle.checked = false;
        saveSettings();
        showToast('error', 'Desktop notifications are blocked in your browser');
    }
}

function desktopNotificationsEnabled() {
    return !!document.getElementById('desktop-notifications')?.checked && ('Notification' in window) && Notification.permission === 'granted';
}

async function triggerBrowserNotification(tracker, options = {}) {
    if (!desktopNotificationsEnabled() && !document.getElementById('push-notifications')?.checked) return;
    const title = options.title || 'Price target reached';
    const body = options.body || ((tracker.productName || 'Tracked product') + ' is now ' + formatCurrency(tracker.currencySymbol, tracker.currentPrice));
    const targetUrl = options.url || tracker.url;
    const iconUrl = options.icon || tracker.productImage || '/static/og-image.svg';
    if (dashboardServiceWorker && dashboardServiceWorker.showNotification) {
        try {
            await dashboardServiceWorker.showNotification(title, {
                body,
                icon: iconUrl,
                badge: '/static/og-image.svg',
                data: { url: targetUrl }
            });
            return;
        } catch (error) {
            console.error('Service worker notification failed', error);
        }
    }
    if (desktopNotificationsEnabled()) {
        new Notification(title, {
            body,
            icon: iconUrl
        });
    }
}

function showApiKey() {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'api-modal';
    modal.innerHTML = `
        <div class="modal">
            <div class="modal-header">
                <h3><i class="fa fa-key"></i> API Access</h3>
                <button class="modal-close" onclick="closeModal('api-modal')">&times;</button>
            </div>
            <div class="modal-body">
                <p>Use this API key for custom integrations:</p>
                <div class="api-key-display">
                    <code id="api-key">AI_PRICE_ALERT_API_KEY_${Date.now()}_${Math.random().toString(36).substr(2, 9)}</code>
                    <button class="btn-secondary" onclick="copyApiKey()">
                        <i class="fa fa-copy"></i> Copy
                    </button>
                </div>
                <p class="api-docs-link">
                    <a href="/contact">View API Documentation</a>
                </p>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    setTimeout(() => modal.classList.add('active'), 10);
}

function copyApiKey() {
    const apiKey = document.getElementById('api-key').textContent;
    navigator.clipboard.writeText(apiKey).then(() => {
        showToast('success', 'API key copied to clipboard');
    }).catch(() => {
        showToast('error', 'Failed to copy API key');
    });
}

function showFeedbackModal() {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'feedback-modal';
    modal.innerHTML = `
        <div class="modal">
            <div class="modal-header">
                <h3><i class="fa fa-comment"></i> Send Feedback</h3>
                <button class="modal-close" onclick="closeModal('feedback-modal')">&times;</button>
            </div>
            <div class="modal-body">
                <p>We'd love to hear your thoughts!</p>
                <div class="form-group">
                    <label>Feedback Type</label>
                    <select id="feedback-type" class="product-input">
                        <option value="bug">Bug Report</option>
                        <option value="feature">Feature Request</option>
                        <option value="improvement">Improvement Idea</option>
                        <option value="other">Other</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Your Feedback</label>
                    <textarea id="feedback-message" class="product-input" rows="5" placeholder="Tell us what you think..."></textarea>
                </div>
                <button class="action-btn" onclick="submitFeedback()">
                    <i class="fa fa-paper-plane"></i> Submit Feedback
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    setTimeout(() => modal.classList.add('active'), 10);
}

function submitFeedback() {
    const type = document.getElementById('feedback-type').value;
    const message = document.getElementById('feedback-message').value;
    
    if (!message.trim()) {
        showToast('error', 'Please enter your feedback');
        return;
    }
    
    // In a real app, this would send to a backend
    console.log('Feedback submitted:', { type, message });
    
    showToast('success', 'Thank you for your feedback!');
    closeModal('feedback-modal');
}

// ==================== AI ACCOUNT FEATURES ====================

function detectStore(url) {
    const value = String(url || '').toLowerCase();
    if (value.includes('amazon')) return 'Amazon';
    if (value.includes('flipkart')) return 'Flipkart';
    if (value.includes('myntra')) return 'Myntra';
    if (value.includes('ajio')) return 'Ajio';
    if (value.includes('meesho')) return 'Meesho';
    if (value.includes('snapdeal')) return 'Snapdeal';
    if (value.includes('tatacliq') || value.includes('tata')) return 'Tata CLiQ';
    if (value.includes('reliance')) return 'Reliance Digital';
    return 'Other';
}

function refreshAIInsights(showToastMessage = false) {
    const scoreEl = document.getElementById('ai-health-score');
    const coverageEl = document.getElementById('ai-coverage');
    const fastDropEl = document.getElementById('ai-fast-drop');
    const riskEl = document.getElementById('ai-risk-alerts');
    const recommendationsEl = document.getElementById('ai-recommendations');
    if (!scoreEl || !coverageEl || !fastDropEl || !riskEl || !recommendationsEl) return;

    if (!trackers.length) {
        scoreEl.textContent = '68/100';
        coverageEl.textContent = '0 stores';
        fastDropEl.textContent = '--';
        riskEl.textContent = '1';
        recommendationsEl.innerHTML = '<li>Add at least 3 trackers to activate stronger AI forecasting.</li><li>Use target price near 8-15% below current price for higher hit-rate.</li>';
        return;
    }

    const uniqueStores = new Set(trackers.map((tracker) => detectStore(tracker.url)).filter((store) => store !== 'Other'));
    const reached = trackers.filter((tracker) => Number(tracker.currentPrice) <= Number(tracker.targetPrice)).length;
    const riskAlerts = trackers.filter((tracker) => !tracker.url || !/^https?:\/\//i.test(String(tracker.url))).length;
    const speedCandidate = trackers
        .filter((tracker) => tracker.createdAt)
        .sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt))[0];

    const base = 55;
    const score = Math.min(
        99,
        Math.round(base + Math.min(uniqueStores.size * 5, 25) + Math.min(reached * 2, 12) - Math.min(riskAlerts * 8, 20))
    );

    scoreEl.textContent = score + '/100';
    coverageEl.textContent = uniqueStores.size + ' stores';
    fastDropEl.textContent = speedCandidate ? (speedCandidate.productName || 'Tracked item').slice(0, 20) : '--';
    riskEl.textContent = String(riskAlerts);

    const recs = [];
    if (uniqueStores.size < 3) recs.push('Track 3+ different stores to improve AI comparison and deal timing.');
    if (reached === 0) recs.push('Lower one target by 5% to increase first successful alert probability.');
    if (riskAlerts > 0) recs.push('Some links look invalid. Update broken URLs to keep auto-refresh healthy.');
    recs.push('Use "Refresh All" during sale windows for higher precision alerts.');
    recommendationsEl.innerHTML = recs.slice(0, 4).map((text) => '<li>' + text + '</li>').join('');

    if (showToastMessage) {
        showToast('success', 'AI insights refreshed for ' + (dashboardUser.username || 'your account'));
    }
}

async function runAiAutofix() {
    const healthPromise = fetch(API_BASE_URL + '/health', { method: 'GET' });
    const userPromise = fetch(API_BASE_URL + '/api/user', { method: 'GET' });
    const results = await Promise.allSettled([healthPromise, userPromise]);

    if (results[0].status !== 'fulfilled' || !results[0].value.ok) {
        showToast('error', 'Auto-fix detected server issue. Check deployment health.');
        return;
    }

    try {
        const raw = localStorage.getItem('settings');
        if (raw) JSON.parse(raw);
    } catch (e) {
        localStorage.removeItem('settings');
    }

    loadTrackers();
    startAutoRefresh();
    refreshAIInsights(true);
}

// ==================== AI HELPER CHAT ====================

function appendAiMessage(text, sender) {
    const box = document.getElementById('ai-helper-messages');
    if (!box) return;
    const row = document.createElement('div');
    row.className = 'ai-msg ' + (sender === 'user' ? 'user' : 'bot');
    row.textContent = text;
    box.appendChild(row);
    box.scrollTop = box.scrollHeight;
}

function toggleAiHelper(forceOpen) {
    const panel = document.getElementById('ai-helper-panel');
    if (!panel) return;
    const shouldOpen = typeof forceOpen === 'boolean' ? forceOpen : !panel.classList.contains('open');
    panel.classList.toggle('open', shouldOpen);
}

function runAiCommand(input) {
    const text = String(input || '').toLowerCase();
    if (text.includes('tracker')) {
        switchView('my-trackers');
        return 'Opened My Trackers. I also refreshed AI insights for this account.';
    }
    if (text.includes('new') || text.includes('add')) {
        switchView('new-alert');
        return 'Opened New Alert view. Paste a product link to start tracking.';
    }
    if (text.includes('setting')) {
        switchView('settings');
        return 'Opened Settings. You can configure notifications, refresh, and backup here.';
    }
    if (text.includes('refresh')) {
        autoRefreshAllPrices();
        return 'Triggered refresh for all trackers.';
    }
    if (text.includes('fix') || text.includes('error')) {
        runAiAutofix();
        return 'Running account auto-fix and health checks now.';
    }
    if (text.includes('trend')) {
        switchView('price-trends');
        return 'Opened Price Trends. Pick a tracker to view history.';
    }
    return 'Try commands like: "open trackers", "refresh", "open settings", or "fix errors".';
}

function sendAiChatMessage() {
    const input = document.getElementById('ai-chat-input');
    if (!input) return;
    const message = input.value.trim();
    if (!message) return;
    appendAiMessage(message, 'user');
    const reply = runAiCommand(message);
    appendAiMessage(reply, 'bot');
    refreshAIInsights();
    input.value = '';
}

function initAiAssistant() {
    const toggle = document.getElementById('ai-helper-toggle');
    const input = document.getElementById('ai-chat-input');
    if (toggle) {
        toggle.addEventListener('click', () => {
            toggleAiHelper();
        });
    }
    if (input) {
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                sendAiChatMessage();
            }
        });
    }
    appendAiMessage('Hi ' + (dashboardUser.username || 'there') + ', I can navigate and auto-fix account issues.', 'bot');
}

function logActivity(title, detail) {
    recentActivity.unshift({
        title: title,
        detail: detail,
        time: new Date().toISOString()
    });
    if (recentActivity.length > 25) {
        recentActivity = recentActivity.slice(0, 25);
    }
}

function formatRelativeTime(iso) {
    const diffMs = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return mins + 'm ago';
    const hours = Math.floor(mins / 60);
    if (hours < 24) return hours + 'h ago';
    return Math.floor(hours / 24) + 'd ago';
}

function renderActivityFeed() {
    const feed = document.getElementById('activity-feed');
    if (!feed) return;

    if (!recentActivity.length) {
        const base = trackers.slice(0, 4).map((tracker) => ({
            title: 'Tracker active',
            detail: tracker.productName || 'Tracked product',
            time: tracker.createdAt || new Date().toISOString()
        }));
        recentActivity = base;
    }

    if (!recentActivity.length) {
        feed.innerHTML = '<div class="activity-item">No activity yet.</div>';
        return;
    }

    feed.innerHTML = recentActivity.slice(0, 8).map((item) => (
        '<div class="activity-item">' +
            '<div class="activity-main"><strong>' + escapeHtml(item.title) + '</strong><span>' + escapeHtml(item.detail) + '</span></div>' +
            '<div class="activity-time">' + formatRelativeTime(item.time) + '</div>' +
        '</div>'
    )).join('');
}

// ==================== 3D TRACKER EFFECT ====================

function initTracker3D() {
    const cards = document.querySelectorAll('.tracker-card.tilt-3d');
    cards.forEach((card) => {
        if (card.dataset.tiltReady === '1') return;
        card.dataset.tiltReady = '1';
        card.addEventListener('mousemove', (event) => {
            const rect = card.getBoundingClientRect();
            const px = (event.clientX - rect.left) / rect.width;
            const py = (event.clientY - rect.top) / rect.height;
            const rotateY = (px - 0.5) * 10;
            const rotateX = (0.5 - py) * 8;
            card.style.transform = 'perspective(900px) rotateX(' + rotateX.toFixed(2) + 'deg) rotateY(' + rotateY.toFixed(2) + 'deg)';
        });
        card.addEventListener('mouseleave', () => {
            card.style.transform = '';
        });
    });
}

// ==================== COMMAND PALETTE ====================

const COMMANDS = [
    { key: 'new', label: 'Open New Alert', run: () => switchView('new-alert') },
    { key: 'trackers', label: 'Open My Trackers', run: () => switchView('my-trackers') },
    { key: 'settings', label: 'Open Settings', run: () => switchView('settings') },
    { key: 'trends', label: 'Open Price Trends', run: () => switchView('price-trends') },
    { key: 'refresh', label: 'Refresh All Prices', run: () => autoRefreshAllPrices() },
    { key: 'fix', label: 'Run AI Auto Fix', run: () => runAiAutofix() },
    { key: 'chat', label: 'Open AI Helper', run: () => toggleAiHelper(true) }
];

function openCommandPalette() {
    const modal = document.getElementById('command-palette');
    const input = document.getElementById('command-input');
    if (!modal || !input) return;
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    renderCommandList('');
    setTimeout(() => input.focus(), 10);
}

function closeCommandPalette() {
    const modal = document.getElementById('command-palette');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
}

function renderCommandList(query) {
    const list = document.getElementById('command-list');
    if (!list) return;
    const q = String(query || '').toLowerCase();
    const filtered = COMMANDS.filter((cmd) => !q || cmd.key.includes(q) || cmd.label.toLowerCase().includes(q));
    list.innerHTML = filtered.map((cmd) => (
        '<button type="button" class="command-item" data-command="' + cmd.key + '">' +
            '<span>' + cmd.label + '</span>' +
            '<code>' + cmd.key + '</code>' +
        '</button>'
    )).join('');

    list.querySelectorAll('.command-item').forEach((btn) => {
        btn.addEventListener('click', () => {
            const found = COMMANDS.find((c) => c.key === btn.dataset.command);
            if (found) {
                found.run();
                logActivity('Quick command', found.label);
                closeCommandPalette();
            }
        });
    });
}

function initCommandPalette() {
    const input = document.getElementById('command-input');
    const modal = document.getElementById('command-palette');
    if (input) {
        input.addEventListener('input', (event) => {
            renderCommandList(event.target.value || '');
        });
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') closeCommandPalette();
            if (event.key === 'Enter') {
                const first = document.querySelector('.command-item');
                if (first) first.click();
            }
        });
    }
    if (modal) {
        modal.addEventListener('click', (event) => {
            if (event.target === modal) closeCommandPalette();
        });
    }
    document.addEventListener('keydown', (event) => {
        const isMetaK = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k';
        if (isMetaK) {
            event.preventDefault();
            openCommandPalette();
        }
        if (event.key === 'Escape') {
            closeCommandPalette();
        }
    });
}
