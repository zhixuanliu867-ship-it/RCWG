from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=Path(__file__).resolve().parents[1]
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'pdf.fonttype':42,'svg.fonttype':'none'})
names=['WorFBench','FlowBench / FlowMind','AgentBoard','AppWorld','ClawArena-Team','OrchBench','WELD']
cols=['Executed\noutcome','Native\nwork vector','Work–time\npairing','Relevant\nupdates','Valid-prefix\nupdate cost']
vals=[[.5,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,1,0],[.5,.5,.5,0,0],[1,1,1,1,1]]
fig,ax=plt.subplots(figsize=(10.1,3.8));ax.set(xlim=(0,10.5),ylim=(-1.2,8.3));ax.axis('off')
ax.plot([.05,10.45],[7.5,7.5],c='black',lw=1)
for j,c in enumerate(cols):ax.text(3.5+j*1.5,7.9,c,ha='center',va='center',fontsize=9,weight='bold')
for i,(n,row) in enumerate(zip(names,vals)):
 y=7-i
 if n=='WELD':ax.axhspan(y-.45,y+.45,color='#e9f0f8');ax.plot([.05,10.45],[y+.47,y+.47],color='#386cb0',lw=1)
 ax.text(.12,y,n,va='center',weight='bold' if n=='WELD' else 'normal')
 for j,v in enumerate(row):
  x=3.5+j*1.5
  if v==1:ax.text(x,y,'✓',va='center',ha='center',fontsize=15,color='#245b57')
  elif v==.5:ax.text(x,y,'◐',va='center',ha='center',fontsize=14,color='#6c7978')
  else:ax.text(x,y,'—',va='center',ha='center',fontsize=11,color='#9a9a9a')
ax.plot([.05,10.45],[.5,.5],c='black',lw=1)
ax.text(.1,-.02,'✓ Direct coverage     ◐ Related measurement in a different domain     — Not separately reported',fontsize=9)
ax.text(.1,-.55,'Columns use WELD operational definitions. Simulation, downstream timing, and usage-only analyses are distinguished.',fontsize=8)
fig.tight_layout(pad=.4)
for ext in ['svg','pdf','png']:fig.savefig(R/'figures'/f'figure_6_coverage.{ext}',dpi=220,bbox_inches='tight')
