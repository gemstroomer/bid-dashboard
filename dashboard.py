import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.express as px
import plotly.graph_objects as go

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Crew Bid Analysis",
    page_icon="✈️",
    layout="wide"
)

st.title("✈️ Crew Bid Analysis Dashboard")
st.caption("Upload the raw bid detail reports and adjust the period dates to run the full analysis.")

# ─────────────────────────────────────────────
# SIDEBAR — FILE UPLOADS & SETTINGS
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")

    st.subheader("1. Upload files")
    f_ab       = st.file_uploader("Airbus bid report (.xlsx)", type="xlsx", key="ab")
    f_bo       = st.file_uploader("Boeing bid report (.xlsx)", type="xlsx", key="bo")
    f_functie  = st.file_uploader("Codes + Functie (.xlsx)",   type="xlsx", key="fn")
    f_base     = st.file_uploader("Base (.xlsx)",              type="xlsx", key="bs")

    st.subheader("2. Period (for days-off explode)")
    period_start = st.date_input("Start", value=pd.Timestamp("2026-05-18"))
    period_end   = st.date_input("End",   value=pd.Timestamp("2026-06-21"))

    st.subheader("3. Inactive / sick crew")
    sick_input = st.text_area(
        "Crew codes to exclude (comma-separated)",
        value="AJS, ARV, GOP, HAW, IHN, IVA, IVG, JJT, OGC, OOC, WOK, EUQ, PRO, NEL"
    )
    sick_crew = [c.strip() for c in sick_input.split(",") if c.strip()]

    run = st.button("▶ Run analysis", type="primary", use_container_width=True)

if not run:
    st.info("Upload the files in the sidebar and click **Run analysis** to start.")
    st.stop()

if not f_ab or not f_bo:
    st.error("Please upload at least the Airbus and Boeing bid reports.")
    st.stop()

# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────
@st.cache_data(show_spinner="Loading data…")
def load_data(f_ab, f_bo, f_functie, f_base):
    df_ab = pd.read_excel(f_ab, skiprows=range(0, 8))
    df_bo = pd.read_excel(f_bo, skiprows=range(0, 8))
    df_ab["ac_type"] = "AB"
    df_bo["ac_type"] = "BO"
    df = pd.concat([df_ab, df_bo], ignore_index=True)

    if f_functie:
        df_functie = pd.read_excel(f_functie)
        df_functie["Functie"] = df_functie["Code"].str.extract(r"\((.*?)\)")
        df_functie["Code"]    = df_functie["Code"].str.extract(r"^([A-Z]+)")
        df = df_functie.merge(df, on="Code", how="left")
    else:
        df["Functie"] = "Unknown"

    if f_base:
        base = pd.read_excel(f_base)
        df = df.merge(base[["Code", "Base"]], on="Code", how="left")
    else:
        df["Base"] = "Unknown"

    return df

df_raw = load_data(f_ab, f_bo, f_functie, f_base)

# ─────────────────────────────────────────────
# PROCESSING
# ─────────────────────────────────────────────
@st.cache_data(show_spinner="Processing…")
def process(df_raw):
    df = df_raw.copy()

    # status_count
    df["status_count"] = df["Status"].str.extract(r"\((\d+)\)")
    df.loc[df["Status"] == "Granted",     "status_count"] = df.loc[df["Status"] == "Granted",     "Maxroster Times Granted"]
    df.loc[df["Status"] == "Not Granted", "status_count"] = 0
    df.loc[
        (df["Description"].str.contains("Avoid Layover", na=False)) &
        (df["Status"].str.contains("Granted", na=False)),
        "status_count"
    ] = df["Maxroster Times Granted"]
    df["status_count"] = pd.to_numeric(df["status_count"], errors="coerce")
    df["Maxroster Times Granted"] = pd.to_numeric(df["Maxroster Times Granted"], errors="coerce")

    # score from points: row
    df["score"] = np.where(
        df["Description"].str.startswith("points:", na=False),
        df["Bid ratio"].str.split("(").str[0].str.strip().apply(pd.to_numeric, errors="coerce"),
        np.nan
    )

    # clean
    df_clean = df.drop(columns=["Nr", "Points", "Limit", "Bid ratio"], errors="ignore")
    df_clean = df_clean[df_clean["Status"].notna()]

    # categories
    def categorize_request(desc):
        desc = str(desc)
        if "Specific Flight" in desc:   return "Specific Flight"
        if "Layover" in desc or "Avoid Layover" in desc: return "Layover"
        if "Check In" in desc or "Check Out" in desc:    return "Time Preference"
        if "Day(s) of Week" in desc or "String of Days Off" in desc \
           or "String of Dates Off" in desc or "Date(s) Off" in desc: return "Days Off"
        if "Consecutive Working Days" in desc or "Consecutive Days Off" in desc: return "Work Pattern"
        return "Other"

    df_clean["request_category"] = df_clean["Description"].apply(categorize_request)

    # relative allocation
    df_clean["relative_allocation"] = (
        df_clean["status_count"] / df_clean["Maxroster Times Granted"]
    ).replace([np.inf, -np.inf], np.nan)

    # Maxroster Points numeric
    df_clean["Maxroster Points"] = pd.to_numeric(df_clean["Maxroster Points"], errors="coerce")

    return df_clean

df_clean = process(df_raw)
PERIOD_START = pd.Timestamp(period_start)
PERIOD_END   = pd.Timestamp(period_end)

# ─────────────────────────────────────────────
# SUMMARY METRICS
# ─────────────────────────────────────────────
st.header("📊 Summary")
tot   = len(df_clean)
ab_n  = (df_clean["ac_type"] == "AB").sum()
bo_n  = (df_clean["ac_type"] == "BO").sum()
grant = (df_clean["Status"].str.contains("Granted", na=False) &
         ~df_clean["Status"].str.contains("Not Granted", na=False)).sum()
gr_pct = round(100 * grant / tot, 1) if tot else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total bids",      f"{tot:,}")
c2.metric("Airbus bids",     f"{ab_n:,}")
c3.metric("Boeing bids",     f"{bo_n:,}")
c4.metric("Granted",         f"{grant:,}")
c5.metric("Grant rate",      f"{gr_pct}%")

st.divider()

# ─────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📁 Request categories",
    "📈 Relative allocation",
    "⏰ Time preferences",
    "📅 Days off",
    "🎯 Bid scores"
])

# ══════════════════════════════════════════════
# TAB 1 — REQUEST CATEGORIES
# ══════════════════════════════════════════════
with tab1:
    st.subheader("Distribution of request categories")

    col1, col2 = st.columns(2)

    with col1:
        rc = df_clean["request_category"].value_counts(normalize=True).reset_index()
        rc.columns = ["request_category", "percentage"]
        rc["percentage"] *= 100
        fig = px.bar(rc, x="request_category", y="percentage", text="percentage",
                     color_discrete_sequence=["#02CC78"],
                     title="Overall distribution (%)")
        fig.update_traces(texttemplate='%{text:.1f}%', textposition="outside", marker_color="#02CC78")
        fig.update_layout(template="simple_white", yaxis_range=[0, 55],
                          xaxis_title="Category", yaxis_title="% of bids")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        if "Functie" in df_clean.columns and df_clean["Functie"].notna().any():
            grouped = (df_clean.groupby("Functie")["request_category"]
                       .value_counts(normalize=True)
                       .rename("percentage").reset_index())
            grouped["percentage"] *= 100
            fig2 = px.bar(grouped, x="request_category", y="percentage",
                          color="Functie", barmode="group",
                          color_discrete_sequence=["#110C8A", "#02CC78"],
                          text="percentage",
                          title="By job position (%)")
            fig2.update_traces(texttemplate='%{text:.1f}%', textposition="outside")
            fig2.update_layout(template="simple_white", yaxis_range=[0, 60],
                               legend_title_text="Job Position",
                               xaxis_title="Category", yaxis_title="% within position")
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Upload the Codes+Functie file to see job position breakdown.")

    # Priority allocation
    st.subheader("Average priority allocation of points per category")
    df_pts = df_clean.copy()
    df_pts["relative_points"] = (
        df_pts["Maxroster Points"] /
        df_pts.groupby("Code")["Maxroster Points"].transform("sum")
    )
    cat_prio = (df_pts.groupby(["Code","request_category"])["relative_points"]
                .sum().reset_index()
                .groupby("request_category")["relative_points"]
                .mean().sort_values(ascending=False).reset_index())
    cat_prio["pct"] = cat_prio["relative_points"] * 100
    fig3 = px.bar(cat_prio, x="request_category", y="pct", text="pct",
                  color_discrete_sequence=["#02CC78"],
                  title="Average priority allocation of points per category (%)")
    fig3.update_traces(texttemplate='%{text:.1f}%', textposition="outside", marker_color="#02CC78")
    fig3.update_layout(template="simple_white", yaxis_range=[0, 80],
                       xaxis_title="Category", yaxis_title="%")
    st.plotly_chart(fig3, use_container_width=True)

# ══════════════════════════════════════════════
# TAB 2 — RELATIVE ALLOCATION
# ══════════════════════════════════════════════
with tab2:
    st.subheader("Mean relative allocation per request category")

    col1, col2 = st.columns(2)

    with col1:
        # Overall
        ov = (df_clean.groupby("request_category")["relative_allocation"]
              .mean().reset_index())
        ov["pct"] = ov["relative_allocation"] * 100
        fig = px.bar(ov, x="request_category", y="pct", text="pct",
                     title="Overall (%)")
        fig.update_traces(texttemplate='%{text:.1f}%', textposition="outside", marker_color="#110C8A")
        fig.update_layout(template="simple_white", yaxis_range=[0, 110],
                          xaxis_title="Category", yaxis_title="Mean allocation (%)")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # By fleet
        fl = (df_clean.groupby(["ac_type","request_category"])["relative_allocation"]
              .mean().reset_index())
        fl["pct"] = fl["relative_allocation"] * 100
        fig2 = px.bar(fl, x="request_category", y="pct", color="ac_type",
                      barmode="group", text="pct",
                      color_discrete_sequence=["#110C8A","#02CC78"],
                      title="By fleet (%)")
        fig2.update_traces(texttemplate='%{text:.1f}%', textposition="outside")
        fig2.update_layout(template="simple_white", yaxis_range=[0, 110],
                           legend_title_text="Fleet",
                           xaxis_title="Category", yaxis_title="Mean allocation (%)")
        st.plotly_chart(fig2, use_container_width=True)

    # By job position
    if "Functie" in df_clean.columns and df_clean["Functie"].notna().any():
        fp = (df_clean.groupby(["request_category","Functie"])["relative_allocation"]
              .mean().reset_index())
        fp["pct"] = fp["relative_allocation"] * 100
        fig3 = px.bar(fp, x="request_category", y="pct", color="Functie",
                      barmode="group", text="pct",
                      color_discrete_sequence=["#110C8A","#02CC78"],
                      title="By job position (%)")
        fig3.update_traces(texttemplate='%{text:.1f}%', textposition="outside")
        fig3.update_layout(template="simple_white", yaxis_range=[0, 110],
                           legend_title_text="Job Position",
                           xaxis_title="Category", yaxis_title="Mean allocation (%)",
                           width=1000)
        st.plotly_chart(fig3, use_container_width=True)

# ══════════════════════════════════════════════
# TAB 3 — TIME PREFERENCES
# ══════════════════════════════════════════════
with tab3:
    st.subheader("Time preference analysis")

    time_pref = df_clean[df_clean["request_category"] == "Time Preference"].copy()

    def classify_bid_type(desc):
        desc = str(desc)
        if "Check In Before"    in desc: return "Check In Before"
        if "Check In After"     in desc: return "Check In After"
        if "Check Out Before"   in desc: return "Check Out Before"
        if "Check Out After"    in desc: return "Check Out After"
        if "Check Out between"  in desc: return "Check Out Between"
        return "Other"

    time_pref["bid_type"] = time_pref["Description"].apply(classify_bid_type)

    col1, col2 = st.columns(2)

    with col1:
        bt_counts = time_pref["bid_type"].value_counts().reset_index()
        bt_counts.columns = ["bid_type", "count"]
        fig = px.bar(bt_counts, x="bid_type", y="count", text="count",
                     color_discrete_sequence=["#02CC78"],
                     title="Distribution of bid types")
        fig.update_traces(textposition="outside", marker_color="#02CC78")
        fig.update_layout(template="simple_white",
                          xaxis_title="Bid type", yaxis_title="Count")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # Grant status per fleet
        def norm_status(s):
            s = str(s or "")
            if "Not Granted" in s: return "Not Granted"
            if "Granted"     in s: return "Granted"
            return "Max not possible"
        time_pref["status_norm"] = time_pref["Status"].apply(norm_status)
        sts = ["Granted","Not Granted","Max not possible"]
        grant_df = (time_pref.groupby(["ac_type","status_norm"])
                    .size().reset_index(name="count"))
        fig2 = px.bar(grant_df, x="ac_type", y="count", color="status_norm",
                      barmode="stack", text="count",
                      color_discrete_sequence=["#5DCAA5","#F0997B","#85B7EB"],
                      title="Grant status by fleet")
        fig2.update_traces(textposition="inside")
        fig2.update_layout(template="simple_white",
                           legend_title_text="Status",
                           xaxis_title="Fleet", yaxis_title="Count")
        st.plotly_chart(fig2, use_container_width=True)

    # CI/CO hour distribution
    st.subheader("Check-in / check-out time popularity")

    co_between = time_pref[time_pref["bid_type"] == "Check Out Between"].copy()

    def extract_times(text):
        times = re.findall(r'(\d{2}):(\d{2})', str(text))
        if len(times) == 2:
            return int(times[0][0]), int(times[1][0])
        return None, None

    if not co_between.empty:
        co_between["start"], co_between["end"] = zip(
            *co_between["Description"].apply(extract_times)
        )

    def extract_hour(desc):
        m = re.search(r'(\d{2}):\d{2}', str(desc))
        return int(m.group(1)) if m else None

    df_tp = time_pref.copy()
    df_tp["hour"] = df_tp["Description"].apply(extract_hour)

    df_main = df_tp[df_tp["bid_type"].isin(["Check In After","Check In Before","Check Out Before"])].copy()

    if not co_between.empty and "end" in co_between.columns:
        co_clean = co_between.copy()
        co_clean["hour"] = co_clean["end"]
        co_clean["bid_type"] = "Check Out Before"
        df_combined = pd.concat([df_main, co_clean], ignore_index=True)
    else:
        df_combined = df_main.copy()

    summary = (df_combined.groupby(["hour","bid_type"]).size().reset_index(name="count"))
    summary["adjusted_hour"] = summary["hour"].apply(lambda x: x - 24 if x > 23 else x)
    summary["adjusted_hour"] = summary["adjusted_hour"].apply(lambda x: x + 24 if x < 5 else x)
    summary = summary.sort_values("adjusted_hour")

    bt_total = df_combined["bid_type"].value_counts()

    fig3 = px.bar(summary, x="adjusted_hour", y="count", color="bid_type",
                  barmode="group", text="count",
                  category_orders={"bid_type":["Check In After","Check In Before","Check Out Before"]},
                  color_discrete_map={
                      "Check In After":  "#02CC78",
                      "Check In Before": "#E30076",
                      "Check Out Before":"#110C8A"
                  },
                  title="Popularity of check-in and check-out time preferences")
    fig3.update_traces(textposition="outside")
    tickvals = sorted(summary["adjusted_hour"].dropna().unique())
    ticktext = [str(int(h - 24 if h > 23 else h)) for h in tickvals]
    fig3.update_xaxes(tickmode="array", tickvals=tickvals, ticktext=ticktext)
    fig3.update_layout(template="simple_white",
                       xaxis_title="Hour", yaxis_title="Number of bids",
                       legend_title_text="Bid type", title_x=0.5)
    fig3.for_each_trace(lambda t: t.update(
        name=f"{t.name} ({bt_total.get(t.name, 0)})"
    ))
    st.plotly_chart(fig3, use_container_width=True)

# ══════════════════════════════════════════════
# TAB 4 — DAYS OFF
# ══════════════════════════════════════════════
with tab4:
    st.subheader("Days off analysis")

    days_off = df_clean[df_clean["request_category"] == "Days Off"].copy()

    # ── Explode helpers ──────────────────────────────────────
    DOWS    = ["MON","TUE","WED","THU","FRI","SAT","SUN"]
    DOW_MAP = {d: i for i, d in enumerate(DOWS)}

    def clamp(dates):
        return [d for d in dates if d and pd.notna(d)
                and PERIOD_START <= pd.Timestamp(d).normalize() <= PERIOD_END]

    def dr_incl(a, b):
        a, b = pd.Timestamp(a).normalize(), pd.Timestamp(b).normalize()
        return list(pd.date_range(min(a,b), max(a,b), freq="D"))

    def parse_dates_field(v):
        if v is None or pd.isna(v): return []
        s = str(v).strip()
        if s in {"-",""}: return []
        m = re.fullmatch(r"(\d{1,2})-(\d{1,2})([A-Za-z]{3}\d{4})", s)
        if m:
            st2 = pd.to_datetime(f"{m.group(1)}{m.group(3)}", format="%d%b%Y", errors="coerce")
            en2 = pd.to_datetime(f"{m.group(2)}{m.group(3)}", format="%d%b%Y", errors="coerce")
            if pd.notna(st2) and pd.notna(en2):
                return list(pd.date_range(st2.normalize(), en2.normalize(), freq="D"))
            return []
        d = pd.to_datetime(s, format="%d%b%Y", errors="coerce")
        return [d.normalize()] if pd.notna(d) else []

    def wd_in_period(wd_idx):
        return [d for d in pd.date_range(PERIOD_START, PERIOD_END, freq="D")
                if d.weekday() == wd_idx]

    def cat_mech(t):
        t = (t or "").upper()
        if "STRING OF DATES OFF" in t: return "STRING_DATES_OFF"
        if "STRING OF DAYS OFF"  in t: return "STRING_DAYS_OFF"
        if "DAY(S) OF WEEK OFF"  in t: return "DOW_OFF"
        if "DATE(S) OFF"         in t: return "DATES_OFF"
        return "OTHER"

    def extract_extra(t):
        m = re.search(r"\bextra\s+(\d+)\s+day\(s\)", t or "", re.I)
        if m: return int(m.group(1))
        m = re.search(r"\b(forward|backward)\s+(\d+)\s+extra\b", t or "", re.I)
        return int(m.group(2)) if m else None

    def extract_wd(t):
        t = (t or "").upper()
        m = re.search(r"\bON\s+(MON|TUE|WED|THU|FRI|SAT|SUN)\b", t)
        if m: return m.group(1)
        m = re.search(r"\bFROM\s+(MON|TUE|WED|THU|FRI|SAT|SUN)\b", t)
        return m.group(1) if m else None

    def wd_dates(codes):
        idxs = {DOW_MAP[c] for c in codes if c in DOW_MAP}
        return [d for d in pd.date_range(PERIOD_START, PERIOD_END, freq="D")
                if d.weekday() in idxs]

    @st.cache_data(show_spinner="Exploding days off…")
    def explode_days_off(days_off_df):
        rows = []
        for bid_id, row in days_off_df.iterrows():
            pilot   = str(row.get("Code","")).strip()
            text    = str(row.get("Description",""))
            dr      = row.get("Dates")
            ac      = row.get("ac_type","")
            mech    = cat_mech(text)
            out     = []

            if mech == "DATES_OFF":
                out = clamp(parse_dates_field(dr))
            elif mech == "STRING_DATES_OFF":
                anc = parse_dates_field(dr)
                anc = anc[0] if anc else None
                ext = extract_extra(text)
                fwd = "BACKWARD" not in text.upper()
                if anc and ext is not None:
                    tot = ext + 1
                    out = clamp(dr_incl(anc - pd.Timedelta(days=tot-1), anc)
                                if not fwd else dr_incl(anc, anc + pd.Timedelta(days=tot-1)))
            elif mech == "DOW_OFF":
                wd = extract_wd(text)
                if wd and wd in DOW_MAP:
                    out = wd_in_period(DOW_MAP[wd])
            elif mech == "STRING_DAYS_OFF":
                wd  = extract_wd(text)
                ext = extract_extra(text)
                fwd = "BACKWARD" not in text.upper()
                if wd and wd in DOW_MAP and ext is not None:
                    tot = ext + 1
                    gen = []
                    for a in wd_in_period(DOW_MAP[wd]):
                        gen.extend(dr_incl(a - pd.Timedelta(days=tot-1), a)
                                   if not fwd else dr_incl(a, a + pd.Timedelta(days=tot-1)))
                    out = clamp(gen)

            for d in sorted(set(out)):
                rows.append({"pilot": pilot, "bid_id": bid_id, "mechanism": mech,
                             "date": pd.Timestamp(d).normalize(),
                             "ac_type": ac})
        ex = pd.DataFrame(rows)
        if not ex.empty:
            ex = ex.drop_duplicates(["pilot","bid_id","mechanism","date","ac_type"])
        return ex

    with st.spinner("Running days-off analysis…"):
        exploded = explode_days_off(days_off)

    if exploded.empty:
        st.warning("No days-off data found for this period.")
    else:
        DAY_EN = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

        counts = (exploded["date"].apply(lambda d: d.weekday())
                  .value_counts().reindex(range(7), fill_value=0))

        col1, col2 = st.columns(2)

        with col1:
            fig = go.Figure(go.Bar(
                x=DAY_EN, y=counts.values,
                marker_color="#02CC78",
                text=counts.values, textposition="outside"
            ))
            fig.update_layout(
                title=f"Day-off requests per weekday (total = {counts.sum()})",
                xaxis_title="Weekday", yaxis_title="Requests",
                plot_bgcolor="#eaf0fb", paper_bgcolor="#eaf0fb",
                yaxis=dict(range=[0, counts.max() * 1.2])
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            wknd = int(counts[[4,5,6]].sum())
            wkdy = int(counts[[0,1,2,3]].sum())
            fig2 = px.pie(
                names=["Weekend (Fri/Sat/Sun)","Weekday (Mon–Thu)"],
                values=[wknd, wkdy],
                title="Weekend vs weekday day-off requests",
                color_discrete_sequence=["#02CC78","#110C8A"]
            )
            fig2.update_traces(textinfo="percent", textposition="outside", textfont_size=14)
            fig2.update_layout(title_x=0.5)
            st.plotly_chart(fig2, use_container_width=True)

        # Overlap & redundant
        st.subheader("Overlap and redundant bids")

        per_day = (exploded.groupby(["pilot","date","ac_type"])
                   .agg(bids=("bid_id","nunique"), mechanisms=("mechanism","nunique"))
                   .reset_index())

        per_day_overlap = per_day[per_day["bids"] >= 2].copy()
        per_day_overlap["weekday"] = per_day_overlap["date"].dt.day_name()
        per_day_overlap["extra_bids"] = per_day_overlap["bids"] - 1

        overlap_wd   = per_day_overlap.groupby("weekday").size().reindex(DAY_EN, fill_value=0)
        redundant_wd = per_day_overlap.groupby("weekday")["extra_bids"].sum().reindex(DAY_EN, fill_value=0)

        per_day_all = per_day.copy()
        per_day_all["weekday"] = per_day_all["date"].dt.day_name()
        total_bids_wd = per_day_all.groupby("weekday")["bids"].sum().reindex(DAY_EN, fill_value=0)
        pct = (redundant_wd / total_bids_wd * 100).round(1).fillna(0)

        ov_df = pd.DataFrame({
            "weekday": DAY_EN,
            "overlap": overlap_wd.values,
            "redundant": redundant_wd.values,
            "pct": pct.values
        })

        fig3 = go.Figure()
        fig3.add_bar(x=ov_df["weekday"], y=ov_df["overlap"],
                     name="Overlap (≥2 bids)", marker_color="#1F2A8A",
                     text=ov_df["overlap"], textposition="outside")
        fig3.add_bar(x=ov_df["weekday"], y=ov_df["redundant"],
                     name="Redundant bids", marker_color="#02CC78",
                     text=ov_df["redundant"], textposition="outside")
        fig3.add_trace(go.Scatter(
            x=ov_df["weekday"], y=ov_df["pct"],
            name="Redundant (%)", mode="lines+markers+text",
            line=dict(color="#E30076", width=3),
            marker=dict(size=8, color="#E30076"),
            text=[f"{p:.1f}%" for p in ov_df["pct"]],
            textposition="top center", yaxis="y2"
        ))
        fig3.update_layout(
            title="Overlapping and redundant bids per weekday",
            yaxis=dict(title="Number of bids",
                       range=[0, ov_df[["overlap","redundant"]].max().max() * 1.3]),
            yaxis2=dict(title="% redundant", overlaying="y", side="right",
                        range=[0, pct.max() * 1.5]),
            barmode="group", plot_bgcolor="#eaf0fb", paper_bgcolor="#eaf0fb",
            bargap=0.2
        )
        st.plotly_chart(fig3, use_container_width=True)

# ══════════════════════════════════════════════
# TAB 5 — BID SCORES
# ══════════════════════════════════════════════
with tab5:
    st.subheader("Bid scores")

    df_scores = df_clean[df_clean["Description"].str.startswith("points:", na=False)][
        ["Code","ac_type","score","Functie"]].copy()
    df_scores = df_scores[df_scores["score"].notna()]

    met    = df_scores.groupby("ac_type")["score"].mean().round(1)
    zonder = df_scores[~df_scores["Code"].isin(sick_crew)].groupby("ac_type")["score"].mean().round(1)
    diff   = (zonder - met).round(1)

    st.markdown("**Effect of excluding inactive/sick crew on mean bid score:**")
    score_df = pd.DataFrame({
        "Fleet":           met.index,
        "With sick crew":  met.values,
        "Without sick crew": zonder.values,
        "Difference":      diff.values
    })
    st.dataframe(score_df, use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)

    with col1:
        fig = px.histogram(df_scores, x="score", color="ac_type",
                           barmode="overlay", nbins=20,
                           color_discrete_sequence=["#110C8A","#02CC78"],
                           title="Bid score distribution by fleet")
        fig.update_layout(template="simple_white",
                          xaxis_title="Score", yaxis_title="Count",
                          legend_title_text="Fleet")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        if "Functie" in df_scores.columns and df_scores["Functie"].notna().any():
            fig2 = px.box(df_scores, x="Functie", y="score", color="Functie",
                          color_discrete_sequence=["#110C8A","#02CC78"],
                          title="Bid score distribution by job position")
            fig2.update_layout(template="simple_white",
                               xaxis_title="Job position", yaxis_title="Score",
                               legend_title_text="Position")
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Upload Codes+Functie to see job position breakdown.")
