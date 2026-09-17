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

JST=ZoneInfo("Asia/Tokyo")

def mins_to_deadline(now,deadline):
    hh,mm=map(int,deadline[:5].split(":"))
    dl=now.replace(hour=hh,minute=mm,second=0,microsecond=0)
    return (dl-now).total_seconds()/60

def seed_today(con,now,cache_dir="cache/live",selected_jcds=None):
    date=now.date().isoformat()
    if selected_jcds:
        venues=[{"jcd":str(j).zfill(2),"venue":VENUES.get(str(j).zfill(2),str(j).zfill(2))} for j in selected_jcds]
    else:
        venues,_=discover_today(date,cache_dir)
    ok=[];err=[]
    for v in venues:
        jcd=v["jcd"]
        try:
            cnt=con.execute("SELECT COUNT(*) FROM races WHERE race_date=? AND jcd=? AND deadline IS NOT NULL",(date,jcd)).fetchone()[0]
            need_seed=(cnt==0) if selected_jcds else (cnt<12)
            if need_seed: seed_venue_races(con,date,jcd,cache_dir)
            ok.append(v)
        except Exception as e:
            err.append({"jcd":jcd,"venue":v["venue"],"error":str(e)})
    return ok,err

def refresh_for_iphone(con,now=None,max_races=8,horizon_min=90,cache_dir="cache/live",progress=None,selected_jcds=None):
    now=now or datetime.now(JST)
    def report(stage,**extra):
        if progress:
            try: progress(stage,extra)
            except Exception: pass
    report("discovering")
    seeded,venue_errors=seed_today(con,now,cache_dir,selected_jcds)
    report("seeded",venues_found=len(seeded))
    today=now.date().isoformat()
    rows=con.execute("SELECT race_id,jcd,race_no,deadline FROM races WHERE race_date=? AND deadline IS NOT NULL ORDER BY deadline,jcd,race_no",(today,)).fetchall()
    if selected_jcds:
        one=str(selected_jcds[0]).zfill(2)
        rows=[row for row in rows if str(row[1]).zfill(2)==one]
    cand=[];fallback=[]
    for rid,jcd,rno,dl in rows:
        try: m=mins_to_deadline(now,dl)
        except Exception: continue
        if 0<=m<=240:
            fallback.append((m,rid,jcd,rno))
            if m<=horizon_min: cand.append((m,rid,jcd,rno))
    if selected_jcds:
        selected=[row for row in cand if row[0]<=60]
    else:
        selected=cand[:max_races] if cand else fallback[:min(4,max_races)]
    updates=[]
    report("selected",races_total=len(selected),venues_requested=len(selected_jcds or []),venues_found=len(seeded))
    for idx,(mins,rid,jcd,rno) in enumerate(selected,start=1):
        report("race_start",race_index=idx,races_total=len(selected),jcd=jcd,race_no=rno)
        item={"race_id":rid,"jcd":jcd,"race_no":rno,"minutes":round(mins,1)}
        try:
            entry_count=con.execute("SELECT COUNT(*) FROM entries WHERE race_id=?",(rid,)).fetchone()[0]
            if entry_count>=6:
                item["racelist"]={"cached":True,"entries":entry_count}; mark(con,rid,"racelist_ok",True)
            else:
                item["racelist"]=refresh_racelist(con,today,jcd,rno,cache_dir); mark(con,rid,"racelist_ok",True)
        except Exception as e:
            item["racelist_error"]=str(e); mark(con,rid,"racelist_ok",False,str(e))
        try:
            item["beforeinfo"]=refresh_beforeinfo_v13(con,today,jcd,rno,cache_dir); mark(con,rid,"beforeinfo_ok",True)
        except Exception as e:
            item["beforeinfo_error"]=str(e); mark(con,rid,"beforeinfo_ok",False,str(e))
        try:
            item["odds"]=refresh_odds(con,today,jcd,rno,cache_dir)
        except Exception as e:
            item["odds_error"]=str(e)
        try:
            ev=evaluate_race(con,rid)
            item["ev"]={"status":ev.get("status"),"model":ev.get("model"),"provisional_model":True,"bets":ev.get("bets",[]),"odds_captured_at":ev.get("odds_captured_at")}
        except Exception as e:
            item["ev"]={"status":"error","provisional_model":True,"error":str(e),"bets":[]}
        item["quality"]=status(con,rid); updates.append(item)
        report("race_done",race_index=idx,races_total=len(selected),jcd=jcd,race_no=rno)
    report("building_board")
    board=build_board(con,now)
    for r in board:
        q=status(con,r["race_id"]); r["quality"]=q; r["data_ready"]=q["racelist_ok"]
    report("done",races_updated=len(updates),venues_found=len(seeded))
    return {"generated_at":now.isoformat(),"settlement":{"skipped_for_speed":True},"plans_saved":0,"stats_today":stats(con,today),"stats_all":stats(con),"venues_found":len(seeded),"selected_jcds":[str(selected_jcds[0]).zfill(2)] if selected_jcds else [v["jcd"] for v in seeded],"venue_errors":venue_errors,"races_updated":len(updates),"refresh_scope":"selected_venue_60min" if selected_jcds else ("normal" if cand else ("nearest" if selected else "none")),"updates":updates,"board":board}
