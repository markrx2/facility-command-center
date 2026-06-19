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
    
    # Global roster table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_roster (
            dept_prefix TEXT, tech_name TEXT, PRIMARY KEY (dept_prefix, tech_name)
        )
    """)
    
    # Dynamic Queues & Goals Matrix Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dynamic_queues (
            dept_prefix TEXT, queue_name TEXT, goal_target TEXT, PRIMARY KEY (dept_prefix, queue_name)
        )
    """)
    
    # 4 Core department production grids
    for dept in ["data_entry_slots", "call_center_slots", "shipping_slots", "fill_slots"]:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {dept} (
                log_date TEXT, tech_name TEXT, slot_id INTEGER, queue TEXT, goal TEXT,
                start_time TEXT, input_number INTEGER, tech_notified INTEGER DEFAULT 0,
                supervisor_notified INTEGER DEFAULT 0, submitted INTEGER DEFAULT 0,
                PRIMARY KEY (log_date, tech_name, slot_id)
            )
        """)
        
    # Global daily checklist table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_checklist (
            log_date TEXT PRIMARY KEY, rejection_queue TEXT DEFAULT 'Pending',
            pa_queue TEXT DEFAULT 'Pending', untransmitted_claims TEXT DEFAULT 'Pending',
            future_bill TEXT DEFAULT 'Pending', data_re_entry TEXT DEFAULT 'Pending',
            reminder_time TEXT DEFAULT '16:00', supervisor_escaped INTEGER DEFAULT 0
        )
    """)
    
    # Core seeding mechanism: ensures tables are populated for all departments
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

# --- 4. MANAGER OVERRIDE AUTHENTICATION LAYER ---
def check_manager_access():
    st.sidebar.header("🔐 Administrative Controls")
    pwd_input = st.sidebar.text_input("Enter Manager Override Password:", type="password", key="mgr_pwd_input_field")
    if pwd_input == "admin123":
        st.sidebar.success("🔑 Admin Privileges Active")
        return True
    elif pwd_input != "":
        st.sidebar.error("❌ Incorrect Password")
    return False

is_manager = check_manager_access()

# --- 5. RENDERING ENGINE FOR WORKER GRID ROWS ---
def render_synchronized_matrix(db_table, prefix, dept_label):
    local_cursor = conn.cursor()
    
    # Always forcefully sync base queues if a department was left empty
    local_cursor.execute("SELECT COUNT(*) FROM dynamic_queues WHERE dept_prefix=?", (prefix,))
    if local_cursor.fetchone()[0] == 0:
        emergency_defaults = {
            "de": [("Queue Alpha - Tier 1", "15 tickets"), ("Queue Beta - Network Ops", "5 alerts")],
            "cc": [("Inbound Support Line", "20 calls"), ("Outbound Follow-ups", "15 checks")],
            "sh": [("Standard Ground Sorting", "40 orders"), ("Priority/Overnight Air", "20 shipments")],
            "fi": [("Automated Dispensing", "10 cells"), ("Manual Counter Line", "50 fills")]
        }
        for q_n, g_t in emergency_defaults[prefix]:
            local_cursor.execute("INSERT OR IGNORE INTO dynamic_queues VALUES (?, ?, ?)", (prefix, q_n, g_t))
        conn.commit()

    # Pull fresh operational paths
    local_cursor.execute("SELECT queue_name, goal_target FROM dynamic_queues WHERE dept_prefix=?", (prefix,))
    goals_dict = {row[0]: row[1] for row in local_cursor.fetchall()}
    
    local_cursor.execute("SELECT tech_name FROM global_roster WHERE dept_prefix=?", (prefix,))
    active_roster = [row[0] for row in local_cursor.fetchall()]
        
    # Roster management module
    with st.expander(f"➕ Manage Live {dept_label} On-Duty Roster", expanded=True):
        col_in, col_bt = st.columns([3, 1])
        with col_in:
            new_worker = st.text_input(f"Enter Employee Name for {dept_label}:", key=f"add_input_{prefix}").strip()
        with col_bt:
            st.markdown("<div style='padding-top:24px;'></div>", unsafe_allow_html=True)
            if st.button("Add to Floor", key=f"add_btn_{prefix}", use_container_width=True) and new_worker:
                if new_worker not in active_roster:
                    local_cursor.execute("INSERT OR IGNORE INTO global_roster (dept_prefix, tech_name) VALUES (?, ?)", (prefix, new_worker))
                    conn.commit()
                    st.rerun()

    if not active_roster:
        st.info(f"💡 No personnel assigned to {dept_label} currently. Add employees above to populate production slots.")
        return

    for worker in active_roster:
        st.markdown(f"### 👤 TECHNICIAN: {worker.upper()}")
        cols = st.columns(4)
        
        for slot_num in range(1, 5):
            with cols[slot_num - 1]:
                with st.container(border=True):
                    st.markdown(f"**🕒 Slot {slot_num}** ({((slot_num-1)*2)+1}-{slot_num*2} Hrs)")
                    local_cursor.execute(f"SELECT * FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                    slot_row = local_cursor.fetchone()
                    
                    if not slot_row:
                        if goals_dict:
                            chosen_q = st.selectbox("Assign Queue:", options=list(goals_dict.keys()), key=f"q_{prefix}_{worker}_{slot_num}")
                            st.caption(f"🎯 Target: {goals_dict[chosen_q]}")
                            if st.button("🚀 Start Clock", key=f"str_{prefix}_{worker}_{slot_num}", use_container_width=True):
                                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                local_cursor.execute(f"INSERT INTO {db_table} (log_date, tech_name, slot_id, queue, goal, start_time) VALUES (?, ?, ?, ?, ?, ?)", (CURRENT_DATE, worker, slot_num, chosen_q, goals_dict[chosen_q], now_str))
                                conn.commit()
                                st.rerun()
                        else:
                            st.warning("Please configure queues in Management panel.")
                    else:
                        _, _, _, db_queue, db_goal, db_start, db_input, db_t_not, db_s_not, db_sub = slot_row
                        st.markdown(f"Queue: `{db_queue}`")
                        st.caption(f"Target Goal: {db_goal}")
                        
                        start_time = datetime.strptime(db_start, "%Y-%m-%d %H:%M:%S")
                        end_time = start_time + timedelta(hours=2)
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
                            st.progress(1.0 - (rem.total_seconds() / 7200.0))
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
st.title("⏱️ Enterprise Facility Command Center")
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
    st.markdown("Add, edit targets, or delete tracking line items.")
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
            for q_prefix, q_name, q_goal in all_qs:
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
            if row[3] == 1:
                totals["Blocks"] += 1
                totals["Units"] += int(row[1])
                dept_chart_series[label] += 1
                tech_chart_series[row[0]] = tech_chart_series.get(row[0], 0) + int(row[1])
            if row[2] == 1: totals["Alerts"] += 1

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
st.markdown("<br><br>", unsafe_with_html=True)
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
            t_obj = datetime.strptime(chk[6], "%H:%M").time()
            new_target_time = st.time_input("Set Verification Deadline:", value=t_obj, key="checklist_deadline_widget")
            if new_target_time.strftime("%H:%M") != chk[6]:
                local_cursor.execute("UPDATE daily_checklist SET reminder_time=? WHERE log_date=?", (new_target_time.strftime("%H:%M"), CURRENT_DATE))
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
                local_cursor.execute("UPDATE daily_checklist SET rejection_queue=?, pa_queue=?, untransmitted_claims=?, future_bill=?, data_re_entry=? WHERE log_date=?", (r1, r2, r3, r4, r5, CURRENT_DATE))
                conn.commit()
                st.rerun()

    # Checklist background scheduling logic
    sys_now = datetime.now()
    alert_target_datetime = datetime.combine(sys_now.date(), t_obj)
    escalation_target_datetime = alert_target_datetime + timedelta(hours=1)
    
    if sys_now >= alert_target_datetime and sys_now < escalation_target_datetime:
        if "Pending" in [r1, r2, r3, r4, r5]:
            dispatch_real_time_alert("⚠️ REMINDER: Global daily queue verification checklist fields are still PENDING.")
            
    if sys_now >= escalation_target_datetime and chk[7] == 0:
        if "Pending" in [chk[1], chk[2], chk[3], chk[4], chk[5]]:
            dispatch_real_time_alert("🚨 LATE COMPLIANCE ESCALATION: Global business operational queues remain unchecked past the 1-hour grace window.")
            local_cursor.execute("UPDATE daily_checklist SET supervisor_escaped=1 WHERE log_date=?", (CURRENT_DATE,))
            conn.commit()
            st.rerun()