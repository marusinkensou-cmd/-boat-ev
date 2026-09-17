from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from today_discovery_v12 import discover_today, VENUES
from racelist_live_v12 import seed_venue_races,refresh_racelist
from beforeinfo_live_v13 import refresh_beforeinfo_v13
from nationwide_board_v09 import build_board
from live_quality_v13 import mark,status
from virtual_ledger_v14 import stats
from official_live_v10 import refresh_one as refresh_odds
from ev_engine_v08 import evaluate_race
from race_interactions_v01 import build_interaction_features
from race_context_features_v01 import build_race_context_features
from venue_environment_v01 import build_environment_features
from race_trace_v01 import save_snapshot, freeze_predeadline, cumulative_actual_stats

JST=ZoneInfo("Asia/Tokyo")

def mins_to_deadline(now,deadline):
    hh,mm=map(int,deadline[:5].split(":"))
    dl=now.replace(hour=hh,minute=mm,second=0,microsecond=0)
    return (dl-now).total_seconds()/60

def _race_from_board(board,rid):
    return next((r for r in board if r.get("race_id")==rid),None)

def _boats_from_race(race):
    boats=[]
    ex_courses=race.get("exhibition_courses") or {}
    for b in race.get("boats") or []:
        boat=b.get("boat") or b.get("boat_no")
        if boat is None: continue
        ex=ex_courses.get(str(boat),ex_courses.get(boat,{})) or {}
        boats.append({
            "boat":boat,"racer_id":b.get("racer_id"),
            "course":ex.get("exhibition_course") or b.get("course") or boat,
            "actual_course":ex.get("exhibition_course") or b.get("course") or boat,
            "avg_st":b.get("avg_st"),
            "exhibition_st":ex.get("exhibition_st") or b.get("exhibition_st"),
            "exhibition_time":ex.get("exhibition_time") or b.get("exhibition_time"),
            "motor_rate":b.get("motor_rate") or b.get("motor_2ren"),
            "local_win_rate":b.get("local_win_rate"),"national_win_rate":b.get("national_win_rate"),
            "class_rank":b.get("class_rank") or b.get("class"),"is_dash":bool(ex.get("is_dash",b.get("is_dash",False))),
            "weight":b.get("weight"),"adjust_weight":b.get("adjust_weight"),"tilt":b.get("tilt"),
            "propeller_changed":b.get("propeller_changed",False),"parts_changed":b.get("parts_changed") or [],
            "previous_race_no":b.get("previous_race_no"),"previous_course":b.get("previous_course"),
            "previous_st":b.get("previous_st"),"previous_finish":b.get("previous_finish"),
        })
    return boats

def _full_trace_from_board(board,rid,jcd):
    race=_race_from_board(board,rid)
    if not race: return {"status":"unavailable","race_id":rid,"reason":"race_not_on_board"}
    boats=_boats_from_race(race)
    weather=race.get("weather") or {}
    return {
        "race_id":rid,"source":"same_race_board_state","status":"measurement_only",
        "interaction_features":build_interaction_features(boats),
        "race_context_features":build_race_context_features(boats,weather),
        "venue_environment":build_environment_features(jcd,weather,race.get("environment") or {}),
    }

def seed_today(con,now,cache_dir="cache/live",selected_jcds=None):
    date=now.date().isoformat()
    if selected_jcds: venues=[{"jcd":str(j).zfill(2),"venue":VENUES.get(str(j).zfill(2),str(j).zfill(2))} for j in selected_jcds]
    else: venues,_=discover_today(date,cache_dir)
    ok=[];err=[]
    for v in venues:
        jcd=v["jcd"]
        try:
            cnt=con.execute("SELECT COUNT(*) FROM races WHERE race_date=? AND jcd=? AND deadline IS NOT NULL",(date,jcd)).fetchone()[0]
            need_seed=(cnt==0) if selected_jcds else (cnt<12)
            if need_seed: seed_venue_races(con,date,jcd,cache_dir)
            ok.append(v)
        except Exception as e: err.append({"jcd":jcd,"venue":v["venue"],"error":str(e)})
    return ok,err

def refresh_for_iphone(con,now=None,max_races=8,horizon_min=90,cache_dir="cache/live",progress=None,selected_jcds=None):
    now=now or datetime.now(JST)
    def report(stage,**extra):
        if progress:
            try: progress(stage,extra)
            except Exception: pass
    report("discovering"); seeded,venue_errors=seed_today(con,now,cache_dir,selected_jcds); report("seeded",venues_found=len(seeded))
    today=now.date().isoformat()
    rows=con.execute("SELECT race_id,jcd,race_no,deadline FROM races WHERE race_date=? AND deadline IS NOT NULL ORDER BY deadline,jcd,race_no",(today,)).fetchall()
    if selected_jcds:
        allowed={str(j).zfill(2) for j in selected_jcds}; rows=[row for row in rows if str(row[1]).zfill(2) in allowed]
    cand=[];fallback=[]
    for rid,jcd,rno,dl in rows:
        try: m=mins_to_deadline(now,dl)
        except Exception: continue
        if 0<=m<=240:
            fallback.append((m,rid,jcd,rno))
            if m<=horizon_min: cand.append((m,rid,jcd,rno))
    selected=[row for row in cand if row[0]<=60] if selected_jcds else (cand[:max_races] if cand else fallback[:min(4,max_races)])
    updates=[]; report("selected",races_total=len(selected),venues_requested=len(selected_jcds or []),venues_found=len(seeded))
    for idx,(mins,rid,jcd,rno) in enumerate(selected,start=1):
        report("race_start",race_index=idx,races_total=len(selected),jcd=jcd,race_no=rno)
        item={"race_id":rid,"jcd":jcd,"race_no":rno,"minutes":round(mins,1)}
        try:
            entry_count=con.execute("SELECT COUNT(*) FROM entries WHERE race_id=?",(rid,)).fetchone()[0]
            if entry_count>=6: item["racelist"]={"cached":True,"entries":entry_count}; mark(con,rid,"racelist_ok",True)
            else: item["racelist"]=refresh_racelist(con,today,jcd,rno,cache_dir); mark(con,rid,"racelist_ok",True)
        except Exception as e: item["racelist_error"]=str(e); mark(con,rid,"racelist_ok",False,str(e))
        try: item["beforeinfo"]=refresh_beforeinfo_v13(con,today,jcd,rno,cache_dir); mark(con,rid,"beforeinfo_ok",True)
        except Exception as e: item["beforeinfo_error"]=str(e); mark(con,rid,"beforeinfo_ok",False,str(e))
        try: item["odds"]=refresh_odds(con,today,jcd,rno,cache_dir)
        except Exception as e: item["odds_error"]=str(e)
        try:
            ev=evaluate_race(con,rid); item["ev"]={"status":ev.get("status"),"model":ev.get("model"),"provisional_model":True,"bets":ev.get("bets",[]),"odds_captured_at":ev.get("odds_captured_at"),"rows":ev.get("rows",[])}
        except Exception as e: item["ev"]={"status":"error","provisional_model":True,"error":str(e),"bets":[]}
        item["quality"]=status(con,rid); updates.append(item); report("race_done",race_index=idx,races_total=len(selected),jcd=jcd,race_no=rno)
    report("building_board"); board=build_board(con,now)
    for r in board:
        q=status(con,r["race_id"]); r["quality"]=q; r["data_ready"]=q["racelist_ok"]
    for item in updates:
        try:
            trace=_full_trace_from_board(board,item["race_id"],item["jcd"]); item["feature_trace"]=trace
            payload={"race_id":item["race_id"],"captured_before_deadline":True,"minutes_to_deadline":item["minutes"],"provisional_model":True,"features":trace,"ev":item.get("ev",{}),"quality":item.get("quality",{})}
            item["trace_saved"]=save_snapshot(con,item["race_id"],"latest_predeadline",payload,immutable=False)
            # Freeze only when real odds/EV are present; never freeze a PRE/incomplete state merely because time is short.
            ev=item.get("ev") or {}; has_odds=bool(ev.get("odds_captured_at")); has_rows=bool(ev.get("rows"))
            if item["minutes"]<=10 and has_odds and has_rows:
                item["final_predeadline_frozen"]=freeze_predeadline(con,item["race_id"],payload)
            else: item["final_predeadline_frozen"]={"saved":False,"reason":"not_final_ready"}
        except Exception as e: item["trace_error"]=str(e)
    report("done",races_updated=len(updates),venues_found=len(seeded))
    return {"generated_at":now.isoformat(),"settlement":{"skipped_for_speed":True},"plans_saved":0,"actual_stats":cumulative_actual_stats(con),"stats_today":stats(con,today),"stats_all":stats(con),"venues_found":len(seeded),"selected_jcds":[str(j).zfill(2) for j in selected_jcds] if selected_jcds else [v["jcd"] for v in seeded],"venue_errors":venue_errors,"races_updated":len(updates),"refresh_scope":"selected_venue_60min" if selected_jcds else ("normal" if cand else ("nearest" if selected else "none")),"updates":updates,"board":board}
