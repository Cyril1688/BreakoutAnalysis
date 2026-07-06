# News Summary Module

This module provides functionality to extract and summarize news articles from URLs using natural language processing.

## Overview

The News Summary module consists of two main components:

1. **Content Extractor**: Extracts the main content from news article URLs using the newspaper3k library.
2. **Article Summarizer**: Summarizes the extracted content using a pre-trained language model (DistilBART).

## Features

- Extracts article content from URLs
- Summarizes articles using a pre-trained language model
- Handles errors gracefully with fallback mechanisms
- Provides a simple API for integration with other modules

## Usage

### Basic Usage

```python
from src.newssummary.summarizer import summarize_article

# Summarize an article from a URL
result = summarize_article("https://example.com/news-article")

if result['success']:
    print(f"Summary: {result['summary']}")
else:
    print(f"Error: {result['error']}")
```

### Using Browser Headers and Cookies

For articles behind login walls, you can provide browser headers and cookies to access the content:

```python
# Define browser headers and cookies
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

cookies = {
    "session_id": "your_session_id_here"
}

# Summarize an article with headers and cookies
result = summarize_article("https://example.com/news-article", headers=headers, cookies=cookies)
```

### Integration with News Collector

The News Summary module is integrated with the News Collector module. When the `summarize_articles` setting is enabled in the configuration, the News Collector will automatically summarize articles and include the summaries in the output.

To enable article summarization, set the `summarize_articles` flag to `true` in the `config.json` file:

```json
{
  "news_collector": {
    "back_hours": 24,
    "summarize_articles": true,
    "browser_headers": {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.5"
    },
    "browser_cookies": {
      "session_id": "YOUR_SESSION_ID_HERE"
    }
  }
}
```

The `browser_headers` and `browser_cookies` fields are optional. If provided, they will be used to access articles that might be behind login walls.

## Components

### Content Extractor

The content extractor uses the newspaper3k library to download and parse articles from URLs. It handles various error cases and provides a clean interface for extracting article content.

### Article Summarizer

The article summarizer uses a pre-trained language model (DistilBART) to generate concise summaries of article content. It includes fallback mechanisms for handling errors and provides options for controlling the length and style of the generated summaries.

## Dependencies

- newspaper3k: For article extraction
- transformers: For the language model
- torch: Required by transformers

## Handling Login-Protected Articles

Some news articles may be behind login walls. The module can detect this and will provide an appropriate message. To access these articles, you can:

1. Configure browser headers and cookies in the `config.json` file
2. Get your session cookies by logging into the news site in your browser and extracting the cookies
3. Add these cookies to the `browser_cookies` section in the configuration

For security reasons, never share your session cookies or include them in public repositories.

## Testing

You can test the article summarizer using the provided test script:

```bash
python -m src.test_article_summarizer --url https://example.com/news-article
```

This will extract and summarize the article at the specified URL and print the result.
