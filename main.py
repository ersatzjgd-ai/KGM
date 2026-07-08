import os
import urllib.parse
from datetime import datetime
import tempfile
from fpdf import FPDF
from taipy.gui import Gui, notify, download
import taipy.gui.builder as tgb
from supabase import create_client, Client
import pandas as pd

# ==========================================
# 1. ACTUAL SUPABASE INITIALIZATION & VALIDATION
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
db_status_ui = "🔄 Checking Connection..."
supabase = None

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ Missing SUPABASE_URL or SUPABASE_KEY in Railway Environment Variables!")
    db_status_ui = "🔴 Missing Railway Variables"
else:
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        supabase.table("guests").select("id").limit(1).execute()
        print("✅ Supabase connection and schema validated successfully.")
        db_status_ui = "🟢 Live Database Connected"
    except Exception as e:
        error_msg = str(e).lower()
        if "relation" in error_msg or "not found" in error_msg:
            print("⚠️ Database connected, but 'guests' table is missing.")
            db_status_ui = "⚠️ DB Connected, but 'guests' table is missing!"
        else:
            print(f"⚠️ Failed to initialize Supabase: {e}")
            db_status_ui = "🔴 Database Offline"
        supabase = None

# ==========================================
# 2. STATE VARIABLES
# ==========================================
role = "On-Ground Team 🏃"
role_options = ["On-Ground Team 🏃", "Manager 👔"]

# Manager State
manager_logged_in = False
pwd_input = ""
search_incoming = ""
session_type = "Morning"
guest_names_input = ""

# Base DataFrame structure to prevent rendering crashes when tables are empty
empty_df = pd.DataFrame(columns=["id", "guest_name", "session_type", "lounge", "is_active", "lmw_status", "demo_status", "ready_to_meet_gurudev", "met_gurudev"])
expected_guests = empty_df.copy()
filtered_expected = empty_df.copy()
mgr_active_guests = empty_df.copy()
active_guests = empty_df.copy()

# On-Ground Team State
selected_lounge_view = "All"
lounge_options = ["All", "Unassigned", "L1", "L2", "L3", "BR", "L5"]
search_active = ""

# Smart Drawer (Dialog) State
show_drawer = False
selected_guest_id = ""
selected_guest_name = ""
selected_guest_lounge = "Unassigned"
selected_guest_lmw = "Not yet"
selected_guest_demo = "Not yet"
selected_guest_ready = False
selected_guest_guru = False
wa_url = "#"
status_options = ["Not yet", "Done", "Skipped"]

# ==========================================
# 3. CORE LOGIC / REFRESH FUNCTIONS
# ==========================================
def get_today_start():
    """Dynamically calculates midnight UTC to match Supabase timestamps exactly."""
    return f"{datetime.utcnow().strftime('%Y-%m-%d')}T00:00:00+00:00"

def refresh_connection(state):
    notify(state, "info", "Checking database connection...")
    global supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            temp_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            temp_client.table("guests").select("id").limit(1).execute()
            supabase = temp_client
            state.db_status_ui = "🟢 Live Database Connected"
            notify(state, "success", "Database reconnected successfully!")
            refresh_data(state)
        except Exception as e:
            state.db_status_ui = "🔴 Database Offline or Schema Missing"
            notify(state, "error", "Could not verify database connection or schema.")

def refresh_data(state):
    if not supabase: return
    today_start = get_today_start()
    
    try:
        # Incoming
        res_inc = supabase.table("guests").select("*").eq("is_active", False).eq("has_left_kaveri", False).gte("created_at", today_start).order("created_at").execute()
        state.expected_guests = pd.DataFrame(res_inc.data) if res_inc.data else empty_df.copy()
        filter_incoming_guests(state)

        # Active
        res_act = supabase.table("guests").select("*").eq("is_active", True).eq("jai_gurudev", False).gte("created_at", today_start).order("created_at").execute()
        df_act = pd.DataFrame(res_act.data) if res_act.data else empty_df.copy()
        
        # Explicit copies force the UI tables to redraw
        state.mgr_active_guests = df_act.copy()
        state.active_guests = df_act.copy()
    except Exception as e:
        print(f"Database fetch error: {e}")

def filter_incoming_guests(state):
    search = state.search_incoming.lower()
    # Explicit copy forces the UI table to detect a state change and redraw
    df = state.expected_guests.copy() 
    
    if not search or df.empty:
        state.filtered_expected = df
    else:
        state.filtered_expected = df[df['guest_name'].str.lower().str.contains(search, na=False)]

def on_search_change(state): 
    filter_incoming_guests(state)

# ==========================================
# 4. SMART DRAWER & TEAM ACTIONS
# ==========================================
def update_wa_url(state):
    msg = (
        f"*{state.selected_guest_lounge}*\n"
        f"{state.selected_guest_name}\n"
        f"📺 LMW: {state.selected_guest_lmw}\n"
        f"💻 IP Demo: {state.selected_guest_demo}\n"
        f"⏳ Ready for Vyas: {'✅' if state.selected_guest_ready else '❌'}\n"
        f"🤝 Met Gurudev: {'✅' if state.selected_guest_guru else '❌'}"
    )
    state.wa_url = f"https://wa.me/?text={urllib.parse.quote(msg)}"

def open_drawer(state, id, payload):
    row_index = payload.get("index")
    if row_index is not None and not state.active_guests.empty:
        guest = state.active_guests.iloc[row_index]
        state.selected_guest_id = guest["id"]
        state.selected_guest_name = guest["guest_name"]
        state.selected_guest_lounge = guest.get("lounge", "Unassigned")
        state.selected_guest_lmw = guest.get("lmw_status", "Not yet")
        state.selected_guest_demo = guest.get("demo_status", "Not yet")
        state.selected_guest_ready = guest.get("ready_to_meet_gurudev", False)
        state.selected_guest_guru = guest.get("met_gurudev", False)
        
        update_wa_url(state)
        state.show_drawer = True

def on_drawer_change(state):
    update_wa_url(state)

def save_drawer_updates(state):
    if not supabase: return
    update_data = {
        "lounge": state.selected_guest_lounge,
        "lmw_status": state.selected_guest_lmw,
        "demo_status": state.selected_guest_demo,
        "ready_to_meet_gurudev": state.selected_guest_ready,
        "met_gurudev": state.selected_guest_guru
    }
    try:
        supabase.table("guests").update(update_data).eq("id", state.selected_guest_id).execute()
        notify(state, "success", f"Saved updates for {state.selected_guest_name}")
        state.show_drawer = False
        refresh_data(state)
    except Exception as e:
        notify(state, "error", "Failed to save updates.")

def checkout_guest(state):
    if not supabase: return
    try:
        supabase.table("guests").update({"jai_gurudev": True, "is_active": False}).eq("id", state.selected_guest_id).execute()
        notify(state, "success", f"{state.selected_guest_name} marked as Jai Gurudev!")
        state.show_drawer = False
        refresh_data(state)
    except Exception as e:
        notify(state, "error", "Failed to checkout guest.")

# ==========================================
# 5. MANAGER CALLBACK FUNCTIONS
# ==========================================
def login_action(state):
    correct_password = os.environ.get("MANAGER_PASSWORD", "kaveri_admin")
    if state.pwd_input == correct_password: 
        state.manager_logged_in = True
        refresh_data(state)
        notify(state, "success", "Logged in successfully!") 
    else:
        notify(state, "error", "Incorrect password.")

def logout_action(state):
    state.manager_logged_in = False
    state.pwd_input = ""
    notify(state, "info", "Logged out.")

def save_new_guests(state):
    if not supabase: return
    if state.guest_names_input.strip():
        names_list = [name.strip() for name in state.guest_names_input.split('\n') if name.strip()]
        insert_data = [{"guest_name": name, "session_type": state.session_type} for name in names_list]
        try:
            supabase.table("guests").insert(insert_data).execute()
            notify(state, "success", f"Added {len(names_list)} guests!")
            state.guest_names_input = ""
            # Triggers dynamic data refresh and UI redraw
            refresh_data(state)
        except Exception as e:
            notify(state, "error", "Failed to save guests.")

def generate_pdf_report(state):
    if not supabase: return
    try:
        today_start = get_today_start()
        res = supabase.table("guests").select("*").gte("created_at", today_start).order("created_at").execute()
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, txt=f"Kaveri GM - Session Report ({datetime.now().strftime('%Y-%m-%d')})", ln=True, align='C')
        pdf.ln(5)
        for g in res.data:
            pdf.set_font("Arial", 'B', 12)
            pdf.cell(0, 8, txt=f"Guest: {g['guest_name']} ({g.get('session_type', 'N/A')})", ln=True)
            pdf.set_font("Arial", '', 10)
            pdf.cell(0, 6, txt=f"Lounge: {g.get('lounge', 'Unassigned')} | LMW: {g.get('lmw_status', 'Not yet')}", ln=True)
            pdf.ln(2)
        pdf_file_path = os.path.join(tempfile.gettempdir(), f"Kaveri_Report_{datetime.now().strftime('%Y%m%d')}.pdf")
        pdf.output(pdf_file_path)
        download(state, content=pdf_file_path, name=f"Kaveri_Report_{datetime.now().strftime('%Y%m%d')}.pdf")
        notify(state, "success", "Report downloaded!")
    except Exception as e:
        notify(state, "error", "Failed to generate report.")

# ==========================================
# 6. GUI LAYOUT
# ==========================================
with tgb.Page() as main_page:
    # Header & Status Indicator
    tgb.layout(columns="1 1")
    with tgb.part():
        tgb.text("🏛️ Kaveri GM", class_name="h1")
    with tgb.part():
        tgb.text("{db_status_ui}", class_name="h4")
        tgb.button("🔄 Retry Connection", on_action=refresh_connection)
    
    tgb.selector(value="{role}", lov="{role_options}", dropdown=False)
    tgb.html("hr")

    # ------------------------------------------
    # MANAGER VIEW
    # ------------------------------------------
    with tgb.part(render="{role == 'Manager 👔'}"):
        with tgb.part(render="{not manager_logged_in}"):
            tgb.text("🔒 Manager Access", class_name="h2")
            tgb.input("{pwd_input}", password=True, label="Enter Admin Password")
            tgb.button("Login", on_action=login_action)
            
        with tgb.part(render="{manager_logged_in}"):
            tgb.layout(columns="4 1")
            with tgb.part(): tgb.text("")
            with tgb.part(): tgb.button("Logout", on_action=logout_action)
            
            tgb.text("📥 Incoming Guests", class_name="h3")
            tgb.input("{search_incoming}", on_change=on_search_change, label="🔍 Search Expected Guest...")
            tgb.table("{filtered_expected}", filter=True, page_size=10)
            
            tgb.html("hr")
            tgb.text("🟢 Arrived Guests", class_name="h3")
            tgb.table("{mgr_active_guests}", filter=True, page_size=10) 
            
            tgb.html("hr")
            with tgb.expandable(title="➕ Add New Expected Guests"):
                tgb.selector(value="{session_type}", lov=["Morning", "Evening"], dropdown=False)
                tgb.input("{guest_names_input}", multiline=True, label="Guest Names (One per line)")
                tgb.button("💾 Save to Database", on_action=save_new_guests)

            tgb.html("hr")
            with tgb.expandable(title="📊 View End of Session Report"):
                tgb.button("📥 Download Report as PDF", on_action=generate_pdf_report, class_name="primary")

    # ------------------------------------------
    # ON-GROUND TEAM VIEW (Smart Drawer Architecture)
    # ------------------------------------------
    with tgb.part(render="{role == 'On-Ground Team 🏃'}"):
        tgb.text("🏃 Active Team Dashboard", class_name="h2")
        tgb.text("Tap any guest card below to open controls.", class_name="text-muted")
        
        # Interactive Table: Triggers open_drawer when any row is clicked
        tgb.table("{active_guests}", on_action=open_drawer, filter=True, page_size=15)
        
        # --- THE SMART DRAWER (DIALOG) ---
        with tgb.dialog("{show_drawer}", title="Managing: {selected_guest_name}"):
            tgb.text("Lounge Assignment", class_name="h4")
            tgb.selector(value="{selected_guest_lounge}", lov="{lounge_options}", dropdown=True, on_change=on_drawer_change)
            
            tgb.html("br")
            tgb.text("Journey Status", class_name="h4")
            tgb.selector(value="{selected_guest_lmw}", lov="{status_options}", label="📺 LMW Status", dropdown=False, on_change=on_drawer_change)
            tgb.selector(value="{selected_guest_demo}", lov="{status_options}", label="💻 IP Demo Status", dropdown=False, on_change=on_drawer_change)
            
            tgb.html("br")
            tgb.toggle(value="{selected_guest_ready}", label="⏳ Ready for Vyas / Gurudev", on_change=on_drawer_change)
            tgb.toggle(value="{selected_guest_guru}", label="🤝 Met Gurudev", on_change=on_drawer_change)
            
            tgb.html("hr")
            tgb.layout(columns="1 1")
            with tgb.part():
                tgb.button("💾 Save Updates", on_action=save_drawer_updates, class_name="primary")
            with tgb.part():
                tgb.html("a", href="{wa_url}", target="_blank", class_name="taipy-button", style="background-color: #25D366; color: white; padding: 10px 15px; border-radius: 4px; text-decoration: none; display: inline-block; text-align: center; font-weight: bold; width: 100%;", text="📲 Send WhatsApp")
            
            tgb.html("br")
            tgb.button("🔴 Checkout (Jai Gurudev)", on_action=checkout_guest)

# ==========================================
# 7. INITIALIZATION & RAILWAY CONFIG
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    
    custom_stylekit = {
        "color_primary": "rgb(247, 97, 10)",
        "color_secondary": "#FFDDC1"
    }
    
    Gui(page=main_page).run(
        title="Kaveri Guest Manager", 
        stylekit=custom_stylekit,
        host="0.0.0.0", 
        port=port,
        dark_mode=False
    )
