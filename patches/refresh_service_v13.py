from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
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

def _evaluate_one(con,now,today,mins,rid,jcd,rno,cache_dir,progress=None):
    item={'race_id':rid,'jcd':jcd,'race_no':rno,'minutes':round(mins,1)}
    # FIXED SPEC: racelist/entries are PREP data. Never fetch them from the
    # user-facing Update button. If prep is absent, fail fast instead of hiding
    # a 10-15 second network request inside refresh.
    ec=con.execute('SELECT COUNT(*) FROM entries WHERE race_id=?',(rid,)).fetchone()[0]
    if ec<6:
        item['ev']={'status':'predata_not_ready','provisional_model':True,'bets':[],'rows':[]}
        item['quality']=status(con,rid)
        item['predata_not_ready']=True
        return item
    mark(con,rid,'racelist_ok',True)
    # Live delta: exhibition/entry/weather/water immediately before prediction.
    if mins<=40:
        try: item['beforeinfo']=refresh_beforeinfo_v13(con,today,jcd,rno,cache_dir); mark(con,rid,'beforeinfo_ok',True)
        except Exception as e: item['beforeinfo_error']=str(e); mark(con,rid,'beforeinfo_ok',False,str(e))
    # Latest odds are for EV, not an input to the prediction model.
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
    now=now or datetime.now(JST); today=now.date().isoformat()
    def report(stage,**extra):
        if progress:
            try: progress(stage,extra)
            except Exception: pass
    # FIXED SPEC: no daily-index discovery and no race seeding here.
    # Those belong to prep/background. Update must use already-prepared DB state.
    report('prepared_state')
    rows=con.execute('SELECT race_id,jcd,race_no,deadline FROM races WHERE race_date=? AND deadline IS NOT NULL ORDER BY deadline,jcd,race_no',(today,)).fetchall()
    allowed={str(j).zfill(2) for j in selected_jcds or []}; cand=[]
    for rid,jcd,rno,dl in rows:
        if allowed and str(jcd).zfill(2) not in allowed: continue
        try: m=mins_to_deadline(now,dl)
        except Exception: continue
        if m>0: cand.append((m,rid,jcd,rno))
    selected=cand[:1]; updates=[]
    report('selected',races_total=len(selected),venues_requested=len(allowed))
    if selected:
        mins,rid,jcd,rno=selected[0]
        report('race_start',race_index=1,races_total=1,jcd=jcd,race_no=rno)
        updates.append(_evaluate_one(con,now,today,mins,rid,jcd,rno,cache_dir,progress))
        report('race_done',race_index=1,races_total=1,jcd=jcd,race_no=rno)
    board=build_board(con,datetime.now(JST)); report('done',races_updated=len(updates))
    return {'generated_at':datetime.now(JST).isoformat(),'settlement':{'skipped_for_speed':True},'actual_stats':cumulative_actual_stats(con),'stats_today':stats(con,today),'stats_all':stats(con),'selected_jcds':list(allowed),'races_updated':len(updates),'refresh_scope':'live_delta_next_race_only','updates':updates,'board':board}
