import streamlit as st

from services import config, db
from ui import rank

st.title("🏆 Rank")

with db.open_db(config.db_path()) as conn:
    left, right = st.columns(2)
    with left:
        rank.summary(conn, "standard", "Standard")
    with right:
        rank.summary(conn, "experimental", "🧪 Experimental: AI-estimated difficulty")

    standard_tab, experimental_tab = st.tabs(["Standard", "🧪 Experimental"])
    with standard_tab:
        rank.full_panel(conn, "standard")
    with experimental_tab:
        st.caption("Experimental: AI-estimated difficulty. Separate from your standard rank. "
                   "Items join it once their assignment file is rated on the Experimental Rank page.")
        rank.full_panel(conn, "experimental")

st.caption("Win = done on time (bonus up to ×1.5 for finishing up to 7 days early) · "
           "Half = up to 24 h late · Loss = more than 24 h late or not done 48 h after the deadline.")
