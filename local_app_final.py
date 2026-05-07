import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="SSU Campus Energy Dashboard", layout="wide", initial_sidebar_state="expanded")

# Absolute path — pipeline writes here, app reads here regardless of working directory
WEEKLY_CSV = "weekly_energy.csv"

# ── Load data ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)  # re-read from disk every 5 minutes to pick up pipeline updates
def load_data():
    if not os.path.exists(WEEKLY_CSV):
        st.error(f"weekly_energy.csv not found at {WEEKLY_CSV}. Run the pipeline first.")
        st.stop()
    df = pd.read_csv(WEEKLY_CSV)
    df = df[df["kWh"] > 1]
    return df

df_all = load_data()
all_weeks = sorted(df_all["week"].unique())

# ── Sidebar ────────────────────────────────────────────────────────────────
st.sidebar.title("Controls")
role = st.sidebar.radio("User Role", ["Student (Gamified)", "Admin (Basic)"])

selected_weeks = st.sidebar.multiselect(
    "Filter Weeks",
    all_weeks,
    default=all_weeks[-2:] if len(all_weeks) >= 2 else all_weeks
)

energy_rate = 0.15

if not selected_weeks:
    st.warning("Please select at least one week.")
    st.stop()

df = df_all[df_all["week"].isin(selected_weeks)]
if df.empty:
    st.warning("No data for selected weeks. Check CSVs.")
    st.stop()

# Sort weeks so latest = last
sorted_selected = sorted(selected_weeks)
latest_week = sorted_selected[-1]
previous_week = sorted_selected[-2] if len(sorted_selected) >= 2 else None

# ── Header metrics ─────────────────────────────────────────────────────────
st.title("SSU Campus Energy Dashboard")
st.subheader("Weekly Building Energy Usage")

campus_current = df[df["week"] == latest_week]["kWh"].sum()
scale = 'MWh' if campus_current > 1e3 else 'kWh'
campus_current_disp = campus_current / 1e3 if scale == 'MWh' else campus_current
campus_current_cost = campus_current * energy_rate
campus_normalized = df[df["week"] == latest_week]["normalized_kWh"].sum()
campus_normalized_disp = campus_normalized / 1e3 if scale == 'MWh' else campus_normalized

if previous_week:
    campus_previous = df[df["week"] == previous_week]["kWh"].sum()
    percent_change = ((campus_current - campus_previous) / campus_previous) * 100 if campus_previous > 0 else 0
    cost_saved = (campus_previous * energy_rate) - campus_current_cost
else:
    percent_change, cost_saved = 0, 0

col1, col2, col3 = st.columns(3)
col1.metric(f"Campus Energy ({scale})", f"{campus_current_disp:,.2f}", f"{percent_change:.1f}% Change")
col2.metric("Campus Cost ($)", f"{campus_current_cost:,.2f}", f"{cost_saved:,.2f} Saved")
col3.metric(f"Normalized ({scale})", f"{campus_normalized_disp:,.2f}")

# ── Building selector ──────────────────────────────────────────────────────
buildings = sorted(df["building"].unique())
selected_building = st.selectbox("Select Building", buildings)

building_df = df[df["building"] == selected_building]
building_current = building_df[building_df["week"] == latest_week]["kWh"].sum()
building_current_disp = building_current / 1e3 if scale == 'MWh' else building_current
building_current_cost = building_current * energy_rate

if previous_week:
    building_previous = building_df[building_df["week"] == previous_week]["kWh"].sum()
    building_change = ((building_current - building_previous) / building_previous) * 100 if building_previous > 0 else 0
    building_saved = (building_previous * energy_rate) - building_current_cost
else:
    building_change, building_saved = 0, 0

st.subheader(f"{selected_building} Details")
col4, col5 = st.columns(2)
col4.metric(f"Energy ({scale})", f"{building_current_disp:,.2f}", f"{building_change:.1f}% Change")
col5.metric("Cost ($)", f"{building_current_cost:,.2f}", f"{building_saved:,.2f} Saved")

# ── Trend chart ────────────────────────────────────────────────────────────
st.subheader("Weekly Trend")
building_weekly = building_df.groupby("week")["kWh"].sum().reset_index()
if len(building_weekly) > 1:
    fig_trend = px.line(building_weekly, x="week", y="kWh", title="Energy Trend", markers=True)
else:
    fig_trend = px.bar(building_weekly, x="week", y="kWh", title="Energy (Single Week)")
fig_trend.update_layout(height=300)
st.plotly_chart(fig_trend, use_container_width=True)

# ── Building comparison ────────────────────────────────────────────────────
st.subheader("Building Comparison (Latest Week)")
latest_df = df[df["week"] == latest_week].sort_values("kWh", ascending=False).copy()
latest_df["cost"] = latest_df["kWh"] * energy_rate
fig_compare = px.bar(latest_df, x="kWh", y="building", orientation="h", text="kWh",
                     hover_data=["cost"], title="Compare Energy & Costs")
fig_compare.update_layout(height=400)
st.plotly_chart(fig_compare, use_container_width=True)

# ── Gamification ───────────────────────────────────────────────────────────
if role == "Student (Gamified)":
    st.subheader("🏆 Building Energy Leaderboard")

    if previous_week:
        # Get kWh for latest and previous week per building
        prev_df = df[df["week"] == previous_week][["building", "kWh"]].rename(columns={"kWh": "kWh_prev"})
        curr_df = df[df["week"] == latest_week][["building", "kWh"]].rename(columns={"kWh": "kWh_curr"})
        compare_df = pd.merge(curr_df, prev_df, on="building", how="left").fillna(0)

        # Savings % and eco-points
        compare_df["savings_percent"] = compare_df.apply(
            lambda r: ((r["kWh_prev"] - r["kWh_curr"]) / r["kWh_prev"]) * 100
            if r["kWh_prev"] > 0 else 0,
            axis=1
        )
        compare_df["eco_points"] = compare_df["savings_percent"].clip(lower=0) * 100

        # Streak: count consecutive weeks of positive savings across ALL selected weeks
        # Build a per-building per-week table from all selected weeks (sorted)
        all_selected_df = df_all[df_all["week"].isin(sorted_selected)].copy()
        pivot = all_selected_df.pivot_table(index="week", columns="building", values="kWh", aggfunc="sum").fillna(0)
        pivot = pivot.sort_index()

        streak_data = {}
        for building in pivot.columns:
            series = pivot[building].values
            streak = 0
            # Walk backward from latest week
            for i in range(len(series) - 1, 0, -1):
                if series[i] < series[i - 1]:  # improvement
                    streak += 1
                else:
                    break
            streak_data[building] = streak

        compare_df["streak"] = compare_df["building"].map(streak_data).fillna(0).astype(int)
        leaderboard = compare_df.sort_values("eco_points", ascending=False).reset_index(drop=True)

        st.table(
            leaderboard[["building", "eco_points", "streak"]]
            .style.format({"eco_points": "{:.0f}", "streak": "{:.0f} Weeks 🔥"})
        )

        if not leaderboard.empty:
            top_building = leaderboard.iloc[0]["building"]
            top_points = leaderboard.iloc[0]["eco_points"]
            top_streak_row = leaderboard.sort_values("streak", ascending=False).iloc[0]
            st.write(f"🥇 Top Eco-Building: **{top_building}** (Earned {top_points:.0f} Points)")
            st.write(f"🔥 Longest Streak: **{top_streak_row['building']}** ({top_streak_row['streak']:.0f} Weeks)")

        goal_reduction = 5
        if percent_change < -goal_reduction:
            st.success(f"🎉 Campus Won! Reduced by {-percent_change:.1f}% (Goal: {goal_reduction}%)")
        else:
            st.warning(f"Progress: {percent_change:.1f}% change vs previous week (Goal: -{goal_reduction}%)")
    else:
        st.info("Select 2+ weeks to see gamification stats and comparisons.")
