/**
 * AI Price Alert - AdSense Integration
 * 
 * AdSense is now configured with your Publisher ID and Ad Slot
 */

const AdSenseConfig = {
    // Your AdSense Publisher ID (required) - format: ca-pub-XXXXXXXXXXXXXX
    publisherId: 'ca-pub-1181608933401999',
    
    // Ad Unit IDs
    adUnits: {
        // Banner ads for dashboard
        dashboardBanner: '7186431191',
        
        // Rectangle ads
        dashboardRectangle: '7186431191',
        
        // Responsive ad unit
        responsive: '7186431191',
        
        // In-article ads
        inArticle: '7186431191',
        
        // Sidebar ads (if applicable)
        sidebar: '7186431191',
        
        // Login page
        loginPage: '7186431191',
        
        // Signup page
        signupPage: '7186431191',
        
        // Home/Landing page
        homePage: '7186431191'
    },
    
    // Enable/disable ads (set to false to disable ads completely)
    enabled: false,
    
    // Test mode (shows placeholder ads when false)
    testMode: false
};

// Ad slot positions
const AdPositions = {
    DASHBOARD_TOP: 'ad-dashboard-top',
    DASHBOARD_BOTTOM: 'ad-dashboard-bottom',
    SIDEBAR: 'ad-sidebar',
    LOGIN_PAGE: 'ad-login',
    SIGNUP_PAGE: 'ad-signup'
};

/**
 * Initialize AdSense
 */
function initAds() {
    if (!AdSenseConfig.enabled && !AdSenseConfig.testMode) {
        console.log('Ads disabled');
        return;
    }
    
    // Load AdSense script
    if (AdSenseConfig.publisherId && AdSenseConfig.publisherId !== 'YOUR_PUBLISHER_ID') {
        loadAdSenseScript();
    } else if (AdSenseConfig.testMode) {
        showAdPlaceholders();
    }
}

/**
 * Load Google AdSense script
 */
function loadAdSenseScript() {
    // Check if script is already loaded (either statically or dynamically)
    if (window.adsbygoogle) {
        console.log('AdSense script already loaded, rendering ads...');
        renderAds();
        return;
    }
    
    // Check if script tag already exists in document
    const existingScript = document.querySelector('script[src*="adsbygoogle"]');
    if (existingScript) {
        console.log('AdSense script tag already exists, waiting for load...');
        existingScript.onload = function() {
            renderAds();
        };
        existingScript.onerror = function() {
            console.error('Failed to load AdSense script');
            showAdPlaceholders();
        };
        return;
    }
    
    try {
        const script = document.createElement('script');
        script.async = true;
        script.src = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=' + AdSenseConfig.publisherId;
        script.crossOrigin = 'anonymous';
        
        script.onerror = function() {
            console.error('Failed to load AdSense script');
            showAdPlaceholders();
        };
        
        script.onload = function() {
            renderAds();
        };
        
        document.head.appendChild(script);
    } catch (e) {
        console.error('Error loading AdSense:', e);
        showAdPlaceholders();
    }
}

/**
 * Render all ads on the page
 */
function renderAds() {
    try {
        const adSlots = document.querySelectorAll('[data-ad-slot]');
        adSlots.forEach(function(slot) {
            const slotId = slot.getAttribute('data-ad-slot');
            if (AdSenseConfig.adUnits[slotId]) {
                const adUnitId = AdSenseConfig.adUnits[slotId];
                slot.innerHTML = '<ins class="adsbygoogle" style="display:block" data-ad-client="' + AdSenseConfig.publisherId + '" data-ad-slot="' + adUnitId + '" data-ad-format="auto" data-full-width-responsive="true"></ins>';
                try {
                    (adsbygoogle = window.adsbygoogle || []).push({});
                } catch (e) {
                    console.error('AdSense push error:', e);
                    // Show placeholder instead of broken ad
                    slot.innerHTML = '<div class="ad-placeholder"><div class="ad-placeholder-content"><span class="ad-label">Advertisement</span><div class="ad-placeholder-box"><i class="fa fa-ad"></i><span>Ad</span></div></div></div>';
                }
            }
        });
    } catch (e) {
        console.error('AdSense render error:', e);
    }
}

/**
 * Show placeholder ads for testing
 */
function showAdPlaceholders() {
    const adSlots = document.querySelectorAll('[data-ad-slot]');
    adSlots.forEach(function(slot) {
        slot.innerHTML = '<div class="ad-placeholder"><div class="ad-placeholder-content"><span class="ad-label">Advertisement</span><div class="ad-placeholder-box"><i class="fa fa-ad"></i><span>Your Ad Here</span><small>Configure AdSense to display real ads</small></div></div></div>';
    });
}

/**
 * Inject ad container into page
 */
function injectAdContainer(position, containerId) {
    const container = document.createElement('div');
    container.id = containerId;
    container.setAttribute('data-ad-slot', position);
    container.className = 'ad-container';
    return container;
}

/**
 * Track ad impressions (for analytics)
 */
function trackAdImpression(adSlot, adType) {
    console.log('Ad Impression: ' + adSlot + ' - ' + adType);
    if (typeof gtag !== 'undefined') {
        gtag('event', 'ad_impression', {
            'ad_slot': adSlot,
            'ad_type': adType
        });
    }
}

/**
 * Check if user is premium (no ads)
 */
function shouldShowAds() {
    const user = JSON.parse(localStorage.getItem('user') || '{}');
    return !user.isPremium;
}

// Initialize ads when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    if (shouldShowAds()) {
        initAds();
    }
});

// Export for use in other scripts
window.AdSenseConfig = AdSenseConfig;
window.AdPositions = AdPositions;
window.initAds = initAds;
window.renderAds = renderAds;
