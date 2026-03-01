// Απλό Service Worker για να περάσουμε τα κριτήρια εγκατάστασης της PWA
const CACHE_NAME = 'weather-app-v1';

self.addEventListener('install', (event) => {
    console.log('Service Worker: Εγκαταστάθηκε');
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    console.log('Service Worker: Ενεργοποιήθηκε');
});

self.addEventListener('fetch', (event) => {
    // Προς το παρόν απλά αφήνουμε όλα τα requests να περνάνε κανονικά
    event.respondWith(fetch(event.request));
});