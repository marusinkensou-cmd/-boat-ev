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
from race_trace_v01 import save_snapshot, freeze_predeadline, cumulative_actual_stats
JST=ZoneInfo('Asia/Tokyo')
def mins_to_deadline(now,deadline):
    hh,mm=map(int,deadline[:5].split(':')); dl=now.replace(hour=hh,minute=mm,second=0,microsecond=0); return (dl-now).total_seconds()/60
def seed_today(con,now,cache_dir='cache/live',selected_jcds=None):
    date=now.date().isoformat(); venues=[{'jcd':str(j).zfill(2),'venue':VENUES.get(str(j).zfill(2),str(j).zfill(2))} for j in selected_jcds] if selected_jcds else discover_today(date,cache_dir)[0]; ok=[];err=[]
    for v in venues:
        try:
            j=v['jcd']; cnt=con.execute('SELECT COUNT(*) FROM races WHERE race_date=? AND jcd=? AND deadline IS NOT NULL',(date,j)).fetchone()[0]
            if cnt==0: seed_venue_races(con,date,j,cache_dir)
            ok.append(v)
        except Exception as e: err.append({'jcd':v['jcd'],'error':str(e)})
    return ok,err
def _evaluate_one(con,now,today,mins,rid,jcd,rno,cache_dir,progress=None):
    item={'race_id':rid,'jcd':jcd,'race_no':rno,'minutes':round(mins,1)}
    try:
        ec=con.execute('SELECT COUNT(*) FROM entries WHERE race_id=?',(rid,)).fetchone()[0]
        if ec<6: refresh_racelist(con,today,jcd,rno,cache_dir)
        mark(con,rid,'racelist_ok',True)
    except Exception as e: mark(con,rid,'racelist_ok',False,str(e)); item['racelist_error']=str(e)
    if mins<=40:
        try: item['beforeinfo']=refresh_beforeinfo_v13(con,today,jcd,rno,cache_dir); mark(con,rid,'beforeinfo_ok',True)
        except Exception as e: item['beforeinfo_error']=str(e); mark(con,rid,'beforeinfo_ok',False,str(e))
    try: item['odds']=refresh_odds(con,today,jcd,rno,cache_dir)
    except Exception as e: item['odds_error']=str(e)
    try:
        ev=evaluate_race(con,rid); item['ev']={'status':ev.get('status'),'model':ev.get('model'),'provisional_model':True,'bets':ev.get('bets',[]),'odds_captured_at':ev.get('odds_captured_at'),'rows':ev.get('rows',[])}
    except Exception as e: item['ev']={'status':'error','provisional_model':True,'error':str(e),'bets':[],'rows':[]}
    item['quality']=status(con,rid)
    try:
        payload={'race_id':rid,'captured_before_deadline':True,'minutes_to_deadline':round(mins,1),'provisional_model':True,'ev':item['ev'],'quality':item['quality']}
        item['trace_saved']=save_snapshot(con,rid,'latest_predeadline',payload,immutable=False)
        if mins<=10 and item['ev'].get('odds_captured_at') and item['ev'].get('rows'): item['final_predeadline_frozen']=freeze_predeadline(con,rid,payload)
    except Exception as e: item['trace_error']=str(e)
    return item
def refresh_for_iphone(con,now=None,max_races=1,horizon_min=90,cache_dir='cache/live',progress=None,selected_jcds=None):
    now=now or datetime.now(JST)
    def report(stage,**extra):
        if progress:
            try: progress(stage,extra)
            except Exception: pass
    report('discovering'); seeded,venue_errors=seed_today(con,now,cache_dir,selected_jcds); today=now.date().isoformat()
    rows=con.execute('SELECT race_id,jcd,race_no,deadline FROM races WHERE race_date=? AND deadline IS NOT NULL ORDER BY deadline,jcd,race_no',(today,)).fetchall()
    allowed={str(j).zfill(2) for j in selected_jcds or []}; cand=[]
    for rid,jcd,rno,dl in rows:
        if allowed and str(jcd).zfill(2) not in allowed: continue
        try: m=mins_to_deadline(now,dl)
        except Exception: continue
        if m>0: cand.append((m,rid,jcd,rno))
    # User-facing refresh is deliberately ONLY the nearest remaining race.
    # The next-next race must never delay the prediction the user needs now.
    selected=cand[:1]
    updates=[]; report('selected',races_total=len(selected),venues_requested=len(allowed),venues_found=len(seeded))
    if selected:
        mins,rid,jcd,rno=selected[0]
        report('race_start',race_index=1,races_total=1,jcd=jcd,race_no=rno)
        item=_evaluate_one(con,now,today,mins,rid,jcd,rno,cache_dir,progress)
        updates.append(item); report('race_done',race_index=1,races_total=1,jcd=jcd,race_no=rno)
    board=build_board(con,datetime.now(JST)); report('done',races_updated=len(updates),venues_found=len(seeded))
    return {'generated_at':datetime.now(JST).isoformat(),'settlement':{'skipped_for_speed':True},'actual_stats':cumulative_actual_stats(con),'stats_today':stats(con,today),'stats_all':stats(con),'venues_found':len(seeded),'selected_jcds':list(allowed),'venue_errors':venue_errors,'races_updated':len(updates),'refresh_scope':'selected_venue_next_race_only','updates':updates,'board':board}
