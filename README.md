# RefOo Quiz Generator

AI-powered quiz generator that creates questions from text or uploaded PDF/Word documents. Built with Flask and designed to work as a Telegram Mini App.

## Features

- 📝 Text input or file upload (PDF/Word)
- 📄 Page range selection for documents
- 🎯 Multiple question types (MCQ, Case Scenario, Open-ended, True/False)
- 📊 Configurable difficulty and question amount
- 📱 Telegram integration - send questions directly to Telegram
- 🎨 Modern, responsive UI

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd QuizGeneratorJungle
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
python app.py
```

The app will be available at `http://localhost:5000`

## Deployment on Koyeb

### Prerequisites
- A Koyeb account
- Your code pushed to a Git repository (GitHub, GitLab, or Bitbucket)

### Steps

1. **Push your code to a Git repository**

2. **Create a new app on Koyeb:**
   - Go to [Koyeb Dashboard](https://app.koyeb.com)
   - Click "Create App"
   - Connect your Git repository
   - Select the branch you want to deploy

3. **Configure the app:**
   - **Build Command:** (leave empty, Koyeb auto-detects Python)
   - **Run Command:** `gunicorn app:app`
   - **Port:** Koyeb automatically sets the PORT environment variable

4. **Environment Variables:**
   - `TELEGRAM_BOT_TOKEN` - Your Telegram bot token (required for Telegram features)
   - `FLASK_ENV=production` (for production mode)
   - `PORT` - Automatically set by Koyeb (no need to configure)

5. **Deploy:**
   - Click "Deploy"
   - Koyeb will build and deploy your application

### Telegram Mini App Setup

To use as a Telegram Mini App:

1. Create a bot with [@BotFather](https://t.me/botfather)
2. Get your bot token
3. Update `TELEGRAM_BOT_TOKEN` in `app.py` with your bot token
4. Set up your bot's web app URL in BotFather to point to your Koyeb deployment URL

## Project Structure

```
QuizGeneratorJungle/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── Procfile              # Koyeb deployment configuration
├── templates/            # HTML templates
│   ├── index.html       # Main form page
│   └── quiz.html        # Quiz display page
├── static/              # Static files
│   └── styles.css      # Stylesheet
└── uploads/             # Temporary file storage (gitignored)
```

## Configuration

- **Telegram Bot Token:** Set in `app.py` as `TELEGRAM_BOT_TOKEN`
- **Upload Folder:** Configured in `app.py` (default: `uploads/`)
- **Max File Size:** 16MB (configurable in `app.py`)

## License

MIT License

