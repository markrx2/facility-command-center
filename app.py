import streamlit as st
import sqlite3
import time
from datetime import datetime, timedelta
from twilio.rest import Client

# --- PAGE SETUP & COMPONENT STYLING ---
st.set_page_config(page_title="Facility Command Hub", page_icon="⏱️", layout="wide")
st.markdown("""
    <style>
    .main { background-color: #fafafa; }
    div[data-testid="stExpander"] { border: 1px solid #e0e0e0; background-color: #ffffff; border-radius: 8px; }
    h3 { margin-top: 15px !important; color: #1e293b; font-weight: 700; }
    .stButton>button { border-radius: 6px; }
    </style>
""", unsafe_with_html=True)

# --- DATABASE SETUP (Shared Persistent Multi-User Matrix) ---
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

# --- TWILIO REAL SMS DISPATCHER ---
def dispatch_real_time_sms(message_body):
    try:
        if "twilio" in st.secrets:
            cfg = st.secrets["twilio"]
            client = Client(cfg["account_sid"], cfg["auth_token"])
            for number in cfg["supervisor_numbers"]:
                client.messages.create(body=message_body, from_=cfg["twilio_number"], to=number)
            return True
    except Exception as e:
        st.sidebar.error(f"SMS Node Warning: {str(e)}")
    return False

# --- RENDERING ENGINE FOR WORKER GRID ROWS ---
def render_synchronized_matrix(db_table, goals_dict, prefix, dept_label):
    cursor.execute("SELECT tech_name FROM global_roster WHERE dept_prefix=?", (prefix,))
    active_roster = [row[0] for row in cursor.fetchall()]
        
    with st.expander(f"➕ Manage Live {dept_label} On-Duty Roster"):
        col_in, col_bt = st.columns([3, 1])
        with col_in:
            new_worker = st.text_input("Enter Employee Name:", key=f"add_input_{prefix}").strip()
        with col_bt:
            st.markdown("<div style='padding-top:24px;'></div>", unsafe_with_html=True)
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
                                dispatch_real_time_sms(f"ALERT: Tech {worker} timer expired for {dept_label} Slot {slot_num}!")
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
                                    dispatch_real_time_sms(f"🚨 CRITICAL ESCALATION: Tech {worker} missed metrics submission for {dept_label} Slot {slot_num}!")
                                    cursor.execute(f"UPDATE {db_table} SET supervisor_notified=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                    conn.commit()
                                st.error("🚨 Supervisors texted.")
                        
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

# --- CORPORATE CONFIGURATIONS ---
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

# --- REAL-TIME GRAPHICAL ANALYTICS ---
with tab_analytics:
    st.header("📊 Cumulative Corporate Analytics Ledger")
    totals = {"Blocks": 0, "Units": 0, "Alerts": 0}
    tech_chart_series = {}
    dept_chart_series = {"Data Entry": 0, "Call Center": 0, "Shipping": 0, "Fill": 0}
    
    labels_map = {"data_entry_slots": "Data Entry", "call_center_slots": "Call Center", "shipping_slots": "Shipping", "fill_slots": "Fill"}
    for table, label in labels_map.items():
        cursor.execute(f"SELECT tech_name, input_number, supervisor_notified, submitted FROM {table}")
        for row in cursor.fetchall():
            if row[3] == 1:
                totals["Blocks"] += 1
                totals["Units"] += int(row[1])
                dept_chart_series[label] += 1
                tech_chart_series[row[0]] = tech_chart_series.get(row[0], 0) + int(row[1])
            if row[2] == 1: totals["Alerts"] += 1

    k1, k2, k3 = st.columns(3)
    k1.metric("⏱️ Completed Shift Blocks", f"{totals['Blocks']} Blocks")
    k2.metric("📦 Processed Volume", f"{totals['Units']} Units")
    k3.metric("🚨 System Alerts Triggered", f"{totals['Alerts']} Escalations")
    
    if tech_chart_series:
        st.markdown("### Production Units per Technician")
        st.bar_chart(tech_chart_series)
    st.markdown("### Operational Load Volume by Department")
    st.line_chart(dept_chart_series)

# --- BUSINESS-WIDE VERIFICATION CHECKLIST ---
st.markdown("<br><br>", unsafe_with_html=True)
with st.container(border=True):
    st.header("📋 Global Facility Daily Queue Verification Log (Business-Wide)")
    cursor.execute("SELECT * FROM daily_checklist WHERE log_date=?", (CURRENT_DATE,))
    chk = cursor.fetchone()
    if not chk:
        cursor.execute("INSERT OR IGNORE INTO daily_checklist (log_date) VALUES (?)", (CURRENT_DATE,))
        conn.commit()
        cursor.execute("SELECT * FROM daily_checklist WHERE log_date=?", (CURRENT_DATE,))
        chk = cursor.fetchone()
        
    c_col, f_col = st.columns([2, 1])
    with f_col:
        with st.container(border=True):
            t_obj = datetime.strptime(chk[6], "%H:%M").time()
            new_target_time = st.time_input("Set Verification Deadline:", value=t_obj)
            if new_target_time.strftime("%H:%M") != chk[6]:
                cursor.execute("UPDATE daily_checklist SET reminder_time=? WHERE log_date=?", (new_target_time.strftime("%H:%M"), CURRENT_DATE))
                conn.commit()
                st.rerun()
            
    with c_col:
        with st.form("master_checklist_form"):
            opt = ["Pending", "Yes", "No"]
            r1 = st.radio("1. Rejection Queue Status", opt, index=opt.index(chk[1]), horizontal=True)
            r2 = st.radio("2. PA Queue Status", opt, index=opt.index(chk[2]), horizontal=True)
            r3 = st.radio("3. Untransmitted Claims Status", opt, index=opt.index(chk[3]), horizontal=True)
            r4 = st.radio("4. Future Bill Status", opt, index=opt.index(chk[4]), horizontal=True)
            r5 = st.radio("5. Data-Re-Entry Status", opt, index=opt.index(chk[5]), horizontal=True)
            
            if st.form_submit_button("Save Global Checklist Progress", type="primary", use_container_width=True):
                cursor.execute("UPDATE daily_checklist SET rejection_queue=?, pa_queue=?, untransmitted_claims=?, future_bill=?, data_re_entry=? WHERE log_date=?", (r1, r2, r3, r4, r5, CURRENT_DATE))
                conn.commit()
                st.rerun()

    # Checklist background scheduling routine rules
    sys_now = datetime.now()
    alert_target_datetime = datetime.combine(sys_now.date(), t_obj)
    escalation_target_datetime = alert_target_datetime + timedelta(hours=1)
    
    if sys_now >= alert_target_datetime and sys_now < escalation_target_datetime:
        if "Pending" in [r1, r2, r3, r4, r5]:
            dispatch_real_time_sms("REMINDER: Enterprise daily queue verification checklist configurations remain PENDING.")
            
    if sys_now >= escalation_target_datetime and chk[7] == 0:
        if "Pending" in [chk[1], chk[2], chk[3], chk[4], chk[5]]:
            dispatch_real_time_sms("🚨 LATE COMPLIANCE ESCALATION: Global business operational queues remain unchecked past deadline window.")
            cursor.execute("UPDATE daily_checklist SET supervisor_escaped=1 WHERE log_date=?", (CURRENT_DATE,))
            conn.commit()
            st.rerun()