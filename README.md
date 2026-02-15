# AI Shopping Price Alert Assistant 🛒🔔

A smart price tracking application that helps you save money by alerting you when product prices drop on Amazon and other e-commerce platforms.

![Price Alert](https://img.shields.io/badge/Price-Alert-brightgreen)
![Python](https://img.shields.io/badge/Python-3.8+-blue)
![Flask](https://img.shields.io/badge/Flask-2.0+-orange)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ Features

- **🔍 Real-time Price Tracking**: Monitor prices on Amazon and other e-commerce sites
- **🤖 AI-Powered Analysis**: Get intelligent price predictions and recommendations
- **📱 Multi-Platform Alerts**: Receive notifications via Telegram, WhatsApp, and Email
- **🌐 Browser Extension**: Track prices directly from your browser
- **📊 Price History**: View historical price trends and charts
- **💰 Smart Alerts**: Set custom target prices and get notified when reached
- **🔥 Firebase Integration**: Secure authentication and real-time database
- **📝 WordPress Integration**: Embed price tracking on WordPress sites

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Node.js 14+ (for browser extension)
- Firebase account
- Modern web browser

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/price-alerter.git
   cd price-alerter
   ```

2. **Install backend dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install frontend dependencies (optional):**
   ```bash
   npm install
   ```

4. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and Firebase credentials
   ```

5. **Start the backend server:**
   ```bash
   python app.py
   ```

6. **Open the frontend:**
   - Open `index.html` in your browser
   - Or use VS Code Live Server extension

### Browser Extension Setup

1. Open Chrome and navigate to `chrome://extensions/`
2. Enable "Developer mode"
3. Click "Load unpacked"
4. Select the `browser-extension` folder

## 📁 Project Structure

```
price-alerter/
├── app.py                 # Flask backend
├── static/                # Frontend assets
│   ├── script.js         # Main JavaScript
│   ├── style.css         # Styles
│   ├── auth.js           # Authentication
│   ├── firebase-init.js  # Firebase initialization
│   └── ads.js            # Ad integration
├── templates/            # HTML templates
│   ├── index.html        # Main page
│   ├── login.html        # Login page
│   ├── signup.html       # Signup page
│   └── ...
├── browser-extension/    # Chrome extension
│   ├── manifest.json     # Extension config
│   ├── popup.html        # Extension popup
│   ├── popup.js          # Extension logic
│   └── content.js        # Content scripts
├── wordpress-plugin/     # WordPress integration
├── firebase.json         # Firebase config
├── requirements.txt      # Python dependencies
└── package.json          # Node.js dependencies
```

## 🔧 Configuration

### Firebase Setup

1. Create a Firebase project at [Firebase Console](https://console.firebase.google.com/)
2. Enable Authentication (Email/Password, Google)
3. Create a Firestore database
4. Copy your Firebase config to `static/firebase-init.js`

### Telegram Integration

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Get your bot token
3. Add token to `telegram_config.json`

### WhatsApp Integration

1. Get WhatsApp Business API credentials
2. Configure in `whatsapp_config.json`

## 🛠️ Tech Stack

- **Backend:** Python, Flask, Flask-Cors
- **Frontend:** HTML5, CSS3, JavaScript
- **Database:** Firebase Firestore, SQLite
- **Authentication:** Firebase Auth
- **Browser Extension:** Chrome Extension API
- **Deployment:** Heroku, Render, VPS

## 📖 API Documentation

### Backend Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/track` | POST | Track a product URL |
| `/api/price` | GET | Get current price |
| `/api/alerts` | GET/POST | Manage price alerts |
| `/api/history` | GET | Get price history |

### WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `price_update` | Server → Client | Price change notification |
| `alert_triggered` | Server → Client | Alert triggered |

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) for web scraping
- [Firebase](https://firebase.google.com/) for backend services
- [Flask](https://flask.palletsprojects.com/) for the web framework

## 📞 Support

- 📧 Email: support@pricealerter.com
- 💬 Discord: [Join our community](https://discord.gg/pricealerter)
- 🐛 Issues: [Report a bug](https://github.com/yourusername/price-alerter/issues)

---

**Made with ❤️ for smart shoppers**

