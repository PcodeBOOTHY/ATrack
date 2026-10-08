import streamlit as st

from core.timeutil import now_utc
from services import config, db, rating
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

st.subheader("Export")
with db.open_db(config.db_path()) as conn:
    export = rating.export_all(conn)
st.download_button("Download all data (JSON)", export, width="content",
                   file_name=f"academic-weapon-{now_utc().strftime('%Y-%m-%d')}.json", mime="application/json")

st.subheader("Reset ratings")
st.caption("Deletes match history so the rating starts again at 1000. Your items stay as they are; "
           "items already completed won't be re-rated.")
with st.form("reset"):
    which = st.radio("Which rating?", ["Standard", "Experimental", "Both"], horizontal=True)
    confirm = st.text_input("Type RESET to confirm")
    if st.form_submit_button("Reset ratings", type="primary"):
        if confirm.strip() != "RESET":
            st.error("Type RESET (in capitals) to confirm.")
        else:
            modes = {"Standard": ("standard",), "Experimental": ("experimental",),
                     "Both": ("standard", "experimental")}[which]
            with db.open_db(config.db_path()) as conn:
                removed = rating.reset_ratings(conn, modes)
            st.success(f"Reset done. {removed} match(es) removed.")
