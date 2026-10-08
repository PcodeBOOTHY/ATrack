"""Academic Weapon: entry point. Run with `streamlit run app.py`."""

import streamlit as st

from core.tiers import tier_for
from core.timeutil import now_utc
from services import config, db, rating
from ui import account, reward

config.load()
st.set_page_config(page_title="Academic Weapon", page_icon="🎓", layout="wide")

email = account.require_login()       # stops here until signed in (if Google sign-in is set up)
sync = account.start_sync(email)      # pull from Google Drive once per session

with db.open_db(config.db_path()) as conn:
    db.init_db(conn)                  # no-op when the schema already exists
    forfeits = rating.forfeit_overdue(conn, now_utc())  # pending items > 48 h past due
    tbd = db.count_tbd_items(conn)
    current, _ = rating.current_rating(conn, "standard")

if forfeits:
    total = sum(f.standard.delta for f in forfeits)
    names = ", ".join(f.title for f in forfeits[:3]) + (" …" if len(forfeits) > 3 else "")
    st.toast(f"{len(forfeits)} overdue item(s) passed the 48 h limit and were forfeited ({total:+d}): {names}",
             icon="⏰")
    demoted = forfeits[-1].standard.tier_after.name
    if forfeits[0].standard.tier_before != forfeits[-1].standard.tier_after:
        st.toast(f"Your rank is now {demoted}. A few on-time items will bring it back.", icon="💪")

pages = [
    st.Page("views/dashboard.py", title="Dashboard", icon="📋", default=True),
    st.Page("views/import.py", title="Import Syllabus", icon="📥"),
    st.Page("views/tbd.py", title=f"TBD ({tbd})" if tbd else "TBD", icon="❓"),
    st.Page("views/rank.py", title="Rank", icon="🏆"),
    st.Page("views/experimental.py", title="Experimental Rank", icon="🧪"),
    st.Page("views/settings.py", title="Settings", icon="⚙️"),
]
nav = st.navigation(pages)

with st.sidebar:
    tier = tier_for(current)
    st.markdown(f"### {tier.badge} {tier.name}  \n<span style='opacity:.7'>Rating {current}</span>",
                unsafe_allow_html=True)
    st.metric("Items in TBD", tbd)
    if not config.has_api_key():
        st.warning("ANTHROPIC_API_KEY is not set. Add it to .env to enable syllabus import.")
    account.sidebar_status(email, sync)

account.unsaved_banner()             # online only: Drive save failed
reward.show_pending_reward()         # reward screen right after a completion

try:
    nav.run()
finally:
    account.push_changes(sync)        # upload to Google Drive if this run changed anything
