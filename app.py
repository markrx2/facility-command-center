import streamlit as st
import streamlit.components.v1 as components
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
import threading
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
# Global browser heartbeat. Keeps the container awake and forces a full-script check cycle every 15 seconds.
# NOTE: this is what keeps things like the Analytics tab and backlog ribbon fresh, since those live
# outside any @st.fragment and only update on a full rerun.
st_autorefresh(interval=15000, key="global_system_heartbeat")

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

        # --- CHECKLIST ITEM MANAGEMENT ---
        # checklist_items is the manageable config (like dynamic_queues): add/rename/remove
        # rows and tune their aging rules from the UI. checklist_entries holds the actual
        # per-day data, one row per (day, item) instead of the old fixed-column design, which
        # is what made the 13 rows hardcoded and unmanageable in the first place.
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS checklist_items (
                item_key TEXT PRIMARY KEY,
                label TEXT,
                aging_basis TEXT DEFAULT 'target_minus_oldest',
                red_threshold_days INTEGER DEFAULT 7,
                sort_order INTEGER DEFAULT 0
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS checklist_entries (
                log_date TEXT,
                item_key TEXT,
                status TEXT DEFAULT 'Pending',
                oldest_date TEXT DEFAULT '',
                target_date TEXT DEFAULT '',
                verified_by TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                PRIMARY KEY (log_date, item_key)
            )
        """))
        session.commit()

        res = session.execute(text("SELECT COUNT(*) as cnt FROM checklist_items")).fetchone()
        if res[0] == 0:
            # Seed with the original 13 items, preserving their exact prior behavior:
            # aging_basis "today_minus_oldest" for the 3 that compared against today's date,
            # "target_minus_oldest" for the rest, and red_threshold_days set so the red
            # trigger point matches what was previously hardcoded per item (e.g. the old
            # "any positive delta is red" items get threshold=1; "> 4 days" becomes
            # threshold=5; the 14-day and default-7-day rules carry over directly).
            default_items = [
                ("return_fourteen_queue", "14 Day Return Queue Checked", "target_minus_oldest", 14, 1),
                ("ai_tech_check", "AI /Tech Check Queue Checked", "target_minus_oldest", 5, 2),
                ("billing", "Billing Queue Checked", "target_minus_oldest", 7, 3),
                ("central_fill_queue", "Central Fill Queue Checked", "today_minus_oldest", 1, 4),
                ("data_re_entry", "Data Re-Entry Checked", "target_minus_oldest", 1, 5),
                ("dispense", "Dispense Queue Checked", "target_minus_oldest", 7, 6),
                ("erx_queue", "ERx Queue Checked", "today_minus_oldest", 1, 7),
                ("future_bill", "Future Bill Queue Checked", "target_minus_oldest", 7, 8),
                ("on_hold_queue", "On Hold Queue Checked", "today_minus_oldest", 1, 9),
                ("ordering", "Ordering Queue Checked", "target_minus_oldest", 7, 10),
                ("pa_queue", "Prior Authorization Queue", "target_minus_oldest", 7, 11),
                ("rejection_queue", "Rejection Queue Checked", "target_minus_oldest", 5, 12),
                ("untransmitted_claims", "Untransmitted Claims Completed", "target_minus_oldest", 1, 13),
            ]
            for item_key, label, basis, threshold, order in default_items:
                session.execute(
                    text("INSERT INTO checklist_items (item_key, label, aging_basis, red_threshold_days, sort_order) VALUES (:k, :l, :b, :t, :o)"),
                    {"k": item_key, "l": label, "b": basis, "t": threshold, "o": order}
                )
            session.commit()

            # One-time migration: daily_checklist has one row per day with the 13 items baked
            # into fixed columns. Convert every existing day's data into checklist_entries so
            # nothing already entered (including today's in-progress checklist) is lost. Only
            # runs once, guarded by checklist_items having just been empty (a fresh install
            # would also have nothing to migrate, which is harmless).
            old_rows = session.execute(text("SELECT * FROM daily_checklist")).fetchall()
            for old_row in old_rows:
                for item_key, _, _, _, _ in default_items:
                    status = getattr(old_row, item_key, None)
                    if status is None:
                        continue
                    session.execute(text("""
                        INSERT INTO checklist_entries (log_date, item_key, status, oldest_date, target_date, verified_by, notes)
                        VALUES (:log_date, :item_key, :status, :oldest_date, :target_date, :verified_by, :notes)
                        ON CONFLICT (log_date, item_key) DO NOTHING
                    """), {
                        "log_date": old_row.log_date, "item_key": item_key, "status": status,
                        "oldest_date": getattr(old_row, f"{item_key}_date", "") or "",
                        "target_date": getattr(old_row, f"{item_key}_target", "") or "",
                        "verified_by": getattr(old_row, f"{item_key}_by", "") or "",
                        "notes": getattr(old_row, f"{item_key}_notes", "") or "",
                    })
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

        # Permanent (not per-day) list of queues a given tech should never be auto-assigned
        # to, e.g. a tech who isn't trained/authorized for a particular queue. Read by the
        # scheduler when allocating; has no effect on manual "Start Clock" assignments.
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS tech_queue_exclusions (
                dept_prefix TEXT,
                tech_name TEXT,
                queue_name TEXT,
                PRIMARY KEY (dept_prefix, tech_name, queue_name)
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

def dispatch_real_time_alert_async(message_body):
    """
    Fire-and-forget version of dispatch_real_time_alert -- runs the network call on a
    background thread instead of blocking the current script run. Use this anywhere the
    notification is a side effect of a user action (like Submit Metrics) rather than
    something the user needs a pass/fail result for on screen -- the webhook's own latency
    (up to the 5s timeout, longer if it's failing slowly) previously delayed the UI from
    showing success even after the actual data was already safely saved.
    """
    threading.Thread(target=dispatch_real_time_alert, args=(message_body,), daemon=True).start()

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
                            # Deliberately no manager-wide notification here -- this fires the
                            # instant the timer hits zero, before the tech has had any chance
                            # to miss the window. The individual tech reminder above is all
                            # that should happen at this point. The manager only hears about it
                            # if the tech actually fails to respond by fifteen_min_overdue_time
                            # below -- there's no separate 10-minute manager escalation anymore.
                            
                            session.execute(
                                text(f"UPDATE {table_name} SET tech_notified = 1 WHERE log_date = :c_date AND tech_name = :t_name AND slot_id = :s_id"),
                                {"c_date": CURRENT_DATE, "t_name": worker, "s_id": slot_num}
                            )
                            state_changed = True
                        
                        if current_now >= fifteen_min_overdue_time and db_s_not == 0:
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

@st.fragment
def render_dynamic_volume_ribbon(dept_prefix, dept_label):
    with db_conn.session as session:
        dept_queues = session.execute(text("SELECT queue_name, goal_target FROM dynamic_queues WHERE dept_prefix=:pfx ORDER BY queue_name"), {"pfx": dept_prefix}).fetchall()
        vol_rows = session.execute(text("SELECT queue_name, volume FROM queue_volumes WHERE log_date=:c_date AND dept_prefix=:pfx"), {"c_date": CURRENT_DATE, "pfx": dept_prefix}).fetchall()

    if not dept_queues:
        st.info(f"💡 No queues configured yet for {dept_label}. Add some in the Queue Management tab to start tracking daily volume here.")
        return

    volume_lookup = {r.queue_name: r.volume for r in vol_rows}

    autosave_error = st.session_state.pop(f"_volume_autosave_error_{dept_prefix}", None)
    if autosave_error:
        st.error(f"⚠️ Couldn't save a volume number just now: {autosave_error}")

    st.markdown(f"<h4 style='color: #1e3a8a; font-size:15px; margin-bottom:4px;'>📊 Today's {dept_label} Queue Volume (start-of-day counts, editable anytime)</h4>", unsafe_allow_html=True)

    def _save_volume_on_change(widget_key, tracking_key, dept_prefix, queue_name):
        """
        on_change callback -- runs synchronously the moment this specific field is edited,
        before any other rerun (including the global heartbeat) can be processed. This means
        a stale screen can never accidentally re-save someone else's field, since each field
        only ever saves itself, on its own genuine edit.
        """
        new_value = st.session_state.get(widget_key)
        try:
            with db_conn.session as session:
                session.execute(text("""
                    INSERT INTO queue_volumes (log_date, dept_prefix, queue_name, volume)
                    VALUES (:c_date, :pfx, :qname, :vol)
                    ON CONFLICT (log_date, dept_prefix, queue_name) DO UPDATE SET volume = EXCLUDED.volume
                """), {"c_date": CURRENT_DATE, "pfx": dept_prefix, "qname": queue_name, "vol": new_value})
                session.commit()
            st.session_state[tracking_key] = new_value
        except Exception as e:
            st.session_state[f"_volume_autosave_error_{dept_prefix}"] = str(e)

    num_cols = min(len(dept_queues), 6) or 1
    cols = st.columns(num_cols)
    for i, q in enumerate(dept_queues):
        with cols[i % num_cols]:
            current_value = int(volume_lookup.get(q.queue_name, 0))
            widget_key = f"vol_{dept_prefix}_{q.queue_name}_{CURRENT_DATE}"
            tracking_key = f"{widget_key}__tracked_saved_value"
            # Whenever the DB disagrees with what this session last confirmed was saved
            # (first-ever render, or another user's save landed since we last checked),
            # delete and recreate the widget with the DB value as its explicit default,
            # rather than writing directly into its session_state.
            if tracking_key not in st.session_state or st.session_state[tracking_key] != current_value:
                if widget_key in st.session_state:
                    del st.session_state[widget_key]
                st.session_state[tracking_key] = current_value
            st.number_input(
                q.queue_name, min_value=0, step=1, value=current_value, key=widget_key,
                on_change=_save_volume_on_change, args=(widget_key, tracking_key, dept_prefix, q.queue_name)
            )

    st.markdown("<hr style='margin: 8px 0px 14px 0px !important; border-top: 2px solid #cbd5e1;'>", unsafe_allow_html=True)

# --- 6. RENDERING ENGINE FOR WORKER GRID ROWS ---
@st.fragment
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
            wipe_armed_key = f"wipe_armed_{prefix}_{w_id}"
            if not st.session_state.get(wipe_armed_key, False):
                if st.button(f"🚨 Wipe Profile & Timers for {worker} from {dept_label}", key=f"mgr_wipe_personnel_{prefix}_{w_id}"):
                    st.session_state[wipe_armed_key] = True
                    st.rerun()
            else:
                st.warning(f"⚠️ This permanently deletes {worker}'s profile and all of today's timer data for {dept_label}. This cannot be undone.")
                confirm_col1, confirm_col2 = st.columns(2)
                if confirm_col1.button(f"✅ Confirm Wipe {worker}", key=f"mgr_wipe_confirm_{prefix}_{w_id}", type="primary", use_container_width=True):
                    try:
                        with db_conn.session as session:
                            session.execute(text(f"DELETE FROM {db_table} WHERE log_date=:c_date AND tech_name=:t_name"), {"c_date": CURRENT_DATE, "t_name": worker})
                            session.execute(text("DELETE FROM global_roster WHERE dept_prefix=:pfx AND tech_name=:t_name"), {"pfx": prefix, "t_name": worker})
                            session.commit()
                        st.session_state["selected_profile_state"] = "-- Create New Profile --"
                        st.session_state.pop(wipe_armed_key, None)
                        # Full rerun (not fragment-scoped): this changes global_roster, which the
                        # sidebar's profile dropdown reads from, and the sidebar lives outside this fragment.
                        st.rerun()
                    except Exception as e:
                        st.error(f"⚠️ Couldn't wipe this profile right now: {str(e)}")
                if confirm_col2.button("Cancel", key=f"mgr_wipe_cancel_{prefix}_{w_id}", use_container_width=True):
                    st.session_state.pop(wipe_armed_key, None)
                    st.rerun()

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
                    elif slot_row.start_time is None:
                        # Auto-scheduler queued this slot to start automatically once an earlier
                        # slot for this tech is submitted. It's not running yet -- no timer, no
                        # display target -- but a manual override is available if someone wants
                        # to jump ahead rather than wait for the sequence.
                        st.markdown(f"Queue: `{slot_row.queue}`")
                        st.info("⏳ Queued — will start automatically once your current slot is submitted.")
                        if st.button("▶️ Start Now Anyway", key=f"queued_start_now_{prefix}_{w_id}_{slot_num}", use_container_width=True):
                            now_str = now_eastern_naive().strftime("%Y-%m-%d %H:%M:%S")
                            try:
                                with db_conn.session as session:
                                    session.execute(text(f"UPDATE {db_table} SET start_time=:st WHERE log_date=:c_date AND tech_name=:t_name AND slot_id=:s_id"), {"st": now_str, "c_date": CURRENT_DATE, "t_name": worker, "s_id": slot_num})
                                    session.commit()
                                fragment_rerun()
                            except Exception as e:
                                st.error(f"⚠️ Couldn't start this slot right now: {str(e)}")
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
                        fifteen_min_overdue_time = end_time + timedelta(minutes=15)
                        current_now = now_eastern_naive()
                        
                        if current_now < end_time and not db_sub:
                            rem = end_time - current_now
                            total_rem_seconds = int(rem.total_seconds())
                            total_alloc_seconds = int(db_dur_min) * 60
                            countdown_id = hashlib.md5(f"{db_table}_{worker}_{slot_num}_{db_start}".encode()).hexdigest()[:10]
                            # Ticks down in the browser via JS, independent of any Streamlit
                            # rerun -- so it can't race with Start Clock/Submit Metrics button
                            # clicks the way a server-refreshed countdown could, and it updates
                            # every second instead of only on the next rerun. Uses "seconds
                            # remaining right now" rather than an absolute end-time string,
                            # since a naive timestamp string would be parsed in the *viewer's*
                            # browser timezone by JS, not necessarily Eastern -- this way there's
                            # no timezone string to parse at all, just elapsed-time math.
                            countdown_html = f"""
                            <div style="font-family: 'Source Sans Pro', sans-serif;">
                                <div style="font-size: 13px; color: #808495; margin-bottom: 2px;">⏳ Time Remaining</div>
                                <div id="cd_time_{countdown_id}" style="font-size: 28px; font-weight: 600; color: #31333F;">--:--:--</div>
                                <div style="background-color: #e6e9ef; border-radius: 4px; height: 6px; margin-top: 8px; overflow: hidden;">
                                    <div id="cd_bar_{countdown_id}" style="background-color: #ff4b4b; height: 100%; width: 0%;"></div>
                                </div>
                            </div>
                            <script>
                            (function() {{
                                var remainingAtLoad = {total_rem_seconds};
                                var totalSeconds = {total_alloc_seconds};
                                var loadTime = new Date().getTime();
                                var timeEl = document.getElementById("cd_time_{countdown_id}");
                                var barEl = document.getElementById("cd_bar_{countdown_id}");
                                function pad(n) {{ return n < 10 ? "0" + n : "" + n; }}
                                function update() {{
                                    if (!timeEl) return;
                                    var elapsed = (new Date().getTime() - loadTime) / 1000;
                                    var distance = Math.max(0, remainingAtLoad - elapsed);
                                    if (distance <= 0) {{
                                        timeEl.innerHTML = "\\ud83d\\uded1 Expired";
                                        timeEl.style.color = "#ff4b4b";
                                        if (barEl) barEl.style.width = "100%";
                                        clearInterval(timerHandle);
                                        return;
                                    }}
                                    var h = Math.floor(distance / 3600);
                                    var m = Math.floor((distance % 3600) / 60);
                                    var s = Math.floor(distance % 60);
                                    timeEl.innerHTML = pad(h) + ":" + pad(m) + ":" + pad(s);
                                    var pct = totalSeconds > 0 ? Math.max(0, Math.min(100, (1 - distance / totalSeconds) * 100)) : 0;
                                    if (barEl) barEl.style.width = pct + "%";
                                }}
                                update();
                                var timerHandle = setInterval(update, 1000);
                            }})();
                            </script>
                            """
                            components.html(countdown_html, height=70)
                        elif not db_sub:
                            st.error("🛑 Timer Expired!")
                        
                        if current_now >= fifteen_min_overdue_time and not db_sub and db_s_not == 2:
                            st.error("🚨 CRITICAL: Past 15-Minute Deadline -- Manager Notified.")
                        
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

                                        # Auto-advance: this tech may have another queue queued up by
                                        # the auto-scheduler (assigned but not yet started, since only
                                        # one slot at a time should be actively running). Start the
                                        # earliest such slot now that this one is done.
                                        next_queued = session.execute(text(f"""
                                            SELECT slot_id FROM {db_table}
                                            WHERE log_date=:c_date AND tech_name=:t_name AND queue IS NOT NULL AND start_time IS NULL
                                            ORDER BY slot_id ASC LIMIT 1
                                        """), {"c_date": CURRENT_DATE, "t_name": worker}).fetchone()
                                        if next_queued:
                                            session.execute(text(f"UPDATE {db_table} SET start_time=:st WHERE log_date=:c_date AND tech_name=:t_name AND slot_id=:s_id"), {"st": time_logged_now.strftime("%Y-%m-%d %H:%M:%S"), "c_date": CURRENT_DATE, "t_name": worker, "s_id": next_queued.slot_id})

                                        session.commit()

                                    # Fire-and-forget: doesn't block the rerun below on the
                                    # webhook's network latency (previously this could still
                                    # take up to 5s+ even after the data-write reordering,
                                    # since fragment_rerun() below only ran after this call
                                    # returned -- meaning the screen wouldn't show "logged"
                                    # until the notification finished, even though the data
                                    # itself was already safely saved).
                                    if is_escalated:
                                        dispatch_real_time_alert_async(
                                            f"📉 **PRODUCTION ALERT: GOAL NOT MET (PRO-RATA)** 📉\n"
                                            f"👤 **Technician:** {worker.upper()}\n"
                                            f"🏢 **Department:** {dept_label}\n"
                                            f"⏱️ **Active Time Spent:** {actual_minutes_used} minutes\n"
                                            f"🎯 **Pro-Rata Target Expected:** {dynamic_target_threshold} units *(Based on {base_hourly_rate}/hr)*\n"
                                            f"📥 **Logged Production:** **{val}** units"
                                        )

                                    # Local to this slot -- the Analytics tab will pick up the new
                                    # metrics_history row on the next full-page heartbeat (every 15s).
                                    fragment_rerun()
                                except Exception as e:
                                    st.error(f"⚠️ Couldn't save these metrics right now: {str(e)}")
                        else:
                            st.success(f"✅ Logged Units: **{db_input}**")

# --- 7. CORE APP ROUTING INTERFACE ---
tab_de, tab_cc, tab_sh, tab_fi, tab_sched, tab_analytics, tab_mgmt = st.tabs([
    "💻 Data Entry", "📞 Call Center", "📦 Shipping", "🧪 Fill Department", "🗓️ Auto-Scheduler", "📊 Cumulative Analytics", "⚙️ Queue Management"
])

with tab_de:
    render_dynamic_volume_ribbon("de", "Data Entry")
    render_synchronized_matrix("data_entry_slots", "de", "Data Entry")
with tab_cc:
    render_dynamic_volume_ribbon("cc", "Call Center")
    render_synchronized_matrix("call_center_slots", "cc", "Call Center")
with tab_sh:
    render_dynamic_volume_ribbon("sh", "Shipping")
    render_synchronized_matrix("shipping_slots", "sh", "Shipping")
with tab_fi:
    render_dynamic_volume_ribbon("fi", "Fill")
    render_synchronized_matrix("fill_slots", "fi", "Fill")

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

# Scheduling preferences: try to give someone a full TARGET_BLOCK_MINUTES (or more) on one
# queue rather than fragmenting their day into many small pieces, but never go below
# MIN_ASSIGNMENT_MINUTES -- if volume/availability can't support the target, fall back to
# the largest block that's still reasonable rather than forcing something tiny.
MIN_ASSIGNMENT_MINUTES = 30
TARGET_BLOCK_MINUTES = 120

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
    params = {"start_date": f"{date_str}T00:00:00Z", "end_date": f"{date_str}T23:59:59Z", "date_filter": "start_at", "per_page": 100, "page": 1}

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
        exclusion_rows = session.execute(text("SELECT tech_name, queue_name FROM tech_queue_exclusions WHERE dept_prefix=:pfx"), {"pfx": dept_prefix}).fetchall()

    exclusions = {}
    for r in exclusion_rows:
        exclusions.setdefault(r.tech_name, set()).add(r.queue_name)

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
                    eligible = [t for t in tech_capacity if t["remaining"] >= MIN_ASSIGNMENT_MINUTES and t["slots_used"] < 4 and queue_name not in exclusions.get(t["tech"], set())]
                    if not eligible:
                        summary["unmet"][queue_name] = summary["unmet"].get(queue_name, 0) + round(remaining_alloc)
                        break

                    # Prefer a tech who can cover a full target-sized (or bigger) block of
                    # what's still needed here, rather than immediately reaching for whoever
                    # happens to have the single largest amount of time left. Among those,
                    # pick the one with the SMALLEST qualifying remaining capacity, since that
                    # uses up their day efficiently without hoarding a very-available tech's
                    # extra time that another queue might need more.
                    desired_block = min(remaining_alloc, TARGET_BLOCK_MINUTES)
                    strong_candidates = [t for t in eligible if t["remaining"] >= desired_block]
                    if strong_candidates:
                        pick = min(strong_candidates, key=lambda t: t["remaining"])
                    else:
                        # Nobody can hit the target -- fall back to whoever has the most time
                        # left, which at least keeps the block as large as availability allows.
                        pick = max(eligible, key=lambda t: t["remaining"])

                    chunk = min(remaining_alloc, pick["remaining"])
                    chunk_rounded = max(MIN_ASSIGNMENT_MINUTES, round(chunk / 15.0) * 15)
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

            for i, row in enumerate(rows):
                if not free_slots:
                    skipped.append(f"{tech_name}: no free slot left for {row.queue_name}")
                    continue
                target_slot = free_slots.pop(0)
                goal_str = rate_strings.get(row.queue_name, "")
                # Only the first assignment in the sequence starts immediately (a real
                # start_time). The rest are inserted as "queued" (start_time NULL, goal/queue
                # already set) and get auto-started one at a time as each prior one is
                # submitted -- see the auto-advance logic in the Submit Metrics handler.
                slot_start = now_str if i == 0 else None
                session.execute(text(f"""
                    INSERT INTO {db_table} (log_date, tech_name, slot_id, queue, goal, start_time, duration_minutes, input_number, tech_notified, supervisor_notified, submitted)
                    VALUES (:c_date, :t_name, :s_id, :queue, :goal, :st, :dur, NULL, 0, 0, 0)
                    ON CONFLICT (log_date, tech_name, slot_id) DO UPDATE
                    SET queue=EXCLUDED.queue, goal=EXCLUDED.goal, start_time=EXCLUDED.start_time, duration_minutes=EXCLUDED.duration_minutes, submitted=0, input_number=NULL
                """), {"c_date": CURRENT_DATE, "t_name": tech_name, "s_id": target_slot, "queue": row.queue_name, "goal": goal_str, "st": slot_start, "dur": row.duration_minutes})

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
                st.session_state[f"hb_sync_outcome_{dept_prefix}"] = {"result": result, "error": error}
                # Rerun so the shift dropdowns below immediately reflect the freshly-synced
                # data (they were previously stale on this same render since we skipped the
                # rerun to preserve the message -- this way we get both: the message is
                # persisted in session_state below instead of a one-off st.success() call,
                # so it survives this rerun instead of needing the rerun to be skipped.
                fragment_rerun()

            outcome = st.session_state.get(f"hb_sync_outcome_{dept_prefix}")
            if outcome:
                result, error = outcome["result"], outcome["error"]
                if error:
                    st.error(f"⚠️ {error}")
                else:
                    if result["matched"]:
                        st.success(f"Synced {len(result['matched'])} shift(s): " + ", ".join(f"{name} ({s}–{e})" for name, (s, e) in result["matched"].items()))
                    else:
                        st.warning(f"Homebase returned {result['total_fetched']} shift(s) today, but none matched a name in your {dept_label} roster.")
                    if result["unmatched_names"]:
                        st.caption(f"Not matched to anyone in your roster (name mismatch?): {', '.join(result['unmatched_names'])}")
                if st.button("✕ Dismiss", key=f"hb_dismiss_{dept_prefix}"):
                    st.session_state.pop(f"hb_sync_outcome_{dept_prefix}", None)
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

        shift_autosave_error = st.session_state.pop("_shift_autosave_error", None)
        if shift_autosave_error:
            st.error(f"⚠️ Couldn't save a shift change just now: {shift_autosave_error}")

        def _save_shift_choice(dept_prefix, tech_name, widget_key, tracking_key):
            """
            on_change callback for the shift-choice dropdown -- saves immediately on genuine
            user interaction, never based on a full-form snapshot. This is what closes the bug
            where clicking one big "Save" button could silently overwrite OTHER techs' shifts
            with whatever was stale/default on your particular screen at that moment.
            """
            chosen = st.session_state.get(widget_key)
            try:
                with db_conn.session as session:
                    if chosen == "Not Working Today":
                        session.execute(text("DELETE FROM tech_shifts WHERE log_date=:c_date AND dept_prefix=:pfx AND tech_name=:t_name"), {"c_date": CURRENT_DATE, "pfx": dept_prefix, "t_name": tech_name})
                    elif chosen == "Custom":
                        session.execute(text("""
                            INSERT INTO tech_shifts (log_date, dept_prefix, tech_name, shift_start, shift_end)
                            VALUES (:c_date, :pfx, :t_name, '09:00', '17:00')
                            ON CONFLICT (log_date, dept_prefix, tech_name) DO UPDATE SET shift_start=EXCLUDED.shift_start, shift_end=EXCLUDED.shift_end
                        """), {"c_date": CURRENT_DATE, "pfx": dept_prefix, "t_name": tech_name})
                    else:
                        p_start, p_end = SHIFT_PRESETS[chosen]
                        session.execute(text("""
                            INSERT INTO tech_shifts (log_date, dept_prefix, tech_name, shift_start, shift_end)
                            VALUES (:c_date, :pfx, :t_name, :s_start, :s_end)
                            ON CONFLICT (log_date, dept_prefix, tech_name) DO UPDATE SET shift_start=EXCLUDED.shift_start, shift_end=EXCLUDED.shift_end
                        """), {"c_date": CURRENT_DATE, "pfx": dept_prefix, "t_name": tech_name, "s_start": p_start.strftime("%H:%M"), "s_end": p_end.strftime("%H:%M")})
                    session.commit()
                st.session_state[tracking_key] = chosen
            except Exception as e:
                st.session_state["_shift_autosave_error"] = str(e)

        def _save_custom_time(dept_prefix, tech_name, db_column, widget_key):
            new_time = st.session_state.get(widget_key)
            try:
                with db_conn.session as session:
                    session.execute(text(f"UPDATE tech_shifts SET {db_column}=:val WHERE log_date=:c_date AND dept_prefix=:pfx AND tech_name=:t_name"), {"val": new_time.strftime("%H:%M"), "c_date": CURRENT_DATE, "pfx": dept_prefix, "t_name": tech_name})
                    session.commit()
            except Exception as e:
                st.session_state["_shift_autosave_error"] = str(e)

        for r in roster_rows:
            tech_name = r.tech_name
            t_id = hashlib.md5(tech_name.encode('utf-8')).hexdigest()[:8]
            cols = st.columns([2, 2, 1, 1])
            cols[0].markdown(f"**{tech_name}**")

            preset_options = ["Not Working Today"] + list(SHIFT_PRESETS.keys()) + ["Custom"]
            true_chosen = "Not Working Today"
            custom_start, custom_end = dtime(9, 0), dtime(17, 0)
            if tech_name in existing_shifts:
                s_str, e_str = existing_shifts[tech_name]
                matched_preset = next((label for label, (ps, pe) in SHIFT_PRESETS.items() if ps.strftime("%H:%M") == s_str and pe.strftime("%H:%M") == e_str), None)
                if matched_preset:
                    true_chosen = matched_preset
                else:
                    true_chosen = "Custom"
                    custom_start = datetime.strptime(s_str, "%H:%M").time()
                    custom_end = datetime.strptime(e_str, "%H:%M").time()

            choice_key = f"shift_choice_{dept_prefix}_{t_id}_{CURRENT_DATE}"
            choice_tracking_key = f"{choice_key}__tracked_saved_value"
            if choice_tracking_key not in st.session_state or st.session_state[choice_tracking_key] != true_chosen:
                if choice_key in st.session_state:
                    del st.session_state[choice_key]
                st.session_state[choice_tracking_key] = true_chosen

            chosen = cols[1].selectbox(
                "Shift", options=preset_options, index=preset_options.index(true_chosen), key=choice_key,
                label_visibility="collapsed", on_change=_save_shift_choice, args=(dept_prefix, tech_name, choice_key, choice_tracking_key)
            )

            if chosen == "Custom":
                start_key = f"shift_start_{dept_prefix}_{t_id}_{CURRENT_DATE}"
                end_key = f"shift_end_{dept_prefix}_{t_id}_{CURRENT_DATE}"
                start_tracking_key = f"{start_key}__tracked_saved_value"
                end_tracking_key = f"{end_key}__tracked_saved_value"
                if start_tracking_key not in st.session_state or st.session_state[start_tracking_key] != custom_start:
                    if start_key in st.session_state:
                        del st.session_state[start_key]
                    st.session_state[start_tracking_key] = custom_start
                if end_tracking_key not in st.session_state or st.session_state[end_tracking_key] != custom_end:
                    if end_key in st.session_state:
                        del st.session_state[end_key]
                    st.session_state[end_tracking_key] = custom_end

                cols[2].time_input("Start", value=custom_start, key=start_key, label_visibility="collapsed", on_change=_save_custom_time, args=(dept_prefix, tech_name, "shift_start", start_key))
                cols[3].time_input("End", value=custom_end, key=end_key, label_visibility="collapsed", on_change=_save_custom_time, args=(dept_prefix, tech_name, "shift_end", end_key))

        st.markdown("---")
        st.subheader(f"🚫 {dept_label} — Queue Exclusions")
        st.caption("Queues a tech should never be auto-assigned to (e.g. not trained/authorized for it). Doesn't affect manual Start Clock assignments.")

        with db_conn.session as session:
            dept_queue_rows = session.execute(text("SELECT queue_name FROM dynamic_queues WHERE dept_prefix=:pfx ORDER BY queue_name"), {"pfx": dept_prefix}).fetchall()
            existing_exclusion_rows = session.execute(text("SELECT tech_name, queue_name FROM tech_queue_exclusions WHERE dept_prefix=:pfx"), {"pfx": dept_prefix}).fetchall()
        dept_queue_names = [q.queue_name for q in dept_queue_rows]
        existing_exclusions = {}
        for r in existing_exclusion_rows:
            existing_exclusions.setdefault(r.tech_name, []).append(r.queue_name)

        if not dept_queue_names:
            st.caption("No queues configured yet for this department.")
        else:
            excl_autosave_error = st.session_state.pop("_exclusions_autosave_error", None)
            if excl_autosave_error:
                st.error(f"⚠️ Couldn't save an exclusion change just now: {excl_autosave_error}")

            def _save_exclusions(dept_prefix, tech_name, widget_key, tracking_key):
                """
                on_change callback, scoped to deleting/reinserting only THIS tech's exclusion
                rows -- the previous version deleted every tech's exclusions in the whole
                department before reinserting whatever the current screen showed, which meant
                one person's save could silently wipe another tech's exclusions that simply
                hadn't loaded yet on that screen.
                """
                chosen_exclusions = st.session_state.get(widget_key, [])
                try:
                    with db_conn.session as session:
                        session.execute(text("DELETE FROM tech_queue_exclusions WHERE dept_prefix=:pfx AND tech_name=:t_name"), {"pfx": dept_prefix, "t_name": tech_name})
                        for q in chosen_exclusions:
                            session.execute(text("""
                                INSERT INTO tech_queue_exclusions (dept_prefix, tech_name, queue_name)
                                VALUES (:pfx, :t_name, :q)
                                ON CONFLICT (dept_prefix, tech_name, queue_name) DO NOTHING
                            """), {"pfx": dept_prefix, "t_name": tech_name, "q": q})
                        session.commit()
                    st.session_state[tracking_key] = sorted(chosen_exclusions)
                except Exception as e:
                    st.session_state["_exclusions_autosave_error"] = str(e)

            for r in roster_rows:
                tech_name = r.tech_name
                t_id = hashlib.md5(tech_name.encode('utf-8')).hexdigest()[:8]
                true_exclusions = sorted([q for q in existing_exclusions.get(tech_name, []) if q in dept_queue_names])
                widget_key = f"excl_{dept_prefix}_{t_id}"
                tracking_key = f"{widget_key}__tracked_saved_value"
                if tracking_key not in st.session_state or st.session_state[tracking_key] != true_exclusions:
                    if widget_key in st.session_state:
                        del st.session_state[widget_key]
                    st.session_state[tracking_key] = true_exclusions

                st.multiselect(
                    f"{tech_name}", options=dept_queue_names, default=true_exclusions, key=widget_key,
                    on_change=_save_exclusions, args=(dept_prefix, tech_name, widget_key, tracking_key)
                )

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

            st.markdown("**Proposed Assignments (adjust as needed, then save and approve):**")
            by_tech_display = {}
            for r in proposal_rows:
                by_tech_display.setdefault(r.tech_name, []).append(r)

            edited_updates = []   # (tech_name, proposal_slot, queue_name, duration_minutes)
            edited_deletes = []   # (tech_name, proposal_slot)

            for tech_name, rows in by_tech_display.items():
                t_id = hashlib.md5(tech_name.encode('utf-8')).hexdigest()[:8]
                st.markdown(f"👤 **{tech_name}**")
                for r in rows:
                    rc1, rc2, rc3 = st.columns([2.5, 1, 0.8])
                    q_options = dept_queue_names if r.queue_name in dept_queue_names else dept_queue_names + [r.queue_name]
                    new_q = rc1.selectbox("Queue", options=q_options, index=q_options.index(r.queue_name), key=f"padj_q_{dept_prefix}_{t_id}_{r.proposal_slot}", label_visibility="collapsed")
                    new_dur = rc2.number_input("Min", min_value=5, step=5, value=max(5, int(r.duration_minutes)), key=f"padj_d_{dept_prefix}_{t_id}_{r.proposal_slot}", label_visibility="collapsed")
                    remove = rc3.checkbox("Remove", key=f"padj_rm_{dept_prefix}_{t_id}_{r.proposal_slot}")
                    if remove:
                        edited_deletes.append((tech_name, r.proposal_slot))
                    else:
                        edited_updates.append((tech_name, r.proposal_slot, new_q, int(new_dur)))

                if dept_queue_names:
                    with st.expander(f"+ Add another assignment for {tech_name}"):
                        add_c1, add_c2, add_c3 = st.columns([2.5, 1, 1])
                        add_q = add_c1.selectbox("Queue", options=dept_queue_names, key=f"padj_new_q_{dept_prefix}_{t_id}", label_visibility="collapsed")
                        add_dur = add_c2.number_input("Min", min_value=5, step=5, value=30, key=f"padj_new_d_{dept_prefix}_{t_id}", label_visibility="collapsed")
                        if add_c3.button("Add", key=f"padj_add_{dept_prefix}_{t_id}"):
                            try:
                                next_slot = max([r.proposal_slot for r in rows], default=0) + 1
                                with db_conn.session as session:
                                    session.execute(text("""
                                        INSERT INTO schedule_proposals (log_date, dept_prefix, tech_name, proposal_slot, queue_name, duration_minutes)
                                        VALUES (:c_date, :pfx, :t_name, :slot, :queue, :dur)
                                    """), {"c_date": CURRENT_DATE, "pfx": dept_prefix, "t_name": tech_name, "slot": next_slot, "queue": add_q, "dur": int(add_dur)})
                                    session.commit()
                                fragment_rerun()
                            except Exception as e:
                                st.error(f"⚠️ Couldn't add this assignment right now: {str(e)}")

            if st.button(f"💾 Save Adjustments", key=f"save_adj_{dept_prefix}", use_container_width=True):
                try:
                    with db_conn.session as session:
                        for tech_name, slot, q, dur in edited_updates:
                            session.execute(text("""
                                UPDATE schedule_proposals SET queue_name=:q, duration_minutes=:dur
                                WHERE log_date=:c_date AND dept_prefix=:pfx AND tech_name=:t_name AND proposal_slot=:slot
                            """), {"q": q, "dur": dur, "c_date": CURRENT_DATE, "pfx": dept_prefix, "t_name": tech_name, "slot": slot})
                        for tech_name, slot in edited_deletes:
                            session.execute(text("""
                                DELETE FROM schedule_proposals
                                WHERE log_date=:c_date AND dept_prefix=:pfx AND tech_name=:t_name AND proposal_slot=:slot
                            """), {"c_date": CURRENT_DATE, "pfx": dept_prefix, "t_name": tech_name, "slot": slot})
                        session.commit()
                    st.success("Adjustments saved.")
                    fragment_rerun()
                except Exception as e:
                    st.error(f"⚠️ Couldn't save adjustments right now: {str(e)}")

            approve_col1, approve_col2 = st.columns(2)
            if approve_col1.button(f"✅ Approve & Apply {dept_label} Schedule", key=f"approve_{dept_prefix}", type="primary", use_container_width=True):
                try:
                    skipped = apply_schedule_proposal(dept_prefix, db_table)
                    if skipped:
                        st.warning("Applied with some exceptions (existing active slots were not overwritten):\n\n" + "\n".join(f"- {s}" for s in skipped))
                    else:
                        st.success(f"{dept_label} schedule applied — first assignment started for each tech; the rest will auto-start in sequence as each is submitted.")
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

            st.markdown("---")
            st.subheader("📋 Daily Verification Checklist Items")
            st.caption("Add, remove, or adjust aging rules for rows shown in the Global Facility Daily Queue Verification Log.")
            with db_conn.session as session:
                current_checklist_items = session.execute(text("SELECT item_key, label, aging_basis, red_threshold_days FROM checklist_items ORDER BY sort_order, label")).fetchall()

            if not current_checklist_items:
                st.info("No checklist items configured yet.")
            else:
                for it in current_checklist_items:
                    with st.container(border=True):
                        ic1, ic2 = st.columns([3, 1])
                        ic1.markdown(f"**{it.label}**")
                        basis_label = "Target date vs Oldest date" if it.aging_basis == "target_minus_oldest" else "Today vs Oldest date"
                        ic1.caption(f"Aging basis: {basis_label} | Turns red at {it.red_threshold_days}+ days")
                        if ic2.button("🗑️ Remove", key=f"del_checklist_item_{it.item_key}", use_container_width=True):
                            try:
                                with db_conn.session as session:
                                    session.execute(text("DELETE FROM checklist_items WHERE item_key=:k"), {"k": it.item_key})
                                    session.commit()
                                fragment_rerun()
                            except Exception as e:
                                st.error(f"⚠️ Couldn't remove this item right now: {str(e)}")

            st.markdown("---")
            st.caption("Add a new checklist row:")
            add_c1, add_c2, add_c3, add_c4 = st.columns([2, 2, 1, 1])
            new_checklist_label = add_c1.text_input("Label", key="new_checklist_item_label")
            new_checklist_basis = add_c2.selectbox(
                "Aging basis", options=["target_minus_oldest", "today_minus_oldest"],
                format_func=lambda x: "Target date vs Oldest date" if x == "target_minus_oldest" else "Today vs Oldest date",
                key="new_checklist_item_basis"
            )
            new_checklist_threshold = add_c3.number_input("Red threshold (days)", min_value=1, step=1, value=7, key="new_checklist_item_threshold")
            if add_c4.button("➕ Add", key="add_checklist_item_btn", use_container_width=True):
                if new_checklist_label.strip():
                    try:
                        item_key = re.sub(r'[^a-z0-9_]', '_', new_checklist_label.strip().lower())
                        with db_conn.session as session:
                            max_order_row = session.execute(text("SELECT COALESCE(MAX(sort_order), 0) as m FROM checklist_items")).fetchone()
                            max_order = max_order_row.m if max_order_row else 0
                            session.execute(text("""
                                INSERT INTO checklist_items (item_key, label, aging_basis, red_threshold_days, sort_order)
                                VALUES (:k, :l, :b, :t, :o)
                                ON CONFLICT (item_key) DO UPDATE SET label=EXCLUDED.label, aging_basis=EXCLUDED.aging_basis, red_threshold_days=EXCLUDED.red_threshold_days
                            """), {"k": item_key, "l": new_checklist_label.strip(), "b": new_checklist_basis, "t": int(new_checklist_threshold), "o": max_order + 1})
                            session.commit()
                        fragment_rerun()
                    except Exception as e:
                        st.error(f"⚠️ Couldn't add this item right now: {str(e)}")
                else:
                    st.warning("Enter a label first.")

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
@st.fragment
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
                        fragment_rerun()
                    except Exception as e:
                        st.error(f"⚠️ Couldn't update the deadline right now: {str(e)}")

        with c_col:
            with db_conn.session as session:
                checklist_items_fresh = session.execute(text("SELECT item_key, label, aging_basis, red_threshold_days FROM checklist_items ORDER BY sort_order, label")).fetchall()
                entry_rows = session.execute(text("SELECT item_key, status, oldest_date, target_date, verified_by, notes FROM checklist_entries WHERE log_date=:c_date"), {"c_date": CURRENT_DATE}).fetchall()
            entries_by_key = {r.item_key: r for r in entry_rows}

            if not checklist_items_fresh:
                st.info("No checklist items configured yet. Add some from ⚙️ Manage Checklist Items above.")
                return

            def parse_stored_date(val):
                if not val or str(val).strip() == "": return datetime.now().date()
                try: return datetime.strptime(str(val).strip(), "%Y-%m-%d").date()
                except: return datetime.now().date()

            def compute_aging(aging_basis, red_threshold, odt, tdt):
                try:
                    date_delta = (datetime.now().date() - odt).days if aging_basis == "today_minus_oldest" else (tdt - odt).days
                    is_red = date_delta >= red_threshold
                    badge = f"🚨 {date_delta} Days" if is_red else (f"⚠️ {date_delta} Days" if date_delta > 0 else "✅ Current")
                    return date_delta, is_red, badge
                except Exception:
                    return 0, False, "-"

            autosave_error = st.session_state.pop("_checklist_autosave_error", None)
            if autosave_error:
                st.error(f"⚠️ Autosave failed for a checklist field -- your last entry may not be saved: {autosave_error}")

            # Cheap signature of everything that would affect the displayed table (both the
            # item config and the day's entries). Only rebuild the DataFrame we hand to
            # data_editor when this actually differs from what we last built it from --
            # otherwise the exact same DataFrame object is reused, so data_editor has no
            # reason to reset anything. Previously the table was rebuilt fresh on literally
            # every rerun, including ones where nothing had changed at all (e.g. the global
            # heartbeat firing with zero other activity), which was tearing down in-progress
            # selections for no reason.
            sig_parts = []
            for item in checklist_items_fresh:
                entry = entries_by_key.get(item.item_key)
                sig_parts.append("|".join([
                    item.item_key, item.label, item.aging_basis, str(item.red_threshold_days),
                    entry.status if entry else "Pending",
                    entry.oldest_date if entry else "", entry.target_date if entry else "",
                    entry.verified_by if entry else "", entry.notes if entry else "",
                ]))
            current_signature = "||".join(sig_parts)

            cache_key = "checklist_table_cache"
            sig_key = "checklist_table_signature"

            if cache_key not in st.session_state or st.session_state.get(sig_key) != current_signature:
                table_rows = []
                for item in checklist_items_fresh:
                    entry = entries_by_key.get(item.item_key)
                    status = entry.status if entry else "Pending"
                    odt = parse_stored_date(entry.oldest_date if entry else "")
                    tdt = parse_stored_date(entry.target_date if entry else "")
                    by = entry.verified_by if entry else ""
                    notes = entry.notes if entry else ""
                    _, _, badge = compute_aging(item.aging_basis, item.red_threshold_days, odt, tdt)
                    table_rows.append({
                        "Queue": item.label, "Status": status, "Oldest Date": odt, "Target Date": tdt,
                        "Aging": badge, "Verified By": by, "Notes/Explanations": notes,
                    })
                st.session_state[cache_key] = pd.DataFrame(table_rows)
                st.session_state["checklist_items_cache"] = checklist_items_fresh
                st.session_state[sig_key] = current_signature

            checklist_df = st.session_state[cache_key]
            checklist_items = st.session_state["checklist_items_cache"]

            # st.data_editor tracks exactly which cells were touched via its own built-in
            # edited_rows mechanism, and checklist_items/checklist_entries (normalized, like
            # dynamic_queues/queue_volumes) is what makes rows genuinely addable/removable --
            # the old fixed-column daily_checklist design couldn't support that at all.
            edited_df = st.data_editor(
                checklist_df,
                key="checklist_data_editor",
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Queue": st.column_config.TextColumn("Queue", disabled=True),
                    "Status": st.column_config.SelectboxColumn("Status", options=["Pending", "Yes", "No"], required=True),
                    "Oldest Date": st.column_config.DateColumn("Oldest Date"),
                    "Target Date": st.column_config.DateColumn("Target Date"),
                    "Aging": st.column_config.TextColumn("Aging", disabled=True),
                    "Verified By": st.column_config.TextColumn("Verified By"),
                    "Notes/Explanations": st.column_config.TextColumn("Notes/Explanations"),
                },
            )

            COLUMN_TO_ENTRY_FIELD = {
                "Status": "status", "Oldest Date": "oldest_date", "Target Date": "target_date",
                "Verified By": "verified_by", "Notes/Explanations": "notes",
            }

            edited_rows = st.session_state.get("checklist_data_editor", {}).get("edited_rows", {})
            last_processed_key = "_checklist_last_processed_edits"
            last_processed = st.session_state.get(last_processed_key, {})

            new_edits_to_save = {}
            for row_idx, changes in edited_rows.items():
                prev_changes = last_processed.get(row_idx, {})
                diff_changes = {k: v for k, v in changes.items() if prev_changes.get(k) != v}
                if diff_changes:
                    new_edits_to_save[row_idx] = diff_changes

            if new_edits_to_save:
                try:
                    with db_conn.session as session:
                        for row_idx, changes in new_edits_to_save.items():
                            item_key = checklist_items[int(row_idx)].item_key
                            set_parts = []
                            params = {"c_date": CURRENT_DATE, "item_key": item_key}
                            for col_name, new_val in changes.items():
                                if col_name not in COLUMN_TO_ENTRY_FIELD:
                                    continue
                                field = COLUMN_TO_ENTRY_FIELD[col_name]
                                val_to_store = str(new_val) if col_name in ("Oldest Date", "Target Date") else new_val
                                set_parts.append(f"{field}=:{field}")
                                params[field] = val_to_store
                            if set_parts:
                                session.execute(text("""
                                    INSERT INTO checklist_entries (log_date, item_key)
                                    VALUES (:c_date, :item_key)
                                    ON CONFLICT (log_date, item_key) DO NOTHING
                                """), {"c_date": CURRENT_DATE, "item_key": item_key})
                                session.execute(text(f"UPDATE checklist_entries SET {', '.join(set_parts)} WHERE log_date=:c_date AND item_key=:item_key"), params)
                        session.commit()
                    merged = dict(last_processed)
                    for row_idx, changes in edited_rows.items():
                        merged.setdefault(row_idx, {}).update(changes)
                    st.session_state[last_processed_key] = merged
                except Exception as e:
                    st.session_state["_checklist_autosave_error"] = str(e)

            st.markdown("<br>", unsafe_allow_html=True)

            form_states = {}
            for i, item in enumerate(checklist_items):
                row = edited_df.iloc[i]
                odt_val = row["Oldest Date"]
                tdt_val = row["Target Date"]
                delta, is_red, _ = compute_aging(item.aging_basis, item.red_threshold_days, odt_val, tdt_val)
                form_states[item.item_key] = {
                    "label": item.label, "status": row["Status"], "odt": str(odt_val), "tdt": str(tdt_val),
                    "by": row["Verified By"], "notes": row["Notes/Explanations"], "is_red": is_red, "delta": delta
                }

            already_submitted_today = bool(chk.last_submitted_at) if chk else False
            resubmit_armed_key = "checklist_resubmit_armed"

            if already_submitted_today:
                st.info(f"✅ Already submitted today at **{chk.last_submitted_at} EST**. Submitting again will re-send Chat alerts for anything still flagged below.")

            if already_submitted_today and not st.session_state.get(resubmit_armed_key, False):
                submit_clicked = False
                if st.button("🔁 Resubmit Anyway", key="checklist_resubmit_arm_btn", use_container_width=True):
                    st.session_state[resubmit_armed_key] = True
                    fragment_rerun()
            else:
                button_label = "⚠️ Confirm Resubmit (will re-send Chat alerts for flagged items)" if already_submitted_today else "💾 Submit Daily Verification Report"
                submit_clicked = st.button(button_label, type="primary", use_container_width=True, key="submit_daily_report_btn")

            if submit_clicked:
                deficiency_list = []
                try:
                    with db_conn.session as session:
                        for item_key, data in form_states.items():
                            session.execute(text("""
                                INSERT INTO checklist_entries (log_date, item_key, status, oldest_date, target_date, verified_by, notes)
                                VALUES (:c_date, :item_key, :status, :odt, :tdt, :by, :notes)
                                ON CONFLICT (log_date, item_key) DO UPDATE
                                SET status=EXCLUDED.status, oldest_date=EXCLUDED.oldest_date, target_date=EXCLUDED.target_date,
                                    verified_by=EXCLUDED.verified_by, notes=EXCLUDED.notes
                            """), {"c_date": CURRENT_DATE, "item_key": item_key, "status": data["status"], "odt": data["odt"], "tdt": data["tdt"], "by": data["by"], "notes": data["notes"]})

                            if data["status"] == "No" or data["is_red"]:
                                deficiency_list.append(f"• **{data['label']}**\n  ↳ Reason: {'⚠️ STATUS: NO' if data['status'] == 'No' else '🚨 CRITICAL AGING'} | Backlog: {data['delta']} Days" + (f" (Notes: {data['by']} - {data['notes']})" if data['by'] or data['notes'] else ""))

                        submitted_at_str = now_eastern_naive().strftime("%H:%M:%S")
                        session.execute(text("UPDATE daily_checklist SET reminder_sent=1, supervisor_escaped=1, last_submitted_at=:t WHERE log_date=:c_date"), {"t": submitted_at_str, "c_date": CURRENT_DATE})
                        session.commit()

                    if deficiency_list:
                        chat_sent_ok = dispatch_real_time_alert(f"📋 **FACILITY OPERATIONS DAILY VERIFICATION REPORT**\n⏰ **Timestamp:** {submitted_at_str} EST\n⚠️ *The following operational tracking points require attention:* \n\n" + "\n\n".join(deficiency_list))
                        st.success("Verification data saved.")
                        if chat_sent_ok:
                            st.success("Deficiency summary report compiled and pushed to Google Chat!")
                        else:
                            st.warning("⚠️ The verification data saved, but the Google Chat notification failed to send. Check the webhook configuration/connectivity.")
                    else:
                        st.success("Verification metrics logged successfully! All operational channels are current.")

                    st.session_state[resubmit_armed_key] = False
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
