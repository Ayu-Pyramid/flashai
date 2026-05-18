import streamlit as st
import openai
import json
import pdfplumber
import io
import sqlite3
from datetime import date, timedelta

st.set_page_config(page_title="FlashAI", page_icon="🧠", layout="centered")

st.markdown("""
<style>
    .main { max-width: 800px; }
    .flashcard {
        background: #fff;
        border: 1px solid #e0e0de;
        border-radius: 16px;
        padding: 2.5rem;
        text-align: center;
        min-height: 200px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        margin: 1rem 0;
    }
    .card-question { font-size: 1.3rem; font-weight: 600; color: #1a1a1a; }
    .card-answer { font-size: 1.1rem; color: #444; line-height: 1.6; }
    .card-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.1em; color: #aaa; margin-bottom: 0.75rem; }
    .score-good { color: #16a34a; font-weight: 600; }
    .score-ok { color: #d97706; font-weight: 600; }
    .score-hard { color: #dc2626; font-weight: 600; }
    div[data-testid="stButton"] button { width: 100%; }
</style>
""", unsafe_allow_html=True)

DB_PATH = "flashcards.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS decks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            difficulty INTEGER DEFAULT 0,
            next_review TEXT DEFAULT CURRENT_DATE,
            review_count INTEGER DEFAULT 0,
            FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()

init_db()

def get_next_review(rating: int, review_count: int) -> str:
    if review_count > 3:
        intervals = {1: 1, 2: 7, 3: 14}
    else:
        intervals = {1: 1, 2: 3, 3: 7}
    return str(date.today() + timedelta(days=intervals.get(rating, 1)))

def generate_cards(text, deck_name, num_cards, difficulty, api_key):
    client = openai.OpenAI(api_key=api_key)
    prompt = f"""You are an expert educator. Generate exactly {num_cards} flashcards from the text below.
Difficulty: {difficulty} (easy=basic recall, medium=understanding, hard=application, mixed=variety)

TEXT:
{text[:4000]}

Respond ONLY with a valid JSON array (no markdown, no backticks):
[{{"question": "...", "answer": "..."}}, ...]

Rules:
- Questions must be clear and specific
- Answers concise but complete (2-4 sentences)
- Cover the most important concepts
- Vary question types (what, why, how, define, compare)"""

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_pdf_text(uploaded_file):
    with pdfplumber.open(io.BytesIO(uploaded_file.read())) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)

def get_decks():
    conn = get_db()
    decks = conn.execute("""
        SELECT d.*, COUNT(c.id) as card_count
        FROM decks d LEFT JOIN cards c ON d.id = c.deck_id
        GROUP BY d.id ORDER BY d.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(d) for d in decks]

def get_cards(deck_id, due_only=False):
    conn = get_db()
    if due_only:
        cards = conn.execute("SELECT * FROM cards WHERE deck_id=? AND next_review<=?", (deck_id, str(date.today()))).fetchall()
    else:
        cards = conn.execute("SELECT * FROM cards WHERE deck_id=?", (deck_id,)).fetchall()
    conn.close()
    return [dict(c) for c in cards]

def save_deck_and_cards(deck_name, cards_data):
    conn = get_db()
    cursor = conn.execute("INSERT INTO decks (name, description) VALUES (?,?)",
                          (deck_name, f"Generated · {len(cards_data)} cards"))
    deck_id = cursor.lastrowid
    for card in cards_data:
        conn.execute("INSERT INTO cards (deck_id, question, answer) VALUES (?,?,?)",
                     (deck_id, card["question"], card["answer"]))
    conn.commit()
    conn.close()
    return deck_id

def update_card_review(card_id, rating, review_count):
    next_review = get_next_review(rating, review_count)
    conn = get_db()
    conn.execute("UPDATE cards SET review_count=review_count+1, next_review=?, difficulty=? WHERE id=?",
                 (next_review, rating, card_id))
    conn.commit()
    conn.close()

def delete_deck(deck_id):
    conn = get_db()
    conn.execute("DELETE FROM cards WHERE deck_id=?", (deck_id,))
    conn.execute("DELETE FROM decks WHERE id=?", (deck_id,))
    conn.commit()
    conn.close()

# Session state init
for key, val in {
    "api_key": "", "tab": "generate", "study_deck": None,
    "study_cards": [], "card_index": 0, "flipped": False,
    "session_results": {"hard": 0, "ok": 0, "easy": 0}, "study_done": False
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

# Header
st.title("🧠 FlashAI")
st.caption("Generate flashcards from any text or PDF · Study with spaced repetition")
st.divider()

# API Key
with st.sidebar:
    st.header("⚙️ Settings")
    api_key = st.text_input("OpenAI API Key", type="password", value=st.session_state.api_key, placeholder="sk-...")
    if api_key:
        st.session_state.api_key = api_key
        st.success("API key set ✅")
    st.caption("Get your key at platform.openai.com/api-keys")
    st.divider()
    st.header("📚 Navigation")
    if st.button("✨ Generate", use_container_width=True):
        st.session_state.tab = "generate"
        st.rerun()
    if st.button("📚 My Decks", use_container_width=True):
        st.session_state.tab = "decks"
        st.rerun()

# ─── GENERATE TAB ───
if st.session_state.tab == "generate":
    st.subheader("✨ Generate Flashcards")
    st.caption("Paste text or upload a PDF — AI generates flashcards instantly.")

    col1, col2, col3 = st.columns(3)
    with col1:
        deck_name = st.text_input("Deck name", placeholder="e.g. Machine Learning Basics")
    with col2:
        num_cards = st.selectbox("Number of cards", [5, 10, 15, 20], index=1)
    with col3:
        difficulty = st.selectbox("Difficulty", ["mixed", "easy", "medium", "hard"])

    uploaded_file = st.file_uploader("Upload PDF (optional)", type=["pdf"])
    text = ""
    if uploaded_file:
        with st.spinner("Reading PDF..."):
            try:
                text = extract_pdf_text(uploaded_file)
                st.success(f"✅ PDF loaded — {len(text)} characters")
            except Exception as e:
                st.error(f"PDF read failed: {e}")

    text_input = st.text_area("Text content", value=text, height=200,
                               placeholder="Paste your notes, article, textbook content here...")

    if st.button("✨ Generate Flashcards", type="primary", use_container_width=True):
        if not st.session_state.api_key:
            st.error("Enter your OpenAI API key in the sidebar first.")
        elif not text_input.strip():
            st.error("Paste some text or upload a PDF first.")
        elif not deck_name.strip():
            st.error("Give your deck a name.")
        else:
            with st.spinner(f"Generating {num_cards} flashcards with GPT-4o..."):
                try:
                    cards_data = generate_cards(text_input, deck_name, num_cards, difficulty, st.session_state.api_key)
                    deck_id = save_deck_and_cards(deck_name, cards_data)
                    st.success(f"✅ Created **{deck_name}** with {len(cards_data)} cards!")
                    st.balloons()
                    with st.expander("Preview cards"):
                        for i, card in enumerate(cards_data):
                            st.markdown(f"**Q{i+1}:** {card['question']}")
                            st.markdown(f"*A: {card['answer']}*")
                            st.divider()
                    if st.button("Go to My Decks →"):
                        st.session_state.tab = "decks"
                        st.rerun()
                except json.JSONDecodeError:
                    st.error("GPT returned invalid JSON. Try again.")
                except Exception as e:
                    st.error(f"Error: {e}")

# ─── DECKS TAB ───
elif st.session_state.tab == "decks":
    st.subheader("📚 My Decks")
    decks = get_decks()

    if not decks:
        st.info("No decks yet. Generate your first one! ✨")
    else:
        for deck in decks:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"**{deck['name']}**")
                    st.caption(f"{deck['card_count']} cards · {deck['created_at'][:10]}")
                with col2:
                    if st.button("🗑", key=f"del_{deck['id']}", help="Delete deck"):
                        delete_deck(deck['id'])
                        st.rerun()

                c1, c2 = st.columns(2)
                with c1:
                    if st.button(f"🎯 Study", key=f"study_{deck['id']}", use_container_width=True, type="primary"):
                        cards = get_cards(deck['id'])
                        if not cards:
                            st.warning("No cards in this deck.")
                        else:
                            st.session_state.study_deck = deck
                            st.session_state.study_cards = cards
                            st.session_state.card_index = 0
                            st.session_state.flipped = False
                            st.session_state.study_done = False
                            st.session_state.session_results = {"hard": 0, "ok": 0, "easy": 0}
                            st.session_state.tab = "study"
                            st.rerun()
                with c2:
                    due = get_cards(deck['id'], due_only=True)
                    if st.button(f"📅 Due today ({len(due)})", key=f"due_{deck['id']}", use_container_width=True):
                        if not due:
                            st.toast("No cards due today!")
                        else:
                            st.session_state.study_deck = deck
                            st.session_state.study_cards = due
                            st.session_state.card_index = 0
                            st.session_state.flipped = False
                            st.session_state.study_done = False
                            st.session_state.session_results = {"hard": 0, "ok": 0, "easy": 0}
                            st.session_state.tab = "study"
                            st.rerun()

# ─── STUDY TAB ───
elif st.session_state.tab == "study":
    deck = st.session_state.study_deck
    cards = st.session_state.study_cards
    idx = st.session_state.card_index

    if st.button("← Back to Decks"):
        st.session_state.tab = "decks"
        st.rerun()

    if st.session_state.study_done or idx >= len(cards):
        st.subheader("✅ Session Complete!")
        r = st.session_state.session_results
        total = r["hard"] + r["ok"] + r["easy"]
        st.markdown(f"**{total} cards reviewed**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("😓 Hard", r["hard"])
        with c2:
            st.metric("😐 OK", r["ok"])
        with c3:
            st.metric("😊 Easy", r["easy"])
        if st.button("Study Again", use_container_width=True):
            st.session_state.card_index = 0
            st.session_state.flipped = False
            st.session_state.study_done = False
            st.session_state.session_results = {"hard": 0, "ok": 0, "easy": 0}
            st.rerun()
    else:
        card = cards[idx]
        st.markdown(f"**{deck['name']}** · Card {idx+1} of {len(cards)}")
        progress = idx / len(cards)
        st.progress(progress)

        st.markdown(f"""
        <div class="flashcard">
            <div class="card-label">{"Answer" if st.session_state.flipped else "Question"}</div>
            <div class="{'card-answer' if st.session_state.flipped else 'card-question'}">
                {card['answer'] if st.session_state.flipped else card['question']}
            </div>
        </div>
        """, unsafe_allow_html=True)

        if not st.session_state.flipped:
            if st.button("👁 Reveal Answer", use_container_width=True, type="primary"):
                st.session_state.flipped = True
                st.rerun()
        else:
            st.caption("How well did you know this?")
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("😓 Hard\nReview tomorrow", use_container_width=True):
                    update_card_review(card['id'], 1, card['review_count'])
                    st.session_state.session_results["hard"] += 1
                    st.session_state.card_index += 1
                    st.session_state.flipped = False
                    st.rerun()
            with c2:
                if st.button("😐 OK\nReview in 3 days", use_container_width=True):
                    update_card_review(card['id'], 2, card['review_count'])
                    st.session_state.session_results["ok"] += 1
                    st.session_state.card_index += 1
                    st.session_state.flipped = False
                    st.rerun()
            with c3:
                if st.button("😊 Easy\nReview in 7 days", use_container_width=True):
                    update_card_review(card['id'], 3, card['review_count'])
                    st.session_state.session_results["easy"] += 1
                    st.session_state.card_index += 1
                    st.session_state.flipped = False
                    st.rerun()
