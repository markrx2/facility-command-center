import streamlit as st
import pandas as pd
import re
import hashlib
from datetime import datetime, timedelta, time as dtime
import time
from zoneinfo import ZoneInfo
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import json
from streamlit_autorefresh import st_autorefresh
from sqlalchemy import text, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

# --- 1. INITIAL SYSTEM ENGINE ARCHITECTURE & CONFIGURATION ---
st.set_page_config(
    page_title="Operational Metrics Sync Dashboard", 
    page_icon="⏱️", 
    layout="wide", 
    initial_sidebar_state="expanded"
)
# --- 2. ANTI-FADE & ANTI-BLUR UI OVERRIDE CORE ---
# Hardened structural style injectors to completely lock element states during heartbeat intervals.
st.markdown(
    """
    <style>
    /* 1. Global Opacity Preservation Matrix */
    div[data-testid="stMain"], 
    div[data-testid="stMain"] *, 
    div[data-testid="stBlock"], 
    div[data-testid="stBlock"] *,
    div[data-testid="element-container"],
    div[data-testid="element-container"] *,
    div[data-testid="stVerticalBlock"],
    div[data-testid="stVerticalBlock"] *,
    [data-baseweb="tab-panel"],
    [data-baseweb="tab-panel"] * {
        opacity: 1 !important;
        transition: none !important;
        animation: none !important;
        filter: none !important;
    }

    /* 2. Neutralize Streamlit's Default Rerun Transition Overlays */
    div[data-testid="stAppViewBlockContainer"] {
        opacity: 1 !important;
        transition: none !important;
    }

    /* 3. Freeze App Canvas & Block Structural Changes */
    .stApp, .stAppHeader, .stMainContainer, .stAppViewContainer {
        opacity: 1 !important;
        transition: none !important;
        animation: none !important;
    }

    /* 4. Suppress the Dynamic Top-Right Spinning Status Indicators */
    div[data-testid="stStatusWidget"] {
        display: none !important;
        visibility: hidden !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)
# Global browser heartbeat. Keeps the container awake and forces a full-script check cycle every 10 seconds.
# NOTE: this is what keeps things like the Analytics tab and backlog ribbon fresh, since those live
# outside any @st.fragment and only update on a full rerun.
st_autorefresh(interval=10000, key="global_system_heartbeat")

# Timezone Lock Configuration 
try:
    EASTERN_TZ = ZoneInfo("America/New_York")
except Exception:
    EASTERN_TZ = None

def get_current_eastern_date():
    if EASTERN_TZ:
        return datetime.now(EASTERN_TZ).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")

def now_eastern_naive():
    """
    Wall-clock 'now' in US/Eastern, returned as a naive datetime so it can be
    freely compared/subtracted against the naive timestamps we store in the DB
    (start_time, etc). Using this everywhere instead of raw datetime.now() keeps
    slot timers, escalation windows, and CURRENT_DATE all anchored to the same
    clock regardless of what timezone the host server actually runs in.
    """
    if EASTERN_TZ:
        return datetime.now(EASTERN_TZ).replace(tzinfo=None)
    return datetime.now()

CURRENT_DATE = get_current_eastern_date()

def fragment_rerun():
    """
    st.rerun(scope="fragment") requires Streamlit >= 1.37. If the deployed
    environment is on an older version, that call raises a TypeError -- which,
    combined with our try/except around DB writes, could make a successful
    submit look like it silently failed. This falls back to a normal full
    rerun so a version mismatch never eats a button click.
    """
    try:
        st.rerun(scope="fragment")
    except TypeError:
        st.rerun()

# Dynamic Supabase Database Matrix Initializer Engine passing clean parameters straight to the driver
# Cached as a resource: without this, every autorefresh/fragment tick (i.e. every few seconds, per
# open session) was re-running every CREATE TABLE statement and spinning up a brand-new SQLAlchemy
# Engine (and connection pool) from scratch, which both wastes DB connections and defeats pooling.
@st.cache_resource
def initialize_system_database():
    db_config = st.secrets["supabase_db"]
    
    # Establish a structured SQLAlchemy URL object instance to protect special character passwords
    url_object = URL.create(
        drivername="postgresql",
        username=db_config["username"],
        password=db_config["password"],
        host=db_config["host"],
        port=db_config["port"],
        database=db_config["database"],
        query={"sslmode": "require"}
    )
    
    # Instantiate custom engine configuration with clean structural pooling parameters
    engine = create_engine(url_object, pool_pre_ping=True, pool_recycle=300)
    
    # Map a standard context sessionmaker instance onto the connection engine
    class StreamlitSessionContextWrapper:
        def __init__(self, engine):
            self.Session = sessionmaker(bind=engine)
        @property
        def session(self):
            return self.Session()
            
    db_conn = StreamlitSessionContextWrapper(engine)
    
    with db_conn.session as session:
        # Roster mapping vectors
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS global_roster (
                dept_prefix TEXT,
                tech_name TEXT,
                tech_email TEXT,
                tech_webhook TEXT,
                PRIMARY KEY (dept_prefix, tech_name)
            )
        """))
        
        # Department execution queues matrix configuration
        tables = ["data_entry_slots", "call_center_slots", "shipping_slots", "fill_slots"]
        for t_name in tables:
            session.execute(text(f"""
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
            """))
            
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS dynamic_queues (
                dept_prefix TEXT,
                queue_name TEXT,
                goal_target TEXT,
                PRIMARY KEY (dept_prefix, queue_name)
            )
        """))
        
        session.execute(text("""
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
        """))
        
        session.execute(text("""
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
        """))
        
        session.execute(text("""
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
        """))
        session.commit()

        # Existing deployments already have this table without this column -- CREATE TABLE IF
        # NOT EXISTS above won't add it to a table that already exists, so add it explicitly.
        # Tracks when the daily verification was last submitted, so the submit button can warn
        # (and require explicit confirmation) before re-sending Chat alerts for the same day.
        session.execute(text("ALTER TABLE daily_checklist ADD COLUMN IF NOT EXISTS last_submitted_at TEXT DEFAULT ''"))
        session.commit()

        # --- AUTO-SCHEDULER SUPPORT TABLES ---
        # queue_volumes replaces the old fixed-9-field floor_backlogs ribbon going forward.
        # One row per (day, department, queue) so the ribbon can grow automatically as queues
        # are added/removed in Queue Management, instead of needing fixed columns per category.
        # floor_backlogs itself is intentionally left untouched (not dropped) in case that
        # historical data is still wanted -- this app just stops writing to it.
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS queue_volumes (
                log_date TEXT,
                dept_prefix TEXT,
                queue_name TEXT,
                volume INTEGER DEFAULT 0,
                PRIMARY KEY (log_date, dept_prefix, queue_name)
            )
        """))

        # One row per tech who is actually working today, with their shift window. Presence
        # in this table IS the "on shift today" signal -- a tech not listed here is treated
        # as not working today, regardless of whether they're in the permanent roster.
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS tech_shifts (
                log_date TEXT,
                dept_prefix TEXT,
                tech_name TEXT,
                shift_start TEXT,
                shift_end TEXT,
                PRIMARY KEY (log_date, dept_prefix, tech_name)
            )
        """))

        # Staging area for a generated schedule proposal, cleared and regenerated each time
        # "Generate/Recalculate Proposal" is clicked, and cleared again once approved & applied
        # to the real slot tables. Nothing here ever starts a real timer on its own.
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_proposals (
                log_date TEXT,
                dept_prefix TEXT,
                tech_name TEXT,
                proposal_slot INTEGER,
                queue_name TEXT,
                duration_minutes INTEGER,
                PRIMARY KEY (log_date, dept_prefix, tech_name, proposal_slot)
            )
        """))
        session.commit()

        # SELF-HEALING AUTOMATIC QUEUE RECOVERY SEEDER 
        res = session.execute(text("SELECT COUNT(*) as cnt FROM dynamic_queues")).fetchone()
        if res[0] == 0:
            default_queues = [
                {"prefix": "de", "name": "Standard Data Entry", "target": "40 rxs"},
                {"prefix": "de", "name": "Priority Intake", "target": "50 rxs"},
                {"prefix": "cc", "name": "Inbound Patient Queue", "target": "15 calls"},
                {"prefix": "cc", "name": "Outbound MD Escalations", "target": "10 calls"},
                {"prefix": "sh", "name": "Bulk Packout", "target": "60 orders"},
                {"prefix": "sh", "name": "Cold Chain Manifests", "target": "30 orders"},
                {"prefix": "fi", "name": "Primary Dispensing Line", "target": "45 rxs"},
                {"prefix": "fi", "name": "Specialty Compounding", "target": "15 rxs"}
            ]
            for dq in default_queues:
                session.execute(
                    text("INSERT INTO dynamic_queues (dept_prefix, queue_name, goal_target) VALUES (:prefix, :name, :target)"),
                    {"prefix": dq["prefix"], "name": dq["name"], "target": dq["target"]}
                )
            session.commit()
    return db_conn

db_conn = initialize_system_database()

# NOTE: "refresh_counter" was previously threaded into nearly every widget `key=`.
# Because the background fragment ticks every 5s and frequently flips state_changed=True
# (a timer expiring for ANY technician, a reminder firing, etc.), that counter was
# incrementing constantly -- which forced Streamlit to throw away and recreate every
# widget on the page every few seconds, including whatever a technician was mid-typing
# into a number_input. That's a real data-loss risk, so widget keys below are now stable
# (derived only from date/tech/slot/department) and the counter has been removed entirely.

# --- 2. MULTI-CHANNEL REAL-TIME NOTIFICATION MATRIX ENGINE ---
GOOGLE_CHAT_GLOBAL_OPERATIONS_WEBHOOK = st.secrets["google_chat"]["webhook_url"]

# Manager/admin password now comes from st.secrets rather than being hardcoded in source.
# To change it: edit the [admin] password value in your secrets.toml (or the Secrets panel
# on Streamlit Community Cloud) and reboot the app -- no code change needed.
ADMIN_PASSWORD = st.secrets["admin"]["password"]

# Homebase sync is optional, so a missing [homebase] secrets block doesn't crash the whole
# app -- it just leaves HOMEBASE_API_KEY as None, and the Sync button will say so instead.
try:
    HOMEBASE_API_KEY = st.secrets["homebase"]["api_key"]
    HOMEBASE_LOCATION_UUIDS = [u.strip() for u in str(st.secrets["homebase"].get("location_uuids", "")).split(",") if u.strip()]
except Exception:
    HOMEBASE_API_KEY = None
    HOMEBASE_LOCATION_UUIDS = []

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
    # NOTE: sender_identity / app_authentication_token are left exactly as provided
    # (out of scope for this pass) -- these should move into st.secrets before this
    # goes anywhere near production, since they're currently live credentials in source.
    sender_identity = "facility-tracker-automation@carepointrx.com"
    smtp_gateway_host = "smtp.gmail.com"
    smtp_gateway_port = 587
    app_authentication_token = "mvkj hgfd lpoi uytr"
    
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

# --- 3. UNIFIED GLOBAL BACKGROUND AUTOMATION MATRIX FRAGMENT ---
@st.fragment(run_every="5s")
def execution_global_background_automation_engine():
    current_now = now_eastern_naive()
    
    dept_mappings = [
        ("data_entry_slots", "de", "Data Entry"),
        ("call_center_slots", "cc", "Call Center"),
        ("shipping_slots", "sh", "Shipping"),
        ("fill_slots", "fi", "Fill")
    ]
    
    state_changed = False
    
    try:
        with db_conn.session as session:
            for table_name, prefix, label in dept_mappings:
                active_timers = session.execute(
                    text(f"SELECT * FROM {table_name} WHERE log_date = :c_date AND submitted = 0 AND start_time IS NOT NULL"),
                    {"c_date": CURRENT_DATE}
                ).fetchall()
                
                for row in active_timers:
                    worker = row.tech_name
                    slot_num = row.slot_id
                    db_start = row.start_time
                    db_dur_min = row.duration_minutes
                    db_t_not = row.tech_notified
                    db_s_not = row.supervisor_notified
                    
                    start_time = datetime.strptime(db_start, "%Y-%m-%d %H:%M:%S")
                    end_time = start_time + timedelta(minutes=db_dur_min)
                    escalation_time = end_time + timedelta(minutes=10)
                    fifteen_min_overdue_time = end_time + timedelta(minutes=15)
                    
                    if current_now >= end_time:
                        if db_t_not == 0:
                            roster_profile = session.execute(
                                text("SELECT tech_email, tech_webhook FROM global_roster WHERE dept_prefix = :pfx AND tech_name = :t_name"),
                                {"pfx": prefix, "t_name": worker}
                            ).fetchone()
                            
                            tech_email = roster_profile.tech_email if roster_profile else None
                            tech_webhook = roster_profile.tech_webhook if roster_profile else None
                            
                            if tech_email:
                                dispatch_individual_tech_notification(tech_email, worker, slot_num, label)
                            if tech_webhook:
                                dispatch_individual_chat_alert(tech_webhook, f"⏱️ **Timer Expired!**\nYour tracking block timer has ended for *{label}* (Slot {slot_num}).\n\nPlease log counts.")
                            dispatch_real_time_alert(f"⚠️ TIMER ALERT: {worker} reached zero on {label} Slot {slot_num} without metrics.")
                            
                            session.execute(
                                text(f"UPDATE {table_name} SET tech_notified = 1 WHERE log_date = :c_date AND tech_name = :t_name AND slot_id = :s_id"),
                                {"c_date": CURRENT_DATE, "t_name": worker, "s_id": slot_num}
                            )
                            state_changed = True
                        
                        if current_now >= escalation_time and db_s_not == 0:
                            dispatch_real_time_alert(f"🚨 CRITICAL ESCALATION: {worker} missed metrics window for {label} Slot {slot_num}.")
                            session.execute(
                                text(f"UPDATE {table_name} SET supervisor_notified = 1 WHERE log_date = :c_date AND tech_name = :t_name AND slot_id = :s_id"),
                                {"c_date": CURRENT_DATE, "t_name": worker, "s_id": slot_num}
                            )
                            state_changed = True
                            
                        if current_now >= fifteen_min_overdue_time and db_s_not < 2:
                            dispatch_real_time_alert(f"⏰ **🚨 OVERDUE METRICS CRITICAL ALERT** 🚨 ⏰\nTechnician: {worker.upper()}\nDepartment: {label}\nSlot: {slot_num} | Status: **Missing counts 15m+ post-deadline.**")
                            session.execute(
                                text(f"UPDATE {table_name} SET supervisor_notified = 2 WHERE log_date = :c_date AND tech_name = :t_name AND slot_id = :s_id"),
                                {"c_date": CURRENT_DATE, "t_name": worker, "s_id": slot_num}
                            )
                            state_changed = True

            chk_row = session.execute(
                text("SELECT reminder_time, reminder_sent, supervisor_escaped FROM daily_checklist WHERE log_date = :c_date"),
                {"c_date": CURRENT_DATE}
            ).fetchone()
            
            if chk_row:
                try:
                    t_obj = datetime.strptime(chk_row.reminder_time, "%H:%M").time()
                    current_time_now = datetime.now(EASTERN_TZ) if EASTERN_TZ else datetime.now()
                    deadline_datetime = datetime.combine(current_time_now.date(), t_obj)
                    if EASTERN_TZ:
                        deadline_datetime = deadline_datetime.replace(tzinfo=EASTERN_TZ)
                        
                    dilation_deadline = deadline_datetime + timedelta(minutes=30)
                    
                    if current_time_now >= deadline_datetime and chk_row.reminder_sent == 0:
                        initial_warning_msg = (
                            f"📋 **FACILITY OPERATIONS REQUIREMENT REMINDER**\n\n"
                            f"The **Global Facility Daily Queue Verification Log** deadline has been reached.\n"
                            f"⏳ **Target Deadline:** {chk_row.reminder_time} EST\n"
                            f"⚠️ *Please ensure all daily backlogs and checklist audits are finalized and submitted.*"
                        )
                        dispatch_real_time_alert(initial_warning_msg)
                        session.execute(text("UPDATE daily_checklist SET reminder_sent = 1 WHERE log_date = :c_date"), {"c_date": CURRENT_DATE})
                        state_changed = True
                        
                    if current_time_now >= dilation_deadline and chk_row.supervisor_escaped == 0:
                        escalation_chat_msg = (
                            f"⏰ **🚨 CRITICAL OPERATIONS ESCALATION** 🚨 ⏰\n\n"
                            f"The **Global Facility Daily Queue Verification Log** has NOT been submitted for today.\n"
                            f"⏳ **Target Deadline:** {chk_row.reminder_time} EST\n"
                            f"❌ **Status:** Overdue by 30+ minutes without supervisor sign-off.\n\n"
                            f"Please complete and log all verification vectors immediately."
                        )
                        dispatch_real_time_alert(escalation_chat_msg)
                        session.execute(text("UPDATE daily_checklist SET supervisor_escaped = 1 WHERE log_date = :c_date"), {"c_date": CURRENT_DATE})
                        state_changed = True
                except Exception as e:
                    print(f"Checklist Background Engine Processing Error: {str(e)}")

            if state_changed:
                session.commit()
    except Exception as e:
        # DB hiccups here should never take the whole app down -- this fragment just
        # skips this tick and quietly retries on the next 5s cycle.
        print(f"Background Automation Engine DB Error: {str(e)}")
        return

    # Deliberately NOT calling a rerun here, even when state_changed is True. This fragment
    # already re-executes every 5s on its own via run_every="5s", so an immediate rerun only
    # saves a few seconds of display lag -- but if scope="fragment" isn't supported by the
    # deployed Streamlit version, fragment_rerun()'s fallback becomes a FULL PAGE rerun firing
    # from a background loop (not a user click). That can land at any moment and wipe out
    # whatever a user was just doing elsewhere (e.g. a just-shown success message on the daily
    # checklist submit, or a mid-click on an unrelated button). Letting the next scheduled
    # 5s tick pick up the change avoids that risk entirely.

execution_global_background_automation_engine()

# --- 4. GLOBAL SIDEBAR MANAGEMENT CONTROL HUB ---
st.sidebar.header("🔐 Global System Control Deck")
pwd_input = st.sidebar.text_input("Enter Manager Override Password:", type="password", key="mgr_pwd_input_field")
is_manager = pwd_input == ADMIN_PASSWORD

if is_manager:
    st.sidebar.success("🔑 Admin Privileges Active")
elif pwd_input != "":
    st.sidebar.error("❌ Incorrect Password")

st.sidebar.markdown("---")
st.sidebar.subheader("➕ Quick Add Personnel to Floor")

with db_conn.session as session:
    saved_profiles = session.execute(text("SELECT tech_name, tech_email, tech_webhook FROM global_roster ORDER BY tech_name ASC")).fetchall()

profile_options = ["-- Create New Profile --"] + [p.tech_name for p in saved_profiles]

if "selected_profile_state" not in st.session_state:
    st.session_state["selected_profile_state"] = "-- Create New Profile --"

current_index = profile_options.index(st.session_state["selected_profile_state"]) if st.session_state["selected_profile_state"] in profile_options else 0
selected_profile = st.sidebar.selectbox("Select Existing Profile (Optional):", options=profile_options, index=current_index)
st.session_state["selected_profile_state"] = selected_profile

default_name, default_email, default_webhook = "", "", ""
if selected_profile != "-- Create New Profile --":
    matched_profile = next((p for p in saved_profiles if p.tech_name == selected_profile), None)
    if matched_profile:
        default_name = matched_profile.tech_name
        default_email = matched_profile.tech_email
        default_webhook = matched_profile.tech_webhook

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

with st.sidebar.form(key="sidebar_personnel_deployment_form", clear_on_submit=True):
    dest_dept = st.selectbox("Assign to Department:", options=[
        ("Data Entry", "de"), ("Call Center", "cc"), ("Shipping", "sh"), ("Fill", "fi")
    ], format_func=lambda x: x[0])

    new_worker_name = st.text_input("Employee Full Name:", value=default_name, placeholder="John Doe").strip()
    new_worker_email = st.text_input("Employee Workspace Email:", value=default_email, placeholder="johndoe@company.com").strip()
    new_worker_webhook = st.text_input("Employee Personal Google Chat Webhook:", value=default_webhook, placeholder="https://chat.googleapis.com/v1/spaces/...").strip()
    
    submit_deployment = st.form_submit_button("Deploy to Department Grid", type="primary", use_container_width=True)

if submit_deployment:
    if not new_worker_name or not new_worker_email:
        st.sidebar.warning("Please input both name and email routing vectors.")
    elif not EMAIL_PATTERN.match(new_worker_email):
        st.sidebar.warning("That doesn't look like a valid email address -- please double check it.")
    else:
        try:
            with db_conn.session as session:
                session.execute(text("""
                    INSERT INTO global_roster (dept_prefix, tech_name, tech_email, tech_webhook) 
                    VALUES (:prefix, :name, :email, :webhook)
                    ON CONFLICT (dept_prefix, tech_name) DO UPDATE 
                    SET tech_email = EXCLUDED.tech_email, tech_webhook = EXCLUDED.tech_webhook
                """), {"prefix": dest_dept[1], "name": new_worker_name, "email": new_worker_email, "webhook": new_worker_webhook})
                session.commit()
            st.session_state["selected_profile_state"] = "-- Create New Profile --"
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"⚠️ Couldn't save this profile right now: {str(e)}")

# --- 5. DYNAMIC QUEUE VOLUME RIBBON (auto-scheduler input) ---
# Replaces the old fixed-9-field ribbon. Instead of hardcoded categories, this mirrors
# whatever queues currently exist in Queue Management, grouped by department -- so adding
# a new queue (or a whole new department's queues) there automatically gives it a volume
# field here too, with no code changes needed. This is also the volume feed the
# auto-scheduler reads from. The old floor_backlogs table is left alone in the DB
# (still there if historical data is wanted) but nothing writes to it anymore.
DEPT_LABELS = {"de": "Data Entry", "cc": "Call Center", "sh": "Shipping", "fi": "Fill"}

def render_dynamic_volume_ribbon():
    with db_conn.session as session:
        all_queues = session.execute(text("SELECT dept_prefix, queue_name, goal_target FROM dynamic_queues ORDER BY dept_prefix, queue_name")).fetchall()
        vol_rows = session.execute(text("SELECT dept_prefix, queue_name, volume FROM queue_volumes WHERE log_date=:c_date"), {"c_date": CURRENT_DATE}).fetchall()

    if not all_queues:
        st.info("💡 No queues configured yet. Add queues in the Queue Management tab to start tracking daily volume here.")
        return

    volume_lookup = {(r.dept_prefix, r.queue_name): r.volume for r in vol_rows}

    st.markdown("<h4 style='color: #1e3a8a; font-size:15px; margin-bottom:4px;'>📊 Today's Queue Volume (start-of-day counts, editable anytime)</h4>", unsafe_allow_html=True)

    queues_by_dept = {}
    for q in all_queues:
        queues_by_dept.setdefault(q.dept_prefix, []).append(q)

    updates = {}
    for dept_prefix, dept_queues in queues_by_dept.items():
        dept_label = DEPT_LABELS.get(dept_prefix, dept_prefix)
        st.caption(f"**{dept_label}**")
        num_cols = min(len(dept_queues), 6) or 1
        cols = st.columns(num_cols)
        for i, q in enumerate(dept_queues):
            with cols[i % num_cols]:
                current_value = volume_lookup.get((dept_prefix, q.queue_name), 0)
                new_val = st.number_input(q.queue_name, min_value=0, step=1, value=int(current_value), key=f"vol_{dept_prefix}_{q.queue_name}_{CURRENT_DATE}")
                if new_val != current_value:
                    updates[(dept_prefix, q.queue_name)] = new_val

    if updates:
        try:
            with db_conn.session as session:
                for (dept_prefix, queue_name), val in updates.items():
                    session.execute(text("""
                        INSERT INTO queue_volumes (log_date, dept_prefix, queue_name, volume)
                        VALUES (:c_date, :pfx, :qname, :vol)
                        ON CONFLICT (log_date, dept_prefix, queue_name) DO UPDATE SET volume = EXCLUDED.volume
                    """), {"c_date": CURRENT_DATE, "pfx": dept_prefix, "qname": queue_name, "vol": val})
                session.commit()
            st.rerun()
        except Exception as e:
            st.error(f"⚠️ Couldn't save volume numbers right now: {str(e)}")
    st.markdown("<hr style='margin: 8px 0px 14px 0px !important; border-top: 2px solid #cbd5e1;'>", unsafe_allow_html=True)

# --- 6. RENDERING ENGINE FOR WORKER GRID ROWS ---
@st.fragment(run_every="5s")
def render_synchronized_matrix(db_table, prefix, dept_label):
    with db_conn.session as session:
        goals_dict = {r.queue_name: r.goal_target for r in session.execute(text("SELECT queue_name, goal_target FROM dynamic_queues WHERE dept_prefix = :pfx"), {"pfx": prefix}).fetchall()}
        roster_rows = session.execute(text("SELECT tech_name, tech_email, tech_webhook FROM global_roster WHERE dept_prefix = :pfx"), {"pfx": prefix}).fetchall()
        # Batched: one query for every slot in this department/day, instead of a separate
        # round trip per worker per slot below. With N workers x 4 slots, the old per-slot
        # query pattern meant N*4 sequential DB calls on every single render of this fragment
        # -- which fires on every button click inside it, plus automatically every 5s. This
        # was very likely the dominant source of the "lag on every submit" you were seeing.
        all_slot_rows = session.execute(text(f"SELECT * FROM {db_table} WHERE log_date=:c_date"), {"c_date": CURRENT_DATE}).fetchall()

    slot_lookup = {(r.tech_name, r.slot_id): r for r in all_slot_rows}
    active_roster = {row.tech_name: {"email": row.tech_email, "webhook": row.tech_webhook} for row in roster_rows}

    if not active_roster:
        st.info(f"💡 No personnel assigned to {dept_label} currently. Use the left sidebar panel to assign employees to this department.")
        return

    is_mgr_active = st.session_state.get("mgr_pwd_input_field") == ADMIN_PASSWORD

    for worker, tech_profiles in active_roster.items():
        w_id = hashlib.md5(worker.encode('utf-8')).hexdigest()[:8]
        tech_email = tech_profiles["email"]
        
        st.markdown(f"### 👤 TECHNICIAN: {worker.upper()} `({tech_email if tech_email else 'No Email Set'})`")
        
        if is_mgr_active:
            if st.button(f"🚨 Wipe Profile & Timers for {worker} from {dept_label}", key=f"mgr_wipe_personnel_{prefix}_{w_id}"):
                try:
                    with db_conn.session as session:
                        session.execute(text(f"DELETE FROM {db_table} WHERE log_date=:c_date AND tech_name=:t_name"), {"c_date": CURRENT_DATE, "t_name": worker})
                        session.execute(text("DELETE FROM global_roster WHERE dept_prefix=:pfx AND tech_name=:t_name"), {"pfx": prefix, "t_name": worker})
                        session.commit()
                    st.session_state["selected_profile_state"] = "-- Create New Profile --"
                    # Full rerun (not fragment-scoped): this changes global_roster, which the
                    # sidebar's profile dropdown reads from, and the sidebar lives outside this fragment.
                    st.rerun()
                except Exception as e:
                    st.error(f"⚠️ Couldn't wipe this profile right now: {str(e)}")

        cols = st.columns(4)
        
        for slot_num in range(1, 5):
            with cols[slot_num - 1]:
                with st.container(border=True):
                    st.markdown(f"**🕒 Slot {slot_num}**")
                    
                    slot_row = slot_lookup.get((worker, slot_num))
                    
                    if is_mgr_active:
                        admin_btn_col1, admin_btn_col2 = st.columns(2)
                        
                        if admin_btn_col1.button("🔴 Reset Slot", key=f"admin_slot_rst_{prefix}_{w_id}_{slot_num}", use_container_width=True, type="secondary"):
                            try:
                                with db_conn.session as session:
                                    if slot_num == 1:
                                        session.execute(text("DELETE FROM global_roster WHERE dept_prefix=:pfx AND tech_name=:t_name"), {"pfx": prefix, "t_name": worker})
                                        session.execute(text(f"DELETE FROM {db_table} WHERE log_date=:c_date AND tech_name=:t_name"), {"c_date": CURRENT_DATE, "t_name": worker})
                                    else:
                                        session.execute(text(f"""
                                            UPDATE {db_table} 
                                            SET queue=NULL, goal=NULL, start_time=NULL, duration_minutes=60, input_number=NULL, 
                                                tech_notified=0, supervisor_notified=0, submitted=0 
                                            WHERE log_date=:c_date AND tech_name=:t_name AND slot_id=:s_id
                                        """), {"c_date": CURRENT_DATE, "t_name": worker, "s_id": slot_num})
                                    session.commit()
                                
                                for key in [f"num_{prefix}_{w_id}_{slot_num}", f"q_{prefix}_{w_id}_{slot_num}", f"dur_{prefix}_{w_id}_{slot_num}"]:
                                    if key in st.session_state: del st.session_state[key]

                                if slot_num == 1:
                                    # This branch also deletes the roster row -> sidebar dropdown needs a full refresh.
                                    st.rerun()
                                else:
                                    fragment_rerun()
                            except Exception as e:
                                st.error(f"⚠️ Couldn't reset this slot right now: {str(e)}")
                            
                        if admin_btn_col2.button("🔄 Force Clock Reset", key=f"admin_clk_rst_{prefix}_{w_id}_{slot_num}", use_container_width=True, type="secondary", disabled=(slot_row is None or slot_row.start_time is None)):
                            if slot_row is not None and slot_row.start_time is not None:
                                now_reset_str = now_eastern_naive().strftime("%Y-%m-%d %H:%M:%S")
                                try:
                                    with db_conn.session as session:
                                        session.execute(text(f"UPDATE {db_table} SET start_time=:st, tech_notified=0, supervisor_notified=0, submitted=0 WHERE log_date=:c_date AND tech_name=:t_name AND slot_id=:s_id"), {"st": now_reset_str, "c_date": CURRENT_DATE, "t_name": worker, "s_id": slot_num})
                                        session.commit()
                                    fragment_rerun()
                                except Exception as e:
                                    st.error(f"⚠️ Couldn't reset this clock right now: {str(e)}")
                    
                    if not slot_row or slot_row.queue is None:
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
                                scaled_num = int(base_num * (float(chosen_dur_min) / 60.0))
                                calculated_goal_str = f"{scaled_num} {text_suffix}".strip()
                            else:
                                calculated_goal_str = base_goal_str
                                
                            st.caption(f"🎯 Scheduled Target: **{calculated_goal_str}** *(Base: {base_goal_str}/hr)*")
                            
                            if st.button("🚀 Start Clock", key=f"str_{prefix}_{w_id}_{slot_num}", use_container_width=True):
                                now_str = now_eastern_naive().strftime("%Y-%m-%d %H:%M:%S")
                                try:
                                    with db_conn.session as session:
                                        session.execute(text(f"""
                                            INSERT INTO {db_table} 
                                            (log_date, tech_name, slot_id, queue, goal, start_time, duration_minutes, input_number, tech_notified, supervisor_notified, submitted) 
                                            VALUES (:c_date, :t_name, :s_id, :queue, :goal, :st, :dur, NULL, 0, 0, 0)
                                            ON CONFLICT (log_date, tech_name, slot_id) DO UPDATE 
                                            SET queue=EXCLUDED.queue, goal=EXCLUDED.goal, start_time=EXCLUDED.start_time, duration_minutes=EXCLUDED.duration_minutes, submitted=0, input_number=NULL
                                        """), {"c_date": CURRENT_DATE, "t_name": worker, "s_id": slot_num, "queue": chosen_q, "goal": base_goal_str, "st": now_str, "dur": chosen_dur_min})
                                        session.commit()
                                    # Local to this slot/fragment -- no need to force a full-page rerun.
                                    fragment_rerun()
                                except Exception as e:
                                    st.error(f"⚠️ Couldn't start this clock right now: {str(e)}")
                        else:
                            st.warning("Configure queues in Management panel.")
                    else:
                        db_queue, db_goal, db_start, db_input = slot_row.queue, slot_row.goal, slot_row.start_time, slot_row.input_number
                        db_t_not, db_s_not, db_sub, db_dur_min = slot_row.tech_notified, slot_row.supervisor_notified, slot_row.submitted, slot_row.duration_minutes
                        
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
                        escalation_time = end_time + timedelta(minutes=10)
                        current_now = now_eastern_naive()
                        
                        if current_now < end_time and not db_sub:
                            rem = end_time - current_now
                            total_rem_seconds = int(rem.total_seconds())
                            h, r = divmod(total_rem_seconds, 3600)
                            m, s = divmod(r, 60)
                            st.metric(label="⏳ Time Remaining", value=f"{int(h):02d}:{int(m):02d}:{int(s):02d}")
                            st.progress(1.0 - (float(total_rem_seconds) / (float(db_dur_min) * 60.0)))
                        elif not db_sub:
                            st.error("🛑 Timer Expired!")
                        
                        if current_now >= escalation_time and not db_sub:
                            if db_s_not == 1: st.error("🚨 Supervisor alert sent to Google Chat.")
                            elif db_s_not == 2: st.error("🚨 CRITICAL: Past 15-Minute Deadline Notification Dispatched.")
                        
                        if not db_sub:
                            val = st.number_input("Log Production Volume:", min_value=0, step=1, value=None, key=f"num_{prefix}_{w_id}_{slot_num}")
                            if st.button("Submit Metrics", key=f"sub_{prefix}_{w_id}_{slot_num}", type="primary", use_container_width=True) and val is not None:
                                time_logged_now = now_eastern_naive()
                                elapsed_delta = time_logged_now - start_time
                                actual_minutes_used = max(1, int(elapsed_delta.total_seconds() / 60.0))
                                
                                base_hourly_rate = 0
                                match_digits = re.search(r'\d+', str(db_goal))
                                if match_digits: base_hourly_rate = int(match_digits.group())
                                
                                dynamic_target_threshold = max(1, int(float(base_hourly_rate) * (float(actual_minutes_used) / 60.0)))
                                is_escalated = 1 if val < dynamic_target_threshold else 0
                                
                                if is_escalated:
                                    dispatch_real_time_alert(
                                        f"📉 **PRODUCTION ALERT: GOAL NOT MET (PRO-RATA)** 📉\n"
                                        f"👤 **Technician:** {worker.upper()}\n"
                                        f"🏢 **Department:** {dept_label}\n"
                                        f"⏱️ **Active Time Spent:** {actual_minutes_used} minutes\n"
                                        f"🎯 **Pro-Rata Target Expected:** {dynamic_target_threshold} units *(Based on {base_hourly_rate}/hr)*\n"
                                        f"📥 **Logged Production:** **{val}** units"
                                    )
                                
                                try:
                                    with db_conn.session as session:
                                        session.execute(text("""
                                            INSERT INTO metrics_history (log_date, department, tech_name, slot_id, queue, goal, input_number, escalated, timestamp, duration_minutes) 
                                            VALUES (:c_date, :dept, :t_name, :s_id, :queue, :goal, :val, :esc, :ts, :dur)
                                        """), {"c_date": CURRENT_DATE, "dept": dept_label, "t_name": worker, "s_id": slot_num, "queue": db_queue, "goal": db_goal, "val": val, "esc": is_escalated, "ts": time_logged_now.strftime("%Y-%m-%d %H:%M:%S"), "dur": actual_minutes_used})
                                        
                                        session.execute(text(f"""
                                            UPDATE {db_table} SET input_number=:val, submitted=1 
                                            WHERE log_date=:c_date AND tech_name=:t_name AND slot_id=:s_id
                                        """), {"val": val, "c_date": CURRENT_DATE, "t_name": worker, "s_id": slot_num})
                                        session.commit()
                                    # Local to this slot -- the Analytics tab will pick up the new
                                    # metrics_history row on the next full-page heartbeat (every 10s).
                                    fragment_rerun()
                                except Exception as e:
                                    st.error(f"⚠️ Couldn't save these metrics right now: {str(e)}")
                        else:
                            st.success(f"✅ Logged Units: **{db_input}**")

# --- 7. CORE APP ROUTING INTERFACE ---
render_dynamic_volume_ribbon()

tab_de, tab_cc, tab_sh, tab_fi, tab_sched, tab_analytics, tab_mgmt = st.tabs([
    "💻 Data Entry Line", "📞 Call Center Desk", "📦 Shipping Floor", "🧪 Fill Department", "🗓️ Auto-Scheduler", "📊 Cumulative Analytics", "⚙️ Queue Management"
])

with tab_de: render_synchronized_matrix("data_entry_slots", "de", "Data Entry")
with tab_cc: render_synchronized_matrix("call_center_slots", "cc", "Call Center")
with tab_sh: render_synchronized_matrix("shipping_slots", "sh", "Shipping")
with tab_fi: render_synchronized_matrix("fill_slots", "fi", "Fill")

# --- 7.5 AUTO-SCHEDULER TAB ---
# Scoped to Data Entry only for now (AUTOSCHEDULER_DEPTS below), but every function here is
# parameterized by dept_prefix/db_table so extending to another department later is just
# adding its prefix to this list -- no rewrite needed.
AUTOSCHEDULER_DEPTS = [("de", "data_entry_slots", "Data Entry")]

SHIFT_PRESETS = {
    "7:00 AM - 3:00 PM": (dtime(7, 0), dtime(15, 0)),
    "9:00 AM - 5:00 PM": (dtime(9, 0), dtime(17, 0)),
    "10:00 AM - 6:00 PM": (dtime(10, 0), dtime(18, 0)),
}

def parse_hourly_rate(goal_str):
    m = re.search(r'\d+', str(goal_str))
    return int(m.group()) if m else 0

def normalize_name(s):
    return re.sub(r'\s+', ' ', str(s)).strip().lower()

def fetch_homebase_shifts(location_uuid, date_str):
    """
    GET /locations/{location_uuid}/shifts for a single day. Handles pagination via the
    RFC-5988 Link header. Assumes the list endpoint returns a bare JSON array (per standard
    REST/Swagger convention when pagination metadata lives in headers rather than a wrapper
    object) but defensively unwraps a {"shifts": [...]}-style response if that's what comes
    back instead -- unverified against a live response as of writing this.
    """
    headers = {
        "Authorization": f"Bearer {HOMEBASE_API_KEY}",
        "Accept": "application/vnd.homebase-v1+json",
    }
    all_shifts = []
    url = f"https://api.joinhomebase.com/locations/{location_uuid}/shifts"
    params = {"start_date": date_str, "end_date": date_str, "date_filter": "start_at", "per_page": 100, "page": 1}

    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            all_shifts.extend(data)
        elif isinstance(data, dict) and isinstance(data.get("shifts"), list):
            all_shifts.extend(data["shifts"])
        else:
            all_shifts.append(data)

        next_url = None
        for part in resp.headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
        url = next_url
        params = None  # the next_url from the Link header already has its own query string

    return all_shifts

def sync_homebase_shifts(dept_prefix):
    """
    Pulls today's shifts from every configured Homebase location, matches each shift to an
    existing roster tech by normalized name (not by trusting Homebase's department/role
    field, which we haven't verified matches our department taxonomy), and upserts matches
    into tech_shifts. Returns (result_dict, error_string) -- exactly one will be None.
    """
    if not HOMEBASE_API_KEY or not HOMEBASE_LOCATION_UUIDS:
        return None, "Homebase isn't configured yet. Add [homebase] api_key and location_uuids to your secrets file."

    with db_conn.session as session:
        roster_rows = session.execute(text("SELECT tech_name FROM global_roster WHERE dept_prefix=:pfx"), {"pfx": dept_prefix}).fetchall()
    roster_lookup = {normalize_name(r.tech_name): r.tech_name for r in roster_rows}

    all_shifts = []
    try:
        for loc_uuid in HOMEBASE_LOCATION_UUIDS:
            all_shifts.extend(fetch_homebase_shifts(loc_uuid, CURRENT_DATE))
    except Exception as e:
        return None, f"Homebase API request failed: {str(e)}"

    matched = {}
    for shift in all_shifts:
        full_name = normalize_name(f"{shift.get('first_name', '')} {shift.get('last_name', '')}")
        if full_name in roster_lookup and shift.get("start_at") and shift.get("end_at"):
            try:
                start_dt_utc = datetime.fromisoformat(str(shift["start_at"]).replace("Z", "+00:00"))
                end_dt_utc = datetime.fromisoformat(str(shift["end_at"]).replace("Z", "+00:00"))
            except Exception:
                continue
            if EASTERN_TZ:
                start_local = start_dt_utc.astimezone(EASTERN_TZ)
                end_local = end_dt_utc.astimezone(EASTERN_TZ)
            else:
                start_local, end_local = start_dt_utc, end_dt_utc
            matched[roster_lookup[full_name]] = (start_local.strftime("%H:%M"), end_local.strftime("%H:%M"))

    unmatched_names = sorted(set(
        f"{s.get('first_name', '')} {s.get('last_name', '')}".strip()
        for s in all_shifts
        if normalize_name(f"{s.get('first_name', '')} {s.get('last_name', '')}") not in roster_lookup
    ))

    if matched:
        try:
            with db_conn.session as session:
                for tech_name, (s_str, e_str) in matched.items():
                    session.execute(text("""
                        INSERT INTO tech_shifts (log_date, dept_prefix, tech_name, shift_start, shift_end)
                        VALUES (:c_date, :pfx, :t_name, :s_start, :s_end)
                        ON CONFLICT (log_date, dept_prefix, tech_name) DO UPDATE SET shift_start=EXCLUDED.shift_start, shift_end=EXCLUDED.shift_end
                    """), {"c_date": CURRENT_DATE, "pfx": dept_prefix, "t_name": tech_name, "s_start": s_str, "s_end": e_str})
                session.commit()
        except Exception as e:
            return None, f"Fetched from Homebase but couldn't save the results: {str(e)}"

    return {"matched": matched, "unmatched_names": unmatched_names, "total_fetched": len(all_shifts)}, None

def generate_schedule_proposal(dept_prefix, reference_dt):
    """
    Computes a proposed schedule for `dept_prefix` as of `reference_dt` (a naive Eastern
    datetime -- either today's 1:00 PM anchor on the standard run, or "now" on a manual
    recalculation) and saves it to schedule_proposals. Returns a summary dict for display;
    nothing here touches the real slot tables.
    """
    with db_conn.session as session:
        shift_rows = session.execute(text("SELECT tech_name, shift_start, shift_end FROM tech_shifts WHERE log_date=:c_date AND dept_prefix=:pfx"), {"c_date": CURRENT_DATE, "pfx": dept_prefix}).fetchall()
        queue_rows = session.execute(text("SELECT queue_name, goal_target FROM dynamic_queues WHERE dept_prefix=:pfx"), {"pfx": dept_prefix}).fetchall()
        volume_rows = session.execute(text("SELECT queue_name, volume FROM queue_volumes WHERE log_date=:c_date AND dept_prefix=:pfx"), {"c_date": CURRENT_DATE, "pfx": dept_prefix}).fetchall()

    volumes = {r.queue_name: r.volume for r in volume_rows}
    rates = {r.queue_name: parse_hourly_rate(r.goal_target) for r in queue_rows}

    required_minutes = {}
    for queue_name, rate in rates.items():
        vol = volumes.get(queue_name, 0)
        if rate > 0 and vol > 0:
            required_minutes[queue_name] = (vol / rate) * 60.0

    tech_capacity = []
    for row in shift_rows:
        shift_start_dt = datetime.combine(reference_dt.date(), datetime.strptime(row.shift_start, "%H:%M").time())
        shift_end_dt = datetime.combine(reference_dt.date(), datetime.strptime(row.shift_end, "%H:%M").time())
        effective_start = max(shift_start_dt, reference_dt)
        remaining = (shift_end_dt - effective_start).total_seconds() / 60.0
        if remaining > 0:
            tech_capacity.append({"tech": row.tech_name, "remaining": remaining, "slots_used": 0})

    total_capacity = sum(t["remaining"] for t in tech_capacity)
    total_required = sum(required_minutes.values())

    summary = {"total_capacity": total_capacity, "total_required": total_required, "unmet": {}, "no_shift_data": len(tech_capacity) == 0, "no_volume_data": len(required_minutes) == 0}

    with db_conn.session as session:
        session.execute(text("DELETE FROM schedule_proposals WHERE log_date=:c_date AND dept_prefix=:pfx"), {"c_date": CURRENT_DATE, "pfx": dept_prefix})

        if total_required > 0 and total_capacity > 0:
            scale = min(1.0, total_capacity / total_required)
            allocations = sorted(
                [[name, req * scale] for name, req in required_minutes.items()],
                key=lambda x: x[1], reverse=True
            )
            for name, req in required_minutes.items():
                unmet_amt = req - (req * scale)
                if unmet_amt > 0.5:
                    summary["unmet"][name] = round(unmet_amt)

            for queue_name, alloc_minutes in allocations:
                remaining_alloc = alloc_minutes
                while remaining_alloc > 0.5:
                    eligible = [t for t in tech_capacity if t["remaining"] > 0.5 and t["slots_used"] < 4]
                    if not eligible:
                        summary["unmet"][queue_name] = summary["unmet"].get(queue_name, 0) + round(remaining_alloc)
                        break
                    pick = max(eligible, key=lambda t: t["remaining"])
                    chunk = min(remaining_alloc, pick["remaining"])
                    chunk_rounded = max(5, round(chunk / 5.0) * 5)
                    chunk_rounded = min(chunk_rounded, pick["remaining"])
                    pick["slots_used"] += 1
                    session.execute(text("""
                        INSERT INTO schedule_proposals (log_date, dept_prefix, tech_name, proposal_slot, queue_name, duration_minutes)
                        VALUES (:c_date, :pfx, :t_name, :slot, :queue, :dur)
                    """), {"c_date": CURRENT_DATE, "pfx": dept_prefix, "t_name": pick["tech"], "slot": pick["slots_used"], "queue": queue_name, "dur": int(chunk_rounded)})
                    pick["remaining"] -= chunk_rounded
                    remaining_alloc -= chunk_rounded
        session.commit()

    summary["unused_capacity"] = round(sum(t["remaining"] for t in tech_capacity))
    return summary

def apply_schedule_proposal(dept_prefix, db_table):
    """Writes an approved proposal into the real slot table -- starts real timers. Skips
    slots that are already occupied by an active (non-submitted) assignment rather than
    clobbering a tech's in-progress work, and reports anything it had to skip."""
    skipped = []
    with db_conn.session as session:
        queue_rows = session.execute(text("SELECT queue_name, goal_target FROM dynamic_queues WHERE dept_prefix=:pfx"), {"pfx": dept_prefix}).fetchall()
        rate_strings = {r.queue_name: r.goal_target for r in queue_rows}
        proposal_rows = session.execute(text("SELECT tech_name, proposal_slot, queue_name, duration_minutes FROM schedule_proposals WHERE log_date=:c_date AND dept_prefix=:pfx ORDER BY tech_name, proposal_slot"), {"c_date": CURRENT_DATE, "pfx": dept_prefix}).fetchall()

        by_tech = {}
        for r in proposal_rows:
            by_tech.setdefault(r.tech_name, []).append(r)

        now_str = now_eastern_naive().strftime("%Y-%m-%d %H:%M:%S")

        for tech_name, rows in by_tech.items():
            existing = session.execute(text(f"SELECT slot_id, queue, submitted FROM {db_table} WHERE log_date=:c_date AND tech_name=:t_name"), {"c_date": CURRENT_DATE, "t_name": tech_name}).fetchall()
            occupied = {e.slot_id for e in existing if e.queue is not None and e.submitted == 0}
            free_slots = [s for s in range(1, 5) if s not in occupied]

            for row in rows:
                if not free_slots:
                    skipped.append(f"{tech_name}: no free slot left for {row.queue_name}")
                    continue
                target_slot = free_slots.pop(0)
                goal_str = rate_strings.get(row.queue_name, "")
                session.execute(text(f"""
                    INSERT INTO {db_table} (log_date, tech_name, slot_id, queue, goal, start_time, duration_minutes, input_number, tech_notified, supervisor_notified, submitted)
                    VALUES (:c_date, :t_name, :s_id, :queue, :goal, :st, :dur, NULL, 0, 0, 0)
                    ON CONFLICT (log_date, tech_name, slot_id) DO UPDATE
                    SET queue=EXCLUDED.queue, goal=EXCLUDED.goal, start_time=EXCLUDED.start_time, duration_minutes=EXCLUDED.duration_minutes, submitted=0, input_number=NULL
                """), {"c_date": CURRENT_DATE, "t_name": tech_name, "s_id": target_slot, "queue": row.queue_name, "goal": goal_str, "st": now_str, "dur": row.duration_minutes})

        session.execute(text("DELETE FROM schedule_proposals WHERE log_date=:c_date AND dept_prefix=:pfx"), {"c_date": CURRENT_DATE, "pfx": dept_prefix})
        session.commit()
    return skipped

@st.fragment
def render_autoscheduler_tab():
    if not is_manager:
        st.warning("🔒 Access Locked: Enter the manager password in the left sidebar to use the auto-scheduler.")
        return

    for dept_prefix, db_table, dept_label in AUTOSCHEDULER_DEPTS:
        st.subheader(f"🗓️ {dept_label} — Today's Shift Schedule")

        if HOMEBASE_API_KEY:
            if st.button(f"🔄 Sync Shifts from Homebase", key=f"hb_sync_{dept_prefix}", use_container_width=True):
                result, error = sync_homebase_shifts(dept_prefix)
                if error:
                    st.error(f"⚠️ {error}")
                else:
                    if result["matched"]:
                        st.success(f"Synced {len(result['matched'])} shift(s): " + ", ".join(f"{name} ({s}–{e})" for name, (s, e) in result["matched"].items()))
                    else:
                        st.warning(f"Homebase returned {result['total_fetched']} shift(s) today, but none matched a name in your {dept_label} roster.")
                    if result["unmatched_names"]:
                        st.caption(f"Not matched to anyone in your roster (name mismatch?): {', '.join(result['unmatched_names'])}")
                    fragment_rerun()
        else:
            st.caption("💡 Homebase sync available once `[homebase]` credentials are added to secrets — manual entry below works either way.")

        with db_conn.session as session:
            roster_rows = session.execute(text("SELECT tech_name FROM global_roster WHERE dept_prefix=:pfx ORDER BY tech_name"), {"pfx": dept_prefix}).fetchall()
            shift_rows = session.execute(text("SELECT tech_name, shift_start, shift_end FROM tech_shifts WHERE log_date=:c_date AND dept_prefix=:pfx"), {"c_date": CURRENT_DATE, "pfx": dept_prefix}).fetchall()
        existing_shifts = {r.tech_name: (r.shift_start, r.shift_end) for r in shift_rows}

        if not roster_rows:
            st.info(f"No technicians assigned to {dept_label} yet. Add them from the sidebar first.")
            continue

        shift_form_state = {}
        for r in roster_rows:
            tech_name = r.tech_name
            t_id = hashlib.md5(tech_name.encode('utf-8')).hexdigest()[:8]
            cols = st.columns([2, 2, 1, 1])
            cols[0].markdown(f"**{tech_name}**")

            preset_options = ["Not Working Today"] + list(SHIFT_PRESETS.keys()) + ["Custom"]
            default_index = 0
            custom_start, custom_end = dtime(9, 0), dtime(17, 0)
            if tech_name in existing_shifts:
                s_str, e_str = existing_shifts[tech_name]
                matched_preset = next((label for label, (ps, pe) in SHIFT_PRESETS.items() if ps.strftime("%H:%M") == s_str and pe.strftime("%H:%M") == e_str), None)
                if matched_preset:
                    default_index = preset_options.index(matched_preset)
                else:
                    default_index = preset_options.index("Custom")
                    custom_start = datetime.strptime(s_str, "%H:%M").time()
                    custom_end = datetime.strptime(e_str, "%H:%M").time()

            chosen = cols[1].selectbox("Shift", options=preset_options, index=default_index, key=f"shift_choice_{dept_prefix}_{t_id}_{CURRENT_DATE}", label_visibility="collapsed")

            if chosen == "Custom":
                c_start = cols[2].time_input("Start", value=custom_start, key=f"shift_start_{dept_prefix}_{t_id}_{CURRENT_DATE}", label_visibility="collapsed")
                c_end = cols[3].time_input("End", value=custom_end, key=f"shift_end_{dept_prefix}_{t_id}_{CURRENT_DATE}", label_visibility="collapsed")
                shift_form_state[tech_name] = (chosen, c_start, c_end)
            elif chosen == "Not Working Today":
                shift_form_state[tech_name] = (chosen, None, None)
            else:
                p_start, p_end = SHIFT_PRESETS[chosen]
                shift_form_state[tech_name] = (chosen, p_start, p_end)

        if st.button(f"💾 Save {dept_label} Shift Schedule", key=f"save_shifts_{dept_prefix}", use_container_width=True):
            try:
                with db_conn.session as session:
                    for tech_name, (chosen, s_time, e_time) in shift_form_state.items():
                        if chosen == "Not Working Today":
                            session.execute(text("DELETE FROM tech_shifts WHERE log_date=:c_date AND dept_prefix=:pfx AND tech_name=:t_name"), {"c_date": CURRENT_DATE, "pfx": dept_prefix, "t_name": tech_name})
                        else:
                            session.execute(text("""
                                INSERT INTO tech_shifts (log_date, dept_prefix, tech_name, shift_start, shift_end)
                                VALUES (:c_date, :pfx, :t_name, :s_start, :s_end)
                                ON CONFLICT (log_date, dept_prefix, tech_name) DO UPDATE SET shift_start=EXCLUDED.shift_start, shift_end=EXCLUDED.shift_end
                            """), {"c_date": CURRENT_DATE, "pfx": dept_prefix, "t_name": tech_name, "s_start": s_time.strftime("%H:%M"), "s_end": e_time.strftime("%H:%M")})
                    session.commit()
                st.success("Shift schedule saved.")
                fragment_rerun()
            except Exception as e:
                st.error(f"⚠️ Couldn't save the shift schedule right now: {str(e)}")

        st.markdown("---")
        st.subheader(f"⚙️ {dept_label} — Generate Proposal")
        st.caption("Standard run anchors to 1:00 PM EST vs. each tech's shift end. Recalculating later uses the actual current time instead.")

        gen_col1, gen_col2 = st.columns(2)
        one_pm_today = datetime.combine(now_eastern_naive().date(), dtime(13, 0))
        if gen_col1.button(f"▶️ Generate Standard Proposal (1:00 PM anchor)", key=f"gen_std_{dept_prefix}", use_container_width=True):
            summary = generate_schedule_proposal(dept_prefix, one_pm_today)
            st.session_state[f"last_proposal_summary_{dept_prefix}"] = summary
            fragment_rerun()
        if gen_col2.button(f"🔁 Recalculate Now (current time anchor)", key=f"gen_now_{dept_prefix}", use_container_width=True):
            summary = generate_schedule_proposal(dept_prefix, now_eastern_naive())
            st.session_state[f"last_proposal_summary_{dept_prefix}"] = summary
            fragment_rerun()

        with db_conn.session as session:
            proposal_rows = session.execute(text("SELECT tech_name, proposal_slot, queue_name, duration_minutes FROM schedule_proposals WHERE log_date=:c_date AND dept_prefix=:pfx ORDER BY tech_name, proposal_slot"), {"c_date": CURRENT_DATE, "pfx": dept_prefix}).fetchall()

        if not proposal_rows:
            st.info("No proposal generated yet for today. Enter shifts and volume, then click Generate.")
        else:
            summary = st.session_state.get(f"last_proposal_summary_{dept_prefix}")
            if summary:
                s1, s2, s3 = st.columns(3)
                s1.metric("Total Tech-Minutes Available", f"{round(summary['total_capacity'])} min")
                s2.metric("Total Tech-Minutes Needed", f"{round(summary['total_required'])} min")
                s3.metric("Unused Capacity", f"{summary['unused_capacity']} min")
                if summary["unmet"]:
                    st.warning("⚠️ Not enough capacity to fully clear today's volume for: " + ", ".join(f"{k} (~{v} min short)" for k, v in summary["unmet"].items()))

            st.markdown("**Proposed Assignments (review before approving):**")
            by_tech_display = {}
            for r in proposal_rows:
                by_tech_display.setdefault(r.tech_name, []).append(r)
            for tech_name, rows in by_tech_display.items():
                line = f"👤 **{tech_name}**: " + " → ".join(f"{r.queue_name} ({r.duration_minutes} min)" for r in rows)
                st.markdown(line)

            approve_col1, approve_col2 = st.columns(2)
            if approve_col1.button(f"✅ Approve & Apply {dept_label} Schedule", key=f"approve_{dept_prefix}", type="primary", use_container_width=True):
                try:
                    skipped = apply_schedule_proposal(dept_prefix, db_table)
                    if skipped:
                        st.warning("Applied with some exceptions (existing active slots were not overwritten):\n\n" + "\n".join(f"- {s}" for s in skipped))
                    else:
                        st.success(f"{dept_label} schedule applied — timers started for all assigned slots.")
                    st.session_state.pop(f"last_proposal_summary_{dept_prefix}", None)
                    fragment_rerun()
                except Exception as e:
                    st.error(f"⚠️ Couldn't apply this schedule right now: {str(e)}")
            if approve_col2.button(f"🗑️ Discard Proposal", key=f"discard_{dept_prefix}", use_container_width=True):
                try:
                    with db_conn.session as session:
                        session.execute(text("DELETE FROM schedule_proposals WHERE log_date=:c_date AND dept_prefix=:pfx"), {"c_date": CURRENT_DATE, "pfx": dept_prefix})
                        session.commit()
                    st.session_state.pop(f"last_proposal_summary_{dept_prefix}", None)
                    fragment_rerun()
                except Exception as e:
                    st.error(f"⚠️ Couldn't discard this proposal right now: {str(e)}")

with tab_sched:
    render_autoscheduler_tab()

# --- 8. DYNAMIC QUEUE & ROSTER MANAGEMENT CONFIGURATION TAB ---
@st.fragment
def render_queue_management_tab():
        st.header("⚙️ System Queue & Target Goal Adjustments")
        st.markdown("---")
    
        if not is_manager:
            st.warning("🔒 Access Locked: Enter the manager password in the left sidebar to unlock modifications.")
        else:
            m_col1, m_col2 = st.columns(2)
        
            with m_col1:
                st.subheader("➕ Create Custom Queue Trackers")
                target_dept = st.selectbox("Select Department Destination:", [("Data Entry", "de"), ("Call Center", "cc"), ("Shipping", "sh"), ("Fill", "fi")], key="mgmt_dept_selector")
                new_q_name = st.text_input("New Queue Name:", placeholder="e.g., Priority Tier 3 Verification", key="mgmt_q_name_input").strip()
                new_q_goal = st.text_input("Production Unit Goal Target (PER 1 HOUR):", placeholder="e.g., 50 rxs", key="mgmt_goal_input").strip()
            
                if st.button("Save New Queue Component", type="primary", use_container_width=True, key="mgmt_save_btn"):
                    if new_q_name and new_q_goal:
                        try:
                            with db_conn.session as session:
                                session.execute(text("""
                                    INSERT INTO dynamic_queues (dept_prefix, queue_name, goal_target) VALUES (:prefix, :name, :target)
                                    ON CONFLICT (dept_prefix, queue_name) DO UPDATE SET goal_target = EXCLUDED.goal_target
                                """), {"prefix": target_dept[1], "name": new_q_name, "target": new_q_goal})
                                session.commit()
                            st.success(f"Added baseline operational tracking line: {new_q_name} at {new_q_goal}/hr")
                            fragment_rerun()
                        except Exception as e:
                            st.error(f"⚠️ Couldn't save this queue right now: {str(e)}")
            
                st.markdown("<br><br>", unsafe_allow_html=True)
                st.subheader("🗑 ... Decommission Employee Profiles")
                with db_conn.session as session:
                    all_staff = session.execute(text("SELECT dept_prefix, tech_name FROM global_roster ORDER BY tech_name ASC")).fetchall()
            
                if not all_staff:
                    st.info("No saved technician profiles found.")
                else:
                    for staff in all_staff:
                        s_prefix, s_name = staff.dept_prefix, staff.tech_name
                        s_id = hashlib.md5(s_name.encode('utf-8')).hexdigest()[:8]
                        d_lbl = {"de": "Data Entry", "cc": "Call Center", "sh": "Shipping", "fi": "Fill"}[s_prefix]
                        s_col1, s_col2 = st.columns([2.5, 1])
                        s_col1.markdown(f"👤 **{s_name}** `({d_lbl})`")
                        if s_col2.button("Remove Profile", key=f"del_staff_{s_prefix}_{s_id}", type="secondary", use_container_width=True):
                            try:
                                with db_conn.session as session:
                                    session.execute(text("DELETE FROM global_roster WHERE dept_prefix=:prefix AND tech_name=:name"), {"prefix": s_prefix, "name": s_name})
                                    for t in ["data_entry_slots", "call_center_slots", "shipping_slots", "fill_slots"]:
                                        session.execute(text(f"DELETE FROM {t} WHERE log_date=:c_date AND tech_name=:name"), {"c_date": CURRENT_DATE, "name": s_name})
                                    session.commit()
                                st.session_state["selected_profile_state"] = "-- Create New Profile --"
                                st.success(f"Decommissioned {s_name} from system.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"⚠️ Couldn't remove this profile right now: {str(e)}")
                        st.markdown("<hr style='margin:2px 0px !important;'>", unsafe_allow_html=True)
                    
            with m_col2:
                st.subheader("📋 Current Active Queue Database Matrix")
                with db_conn.session as session:
                    all_qs = session.execute(text("SELECT dept_prefix, queue_name, goal_target FROM dynamic_queues")).fetchall()
            
                if not all_qs:
                    st.info("No customized tracking queues available.")
                else:
                    for q_row in all_qs:
                        q_prefix, q_name, q_goal = q_row.dept_prefix, q_row.queue_name, q_row.goal_target
                        q_id = hashlib.md5(q_name.encode('utf-8')).hexdigest()[:8]
                        dept_lbl = {"de": "Data Entry", "cc": "Call Center", "sh": "Shipping", "fi": "Fill"}[q_prefix]
                        with st.container(border=True):
                            st.markdown(f"**[{dept_lbl}]** `{q_name}`")
                            st.caption(f"Base Hourly Vector: {q_goal} per hour")
                            if st.button("🗑️ Delete Line", key=f"del_{q_prefix}_{q_id}", use_container_width=True):
                                try:
                                    with db_conn.session as session:
                                        session.execute(text("DELETE FROM dynamic_queues WHERE dept_prefix=:prefix AND queue_name=:name"), {"prefix": q_prefix, "name": q_name})
                                        session.commit()
                                    fragment_rerun()
                                except Exception as e:
                                    st.error(f"⚠️ Couldn't delete this queue right now: {str(e)}")

with tab_mgmt:
    render_queue_management_tab()

# --- 9. ADVANCED HISTORICAL & TRENDS ANALYTICS TAB ---
with tab_analytics:
    if not is_manager:
        st.warning("🔒 Access Locked: Enter the manager password in the left sidebar to view analytics.")
    else:
        st.header("📊 Cumulative Corporate Analytics Ledger")
    
        date_cols = st.columns(2)
        start_filt = date_cols[0].date_input("Start History Date", value=datetime.now() - timedelta(days=30))
        end_filt = date_cols[1].date_input("End History Date", value=datetime.now())
    
        query = text("""
            SELECT log_date, department, tech_name, queue, goal, input_number, duration_minutes 
            FROM metrics_history 
            WHERE log_date >= :start AND log_date <= :end
        """)
    
        with db_conn.session as session:
            res_analytics = session.execute(query, {"start": start_filt.strftime("%Y-%m-%d"), "end": end_filt.strftime("%Y-%m-%d")}).fetchall()
    
        if not res_analytics:
            st.info("💡 No production records logged during this timeframe configuration.")
        else:
            df_analytics = pd.DataFrame(res_analytics)
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
                    if not match: return pd.Series([0, "✅ Met Goal"])
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
            
                st.dataframe(display_df.style.map(lambda val: 'background-color: #ffccd5' if val == '❌ Missed Goal' else 'background-color: #d1e7dd', subset=['True Performance Status']), use_container_width=True, hide_index=True)
            
                true_missed_count = (df_filtered["True Performance Status"] == "❌ Missed Goal").sum()
            
                k1, k2, k3 = st.columns(3)
                k1.metric("⏱️ Shift Blocks Evaluated", f"{total_blocks} Blocks")
                k2.metric("📦 Volume Processed", f"{total_units:,} Units")
                k3.metric("🚨 True Pro-Rata Deficits Flagged", f"{true_missed_count} Incidents")
            else:
                st.warning("Please select at least one technician profile.")
                # display_df is intentionally set to an empty frame with the expected columns here.
                # Previously this branch left display_df undefined, and the trend chart below
                # referenced it unconditionally -- if a user deselected every technician, that threw
                # an uncaught NameError which halted the ENTIRE script at that point in the run,
                # silently skipping everything rendered after it (including the daily checklist
                # section further down the page).
                display_df = pd.DataFrame(columns=["Date", "Technician Name", "Department", "Assigned Queue", "Logged Units"])
            
            st.markdown("---")
            st.subheader("📈 Operational Velocity Trend Analysis")
            trend_view_option = st.radio("Group Trend Visualization By:", ["Individual Technician Trends", "Queue Volume Trends"], horizontal=True)
            if display_df.empty:
                st.caption("No data to chart for the current technician selection.")
            elif trend_view_option == "Individual Technician Trends":
                st.line_chart(display_df.groupby(["Date", "Technician Name"])["Logged Units"].sum().unstack(fill_value=0))
            else:
                st.line_chart(display_df.groupby(["Date", "Assigned Queue"])["Logged Units"].sum().unstack(fill_value=0))
# --- 10. BUSINESS-WIDE VERIFICATION CHECKLIST (BATCH SUBMISSION ENGINE) ---
st.markdown("<br>", unsafe_allow_html=True)
def render_daily_verification_section():
    with st.container(border=True):
        st.header("📋 Global Facility Daily Queue Verification Log")
    
        with db_conn.session as session:
            chk = session.execute(text("SELECT * FROM daily_checklist WHERE log_date = :c_date"), {"c_date": CURRENT_DATE}).fetchone()
            if not chk:
                session.execute(text("INSERT INTO daily_checklist (log_date, reminder_sent, supervisor_escaped, reminder_time) VALUES (:c_date, 0, 0, '17:00') ON CONFLICT (log_date) DO NOTHING"), {"c_date": CURRENT_DATE})
                session.commit()
                chk = session.execute(text("SELECT * FROM daily_checklist WHERE log_date = :c_date"), {"c_date": CURRENT_DATE}).fetchone()
        
        c_col, f_col = st.columns([3.2, 1])
    
        with f_col:
            with st.container(border=True):
                t_obj = datetime.strptime(chk.reminder_time, "%H:%M").time()
                new_target_time = st.time_input("Set Verification Deadline (EST):", value=t_obj, key="checklist_deadline_widget")
                if new_target_time.strftime("%H:%M") != chk.reminder_time:
                    try:
                        with db_conn.session as session:
                            session.execute(text("UPDATE daily_checklist SET reminder_time=:rt, reminder_sent=0, supervisor_escaped=0 WHERE log_date=:c_date"), {"rt": new_target_time.strftime("%H:%M"), "c_date": CURRENT_DATE})
                            session.commit()
                        st.rerun()
                    except Exception as e:
                        st.error(f"⚠️ Couldn't update the deadline right now: {str(e)}")
            
        with c_col:
            opt = ["Pending", "Yes", "No"]
        
            def parse_stored_date(val):
                if not val or str(val).strip() == "": return datetime.now().date()
                try: return datetime.strptime(str(val).strip(), "%Y-%m-%d").date()
                except: return datetime.now().date()

            form_states = {}

            def render_checklist_row(label, db_prefix, prefix_key):
                st.markdown(f"##### {label}")
                cols = st.columns([1.1, 1.0, 1.0, 0.7, 0.8, 2.0])
            
                stored_status = getattr(chk, db_prefix, "Pending") if chk else "Pending"
                stored_odt = getattr(chk, f"{db_prefix}_date", "") if chk else ""
                stored_tdt = getattr(chk, f"{db_prefix}_target", "") if chk else ""
                stored_by = getattr(chk, f"{db_prefix}_by", "") if chk else ""
                stored_notes = getattr(chk, f"{db_prefix}_notes", "") if chk else ""

                curr_status = cols[0].selectbox("Status", options=opt, index=opt.index(stored_status) if stored_status in opt else 0, key=f"status_{prefix_key}_{CURRENT_DATE}")
                curr_odt = cols[1].date_input("Oldest Date", value=parse_stored_date(stored_odt), key=f"odt_{prefix_key}_{CURRENT_DATE}")
                curr_tdt = cols[2].date_input("Target Date", value=parse_stored_date(stored_tdt), key=f"tdt_{prefix_key}_{CURRENT_DATE}")
            
                try:
                    date_delta = (datetime.now().date() - curr_odt).days if db_prefix in ["erx_queue", "central_fill_queue", "on_hold_queue"] else (curr_tdt - curr_odt).days
                    is_red = False
                    if date_delta > 0:
                        if db_prefix in ["erx_queue", "central_fill_queue", "on_hold_queue", "data_re_entry", "untransmitted_claims"]: is_red = True
                        elif db_prefix in ["ai_tech_check", "rejection_queue"] and date_delta > 4: is_red = True
                        elif db_prefix == "return_fourteen_queue" and date_delta >= 14: is_red = True
                        elif db_prefix not in ["erx_queue", "central_fill_queue", "on_hold_queue", "data_re_entry", "untransmitted_claims", "ai_tech_check", "rejection_queue", "return_fourteen_queue"] and date_delta >= 7: is_red = True

                    badge_html = f"<div style='text-align:center;'><span style='background-color:#f8d7da; color:#842029; padding:6px 10px; border-radius:4px; font-weight:bold; font-size:12px;'>🚨 {date_delta} Days</span></div>" if is_red else (f"<div style='text-align:center;'><span style='background-color:#fff3cd; color:#664d03; padding:6px 10px; border-radius:4px; font-weight:bold; font-size:12px;'>⚠️ {date_delta} Days</span></div>" if date_delta > 0 else f"<div style='text-align:center;'><span style='background-color:#d1e7dd; color:#0f5132; padding:6px 10px; border-radius:4px; font-weight:bold; font-size:12px;'>✅ Current</span></div>")
                    cols[3].markdown(f"<div style='font-size: 14px; margin-bottom: 10px; color: #31333F;'>Aging</div>{badge_html}", unsafe_allow_html=True)
                except Exception:
                    cols[3].markdown("<div style='font-size: 14px; margin-bottom: 10px; color: #31333F;'>Aging</div><div style='text-align:center;'><span style='background-color:#cbd5e1; color:#1e293b; padding:6px 10px; border-radius:4px; font-size:12px;'>-</span></div>", unsafe_allow_html=True)
                    is_red = False
                    date_delta = 0

                curr_by = cols[4].text_input("Verified By", value=stored_by, key=f"by_{prefix_key}_{CURRENT_DATE}")
                curr_notes = cols[5].text_input("Notes/Explanations", value=stored_notes, key=f"notes_{prefix_key}_{CURRENT_DATE}")
            
                form_states[db_prefix] = {
                    "label": label, "status": curr_status, "odt": str(curr_odt), "tdt": str(curr_tdt),
                    "by": curr_by, "notes": curr_notes, "is_red": is_red, "delta": date_delta
                }

            render_checklist_row("14 Day Return Queue Checked", "return_fourteen_queue", "ret_14")
            render_checklist_row("AI /Tech Check Queue Checked", "ai_tech_check", "ai_tch")
            render_checklist_row("Billing Queue Checked", "billing", "bill")
            render_checklist_row("Central Fill Queue Checked", "central_fill_queue", "c_fill")
            render_checklist_row("Data Re-Entry Checked", "data_re_entry", "re_ent")
            render_checklist_row("Dispense Queue Checked", "dispense", "disp")
            render_checklist_row("ERx Queue Checked", "erx_queue", "erx_chk")
            render_checklist_row("Future Bill Queue Checked", "future_bill", "fut")
            render_checklist_row("On Hold Queue Checked", "on_hold_queue", "on_hld")
            render_checklist_row("Ordering Queue Checked", "ordering", "ord")
            render_checklist_row("Prior Authorization Queue", "pa_queue", "pa")
            render_checklist_row("Rejection Queue Checked", "rejection_queue", "rej")
            render_checklist_row("Untransmitted Claims Completed", "untransmitted_claims", "untrans")

            st.markdown("<br>", unsafe_allow_html=True)

            already_submitted_today = bool(chk.last_submitted_at) if chk else False
            resubmit_armed_key = "checklist_resubmit_armed"

            if already_submitted_today:
                st.info(f"✅ Already submitted today at **{chk.last_submitted_at} EST**. Submitting again will re-send Chat alerts for anything still flagged below.")

            # Two-step guard: once already submitted today, the first click only "arms" a
            # resubmit and asks for explicit confirmation, so a stray click can't silently
            # re-fire duplicate Chat alerts for the same deficiencies.
            if already_submitted_today and not st.session_state.get(resubmit_armed_key, False):
                submit_clicked = False
                if st.button("🔁 Resubmit Anyway", key="checklist_resubmit_arm_btn", use_container_width=True):
                    st.session_state[resubmit_armed_key] = True
                    st.rerun()
            else:
                button_label = "⚠️ Confirm Resubmit (will re-send Chat alerts for flagged items)" if already_submitted_today else "💾 Submit Daily Verification Report"
                submit_clicked = st.button(button_label, type="primary", use_container_width=True, key="submit_daily_report_btn")

            if submit_clicked:
                deficiency_list = []
            
                try:
                    # Single batched UPDATE covering all 13 checklist rows plus the tracking
                    # flags, instead of 13+ separate sequential round trips to the DB. Each
                    # round trip has its own network latency, so this was a real contributor
                    # to the "lag on submit" -- now it's one statement, one round trip.
                    set_parts = []
                    params = {"c_date": CURRENT_DATE}
                    for db_field, data in form_states.items():
                        set_parts.append(f"{db_field}=:{db_field}__status")
                        set_parts.append(f"{db_field}_date=:{db_field}__odt")
                        set_parts.append(f"{db_field}_target=:{db_field}__tdt")
                        set_parts.append(f"{db_field}_by=:{db_field}__by")
                        set_parts.append(f"{db_field}_notes=:{db_field}__notes")
                        params[f"{db_field}__status"] = data["status"]
                        params[f"{db_field}__odt"] = data["odt"]
                        params[f"{db_field}__tdt"] = data["tdt"]
                        params[f"{db_field}__by"] = data["by"]
                        params[f"{db_field}__notes"] = data["notes"]

                        if data["status"] == "No" or data["is_red"]:
                            deficiency_list.append(f"• **{data['label']}**\n  ↳ Reason: {'⚠️ STATUS: NO' if data['status'] == 'No' else '🚨 CRITICAL AGING'} | Backlog: {data['delta']} Days" + (f" (Notes: {data['by']} - {data['notes']})" if data['by'] or data['notes'] else ""))

                    submitted_at_str = now_eastern_naive().strftime("%H:%M:%S")
                    set_parts.append("reminder_sent=1")
                    set_parts.append("supervisor_escaped=1")
                    set_parts.append("last_submitted_at=:last_submitted_at")
                    params["last_submitted_at"] = submitted_at_str

                    with db_conn.session as session:
                        session.execute(text(f"UPDATE daily_checklist SET {', '.join(set_parts)} WHERE log_date=:c_date"), params)
                        session.commit()
                
                    if deficiency_list:
                        chat_sent_ok = dispatch_real_time_alert(f"📋 **FACILITY OPERATIONS DAILY VERIFICATION REPORT**\n⏰ **Timestamp:** {submitted_at_str} EST\n⚠️ *The following operational tracking points require attention:* \n\n" + "\n\n".join(deficiency_list))
                        st.success("Verification data saved.")
                        if chat_sent_ok:
                            st.success("Deficiency summary report compiled and pushed to Google Chat!")
                        else:
                            # dispatch_real_time_alert() previously failed completely silently here --
                            # the DB save succeeded (that part is confirmed above) but the webhook POST
                            # did not, and nothing told the user that. Surfacing it now.
                            st.warning("⚠️ The verification data saved, but the Google Chat notification failed to send. Check the webhook configuration/connectivity.")
                    else:
                        st.success("Verification metrics logged successfully! All operational channels are current.")

                    st.session_state[resubmit_armed_key] = False
                    # No immediate st.rerun() here: this section isn't inside a fragment, so a
                    # rerun means a full-page reload (sidebar, all 4 dept tabs, analytics, etc.),
                    # which is heavy enough that it was likely wiping this success message before
                    # it could be seen. The existing 10s global heartbeat will refresh everything
                    # else naturally without us forcing it.
                except Exception as e:
                    st.error(f"⚠️ Couldn't save the verification report right now: {str(e)}")

try:
    render_daily_verification_section()
except Exception as e:
    # Temporary diagnostic net: surfaces the FULL traceback in the UI so any failure
    # here is visible immediately, regardless of how error-detail display is configured
    # on this deployment. Safe to narrow back down to a plain st.error(...) once the
    # daily verification submit is confirmed working end-to-end.
    st.error("⚠️ The Daily Verification section hit an unexpected error:")
    st.exception(e)
