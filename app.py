import os               # file system interaction
import numpy as np      # numerical computations and interpolation 
import pandas as pd     # DataFrames creation (tables)
import streamlit as st  # GUI/Interactive web dashboard
import plotly.graph_objects as go #Data visulaization (interactive Charts)
import fastf1   #library For Fetching F1 telemetry data 


class F1Service:
    def __init__(self, cache_dir: str = "cache"): #constructor
        fastf1.Cache.enable_cache(cache_dir) #Speeds up future reload , saves previously fetched data to cache folder

    def get_schedule(self, year: int) -> pd.DataFrame: #returns a dataframe (table) of events for the given year
        return fastf1.get_event_schedule(year) #built-in func

    def load_session(self, year: int, event_name: str, session_name: str): #loads session data from external sources
        session = fastf1.get_session(year, event_name, session_name)#built-in func
        session.load() #reads  session's data (downloads)
        return session  

    def list_drivers(self, session) -> list[str]: #returns the list of participating drivers sorted
        drivers = session.laps["Driver"].dropna().unique().tolist() # drivers= list of Strings
        drivers.sort() #sorts in place
        return drivers #list of drivers (string)

    def fastest_lap_telemetry(self, session, driver_code: str): #Fetches fastest lap of given driver in the given session
        lap = session.laps.pick_drivers(driver_code).pick_fastest() #for given session, go thru laps of the given driver, pick fastest lap
        tel = lap.get_telemetry() # Get Telemetry details of the fastest lap (returns a dataframe)
        cols = [ c
                    for c in ["Distance", "SessionTime", "Speed", "Throttle", "Brake", "nGear", "RPM"] 
                        if c in tel.columns ] # To keep only relevant columns 
        tel = tel[cols].copy() # new dataframe(copy)  
        tel["Driver"] = driver_code # add new column carrying the driver's code name 
        return lap, tel # return lap (series/record), tel (dataframe)

    def compare_fastest(self, session, d1: str, d2: str): #given two drivers, compare their laps' telemetries
        lap1, tel1 = self.fastest_lap_telemetry(session, d1)
        lap2, tel2 = self.fastest_lap_telemetry(session, d2)

        dmin = max(float(tel1["Distance"].min()), float(tel2["Distance"].min())) #lowest start point 
        dmax = min(float(tel1["Distance"].max()), float(tel2["Distance"].max())) #highest end  point
        if dmax <= dmin:
            dist = tel1["Distance"].to_numpy() # convert to a numpy array if there's no overlap
        else:
            dist = np.linspace(dmin, dmax, 1200) #grid for comparison 
        # -- interpolation: to align speeds at the same distance points --
        s1 = np.interp(dist, tel1["Distance"], tel1["Speed"])
        s2 = np.interp(dist, tel2["Distance"], tel2["Speed"])
        comp_df = pd.DataFrame({"Distance": dist, f"{d1}_Speed": s1, f"{d2}_Speed": s2})
        return lap1, lap2, tel1, tel2, comp_df
    
    @staticmethod
    def format_laptime(lap_time): #helper method for reformatting laptimes in mm:ss.sss format
        if pd.isna(lap_time):
            return "N/A" #no laptime found
        total_seconds = lap_time.total_seconds() #days:hrs:min:ss.sss
        minutes = int(total_seconds // 60)
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:06.3f}"  # minutes:seconds.sss
#end of Class F1Service.

# -----------------------------
# Streamlit GUI(dashboard)
# -----------------------------

st.set_page_config(page_title="F1 Telemetry Mini-Dashboard", layout="wide") #page configuartion
st.title("🏎️ F1 Telemetry Mini-Dashboard") #dashboard title

with st.sidebar:
    st.header("Controls") #sidebar header title
    cache_dir = st.text_input("Cache folder", value="cache") #Select cache folder (default=cache)
    min_year, max_year = 2018, 2025 #Seasons available
    year = st.selectbox("Season", options=list(range(max_year, min_year-1, -1)), index=0) #select box of seasons (pick the year)
    session_name = st.selectbox("Session", options=["Qualifying", "Race", "FP1", "FP2", "FP3", "Sprint Race"], index=0) #type of session select box(pick session type)

service = F1Service(cache_dir=cache_dir) #instance of F1Service to access its methods

# Load schedule
try:
    schedule = service.get_schedule(year) #load schedule of the given year (dataframe)
    if "EventName" in schedule.columns:
        gps = schedule["EventName"].tolist() #gps = list of grandprix names
    else:
        possible_cols = [c for c in ["OfficialEventName", "Event"] if c in schedule.columns] #try another way to find names
        gps = schedule[possible_cols[0]].tolist() if possible_cols else []
except Exception as e:
    st.error(f"Couldn't fetch season schedule for {year}: {e}")
    st.stop() #error fetching the data

#  Filter out Pre-Season Testing (no telemetry available)
gps = [gp 
       for gp in gps 
       if "Testing" not in gp] 
# if no info found for that year
if not gps: 
    st.warning("No events found for this season.")
    st.stop()
# pick the grandprix
event_name = st.selectbox("Grand Prix", options=gps, index=0)

# Load button -> load session data
if st.button("Load Session", type="primary"): #button/listener
    with st.spinner("Loading session… (may take ~1-2 minutes)."): #spinning loader icon
        try:
            session = service.load_session(year, event_name, session_name)
            st.session_state["session"] = session #save session in streamlit.session_state
        except Exception as e:
            st.error(f"Failed to load session: {e}")
            st.stop()

session = st.session_state.get("session", None) #retrieve the session, if button not pressed-> return none

if session is not None: #if button Was pressed
    drivers = service.list_drivers(session) # for the selected session, get participating drivers
    if not drivers:
        st.warning("No drivers available.")
        st.stop()

    selected = st.multiselect("Pick TWO drivers to compare", options=drivers, key="drivers") #select drivers to compare telemetry
    if len(selected) != 2:
        st.info("Please select exactly two drivers to show comparisons.")
        st.stop()

    d1, d2 = selected #store selected drivers 
    lap1, lap2, tel1, tel2, comp_df = service.compare_fastest(session, d1, d2) #compare telemetries

    # --- Lap Delta Calculation ---
    try:
        td1 = pd.to_timedelta(lap1["LapTime"]) #driver1 Laptime
        td2 = pd.to_timedelta(lap2["LapTime"]) #driver2 Laptime
        delta_td = td1 - td2 #difference between times -> time delta data type
        delta_seconds = float(delta_td.total_seconds()) #convert to seconds
    except Exception:
        delta_seconds = float(pd.to_timedelta(lap1["LapTime"]).total_seconds() -
                              pd.to_timedelta(lap2["LapTime"]).total_seconds())

    delta_str = f"{delta_seconds:+.3f}s" #format to 3 decimal places

    # KPIs -> display metrics
    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric(label=f"{d1} Fastest Lap", value=service.format_laptime(lap1['LapTime']))
    kpi2.metric(label=f"{d2} Fastest Lap", value=service.format_laptime(lap2['LapTime']))
    kpi3.metric(label=f"Lap Time Delta ({d1} - {d2})", value=delta_str)

    st.markdown("---")

    # Speed overlay -> Plot speed vs. difference (Visualize)
    fig_speed = go.Figure() 
    fig_speed.add_trace(go.Scatter(x=comp_df["Distance"], y=comp_df[f"{d1}_Speed"], mode="lines", name=f"{d1} Speed"))
    fig_speed.add_trace(go.Scatter(x=comp_df["Distance"], y=comp_df[f"{d2}_Speed"], mode="lines", name=f"{d2} Speed"))
    fig_speed.update_layout(title=f"Speed vs Distance — {event_name} {year} ({session_name})",
                            xaxis_title="Distance (m)", yaxis_title="Speed (km/h)", legend_title="Driver") #Layout Configuration
    st.plotly_chart(fig_speed, use_container_width=True) # Display chart

    # Throttle & Brake -> plot  throttle&brake inputs vs distance
    fig_tb = go.Figure()
    #for driver 1
    if "Throttle" in tel1.columns:
        fig_tb.add_trace(go.Scatter(x=tel1["Distance"], y=tel1["Throttle"], mode="lines", name=f"{d1} Throttle"))
    if "Brake" in tel1.columns:
        fig_tb.add_trace(go.Scatter(x=tel1["Distance"],
                                    y=tel1["Brake"]*100 if tel1["Brake"].max() <= 1 else tel1["Brake"],
                                    mode="lines", name=f"{d1} Brake (%)"))
    #for driver 2
    if "Throttle" in tel2.columns:
        fig_tb.add_trace(go.Scatter(x=tel2["Distance"], y=tel2["Throttle"], mode="lines", name=f"{d2} Throttle"))
    if "Brake" in tel2.columns:
        fig_tb.add_trace(go.Scatter(x=tel2["Distance"],
                                    y=tel2["Brake"]*100 if tel2["Brake"].max() <= 1 else tel2["Brake"],
                                    mode="lines", name=f"{d2} Brake (%)"))
    
    fig_tb.update_layout(title="Throttle & Brake vs Distance", xaxis_title="Distance (m)", yaxis_title="Percent (0–100)")
    st.plotly_chart(fig_tb, use_container_width=True) #Display chart

    # Delta vs Distance
    if "SessionTime" in tel1.columns and "SessionTime" in tel2.columns:
        # Convert Timedelta to float seconds
        t1_sec = tel1["SessionTime"].dt.total_seconds()
        t2_sec = tel2["SessionTime"].dt.total_seconds()

        t1 = np.interp(comp_df["Distance"], tel1["Distance"], t1_sec)
        t2 = np.interp(comp_df["Distance"], tel2["Distance"], t2_sec)
        delta_time = t1 - t2

        fig_delta = go.Figure()
        fig_delta.add_trace(go.Scatter(x=comp_df["Distance"], y=delta_time, mode="lines",
                                   name=f"{d1} - {d2} (s)"))
        fig_delta.update_layout(title="Lap Time Delta vs Distance (positive => driver1 slower)",
                            xaxis_title="Distance (m)", yaxis_title="Delta (s)")
        st.plotly_chart(fig_delta, use_container_width=True)

    # Gear plot
    driver_for_gears = st.selectbox("Gear plot driver", options=[d1, d2], index=0) #select a driver to show gear plot
    tel_g = tel1 if driver_for_gears == d1 else tel2
    if "nGear" in tel_g.columns:
        fig_gear = go.Figure()
        fig_gear.add_trace(go.Scatter(x=tel_g["Distance"], y=tel_g["nGear"], mode="lines", name=f"{driver_for_gears} Gear"))
        fig_gear.update_layout(title=f"Gear vs Distance — {driver_for_gears}", xaxis_title="Distance (m)", yaxis_title="Gear")
        st.plotly_chart(fig_gear, use_container_width=True)

    st.caption("Data cached for faster reloads. Using Plotly,Streamlit and Fastf1.")
