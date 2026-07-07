import streamlit as st
import pandas as pd
import re
import hashlib
from datetime import datetime, timedelta
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
is_manager = pwd_input == "admin123"

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

# --- 5. TOP-LEVEL BACKLOG MATRIX INPUT INJECTOR ---
def render_global_backlog_ribbon():
    with db_conn.session as session:
        row = session.execute(text("SELECT * FROM floor_backlogs WHERE log_date = :c_date"), {"c_date": CURRENT_DATE}).fetchone()
        if not row:
            session.execute(text("INSERT INTO floor_backlogs (log_date) VALUES (:c_date) ON CONFLICT (log_date) DO NOTHING"), {"c_date": CURRENT_DATE})
            session.commit()
            row = session.execute(text("SELECT * FROM floor_backlogs WHERE log_date = :c_date"), {"c_date": CURRENT_DATE}).fetchone()

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
            current_value = getattr(row, db_field) if row else 0
            new_val = st.number_input(label, min_value=0, step=1, value=int(current_value), key=f"top_bl_{db_field}_{CURRENT_DATE}")
            if new_val != current_value:
                updates[db_field] = new_val

    if updates:
        set_clause = ", ".join([f"{k}=:{k}" for k in updates.keys()])
        updates["c_date"] = CURRENT_DATE
        try:
            with db_conn.session as session:
                session.execute(text(f"UPDATE floor_backlogs SET {set_clause} WHERE log_date=:c_date"), updates)
                session.commit()
            st.rerun()
        except Exception as e:
            st.error(f"⚠️ Couldn't save backlog numbers right now: {str(e)}")
    st.markdown("<hr style='margin: 8px 0px 14px 0px !important; border-top: 2px solid #cbd5e1;'>", unsafe_allow_html=True)

# --- 6. RENDERING ENGINE FOR WORKER GRID ROWS ---
@st.fragment(run_every="5s")
def render_synchronized_matrix(db_table, prefix, dept_label):
    with db_conn.session as session:
        goals_dict = {r.queue_name: r.goal_target for r in session.execute(text("SELECT queue_name, goal_target FROM dynamic_queues WHERE dept_prefix = :pfx"), {"pfx": prefix}).fetchall()}
        roster_rows = session.execute(text("SELECT tech_name, tech_email, tech_webhook FROM global_roster WHERE dept_prefix = :pfx"), {"pfx": prefix}).fetchall()
    
    active_roster = {row.tech_name: {"email": row.tech_email, "webhook": row.tech_webhook} for row in roster_rows}

    if not active_roster:
        st.info(f"💡 No personnel assigned to {dept_label} currently. Use the left sidebar panel to assign employees to this department.")
        return

    is_mgr_active = st.session_state.get("mgr_pwd_input_field") == "admin123"

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
                    
                    with db_conn.session as session:
                        slot_row = session.execute(text(f"SELECT * FROM {db_table} WHERE log_date=:c_date AND tech_name=:t_name AND slot_id=:s_id"), {"c_date": CURRENT_DATE, "t_name": worker, "s_id": slot_num}).fetchone()
                    
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
                        st.rerun()
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
                                st.rerun()
                            except Exception as e:
                                st.error(f"⚠️ Couldn't delete this queue right now: {str(e)}")

# --- 9. ADVANCED HISTORICAL & TRENDS ANALYTICS TAB ---
with tab_analytics:
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
            render_checklist_row("ERx Queue Checked-Any Rx from previous day?", "erx_queue", "erx_chk")
            render_checklist_row("Future Bill Queue Checked", "future_bill", "fut")
            render_checklist_row("On Hold Queue Checked", "on_hold_queue", "on_hld")
            render_checklist_row("Ordering Queue Checked", "ordering", "ord")
            render_checklist_row("Prior Authorization Queue", "pa_queue", "pa")
            render_checklist_row("Rejection Queue Checked", "rejection_queue", "rej")
            render_checklist_row("Untransmitted Claims Completed", "untransmitted_claims", "untrans")

            st.markdown("<br>", unsafe_allow_html=True)
        
            if st.button("💾 Submit Daily Verification Report", type="primary", use_container_width=True, key="submit_daily_report_btn"):
                deficiency_list = []
            
                try:
                    with db_conn.session as session:
                        for db_field, data in form_states.items():
                            session.execute(text(f"""
                                UPDATE daily_checklist 
                                SET {db_field}=:status, {db_field}_date=:odt, {db_field}_target=:tdt, {db_field}_by=:by, {db_field}_notes=:notes 
                                WHERE log_date=:c_date
                            """), {"status": data["status"], "odt": data["odt"], "tdt": data["tdt"], "by": data["by"], "notes": data["notes"], "c_date": CURRENT_DATE})
                        
                            if data["status"] == "No" or data["is_red"]:
                                deficiency_list.append(f"• **{data['label']}**\n  ↳ Reason: {'⚠️ STATUS: NO' if data['status'] == 'No' else '🚨 CRITICAL AGING'} | Backlog: {data['delta']} Days" + (f" (Notes: {data['by']} - {data['notes']})" if data['by'] or data['notes'] else ""))
                    
                        session.execute(text("UPDATE daily_checklist SET reminder_sent=1, supervisor_escaped=1 WHERE log_date=:c_date"), {"c_date": CURRENT_DATE})
                        session.commit()
                
                    if deficiency_list:
                        ts_str = datetime.now(EASTERN_TZ).strftime('%H:%M:%S') if EASTERN_TZ else datetime.now().strftime('%H:%M:%S')
                        chat_sent_ok = dispatch_real_time_alert(f"📋 **FACILITY OPERATIONS DAILY VERIFICATION REPORT**\n⏰ **Timestamp:** {ts_str} EST\n⚠️ *The following operational tracking points require attention:* \n\n" + "\n\n".join(deficiency_list))
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
