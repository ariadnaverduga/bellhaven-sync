"""Local review app: see each proposed change with its evidence, approve or reject.

Run with:  streamlit run app.py
"""
import os
import json
import streamlit as st
from dotenv import load_dotenv
import store
from apply import apply_proposal

load_dotenv()
CRM_BROWSER = f"https://analyst-assessment-production.up.railway.app/crm/{os.getenv('BH_TOKEN')}/accounts"

st.set_page_config(page_title="Bellhaven CRM Review", layout="wide")
st.title("Bellhaven → CRM review queue")
st.caption("Nothing is written to the CRM until you click Approve.")

# Show the result of the last click (survives the page refresh)
if "flash" in st.session_state:
    kind, msg = st.session_state.pop("flash")
    (st.success if kind == "ok" else st.error)(msg)

tab_queue, tab_history = st.tabs(["Review queue", "History"])

with tab_queue:
    rows = store.list_proposals(["pending", "failed"])
    kinds = sorted({r["kind"] for r in rows})
    chosen = st.multiselect("Filter by type", kinds, default=kinds)
    rows = [r for r in rows if r["kind"] in chosen]
    st.write(f"**{len(rows)}** proposals waiting for review")

    for r in rows:
        p = r["payload"]
        with st.container(border=True):
            st.subheader(p["title"])
            st.caption(f"{p['kind']}  ·  key: {p['key'][:80]}")

            if r["status"] == "failed":
                st.error(f"Last attempt failed: {json.loads(r['result']).get('error')}")

            st.dataframe([{"Field": d["field"], "Current": str(d["current"]), "Proposed": str(d["proposed"])}
                          for d in p["diff"]], hide_index=True)

            with st.expander("Evidence", expanded=True):
                for line in p["evidence"]:
                    # Escape $ so Streamlit doesn't render dollar amounts as math
                    st.markdown("- " + line.replace("$", "\\$"))
            if p["account_id"]:
                st.markdown(f"[Open account in CRM browser]({CRM_BROWSER}/{p['account_id']})")

            c1, c2, c3 = st.columns([1, 1, 4])
            reason = c3.text_input("Reason", key=f"reason-{p['key']}",
                                   placeholder="Reason (optional, saved with the decision)",
                                   label_visibility="collapsed")

            if c1.button("✅ Approve", key=f"ok-{p['key']}", type="primary"):
                prev = json.loads(r["result"]) if r["status"] == "failed" and r["result"] else None
                ok, state, err = apply_proposal(p, prev)
                result = json.dumps({**state, "error": err, "reason": reason})
                store.decide(p["key"], "approved" if ok else "failed", result)
                link = f" · [Open in CRM browser]({CRM_BROWSER}/{p['account_id']})" if p["account_id"] else ""
                st.session_state["flash"] = ("ok", f"Applied: {p['title']}{link}") if ok \
                    else ("err", f"Failed: {p['title']} → {err}")
                st.rerun()

            if c2.button("❌ Reject", key=f"no-{p['key']}"):
                store.decide(p["key"], "rejected", json.dumps({"reason": reason}))
                st.session_state["flash"] = ("ok", f"Rejected: {p['title']}")
                st.rerun()

with tab_history:
    done = store.list_proposals(["approved", "rejected", "superseded"])
    st.write(f"**{len(done)}** decided")
    st.dataframe(
        [{"Decided": r["decided_at"], "Status": r["status"], "Type": r["kind"], "Title": r["title"],
          "CRM": f"{CRM_BROWSER}/{r['account_id']}" if r["account_id"] else None,
          "Details": r["result"]} for r in done],
        hide_index=True,
        column_config={"CRM": st.column_config.LinkColumn("CRM", display_text="Open")},
    )