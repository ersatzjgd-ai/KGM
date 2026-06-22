import os
import urllib.parse
import base64
from datetime import datetime
import tempfile
from fpdf import FPDF
from taipy.gui import Gui, notify, download
import taipy.gui.builder as tgb

# Use the native python supabase client for Taipy
from supabase import create_client, Client

# ==========================================
# 1. INITIALIZATION & DATABASE
# ==========================================
# Fetch credentials from Railway environment variables
SUPABASE_URL = os.environ.get("SUPABASE_URL", "your_supabase_url")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "your_supabase_key")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print("⚠️ Supabase client not initialized. Ensure env variables are set in Railway.")
    supabase = None

today_start = f"{datetime.now().strftime('%Y-%m-%d')}T00:00:00"

# ==========================================
# 2. STATE VARIABLES
# ==========================================
role = "On-Ground Team 🏃"
role_options = ["On-Ground Team 🏃", "Manager 👔"]

# Manager State
manager_logged_in = False
pwd_input = ""
search_incoming = ""
expected_guests = []
filtered_expected = []
mgr_active_guests = []
session_type = "Morning"
guest_names_input = ""

# On-Ground Team State
active_guests = []
selected_lounge_view = "All"
lounge_options = ["All", "Unassigned", "L1", "L2", "L3", "BR", "L5"]
search_active = ""

# ==========================================
# 3. CORE LOGIC / REFRESH FUNCTIONS
# ==========================================
def refresh_data(state):
    if not supabase: return
    
    # Manager: Incoming Guests
    res_inc = supabase.table("guests").select("*").eq("is_active", False).eq("has_left_kaveri", False).gte("created_at", today_start).order("created_at").execute()
    state.expected_guests = res_inc.data
    filter_incoming_guests(state)

    # Manager & Team: Active Guests
    res_act = supabase.table("guests").select("*").eq("is_active", True).eq("jai_gurudev", False).gte("created_at", today_start).order("created_at").execute()
    state.mgr_active_guests = res_act.data
    state.active_guests = res_act.data

def filter_incoming_guests(state):
    search = state.search_incoming.lower()
    if not search:
        state.filtered_expected = state.expected_guests
    else:
        state.filtered_expected = [g for g in state.expected_guests if search in g['guest_name'].lower()]

# ==========================================
# 4. CALLBACK FUNCTIONS
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

def save_new_guests(state):
    if not supabase: return
    if state.guest_names_input.strip():
        names_list = [name.strip() for name in state.guest_names_input.split('\n') if name.strip()]
        insert_data = [{"guest_name": name, "session_type": state.session_type} for name in names_list]
        supabase.table("guests").insert(insert_data).execute()
        notify(state, "success", f"Added {len(names_list)} guests!")
        state.guest_names_input = ""
        refresh_data(state)
    else:
        notify(state, "error", "Please enter at least one guest name.")

def generate_pdf_report(state):
    if not supabase: return
    res = supabase.table("guests").select("*").gte("created_at", today_start).order("created_at").execute()
    guests_data = res.data
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, txt=f"Kaveri GM - Session Report ({datetime.now().strftime('%Y-%m-%d')})", ln=True, align='C')
    pdf.ln(5)
    
    for g in guests_data:
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 8, txt=f"Guest: {g['guest_name']} ({g.get('session_type', 'N/A')})", ln=True)
        pdf.set_font("Arial", '', 10)
        pdf.cell(0, 6, txt=f"Lounge: {g.get('lounge', 'Unassigned')} | LMW: {g.get('lmw_status', 'Not yet')}", ln=True)
        pdf.ln(2)
        
    pdf_file_path = os.path.join(tempfile.gettempdir(), f"Kaveri_Report_{datetime.now().strftime('%Y%m%d')}.pdf")
    pdf.output(pdf_file_path)
    download(state, content=pdf_file_path, name=f"Kaveri_Report_{datetime.now().strftime('%Y%m%d')}.pdf")
    notify(state, "success", "Report downloaded!")

# ==========================================
# 5. GUI LAYOUT
# ==========================================
with tgb.Page() as main_page:
    tgb.text("🏛️ Kaveri GM", class_name="h1")
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
            tgb.input("{search_incoming}", label="🔍 Search Expected Guest...")
            
            # Simplified Data Table Representation for Taipy
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
    # ON-GROUND TEAM VIEW
    # ------------------------------------------
    with tgb.part(render="{role == 'On-Ground Team 🏃'}"):
        tgb.text("🏃 Active Team Dashboard", class_name="h2")
        tgb.selector(value="{selected_lounge_view}", lov="{lounge_options}", dropdown=False)
        tgb.input("{search_active}", label="🔍 Search Active Guest...")
        
        # In a full Taipy build, a customized list iterator (using <|part|loop|>) is used 
        # to render individual complex cards. Here we provide the standard Taipy table view 
        # to ensure stable execution on deployment.
        tgb.table("{active_guests}", filter=True, page_size=15)

# ==========================================
# 6. INITIALIZATION & RAILWAY CONFIG
# ==========================================
if __name__ == "__main__":
    # Fetch the dynamic port provided by Railway, or default to 5000 for local testing
    port = int(os.environ.get("PORT", 5000))
    
    # Establish your application's base theme color
    custom_stylekit = {
        "color_primary": "rgb(247, 97, 10)",
        "color_secondary": "#FFDDC1"
    }
    
    # Run the Taipy Server bound to 0.0.0.0 for external cloud access
    Gui(page=main_page).run(
        title="Kaveri Guest Manager", 
        stylekit=custom_stylekit,
        host="0.0.0.0", 
        port=port,
        dark_mode=False
    )
