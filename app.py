"""Academic Weapon: entry point. Run with `streamlit run app.py`."""

import streamlit as st

from services import config, db
from ui import account

config.load()
st.set_page_config(page_title="Academic Weapon", page_icon="🎓", layout="wide")

email = account.require_login()       # stops here until signed in (if Google sign-in is set up)
sync = account.start_sync(email)      # pull from Google Drive once per session

with db.open_db(config.db_path()) as conn:
    db.init_db(conn)                  # no-op when the schema already exists
    tbd = db.count_tbd_items(conn)

pages = [
    st.Page("pages/dashboard.py", title="Dashboard", icon="📋", default=True),
    st.Page("pages/import.py", title="Import Syllabus", icon="📥"),
    st.Page("pages/tbd.py", title=f"TBD ({tbd})" if tbd else "TBD", icon="❓"),
    st.Page("pages/rank.py", title="Rank", icon="🏆"),
    st.Page("pages/experimental.py", title="Experimental Rank", icon="🧪"),
    st.Page("pages/settings.py", title="Settings", icon="⚙️"),
]
nav = st.navigation(pages)

with st.sidebar:
    st.metric("Items in TBD", tbd)
    if not config.has_api_key():
        st.warning("ANTHROPIC_API_KEY is not set. Add it to .env to enable syllabus import.")
    account.sidebar_status(email, sync)

try:
    nav.run()
finally:
    account.push_changes(sync)        # upload to Google Drive if this run changed anything
