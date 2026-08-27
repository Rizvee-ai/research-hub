"""
The web page.

Everything below the text box runs on the server. The browser only
ever receives the finished answer — it never sees the API key, never
talks to Gemini, never touches the database.
"""

import streamlit as st

import db
import answer as answer_mod
import review as review_mod
from config import DOC_TYPES, TOPICS

st.set_page_config(page_title="Research Hub", layout="wide")

st.title("Research Hub")
st.caption("Search across the collection. Every answer shows where it came from.")

tab_ask, tab_browse, tab_review = st.tabs(["Ask", "Browse", "Brief or review"])


# ─── Ask ─────────────────────────────────────────────────────────
with tab_ask:
    question = st.text_input(
        "Ask a question",
        placeholder="What is our approach to psychological safety?",
    )

    if question:
        with st.spinner("Searching the collection…"):
            try:
                text, sources = answer_mod.ask(question)
            except Exception as e:
                st.error(f"Something went wrong: {e}")
                text, sources = None, []

        if text:
            st.markdown(text)

            if sources:
                st.divider()
                st.caption(f"Built from {len(sources)} passages")
                for i, s in enumerate(sources, start=1):
                    name = s["title"] or s["filename"]
                    page = f" · p.{s['page']}" if s["page"] and s["page"] > 1 else ""
                    with st.expander(f"{i}. {name}{page}"):
                        st.write(s["text"])
                        st.caption(s["filename"])


# ─── Browse ──────────────────────────────────────────────────────
with tab_browse:
    st.write("Everything in the collection. No AI involved — this is the record.")

    try:
        rows = db.all_documents()
    except Exception as e:
        st.error(f"Could not reach the database: {e}")
        rows = []

    if not rows:
        st.info("Nothing ingested yet. Run:  python ingest.py")
    else:
        ingested = [r for r in rows if r["status"] == "ingested"]
        excluded = [r for r in rows if r["status"] != "ingested"]

        c1, c2, c3 = st.columns(3)
        c1.metric("Documents", len(ingested))
        c2.metric("Excluded", len(excluded))
        c3.metric("Unchecked", sum(1 for r in ingested if not r["reviewed_by"]))

        st.dataframe(
            [
                {
                    "Title": r["title"] or r["filename"],
                    "Date": r["doc_date"] or "",
                    "Type": r["doc_type"] or "",
                    "Audience": r["audience"] or "",
                    "Topics": ", ".join(r["topics"] or []),
                    "Pages": r["page_count"],
                    "Words": r["word_count"],
                    "Checked": "yes" if r["reviewed_by"] else "",
                }
                for r in ingested
            ],
            use_container_width=True,
            hide_index=True,
        )

        if excluded:
            with st.expander(f"{len(excluded)} document(s) could not be used"):
                for r in excluded:
                    st.write(f"**{r['filename']}** — {r['status']}")


# ─── Brief or review ─────────────────────────────────────────────
with tab_review:
    st.write(
        "These read whole documents rather than passages, so the result "
        "reflects the collection rather than whichever documents happen "
        "to phrase the topic best."
    )

    topic = st.text_input(
        "Topic",
        placeholder="psychological safety in frontline teams",
        key="review_topic",
    )

    c1, c2, c3 = st.columns(3)
    kind = c1.radio("Length", ["brief", "review"], horizontal=True)
    doc_type = c2.selectbox("Only this type", [None] + DOC_TYPES,
                            format_func=lambda x: x or "Any")
    label = c3.selectbox("Only this topic", [None] + TOPICS,
                         format_func=lambda x: x or "Any")

    if st.button("Generate", type="primary") and topic:
        with st.spinner("Reading the documents…"):
            try:
                text, docs = review_mod.generate(
                    topic, kind=kind, doc_type=doc_type, label=label
                )
            except Exception as e:
                st.error(f"Something went wrong: {e}")
                text, docs = None, []

        if text:
            st.markdown(text)
            if docs:
                with st.expander(f"The {len(docs)} documents used"):
                    for d in docs:
                        st.write(f"- {d['title'] or 'Untitled'}")
