import streamlit as st

st.title("📋 Dashboard")
st.info("Coming in Phase 3: By Priority, By Type, By Course, This Week and Completed views.")
tabs = st.tabs(["By Priority", "By Type", "By Course", "This Week", "Completed"])
for tab in tabs:
    with tab:
        st.caption("No items yet. Import a syllabus to get started.")
