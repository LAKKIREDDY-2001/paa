self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
    let payload = { title: 'Price Alerter', body: 'A tracked product has an update.', url: '/' };
    try {
        payload = event.data ? event.data.json() : payload;
    } catch (error) {
        payload = { title: 'Price Alerter', body: event.data ? event.data.text() : 'A tracked product has an update.', url: '/' };
    }
    event.waitUntil(
        self.registration.showNotification(payload.title || 'Price Alerter', {
            body: payload.body || 'A tracked product has an update.',
            icon: '/static/og-image.svg',
            badge: '/static/og-image.svg',
            data: { url: payload.url || '/' }
        })
    );
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) || '/';
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
            for (const client of clients) {
                if ('focus' in client) {
                    client.navigate(targetUrl);
                    return client.focus();
                }
            }
            if (self.clients.openWindow) {
                return self.clients.openWindow(targetUrl);
            }
            return null;
        })
    );
});
