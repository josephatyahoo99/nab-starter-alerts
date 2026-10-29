import csv, json, math, os, datetime as dt, collections
HERE=os.path.dirname(os.path.abspath(__file__))
# team: (city, name, lat, lon, utc offset std (ET=-5), elevation ft)
TEAMS = {
'ATL':('Atlanta','Hawks',33.757,-84.396,-5,1050),'BOS':('Boston','Celtics',42.366,-71.062,-5,20),
'BKN':('Brooklyn','Nets',40.683,-73.976,-5,30),'CHA':('Charlotte','Hornets',35.225,-80.839,-5,750),
'CHI':('Chicago','Bulls',41.881,-87.674,-6,600),'CLE':('Cleveland','Cavaliers',41.497,-81.688,-5,650),
'DAL':('Dallas','Mavericks',32.790,-96.810,-6,430),'DEN':('Denver','Nuggets',39.749,-105.008,-7,5280),
'DET':('Detroit','Pistons',42.341,-83.055,-5,600),'GSW':('San Francisco','Warriors',37.768,-122.388,-8,10),
'HOU':('Houston','Rockets',29.751,-95.362,-6,50),'IND':('Indianapolis','Pacers',39.764,-86.156,-5,715),
'LAC':('Los Angeles','Clippers',33.945,-118.341,-8,100),'LAL':('Los Angeles','Lakers',34.043,-118.267,-8,300),
'MEM':('Memphis','Grizzlies',35.138,-90.051,-6,340),'MIA':('Miami','Heat',25.781,-80.188,-5,10),
'MIL':('Milwaukee','Bucks',43.045,-87.917,-6,620),'MIN':('Minneapolis','Timberwolves',44.979,-93.276,-6,830),
'NOP':('New Orleans','Pelicans',29.949,-90.082,-6,10),'NYK':('New York','Knicks',40.751,-73.993,-5,30),
'OKC':('Oklahoma City','Thunder',35.463,-97.515,-6,1200),'ORL':('Orlando','Magic',28.539,-81.384,-5,100),
'PHI':('Philadelphia','76ers',39.901,-75.172,-5,40),'PHX':('Phoenix','Suns',33.446,-112.071,-7,1100),
'POR':('Portland','Trail Blazers',45.532,-122.667,-8,50),'SAC':('Sacramento','Kings',38.580,-121.500,-8,30),
'SAS':('San Antonio','Spurs',29.427,-98.438,-6,650),'TOR':('Toronto','Raptors',43.643,-79.379,-5,250),
'UTA':('Salt Lake City','Jazz',40.768,-111.901,-7,4226),'WAS':('Washington','Wizards',38.898,-77.021,-5,50),
}
def miles(a,b):
    la1,lo1,la2,lo2=map(math.radians,(TEAMS[a][2],TEAMS[a][3],TEAMS[b][2],TEAMS[b][3]))
    h=math.sin((la2-la1)/2)**2+math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 3959*2*math.asin(math.sqrt(h))
def t24(s):
    s=s.strip()
    if not s: return ''
    if 'M' in s:
        hm,ap=s.split(); h,m=map(int,hm.split(':'))
        if ap=='PM' and h!=12: h+=12
        if ap=='AM' and h==12: h=0
        return f'{h:02d}:{m:02d}'
    return s
games=[]
for i,(d,a,h,t) in enumerate(sorted(csv.reader(open(os.path.join(HERE,'schedule-2026-27.csv'))), key=lambda r:(r[0],t24(r[3]) or '99'))):
    games.append(dict(id=i,date=d,away=a,home=h,time=t24(t)))
D=lambda s: dt.date.fromisoformat(s)
byteam=collections.defaultdict(list)
for g in games:
    byteam[g['away']].append(g); byteam[g['home']].append(g)

# per-team per-game fatigue
fat={}  # (gid,team)->dict
for t,gl in byteam.items():
    gl.sort(key=lambda g:g['date'])
    trip=0
    for i,g in enumerate(gl):
        d=D(g['date']); away = g['away']==t
        loc=g['home']
        prev=gl[i-1] if i else None
        prevloc=prev['home'] if prev else t
        rest=(d-D(prev['date'])).days-1 if prev else 9
        trip = trip+1 if away else 0
        dates=[D(x['date']) for x in gl[:i+1]]
        in4=sum(1 for x in dates if (d-x).days<4)
        in6=sum(1 for x in dates if (d-x).days<6)
        in7=sum(1 for x in dates if (d-x).days<7)
        dist=miles(prevloc,loc) if prevloc!=loc else 0
        tzshift=TEAMS[loc][4]-TEAMS[prevloc][4]  # +ve = flew east
        # rolling 7-day travel
        win=[x for x in gl[max(0,i-6):i+1] if (d-D(x['date'])).days<7]
        trav7=0
        for j in range(1,len(win)): trav7+=miles(win[j-1]['home'],win[j]['home'])
        if win and win[0] is not gl[0]:
            k=gl.index(win[0]); trav7+=miles(gl[k-1]['home'],win[0]['home'])
        pts=0; why=[]
        if rest==0:
            pts+=3; why.append('2nd night of a back-to-back')
            if away and prev['away']==t: pts+=1; why.append('both B2B games on the road')
            if dist>500: pts+=1; why.append(f'flew {dist:,.0f} mi overnight')
        if in4>=3: pts+=2; why.append(f'{in4} games in 4 nights')
        if in6>=4: pts+=1; why.append(f'{in6} games in 6 nights')
        if in7>=5: pts+=2; why.append(f'{in7} games in 7 nights')
        if trip>=4: pts+=1; why.append(f'game {trip} of a road trip')
        if trip>=6: pts+=1
        if dist>=1500 and rest<=1: pts+=1; why.append(f'long flight ({dist:,.0f} mi) on short rest')
        if tzshift>=2 and rest<=1: pts+=1; why.append(f'body clock: {tzshift} time zones east')
        if trav7>=4000: pts+=1; why.append(f'{trav7:,.0f} mi traveled this week')
        if away and loc in ('DEN','UTA'):
            p=2 if rest==0 else 1; pts+=p; why.append(f'altitude in {TEAMS[loc][0]} ({TEAMS[loc][5]:,} ft)')
        fat[(g['id'],t)]=dict(pts=pts,why=why,rest=rest,trip=trip,in4=in4,in6=in6,dist=round(dist),away=away)

out=[]; tiers=collections.Counter()
for g in games:
    fa=fat[(g['id'],g['away'])]; fh=fat[(g['id'],g['home'])]
    rec=dict(g); rec['af']=fa; rec['hf']=fh
    # who is the fade candidate
    best=None
    for side,me,op,opn in (('away',fa,fh,g['home']),('home',fh,fa,g['away'])):
        edge=me['pts']-op['pts']
        if me['rest']==0 and op['rest']>=1: edge+=1  # rest disadvantage
        if me['rest']==0 and op['rest']>=2: edge+=1
        if best is None or edge>best[1]: best=(side,edge)
    side,edge=best
    team=g[side]; me=rec['af' if side=='away' else 'hf']
    tier = 'strong' if (edge>=8 and me['pts']>=8) else 'lean' if (edge>=5 and me['pts']>=5) else None
    rec['fade']=dict(team=team,edge=edge,tier=tier) if tier else None
    tiers[tier]+=1
    out.append(rec)
print(tiers)
json.dump(dict(teams={k:dict(city=v[0],name=v[1],tz=v[4],elev=v[5]) for k,v in TEAMS.items()},games=out),open(os.path.join(HERE,'data.json'),'w'))
# summaries
import statistics
print('top spots:')
for r in sorted([r for r in out if r['fade'] and r['fade']['tier']=='strong'],key=lambda r:-r['fade']['edge'])[:15]:
    f=r['af'] if r['fade']['team']==r['away'] else r['hf']
    print(r['date'],r['away'],'@',r['home'],'fade',r['fade']['team'],r['fade']['edge'],f['why'])
c=collections.Counter(r['fade']['team'] for r in out if r['fade'])
print(c.most_common(30))

# Compact lookup used by the alert emails: "YYYY-MM-DD AWAY HOME" -> scores
lookup={}
for r in out:
    lookup[f"{r['date']} {r['away']} {r['home']}"]=dict(
        fade=r['fade'], away=dict(pts=r['af']['pts'],why=r['af']['why']), home=dict(pts=r['hf']['pts'],why=r['hf']['why']))
json.dump(lookup,open(os.path.join(HERE,'fade.json'),'w'),separators=(',',':'))
os.remove(os.path.join(HERE,'data.json'))
