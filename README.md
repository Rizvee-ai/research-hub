# AI Research Hub

Search across a collection of documents. Every answer shows the
document and page it came from.

---

## Setting up — Windows

Open **Command Prompt** in the project folder and run these in order.

### 1. Create a Python environment

```
python -m venv .venv
.venv\Scripts\activate
```

Your prompt should now start with `(.venv)`.

### 2. Install what it needs

```
pip install -r requirements.txt
```

Two or three minutes. `sentence-transformers` is the large one.

### 3. Add your credentials

Copy `.env.example` to a new file called `.env`:

```
copy .env.example .env
```

Open `.env` in Notepad and paste in your two values:

```
GEMINI_API_KEY=AQ.Ab8...your key...
DATABASE_URL=postgresql://postgres:YourPassword@db.xxxx.supabase.co:5432/postgres
```

The `.env` file is already in `.gitignore`, so it will never be
committed.

### 4. Create the tables

Open the Supabase **SQL Editor**, paste the whole of `schema.sql`,
and run it. It should say *Success. No rows returned.*

### 5. Put some documents in

Make a folder called `documents` in the project folder and copy a
handful of PDFs or Word files into it. Start with about ten.

---

## Running it

### Ingest the documents

```
python ingest.py
```

It prints a line per file. Safe to stop and re-run — anything already
processed is skipped, so an interrupted run picks up where it stopped.

The first run downloads the embedding model, about 90 MB, once.

### Ask a question from the command line

```
python answer.py what is our approach to psychological safety
```

### Open the web page

```
streamlit run app.py
```

It opens in your browser at `localhost:8501`.

---

## What each file does

| File | What it does |
| --- | --- |
| `config.py` | Settings. The first three cannot change later |
| `schema.sql` | The two tables and their indexes |
| `db.py` | Everything that touches the database |
| `reader.py` | PDF and Word into text, with page numbers |
| `chunker.py` | Text into passages, within page boundaries |
| `labeller.py` | Gemini fills in a record for each document |
| `embedder.py` | Text into numbers, on this machine |
| `ingest.py` | Ties the above together, one file at a time |
| `search.py` | Meaning and keyword search, merged |
| `answer.py` | Passages into a cited answer |
| `review.py` | Whole documents into a brief or review |
| `app.py` | The web page |

---

## Two things worth knowing

**The settings at the top of `config.py` are fixed.** The embedding
model and the chunk sizes have to stay as they are. Passages and
questions must be turned into numbers by the same model, in the same
way, or the comparison is meaningless — and it fails quietly, giving
plausible but wrong results rather than an error. Changing them means
re-processing every document.

**The model never writes a citation.** It is shown numbered passages
and nothing else — no titles, no authors, no dates. Every reference in
a finished answer is built by `answer.py` from the database rows that
produced those passages. That makes an invented source impossible
rather than merely unlikely.

---

## If something goes wrong

| What you see | What it means |
| --- | --- |
| `GEMINI_API_KEY is not set` | The `.env` file is missing or misnamed. It must be `.env`, not `.env.txt` |
| `could not translate host name` | The `DATABASE_URL` is wrong, or `[YOUR-PASSWORD]` was never replaced |
| `password authentication failed` | Wrong database password, or it contains symbols that need escaping in a URL |
| `relation "documents" does not exist` | `schema.sql` has not been run in Supabase yet |
| `429` or `RESOURCE_EXHAUSTED` | Free-tier rate limit. Wait, then re-run `ingest.py` — it skips what is done |
| A document is excluded | Check the Browse tab. The reason is recorded against it |
