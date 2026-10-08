import streamlit as st

from services import config, db
from ui import account

st.title("⚙️ Settings")

st.subheader("Configuration")
st.write(f"**Model:** `{config.anthropic_model()}`")
st.write(f"**API key:** {'configured ✅' if config.has_api_key() else 'missing ❌'}")
st.write(f"**Database:** `{config.db_path()}`")

st.subheader("Account")
if account.auth_configured():
    st.write(f"**Google sign-in:** on · allowed account `{config.allowed_email() or 'not set'}`")
    st.write("Data is saved to the hidden app folder in your Google Drive after every change.")
    backups = sorted((config.db_path().parent / "backups").glob("*.db"))
    if backups:
        st.caption(f"{len(backups)} backup(s) from sync conflicts in `data/backups/`.")
else:
    st.write("**Google sign-in:** not set up. Data is stored on this computer only. "
             "See the README section *Google sign-in and Drive sync* to turn it on.")

with db.open_db(config.db_path()) as conn:
    st.subheader("Database contents")
    st.table(db.table_counts(conn))

st.info("Coming later: export data to JSON and reset ratings.")
