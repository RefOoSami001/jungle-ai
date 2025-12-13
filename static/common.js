/**
 * Common JavaScript utilities for Quiz Generator application.
 */

/**
 * Initialize Telegram WebApp if available.
 */
function initTelegramWebApp() {
  if (window.Telegram && window.Telegram.WebApp) {
    const tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
  }
}

/**
 * Get user info (ID and name) from Telegram WebApp.
 * @returns {Object} Object with id, name, and full_name properties
 */
function getTelegramUserInfo() {
  if (window.Telegram && window.Telegram.WebApp) {
    const webApp = window.Telegram.WebApp;
    
    // Try initDataUnsafe first
    if (webApp.initDataUnsafe && webApp.initDataUnsafe.user) {
      const user = webApp.initDataUnsafe.user;
      return {
        id: user.id ? String(user.id) : null,
        name: user.first_name || user.username || null,
        full_name: user.first_name && user.last_name 
          ? `${user.first_name} ${user.last_name}`.trim()
          : user.first_name || user.username || null
      };
    }
    
    // Try parsing initData string
    if (webApp.initData) {
      try {
        const params = new URLSearchParams(webApp.initData);
        const userParam = params.get('user');
        if (userParam) {
          const user = JSON.parse(decodeURIComponent(userParam));
          return {
            id: user.id ? String(user.id) : null,
            name: user.first_name || user.username || null,
            full_name: user.first_name && user.last_name 
              ? `${user.first_name} ${user.last_name}`.trim()
              : user.first_name || user.username || null
          };
        }
      } catch (e) {
        console.log('Error parsing initData:', e);
      }
    }
  }
  return { id: null, name: null, full_name: null };
}

/**
 * Notify admin when mini app is opened.
 * @param {string} page - Page identifier (e.g., 'index', 'quiz')
 */
async function notifyAdmin(page = 'unknown') {
  const userInfo = getTelegramUserInfo();
  if (userInfo.id) {
    try {
      await fetch('/api/notify-admin', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          user_id: userInfo.id,
          user_name: userInfo.full_name || userInfo.name || 'Unknown',
          page: page
        })
      });
    } catch (e) {
      console.error('Error notifying admin:', e);
    }
  }
}

/**
 * Format file size in human-readable format.
 * @param {number} bytes - File size in bytes
 * @returns {string} Formatted file size
 */
function formatFileSize(bytes) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}
