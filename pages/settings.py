import streamlit as st

from services import config, db

st.title("⚙️ Settings")

st.subheader("Configuration")
st.write(f"**Model:** `{config.anthropic_model()}`")
st.write(f"**API key:** {'configured ✅' if config.has_api_key() else 'missing ❌'}")
st.write(f"**Database:** `{config.db_path()}`")

with db.open_db(config.db_path()) as conn:
    st.subheader("Database contents")
    st.table(db.table_counts(conn))

st.info("Coming later: export data to JSON and reset ratings.")
