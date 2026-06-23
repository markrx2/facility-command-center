import streamlit as st
import sqlite3
import requests
import hashlib
import re
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# --- 1. PAGE SETUP & COMPONENT STYLING ---
st.set_page_config(page_title="Facility Command Hub", page_icon="⏱️", layout="wide")
st.markdown("""
    <style>
    .main { background-color: #fafafa; }
    div[data-testid="stExpander"] { border: 1px solid #e0e0e0; background-color: #ffffff; border-radius: 8px; }
    h3 { margin-top: 15px !important; color: #1e293b; font-weight: 700; }
    .stButton>button { border-radius: 6px; }
    
    /* Global Compact Padding Tweaks for Dashboard Layout Grid */
    [data-testid="column"] { padding: 0px 2px !important; }
    
    /* Shrink sizes of checklist widgets so they pack tightly horizontally */
    .stRadio div[role="radiogroup"] label { font-size: 11px !important; padding: 2px 4px !important; }
    div[data-testid="stDateInput"] input { padding: 4px 6px !important; font-size: 12px !important; }
    div[data-testid="stTextInput"] input { padding: 4px 6px !important; font-size: 12px !important; }
    div.stMarkdown h5 { font-size: 13px !important; margin-bottom: 2px !important; margin-top: 4px !important; }
    hr { margin: 6px 0px !important; }

    /* Column Width Allocation Layout Grid */
    [data-testid="column"]:nth-of-type(1) { max-width: 150px !important; } 
    [data-testid="column"]:nth-of-type(2) { max-width: 120px !important; } 
    [data-testid="column"]:nth-of-type(3) { max-width: 120px !important; } 
    [data-testid="column"]:nth-of-type(4) { max-width: 75px !important;  } 
    [data-testid="column"]:nth-of-type(5) { max-width: 110px !important; } 
    [data-testid="column"]:nth-of-type(6) { max-width: 450px !important; } 
    </style>
""", unsafe_allow_html=True)

# --- TRUE BROWSER HEARTBEAT ENGINE ---
st.components.v1.html(
    """
    <script>
        const interval = setInterval(function() {
            window.parent.document.querySelector('.stButton button')?.click();
            const streamlitDoc = window.parent.document;
            const updateTrigger = streamlitDoc.createElement('button');
            updateTrigger.style.display = 'none';
            streamlitDoc.body.appendChild(updateTrigger);
            updateTrigger.addEventListener('click', () => {
                window.parent.postMessage({type: 'streamlit:rerun'}, '*');
            });
            window.parent.postMessage({type: 'streamlit:render'}, '*');
        }, 15000); 
    </script>
    """,
    height=0,
    width=0,
)

# --- 2. DATABASE SETUP & MIGRATION ENGINE ---
def init_shared_db():
    conn = sqlite3.connect("shared_facility_matrix.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row  
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_roster (
            dept_prefix TEXT, 
            tech_name TEXT, 
            tech_email TEXT DEFAULT '', 
            PRIMARY KEY (dept_prefix, tech_name)
        )
    """)
    
    try:
        cursor.execute("SELECT tech_email FROM global_roster LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE global_roster ADD COLUMN tech_email TEXT DEFAULT ''")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dynamic_queues (
            dept_prefix TEXT, queue_name TEXT, goal_target TEXT, PRIMARY KEY (dept_prefix, queue_name)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metrics_history (
            archive_id INTEGER PRIMARY KEY AUTOINCREMENT, log_date TEXT, department TEXT, tech_name TEXT, 
            slot_id INTEGER, queue TEXT, goal TEXT, input_number INTEGER, escalated INTEGER DEFAULT 0, timestamp TEXT
        )
    """)
    
    for dept in ["data_entry_slots", "call_center_slots", "shipping_slots", "fill_slots"]:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {dept} (
                log_date TEXT, tech_name TEXT, slot_id INTEGER, queue TEXT, goal TEXT,
                start_time TEXT, input_number INTEGER, tech_notified INTEGER DEFAULT 0,
                supervisor_notified INTEGER DEFAULT 0, submitted INTEGER DEFAULT 0, duration_minutes INTEGER DEFAULT 120,
                PRIMARY KEY (log_date, tech_name, slot_id)
            )
        """)
        try:
            cursor.execute(f"SELECT duration_minutes FROM {dept} LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(f"ALTER TABLE {dept} ADD COLUMN duration_minutes INTEGER DEFAULT 120")
        
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_checklist (
            log_date TEXT PRIMARY KEY, rejection_queue TEXT DEFAULT 'Pending', pa_queue TEXT DEFAULT 'Pending', 
            untransmitted_claims TEXT DEFAULT 'Pending', future_bill TEXT DEFAULT 'Pending', data_re_entry TEXT DEFAULT 'Pending',
            ai_tech_check TEXT DEFAULT 'Pending', billing TEXT DEFAULT 'Pending', ordering TEXT DEFAULT 'Pending',
            dispense TEXT DEFAULT 'Pending', return_fourteen_queue TEXT DEFAULT 'Pending', reminder_time TEXT DEFAULT '16:00', 
            reminder_sent INTEGER DEFAULT 0, supervisor_escaped INTEGER DEFAULT 0
        )
    """)
    
    schema_extensions = [
        ("rejection_queue_by", "TEXT DEFAULT ''"), ("rejection_queue_notes", "TEXT DEFAULT ''"), ("rejection_queue_date", "TEXT DEFAULT ''"), ("rejection_queue_target", "TEXT DEFAULT ''"),
        ("pa_queue_by", "TEXT DEFAULT ''"), ("pa_queue_notes", "TEXT DEFAULT ''"), ("pa_queue_date", "TEXT DEFAULT ''"), ("pa_queue_target", "TEXT DEFAULT ''"),
        ("untransmitted_claims_by", "TEXT DEFAULT ''"), ("untransmitted_claims_notes", "TEXT DEFAULT ''"), ("untransmitted_claims_date", "TEXT DEFAULT ''"), ("untransmitted_claims_target", "TEXT DEFAULT ''"),
        ("future_bill_by", "TEXT DEFAULT ''"), ("future_bill_notes", "TEXT DEFAULT ''"), ("future_bill_date", "TEXT DEFAULT ''"), ("future_bill_target", "TEXT DEFAULT ''"),
        ("data_re_entry_by", "TEXT DEFAULT ''"), ("data_re_entry_notes", "TEXT DEFAULT ''"), ("data_re_entry_date", "TEXT DEFAULT ''"), ("data_re_entry_target", "TEXT DEFAULT ''"),
        ("ai_tech_check_by", "TEXT DEFAULT ''"), ("ai_tech_check_notes", "TEXT DEFAULT ''"), ("ai_tech_check_date", "TEXT DEFAULT ''"), ("ai_tech_check_target", "TEXT DEFAULT ''"),
        ("billing_by", "TEXT DEFAULT ''"), ("billing_notes", "TEXT DEFAULT ''"), ("billing_date", "TEXT DEFAULT ''"), ("billing_target", "TEXT DEFAULT ''"),
        ("ordering_by", "TEXT DEFAULT ''"), ("ordering_notes", "TEXT DEFAULT ''"), ("ordering_date", "TEXT DEFAULT ''"), ("ordering_target", "TEXT DEFAULT ''"),
        ("dispense_by", "TEXT DEFAULT ''"), ("dispense_notes", "TEXT DEFAULT ''"), ("dispense_date", "TEXT DEFAULT ''"), ("dispense_target", "TEXT DEFAULT ''"),
        ("return_fourteen_queue_by", "TEXT DEFAULT ''"), ("return_fourteen_queue_notes", "TEXT DEFAULT ''"), ("return_fourteen_queue_date", "TEXT DEFAULT ''"), ("return_fourteen_queue_target", "TEXT DEFAULT ''")
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

# --- 3. DUAL-CHANNEL NOTIFICATION ENGINE ---
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

def dispatch_individual_tech_notification(recipient_email, worker_name, slot, department):
    if not recipient_email or "@" not in recipient_email:
        print(f"Skipping individual alert: {worker_name} does not have a valid email vector routing configuration.")
        return False
        
    try:
        if "email" in st.secrets:
            system_sender = st.secrets["email"]["sender"]
            system_password = st.secrets["email"]["password"]
            smtp_server = st.secrets["email"].get("smtp_server", "smtp.gmail.com")
            smtp_port = int(st.secrets["email"].get("port", 465))
            
            msg_text = (
                f"Hello {worker_name},\n\n"
                f"Your tracking block block timer has ended for {department} (Slot {slot}).\n\n"
                f"Please navigate back to the Facility Command Hub dashboard immediately to log your production counts.\n\n"
                f"Thank you!"
            )
            msg = MIMEText(msg_text)
            msg['Subject'] = f"⏱️ Action Required: Timer Ended - Slot {slot} ({department})"
            msg['From'] = f"Facility Command Hub <{system_sender}>"
            msg['To'] = recipient_email
            
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(system_sender, system_password)
                server.sendmail(system_sender, [recipient_email], msg.as_string())
            return True
        else:
            print(f"[Fallback Log] No cloud secrets found. Direct notification triggered for {worker_name} ({recipient_email}).")
            return True
    except Exception as e:
        print(f"Individual Tech Notification Refusal: {str(e)}")
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

dest_dept = st.sidebar.selectbox("Assign to Department:", options=[
    ("Data Entry", "de"), ("Call Center", "cc"), ("Shipping", "sh"), ("Fill", "fi")
], format_func=lambda x: x[0], key="global_target_dept_sel")

new_worker_name = st.sidebar.text_input("Employee Full Name:", placeholder="John Doe", key="global_name_field").strip()
new_worker_email = st.sidebar.text_input("Employee Workspace Email:", placeholder="johndoe@company.com", key="global_email_field").strip()

if st.sidebar.button("Deploy to Department Grid", use_container_width=True, type="primary"):
    if new_worker_name and new_worker_email:
        sidebar_cursor = conn.cursor()
        sidebar_cursor.execute("""
            INSERT OR REPLACE INTO global_roster (dept_prefix, tech_name, tech_email) 
            VALUES (?, ?, ?)
        """, (dest_dept[1], new_worker_name, new_worker_email))
        conn.commit()
        st.sidebar.success(f"Deployed {new_worker_name} ({new_worker_email}) to {dest_dept[0]}!")
        st.rerun()
    else:
        st.sidebar.warning("Please input both name and email routing vectors.")

# --- NEW FEATURE: PERSONNEL OFFBOARDING & DELETION DECK ---
st.sidebar.markdown("---")
st.sidebar.subheader("🗑️ Remove Personnel from Grid")

sidebar_cursor = conn.cursor()
sidebar_cursor.execute("SELECT dept_prefix, tech_name FROM global_roster ORDER BY dept_prefix ASC, tech_name ASC")
all_active_personnel = sidebar_cursor.fetchall()

if not all_active_personnel:
    st.sidebar.info("No technicians currently on the active grid floor.")
else:
    dept_map_labels = {"de": "Data Entry", "cc": "Call Center", "sh": "Shipping", "fi": "Fill"}
    personnel_options = [
        (row["dept_prefix"], row["tech_name"], f"[{dept_map_labels.get(row['dept_prefix'], 'Unknown')}] {row['tech_name']}") 
        for row in all_active_personnel
    ]
    
    selected_removal_target = st.sidebar.selectbox(
        "Select Employee to Remove:",
        options=personnel_options,
        format_func=lambda x: x[2],
        key="global_removal_selectbox"
    )
    
    if st.sidebar.button("⚠️ Purge from Active Floor", use_container_width=True, type="secondary"):
        target_prefix, target_name, _ = selected_removal_target
        
        # 1. Strip the employee from the primary corporate floor matrix roster
        sidebar_cursor.execute("DELETE FROM global_roster WHERE dept_prefix=? AND tech_name=?", (target_prefix, target_name))
        
        # 2. Automatically clear out any running block timer tables so the dashboard nodes don't look orphan or corrupt
        dept_table_mapping = {"de": "data_entry_slots", "cc": "call_center_slots", "sh": "shipping_slots", "fi": "fill_slots"}
        target_table = dept_table_mapping.get(target_prefix)
        
        if target_table:
            sidebar_cursor.execute(f"DELETE FROM {target_table} WHERE log_date=? AND tech_name=?", (CURRENT_DATE, target_name))
            
        conn.commit()
        st.sidebar.success(f"Successfully removed {target_name} from active track lists!")
        st.rerun()

# --- 5. RENDERING ENGINE FOR WORKER GRID ROWS ---
def render_synchronized_matrix(db_table, prefix, dept_label):
    local_cursor = conn.cursor()
    
    local_cursor.execute("SELECT queue_name, goal_target FROM dynamic_queues WHERE dept_prefix=?", (prefix,))
    goals_dict = {row["queue_name"]: row["goal_target"] for row in local_cursor.fetchall()}
    
    local_cursor.execute("SELECT tech_name, tech_email FROM global_roster WHERE dept_prefix=?", (prefix,))
    roster_rows = local_cursor.fetchall()
    active_roster = {row["tech_name"]: row["tech_email"] for row in roster_rows}

    if not active_roster:
        st.info(f"💡 No personnel assigned to {dept_label} currently. Use the left sidebar panel to assign employees to this department.")
        return

    for worker, tech_email in active_roster.items():
        w_id = hashlib.md5(worker.encode('utf-8')).hexdigest()[:8]
        
        st.markdown(f"### 👤 TECHNICIAN: {worker.upper()} `({tech_email if tech_email else 'No Email Profile Set'})`")
        cols = st.columns(4)
        
        for slot_num in range(1, 5):
            with cols[slot_num - 1]:
                with st.container(border=True):
                    st.markdown(f"**🕒 Slot {slot_num}**")
                    local_cursor.execute(f"SELECT * FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                    slot_row = local_cursor.fetchone()
                    
                    if not slot_row:
                        if goals_dict:
                            chosen_q = st.selectbox("Assign Queue:", options=list(goals_dict.keys()), key=f"q_{prefix}_{w_id}_{slot_num}")
                            base_goal_str = goals_dict[chosen_q]
                            
                            durations = {
                                "30 Minutes": 30, "1 Hour": 60, "2 Hours": 120, "4 Hours": 240, "8 Hours": 480
                            }
                            chosen_dur_label = st.selectbox("Block Duration:", options=list(durations.keys()), index=1, key=f"dur_{prefix}_{w_id}_{slot_num}")
                            chosen_dur_min = durations[chosen_dur_label]
                            
                            numeric_match = re.search(r'\d+', str(base_goal_str))
                            if numeric_match:
                                base_num = int(numeric_match.group())
                                text_suffix = base_goal_str.replace(str(base_num), "").strip()
                                scaled_num = int(base_num * (chosen_dur_min / 60.0))
                                calculated_goal_str = f"{scaled_num} {text_suffix}".strip()
                            else:
                                calculated_goal_str = base_goal_str
                                
                            st.caption(f"🎯 Calculated Target: **{calculated_goal_str}** *(Base: {base_goal_str}/hr)*")
                            
                            if st.button("🚀 Start Clock", key=f"str_{prefix}_{w_id}_{slot_num}", use_container_width=True):
                                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                local_cursor.execute(f"""
                                    INSERT INTO {db_table} (log_date, tech_name, slot_id, queue, goal, start_time, duration_minutes) 
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (CURRENT_DATE, worker, slot_num, chosen_q, calculated_goal_str, now_str, chosen_dur_min))
                                conn.commit()
                                st.rerun()
                        else:
                            st.warning("Configure queues in Management panel.")
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
                        st.caption(f"Target Goal: **{db_goal}** ({db_dur_min} min block)")
                        
                        start_time = datetime.strptime(db_start, "%Y-%m-%d %H:%M:%S")
                        end_time = start_time + timedelta(minutes=db_dur_min)
                        
                        fifteen_min_overdue_time = end_time + timedelta(minutes=15)
                        escalation_time = end_time + timedelta(minutes=10)
                        current_now = datetime.now()
                        
                        if is_manager:
                            if st.button("♻️ Force Reset Clock", key=f"mgr_rst_{prefix}_{w_id}_{slot_num}", use_container_width=True, type="secondary"):
                                local_cursor.execute(f"DELETE FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.rerun()
                        
                        if current_now < end_time and not db_sub:
                            rem = end_time - current_now
                            h, r = divmod(rem.seconds, 3600)
                            m, s = divmod(r, 60)
                            st.metric(label="⏳ Time Remaining", value=f"{int(h):02d}:{int(m):02d}:{int(s):02d}")
                            st.progress(1.0 - (rem.total_seconds() / (db_dur_min * 60.0)))
                        elif not db_sub:
                            st.error("🛑 Timer Expired!")
                            
                            if db_t_not == 0:
                                dispatch_individual_tech_notification(tech_email, worker, slot_num, dept_label)
                                dispatch_real_time_alert(f"⚠️ TIMER ALERT: {worker} reached zero on {dept_label} Slot {slot_num} without metrics.")
                                
                                local_cursor.execute(f"UPDATE {db_table} SET tech_notified=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                
                            if current_now >= fifteen_min_overdue_time and db_s_not < 2:
                                dispatch_real_time_alert(
                                    f"⏰ **🚨 OVERDUE METRICS CRITICAL ALERT** 🚨 ⏰\n"
                                    f"Technician: {worker.upper()}\n"
                                    f"Department: {dept_label}\n"
                                    f"Slot: {slot_num} | Queue: `{db_queue}`\n"
                                    f"Status: **Metrics have NOT been logged** and 15 minutes have passed since the block expired."
                                )
                                local_cursor.execute(f"UPDATE {db_table} SET supervisor_notified=2 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()

                            if current_now < escalation_time:
                                grace = escalation_time - current_now
                                gm, gs = divmod(grace.seconds, 60)
                                st.warning(f"⚠️ Escalation in: {int(gm):02d}:{int(gs):02d}")
                            else:
                                if db_s_not == 0:
                                    dispatch_real_time_alert(f"🚨 CRITICAL ESCALATION: {worker} missed metrics window for {dept_label} Slot {slot_num}.")
                                    local_cursor.execute(f"UPDATE {db_table} SET supervisor_notified=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                    conn.commit()
                                if db_s_not == 1:
                                    st.error("🚨 Supervisor alert sent to Google Chat.")
                                elif db_s_not == 2:
                                    st.error("🚨 CRITICAL: Past 15-Minute Deadline Notification Dispatched.")
                        
                        if not db_sub:
                            val = st.number_input("Log Production Volume:", min_value=0, step=1, value=None, key=f"num_{prefix}_{w_id}_{slot_num}")
                            if st.button("Submit Metrics", key=f"sub_{prefix}_{w_id}_{slot_num}", type="primary", use_container_width=True) and val is not None:
                                target_numeric_value = 0
                                match_digits = re.search(r'\d+', str(db_goal))
                                if match_digits:
                                    target_numeric_value = int(match_digits.group())
                                
                                is_escalated = 1 if val < target_numeric_value else 0
                                if is_escalated:
                                    dispatch_real_time_alert(
                                        f"📉 **PRODUCTION ALERT: GOAL NOT MET** 📉\n"
                                        f"Technician: {worker.upper()}\n"
                                        f"Department: {dept_label}\n"
                                        f"Queue Segment: {db_queue}\n"
                                        f"Assigned Goal Vector: {db_goal}\n"
                                        f"Logged Metrics Value: **{val}** (Deficit of {target_numeric_value - val} units)"
                                    )
                                
                                local_cursor.execute("""
                                    INSERT INTO metrics_history (log_date, department, tech_name, slot_id, queue, goal, input_number, escalated, timestamp)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (CURRENT_DATE, dept_label, worker, slot_num, db_queue, db_goal, val, is_escalated, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

                                local_cursor.execute(f"UPDATE {db_table} SET input_number=?, submitted=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (val, CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.rerun()
                        else:
                            st.success(f"✅ Logged Units: **{db_input}**")
                            if st.button("🔄 Reset Slot", key=f"rst_{prefix}_{w_id}_{slot_num}", use_container_width=True):
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
            new_q_goal = st.text_input("Production Unit Goal Target (PER 1 HOUR):", placeholder="e.g., 50 claims", key="mgmt_goal_input").strip()
            
            if st.button("Save New Queue Component", type="primary", use_container_width=True, key="mgmt_save_btn"):
                if new_q_name and new_q_goal:
                    local_cursor.execute("INSERT OR REPLACE INTO dynamic_queues VALUES (?, ?, ?)", (target_dept[1], new_q_name, new_q_goal))
                    conn.commit()
                    st.success(f"Added baseline operational tracking line: {new_q_name} at {new_q_goal}/hr")
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
                        st.caption(f"Base Hourly Vector: {q_goal} per hour")
                        
                        if st.button("🗑️ Delete Line", key=f"del_{q_prefix}_{hash(q_name)}", use_container_width=True):
                            local_cursor.execute("DELETE FROM dynamic_queues WHERE dept_prefix=? AND queue_name=?", (q_prefix, q_name))
                            conn.commit()
                            st.rerun()

# --- 8. REAL-TIME HISTORICAL GRAPHICAL ANALYTICS ---
with tab_analytics:
    st.header("📊 Cumulative Corporate Analytics Ledger (Permanent History)")
    local_cursor = conn.cursor()
    
    st.subheader("🔍 Historical Data Range Filters")
    date_cols = st.columns(2)
    start_filt = date_cols[0].date_input("Start History Date", value=datetime.now() - timedelta(days=30))
    end_filt = date_cols[1].date_input("End History Date", value=datetime.now())
    
    local_cursor.execute("""
        SELECT log_date, department, tech_name, input_number, escalated 
        FROM metrics_history 
        WHERE log_date >= ? AND log_date <= ?
    """, (start_filt.strftime("%Y-%m-%d"), end_filt.strftime("%Y-%m-%d")))
    
    historical_records = local_cursor.fetchall()
    
    totals = {"Blocks": 0, "Units": 0, "Alerts": 0}
    tech_chart_series = {}
    dept_chart_series = {"Data Entry": 0, "Call Center": 0, "Shipping": 0, "Fill": 0}
    
    for row in historical_records:
        totals["Blocks"] += 1
        totals["Units"] += int(row["input_number"])
        if int(row["escalated"]) > 0: 
            totals["Alerts"] += 1
        
        dept_chart_series[row["department"]] = dept_chart_series.get(row["department"], 0) + int(row["input_number"])
        tech_chart_series[row["tech_name"]] = tech_chart_series.get(row["tech_name"], 0) + int(row["input_number"])

    k1, k2, k3 = st.columns(3)
    k1.metric("⏱️ Lifetime Shift Blocks Logged", f"{totals['Blocks']} Blocks")
    k2.metric("📦 Cumulative Processed Volume", f"{totals['Units']} Units")
    k3.metric("🚨 Total Goal Deficit Infractions", f"{totals['Alerts']} Incidents")
    
    st.markdown("---")
    if tech_chart_series:
        st.markdown("### Historical Production Metrics per Technician")
        st.bar_chart(tech_chart_series)
    st.markdown("### Historical Production Load Volume by Department")
    st.line_chart(dept_chart_series)

# --- 9. BUSINESS-WIDE VERIFICATION CHECKLIST ---
st.markdown("<br>", unsafe_allow_html=True)
with st.container(border=True):
    st.header("📋 Global Facility Daily Queue Verification Log")
    local_cursor = conn.cursor()
    
    try:
        local_cursor.execute("SELECT reminder_sent, supervisor_escaped FROM daily_checklist LIMIT 1")
    except sqlite3.OperationalError:
        try:
            local_cursor.execute("ALTER TABLE daily_checklist ADD COLUMN reminder_sent INTEGER DEFAULT 0")
        except: pass
    
    local_cursor.execute("SELECT * FROM daily_checklist WHERE log_date=?", (CURRENT_DATE,))
    chk = local_cursor.fetchone()
    
    if not chk:
        local_cursor.execute("INSERT OR IGNORE INTO daily_checklist (log_date, reminder_sent, supervisor_escaped) VALUES (?, 0, 0)", (CURRENT_DATE,))
        conn.commit()
        local_cursor.execute("SELECT * FROM daily_checklist WHERE log_date=?", (CURRENT_DATE,))
        chk = local_cursor.fetchone()
        
    c_col, f_col = st.columns([3.2, 1])
    with f_col:
        with st.container(border=True):
            t_obj = datetime.strptime(chk["reminder_time"], "%H:%M").time()
            new_target_time = st.time_input("Set Verification Deadline (EST):", value=t_obj, key="checklist_deadline_widget")
            if new_target_time.strftime("%H:%M") != chk["reminder_time"]:
                local_cursor.execute("UPDATE daily_checklist SET reminder_time=?, reminder_sent=0, supervisor_escaped=0 WHERE log_date=?", (new_target_time.strftime("%H:%M"), CURRENT_DATE))
                conn.commit()
                st.rerun()
            
    with c_col:
        opt = ["Pending", "Yes", "No"]
        
        def parse_stored_date(val):
            if not val or str(val).strip() == "":
                return datetime.now().date()
            if isinstance(val, type(datetime.now().date())):
                return val
            try:
                val_str = str(val).strip()
                if "-" in val_str:
                    return datetime.strptime(val_str, "%Y-%m-%d").date()
                return datetime.strptime(val_str, "%m/%d/%Y").date()
            except:
                return datetime.now().date()

        def render_checklist_row(form_container, label, db_prefix, prefix_key, is_fourteen_day_threshold=False):
            form_container.markdown(f"##### {label}")
            cols = form_container.columns([1.1, 1.0, 1.0, 0.7, 0.8, 2.0])
            
            row_keys = chk.keys() if hasattr(chk, "keys") else []
            stored_status = chk[db_prefix] if (db_prefix in row_keys and chk[db_prefix]) else "Pending"
            stored_odt = chk[f"{db_prefix}_date"] if f"{db_prefix}_date" in row_keys else ""
            stored_tdt = chk[f"{db_prefix}_target"] if f"{db_prefix}_target" in row_keys else ""
            stored_by = chk[f"{db_prefix}_by"] if f"{db_prefix}_by" in row_keys else ""
            stored_notes = chk[f"{db_prefix}_notes"] if f"{db_prefix}_notes" in row_keys else ""

            status_key = f"status_{prefix_key}_{CURRENT_DATE}"
            odt_key = f"odt_{prefix_key}_{CURRENT_DATE}"
            tdt_key = f"tdt_{prefix_key}_{CURRENT_DATE}"
            by_key = f"by_{prefix_key}_{CURRENT_DATE}"
            nt_key = f"nt_{prefix_key}_{CURRENT_DATE}"

            status_val = cols[0].radio(f"Status for {prefix_key}", opt, index=opt.index(stored_status if stored_status in opt else "Pending"), horizontal=True, key=status_key, label_visibility="collapsed")
            
            oldest_dt = cols[1].date_input("Oldest", value=parse_stored_date(stored_odt), key=odt_key, format="MM/DD/YYYY", label_visibility="collapsed")
            target_dt = cols[2].date_input("Target", value=parse_stored_date(stored_tdt), key=tdt_key, format="MM/DD/YYYY", label_visibility="collapsed")
            sign_by = cols[3].text_input("Sign", value=stored_by, key=by_key, placeholder="Initials", label_visibility="collapsed")
            
            days_gap = (target_dt - oldest_dt).days
            limit_trigger = 14 if is_fourteen_day_threshold else 7
            
            if days_gap >= limit_trigger:
                cols[4].markdown(f"<div style='background-color:#fee2e2; border:1px solid #ef4444; color:#b91c1c; font-weight:bold; border-radius:4px; text-align:center; padding:3px 2px; font-size:11px; margin-top:2px;'>{days_gap} Days</div>", unsafe_allow_html=True)
            else:
                cols[4].markdown(f"<div style='background-color:#dcfce7; border:1px solid #22c55e; color:#15803d; font-weight:bold; border-radius:4px; text-align:center; padding:3px 2px; font-size:11px; margin-top:2px;'>{days_gap} Days</div>", unsafe_allow_html=True)
            
            notes_val = cols[5].text_input("Notes", value=stored_notes, key=nt_key, placeholder="Operational notes...", label_visibility="collapsed")
            form_container.markdown("---")
            
            return status_val, oldest_dt.strftime("%Y-%m-%d"), target_dt.strftime("%Y-%m-%d"), sign_by, notes_val

        this_form = st.container()
        
        h_cols = this_form.columns([1.1, 1.0, 1.0, 0.7, 0.8, 2.0])
        h_cols[0].caption("Status")
        h_cols[1].caption("Oldest Date")
        h_cols[2].caption("Target Date")
        h_cols[3].caption("Sign")
        h_cols[4].caption("Backlog")
        h_cols[5].caption("Queue Line Comments")
        this_form.markdown("---")
        
        r1, r1_oldest, r1_target, r1_by, r1_nt = render_checklist_row(this_form, "1. Reject Queue Current", "rejection_queue", "r1")
        r2, r2_oldest, r2_target, r2_by, r2_nt = render_checklist_row(this_form, "2. PA Queue Addressed", "pa_queue", "r2")
        r3, r3_oldest, r3_target, r3_by, r3_nt = render_checklist_row(this_form, "3. Untransmitted Claims Completed", "untransmitted_claims", "r3")
        r4, r4_oldest, r4_target, r4_by, r4_nt = render_checklist_row(this_form, "4. Future Bill Queue Current", "future_bill", "r4")
        r5, r5_oldest, r5_target, r5_by, r5_nt = render_checklist_row(this_form, "5. Data Re-Entry Queue Cleared", "data_re_entry", "r5")
        r6, r6_oldest, r6_target, r6_by, r6_nt = render_checklist_row(this_form, "6. AI/Tech Check Status", "ai_tech_check", "r6")
        r7, r7_oldest, r7_target, r7_by, r7_nt = render_checklist_row(this_form, "7. Billing Queue Current", "billing", "r7")
        r8, r8_oldest, r8_target, r8_by, r8_nt = render_checklist_row(this_form, "8. Order Queue Current", "ordering", "r8")
        r9, r9_oldest, r9_target, r9_by, r9_nt = render_checklist_row(this_form, "9. Dispense Queue Current", "dispense", "r9")
        r10, r10_oldest, r10_target, r10_by, r10_nt = render_checklist_row(this_form, "10. 14 Day Return Current", "return_fourteen_queue", "r10", is_fourteen_day_threshold=True)
        
        if st.button("Save Global Checklist Progress", type="primary", use_container_width=True, key="save_global_checklist_direct_btn"):
            local_cursor.execute("""
                UPDATE daily_checklist 
                SET rejection_queue=?, pa_queue=?, untransmitted_claims=?, future_bill=?, data_re_entry=?, ai_tech_check=?, billing=?, ordering=?, dispense=?, return_fourteen_queue=?,
                    rejection_queue_by=?, rejection_queue_notes=?, rejection_queue_date=?, rejection_queue_target=?,
                    pa_queue_by=?, pa_queue_notes=?, pa_queue_date=?, pa_queue_target=?,
                    untransmitted_claims_by=?, untransmitted_claims_notes=?, untransmitted_claims_date=?, untransmitted_claims_target=?,
                    future_bill_by=?, future_bill_notes=?, future_bill_date=?, future_bill_target=?,
                    data_re_entry_by=?, data_re_entry_notes=?, data_re_entry_date=?, data_re_entry_target=?,
                    ai_tech_check_by=?, ai_tech_check_notes=?, ai_tech_check_date=?, ai_tech_check_target=?,
                    billing_by=?, billing_notes=?, billing_date=?, billing_target=?,
                    ordering_by=?, ordering_notes=?, ordering_date=?, ordering_target=?,
                    dispense_by=?, dispense_notes=?, dispense_date=?, dispense_target=?,
                    return_fourteen_queue_by=?, return_fourteen_queue_notes=?, return_fourteen_queue_date=?, return_fourteen_queue_target=?
                WHERE log_date=?
            """, (
                r1, r2, r3, r4, r5, r6, r7, r8, r9, r10,
                r1_by, r1_nt, r1_oldest, r1_target,
                r2_by, r2_nt, r2_oldest, r2_target,
                r3_by, r3_nt, r3_oldest, r3_target,
                r4_by, r4_nt, r4_oldest, r4_target,
                r5_by, r5_nt, r5_oldest, r5_target,
                r6_by, r6_nt, r6_oldest, r6_target,
                r7_by, r7_nt, r7_oldest, r7_target,
                r8_by, r8_nt, r8_oldest, r8_target,
                r9_by, r9_nt, r9_oldest, r9_target,
                r10_by, r10_nt, r10_oldest, r10_target,
                CURRENT_DATE
            ))
            conn.commit()
            st.success("🎉 All checklist parameters saved permanently to the database matrix!")
            st.rerun()

    # --- TIMEZONE AND WEEKEND HANDLING ENGINE ---
    try:
        import zoneinfo
        est_tz = zoneinfo.ZoneInfo("America/New_York")
    except ImportError:
        from datetime import timezone
        est_tz = timezone(timedelta(hours=-5))
        
    sys_now = datetime.now(est_tz)
    is_weekend = sys_now.weekday() in [5, 6]

    if not is_weekend:
        alert_target_datetime = datetime.combine(sys_now.date(), t_obj, tzinfo=est_tz)
        escalation_target_datetime = alert_target_datetime + timedelta(hours=1)
        
        queue_map = [
            {"name": "Reject Queue Current", "status": r1, "user": r1_by, "note": r1_nt, "oldest": r1_oldest, "target": r1_target},
            {"name": "PA Queue Addressed", "status": r2, "user": r2_by, "note": r2_nt, "oldest": r2_oldest, "target": r2_target},
            {"name": "Untransmitted Claims Completed", "status": r3, "user": r3_by, "note": r3_nt, "oldest": r3_oldest, "target": r3_target},
            {"name": "Future Bill Queue Current", "status": r4, "user": r4_by, "note": r4_nt, "oldest": r4_oldest, "target": r4_target},
            {"name": "Data Re-Entry Queue Cleared", "status": r5, "user": r5_by, "note": r5_nt, "oldest": r5_oldest, "target": r5_target},
            {"name": "AI/Tech Check Status", "status": r6, "user": r6_by, "note": r6_nt, "oldest": r6_oldest, "target": r6_target},
            {"name": "Billing Queue Current", "status": r7, "user": r7_by, "note": r7_nt, "oldest": r7_oldest, "target": r7_target},
            {"name": "Order Queue Current", "status": r8, "user": r8_by, "note": r8_nt, "oldest": r8_oldest, "target": r8_target},
            {"name": "Dispense Queue Current", "status": r9, "user": r9_by, "note": r9_nt, "oldest": r9_oldest, "target": r9_target},
            {"name": "14 Day Return Current", "status": r10, "user": r10_by, "note": r10_nt, "oldest": r10_oldest, "target": r10_target},
        ]
        
        exception_lines = []
        for q in queue_map:
            user_string = f" [By: {q['user'].strip()}]" if q['user'].strip() else ""
            note_string = f" - Note: \"{q['note'].strip()}\"" if q['note'].strip() else ""
            dates_string = f" (Oldest: {q['oldest']} | Target: {q['target']})"
            
            if q["status"] == "Pending":
                exception_lines.append(f"❌ {q['name']}: PENDING")
            elif q["status"] == "No":
                exception_lines.append(f"⚠️ {q['name']}: MARKED NO{dates_string}{user_string}{note_string}")
        
        if exception_lines:
            status_ledger_string = "\n".join(exception_lines)
            
            chk_keys = chk.keys() if hasattr(chk, "keys") else []
            is_reminder_sent = int(chk["reminder_sent"]) if "reminder_sent" in chk_keys else 0
            is_sup_escaped = int(chk["supervisor_escaped"]) if "supervisor_escaped" in chk_keys else 0
            
            if alert_target_datetime <= sys_now < escalation_target_datetime:
                if is_reminder_sent == 0:
                    dispatch_real_time_alert(
                        f"⚠️ **FACILITY DAILY SUMMARY: ITEMS OUTSTANDING** ⚠️\n"
                        f"The following exceptions require immediate operational adjustment before the grace window closes:\n\n"
                        f"{status_ledger_string}"
                    )
                    local_cursor.execute("UPDATE daily_checklist SET reminder_sent=1 WHERE log_date=?", (CURRENT_DATE,))
                    conn.commit()
                    st.rerun()
                    
            elif sys_now >= escalation_target_datetime:
                if is_sup_escaped == 0:
                    dispatch_real_time_alert(
                        f"🚨 **CRITICAL COMPLIANCE ESCALATION: PAST GRACE WINDOW** 🚨\n"
                        f"The following facility lines remain incomplete past the 1-hour grace parameters:\n\n"
                        f"{status_ledger_string}"
                    )
                    local_cursor.execute("UPDATE daily_checklist SET supervisor_escaped=1 WHERE log_date=?", (CURRENT_DATE,))
                    conn.commit()
                    st.rerun()
