# url-shortener

A minimal Flask-based URL shortener with SQLite storage, temporary links, and a small privacy-focused frontend.

## Features

- Create permanent short links
- Deduplicate permanent links after URL normalization
- Create temporary short links with selectable expiration
- Redirect via short codes stored in SQLite
- Block private, local, and internal hosts
- Block embedded credentials in URLs
- Clean common tracking parameters before storing links
- Minimal frontend with dark mode and a separate privacy-policy page
- Custom 404 page for unknown or expired links

## Tech Stack

- Flask
- SQLite

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Initialize the database:

   ```bash
   python3 init_db.py
   ```

3. Start the app:

   ```bash
   python3 app.py
   ```

## Docker

Build the image:

```bash
docker build -t url-shortener .
```

Run the container with a persistent SQLite volume:

```bash
docker run -d \
  --name url-shortener \
  -p 5000:5000 \
  -v url_shortener_data:/data \
  url-shortener
```

Optional environment variables:

- `PORT` sets the application port inside the container
- `DATABASE_PATH` sets the SQLite file location and defaults to `/data/urls.db`

## How It Works

- Permanent links are deduplicated, so the same normalized URL gets the same short code.
- Temporary links are always created as new entries and expire after the selected duration.
- Expired links return `404` and are removed when accessed.

## URL Cleaning

Before storing a URL, the app normalizes and cleans it:

- lowercases scheme and hostname
- removes default ports like `:80` and `:443`
- removes fragments
- strips common tracking parameters such as `utm_*`, `fbclid`, and `gclid`

## Security Rules

The app rejects:

- invalid URLs
- URLs longer than `10,000` characters
- URLs with embedded credentials
- private or internal destinations such as `localhost`, `127.0.0.1`, or `192.168.x.x`

## Files

- `app.py` contains the Flask app, routing, URL validation, normalization, and redirect logic
- `init_db.py` initializes or migrates the SQLite schema
- `templates/index.html` is the main frontend
- `templates/privacy.html` contains the privacy-policy page
- `templates/404.html` is the custom not-found page
