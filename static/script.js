// Dashboard JavaScript - Main app functionality with celebration
let trackers = [];
let currentFilter = 'all';
let currentTracker = null;
let celebrationTracker = null;

// Backend API configuration
const getApiBaseUrl = () => {
    const currentUrl = window.location.origin;
    if (currentUrl.includes('localhost') || currentUrl.includes('127.0.0.1')) {
        return currentUrl;
    }
    return 'http://localhost:8081';
};
const API_BASE_URL = getApiBaseUrl();

// Celebration Configuration
const celebrationColors = [
    '#ff6b6b', '#feca57', '#48dbfb', '#ff9ff3', 
    '#54a0ff', '#5f27cd', '#00d2d3', '#ff9f0a'
];

document.addEventListener('DOMContentLoaded', () => {
    loadTrackers();
    setupNavigation();
    loadUserData();
    initTilt();
    initCelebration();
});

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

function showCelebration(tracker) {
    const modal = document.getElementById('celebration-modal');
    const productNameEl = document.getElementById('celeb-product-name');
    const savingsEl = document.getElementById('celeb-savings');
    
    if (modal && tracker) {
        productNameEl.textContent = tracker.productName || 'Product';
        
        const saved = tracker.currentPrice - tracker.targetPrice;
        savingsEl.textContent = `You save ${tracker.currencySymbol || '$'}${Math.abs(saved).toFixed(2)}`;
        
        modal.classList.add('active');
        createConfetti();
        
        // Play sound effect (optional - browsers may block this)
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();
            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);
            oscillator.type = 'sine';
            oscillator.frequency.setValueAtTime(523.25, audioContext.currentTime); // C5
            oscillator.frequency.setValueAtTime(659.25, audioContext.currentTime + 0.1); // E5
            oscillator.frequency.setValueAtTime(783.99, audioContext.currentTime + 0.2); // G5
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

function createConfetti() {
    const container = document.getElementById('confetti-container');
    if (!container) return;
    
    container.innerHTML = '';
    
    for (let i = 0; i < 150; i++) {
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
    if (celebrationTracker && celebrationTracker.url) {
        window.open(celebrationTracker.url, '_blank');
    }
}

function checkPriceReached(tracker) {
    return tracker && tracker.currentPrice <= tracker.targetPrice;
}

// ==================== TILT EFFECT ====================

function initTilt() {
    const tiltRoots = document.querySelectorAll('.tilt-root');
    if (!tiltRoots.length) return;
    if (window.matchMedia('(hover: none)').matches) return;

    tiltRoots.forEach((root) => {
        let rect = null;
        const maxTilt = parseFloat(root.dataset.tilt || '8');

        const handleMove = (event) => {
            if (!rect) rect = root.getBoundingClientRect();
            const x = (event.clientX - rect.left) / rect.width;
            const y = (event.clientY - rect.top) / rect.height;
            const tiltX = (0.5 - y) * maxTilt;
            const tiltY = (x - 0.5) * maxTilt;
            root.classList.add('tilt-active');
            root.style.setProperty('--tilt-x', tiltX.toFixed(2) + 'deg');
            root.style.setProperty('--tilt-y', tiltY.toFixed(2) + 'deg');
        };

        const handleLeave = () => {
            root.classList.remove('tilt-active');
            root.style.setProperty('--tilt-x', '0deg');
            root.style.setProperty('--tilt-y', '0deg');
            rect = null;
        };

        root.addEventListener('mousemove', handleMove);
        root.addEventListener('mouseleave', handleLeave);
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
            }
        }
    } catch (error) {
        console.log('User not logged in');
    }
}

function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const view = item.dataset.view;
            switchView(view);
        });
    });
}

function switchView(viewName) {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.view === viewName) {
            item.classList.add('active');
        }
    });
    document.querySelectorAll('.view').forEach(view => {
        view.classList.remove('active');
    });
    document.getElementById('view-' + viewName).classList.add('active');
}

// ==================== PRICE TRACKING ====================

async function handleFlow() {
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
        setLoadingState(true, 'Fetching price...');
        
        try {
            const response = await fetch(API_BASE_URL + '/get-price', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                priceStep.style.display = 'block';
                priceStep.innerHTML = '<p><strong>Current Price: ' + (data.currency_symbol || '$') + data.price + '</strong></p>' +
                    '<input type="number" id="targetPrice" class="product-input" style="width: 150px;" placeholder="Set target price" value="' + (data.price * 0.9).toFixed(2) + '">';
                mainBtn.innerHTML = 'Create Tracker';
                setLoadingState(false);
                
                priceStep.dataset.productName = data.productName || 'Product';
                priceStep.dataset.currentPrice = data.price;
                priceStep.dataset.currency = data.currency;
                priceStep.dataset.currencySymbol = data.currency_symbol;
            } else {
                setLoadingState(false);
                showToast('error', data.error || 'Failed to fetch price');
            }
        } catch (error) {
            setLoadingState(false);
            showToast('error', 'Failed to connect to server');
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
        
        await createTracker(url, targetPrice, currentPrice, productName, currency, currencySymbol);
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

async function createTracker(url, targetPrice, currentPrice, productName, currency, currencySymbol) {
    const urlInput = document.getElementById('urlInput');
    const mainBtn = document.getElementById('mainBtn');
    const priceStep = document.getElementById('priceStep');
    
    setLoadingState(true, 'Creating tracker...');
    
    try {
        const response = await fetch(API_BASE_URL + '/api/trackers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                currentPrice: currentPrice,
                targetPrice: parseFloat(targetPrice),
                currency: currency,
                currencySymbol: currencySymbol,
                productName: productName
            })
        });
        
        if (!response.ok) {
            throw new Error('Failed to create tracker');
        }
        
        const newTracker = {
            id: Date.now(),
            url: url,
            productName: productName,
            currentPrice: currentPrice,
            targetPrice: parseFloat(targetPrice),
            currency: currency,
            currencySymbol: currencySymbol,
            createdAt: new Date().toISOString()
        };
        
        trackers.push(newTracker);
        localStorage.setItem('trackers', JSON.stringify(trackers));
        
        setLoadingState(false);
        showToast('success', 'Tracker created successfully!');
        
        urlInput.value = '';
        priceStep.style.display = 'none';
        mainBtn.innerHTML = 'Start AI Tracking';
        
        renderTrackers();
        updateStats();
        switchView('my-trackers');
    } catch (error) {
        setLoadingState(false);
        showToast('error', error.message);
    }
}

// ==================== TRACKERS DISPLAY ====================

function loadTrackers() {
    trackers = JSON.parse(localStorage.getItem('trackers') || '[]');
    renderTrackers();
    updateStats();
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
        if (urlLower.includes('amazon')) return '<img src="https://upload.wikimedia.org/wikipedia/commons/a/a9/Amazon_logo.svg" alt="Amazon" class="company-logo" onerror="this.style.display=\'none\'; this.parentElement.innerHTML=\'<i class=\\\'fa fa-amazon\\\'></i>\'">';
        if (urlLower.includes('flipkart')) return '<img src="https://upload.wikimedia.org/wikipedia/commons/2/2f/Flipkart_logo.svg" alt="Flipkart" class="company-logo" onerror="this.style.display=\'none\'; this.parentElement.innerHTML=\'<i class=\\\'fa fa-shopping-cart\\\'></i>\'">';
        if (urlLower.includes('myntra')) return '<img src="https://upload.wikimedia.org/wikipedia/commons/2/24/Myntra_logo.svg" alt="Myntra" class="company-logo" onerror="this.style.display=\'none\'; this.parentElement.innerHTML=\'<i class=\\\'fa fa-tag\\\'></i>\'">';
        if (urlLower.includes('ajio')) return '<i class="fa fa-shopping-bag"></i>';
        if (urlLower.includes('meesho')) return '<i class="fa fa-mobile"></i>';
        if (urlLower.includes('snapdeal')) return '<i class="fa fa-shopping-cart"></i>';
        if (urlLower.includes('tatacliq') || urlLower.includes('tata')) return '<i class="fa fa-store"></i>';
        if (urlLower.includes('reliance') || urlLower.includes('reliancedigital')) return '<i class="fa fa-laptop"></i>';
        if (urlLower.includes('ebay')) return '<i class="fa fa-shopping-bag"></i>';
        return '<i class="fa fa-shopping-bag"></i>';
    }
    
    container.innerHTML = filteredTrackers.map(tracker => {
        const status = tracker.currentPrice <= tracker.targetPrice ? 'reached' : 'active';
        const statusClass = status === 'reached' ? 'status-reached' : 'status-active';
        const statusText = status === 'reached' ? 'Target Reached!' : 'Active';
        
        return '<div class="tracker-card" data-id="' + tracker.id + '"><div class="tracker-header"><div class="tracker-info"><div class="tracker-logo">' + getCompanyLogo(tracker.url) + '</div><h4 class="tracker-name">' + (tracker.productName || 'Product') + '</h4></div><div class="tracker-checkbox" onclick="event.stopPropagation(); toggleSelect(' + tracker.id + ')"><i class="fa fa-check" style="display: none;"></i></div></div><div class="tracker-url">' + tracker.url + '</div><div class="tracker-prices"><div class="price-info current"><span class="price-label">Current</span><span class="price-amount">' + (tracker.currencySymbol || '$') + tracker.currentPrice + '</span></div><div class="price-info target"><span class="price-label">Target</span><span class="price-amount">' + (tracker.currencySymbol || '$') + tracker.targetPrice + '</span></div><div class="price-status ' + statusClass + '">' + statusText + '</div></div><div class="tracker-actions"><button class="tracker-action" onclick="viewTrends(' + tracker.id + ')"><i class="fa fa-chart-line"></i> Trends</button><button class="tracker-action" onclick="refreshPrice(' + tracker.id + ')"><i class="fa fa-refresh"></i> Refresh</button><button class="tracker-action delete" onclick="deleteTracker(' + tracker.id + ')"><i class="fa fa-trash"></i></button></div>';
    }).join('');
    
    updateCounts();
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
        const response = await fetch(API_BASE_URL + '/get-price', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: tracker.url })
        });
        
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.innerHTML = '<i class="fa fa-refresh"></i> Refresh';
        }
        
        const data = await response.json();
        
        if (response.ok) {
            const oldPrice = tracker.currentPrice;
            tracker.currentPrice = data.price;
            tracker.productName = data.productName || tracker.productName;
            
            // Check if target just reached
            if (checkPriceReached(tracker) && oldPrice > tracker.targetPrice) {
                celebrationTracker = tracker;
                setTimeout(() => {
                    showCelebration(tracker);
                }, 500);
            }
            
            localStorage.setItem('trackers', JSON.stringify(trackers));
            showToast('success', 'Price updated: ' + (data.currency_symbol || '$') + data.price);
            renderTrackers();
            updateStats();
        } else {
            showToast('error', data.error || 'Failed to refresh price');
        }
    } catch (error) {
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.innerHTML = '<i class="fa fa-refresh"></i> Refresh';
        }
        showToast('error', 'Failed to connect to server');
    }
}

function deleteTracker(trackerId) {
    if (!confirm('Are you sure you want to delete this tracker?')) return;
    trackers = trackers.filter(t => t.id !== trackerId);
    localStorage.setItem('trackers', JSON.stringify(trackers));
    renderTrackers();
    updateStats();
    showToast('success', 'Tracker deleted');
}

function toggleSelect(trackerId) {
    const checkbox = document.querySelector('.tracker-card[data-id="' + trackerId + '"] .tracker-checkbox');
    checkbox.classList.toggle('checked');
    const icon = checkbox.querySelector('i');
    icon.style.display = checkbox.classList.contains('checked') ? 'block' : 'none';
}

// ==================== PRICE TRENDS ====================

function viewTrends(trackerId) {
    const tracker = trackers.find(t => t.id === trackerId);
    if (!tracker) return;
    currentTracker = tracker;
    switchView('price-trends');
    
    document.querySelector('.product-details h3').textContent = tracker.productName || 'Product';
    document.querySelector('.product-details p').textContent = tracker.url;
    document.getElementById('original-price').textContent = (tracker.currencySymbol || '$') + tracker.currentPrice;
    document.getElementById('current-price').textContent = (tracker.currencySymbol || '$') + tracker.currentPrice;
    
    const savings = tracker.currentPrice - tracker.targetPrice;
    document.getElementById('savings-amount').textContent = (tracker.currencySymbol || '$') + savings.toFixed(2);
    
    generateChart(tracker);
    
    const prediction = tracker.currentPrice <= tracker.targetPrice ? 'Price is at or below your target!' : 'Price may drop further';
    document.getElementById('prediction-text').textContent = prediction;
    document.getElementById('confidence').textContent = '85%';
}

function generateChart(tracker) {
    const chartContainer = document.querySelector('.chart-main');
    const days = 7;
    const data = [];
    let basePrice = tracker.currentPrice;
    
    for (let i = 0; i < days; i++) {
        const variation = (Math.random() - 0.5) * basePrice * 0.1;
        data.push(basePrice + variation);
    }
    data[days - 1] = tracker.currentPrice;
    
    const maxPrice = Math.max(...data);
    chartContainer.innerHTML = '<div class="chart-placeholder"><div class="chart-line">' + 
        data.map(price => '<div class="chart-bar" style="height: ' + ((price / maxPrice) * 150) + 'px;" title="' + price.toFixed(2) + '"></div>').join('') + 
        '</div><div class="chart-labels">' + 
        Array.from({length: days}, (_, i) => { 
            const date = new Date(); 
            date.setDate(date.getDate() - (days - 1 - i)); 
            return '<span>' + date.toLocaleDateString('en-US', {month: 'short', day: 'numeric'}) + '</span>'; 
        }).join('') + '</div>';
    
    document.getElementById('trend-lowest').textContent = (tracker.currencySymbol || '$') + Math.min(...data).toFixed(2);
    document.getElementById('trend-highest').textContent = (tracker.currencySymbol || '$') + Math.max(...data).toFixed(2);
    document.getElementById('trend-since').textContent = new Date(tracker.createdAt).toLocaleDateString();
    document.getElementById('buy-now-btn').style.display = tracker.currentPrice <= tracker.targetPrice ? 'flex' : 'none';
    document.getElementById('buy-now-btn').onclick = () => window.open(tracker.url, '_blank');
}

function setTimePeriod(period) {
    document.querySelectorAll('.time-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.textContent.toLowerCase().includes(period)) btn.classList.add('active');
    });
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
        emailAlerts: document.getElementById('email-alerts').checked,
        darkMode: document.getElementById('dark-mode').checked,
        compactView: document.getElementById('compact-view').checked,
        refreshInterval: document.getElementById('refresh-interval').value,
        autoDelete: document.getElementById('auto-delete').value,
        dropPercentage: document.getElementById('drop-percentage').value
    }));
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
    if (settings.emailAlerts !== undefined) document.getElementById('email-alerts').checked = settings.emailAlerts;
    if (settings.darkMode !== undefined) document.getElementById('dark-mode').checked = settings.darkMode;
    if (settings.compactView !== undefined) document.getElementById('compact-view').checked = settings.compactView;
    if (settings.refreshInterval !== undefined) document.getElementById('refresh-interval').value = settings.refreshInterval;
    if (settings.autoDelete !== undefined) document.getElementById('auto-delete').value = settings.autoDelete;
    if (settings.dropPercentage !== undefined) document.getElementById('drop-percentage').value = settings.dropPercentage;
    const currency = localStorage.getItem('currency');
    if (currency) document.getElementById('currency-select').value = currency;
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
                trackers = imported;
                localStorage.setItem('trackers', JSON.stringify(trackers));
                renderTrackers();
                updateStats();
                showToast('success', 'Data imported successfully');
            }
        } catch (error) {
            showToast('error', 'Invalid file format');
        }
    };
    reader.readAsText(file);
}

function clearAllData() {
    if (!confirm('Are you sure you want to delete all trackers? This cannot be undone.')) return;
    trackers = [];
    localStorage.setItem('trackers', JSON.stringify(trackers));
    renderTrackers();
    updateStats();
    showToast('success', 'All data cleared');
}

function exportTrackers() { exportData(); }

function deleteSelected() {
    const selected = document.querySelectorAll('.tracker-checkbox.checked');
    if (selected.length === 0) {
        showToast('error', 'No trackers selected');
        return;
    }
    if (!confirm('Delete ' + selected.length + ' tracker(s)?')) return;
    selected.forEach(checkbox => {
        const card = checkbox.closest('.tracker-card');
        const id = parseInt(card.dataset.id);
        trackers = trackers.filter(t => t.id !== id);
    });
    localStorage.setItem('trackers', JSON.stringify(trackers));
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
                <h3><i class="fa fa-telegram"></i> Connect Telegram</h3>
                <button class="modal-close" onclick="closeModal('telegram-modal')">&times;</button>
            </div>
            <div class="modal-body">
                <div class="modal-icon telegram-icon">
                    <i class="fa fa-telegram"></i>
                </div>
                <p>Get instant price drop alerts on Telegram!</p>
                <button class="action-btn" onclick="window.open('https://t.me/AI_Price_Alert_Bot', '_blank')">
                    <i class="fa fa-external-link"></i> Open Telegram Bot
                </button>
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
                <h3><i class="fa fa-whatsapp"></i> Connect WhatsApp</h3>
                <button class="modal-close" onclick="closeModal('whatsapp-modal')">&times;</button>
            </div>
            <div class="modal-body">
                <div class="modal-icon whatsapp-icon">
                    <i class="fa fa-whatsapp"></i>
                </div>
                <p>Get price drop alerts on WhatsApp!</p>
                <input type="tel" id="whatsapp-number" class="product-input" placeholder="+1234567890" style="width: 100%; margin-bottom: 12px;">
                <button class="action-btn" onclick="saveWhatsAppNumber()">
                    <i class="fa fa-check"></i> Connect
                </button>
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

function saveWhatsAppNumber() {
    showToast('success', 'WhatsApp connected!');
    closeModal('whatsapp-modal');
}

// Initialize settings on load
loadSettings();

// ==================== AUTO-REFRESH ALERTER ====================

let autoRefreshInterval = null;
let lastRefreshTime = null;

function startAutoRefresh() {
    const settings = JSON.parse(localStorage.getItem('settings') || '{}');
    const intervalMinutes = parseInt(settings.refreshInterval || '15');
    const intervalMs = intervalMinutes * 60 * 1000;
    
    // Clear any existing interval
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
    }
    
    // Start new interval
    autoRefreshInterval = setInterval(() => {
        autoRefreshAllPrices();
    }, intervalMs);
    
    // Update UI to show auto-refresh is active
    updateAutoRefreshUI(intervalMinutes);
    console.log(`Auto-refresh started: every ${intervalMinutes} minutes`);
}

function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
    console.log('Auto-refresh stopped');
}

async function autoRefreshAllPrices() {
    if (trackers.length === 0) return;
    
    console.log('Auto-refreshing all prices...');
    lastRefreshTime = new Date();
    
    let updatedCount = 0;
    for (const tracker of trackers) {
        try {
            const response = await fetch(API_BASE_URL + '/get-price', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: tracker.url })
            });
            
            if (response.ok) {
                const data = await response.json();
                const oldPrice = tracker.currentPrice;
                tracker.currentPrice = data.price;
                tracker.productName = data.productName || tracker.productName;
                
                // Check if target just reached
                if (checkPriceReached(tracker) && oldPrice > tracker.targetPrice) {
                    celebrationTracker = tracker;
                    showCelebration(tracker);
                }
                updatedCount++;
            }
        } catch (error) {
            console.error(`Failed to refresh price for ${tracker.url}:`, error);
        }
    }
    
    // Save updated trackers
    localStorage.setItem('trackers', JSON.stringify(trackers));
    
    // Update UI
    renderTrackers();
    updateStats();
    
    // Show notification
    if (updatedCount > 0) {
        showToast('success', `Auto-refreshed ${updatedCount} tracker(s)`);
    }
}

function updateAutoRefreshUI(intervalMinutes) {
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
        let secondsRemaining = intervalMinutes * 60;
        refreshTimer.innerHTML = `<i class="fa fa-sync fa-spin"></i> ${formatTime(secondsRemaining)}`;
        
        // Update timer every second
        if (window.refreshTimerInterval) {
            clearInterval(window.refreshTimerInterval);
        }
        window.refreshTimerInterval = setInterval(() => {
            secondsRemaining--;
            if (secondsRemaining <= 0) {
                secondsRemaining = intervalMinutes * 60;
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
    loadTrackers();
    setupNavigation();
    loadUserData();
    initTilt();
    initCelebration();
    startAutoRefresh();
    addManualRefreshButton();
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
    if (!('Notification' in window)) {
        showToast('error', 'This browser does not support desktop notifications');
        return;
    }
    
    if (Notification.permission === 'granted') {
        showToast('success', 'Desktop notifications already enabled');
    } else if (Notification.permission !== 'denied') {
        Notification.requestPermission().then(permission => {
            if (permission === 'granted') {
                showToast('success', 'Desktop notifications enabled');
                new Notification('AI Price Alert', {
                    body: 'Notifications enabled successfully!',
                    icon: '🔔'
                });
            } else {
                showToast('error', 'Desktop notifications denied');
            }
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
                    <a href="#" target="_blank">View API Documentation</a>
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
