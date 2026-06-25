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
    # Using v3 guarantees a brand-new file system slot to bypass any hidden server cache blocks
    conn = sqlite3.connect("facility_matrix_v3.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row  
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_roster (
            dept_prefix TEXT, 
            tech_name TEXT, 
            tech_email TEXT DEFAULT '', 
            tech_webhook TEXT DEFAULT '',
            PRIMARY KEY (dept_prefix, tech_name)
        )
    """)
    
    try:
        cursor.execute("SELECT tech_email FROM global_roster LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE global_roster ADD COLUMN tech_email TEXT DEFAULT ''")
        
    try:
        cursor.execute("SELECT tech_webhook FROM global_roster LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE global_roster ADD COLUMN tech_webhook TEXT DEFAULT ''")
    
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
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS floor_backlogs (
            log_date TEXT PRIMARY KEY,
            erx INT DEFAULT 0, central_fill INT DEFAULT 0, rejected INT DEFAULT 0,
            on_hold INT DEFAULT 0, pa INT DEFAULT 0, dispense INT DEFAULT 0,
            ai_tech INT DEFAULT 0, ordering INT DEFAULT 0, billing INT DEFAULT 0
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
        
    # Full Explicit Checklist Schema mapping ensures zero operational column mismatches
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_checklist (
            log_date TEXT PRIMARY KEY, 
            reminder_time TEXT DEFAULT '16:00', 
            reminder_sent INTEGER DEFAULT 0, 
            supervisor_escaped INTEGER DEFAULT 0,
            rejection_queue TEXT DEFAULT 'Pending', 
            pa_queue TEXT DEFAULT 'Pending', 
            untransmitted_claims TEXT DEFAULT 'Pending', 
            future_bill TEXT DEFAULT 'Pending', 
            data_re_entry TEXT DEFAULT 'Pending',
            ai_tech_check TEXT DEFAULT 'Pending', 
            billing TEXT DEFAULT 'Pending', 
            ordering TEXT DEFAULT 'Pending',
            dispense TEXT DEFAULT 'Pending', 
            return_fourteen_queue TEXT DEFAULT 'Pending',
            rejection_queue_by TEXT DEFAULT '', rejection_queue_notes TEXT DEFAULT '', rejection_queue_date TEXT DEFAULT '', rejection_queue_target TEXT DEFAULT '',
            pa_queue_by TEXT DEFAULT '', pa_queue_notes TEXT DEFAULT '', pa_queue_date TEXT DEFAULT '', pa_queue_target TEXT DEFAULT '',
            untransmitted_claims_by TEXT DEFAULT '', untransmitted_claims_notes TEXT DEFAULT '', untransmitted_claims_date TEXT DEFAULT '', untransmitted_claims_target TEXT DEFAULT '',
            future_bill_by TEXT DEFAULT '', future_bill_notes TEXT DEFAULT '', future_bill_date TEXT DEFAULT '', future_bill_target TEXT DEFAULT '',
            data_re_entry_by TEXT DEFAULT '', data_re_entry_notes TEXT DEFAULT '', data_re_entry_date TEXT DEFAULT '', data_re_entry_target TEXT DEFAULT '',
            ai_tech_check_by TEXT DEFAULT '', ai_tech_check_notes TEXT DEFAULT '', ai_tech_check_date TEXT DEFAULT '', ai_tech_check_target TEXT DEFAULT '',
            billing_by TEXT DEFAULT '', billing_notes TEXT DEFAULT '', billing_date TEXT DEFAULT '', billing_target TEXT DEFAULT '',
            ordering_by TEXT DEFAULT '', ordering_notes TEXT DEFAULT '', ordering_date TEXT DEFAULT '', ordering_target TEXT DEFAULT '',
            dispense_by TEXT DEFAULT '', dispense_notes TEXT DEFAULT '', dispense_date TEXT DEFAULT '', dispense_target TEXT DEFAULT '',
            return_fourteen_queue_by TEXT DEFAULT '', return_fourteen_queue_notes TEXT DEFAULT '', return_fourteen_queue_date TEXT DEFAULT '', return_fourteen_queue_target TEXT DEFAULT ''
        )
    """)
    
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
        st.sidebar.error(f"Global Google Chat Warning: {str(e)}")
    return False

def dispatch_individual_chat_alert(tech_webhook_url, message_body):
    if not tech_webhook_url or "chat.googleapis.com" not in tech_webhook_url:
        return False
    try:
        payload = {"text": message_body}
        response = requests.post(tech_webhook_url, json=payload, headers={"Content-Type": "application/json"})
        return response.status_code == 200
    except Exception as e:
        print(f"Direct Tech Chat Node Alert Refusal: {str(e)}")
    return False

def dispatch_individual_tech_notification(recipient_email, worker_name, slot, department):
    if not recipient_email or "@" not in recipient_email:
        return False
    try:
        if "email" in st.secrets:
            system_sender = st.secrets["email"]["sender"]
            system_password = st.secrets["email"]["password"]
            smtp_server = st.secrets["email"].get("smtp_server", "smtp.gmail.com")
            smtp_port = int(st.secrets["email"].get("port", 465))
            
            msg_text = (f"Hello {worker_name},\n\nYour tracking block timer has ended for {department} (Slot {slot}).\n\nPlease navigate back to the Facility Command Hub dashboard immediately to log your production counts.\n\nThank you!")
            msg = MIMEText(msg_text)
            msg['Subject'] = f"⏱️ Action Required: Timer Ended - Slot {slot} ({department})"
            msg['From'] = f"Facility Command Hub <{system_sender}>"
            msg['To'] = recipient_email
            
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(system_sender, system_password)
                server.sendmail(system_sender, [recipient_email], msg.as_string())
            return True
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

sidebar_db_cursor = conn.cursor()
sidebar_db_cursor.execute("SELECT tech_name, tech_email, tech_webhook FROM global_roster ORDER BY tech_name ASC")
saved_profiles = sidebar_db_cursor.fetchall()

profile_options = ["-- Create New Profile --"] + [p["tech_name"] for p in saved_profiles]
selected_profile = st.sidebar.selectbox("Select Existing Profile (Optional):", options=profile_options, key="profile_selector_widget")

default_name, default_email, default_webhook = "", "", ""
if selected_profile != "-- Create New Profile --":
    matched_profile = next((p for p in saved_profiles if p["tech_name"] == selected_profile), None)
    if matched_profile:
        default_name = matched_profile["tech_name"]
        default_email = matched_profile["tech_email"]
        default_webhook = matched_profile["tech_webhook"]

new_worker_name = st.sidebar.text_input("Employee Full Name:", value=default_name, placeholder="John Doe", key="global_name_field").strip()
new_worker_email = st.sidebar.text_input("Employee Workspace Email:", value=default_email, placeholder="johndoe@company.com", key="global_email_field").strip()
new_worker_webhook = st.sidebar.text_input("Employee Personal Google Chat Webhook:", value=default_webhook, placeholder="https://chat.googleapis.com/v1/spaces/...", key="global_webhook_field").strip()

if st.sidebar.button("Deploy to Department Grid", use_container_width=True, type="primary"):
    if new_worker_name and new_worker_email:
        sidebar_cursor = conn.cursor()
        sidebar_cursor.execute("""
            INSERT OR REPLACE INTO global_roster (dept_prefix, tech_name, tech_email, tech_webhook) 
            VALUES (?, ?, ?, ?)
        """, (dest_dept[1], new_worker_name, new_worker_email, new_worker_webhook))
        conn.commit()
        st.sidebar.success(f"Deployed {new_worker_name} to {dest_dept[0]} Layout!")
        st.rerun()
    else:
        st.sidebar.warning("Please input both name and email routing vectors.")


# --- 5. TOP-LEVEL BACKLOG MATRIX INPUT INJECTOR ---
def render_global_backlog_ribbon():
    backlog_cursor = conn.cursor()
    backlog_cursor.execute("SELECT * FROM floor_backlogs WHERE log_date=?", (CURRENT_DATE,))
    row = backlog_cursor.fetchone()
    
    if not row:
        backlog_cursor.execute("INSERT OR IGNORE INTO floor_backlogs (log_date) VALUES (?)", (CURRENT_DATE,))
        conn.commit()
        backlog_cursor.execute("SELECT * FROM floor_backlogs WHERE log_date=?", (CURRENT_DATE,))
        row = backlog_cursor.fetchone()

    st.markdown("<h4 style='color: #1e3a8a; font-size:15px; margin-bottom:4px;'>📊 Global Real-Time Operational Queue Volume Snapshots</h4>", unsafe_allow_html=True)
    b_cols = st.columns(9)
    
    fields = [
        ("ERx", "erx"), ("Central Fill", "central_fill"), ("Rejected Queue", "rejected"),
        ("On Hold Queue", "on_hold"), ("PA Queue", "pa"), ("Dispense Queue", "dispense"),
        ("AI/Tech Check", "ai_tech"), ("Ordering Queue", "ordering"), ("Billing Queue", "billing")
    ]
    
    updates = {}
    for i, (label, db_field) in enumerate(fields):
        with b_cols[i]:
            current_value = row[db_field] if row else 0
            new_val = st.number_input(label, min_value=0, step=1, value=int(current_value), key=f"top_bl_{db_field}")
            if new_val != current_value:
                updates[db_field] = new_val

    if updates:
        set_clause = ", ".join([f"{k}=?" for k in updates.keys()])
        params = list(updates.values()) + [CURRENT_DATE]
        backlog_cursor.execute(f"UPDATE floor_backlogs SET {set_clause} WHERE log_date=?", params)
        conn.commit()
        st.rerun()
    st.markdown("<hr style='margin: 8px 0px 14px 0px !important; border-top: 2px solid #cbd5e1;'>", unsafe_allow_html=True)


# --- 6. RENDERING ENGINE FOR WORKER GRID ROWS ---
def render_synchronized_matrix(db_table, prefix, dept_label):
    local_cursor = conn.cursor()
    
    local_cursor.execute("SELECT queue_name, goal_target FROM dynamic_queues WHERE dept_prefix=?", (prefix,))
    goals_dict = {row["queue_name"]: row["goal_target"] for row in local_cursor.fetchall()}
    
    local_cursor.execute("SELECT tech_name, tech_email, tech_webhook FROM global_roster WHERE dept_prefix=?", (prefix,))
    roster_rows = local_cursor.fetchall()
    active_roster = {row["tech_name"]: {"email": row["tech_email"], "webhook": row["tech_webhook"]} for row in roster_rows}

    if not active_roster:
        st.info(f"💡 No personnel assigned to {dept_label} currently. Use the left sidebar panel to assign employees to this department.")
        return

    for worker, tech_profiles in active_roster.items():
        w_id = hashlib.md5(worker.encode('utf-8')).hexdigest()[:8]
        tech_email = tech_profiles["email"]
        tech_webhook = tech_profiles["webhook"]
        
        st.markdown(f"### 👤 TECHNICIAN: {worker.upper()} `({tech_email if tech_email else 'No Email Set'})`")
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
                            
                            durations = {"30 Minutes": 30, "1 Hour": 60, "2 Hours": 120, "4 Hours": 240, "8 Hours": 480}
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
                                local_cursor.execute(f"INSERT INTO {db_table} (log_date, tech_name, slot_id, queue, goal, start_time, duration_minutes) VALUES (?, ?, ?, ?, ?, ?, ?)", (CURRENT_DATE, worker, slot_num, chosen_q, calculated_goal_str, now_str, chosen_dur_min))
                                conn.commit()
                                st.rerun()
                        else:
                            st.warning("Configure queues in Management panel.")
                    else:
                        db_queue, db_goal, db_start, db_input = slot_row["queue"], slot_row["goal"], slot_row["start_time"], slot_row["input_number"]
                        db_t_not, db_s_not, db_sub, db_dur_min = slot_row["tech_notified"], slot_row["supervisor_notified"], slot_row["submitted"], slot_row["duration_minutes"]
                        
                        st.markdown(f"Queue: `{db_queue}`")
                        st.caption(f"Target Goal: **{db_goal}** ({db_dur_min} min block)")
                        
                        start_time = datetime.strptime(db_start, "%Y-%m-%d %H:%M:%S")
                        end_time = start_time + timedelta(minutes=db_dur_min)
                        fifteen_min_overdue_time = end_time + timedelta(minutes=15)
                        escalation_time = end_time + timedelta(minutes=10)
                        current_now = datetime.now()
                        
                        # --- SECURED INSTANT PASS-THROUGH FOR MANAGER RESET PRIVILEGES ---
                        is_mgr_active = st.session_state.get("mgr_pwd_input_field") == "admin123"
                        if is_mgr_active:
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
                                if tech_webhook:
                                    dispatch_individual_chat_alert(tech_webhook, f"⏱️ **Timer Expired!**\nYour tracking block timer has ended for *{dept_label}* (Slot {slot_num}).\n\nPlease log counts.")
                                dispatch_real_time_alert(f"⚠️ TIMER ALERT: {worker} reached zero on {dept_label} Slot {slot_num} without metrics.")
                                local_cursor.execute(f"UPDATE {db_table} SET tech_notified=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                
                            if current_now >= fifteen_min_overdue_time and db_s_not < 2:
                                dispatch_real_time_alert(f"⏰ **🚨 OVERDUE METRICS CRITICAL ALERT** 🚨 ⏰\nTechnician: {worker.upper()}\nDepartment: {dept_label}\nSlot: {slot_num} | Status: **Missing counts 15m+ post-deadline.**")
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
                                if db_s_not == 1: st.error("🚨 Supervisor alert sent to Google Chat.")
                                elif db_s_not == 2: st.error("🚨 CRITICAL: Past 15-Minute Deadline Notification Dispatched.")
                        
                        if not db_sub:
                            val = st.number_input("Log Production Volume:", min_value=0, step=1, value=None, key=f"num_{prefix}_{w_id}_{slot_num}")
                            if st.button("Submit Metrics", key=f"sub_{prefix}_{w_id}_{slot_num}", type="primary", use_container_width=True) and val is not None:
                                target_numeric_value = 0
                                match_digits = re.search(r'\d+', str(db_goal))
                                if match_digits: target_numeric_value = int(match_digits.group())
                                
                                is_escalated = 1 if val < target_numeric_value else 0
                                if is_escalated:
                                    dispatch_real_time_alert(f"📉 **PRODUCTION ALERT: GOAL NOT MET** 📉\nTechnician: {worker.upper()}\nDepartment: {dept_label}\nGoal: {db_goal} | Logged: **{val}**")
                                
                                local_cursor.execute("INSERT INTO metrics_history (log_date, department, tech_name, slot_id, queue, goal, input_number, escalated, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (CURRENT_DATE, dept_label, worker, slot_num, db_queue, db_goal, val, is_escalated, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                                local_cursor.execute(f"UPDATE {db_table} SET input_number=?, submitted=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (val, CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.rerun()
                        else:
                            st.success(f"✅ Logged Units: **{db_input}**")
                            if st.button("🔄 Reset Slot", key=f"rst_{prefix}_{w_id}_{slot_num}", use_container_width=True):
                                local_cursor.execute(f"DELETE FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.rerun()

# --- 7. CORE APP ROUTING INTERFACE ---
render_global_backlog_ribbon()

tab_de, tab_cc, tab_sh, tab_fi, tab_analytics, tab_mgmt = st.tabs([
    "💻 Data Entry Line", "📞 Call Center Desk", "📦 Shipping Floor", "🧪 Fill Department", "📊 Cumulative Analytics", "⚙️ Queue Management"
])

with tab_de: render_synchronized_matrix("data_entry_slots", "de", "Data Entry")
with tab_cc: render_synchronized_matrix("call_center_slots", "cc", "Call Center")
with tab_sh: render_synchronized_matrix("shipping_slots", "sh", "Shipping")
with tab_fi: render_synchronized_matrix("fill_slots", "fi", "Fill")

# --- 8. DYNAMIC QUEUE & ROSTER MANAGEMENT CONFIGURATION TAB ---
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
            
            st.markdown("<br><br>", unsafe_allow_html=True)
            st.subheader("🗑 ... Decommission Employee Profiles")
            local_cursor.execute("SELECT dept_prefix, tech_name FROM global_roster ORDER BY tech_name ASC")
            all_staff = local_cursor.fetchall()
            
            if not all_staff:
                st.info("No saved technician profiles found.")
            else:
                for staff in all_staff:
                    s_prefix, s_name = staff["dept_prefix"], staff["tech_name"]
                    d_lbl = {"de": "Data Entry", "cc": "Call Center", "sh": "Shipping", "fi": "Fill"}[s_prefix]
                    s_col1, s_col2 = st.columns([2.5, 1])
                    s_col1.markdown(f"👤 **{s_name}** `({d_lbl})`")
                    if s_col2.button("Remove Profile", key=f"del_staff_{s_prefix}_{hash(s_name)}", type="secondary", use_container_width=True):
                        local_cursor.execute("DELETE FROM global_roster WHERE dept_prefix=? AND tech_name=?", (s_prefix, s_name))
                        conn.commit()
                        st.success(f"Decommissioned {s_name} from system.")
                        st.rerun()
                    st.markdown("<hr style='margin:2px 0px !important;'>", unsafe_allow_html=True)
                    
        with m_col2:
            st.subheader("📋 Current Active Queue Database Matrix")
            local_cursor.execute("SELECT dept_prefix, queue_name, goal_target FROM dynamic_queues")
            all_qs = local_cursor.fetchall()
            
            if not all_qs:
                st.info("No customized tracking queues available.")
            else:
                for q_row in all_qs:
                    q_prefix, q_name, q_goal = q_row["dept_prefix"], q_row["queue_name"], q_row["goal_target"]
                    dept_lbl = {"de": "Data Entry", "cc": "Call Center", "sh": "Shipping", "fi": "Fill"}[q_prefix]
                    with st.container(border=True):
                        st.markdown(f"**[{dept_lbl}]** `{q_name}`")
                        st.caption(f"Base Hourly Vector: {q_goal} per hour")
                        if st.button("🗑️ Delete Line", key=f"del_{q_prefix}_{hash(q_name)}", use_container_width=True):
                            local_cursor.execute("DELETE FROM dynamic_queues WHERE dept_prefix=? AND queue_name=?", (q_prefix, q_name))
                            conn.commit()
                            st.rerun()

# --- 9. REAL-TIME HISTORICAL GRAPHICAL ANALYTICS ---
with tab_analytics:
    st.header("📊 Cumulative Corporate Analytics Ledger")
    local_cursor = conn.cursor()
    date_cols = st.columns(2)
    start_filt = date_cols[0].date_input("Start History Date", value=datetime.now() - timedelta(days=30))
    end_filt = date_cols[1].date_input("End History Date", value=datetime.now())
    
    local_cursor.execute("SELECT log_date, department, tech_name, input_number, escalated FROM metrics_history WHERE log_date >= ? AND log_date <= ?", (start_filt.strftime("%Y-%m-%d"), end_filt.strftime("%Y-%m-%d")))
    historical_records = local_cursor.fetchall()
    
    totals = {"Blocks": 0, "Units": 0, "Alerts": 0}
    tech_chart_series = {}
    dept_chart_series = {"Data Entry": 0, "Call Center": 0, "Shipping": 0, "Fill": 0}
    
    for row in historical_records:
        totals["Blocks"] += 1
        totals["Units"] += int(row["input_number"])
        if int(row["escalated"]) > 0: totals["Alerts"] += 1
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

# --- 10. BUSINESS-WIDE VERIFICATION CHECKLIST ---
st.markdown("<br>", unsafe_allow_html=True)
with st.container(border=True):
    st.header("📋 Global Facility Daily Queue Verification Log")
    local_cursor = conn.cursor()
    
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
            if not val or str(val).strip() == "": return datetime.now().date()
            if isinstance(val, type(datetime.now().date())): return val
            try:
                val_str = str(val).strip()
                return datetime.strptime(val_str, "%Y-%m-%d").date() if "-" in val_str else datetime.strptime(val_str, "%m/%d/%Y").date()
            except: return datetime.now().date()

        def render_checklist_row(form_container, label, db_prefix, prefix_key, is_fourteen_day_threshold=False):
            form_container.markdown(f"##### {label}")
            cols = form_container.columns([1.1, 1.0, 1.0, 0.7, 0.8, 2.0])
            
            row_keys = chk.keys() if hasattr(chk, "keys") else []
            stored_status = chk[db_prefix] if (db_prefix in row_keys and chk[db_prefix]) else "Pending"
            stored_odt = chk[f"{db_prefix}_date"] if f"{db_prefix}_date" in row_keys else ""
            stored_tdt = chk[f"{db_prefix}_target"] if f"{db_prefix}_target" in row_keys else ""
            stored_by = chk[f"{db_prefix}_by"] if f"{db_prefix}_by" in row_keys else ""
            stored_notes = chk[f"{db_prefix}_notes"] if f"{db_prefix}_notes" in row_keys else ""

            curr_status = cols[0].selectbox("Status", options=opt, index=opt.index(stored_status) if stored_status in opt else 0, key=f"status_{prefix_key}_{CURRENT_DATE}")
            curr_odt = cols[1].date_input("Oldest Date", value=parse_stored_date(stored_odt), key=f"odt_{prefix_key}_{CURRENT_DATE}")
            curr_tdt = cols[2].date_input("Target Date", value=parse_stored_date(stored_tdt), key=f"tdt_{prefix_key}_{CURRENT_DATE}")
            
            try:
                date_delta = (curr_tdt - curr_odt).days
                if date_delta > 0:
                    cols[3].markdown(f"<div style='text-align:center; padding-top:24px;'><span style='background-color:#ffeec2; color:#b76e00; padding:4px 8px; border-radius:4px; font-weight:bold; font-size:12px;'>⚠️ {date_delta} Days</span></div>", unsafe_allow_html=True)
                else:
                    cols[3].markdown(f"<div style='text-align:center; padding-top:24px;'><span style='background-color:#d1e7dd; color:#0f5132; padding:4px 8px; border-radius:4px; font-weight:bold; font-size:12px;'>✅ Current</span></div>", unsafe_allow_html=True)
            except:
                cols[3].text_input("Days", value="-", disabled=True, key=f"delta_err_{prefix_key}")
                
            curr_by = cols[4].text_input("Verified By", value=stored_by, key=f"by_{prefix_key}_{CURRENT_DATE}")
            curr_notes = cols[5].text_input("Notes/Explanations", value=stored_notes, key=f"notes_{prefix_key}_{CURRENT_DATE}")
            
            if (curr_status != stored_status or str(curr_odt) != str(stored_odt) or str(curr_tdt) != str(stored_tdt) or curr_by != stored_by or curr_notes != stored_notes):
                up_cursor = conn.cursor()
                up_cursor.execute(f"UPDATE daily_checklist SET {db_prefix}=?, {db_prefix}_date=?, {db_prefix}_target=?, {db_prefix}_by=?, {db_prefix}_notes=? WHERE log_date=?", (curr_status, str(curr_odt), str(curr_tdt), curr_by, curr_notes, CURRENT_DATE))
                conn.commit()
                st.rerun()

        render_checklist_row(c_col, "Rejection Queue", "rejection_queue", "rej")
        render_checklist_row(c_col, "Prior Authorization Queue", "pa_queue", "pa")
        render_checklist_row(c_col, "Untransmitted Claims Ledger", "untransmitted_claims", "untrans")
        render_checklist_row(c_col, "Future Bill Queue", "future_bill", "fut")
        render_checklist_row(c_col, "Data Re-Entry Desk", "data_re_entry", "re_ent")
        render_checklist_row(c_col, "AI Tech Verification Check", "ai_tech_check", "ai_tch")
        render_checklist_row(c_col, "Corporate Billing Module", "billing", "bill")
        render_checklist_row(c_col, "Ordering Queue Logistics", "ordering", "ord")
        render_checklist_row(c_col, "Dispense Station Matrix", "dispense", "disp")
        render_checklist_row(c_col, "14-Day Return Threshold Queue", "return_fourteen_queue", "ret_14", is_fourteen_day_threshold=True)
