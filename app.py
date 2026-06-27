import streamlit as st
import sqlite3
import requests
import hashlib
import re
import smtplib
import pandas as pd
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import time

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
            const streamlitDoc = window.parent.document;
            const updateTrigger = streamlitDoc.createElement('button');
            updateTrigger.style.display = 'none';
            streamlitDoc.body.appendChild(updateTrigger);
            window.parent.postMessage({type: 'streamlit:render'}, '*');
        }, 5000); 
    </script>
    """,
    height=0,
    width=0,
)

# --- 2. DATABASE SETUP & MIGRATION ENGINE ---
def init_shared_db():
    conn = sqlite3.connect("facility_matrix_v5.db", check_same_thread=False)
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
            slot_id INTEGER, queue TEXT, goal TEXT, input_number INTEGER, escalated INTEGER DEFAULT 0, timestamp TEXT,
            duration_minutes INTEGER DEFAULT 120
        )
    """)
    try:
        cursor.execute("SELECT duration_minutes FROM metrics_history LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE metrics_history ADD COLUMN duration_minutes INTEGER DEFAULT 120")
    
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

    try:
        cursor.execute("SELECT erx_queue FROM daily_checklist LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN erx_queue TEXT DEFAULT 'Pending'")
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN erx_queue_by TEXT DEFAULT ''")
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN erx_queue_notes TEXT DEFAULT ''")
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN erx_queue_date TEXT DEFAULT ''")
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN erx_queue_target TEXT DEFAULT ''")

    try:
        cursor.execute("SELECT central_fill_queue FROM daily_checklist LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN central_fill_queue TEXT DEFAULT 'Pending'")
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN central_fill_queue_by TEXT DEFAULT ''")
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN central_fill_queue_notes TEXT DEFAULT ''")
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN central_fill_queue_date TEXT DEFAULT ''")
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN central_fill_queue_target TEXT DEFAULT ''")

    try:
        cursor.execute("SELECT on_hold_queue FROM daily_checklist LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN on_hold_queue TEXT DEFAULT 'Pending'")
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN on_hold_queue_by TEXT DEFAULT ''")
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN on_hold_queue_notes TEXT DEFAULT ''")
        cursor.execute("ALTER TABLE daily_checklist ADD COLUMN on_hold_queue_date TEXT DEFAULT ''")
    
    cursor.execute("SELECT COUNT(*) FROM dynamic_queues")
    if cursor.fetchone()[0] == 0:
        defaults = [
            ("de", "ERx Regular", "50 rxs"), ("de", "ERx Facility", "60 rxs"), ("de", "Autofill Regular", "50 rxs"), ("de", "Autofill Facility", "75 rxs"),
            ("de", "Ekit Non-Controlled", "50 rxs"), ("de", "Ekit Controlled", "10 rxs"), ("de", "On Hold", "40 rxs"), ("de", "AI/Tech", "30 tags"),
            ("de", "Reject", "40 rxs"), ("de", "PA", "15 rxs"), ("cc", "Inbound Support Line", "20 calls"), ("cc", "Outbound Follow-ups", "15 checks"),
            ("sh", "Standard Ground Sorting", "40 orders"), ("sh", "Priority/Overnight Air", "20 shipments"), ("fi", "Automated Dispensing", "10 cells"), ("fi", "Manual Counter Line", "50 fills")
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
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
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

sidebar_db_cursor = conn.cursor()
sidebar_db_cursor.execute("SELECT tech_name, tech_email, tech_webhook FROM global_roster ORDER BY tech_name ASC")
saved_profiles = sidebar_db_cursor.fetchall()

profile_options = ["-- Create New Profile --"] + [p["tech_name"] for p in saved_profiles]

if "selected_profile_state" not in st.session_state:
    st.session_state["selected_profile_state"] = "-- Create New Profile --"

current_index = 0
if st.session_state["selected_profile_state"] in profile_options:
    current_index = profile_options.index(st.session_state["selected_profile_state"])

selected_profile = st.sidebar.selectbox("Select Existing Profile (Optional):", options=profile_options, index=current_index)
st.session_state["selected_profile_state"] = selected_profile

default_name, default_email, default_webhook = "", "", ""
if selected_profile != "-- Create New Profile --":
    matched_profile = next((p for p in saved_profiles if p["tech_name"] == selected_profile), None)
    if matched_profile:
        default_name = matched_profile["tech_name"]
        default_email = matched_profile["tech_email"]
        default_webhook = matched_profile["tech_webhook"]

with st.sidebar.form(key="sidebar_personnel_deployment_form", clear_on_submit=True):
    dest_dept = st.selectbox("Assign to Department:", options=[
        ("Data Entry", "de"), ("Call Center", "cc"), ("Shipping", "sh"), ("Fill", "fi")
    ], format_func=lambda x: x[0])

    new_worker_name = st.text_input("Employee Full Name:", value=default_name, placeholder="John Doe").strip()
    new_worker_email = st.text_input("Employee Workspace Email:", value=default_email, placeholder="johndoe@company.com").strip()
    new_worker_webhook = st.text_input("Employee Personal Google Chat Webhook:", value=default_webhook, placeholder="https://chat.googleapis.com/v1/spaces/...").strip()
    
    submit_deployment = st.form_submit_button("Deploy to Department Grid", type="primary", use_container_width=True)

if submit_deployment:
    if new_worker_name and new_worker_email:
        sidebar_cursor = conn.cursor()
        sidebar_cursor.execute("""
            INSERT OR REPLACE INTO global_roster (dept_prefix, tech_name, tech_email, tech_webhook) 
            VALUES (?, ?, ?, ?)
        """, (dest_dept[1], new_worker_name, new_worker_email, new_worker_webhook))
        conn.commit()
        st.session_state["selected_profile_state"] = "-- Create New Profile --"
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
        st.query_params.update({"sync_tick": str(time.time())})
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

    is_mgr_active = st.session_state.get("mgr_pwd_input_field") == "admin123"

    for worker, tech_profiles in active_roster.items():
        w_id = hashlib.md5(worker.encode('utf-8')).hexdigest()[:8]
        tech_email = tech_profiles["email"]
        tech_webhook = tech_profiles["webhook"]
        
        st.markdown(f"### 👤 TECHNICIAN: {worker.upper()} `({tech_email if tech_email else 'No Email Set'})`")
        
        # MAIN ROW DISMISSAL CONTROL
        if is_mgr_active:
            if st.button(f"🚨 Wipe Profile & Timers for {worker} from {dept_label}", key=f"mgr_wipe_personnel_{prefix}_{w_id}"):
                local_cursor.execute(f"DELETE FROM {db_table} WHERE log_date=? AND tech_name=?", (CURRENT_DATE, worker))
                local_cursor.execute("DELETE FROM global_roster WHERE dept_prefix=? AND tech_name=?", (prefix, worker))
                conn.commit()
                st.session_state["selected_profile_state"] = "-- Create New Profile --"
                st.query_params.update({"sync_tick": str(time.time())})
                st.rerun()

        cols = st.columns(4)
        
        for slot_num in range(1, 5):
            with cols[slot_num - 1]:
                with st.container(border=True):
                    st.markdown(f"**🕒 Slot {slot_num}**")
                    
                    local_cursor.execute(f"SELECT * FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                    slot_row = local_cursor.fetchone()
                    
                    # --- UNCONDITIONAL HOISTED ADMINISTRATIVE MANAGEMENT BUTTON DECK ---
                    if is_mgr_active:
                        admin_btn_col1, admin_btn_col2 = st.columns(2)
                        
                        # UNCONDITIONAL REMOVAL ENGINE (Wipes tech immediately upon click)
                        if admin_btn_col1.button("🔴 Reset Slot", key=f"admin_slot_rst_{prefix}_{w_id}_{slot_num}", use_container_width=True, type="secondary"):
                            # 1. Immediately kill the tech from the roster table so they drop out of the layout loop
                            local_cursor.execute("DELETE FROM global_roster WHERE dept_prefix=? AND tech_name=?", (prefix, worker))
                            # 2. Clean out any data entries tied to them for the day in this department
                            local_cursor.execute(f"DELETE FROM {db_table} WHERE log_date=? AND tech_name=?", (CURRENT_DATE, worker))
                            conn.commit()
                            
                            # 3. Hard drop memory keys for all 4 slots to avoid memory ghosting elements
                            for s in range(1, 5):
                                state_keys_to_clear =
