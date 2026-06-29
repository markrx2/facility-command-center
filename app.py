import streamlit as st
import sqlite3
import pandas as pd
import re
import hashlib
from datetime import datetime, timedelta, date, time as dt_time
import time
from zoneinfo import ZoneInfo
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import json

# --- 1. INITIAL SYSTEM ENGINE ARCHITECTURE & CONFIGURATION ---
st.set_page_config(
    page_title="Operational Metrics Sync Dashboard", 
    page_icon="⏱️", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# Timezone Lock Configuration 
try:
    EASTERN_TZ = ZoneInfo("America/New_York")
except Exception:
    EASTERN_TZ = None

def get_current_eastern_date():
    if EASTERN_TZ:
        return datetime.now(EASTERN_TZ).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")

CURRENT_DATE = get_current_eastern_date()

# Dynamic Database Matrix Initializer Engine
def initialize_system_database():
    conn = sqlite3.connect("facility_matrix_v5.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Roster mapping vectors
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_roster (
            dept_prefix TEXT,
            tech_name TEXT,
            tech_email TEXT,
            tech_webhook TEXT,
            PRIMARY KEY (dept_prefix, tech_name)
        )
    """)
    
    # Department execution queues matrix configuration
    tables = ["data_entry_slots", "call_center_slots", "shipping_slots", "fill_slots"]
    for t_name in tables:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {t_name} (
                log_date TEXT,
                tech_name TEXT,
                slot_id INTEGER,
                queue TEXT,
                goal TEXT,
                start_time TEXT,
                duration_minutes INTEGER,
                input_number INTEGER DEFAULT NULL,
                tech_notified INTEGER DEFAULT 0,
                supervisor_notified INTEGER DEFAULT 0,
                submitted INTEGER DEFAULT 0,
                PRIMARY KEY (log_date, tech_name, slot_id)
            )
        """)
        
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dynamic_queues (
            dept_prefix TEXT,
            queue_name TEXT,
            goal_target TEXT,
            PRIMARY KEY (dept_prefix, queue_name)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS floor_backlogs (
            log_date TEXT PRIMARY KEY,
            erx INTEGER DEFAULT 0,
            central_fill INTEGER DEFAULT 0,
            rejected INTEGER DEFAULT 0,
            on_hold INTEGER DEFAULT 0,
            pa INTEGER DEFAULT 0,
            dispense INTEGER DEFAULT 0,
            ai_tech INTEGER DEFAULT 0,
            ordering INTEGER DEFAULT 0,
            billing INTEGER DEFAULT 0
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metrics_history (
            log_date TEXT,
            department TEXT,
            tech_name TEXT,
            slot_id INTEGER,
            queue TEXT,
            goal TEXT,
            input_number INTEGER,
            escalated INTEGER,
            timestamp TEXT,
            duration_minutes INTEGER
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_checklist (
            log_date TEXT PRIMARY KEY,
            reminder_sent INTEGER DEFAULT 0,
            supervisor_escaped INTEGER DEFAULT 0,
            reminder_time TEXT DEFAULT '17:00',
            return_fourteen_queue TEXT DEFAULT 'Pending', return_fourteen_queue_date TEXT DEFAULT '', return_fourteen_queue_target TEXT DEFAULT '', return_fourteen_queue_by TEXT DEFAULT '', return_fourteen_queue_notes TEXT DEFAULT '',
            ai_tech_check TEXT DEFAULT 'Pending', ai_tech_check_date TEXT DEFAULT '', ai_tech_check_target TEXT DEFAULT '', ai_tech_check_by TEXT DEFAULT '', ai_tech_check_notes TEXT DEFAULT '',
            billing TEXT DEFAULT 'Pending', billing_date TEXT DEFAULT '', billing_target TEXT DEFAULT '', billing_by TEXT DEFAULT '', billing_notes TEXT DEFAULT '',
            central_fill_queue TEXT DEFAULT 'Pending', central_fill_queue_date TEXT DEFAULT '', central_fill_queue_target TEXT DEFAULT '', central_fill_queue_by TEXT DEFAULT '', central_fill_queue_notes TEXT DEFAULT '',
            data_re_entry TEXT DEFAULT 'Pending', data_re_entry_date TEXT DEFAULT '', data_re_entry_target TEXT DEFAULT '', data_re_entry_by TEXT DEFAULT '', data_re_entry_notes TEXT DEFAULT '',
            dispense TEXT DEFAULT 'Pending', dispense_date TEXT DEFAULT '', dispense_target TEXT DEFAULT '', dispense_by TEXT DEFAULT '', dispense_notes TEXT DEFAULT '',
            erx_queue TEXT DEFAULT 'Pending', erx_queue_date TEXT DEFAULT '', erx_queue_target TEXT DEFAULT '', erx_queue_by TEXT DEFAULT '', erx_queue_notes TEXT DEFAULT '',
            future_bill TEXT DEFAULT 'Pending', future_bill_date TEXT DEFAULT '', future_bill_target TEXT DEFAULT '', future_bill_by TEXT DEFAULT '', future_bill_notes TEXT DEFAULT '',
            on_hold_queue TEXT DEFAULT 'Pending', on_hold_queue_date TEXT DEFAULT '', on_hold_queue_target TEXT DEFAULT '', on_hold_queue_by TEXT DEFAULT '', on_hold_queue_notes TEXT DEFAULT '',
            ordering TEXT DEFAULT 'Pending', ordering_date TEXT DEFAULT '', ordering_target TEXT DEFAULT '', ordering_by TEXT DEFAULT '', ordering_notes TEXT DEFAULT '',
            pa_queue TEXT DEFAULT 'Pending', pa_queue_date TEXT DEFAULT '', pa_queue_target TEXT DEFAULT '', pa_queue_by TEXT DEFAULT '', pa_queue_notes TEXT DEFAULT '',
            rejection_queue TEXT DEFAULT 'Pending', rejection_queue_date TEXT DEFAULT '', rejection_queue_target TEXT DEFAULT '', rejection_queue_by TEXT DEFAULT '', rejection_queue_notes TEXT DEFAULT '',
            untransmitted_claims TEXT DEFAULT 'Pending', untransmitted_claims_date TEXT DEFAULT '', untransmitted_claims_target TEXT DEFAULT '', untransmitted_claims_by TEXT DEFAULT '', untransmitted_claims_notes TEXT DEFAULT ''
        )
    """)
    
    conn.commit()
    return conn

conn = initialize_system_database()

if "refresh_counter" not in st.session_state:
    st.session_state["refresh_counter"] = 0

# --- 2. MULTI-CHANNEL REAL-TIME NOTIFICATION MATRIX ENGINE ---
GOOGLE_CHAT_GLOBAL_OPERATIONS_WEBHOOK = "https://chat.googleapis.com/v1/spaces/AAAA8S6pE70/messages?key=AIzaSyD2N_Z8m6Wl-9gNn_p8O1bV_kXmXyNbcY8&token=S_r9uYkNdHwN2p6fLz8wM2n8x8v8c8b8"

def dispatch_real_time_alert(message_body):
    payload = {"text": message_body}
    headers = {"Content-Type": "application/json; charset=UTF-8"}
    try:
        response = requests.post(GOOGLE_CHAT_GLOBAL_OPERATIONS_WEBHOOK, data=json.dumps(payload), headers=headers, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Global Live Broadcast Exception Linkage Failure: {str(e)}")
        return False

def dispatch_individual_chat_alert(target_webhook_url, message_body):
    payload = {"text": message_body}
    headers = {"Content-Type": "application/json; charset=UTF-8"}
    try:
        response = requests.post(target_webhook_url, data=json.dumps(payload), headers=headers, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Direct Route Handshake Notification Exception: {str(e)}")
        return False

def dispatch_individual_tech_notification(recipient_email, personnel_name, block_index, business_dept):
    sender_identity = "facility-tracker-automation@carepointrx.com"
    smtp_gateway_host = "smtp.gmail.com"
    smtp_gateway_port = 587
    app_authentication_token = "mvkj hgfd lpoi uytr" # Placeholder layout matching systemic variables
    
    email_carrier_wrapper = MIMEMultipart()
    email_carrier_wrapper["From"] = sender_identity
    email_carrier_wrapper["To"] = recipient_email
    email_carrier_wrapper["Subject"] = f"🚨 URGENT ACTION REQUIRED: Metrics Submission Window Open for Slot {block_index}"
    
    message_html_template = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 5px;">
          <h2 style="color: #d32f2f;">⏱️ Production Window Alert</h2>
          <p>Hello <b>{personnel_name}</b>,</p>
          <p>Your scheduled tracking block for <b>{business_dept} (Slot {block_index})</b> has expired.</p>
          <p style="background-color: #fff3cd; padding: 10px; border-left: 5px solid #ffc107;">
            Please log back into the operations terminal dashboard immediately to report your finalized production metrics.
          </p>
          <p style="font-size: 0.8em; color: #777; margin-top: 25px;">
            This is an automated system communication. Please do not reply directly to this message.
          </p>
        </div>
      </body>
    </html>
    """
    email_carrier_wrapper.attach(MIMEText(message_html_template, "html"))
    
    try:
        server = smtplib.SMTP(smtp_gateway_host, smtp_gateway_port)
        server.starttls()
        server.login(sender_identity, app_authentication_token)
        server.sendmail(sender_identity, [recipient_email], email_carrier_wrapper.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"SMTP Notification Engine Interruption: {str(e)}")
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
        st.session_state["refresh_counter"] += 1
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
            new_val = st.number_input(label, min_value=0, step=1, value=int(current_value), key=f"top_bl_{db_field}_{st.session_state['refresh_counter']}")
            if new_val != current_value:
                updates[db_field] = new_val

    if updates:
        set_clause = ", ".join([f"{k}=?" for k in updates.keys()])
        params = list(updates.values()) + [CURRENT_DATE]
        backlog_cursor.execute(f"UPDATE floor_backlogs SET {set_clause} WHERE log_date=?", params)
        conn.commit()
        st.session_state["refresh_counter"] += 1
        st.rerun()
    st.markdown("<hr style='margin: 8px 0px 14px 0px !important; border-top: 2px solid #cbd5e1;'>", unsafe_allow_html=True)

# --- 6. RENDERING ENGINE FOR WORKER GRID ROWS ---
@st.fragment(run_every="5s")
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
        
        if is_mgr_active:
            if st.button(f"🚨 Wipe Profile & Timers for {worker} from {dept_label}", key=f"mgr_wipe_personnel_{prefix}_{w_id}_{st.session_state['refresh_counter']}"):
                local_cursor.execute(f"DELETE FROM {db_table} WHERE log_date=? AND tech_name=?", (CURRENT_DATE, worker))
                local_cursor.execute("DELETE FROM global_roster WHERE dept_prefix=? AND tech_name=?", (prefix, worker))
                conn.commit()
                st.session_state["selected_profile_state"] = "-- Create New Profile --"
                st.session_state["refresh_counter"] += 1
                st.rerun()

        cols = st.columns(4)
        
        for slot_num in range(1, 5):
            with cols[slot_num - 1]:
                with st.container(border=True):
                    st.markdown(f"**🕒 Slot {slot_num}**")
                    
                    local_cursor.execute(f"SELECT * FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                    slot_row = local_cursor.fetchone()
                    
                    if is_mgr_active:
                        admin_btn_col1, admin_btn_col2 = st.columns(2)
                        
                        if admin_btn_col1.button("🔴 Reset Slot", key=f"admin_slot_rst_{prefix}_{w_id}_{slot_num}_{st.session_state['refresh_counter']}", use_container_width=True, type="secondary"):
                            local_cursor.execute(f"DELETE FROM {db_table} WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                            conn.commit()
                            
                            state_keys_to_clear = [
                                f"num_{prefix}_{w_id}_{slot_num}", 
                                f"q_{prefix}_{w_id}_{slot_num}", 
                                f"dur_{prefix}_{w_id}_{slot_num}"
                            ]
                            for key in state_keys_to_clear:
                                if key in st.session_state:
                                    del st.session_state[key]
                            
                            st.session_state["refresh_counter"] += 1
                            st.rerun()
                            
                        if admin_btn_col2.button("🔄 Force Clock Reset", key=f"admin_clk_rst_{prefix}_{w_id}_{slot_num}_{st.session_state['refresh_counter']}", use_container_width=True, type="secondary", disabled=(slot_row is None)):
                            if slot_row is not None:
                                now_reset_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                local_cursor.execute(f"UPDATE {db_table} SET start_time=?, tech_notified=0, supervisor_notified=0, submitted=0 WHERE log_date=? AND tech_name=? AND slot_id=?", (now_reset_str, CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.session_state["refresh_counter"] += 1
                                st.rerun()
                    
                    if not slot_row:
                        if goals_dict:
                            chosen_q = st.selectbox("Assign Queue:", options=list(goals_dict.keys()), key=f"q_{prefix}_{w_id}_{slot_num}_{st.session_state['refresh_counter']}")
                            base_goal_str = goals_dict[chosen_q]
                            
                            durations = {"30 Minutes": 30, "1 Hour": 60, "2 Hours": 120, "4 Hours": 240, "8 Hours": 480}
                            chosen_dur_label = st.selectbox("Block Duration:", options=list(durations.keys()), index=1, key=f"dur_{prefix}_{w_id}_{slot_num}_{st.session_state['refresh_counter']}")
                            chosen_dur_min = durations[chosen_dur_label]
                            
                            numeric_match = re.search(r'\d+', str(base_goal_str))
                            if numeric_match:
                                base_num = int(numeric_match.group())
                                text_suffix = base_goal_str.replace(str(base_num), "").strip()
                                scaled_num = int(base_num * (float(chosen_dur_min) / 60.0))
                                calculated_goal_str = f"{scaled_num} {text_suffix}".strip()
                            else:
                                calculated_goal_str = base_goal_str
                                
                            st.caption(f"🎯 Scheduled Target: **{calculated_goal_str}** *(Base: {base_goal_str}/hr)*")
                            
                            if st.button("🚀 Start Clock", key=f"str_{prefix}_{w_id}_{slot_num}_{st.session_state['refresh_counter']}", use_container_width=True):
                                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                local_cursor.execute(f"INSERT INTO {db_table} (log_date, tech_name, slot_id, queue, goal, start_time, duration_minutes) VALUES (?, ?, ?, ?, ?, ?, ?)", (CURRENT_DATE, worker, slot_num, chosen_q, base_goal_str, now_str, chosen_dur_min))
                                conn.commit()
                                st.session_state["refresh_counter"] += 1
                                st.rerun()
                        else:
                            st.warning("Configure queues in Management panel.")
                    else:
                        db_queue, db_goal, db_start, db_input = slot_row["queue"], slot_row["goal"], slot_row["start_time"], slot_row["input_number"]
                        db_t_not, db_s_not, db_sub, db_dur_min = slot_row["tech_notified"], slot_row["supervisor_notified"], slot_row["submitted"], slot_row["duration_minutes"]
                        
                        numeric_match = re.search(r'\d+', str(db_goal))
                        if numeric_match:
                            b_num = int(numeric_match.group())
                            sfx = db_goal.replace(str(b_num), "").strip()
                            display_target = f"{int(b_num * (float(db_dur_min) / 60.0))} {sfx}".strip()
                        else:
                            display_target = db_goal

                        st.markdown(f"Queue: `{db_queue}`")
                        st.caption(f"Target Goal: **{display_target}** ({db_dur_min} min allocated)")
                        
                        start_time = datetime.strptime(db_start, "%Y-%m-%d %H:%M:%S")
                        end_time = start_time + timedelta(minutes=db_dur_min)
                        fifteen_min_overdue_time = end_time + timedelta(minutes=15)
                        escalation_time = end_time + timedelta(minutes=10)
                        current_now = datetime.now()
                        
                        if current_now < end_time and not db_sub:
                            rem = end_time - current_now
                            total_rem_seconds = int(rem.total_seconds())
                            h, r = divmod(total_rem_seconds, 3600)
                            m, s = divmod(r, 60)
                            st.metric(label="⏳ Time Remaining", value=f"{int(h):02d}:{int(m):02d}:{int(s):02d}")
                            st.progress(1.0 - (float(total_rem_seconds) / (float(db_dur_min) * 60.0)))
                        elif not db_sub:
                            st.error("🛑 Timer Expired!")
                            if db_t_not == 0:
                                dispatch_individual_tech_notification(tech_email, worker, slot_num, dept_label)
                                if tech_webhook:
                                    dispatch_individual_chat_alert(tech_webhook, f"⏱️ **Timer Expired!**\nYour tracking block timer has ended for *{dept_label}* (Slot {slot_num}).\n\nPlease log counts.")
                                dispatch_real_time_alert(f"⚠️ TIMER ALERT: {worker} reached zero on {dept_label} Slot {slot_num} without metrics.")
                                local_cursor.execute(f"UPDATE {db_table} SET tech_notified=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.session_state["refresh_counter"] += 1
                                st.rerun()
                                
                            if current_now >= fifteen_min_overdue_time and db_s_not < 2:
                                dispatch_real_time_alert(f"⏰ **🚨 OVERDUE METRICS CRITICAL ALERT** 🚨 ⏰\nTechnician: {worker.upper()}\nDepartment: {dept_label}\nSlot: {slot_num} | Status: **Missing counts 15m+ post-deadline.**")
                                local_cursor.execute(f"UPDATE {db_table} SET supervisor_notified=2 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.session_state["refresh_counter"] += 1
                                st.rerun()

                        if current_now < escalation_time:
                            grace = escalation_time - current_now
                            gm, gs = divmod(int(grace.total_seconds()), 60)
                            if current_now >= end_time and not db_sub:
                                st.warning(f"⚠️ Escalation in: {int(gm):02d}:{int(gs):02d}")
                        else:
                            if db_s_not == 0 and not db_sub:
                                dispatch_real_time_alert(f"🚨 CRITICAL ESCALATION: {worker} missed metrics window for {dept_label} Slot {slot_num}.")
                                local_cursor.execute(f"UPDATE {db_table} SET supervisor_notified=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.session_state["refresh_counter"] += 1
                                p.rerun()
                        
                        if db_s_not == 1: st.error("🚨 Supervisor alert sent to Google Chat.")
                        elif db_s_not == 2: st.error("🚨 CRITICAL: Past 15-Minute Deadline Notification Dispatched.")
                        
                        if not db_sub:
                            val = st.number_input("Log Production Volume:", min_value=0, step=1, value=None, key=f"num_{prefix}_{w_id}_{slot_num}_{st.session_state['refresh_counter']}")
                            if st.button("Submit Metrics", key=f"sub_{prefix}_{w_id}_{slot_num}_{st.session_state['refresh_counter']}", type="primary", use_container_width=True) and val is not None:
                                time_logged_now = datetime.now()
                                elapsed_delta = time_logged_now - start_time
                                
                                actual_minutes_used = max(1, int(elapsed_delta.total_seconds() / 60.0))
                                base_hourly_rate = 0
                                match_digits = re.search(r'\d+', str(db_goal))
                                if match_digits: 
                                    base_hourly_rate = int(match_digits.group())
                                
                                dynamic_target_threshold = max(1, int(float(base_hourly_rate) * (float(actual_minutes_used) / 60.0)))
                                is_escalated = 1 if val < dynamic_target_threshold else 0
                                
                                if is_escalated:
                                    dispatch_real_time_alert(f"📉 **PRODUCTION ALERT: GOAL NOT MET** 📉\nTechnician: {worker.upper()}\nDepartment: {dept_label}\nCalculated Target for {actual_minutes_used} min: {dynamic_target_threshold} | Logged: **{val}**")
                                
                                local_cursor.execute("INSERT INTO metrics_history (log_date, department, tech_name, slot_id, queue, goal, input_number, escalated, timestamp, duration_minutes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (CURRENT_DATE, dept_label, worker, slot_num, db_queue, db_goal, val, is_escalated, time_logged_now.strftime("%Y-%m-%d %H:%M:%S"), actual_minutes_used))
                                local_cursor.execute(f"UPDATE {db_table} SET input_number=?, submitted=1 WHERE log_date=? AND tech_name=? AND slot_id=?", (val, CURRENT_DATE, worker, slot_num))
                                conn.commit()
                                st.session_state["refresh_counter"] += 1
                                st.rerun()
                        else:
                            st.success(f"✅ Logged Units: **{db_input}**")

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
            new_q_goal = st.text_input("Production Unit Goal Target (PER 1 HOUR):", placeholder="e.g., 50 rxs", key="mgmt_goal_input").strip()
            
            if st.button("Save New Queue Component", type="primary", use_container_width=True, key="mgmt_save_btn"):
                if new_q_name and new_q_goal:
                    local_cursor.execute("INSERT OR REPLACE INTO dynamic_queues VALUES (?, ?, ?)", (target_dept[1], new_q_name, new_q_goal))
                    conn.commit()
                    st.success(f"Added baseline operational tracking line: {new_q_name} at {new_q_goal}/hr")
                    st.session_state["refresh_counter"] += 1
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
                    if s_col2.button("Remove Profile", key=f"del_staff_{s_prefix}_{hash(s_name)}_{st.session_state['refresh_counter']}", type="secondary", use_container_width=True):
                        local_cursor.execute("DELETE FROM global_roster WHERE dept_prefix=? AND tech_name=?", (s_prefix, s_name))
                        local_cursor.execute(f"DELETE FROM data_entry_slots WHERE log_date=? AND tech_name=?", (CURRENT_DATE, s_name))
                        local_cursor.execute(f"DELETE FROM call_center_slots WHERE log_date=? AND tech_name=?", (CURRENT_DATE, s_name))
                        local_cursor.execute(f"DELETE FROM shipping_slots WHERE log_date=? AND tech_name=?", (CURRENT_DATE, s_name))
                        local_cursor.execute(f"DELETE FROM fill_slots WHERE log_date=? AND tech_name=?", (CURRENT_DATE, s_name))
                        conn.commit()
                        st.session_state["selected_profile_state"] = "-- Create New Profile --"
                        st.success(f"Decommissioned {s_name} from system.")
                        st.session_state["refresh_counter"] += 1
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
                        if st.button("🗑️ Delete Line", key=f"del_{q_prefix}_{hash(q_name)}_{st.session_state['refresh_counter']}", use_container_width=True):
                            local_cursor.execute("DELETE FROM dynamic_queues WHERE dept_prefix=? AND queue_name=?", (q_prefix, q_name))
                            conn.commit()
                            st.session_state["refresh_counter"] += 1
                            st.rerun()

# --- 9. ADVANCED HISTORICAL & TRENDS ANALYTICS TAB ---
with tab_analytics:
    st.header("📊 Cumulative Corporate Analytics Ledger")
    local_cursor = conn.cursor()
    
    date_cols = st.columns(2)
    start_filt = date_cols[0].date_input("Start History Date", value=datetime.now() - timedelta(days=30))
    end_filt = date_cols[1].date_input("End History Date", value=datetime.now())
    
    query = """
        SELECT log_date, department, tech_name, queue, goal, input_number, duration_minutes 
        FROM metrics_history 
        WHERE log_date >= ? AND log_date <= ?
    """
    df_analytics = pd.read_sql_query(query, sqlite3.connect("facility_matrix_v5.db"), params=(start_filt.strftime("%Y-%m-%d"), end_filt.strftime("%Y-%m-%d")))
    
    if df_analytics.empty:
        st.info("💡 No production records logged during this timeframe configuration.")
    else:
        total_blocks = len(df_analytics)
        total_units = df_analytics["input_number"].sum()
        
        st.markdown("---")
        st.subheader("👤 Technician Production Log Matrix (By Date & Queue)")
        st.markdown("📋 **Calculations evaluate goals using the precise time used by the technician.**")
        
        selected_techs = st.multiselect("Filter by Technicians:", options=df_analytics["tech_name"].unique(), default=df_analytics["tech_name"].unique())
        df_filtered = df_analytics[df_analytics["tech_name"].isin(selected_techs)].copy()
        
        if not df_filtered.empty:
            def recalculate_pro_rata_metrics(row):
                raw_goal_str = str(row["goal"])
                match = re.search(r'\d+', raw_goal_str)
                if not match:
                    return pd.Series([0, "✅ Met Goal"])
                
                base_hourly_target = int(match.group())
                actual_min = max(1, int(row["duration_minutes"]))
                pro_rated_calculated_goal = max(1, int(float(base_hourly_target) * (float(actual_min) / 60.0)))
                status_label = "✅ Met Goal" if int(row["input_number"]) >= pro_rated_calculated_goal else "❌ Missed Goal"
                return pd.Series([pro_rated_calculated_goal, status_label])

            df_filtered[["Pro-Rated Goal", "True Performance Status"]] = df_filtered.apply(recalculate_pro_rata_metrics, axis=1)
            df_filtered["Actual Time Used"] = df_filtered["duration_minutes"].apply(lambda x: f"{x} Min")
            
            display_df = df_filtered[[
                "log_date", "tech_name", "department", "queue", "Actual Time Used", "Pro-Rated Goal", "input_number", "True Performance Status"
            ]].rename(columns={
                "log_date": "Date", "tech_name": "Technician Name", "department": "Department", "queue": "Assigned Queue", "input_number": "Logged Units"
            })
            
            def highlight_status(val):
                color = '#ffccd5' if val == '❌ Missed Goal' else '#d1e7dd'
                return f'background-color: {color}'
                
            st.dataframe(display_df.style.map(highlight_status, subset=['True Performance Status']), use_container_width=True, hide_index=True)
            
            true_missed_count = (df_filtered["True Performance Status"] == "❌ Missed Goal").sum()
            
            k1, k2, k3 = st.columns(3)
            k1.metric("⏱️ Shift Blocks Evaluated", f"{total_blocks} Blocks")
            k2.metric("📦 Volume Processed", f"{total_units:,} Units")
            k3.metric("🚨 True Pro-Rata Deficits Flagged", f"{true_missed_count} Incidents")
        else:
            st.warning("Please select at least one technician profile.")
            
        st.markdown("---")
        st.subheader("📈 Operational Velocity Trend Analysis")
        
        trend_view_option = st.radio("Group Trend Visualization By:", ["Individual Technician Trends", "Queue Volume Trends"], horizontal=True)
        if trend_view_option == "Individual Technician Trends":
            trend_df = df_filtered.groupby(["log_date", "tech_name"])["input_number"].sum().unstack(fill_value=0)
            st.line_chart(trend_df)
        else:
            trend_df = df_filtered.groupby(["log_date", "queue"])["input_number"].sum().unstack(fill_value=0)
            st.line_chart(trend_df)

# --- 10. BUSINESS-WIDE VERIFICATION CHECKLIST (BATCH SUBMISSION ENGINE) ---
st.markdown("<br>", unsafe_allow_html=True)
with st.container(border=True):
    st.header("📋 Global Facility Daily Queue Verification Log")
    local_cursor = conn.cursor()
    
    local_cursor.execute("SELECT * FROM daily_checklist WHERE log_date=?", (CURRENT_DATE,))
    chk = local_cursor.fetchone()
    
    if not chk:
        local_cursor.execute("INSERT OR IGNORE INTO daily_checklist (log_date, reminder_sent, supervisor_escaped, reminder_time) VALUES (?, 0, 0, '17:00')", (CURRENT_DATE,))
        conn.commit()
        local_cursor.execute("SELECT * FROM daily_checklist WHERE log_date=?", (CURRENT_DATE,))
        chk = local_cursor.fetchone()
        
    c_col, f_col = st.columns([3.2, 1])
    
    with f_col:
        with st.container(border=True):
            t_obj = datetime.strptime(chk["reminder_time"], "%H:%M").time()
            new_target_time = st.time_input("Set Verification Deadline (EST):", value=t_obj, key=f"checklist_deadline_widget_{st.session_state['refresh_counter']}")
            if new_target_time.strftime("%H:%M") != chk["reminder_time"]:
                local_cursor.execute("UPDATE daily_checklist SET reminder_time=?, reminder_sent=0, supervisor_escaped=0 WHERE log_date=?", (new_target_time.strftime("%H:%M"), CURRENT_DATE))
                conn.commit()
                st.session_state["refresh_counter"] += 1
                st.rerun()
            
            # --- 30 MINUTE OVERDUE ESCALATION TRACKER (TIMEZONE LOCKED) ---
            if EASTERN_TZ:
                current_time_now = datetime.now(EASTERN_TZ)
            else:
                current_time_now = datetime.now()
            
            deadline_datetime = datetime.combine(current_time_now.date(), t_obj)
            if EASTERN_TZ:
                deadline_datetime = deadline_datetime.replace(tzinfo=EASTERN_TZ)
                
            dilation_deadline = deadline_datetime + timedelta(minutes=30)
            
            if current_time_now >= dilation_deadline and chk["supervisor_escaped"] == 0:
                if chk["reminder_sent"] == 0: 
                    escalation_chat_msg = (
                        f"⏰ **🚨 CRITICAL OPERATIONS ESCALATION** 🚨 ⏰\n\n"
                        f"The **Global Facility Daily Queue Verification Log** has NOT been submitted for today.\n"
                        f"⏳ **Target Deadline:** {chk['reminder_time']} EST\n"
                        f"❌ **Status:** Overdue by 30+ minutes without supervisor sign-off.\n\n"
                        f"Please complete and log all verification vectors immediately."
                    )
                    dispatch_real_time_alert(escalation_chat_msg)
                    local_cursor.execute("UPDATE daily_checklist SET supervisor_escaped=1, reminder_sent=1 WHERE log_date=?", (CURRENT_DATE,))
                    conn.commit()
                    st.toast("🚨 Deadline escalation alert dispatched to Google Chat!", icon="📧")
            
    with c_col:
        opt = ["Pending", "Yes", "No"]
        
        def parse_stored_date(val):
            if not val or str(val).strip() == "": return datetime.now().date()
            if isinstance(val, type(datetime.now().date())): return val
            try:
                val_str = str(val).strip()
                return datetime.strptime(val_str, "%Y-%m-%d").date() if "-" in val_str else datetime.strptime(val_str, "%m/%d/%Y").date()
            except: return datetime.now().date()

        form_states = {}

        def render_checklist_row(label, db_prefix, prefix_key):
            st.markdown(f"##### {label}")
            cols = st.columns([1.1, 1.0, 1.0, 0.7, 0.8, 2.0])
            
            row_keys = list(chk.keys()) if chk else []
            stored_status = chk[db_prefix] if (db_prefix in row_keys and chk[db_prefix]) else "Pending"
            stored_odt = chk[f"{db_prefix}_date"] if f"{db_prefix}_date" in row_keys else ""
            stored_tdt = chk[f"{db_prefix}_target"] if f"{db_prefix}_target" in row_keys else ""
            stored_by = chk[f"{db_prefix}_by"] if f"{db_prefix}_by" in row_keys else ""
            stored_notes = chk[f"{db_prefix}_notes"] if f"{db_prefix}_notes" in row_keys else ""

            curr_status = cols[0].selectbox("Status", options=opt, index=opt.index(stored_status) if stored_status in opt else 0, key=f"status_{prefix_key}_{CURRENT_DATE}_{st.session_state['refresh_counter']}")
            curr_odt = cols[1].date_input("Oldest Date", value=parse_stored_date(stored_odt), key=f"odt_{prefix_key}_{CURRENT_DATE}_{st.session_state['refresh_counter']}")
            curr_tdt = cols[2].date_input("Target Date", value=parse_stored_date(stored_tdt), key=f"tdt_{prefix_key}_{CURRENT_DATE}_{st.session_state['refresh_counter']}")
            
            date_delta = 0
            try:
                if db_prefix in ["erx_queue", "central_fill_queue", "on_hold_queue"]:
                    date_delta = (datetime.now().date() - curr_odt).days
                else:
                    date_delta = (curr_tdt - curr_odt).days
                
                header_html = "<div style='font-size: 14px; margin-bottom: 10px; color: #31333F;'>Aging</div>"
                is_red = False
                if date_delta > 0:
                    if db_prefix in ["erx_queue", "central_fill_queue", "on_hold_queue", "data_re_entry", "untransmitted_claims"]:
                        is_red = True
                    elif db_prefix in ["ai_tech_check", "rejection_queue"] and date_delta > 4:
                        is_red = True
                    elif db_prefix == "return_fourteen_queue" and date_delta >= 14:
                        is_red = True
                    elif db_prefix not in ["erx_queue", "central_fill_queue", "on_hold_queue", "data_re_entry", "untransmitted_claims", "ai_tech_check", "rejection_queue", "return_fourteen_queue"] and date_delta >= 7:
                        is_red = True

                if is_red:
                    badge_html = f"<div style='text-align:center;'><span style='background-color:#f8d7da; color:#842029; padding:6px 10px; border-radius:4px; font-weight:bold; font-size:12px;'>🚨 {date_delta} Days</span></div>"
                elif date_delta > 0:
                    badge_html = f"<div style='text-align:center;'><span style='background-color:#fff3cd; color:#664d03; padding:6px 10px; border-radius:4px; font-weight:bold; font-size:12px;'>⚠️ {date_delta} Days</span></div>"
                else:
                    badge_html = f"<div style='text-align:center;'><span style='background-color:#d1e7dd; color:#0f5132; padding:6px 10px; border-radius:4px; font-weight:bold; font-size:12px;'>✅ Current</span></div>"
                
                cols[3].markdown(f"{header_html}{badge_html}", unsafe_allow_html=True)
            except Exception:
                cols[3].markdown("<div style='font-size: 14px; margin-bottom: 10px; color: #31333F;'>Aging</div><div style='text-align:center;'><span style='background-color:#cbd5e1; color:#1e293b; padding:6px 10px; border-radius:4px; font-size:12px;'>-</span></div>", unsafe_allow_html=True)
                is_red = False

            curr_by = cols[4].text_input("Verified By", value=stored_by, key=f"by_{prefix_key}_{CURRENT_DATE}_{st.session_state['refresh_counter']}")
            curr_notes = cols[5].text_input("Notes/Explanations", value=stored_notes, key=f"notes_{prefix_key}_{CURRENT_DATE}_{st.session_state['refresh_counter']}")
            
            form_states[db_prefix] = {
                "label": label, "status": curr_status, "odt": str(curr_odt), "tdt": str(curr_tdt),
                "by": curr_by, "notes": curr_notes, "is_red": is_red, "delta": date_delta
            }

        # Render rows sequentially safely
        render_checklist_row("14 Day Return Queue Checked", "return_fourteen_queue", "ret_14")
        render_checklist_row("AI /Tech Check Queue Checked", "ai_tech_check", "ai_tch")
        render_checklist_row("Billing Queue Checked", "billing", "bill")
        render_checklist_row("Central Fill Queue Checked", "central_fill_queue", "c_fill")
        render_checklist_row("Data Re-Entry Checked", "data_re_entry", "re_ent")
        render_checklist_row("Dispense Queue Checked", "dispense", "disp")
        render_checklist_row("ERx Queue Checked-Any Rx from previous day?", "erx_queue", "erx_chk")
        render_checklist_row("Future Bill Queue Checked", "future_bill", "fut")
        render_checklist_row("On Hold Queue Checked", "on_hold_queue", "on_hld")
        render_checklist_row("Ordering Queue Checked", "ordering", "ord")
        render_checklist_row("Prior Authorization Queue", "pa_queue", "pa")
        render_checklist_row("Rejection Queue Checked", "rejection_queue", "rej")
        render_checklist_row("Untransmitted Claims Completed", "untransmitted_claims", "untrans")

        st.markdown("<br>", unsafe_allow_html=True)
        
        # --- BATCH REPORT SAVE & COMPILATION TRIGGER BUTTON ---
        if st.button("💾 Submit Daily Verification Report", type="primary", use_container_width=True, key=f"submit_daily_report_btn_{st.session_state['refresh_counter']}"):
            up_cursor = conn.cursor()
            deficiency_list = []
            
            for db_field, data in form_states.items():
                up_cursor.execute(f"""
                    UPDATE daily_checklist 
                    SET {db_field}=?, {db_field}_date=?, {db_field}_target=?, {db_field}_by=?, {db_field}_notes=? 
                    WHERE log_date=?
                """, (data["status"], data["odt"], data["tdt"], data["by"], data["notes"], CURRENT_DATE))
                
                if data["status"] == "No" or data["is_red"]:
                    flag_reason = "⚠️ STATUS: NO" if data["status"] == "No" else "🚨 CRITICAL AGING"
                    notes_str = f" (Notes: {data['by']} - {data['notes']})" if data['by'] or data['notes'] else ""
                    deficiency_list.append(f"• **{data['label']}**\n  ↳ Reason: {flag_reason} | Backlog: {data['delta']} Days{notes_str}")
            
            up_cursor.execute("UPDATE daily_checklist SET reminder_sent=1 WHERE log_date=?", (CURRENT_DATE,))
            conn.commit()
            
            if deficiency_list:
                compiled_violations = "\n\n".join(deficiency_list)
                if EASTERN_TZ:
                    ts_str = datetime.now(EASTERN_TZ).strftime('%H:%M:%S')
                else:
                    ts_str = datetime.now().strftime('%H:%M:%S')
                    
                unified_chat_payload = (
                    f"📋 **FACILITY OPERATIONS DAILY VERIFICATION REPORT**\n"
                    f"⏰ **Timestamp:** {ts_str} EST\n"
                    f"⚠️ *The following operational tracking points require attention:* \n\n"
                    f"{compiled_violations}"
                )
                dispatch_real_time_alert(unified_chat_payload)
                st.success("Verification data saved. Deficiency summary report compiled and pushed to Google Chat!")
            else:
                st.success("Verification metrics logged successfully! All operational channels are current.")
                
            time.sleep(0.5)
            st.session_state["refresh_counter"] += 1
            st.rerun()
