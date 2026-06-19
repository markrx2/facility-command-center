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

# --- 2. DATABASE SETUP ---
def init_shared_db():
    conn = sqlite3.connect("shared_facility_matrix.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row  
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_roster (
            dept_prefix TEXT, tech_name TEXT, PRIMARY KEY (dept_prefix, tech_name)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dynamic_queues (
            dept_prefix TEXT, queue_name TEXT, goal_target TEXT, PRIMARY KEY (dept_prefix, queue_name)
        )
    """)
    
    for dept in ["data_entry_slots", "call_center_slots", "shipping_slots", "fill_slots"]:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {dept} (
                log_date TEXT, tech_name TEXT, slot_id INTEGER, queue TEXT, goal TEXT,
                start_time TEXT, input_number INTEGER, tech_notified INTEGER DEFAULT 0,
                supervisor_notified INTEGER DEFAULT 0, submitted INTEGER DEFAULT 0,
                duration_minutes INTEGER DEFAULT 120,
                PRIMARY KEY (log_date, tech_name, slot_id)
            )
        """)
        try:
            cursor.execute(f"SELECT duration_minutes FROM {dept} LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(f"ALTER TABLE {dept} ADD COLUMN duration_minutes INTEGER DEFAULT 120")
        
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_checklist (
            log_date TEXT PRIMARY KEY, 
            rejection_queue TEXT DEFAULT 'Pending',
            pa_queue TEXT DEFAULT 'Pending', 
            untransmitted_claims TEXT DEFAULT 'Pending',
            future_bill TEXT DEFAULT 'Pending', 
            data_re_entry TEXT DEFAULT 'Pending',
            reminder_time TEXT DEFAULT '16:00', 
            supervisor_escaped INTEGER DEFAULT 0
        )
    """)
    
    schema_extensions = [
        ("rejection_queue_by", "TEXT DEFAULT ''"), ("rejection_queue_notes", "TEXT DEFAULT ''"),
        ("pa_queue_by", "TEXT DEFAULT ''"), ("pa_queue_notes", "TEXT DEFAULT ''"),
        ("untransmitted_claims_by", "TEXT DEFAULT ''"), ("untransmitted_claims_notes", "TEXT DEFAULT ''"),
        ("future_bill_by", "TEXT DEFAULT ''"), ("future_bill_notes", "TEXT DEFAULT ''"),
        ("data_re_entry_by", "TEXT DEFAULT ''"), ("data_re_entry_notes", "TEXT DEFAULT ''")
    ]
    for col_name, col_type in schema_extensions:
        try:
            cursor.execute(f"SELECT {col_name} FROM daily_checklist LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(f"ALTER TABLE daily_checklist ADD COLUMN {col_name} {col_type}")
        
    cursor.execute("SELECT COUNT(*) FROM dynamic_queues")
    if cursor.fetchone()[0] == 0:
        defaults = [
            ("de", "Queue Alpha - Tier 1", "15 tickets"), ("de", "Queue Beta - Network Ops", "5 alerts"),
            ("cc", "Inbound Support Line", "20 calls"), ("cc", "Outbound Follow-ups", "15 checks"),
            ("sh", "Standard Ground Sorting", "40 orders"), ("sh", "Priority/Overnight Air", "20 shipments"),
            ("fi", "Automated Dispensing", "10 cells"), ("fi", "Manual Counter Line", "50 fills")
        ]
        cursor.executemany("INSERT OR IGNORE INTO dynamic_queues VALUES (?, ?, ?)", defaults)
        
    conn.commit()
    return conn

conn = init_shared_db()
CURRENT_DATE = datetime.now().strftime("%Y-%m-%d")

# --- 3. GOOGLE CHAT WEBHOOK DISPATCHER ENGINE ---
def dispatch_real_time_alert(message_body):
    try:
        if "google_chat" in st.secrets:
            url = st.secrets["google_chat"]["webhook_url"]
            payload = {"text": message_body}
            response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
            return response.status_code == 200
    except Exception as e:
        st.sidebar.error(f"Google Chat Node Warning: {str(e)}")
    return False

# --- 4. GLOBAL SIDEBAR MANAGEMENT CONTROL HUB ---
st.sidebar.header("🔐 Global System Control Deck")
pwd_input = st.sidebar.text_input("Enter Manager Override Password:", type="password", key="mgr_pwd_input_field")
is_manager = False
if pwd_input == "admin123":
    st.sidebar.success("🔑 Admin Privileges Active")
    is_manager = True
elif pwd_input != "":
    st.sidebar.error("❌ Incorrect Password")

st.sidebar.markdown("---")
st.sidebar.subheader("➕ Quick Add Personnel to Floor")
with st.sidebar.form("global_roster_form", clear_on_submit=True):
    dest_dept = st.selectbox("Assign to Department:", options=[
        ("Data Entry", "de"), ("Call Center", "cc"), ("Shipping", "sh"), ("Fill", "fi")
    ], format_func=lambda x: x[0], key="global_target_dept_sel")
    new_worker_name = st.text_input("Employee Full Name:", placeholder="John Doe", key="global_name_field").strip()
    
    if st.form_submit_button("Deploy to Department Grid", use_container_width=True):
        if new_worker_name:
            sidebar_cursor = conn.cursor()
            sidebar_cursor.execute("INSERT OR IGNORE INTO global_roster (dept_prefix, tech_name) VALUES (?, ?)", (dest_dept[1], new_worker_name))
            conn.commit()
            st.success(f"Deployed {new_worker_name} to {dest_dept[0]}!")
            time.sleep(0.5)
            st.rerun()

# --- 5. RENDERING ENGINE FOR WORKER GRID ROWS ---
def render_synchronized_matrix(db_table, prefix, dept_label):
    local_cursor = conn.cursor()
    
    local_cursor.execute("SELECT queue_name, goal_target FROM dynamic_queues WHERE dept_prefix=?", (prefix,))
    goals_dict = {row["queue_name"]: row["goal_target"] for row in local_cursor.fetchall()}
    
    local_cursor.execute("SELECT tech_name FROM global_roster WHERE dept_prefix=?", (prefix,))
    active_roster = [row["tech_name"] for row in local_cursor.fetchall()]

    if not active_roster:
        st.info(f"💡 No personnel assigned to {dept_label} currently. Use the left sidebar panel to assign employees to this department.")
        return

    for worker in active_roster:
        st.markdown(f"### 👤 TECHNICIAN: {worker.upper()}")
        cols = st.columns(4)
        
        for slot_num in range(1, 5):
            with cols[slot_num - 1]:
                with st.container(border=True):
                    st.markdown(f"**🕒 Slot {slot_num}**")
                    local_cursor.execute(f"SELECT * FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                    slot_row = local_cursor.fetchone()
                    
                    if not slot_row:
                        if goals_dict:
                            chosen_q = st.selectbox("Assign Queue:", options=list(goals_dict.keys()), key=f"q_{prefix}_{worker}_{slot_num}")
                            st.caption(f"🎯 Target: {goals_dict[chosen_q]}")
                            
                            durations = {
                                "30 Minutes": 30, "1 Hour": 60, "2 Hours": 120, "4 Hours": 240, "8 Hours": 480
                            }
                            chosen_dur_label = st.selectbox("Block Duration:", options=list(durations.keys()), index=2, key=f"dur_{prefix}_{worker}_{slot_num}")
                            chosen_dur_min = durations[chosen_dur_label]
                            
                            if st.button("🚀 Start Clock", key=f"str_{prefix}_{worker}_{slot_num}", use_container_width=True):
                                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                local_cursor.execute(f"""
                                    INSERT INTO {db_table} (log_date, tech_name, slot_id, queue, goal, start_time, duration_minutes) 
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (CURRENT_DATE, worker, slot_num, chosen_q, goals_dict[chosen_q], now_str, chosen_dur_min))
                                conn.commit()
                                st.rerun()
                        else:
                            st.warning("Please configure queues in Management panel.")
                    else:
                        db_queue = slot_row["queue"]
                        db_goal = slot_row["goal"]
                        db_start = slot_row["start_time"]
                        db_input = slot_row["input_number"]
                        db_t_not = slot_row["tech_notified"]
                        db_s_not = slot_row["supervisor_notified"]
                        db_sub = slot_row["submitted"]
                        db_dur_min = slot_row["duration_minutes"]
                        
                        st.markdown(f"Queue: `{db_queue}`")
                        st.caption(f"Target Goal: {db_goal} ({db_dur_min} min block)")
                        
                        start_time = datetime.strptime(db_start, "%Y-%m-%d %H:%M:%S")
                        end_time = start_time + timedelta(minutes=db_dur_min)
                        escalation_time = end_time + timedelta(minutes=10)
                        current_now = datetime.now()
                        
                        if is_manager:
                            if st.button("♻️ Force Reset Clock", key=f"mgr_rst_{prefix}_{worker}_{slot_num}", use_container_width=True, type="secondary"):
                                local_cursor.execute(f"DELETE FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.rerun()
                        
                        if current_now < end_time and not db_sub:
                            rem = end_time - current_now
                            h, r = divmod(rem.seconds, 3600)
                            m, s = divmod(r, 60)
                            st.metric(label="⏳ Time Remaining", value=f"{int(h):02d}:{int(m):02d}:{int(s):02d}")
                            st.progress(1.0 - (rem.total_seconds() / (db_dur_min * 60.0)))
                            time.sleep(0.5)
                            st.rerun()
                        elif not db_sub:
                            st.error("🛑 Timer Expired!")
                            if db_t_not == 0:
                                dispatch_real_time_alert(f"⚠️ TIMER ALERT: {worker} reached zero on {dept_label} Slot {slot_num} without metrics.")
                                local_cursor.execute(f"UPDATE {db_table} SET tech_notified=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                            if current_now < escalation_time:
                                grace = escalation_time - current_now
                                gm, gs = divmod(grace.seconds, 60)
                                st.warning(f"⚠️ Escalation in: {int(gm):02d}:{int(gs):02d}")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                if db_s_not == 0:
                                    dispatch_real_time_alert(f"🚨 CRITICAL ESCALATION: {worker} missed metrics window for {dept_label} Slot {slot_num}.")
                                    local_cursor.execute(f"UPDATE {db_table} SET supervisor_notified=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                    conn.commit()
                                st.error("🚨 Supervisor alert sent to Google Chat.")
                        
                        if not db_sub:
                            val = st.number_input("Log Production Volume:", min_value=0, step=1, value=None, key=f"num_{prefix}_{worker}_{slot_num}")
                            if st.button("Submit Metrics", key=f"sub_{prefix}_{worker}_{slot_num}", type="primary", use_container_width=True) and val is not None:
                                local_cursor.execute(f"UPDATE {db_table} SET input_number=?, submitted=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (val, CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.rerun()
                        else:
                            st.success(f"✅ Logged Units: **{db_input}**")
                            if st.button("🔄 Reset Slot", key=f"rst_{prefix}_{worker}_{slot_num}", use_container_width=True):
                                local_cursor.execute(f"DELETE FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.rerun()

# --- 6. CORE APP ROUTING INTERFACE ---
tab_de, tab_cc, tab_sh, tab_fi, tab_analytics, tab_mgmt = st.tabs([
    "💻 Data Entry Line", "📞 Call Center Desk", "📦 Shipping Floor", "🧪 Fill Department", "📊 Cumulative Analytics", "⚙️ Queue Management"
])

with tab_de: render_synchronized_matrix("data_entry_slots", "de", "Data Entry")
with tab_cc: render_synchronized_matrix("call_center_slots", "cc", "Call Center")
with tab_sh: render_synchronized_matrix("shipping_slots", "sh", "Shipping")
with tab_fi: render_synchronized_matrix("fill_slots", "fi", "Fill")

# --- 7. DYNAMIC QUEUE MANAGEMENT CONFIGURATION TAB ---
with tab_mgmt:
    st.header("⚙️ System Queue & Target Goal Adjustments")
    st.markdown("---")
    
    if not is_manager:
        st.warning("🔒 Access Locked: Enter the valid password (`admin123`) in the left sidebar to unlock modifications.")
    else:
        m_col1, m_col2 = st.columns(2)
        local_cursor = conn.cursor()
        
        with m_col1:
            st.subheader("➕ Create Custom Queue Trackers")
            target_dept = st.selectbox("Select Department Destination:", [("Data Entry", "de"), ("Call Center", "cc"), ("Shipping", "sh"), ("Fill", "fi")], key="mgmt_dept_selector")
            new_q_name = st.text_input("New Queue Name:", placeholder="e.g., Priority Tier 3 Verification", key="mgmt_q_name_input").strip()
            new_q_goal = st.text_input("Production Unit Goal Target:", placeholder="e.g., 25 claims processed", key="mgmt_goal_input").strip()
            
            if st.button("Save New Queue Component", type="primary", use_container_width=True, key="mgmt_save_btn"):
                if new_q_name and new_q_goal:
                    local_cursor.execute("INSERT OR REPLACE INTO dynamic_queues VALUES (?, ?, ?)", (target_dept[1], new_q_name, new_q_goal))
                    conn.commit()
                    st.success(f"Added operational tracking line: {new_q_name}")
                    st.rerun()
                    
        with m_col2:
            st.subheader("📋 Current Active Queue Database Matrix")
            local_cursor.execute("SELECT dept_prefix, queue_name, goal_target FROM dynamic_queues")
            all_qs = local_cursor.fetchall()
            
            if not all_qs:
                st.info("No customized tracking queues available.")
            else:
                for q_row in all_qs:
                    q_prefix = q_row["dept_prefix"]
                    q_name = q_row["queue_name"]
                    q_goal = q_row["goal_target"]
                    
                    dept_lbl = {"de": "Data Entry", "cc": "Call Center", "sh": "Shipping", "fi": "Fill"}[q_prefix]
                    with st.container(border=True):
                        st.markdown(f"**[{dept_lbl}]** `{q_name}`")
                        st.caption(f"Goal Vector: {q_goal}")
                        
                        if st.button("🗑️ Delete Line", key=f"del_{q_prefix}_{q_name}", use_container_width=True):
                            local_cursor.execute("DELETE FROM dynamic_queues WHERE dept_prefix=? AND queue_name=?", (q_prefix, q_name))
                            conn.commit()
                            st.rerun()

# --- 8. REAL-TIME GRAPHICAL ANALYTICS ---
with tab_analytics:
    st.header("📊 Cumulative Corporate Analytics Ledger")
    totals = {"Blocks": 0, "Units": 0, "Alerts": 0}
    tech_chart_series = {}
    dept_chart_series = {"Data Entry": 0, "Call Center": 0, "Shipping": 0, "Fill": 0}
    
    local_cursor = conn.cursor()
    labels_map = {"data_entry_slots": "Data Entry", "call_center_slots": "Call Center", "shipping_slots": "Shipping", "fill_slots": "Fill"}
    for table, label in labels_map.items():
        local_cursor.execute(f"SELECT tech_name, input_number, supervisor_notified, submitted FROM {table}")
        for row in local_cursor.fetchall():
            if row["submitted"] == 1:
                totals["Blocks"] += 1
                totals["Units"] += int(row["input_number"])
                dept_chart_series[label] += 1
                tech_chart_series[row["tech_name"]] = tech_chart_series.get(row["tech_name"], 0) + int(row["input_number"])
            if row["supervisor_notified"] == 1: totals["Alerts"] += 1

    k1, k2, k3 = st.columns(3)
    k1.metric("⏱️ Completed Shift Blocks", f"{totals['Blocks']} Blocks")
    k2.metric("📦 Processed Volume", f"{totals['Units']} Units")
    k3.metric("🚨 Chat Alerts Triggered", f"{totals['Alerts']} Escalations")
    
    if tech_chart_series:
        st.markdown("### Production Units per Technician")
        st.bar_chart(tech_chart_series)
    st.markdown("### Operational Load Volume by Department")
    st.line_chart(dept_chart_series)

# --- 9. BUSINESS-WIDE VERIFICATION CHECKLIST ---
st.markdown("<br><br>", unsafe_allow_html=True)
with st.container(border=True):
    st.header("📋 Global Facility Daily Queue Verification Log (Business-Wide)")
    local_cursor = conn.cursor()
    local_cursor.execute("SELECT * FROM daily_checklist WHERE log_date=?", (CURRENT_DATE,))
    chk = local_cursor.fetchone()
    
    if not chk:
        local_cursor.execute("INSERT OR IGNORE INTO daily_checklist (log_date) VALUES (?)", (CURRENT_DATE,))
        conn.commit()
        local_cursor.execute("SELECT * FROM daily_checklist WHERE log_date=?", (CURRENT_DATE,))
        chk = local_cursor.fetchone()
        
    c_col, f_col = st.columns([2, 1])
    with f_col:
        with st.container(border=True):
            t_obj = datetime.strptime(chk["reminder_time"], "%H:%M").time()
            new_target_time = st.time_input("Set Verification Deadline:", value=t_obj, key="checklist_deadline_widget")
            if new_target_time.strftime("%H:%M") != chk["reminder_time"]:
                local_cursor.execute("UPDATE daily_checklist SET reminder_time=? WHERE log_date=?", (new_target_time.strftime("%H:%M"), CURRENT_DATE))
                conn.commit()
                st.rerun()
            
    with c_col:
        with st.form("master_checklist_form"):
            opt = ["Pending", "Yes", "No"]
            
            r1_c1, r1_c2, r1_c3 = st.columns([2, 1, 2])
            r1 = r1_c1.radio("1. Rejection Queue Status", opt, index=opt.index(chk["rejection_queue"]), horizontal=True)
            r1_by = r1_c2.text_input("Sign:", value=chk["rejection_queue_by"], key="by_r1", placeholder="User")
            r1_nt = r1_c3.text_input("Operational Notes:", value=chk["rejection_queue_notes"], key="nt_r1", placeholder="Add context...")
            
            r2_c1, r2_c2, r2_c3 = st.columns([2, 1, 2])
            r2 = r2_c1.radio("2. PA Queue Status", opt, index=opt.index(chk["pa_queue"]), horizontal=True)
            r2_by = r2_c2.text_input("Sign:", value=chk["pa_queue_by"], key="by_r2", placeholder="User")
            r2_nt = r2_c3.text_input("Operational Notes:", value=chk["pa_queue_notes"], key="nt_r2", placeholder="Add context...")
            
            r3_c1, r3_c2, r3_c3 = st.columns([2, 1, 2])
            r3 = r3_c1.radio("3. Untransmitted Claims Status", opt, index=opt.index(chk["untransmitted_claims"]), horizontal=True)
            r3_by = r3_c2.text_input("Sign:", value=chk["untransmitted_claims_by"], key="by_r3", placeholder="User")
            r3_nt = r3_c3.text_input("Operational Notes:", value=chk["untransmitted_claims_notes"], key="nt_r3", placeholder="Add context...")
            
            r4_c1, r4_c2, r4_c3 = st.columns([2, 1, 2])
            r4 = r4_c1.radio("4. Future Bill Status", opt, index=opt.index(chk["future_bill"]), horizontal=True)
            r4_by = r4_c2.text_input("Sign:", value=chk["future_bill_by"], key="by_r4", placeholder="User")
            r4_nt = r4_c3.text_input("Operational Notes:", value=chk["future_bill_notes"], key="nt_r4", placeholder="Add context...")
            
            r5_c1, r5_c2, r5_c3 = st.columns([2, 1, 2])
            r5 = r5_c1.radio("5. Data-Re-Entry Status", opt, index=opt.index(chk["data_re_entry"]), horizontal=True)
            r5_by = r5_c2.text_input("Sign:", value=chk["data_re_entry_by"], key="by_r5", placeholder="User")
            r5_nt = r5_c3.text_input("Operational Notes:", value=chk["data_re_entry_notes"], key="nt_r5", placeholder="Add context...")
            
            if st.form_submit_button("Save Global Checklist Progress", type="primary", use_container_width=True):
                local_cursor.execute("""
                    UPDATE daily_checklist 
                    SET rejection_queue=?, pa_queue=?, untransmitted_claims=?, future_bill=?, data_re_entry=?,
                        rejection_queue_by=?, rejection_queue_notes=?, pa_queue_by=?, pa_queue_notes=?, 
                        untransmitted_claims_by=?, untransmitted_claims_notes=?, future_bill_by=?, future_bill_notes=?, 
                        data_re_entry_by=?, data_re_entry_notes=?
                    WHERE log_date=?
                """, (r1, r2, r3, r4, r5, r1_by, r1_nt, r2_by, r2_nt, r3_by, r3_nt, r4_by, r4_nt, r5_by, r5_nt, CURRENT_DATE))
                conn.commit()
                st.rerun()

    sys_now = datetime.now()
    alert_target_datetime = datetime.combine(sys_now.date(), t_obj)
    escalation_target_datetime = alert_target_datetime + timedelta(hours=1)
    
    if sys_now >= alert_target_datetime:
        queue_map = [
            {"name": "Rejection Queue", "status": r1, "user": r1_by, "note": r1_nt},
            {"name": "PA Queue", "status": r2, "user": r2_by, "note": r2_nt},
            {"name": "Untransmitted Claims", "status": r3, "user": r3_by, "note": r3_nt},
            {"name": "Future Bill", "status": r4, "user": r4_by, "note": r4_nt},
            {"name": "Data-Re-Entry", "status": r5, "user": r5_by, "note": r5_nt},
        ]
        
        exception_lines = []
        for q in queue_map:
            user_string = f" [By: {q['user'].strip()}]" if q['user'].strip() else ""
            note_string = f" - Note: \"{q['note'].strip()}\"" if q['note'].strip() else ""
            
            if q["status"] == "Pending":
                exception_lines.append(f"❌ {q['name']}: PENDING")
            elif q["status"] == "No":
                exception_lines.append(f"⚠️ {q['name']}: MARKED NO{user_string}{note_string}")
        
        if exception_lines:
            status_ledger_string = "\n".join(exception_lines)
            
            if sys_now < escalation_target_datetime:
                dispatch_real_time_alert(
                    f"⚠️ **FACILITY REMINDER: DEADLINE REACHED** ⚠️\n"
                    f"The following exceptions require immediate operational adjustment:\n\n"
                    f"{status_ledger_string}"
                )
            elif chk["supervisor_escaped"] == 0:
                dispatch_real_time_alert(
                    f"🚨 **CRITICAL COMPLIANCE ESCALATION: PAST GRACE WINDOW** 🚨\n"
                    f"The following facility lines remain incomplete past the 1-hour grace parameters:\n\n"
                    f"{status_ledger_string}"
                )
                local_cursor.execute("UPDATE daily_checklist SET supervisor_escaped=1 WHERE log_date=?", (CURRENT_DATE,))
                conn.commit()
                st.rerun()