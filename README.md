# FlashAI — AI Flashcard Generator

Generate flashcards from any text or PDF using GPT-4o. Study with spaced repetition.

**Stack:** Streamlit · OpenAI GPT-4o · SQLite · pdfplumber

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Cloud (free)
1. Push to GitHub
2. Go to share.streamlit.io
3. Select repo → set main file as `app.py`
4. Deploy — get a live URL instantly

## Features
- Paste text or upload PDF → GPT-4o generates flashcards
- Choose number of cards and difficulty
- Flip cards to reveal answers
- Rate: Hard / OK / Easy → spaced repetition scheduling
- Due today mode
- Multiple decks, delete decks
- Session summary

## Resume line
> Built an AI flashcard generator with spaced repetition using Streamlit, GPT-4o, and SQLite — supports PDF upload and adaptive review scheduling. Deployed on Streamlit Cloud.
