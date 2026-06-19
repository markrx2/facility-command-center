import streamlit as st
import sqlite3
import time
import requests
from datetime import datetime, timedelta

# --- 1. PAGE SETUP & COMPONENT STYLING ---
st.set_page_config(page_title="Facility Command Hub", page_icon="⏱️", layout="wide")
st.markdown("""
    <style>
    .main { background-color: #fafafa; }
    div[data-testid="stExpander"] { border: 1px solid #e0e0e0; background-color: #ffffff; border-radius: 8px; }
    h3 { margin-top: 15px !important; color: #1e293b; font-weight: 700; }
    .stButton>button { border-radius: 6px; }
    </style>
""", unsafe_allow_html=True)

# --- 2. DATABASE SETUP (Shared Persistent Multi-User Matrix) ---
def init_shared_db():
    conn = sqlite3.connect("shared_facility_matrix.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_roster (
            dept_prefix TEXT, tech_name TEXT, PRIMARY KEY (dept_prefix, tech_name)
        )
    """)
    for dept in ["data_entry_slots", "call_center_slots", "shipping_slots", "fill_slots"]:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {dept} (
                log_date TEXT, tech_name TEXT, slot_id INTEGER, queue TEXT, goal TEXT,
                start_time TEXT, input_number INTEGER, tech_notified INTEGER DEFAULT 0,
                supervisor_notified INTEGER DEFAULT 0, submitted INTEGER DEFAULT 0,
                PRIMARY KEY (log_date, tech_name, slot_id)
            )
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_checklist (
            log_date TEXT PRIMARY KEY, rejection_queue TEXT DEFAULT 'Pending',
            pa_queue TEXT DEFAULT 'Pending', untransmitted_claims TEXT DEFAULT 'Pending',
            future_bill TEXT DEFAULT 'Pending', data_re_entry TEXT DEFAULT 'Pending',
            reminder_time TEXT DEFAULT '16:00', supervisor_escaped INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn

conn = init_shared_db()
cursor = conn.cursor()
CURRENT_DATE = datetime.now().strftime("%Y-%m-%d")

# --- 3. GOOGLE CHAT WEBHOOK DISPATCHER ENGINE ---
def dispatch_real_time_alert(message_body):
    """Sends a real-time notification directly to your Google Chat Space."""
    try:
        if "google_chat" in st.secrets:
            url = st.secrets["google_chat"]["webhook_url"]
            payload = {"text": message_body}
            response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
            return response.status_code == 200
    except Exception as e:
        st.sidebar.error(f"Google Chat Node Warning: {str(e)}")
    return False

# --- 4. RENDERING ENGINE FOR WORKER GRID ROWS ---
def render_synchronized_matrix(db_table, goals_dict, prefix, dept_label):
    cursor.execute("SELECT tech_name FROM global_roster WHERE dept_prefix=?", (prefix,))
    active_roster = [row[0] for row in cursor.fetchall()]
        
    with st.expander(f"➕ Manage Live {dept_label} On-Duty Roster"):
        col_in, col_bt = st.columns([3, 1])
        with col_in:
            new_worker = st.text_input("Enter Employee Name:", key=f"add_input_{prefix}").strip()
        with col_bt:
            st.markdown("<div style='padding-top:24px;'></div>", unsafe_allow_html=True)
            if st.button("Add to Floor", key=f"add_btn_{prefix}", use_container_width=True) and new_worker:
                if new_worker not in active_roster:
                    cursor.execute("INSERT OR IGNORE INTO global_roster (dept_prefix, tech_name) VALUES (?, ?)", (prefix, new_worker))
                    conn.commit()
                    st.rerun()

    for worker in active_roster:
        st.subheader(f"👤 TECHNICIAN: {worker.upper()}")
        cols = st.columns(4)
        
        for slot_num in range(1, 5):
            with cols[slot_num - 1]:
                with st.container(border=True):
                    st.markdown(f"**🕒 Slot {slot_num}** ({((slot_num-1)*2)+1}-{slot_num*2} Hrs)")
                    cursor.execute(f"SELECT * FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                    slot_row = cursor.fetchone()
                    
                    if not slot_row:
                        chosen_q = st.selectbox("Assign Queue:", options=list(goals_dict.keys()), key=f"q_{prefix}_{worker}_{slot_num}")
                        st.caption(f"🎯 Target: {goals_dict[chosen_q]}")
                        if st.button("🚀 Start Clock", key=f"str_{prefix}_{worker}_{slot_num}", use_container_width=True):
                            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            cursor.execute(f"INSERT INTO {db_table} (log_date, tech_name, slot_id, queue, goal, start_time) VALUES (?, ?, ?, ?, ?, ?)", (CURRENT_DATE, worker, slot_num, chosen_q, goals_dict[chosen_q], now_str))
                            conn.commit()
                            st.rerun()
                    else:
                        _, _, _, db_queue, db_goal, db_start, db_input, db_t_not, db_s_not, db_sub = slot_row
                        st.markdown(f"Queue: `{db_queue}`")
                        
                        start_time = datetime.strptime(db_start, "%Y-%m-%d %H:%M:%S")
                        end_time = start_time + timedelta(hours=2)
                        escalation_time = end_time + timedelta(minutes=10)
                        current_now = datetime.now()
                        
                        if current_now < end_time and not db_sub:
                            rem = end_time - current_now
                            h, r = divmod(rem.seconds, 3600)
                            m, s = divmod(r, 60)
                            st.metric(label="⏳ Time Remaining", value=f"{int(h):02d}:{int(m):02d}:{int(s):02d}")
                            st.progress(1.0 - (rem.total_seconds() / 7200.0))
                            time.sleep(0.5)
                            st.rerun()
                        elif not db_sub:
                            st.error("🛑 Timer Expired!")
                            if db_t_not == 0:
                                dispatch_real_time_alert(f"⚠️ TIMER ALERT: {worker} has reached zero on {dept_label} Slot {slot_num} without submitted metrics.")
                                cursor.execute(f"UPDATE {db_table} SET tech_notified=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                            if current_now < escalation_time:
                                grace = escalation_time - current_now
                                gm, gs = divmod(grace.seconds, 60)
                                st.warning(f"⚠️ Escalation in: {int(gm):02d}:{int(gs):02d}")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                if db_s_not == 0:
                                    dispatch_real_time_alert(f"🚨 CRITICAL ESCALATION: {worker} missed the metrics window for {dept_label} Slot {slot_num}. Immediate attention required.")
                                    cursor.execute(f"UPDATE {db_table} SET supervisor_notified=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                    conn.commit()
                                st.error("🚨 Supervisor alert sent to Google Chat.")
                        
                        if not db_sub:
                            val = st.number_input("Log Production Volume:", min_value=0, step=1, value=None, key=f"num_{prefix}_{worker}_{slot_num}")
                            if st.button("Submit Metrics", key=f"sub_{prefix}_{worker}_{slot_num}", type="primary", use_container_width=True) and val is not None:
                                cursor.execute(f"UPDATE {db_table} SET input_number=?, submitted=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (val, CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.rerun()
                        else:
                            st.success(f"✅ Logged Units: **{db_input}**")
                            if st.button("🔄 Reset Slot", key=f"rst_{prefix}_{worker}_{slot_num}", use_container_width=True):
                                cursor.execute(f"DELETE FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.rerun()

# --- 5. CORPORATE CONFIGURATIONS ---
GOALS = {
    "de": {"Queue Alpha - Tier 1": "15 tickets", "Queue Beta - Network Ops": "5 alerts"},
    "cc": {"Inbound Support Line": "20 calls", "Outbound Follow-ups": "15 checks"},
    "sh": {"Standard Ground Sorting": "40 orders", "Priority/Overnight Air": "20 shipments"},
    "fi": {"Automated Dispensing": "10 cells", "Manual Counter Line": "50 fills"}
}

st.title("⏱️ Enterprise Facility Command Center")
tab_de, tab_cc, tab_sh, tab_fi, tab_analytics = st.tabs([
    "💻 Data Entry Line", "📞 Call Center Desk", "📦 Shipping Floor", "🧪 Fill Department", "📊 Cumulative Analytics"
])

with tab_de: render_synchronized_matrix("data_entry_slots", GOALS["de"], "de", "Data Entry")
with tab_cc: render_synchronized_matrix("call_center_slots", GOALS["cc"], "cc", "Call Center")
with tab_sh: render_synchronized_matrix("shipping_slots", GOALS["sh"], "sh", "Shipping")
with tab_fi: render_synchronized_matrix("fill_slots", GOALS["fi"], "fi", "Fill")

# --- 6. REAL-TIME GRAPHICAL ANALYTICS ---
with tab_analytics:
    st.header("📊 Cumulative Corporate Analytics Ledger")
    totals = {"Blocks": 0, "Units": 0, "Alerts": 0}
    tech_chart_series = {}
    dept_chart_series = {"Data Entry": 0, "Call Center": 0, "Shipping": 0, "Fill": 0}
    
    labels_map = {"data_entry_slots": "Data Entry", "call_center_slots": "Call Center", "shipping_slots": "Shipping", "fill_slots": "Fill"}