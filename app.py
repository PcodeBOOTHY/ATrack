"""Academic Weapon: entry point. Run with `streamlit run app.py`."""

import streamlit as st

from services import config, db

config.load()
st.set_page_config(page_title="Academic Weapon", page_icon="🎓", layout="wide")


@st.cache_resource
def _init_database() -> str:
    """Create the schema once per server process."""
    path = config.db_path()
    with db.open_db(path) as conn:
        db.init_db(conn)
    return str(path)


_init_database()

pages = [
    st.Page("pages/dashboard.py", title="Dashboard", icon="📋", default=True),
    st.Page("pages/import.py", title="Import Syllabus", icon="📥"),
    st.Page("pages/tbd.py", title="TBD", icon="❓"),
    st.Page("pages/rank.py", title="Rank", icon="🏆"),
    st.Page("pages/experimental.py", title="Experimental Rank", icon="🧪"),
    st.Page("pages/settings.py", title="Settings", icon="⚙️"),
]
nav = st.navigation(pages)

with st.sidebar:
    with db.open_db(config.db_path()) as conn:
        tbd = db.count_tbd_items(conn)
    st.metric("Items in TBD", tbd)
    if not config.has_api_key():
        st.warning("ANTHROPIC_API_KEY is not set. Add it to .env to enable syllabus import.")

nav.run()
